"""Invariant: coherencia outbound vs tools de write ejecutados.

Rev. 107 — bug runtime conducción KAIU turno A (conv 6b367d8f):
Cliente pidió re-generar link expirado. El LLM emitió OUTBOUND con dos
intents incompatibles en el mismo mensaje:

  «¿Confirmas que los datos están correctos para generar tu link de pago?
   ...
   Listo, Cristian! Aquí tienes un nuevo link de pago...
   https://checkout.wompi.co/l/test_sj9wWb»

Y simultáneamente ejecutó `generate_payment_link(ok=True)`. UX confuso:
el cliente lee primero "¿confirmas?" + abajo "aquí está el link" — no
sabe si tiene que responder Sí o si ya está hecho.

Causa raíz: el LLM compuso un texto que mezcla la INTENCIÓN previa
("voy a generar el link, ¿confirmas?") con el RESULTADO posterior
("aquí está el link"). Sin guardrail, este pattern se replicará.

Diseño del invariant:
  • Detecta outbound con pregunta de confirmación ("¿confirmas?",
    "¿proceder?", "¿de acuerdo?", "¿genero el link?") EN PRESENCIA de un
    tool de write ejecutado con éxito en el mismo turn (add_to_cart,
    generate_payment_link, record_consent, save_*, select_carrier).
  • REWRITE: elimina la pregunta de confirmación, deja solo el texto
    post-fact (la parte que afirma lo que ya pasó).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# Tools de write donde una pregunta de confirmación post-acción es
# REDUNDANTE — el flow ya terminó:
#   • generate_payment_link → ya generó link, "¿confirmas el pedido?"
#     sobra (el cliente confirma pagando el link).
#   • escalate_to_human → ya escaló, "¿confirmas escalar?" no aplica.
#
# Para los demás writes (add_to_cart, save_*, select_carrier,
# record_consent) la pregunta siguiente suele ser legítima next step
# del flow (e.g. "guardé tu nombre. ¿Confirmas tu email?" es válido —
# save_name no implica que el pedido está completo).
# Rev. 107 — bug runtime KAIU ff228be7: el invariant cortaba preguntas
# legítimas post-save_email; ahora SOLO dispara con write tools terminales.
_WRITE_TOOLS = {
    "generate_payment_link",
    "escalate_to_human",
}

# Patrones de pregunta de confirmación pre-acción (REDUNDANTE — la
# acción ya se ejecutó). Rev. 107 refinado:
#   • "Confirmas EL pedido / LOS datos / EL envío" — confirma acción ya
#     hecha → REDUNDANTE, quitar.
#   • "Confirmas TU nombre / TU email / TU dirección" — pide al cliente
#     DECLARAR su data → LEGÍTIMO, NO quitar (es next step del flow).
# La distinción es artículo definido (el/los/la) vs posesivo (tu/su).
_CONFIRMATION_QUESTION_PATTERNS = (
    # "Confirmas EL pedido / LOS datos / LA dirección / EL link / etc."
    # — la acción ya pasó, NO necesita confirmación del cliente.
    re.compile(
        r"\bconfirmas?\b\s+(?:que\s+)?(?:el|los|la|las)\s+"
        r"(?:pedido|datos|env[ií]o|carrito|orden|direcci[oó]n|link|"
        r"items?|productos?|presentaci[oó]n|elecci[oó]n)\b[^?]*\?",
        re.IGNORECASE,
    ),
    # "¿Procedemos / procedo / a proceder?" — bot ya procedió.
    re.compile(r"\bproced(?:o|emos|er)\b[^?]*\?", re.IGNORECASE),
    # "¿Genero el link?" — bot ya lo generó.
    re.compile(r"\bgenero(?:\s+el)?\s+link\b[^?]*\?", re.IGNORECASE),
    # "¿Estás de acuerdo / estamos de acuerdo?" sobre acción ya hecha.
    re.compile(r"\b(?:est[aá]s?|estamos)\s+de\s+acuerdo\b[^?]*\?", re.IGNORECASE),
    # "¿Te parece bien?" post-acción.
    re.compile(r"\bte\s+parece\b[^?]*\?", re.IGNORECASE),
)


def _has_successful_write_tool(tool_call_log: list[dict]) -> Optional[str]:
    """Retorna el nombre del primer write tool exitoso, o None."""
    for call in tool_call_log or []:
        if call.get("tool") not in _WRITE_TOOLS:
            continue
        if "error" not in (call.get("result") or {}):
            return call["tool"]
    return None


def _has_confirmation_question(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _CONFIRMATION_QUESTION_PATTERNS)


def _strip_confirmation_question(text: str) -> str:
    """Elimina la oración de confirmación del texto y limpia separadores
    huérfanos. Si la pregunta era la única oración del bloque, retorna
    el resto sin doble salto.
    """
    if not text:
        return text
    result = text
    for pat in _CONFIRMATION_QUESTION_PATTERNS:
        result = pat.sub("", result)
    # Limpiar saltos múltiples (3+) que quedan al borrar la pregunta.
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


class PostToolCoherenceInvariant:
    """Si el outbound contiene pregunta de confirmación + un write tool
    ya se ejecutó con éxito en el mismo turn → REWRITE eliminando la
    pregunta (mantener solo el resultado factual)."""

    name = "post_tool_coherence"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
    ) -> InvariantResult:
        write_tool = _has_successful_write_tool(tool_call_log)
        if not write_tool:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        if not _has_confirmation_question(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        cleaned = _strip_confirmation_question(candidate_text)
        if not cleaned or cleaned == candidate_text:
            # Sin diferencia útil — OK pero anotamos reason.
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="strip produjo cleaning vacío o idéntico",
            )

        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=cleaned,
            reason=(
                f"outbound contiene pregunta de confirmación + write tool "
                f"`{write_tool}` ya ejecutado → eliminando pregunta redundante."
            ),
        )

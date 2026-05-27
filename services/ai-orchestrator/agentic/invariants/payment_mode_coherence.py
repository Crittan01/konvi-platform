"""Invariant: coherencia LENGUAJE outbound vs cart.payment_method.

Rev. 108 holístico — founder feedback 2026-05-26:
  Bot dijo "generar el link de pago contra entrega?" — TOTALMENTE
  CONTRADICTORIO. "link de pago" implica Wompi (credit), "contra entrega"
  implica COD (sin link). El LLM mezcló términos.

Causa raíz arquitectónica:
  El LLM compone el resumen final libremente (no usa
  `_build_order_summary_text` determinístico siempre). En cart con
  payment_method='cod', el LLM aún arrastra patrones del prompt sobre
  "link de pago" (default credit path) y produce frases mezcladas.

Solución:
  Invariant DETERMINÍSTICO que detecta inconsistencia léxica vs cart
  y REESCRIBE. Defensa en profundidad: el LLM puede equivocarse, pero
  el invariant NUNCA permite enviar texto contradictorio al cliente.

Reglas:
  • Si cart.payment_method='cod' AND outbound contiene términos de
    credit ("link de pago", "checkout", "Wompi", "paga aquí", "pagar
    ahora", "pagar online") → REWRITE.
  • Si cart.payment_method='credit' AND outbound dice explícitamente
    "contraentrega" o "pago al recibir" COMO modo principal → REWRITE
    (caso menos común; el LLM raramente hallucina COD si cart=credit).

Coordinación con otros invariants:
  • payment_method_explicit (existente): asegura cliente especifica modo
    ANTES de quote/payment-action. Este invariant es el siguiente eslabón:
    asegura coherencia léxica DESPUÉS de que modo está establecido.

NO machetazos — patrón espejo de `summary_coherence`, `cart_state`,
`payment_method_explicit`: detección + rewrite, NO branching condicional
del LLM.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# Términos que el LLM usa SOLO en credit flow (Wompi link).
# Match insensible mayúsculas; conservador para no falso-positivo.
_CREDIT_LANGUAGE_PATTERNS = (
    re.compile(r"\blink\s+de\s+pago\b", re.IGNORECASE),
    re.compile(r"\bcheckout(?:\.wompi)?\b", re.IGNORECASE),
    re.compile(r"\bpaga(?:r)?\s+(?:aqu[ií]|ahora|en\s+l[ií]nea|online)\b", re.IGNORECASE),
    re.compile(r"\bwompi\b", re.IGNORECASE),
    re.compile(r"\bgenerar(?:te)?\s+(?:el\s+)?link\b", re.IGNORECASE),
    re.compile(r"\benviar(?:te)?\s+(?:el\s+)?link\b", re.IGNORECASE),
)

# Términos que el LLM usa SOLO en COD flow.
_COD_LANGUAGE_PATTERNS = (
    re.compile(r"\bcontra[\s\-]?entrega\b", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+(?:al|cuando|en\s+el\s+momento\s+de)\s+(?:recibi|lleg|entrega)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+en\s+efectivo\s+(?:al\s+)?(?:recibi|lleg)", re.IGNORECASE),
    re.compile(r"\bcod\b", re.IGNORECASE),
)


def _has_credit_language(text: str) -> bool:
    return any(p.search(text or "") for p in _CREDIT_LANGUAGE_PATTERNS)


def _has_cod_language(text: str) -> bool:
    return any(p.search(text or "") for p in _COD_LANGUAGE_PATTERNS)


def _build_cod_replacement(
    candidate_text: str, total_cop: int, carrier: str,
) -> str:
    """Reescribe outbound con lenguaje COD coherente.

    Estrategia: si el outbound original era un resumen, mantén estructura
    pero reemplaza la pregunta final por COD-correcta. Si era una pregunta
    simple, reformúlala.
    """
    # Caso 1: outbound era resumen con "link de pago" → reemplazar la frase.
    if re.search(r"\bgenerar(?:te)?\s+(?:el\s+)?link\s+de\s+pago", candidate_text, re.IGNORECASE):
        # Reemplazar "para generar el link de pago [contra entrega]" →
        # "para procesar tu pedido contraentrega" (gramática natural).
        new = re.sub(
            r"para\s+generar(?:te)?\s+(?:el\s+)?link\s+de\s+pago(?:\s+contra\s*entrega)?",
            "para procesar tu pedido contraentrega",
            candidate_text,
            flags=re.IGNORECASE,
        )
        # Si no había "para" delante, fallback genérico.
        new = re.sub(
            r"generar(?:te)?\s+(?:el\s+)?link\s+de\s+pago(?:\s+contra\s*entrega)?",
            "procesar tu pedido contraentrega",
            new,
            flags=re.IGNORECASE,
        )
        return new

    if re.search(r"\blink\s+de\s+pago\b", candidate_text, re.IGNORECASE):
        new = re.sub(
            r"(?:el\s+)?link\s+de\s+pago\b",
            "pago contraentrega",
            candidate_text,
            flags=re.IGNORECASE,
        )
        return new

    if re.search(r"\bpaga(?:r)?\s+(?:aqu[ií]|ahora|en\s+l[ií]nea|online)\b", candidate_text, re.IGNORECASE):
        new = re.sub(
            r"\bpaga(?:r)?\s+(?:aqu[ií]|ahora|en\s+l[ií]nea|online)\b",
            "pagas al recibir",
            candidate_text,
            flags=re.IGNORECASE,
        )
        return new

    # Caso 2: outbound era pregunta simple → reformular.
    carrier_part = f" con *{carrier}*" if carrier else ""
    total_fmt = f"${total_cop:,}".replace(",", ".")
    return (
        f"Tu pedido por *{total_fmt} COP* irá contraentrega{carrier_part}.\n"
        f"Pagas en efectivo cuando el courier te entregue el paquete.\n\n"
        f"¿Confirmas tu pedido?"
    )


def _build_credit_replacement(candidate_text: str) -> str:
    """Reescribe outbound con lenguaje credit (Wompi link) coherente."""
    if re.search(r"\bcontra[\s\-]?entrega\b", candidate_text, re.IGNORECASE):
        return re.sub(
            r"\bcontra[\s\-]?entrega\b",
            "pago online",
            candidate_text,
            flags=re.IGNORECASE,
        )
    if re.search(r"\bpag(?:o|ar)\s+al\s+(?:recibi|lleg)", candidate_text, re.IGNORECASE):
        return re.sub(
            r"\bpag(?:o|ar)\s+al\s+(?:recibi|lleg)\w*",
            "pago online",
            candidate_text,
            flags=re.IGNORECASE,
        )
    return candidate_text


class PaymentModeCoherenceInvariant:
    """Defensa léxica: outbound NO puede contradecir cart.payment_method.

    Casos detectados:
      • cart=cod AND outbound tiene "link de pago" / "Wompi" / "paga aquí"
        → REWRITE con lenguaje COD coherente.
      • cart=credit AND outbound dice "contraentrega" como modo
        → REWRITE con lenguaje credit.
    """

    name = "payment_mode_coherence"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
        inbound_text: str = "",
    ) -> InvariantResult:
        if not candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # Leer cart.payment_method (DB-first).
        try:
            cart_q = (
                supabase.table("conversation_carts")
                .select("payment_method, total_cents, shipping_meta")
                .eq("tenant_id", tenant_id)
                .eq("conversation_id", conversation_id)
                .in_("status", ["open", "checkout"])
                .order("created_at", desc=True).limit(1).execute()
            )
            row = (cart_q.data or [{}])[0]
        except Exception:
            row = {}

        cart_payment_method = (row.get("payment_method") or "credit").lower()
        if cart_payment_method not in ("cod", "credit"):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason=f"unknown payment_method={cart_payment_method!r}",
            )

        has_credit_lang = _has_credit_language(candidate_text)
        has_cod_lang = _has_cod_language(candidate_text)

        # Caso 1: cart=cod pero outbound habla de credit → INCOHERENTE.
        if cart_payment_method == "cod" and has_credit_lang:
            total_cop = int(row.get("total_cents") or 0) // 100
            carrier = (
                (row.get("shipping_meta") or {}).get("carrier")
                or ""
            )
            replacement = _build_cod_replacement(
                candidate_text, total_cop, carrier,
            )
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    f"cart.payment_method=cod pero outbound contiene "
                    f"lenguaje credit (link/Wompi/checkout) — rewrite a "
                    f"lenguaje COD coherente."
                ),
            )

        # Caso 2: cart=credit pero outbound habla de COD como modo → INCOHERENTE.
        # Conservador: solo rewrite si COD aparece SIN credit (no mezcla).
        # Si hay ambos, el cart es la fuente de verdad.
        if cart_payment_method == "credit" and has_cod_lang and not has_credit_lang:
            replacement = _build_credit_replacement(candidate_text)
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    f"cart.payment_method=credit pero outbound contiene "
                    f"lenguaje COD ('contraentrega') sin credit — rewrite."
                ),
            )

        return InvariantResult(
            outcome=InvariantOutcome.OK,
            invariant_name=self.name,
            reason=f"outbound coherente con cart.payment_method={cart_payment_method}",
        )

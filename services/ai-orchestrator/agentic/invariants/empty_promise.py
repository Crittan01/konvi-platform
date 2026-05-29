"""Invariant: detecta "promesa vacía" — bot dice "un momento, estoy
calculando/buscando" SIN haber ejecutado el tool correspondiente.

Bug runtime KAIU 2026-05-24 conv eb21c1fc (ROUND-4 live):
  Cliente: "Envíalo a Medellín por favor"
  Bot:     "Claro, Cristian. Un momento por favor, estoy calculando
            el costo de envío a Medellín."
  Real:    tool_calls=0 → cliente queda esperando una cotización que
           NUNCA va a llegar. Inadmisible.

Pattern: Gemini no-determinismo. El system_prompt indica claramente
"Cliente quiere cotizar envío → quote_shipping(city)", pero a veces
el LLM emite texto antes que el tool call. Defensa en profundidad post-LLM.

Reglas:
  • Detecta frases de "promesa de acción" en candidate_text:
    "un momento", "estoy calculando", "estoy cotizando", "estoy
    buscando", "déjame revisar", "permíteme calcular", etc.
  • Si la promesa es de cotización/búsqueda/cálculo y NO corrió el
    tool correspondiente (`quote_shipping`, `list_catalog`,
    `get_recent_orders`, etc.) → REWRITE.
  • Reemplazo: pregunta concreta que destrabe el flow en el SIGUIENTE
    turno del cliente (e.g. "¿Confirmas que enviamos a Medellín para
    cotizar las opciones disponibles?").

NO bloquea — REWRITE. Mantiene momentum de venta.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from agentic.invariants.base import (
    Invariant,
    InvariantOutcome,
    InvariantResult,
)

logger = logging.getLogger(__name__)


# Patrones de "estoy haciendo X" / "voy a hacer X" / "déjame X".
# Cubre las formas más comunes que Gemini emite cuando "pospone" la
# ejecución de un tool en lugar de llamarlo de una.
_EMPTY_PROMISE_PATTERNS = (
    re.compile(r"\bun\s+momento\s+por\s+favor\b", re.IGNORECASE),
    re.compile(r"\bd[ée]jame\s+(?:un\s+momento|revisar|verificar|calcular|buscar|cotizar)\b", re.IGNORECASE),
    re.compile(r"\bperm[ií]teme\s+(?:un\s+momento|revisar|verificar|calcular|buscar|cotizar|consultar)\b", re.IGNORECASE),
    re.compile(r"\bestoy\s+(?:calculando|cotizando|buscando|revisando|consultando|verificando|procesando)\b", re.IGNORECASE),
    re.compile(r"\bvoy\s+a\s+(?:calcular|cotizar|buscar|revisar|consultar|verificar|procesar)\b", re.IGNORECASE),
    re.compile(r"\b(?:enseguida|ya\s+mismo|ahora\s+mismo)\s+(?:te|le)\s+(?:cotizo|busco|consulto|reviso)\b", re.IGNORECASE),
    re.compile(r"\b(?:proceso|procesando)\s+(?:tu|el|la)\s+(?:cotizaci[oó]n|consulta|b[uú]squeda)\b", re.IGNORECASE),
)

# Tools de "lectura/cálculo" cuya ausencia delata la promesa vacía. Si el
# bot dice "estoy calculando envío" y NO corrió quote_shipping → mentira.
_ACTION_TOOLS = {
    "quote_shipping",
    "list_catalog",
    "get_cart",
    "get_recent_orders",
    "kb_query",
    "get_contact_info",
}


def _has_empty_promise(text: str) -> bool:
    """True si el outbound promete una acción que aún no se ejecutó."""
    if not text:
        return False
    return any(p.search(text) for p in _EMPTY_PROMISE_PATTERNS)


def _executed_any_action_tool(tool_call_log: list[dict]) -> bool:
    """True si corrió al menos un tool de lectura/cálculo en este turn."""
    for call in tool_call_log or []:
        tool_name = (call.get("tool") or "").strip()
        if tool_name not in _ACTION_TOOLS:
            continue
        # Hubo tool call (exitoso o no) — la promesa NO es vacía.
        return True
    return False


def _is_pure_promise_without_content(text: str) -> bool:
    """Rev. 109 BUG 42 — True si outbound es SOLO promesa sin contenido útil.

    Caso UAT live observado: "Permíteme un momento, voy a verificar tus
    datos. Te confirmo en seguida." — el LLM corrió tools (legítimo)
    pero NO entregó NADA útil al cliente. Promesa colgada → cliente
    espera indefinidamente.

    Heurística contenido sustantivo (cualquiera lo descarta como vacío):
      • Precios ($X.XXX)
      • Listas de productos / opciones (líneas con * o •)
      • Datos del cart (Total, Subtotal, Descuento, Envío)
      • Pregunta concreta al cliente (¿confirmas? / ¿prefieres? / ¿cuál?)
      • Texto largo (>180 chars sin contar la promesa) sugiere contenido útil
    """
    if not text:
        return False
    has_substantive = bool(
        re.search(r"\$\s*[\d.,]+", text)
        or re.search(r"^\s*[\*•\-]\s", text, re.MULTILINE)
        or re.search(
            r"\b(?:total|subtotal|descuento|env[ií]o|carrier|cupon|cup[oó]n)\b",
            text, re.IGNORECASE,
        )
        or re.search(
            r"[¿?]\s*(?:cu[aá]l|prefieres|confirmas|qu[eé])\b",
            text, re.IGNORECASE,
        )
        or len(re.sub(r"\s+", " ", text.strip())) > 180
    )
    return not has_substantive


def _detect_promised_action(text: str) -> str:
    """Identifica qué acción concreta prometió el bot para el rewrite."""
    if not text:
        return ""
    t = text.lower()
    if re.search(r"\b(?:cotiza|env[ií]o|cost[oa]\s+de\s+env[ií]o|tarif)", t):
        return "shipping"
    if re.search(r"\b(?:pedido|orden|hist[oó]rico|compras\s+anteriores)", t):
        return "order_history"
    if re.search(r"\b(?:cat[aá]logo|productos?|presentaciones?)", t):
        return "catalog"
    return "generic"


def _replacement_for_promise(promised: str, candidate_text: str) -> str:
    """Genera CTA determinístico que destrabe el flow en el siguiente turn."""
    # Intenta extraer la ciudad/recurso mencionado para personalizar el CTA.
    city_match = re.search(
        r"\b(?:env[ií]o\s+a|a)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)",
        candidate_text or "",
    )
    city = city_match.group(1) if city_match else None

    if promised == "shipping":
        if city:
            return (
                f"Para cotizar el envío a *{city}*, confirma esa ciudad y "
                "te muestro las opciones disponibles enseguida."
            )
        return (
            "Para cotizar el envío, dime a qué ciudad lo enviamos y "
            "te muestro las opciones."
        )
    if promised == "order_history":
        return (
            "Para revisar tus pedidos anteriores, confirma esta consulta y "
            "te traigo el detalle al instante."
        )
    if promised == "catalog":
        return (
            "Cuéntame qué producto o categoría te interesa y te muestro "
            "las opciones disponibles."
        )
    # Generic — invita al cliente a re-confirmar la acción pedida.
    return (
        "Confirma lo que necesitas y avanzamos enseguida con tu pedido."
    )


class EmptyPromiseInvariant:
    """Reescribe outbounds que prometen acción sin haberla ejecutado.

    Caso clásico: cliente pide cotización a ciudad X, Gemini emite
    "Un momento, estoy calculando..." con tools=0. Cliente queda
    esperando indefinidamente.

    Fix: REWRITE a CTA que invite al cliente a re-confirmar para que
    el siguiente turn dispare el tool. Mantenemos momentum y nunca
    dejamos al cliente sin respuesta útil.
    """

    name = "empty_promise"

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
        if not _has_empty_promise(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # Rev. 109 BUG 42 — incluso si tools corrieron, si el outbound
        # es promesa pura sin contenido útil, REWRITE. El cliente quedó
        # esperando "te confirmo en seguida" sin nada más.
        if _is_pure_promise_without_content(candidate_text):
            promised = _detect_promised_action(candidate_text)
            replacement = _replacement_for_promise(promised, candidate_text)
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    "Promesa pura sin contenido útil — rewrite a CTA "
                    "determinístico aunque tools hayan corrido"
                ),
            )

        # Hay promesa. ¿Corrió tool de acción?
        if _executed_any_action_tool(tool_call_log):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="promesa con tool ejecutado coherente",
            )

        # Promesa vacía detectada — REWRITE.
        promised = _detect_promised_action(candidate_text)
        replacement = _replacement_for_promise(promised, candidate_text)
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason=(
                f"Promesa vacía detectada (action={promised}) sin tool "
                "ejecutado — rewrite a CTA determinístico."
            ),
        )

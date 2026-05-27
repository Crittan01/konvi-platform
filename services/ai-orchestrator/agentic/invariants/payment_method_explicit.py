"""Invariant: payment_method debe ser EXPLÍCITO antes de generate_payment_link.

Rev. 108 Fase B fix arquitectónico — el LLM no puede asumir modalidad de
pago por default. Si el cliente NO mencionó explícitamente "online/tarjeta/
PSE/Nequi" o "contraentrega/COD", el bot DEBE preguntar antes de generar
el link de pago.

Patrón: hard gate. Si invariant detecta que el outbound del LLM:
  - Está compartiendo un link Wompi (modo credit implícito)
  - Está confirmando pedido COD (modo cod implícito)
  - Sin que el history tenga evidencia explícita del modo
→ BLOQUEA + reescribe a pregunta determinística.

Diferenciación arquitectónica clave (founder feedback 2026-05-26):
  • "contraentrega" / "contra entrega" / "COD" = modo de pago COD
  • "Servientrega" / "SERVIENTREGA" = carrier name (NO modo de pago)
  Aunque suenan parecidos, son conceptos distintos. El invariant no puede
  confundirlos: chequea evidencia POR PALABRA EXACTA, no fuzzy.

Coordinación con cod_intent_resolver:
  - cod_intent_resolver marca cart.payment_method=cod cuando detecta intent
    explícito en mensaje inbound del cliente.
  - Este invariant lee cart.payment_method actual + history para confirmar
    que la decisión fue explícita del cliente, no asumida por LLM.
  - Si cart.payment_method='credit' (default) Y history NO contiene
    evidencia de intent credit explícito → bloquea + pregunta.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    Invariant,
    InvariantOutcome,
    InvariantResult,
)


# Patrones EXACTOS — no fuzzy. Diseñados para NO confundir Servientrega/contraentrega.
_COD_EXPLICIT_PATTERNS = (
    re.compile(r"\bcontra[\s\-]?entrega\b", re.IGNORECASE),
    re.compile(r"\bcod\b", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+(?:al|cuando|en\s+el\s+momento\s+de)\s+(?:recibi|lleg|entrega)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+en\s+efectivo\s+al\s+(?:recibi|lleg)", re.IGNORECASE),
)

_CREDIT_EXPLICIT_PATTERNS = (
    re.compile(r"\bpag(?:o|ar)\s+(?:online|anticipa|antes|ahora|por\s+adelantado)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+con\s+tarjeta\b", re.IGNORECASE),
    re.compile(r"\b(?:tarjeta\s+de\s+credito|cr[eé]dito\b|d[eé]bito\b)", re.IGNORECASE),
    re.compile(r"\b(?:pse|nequi|bancolombia\s+transfer|wompi)\b", re.IGNORECASE),
    re.compile(r"\bpref(?:iero|erir[íi]a)\s+pag(?:o|ar)\s+(?:online|antes|ahora)\b", re.IGNORECASE),
    # Rev. 108 holístico — cliente responde simplemente "online" / "Online"
    # tras pregunta del bot "¿online o contra entrega?". Patrón aislado o
    # como token suelto.
    re.compile(r"(?:^|[^a-záéíóúñ])online([^a-záéíóúñ]|$)", re.IGNORECASE),
    re.compile(r"\bpago\s+anticipado\b", re.IGNORECASE),
    re.compile(r"\bpor\s+wompi\b", re.IGNORECASE),
)


# Patrones del outbound del LLM que sugieren intent de generar link/confirmar pedido.
_LLM_PAYMENT_INTENT_PATTERNS = (
    re.compile(r"checkout\.wompi\.co|paga\s+aqu[ií]|\*paga\s+aqu", re.IGNORECASE),
    re.compile(r"link\s+de\s+pago.*generado|generando.*link\s+de\s+pago", re.IGNORECASE),
    re.compile(r"pedido.*registrado\s+para\s+contraentrega", re.IGNORECASE),
)

# Patrón outbound: lista de carriers con precios (cotización).
# Detecta texto tipo "* *SERVIENTREGA* — *$17.875 COP*" o variantes.
# Si el bot va a mostrar cotización SIN que el modo de pago sea explícito,
# es bug: el cliente debe saber el modo ANTES porque COD puede tener costo
# distinto (dossier §7.1, §7.3 — comisión 2.40%+ + tarifa carrier COD).
_LLM_QUOTE_DISPLAY_PATTERNS = (
    # 2+ líneas con bullet + carrier name + precio (COP suffix opcional).
    # Rev. 108 holístico — COP suffix opcional porque LLM a veces omite
    # la unidad ("*$7.530*" sin "COP" post markdown formatting).
    re.compile(
        r"(?:^|\n)\s*[\*•]\s+\*[A-ZÁÉÍÓÚÑ ]{3,}\*.*?\$[\d.,]+",
        re.MULTILINE,
    ),
    # "opciones de envío" / "estas opciones" + lista carriers
    re.compile(
        r"(?:opciones?\s+de\s+env[ií]o|estas\s+opciones|tenemos\s+est[ao]s?\b).*?"
        r"(?:COORDINADORA|SERVIENTREGA|ENVIA|INTERRAPIDISIMO|TCC|SAFERBO|"
        r"DOMINA|MOOVA|99\s?MINUTOS|GO\s?ENVIOS)",
        re.IGNORECASE | re.DOTALL,
    ),
)


def _client_mentioned_payment_method(history_messages: list[dict]) -> Optional[str]:
    """Escanea history del cliente buscando intent EXPLÍCITO de modo de pago.

    Returns:
        'cod' | 'credit' | None.
    """
    for msg in history_messages:
        if msg.get("direction") != "inbound":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        # COD primero (más específico, "contraentrega" es palabra dedicada).
        for pat in _COD_EXPLICIT_PATTERNS:
            if pat.search(content):
                return "cod"
        # Credit (más genérico, evita "Servientrega" — el regex usa \b boundaries).
        for pat in _CREDIT_EXPLICIT_PATTERNS:
            if pat.search(content):
                return "credit"
    return None


def _llm_outbound_implies_payment_action(candidate_text: str) -> bool:
    """True si el outbound LLM implica generar link o confirmar pago."""
    if not candidate_text:
        return False
    return any(p.search(candidate_text) for p in _LLM_PAYMENT_INTENT_PATTERNS)


def _llm_outbound_shows_quote(candidate_text: str) -> bool:
    """True si el outbound LLM muestra cotización de carriers + precios.

    Antes de mostrar cotización, el modo de pago debe estar definido
    porque COD puede tener tarifa carrier distinta (dossier §7.1) +
    comisión Aveonline (§7.3).
    """
    if not candidate_text:
        return False
    return any(p.search(candidate_text) for p in _LLM_QUOTE_DISPLAY_PATTERNS)


class PaymentMethodExplicitInvariant:
    """Bloquea outbounds que ejecutan acción de pago sin que el cliente haya
    mencionado modo de pago explícitamente.

    Si el LLM va a:
      - Compartir link Wompi (asume credit)
      - Confirmar pedido COD (asume cod)
    Sin que el history contenga evidencia explícita del modo:
      → BLOCK + reescribe a pregunta:
        "Antes de generar tu pedido, cuéntame: ¿prefieres pagar online
         (con tarjeta, PSE o Nequi) o contra entrega (pagas en efectivo
         al recibir el paquete)?"
    """

    name = "payment_method_explicit"

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
        # Aplica en 2 momentos del flow:
        #  (1) Cotización (lista de carriers + precios) — modo debe estar
        #      definido ANTES porque tarifa COD puede ser distinta.
        #  (2) Acción de pago (link Wompi o confirmación COD) — defensa
        #      en profundidad para casos sin cotización previa.
        is_quote = _llm_outbound_shows_quote(candidate_text)
        is_payment = _llm_outbound_implies_payment_action(candidate_text)
        if not (is_quote or is_payment):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="outbound no muestra cotización ni acción de pago",
            )

        # Leer history para buscar evidencia explícita.
        try:
            history_res = (
                supabase.table("messages")
                .select("direction, content")
                .eq("conversation_id", conversation_id)
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=False)
                .limit(50)
                .execute()
            )
            history = history_res.data or []
        except Exception:
            history = []

        # También verificar inbound_text actual (puede contener intent fresh).
        if inbound_text:
            history = list(history) + [
                {"direction": "inbound", "content": inbound_text},
            ]

        mentioned = _client_mentioned_payment_method(history)

        if mentioned is not None:
            # Cliente fue explícito → invariant OK.
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason=f"cliente mencionó modo explícito: {mentioned}",
            )

        # Cliente NO mencionó modo → BLOCK + reescribir.
        # Rev. 108 modular — adapta pregunta a métodos enabled del tenant.
        # Si tenant solo tiene 'online_wompi' → pide confirmación online
        # sin ofrecer COD (que no maneja).
        try:
            from lib.tenant_payment_methods import list_enabled_methods
            enabled = list_enabled_methods(supabase, tenant_id=tenant_id)
        except Exception:
            enabled = ["cod", "online_wompi"]  # fail-open

        has_cod = "cod" in enabled
        has_online = "online_wompi" in enabled

        if has_cod and has_online:
            replacement = (
                "Antes de continuar con tu pedido, cuéntame cómo prefieres "
                "pagar:\n\n"
                "🏦 *Pago online* (tarjeta, PSE, Nequi o transferencia "
                "Bancolombia) — recibes el link al confirmar.\n\n"
                "💵 *Contra entrega* — pagas en efectivo cuando el courier "
                "te entregue el paquete.\n\n"
                "Cuál prefieres?"
            )
        elif has_online and not has_cod:
            replacement = (
                "Para procesar tu pedido te envío un *link de pago online* "
                "(tarjeta, PSE, Nequi o transferencia Bancolombia). En "
                "este momento manejamos pago anticipado únicamente.\n\n"
                "Confirmas?"
            )
        elif has_cod and not has_online:
            replacement = (
                "Tu pedido será *contraentrega* — pagas en efectivo "
                "cuando el courier te entregue el paquete.\n\n"
                "Confirmas?"
            )
        else:
            # Edge: tenant deshabilitó ambos (config inválida).
            replacement = (
                "En este momento no tenemos métodos de pago disponibles. "
                "Te conecto con un asesor para coordinar la compra."
            )

        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason=(
                f"outbound implicaría acción de pago sin que el cliente "
                f"haya mencionado modo explícitamente. Métodos enabled "
                f"para tenant: {enabled}"
            ),
        )

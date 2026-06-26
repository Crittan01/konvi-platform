"""Invariant determinístico: el bot NUNCA presenta un resumen/total cuando el
envío está pendiente de recotizar (`requires_requote=True`).

Causa raíz (conversación +573125835649, 2026-06-26): el cliente agregó un Sérum
a mitad del checkout. `add_to_cart` invalidó el envío correctamente
(`shipping_cents=0`, `requires_requote=True`), pero el bot —cuyo estado del turno
ya era PAYMENT— presentó un resumen "listo" con `Total: $214.000` SIN línea de
envío (Total = Subtotal). Engaña al cliente sobre el monto real y monta un flujo
roto: si confirma, el adapter de pago bloquea el link (gate `shipping_cents>0`) y
toca recotizar.

El adapter de pago YA protege la plata (no genera link con envío=0). Este guard
cierra el hueco de UX/verdad: si el envío está invalidado, el bot debe RECOTIZAR,
no presentar un total. Principio #4 (el LLM no decide verdad transaccional).

Diseño per ADR-0024 (binario/determinístico):
  1. Pre-check barato: ¿el outbound presenta un resumen/total? (regex). Si NO → OK.
  2. Si SÍ: leer el carrito real. Si `requires_requote=True` con items → el total
     mostrado omite envío → REWRITE a un mensaje que dirige a recotizar.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import InvariantOutcome, InvariantResult

# Marcadores de "el bot está presentando un total / resumen / cierre de pago".
# Pre-check barato: si ninguno aparece, no hay total que validar → OK sin DB.
_SUMMARY_OR_TOTAL = re.compile(
    r"\btotal\b\s*:?\s*\*?\s*\$"      # "Total: $" / "TOTAL $" / "total: *$"
    r"|📋"                              # encabezado de resumen
    r"|resumen\s+(?:de|del)\s+(?:tu\s+)?pedido"
    r"|link\s+de\s+pago",             # cierre de pago (genero/comparto el link)
    re.IGNORECASE,
)

_REWRITE = (
    "Actualicé tu pedido con el nuevo producto. Como cambió el contenido, debo "
    "recalcular el costo de envío para darte el total exacto. ¿Te recotizo el "
    "envío con tu misma dirección de entrega?"
)

# Tools que mutan el carrito (invalidan el envío al ejecutarse exitosamente).
_CART_MUTATIONS = frozenset({
    "add_to_cart", "update_cart_item_quantity", "remove_cart_item",
})
# El bot YA reconoce que recotiza/recalcula el envío (no hace falta reescribir).
# Amplio (auditoría 2026-06-26): captura sinónimos válidos para no reescribir cuando
# el bot SÍ avisó ('calcular el costo de envío', 'actualizar el envío', etc.).
_ACK_REQUOTE = re.compile(
    r"recotiz|recalcul|vuelvo a cotiz|cotiz\w*\s+(?:de\s+)?nuevo|"
    r"(?:calcul|actualiz|ajust|cambi)\w*\s+(?:el\s+|tu\s+|del\s+)?"
    r"(?:costo\s+(?:de\s+)?)?env",
    re.IGNORECASE,
)


class RequotePendingSummaryInvariant:
    """Reconciliación de estado intra-turno: cuando el envío quedó pendiente de
    recotizar, fuerza que el bot lo avise. Cubre (A) presentar resumen/total/link
    y (B) mutar el carrito sin avisar la recotización (silent stale)."""

    name = "requote_pending_summary"

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
        ok = InvariantResult(outcome=InvariantOutcome.OK, invariant_name=self.name)
        if not candidate_text or not candidate_text.strip():
            return ok

        # Reconciliación intra-turno (palanca 3): el guard cubre DOS casos cuando
        # el envío quedó pendiente de recotizar (requires_requote=True):
        #   (A) el bot presenta un resumen/total/link → engaña con total sin envío.
        #   (B) el bot mutó el carrito ESTE turno (add/remove/qty) y NO avisó que
        #       recotiza → deja al cliente con cotización vieja silenciosamente.
        shows_summary = bool(_SUMMARY_OR_TOTAL.search(candidate_text))
        mutated_this_turn = any(
            c.get("tool") in _CART_MUTATIONS
            and "error" not in (c.get("result") or {})
            for c in (tool_call_log or [])
        )
        already_ack = bool(_ACK_REQUOTE.search(candidate_text))

        # (1) Pre-check barato: si no hay resumen NI mutación-sin-aviso → nada que validar.
        if not shows_summary and not (mutated_this_turn and not already_ack):
            return ok

        # (2) Estado real del carrito — fuente de verdad.
        try:
            rows = (
                supabase.table("conversation_carts")
                .select("requires_requote, shipping_cents, status")
                .eq("tenant_id", tenant_id)  # ADR-0025 aislamiento multi-tenant
                .eq("conversation_id", conversation_id)
                .neq("status", "converted")
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            cart = (rows.data or [None])[0]
        except Exception:
            return ok  # ante fallo de DB no rompemos el outbound (degradación segura)
        if not cart:
            return ok

        requires_requote = bool(cart.get("requires_requote"))

        # Señal PRECISA: requires_requote=True = el envío FUE cotizado y luego se
        # invalidó (agregar/quitar item). NO usamos shipping_cents<=0 solo (también
        # es 0 antes de la 1ª cotización o con envío gratis → falsos positivos).
        if requires_requote:
            caso = "resumen/total" if shows_summary else "mutación sin avisar recotización"
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=_REWRITE,
                reason=(
                    f"{caso} con envío pendiente de recotizar "
                    f"(requires_requote=True, mutated_this_turn={mutated_this_turn}, "
                    f"shipping_cents={int(cart.get('shipping_cents') or 0)})"
                ),
            )
        return ok

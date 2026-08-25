"""Puertos del adaptador API para el dominio reclamos (Track 5 M2.4).

El domain service (`konvi_domain.claims`) orquesta la lógica; cada canal cablea
SUS efectos de notificación. Aquí: Telegram al operador (`lib/operator_alerts`)
y WhatsApp al cliente cuando su reclamo llega a outcome (BLOQUE F-5 — la lógica
se MUEVE aquí desde `routers/claims.py`, intacta: mismos textos, mismo lazy
import, mismo best-effort).

⚠️ El import de `routers.wompi_webhook._enqueue_whatsapp_outbound` es LAZY EN
CALL TIME a propósito: los tests pachean el atributo del MÓDULO y resolver el
símbolo en cada llamada preserva ese contrato (patrón heredado del router —
misma razón que en `lib/order_payment_ports.py`).
"""
from __future__ import annotations

import logging
from typing import Any

from konvi_domain.claims import ClaimPorts

logger = logging.getLogger(__name__)


def notify_client_claim_outcome(supabase, *, claim: dict, tenant_id: str) -> None:
    """BLOQUE F-5: notifica al cliente por WhatsApp cuando su reclamo se RESUELVE o RECHAZA.

    Reusa el patrón best-effort de wompi_webhook (_enqueue_whatsapp_outbound): encola el
    mensaje y la ventana 24h de Meta la aplica el downstream (si el cliente escribió hace
    >24h la entrega falla igual que en las notifs de pago/envío). NUNCA rompe la mutación
    (best-effort). `claim` es la fila YA actualizada (incluye status/notes/order_id).
    El servicio la dispara SOLO en transición real a outcome (el gate `enabled` del
    helper histórico ahora vive en `transition_claim`).
    """
    try:
        status = (claim or {}).get("status")
        if status not in ("resolved", "rejected"):
            return
        order_id = claim.get("order_id")
        if not order_id:
            return
        order = (
            supabase.table("orders")
            .select("conversation_id")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        ).data
        conversation_id = (order or [{}])[0].get("conversation_id")
        if not conversation_id:
            return  # sin conversación WhatsApp (p.ej. pedido MeLi/consola) → no hay canal

        ticket = claim.get("ticket_number")
        notes = (claim.get("resolution_notes") or "").strip()
        ref = f"#{ticket}" if ticket else f"del pedido #{str(order_id)[:8].upper()}"
        if status == "resolved":
            text = (
                f"✅ *Reclamo resuelto*\n\nTu reclamo {ref} fue resuelto."
                + (f"\n\n{notes}" if notes else "")
                + "\n\nGracias por tu paciencia. Si necesitas algo más, escríbenos."
            )
        else:  # rejected
            text = (
                f"Hemos revisado tu reclamo {ref}."
                + (f"\n\n{notes}" if notes else "")
                + "\n\nSi tienes dudas o nueva información, escríbenos y lo revisamos."
            )

        from routers.wompi_webhook import _enqueue_whatsapp_outbound
        _enqueue_whatsapp_outbound(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
            text=text, log_tag="CLAIM_WA_OUTCOME",
        )
    except Exception as exc:
        logger.warning("[CLAIMS] notif cliente falló claim=%s: %s", (claim or {}).get("id"), exc)


def build_api_claim_ports(supabase: Any, tenant_id: str) -> ClaimPorts:
    """Puertos del canal consola/API: Telegram operador + WhatsApp cliente (F-5)."""

    def _notify_operator(text: str) -> None:
        from lib.operator_alerts import notify_operator_telegram  # lazy (ver docstring)
        notify_operator_telegram(supabase, tenant_id=tenant_id, text=text)

    def _notify_client(claim: dict) -> None:
        notify_client_claim_outcome(supabase, claim=claim, tenant_id=tenant_id)

    return ClaimPorts(
        notify_operator_new_claim=_notify_operator,
        notify_client_outcome=_notify_client,
    )

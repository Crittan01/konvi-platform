"""Puertos del adaptador API para el pipeline unificado de cancelación (M2.2).

Cada canal cablea SUS implementaciones de los efectos de proveedor que el
domain service (`konvi_domain.orders.cancellation`) orquesta. Aquí: void Wompi
+ cancel guía Aveonline + notificaciones (WhatsApp cliente / Telegram operador)
con las piezas del servicio API.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from konvi_domain.orders.cancellation import CancellationPorts

from integrations.aveonline_client import AveonlineClient
from integrations.wompi_client import get_tenant_wompi_creds, void_transaction_sync
from lib.client_notifications import _enqueue_whatsapp_outbound
from lib.operator_alerts import notify_operator_telegram

logger = logging.getLogger(__name__)


def build_api_cancellation_ports(supabase: Any) -> CancellationPorts:
    """Puertos del canal consola/API: void Wompi + cancel guía Aveonline."""

    def _void_credentials(tenant_id: str) -> Optional[tuple[str, str]]:
        private_key, _events_key, environment = get_tenant_wompi_creds(supabase, tenant_id)
        if not private_key:
            return None
        return (private_key, environment or "sandbox")

    def _void_payment(private_key: str, environment: str, txn_id: str) -> None:
        void_transaction_sync(
            private_key=private_key,
            environment=environment,
            transaction_id=txn_id,
        )

    async def _cancel_shipping_guide(tenant_id: str, tracking_number: str) -> dict:
        client = AveonlineClient(supabase=supabase, tenant_id=tenant_id)
        result = await client.cancel_guide(tracking_number=tracking_number)
        return {"ok": bool(result.get("ok")), "method": "aveonline_api"}

    def _on_stock_restored(variation_id: str, new_stock: int) -> None:
        """Sync MeLi tras reponer stock por cancelación (cobertura que la consola
        ya tenía vía `_restore_stock_on_cancel`; preservada en el pipeline — el
        bot la ganará al adoptar el paquete en B-2). Loop-aware: el pipeline
        corre dentro de asyncio.run en el adaptador (loop activo)."""
        import asyncio as _asyncio

        from routers.marketplace import sync_meli_stock
        try:
            loop = _asyncio.get_running_loop()
            loop.create_task(sync_meli_stock(variation_id, new_stock, supabase))
        except RuntimeError:
            try:
                _asyncio.run(sync_meli_stock(variation_id, new_stock, supabase))
            except Exception as meli_err:
                logger.warning(
                    "[CANCEL] Sync MeLi (restore) falló variation=%s (no bloquea): %s",
                    variation_id, meli_err,
                )

    return CancellationPorts(
        void_credentials=_void_credentials,
        void_payment=_void_payment,
        cancel_shipping_guide=_cancel_shipping_guide,
        on_stock_restored=_on_stock_restored,
    )


def send_cancellation_notifications(
    supabase: Any,
    *,
    result: Any,  # konvi_domain CancellationResult
    tenant_id: str,
    conversation_id: Optional[str],
) -> None:
    """Entrega los mensajes del pipeline por los canales del servicio API.

    - Cliente: WhatsApp encolado (solo si la orden tiene conversación — un
      pedido manual sin conversación no tiene canal al cliente).
    - Operador: Telegram cuando hay refund manual pendiente (plazo legal corre).
    Todo best-effort: una falla de notificación nunca tumba la cancelación.
    """
    if conversation_id and result.customer_message:
        try:
            _enqueue_whatsapp_outbound(
                supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=result.customer_message,
                log_tag="CANCEL",
            )
        except Exception as exc:
            logger.warning("[CANCEL] notif cliente WhatsApp falló: %s", exc)

    if result.operator_notification:
        try:
            notify_operator_telegram(
                supabase, tenant_id=tenant_id, text=result.operator_notification,
            )
        except Exception as exc:
            logger.warning("[CANCEL] notif operador Telegram falló: %s", exc)

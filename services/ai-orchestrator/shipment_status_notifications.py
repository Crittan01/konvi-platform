"""A10 (auditoría 2026-08-02) — Tracking de envíos Aveonline para el poll backup
del worker (`aveonline_status_poll`).

Por qué existe este módulo: el tracking de envíos dependía 100% del webhook de
Aveonline — si el tenant no lo registra o un evento se pierde, el envío queda
congelado para siempre. El cliente espejo YA tenía `get_estado` implementado
(integrations/aveonline_client.py) pero con CERO callers. El poll del worker lo
invoca sobre shipments stale no-terminales y aplica la MISMA semántica del
webhook (dedup + guard monotónico + avance de orden + notificación).

Qué se REUSA de hecho (sin duplicar):
  • `fn_record_shipment_tracking_event` (RPC, migración 20260712040000): dedup
    atómico + guard monotónico por occurred_at + bloqueo de terminales. Es la
    misma RPC que invoca el webhook — el guard vive en DB, no en app.
  • `_enqueue_whatsapp_outbound` (refund_notifications.py): cola durable WA.
  • `_send_email_via_resend` (notifications.py): email transaccional.
  • `notify_escalation_async` (telegram_notifications.py): alerta al operador.

Qué se REPLICA aquí (NO importable desde este proceso — en Render el rootDir
del orchestrator es services/ai-orchestrator y services/api/ NO existe; ver el
incidente P0-1 documentado en refund_notifications.py):
  • RAW_STATE_TO_INTERNAL / TERMINAL_STATUSES / parse de fechas / rank de orden
    — SST: services/api/routers/aveonline_webhook.py. Si editas el mapping o el
    rank allá, actualiza acá (y viceversa — el SST tiene un puntero a esta
    réplica).
  • Copy WA/email de las notificaciones de estado — SST: las funciones
    `_notify_client_shipment_*` de services/api/routers/wompi_webhook.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from notifications import _send_email_via_resend
from refund_notifications import _enqueue_whatsapp_outbound, _html_to_text
from telegram_notifications import notify_escalation_async

logger = logging.getLogger("shipment_status_notifications")


# ── Mapping de estados Aveonline → canónico interno ──────────────────────────
# ESPEJO de RAW_STATE_TO_INTERNAL en services/api/routers/aveonline_webhook.py
# (mantener alineados — el poll y el webhook escriben en la misma tabla).
# Cobertura del flujo oficial del API Sandbox (doc `sandbox-avanzarEstado`,
# fetch 2026-08-22): GENERADA → PRODUCIDA → EN DESPACHO → EN REPARTO →
# ENTREGADA, forzable a EN NOVEDAD; terminales ENTREGADA y ANULADA.
RAW_STATE_TO_INTERNAL = {
    # Generada / pre-recogida / recogida.
    "GENERADA": "pending",
    "PRODUCIDA": "pending",
    "EN OFICINA": "pending",
    "EN RECOGIDA": "pending",
    "RECOGIDA": "pending",
    # En tránsito físico.
    "EN DESPACHO": "in_transit",
    "EN BODEGA": "in_transit",
    "EN TRANSITO": "in_transit",
    "EN TRÁNSITO": "in_transit",
    "EN REPARTO": "in_transit",
    "EN ENTREGA": "in_transit",
    "EN RUTA": "in_transit",
    "EN CAMINO": "in_transit",
    "DESPACHADO": "in_transit",
    "DESPACHADA": "in_transit",
    "ENVIADO": "in_transit",
    "ENVIADA": "in_transit",
    "RECIBIDA EN TRANSPORTADORA": "in_transit",
    # Entregada (terminal positivo).
    "ENTREGADA": "delivered",
    "ENTREGADO": "delivered",
    # Excepciones.
    "EN NOVEDAD": "exception",
    "NOVEDAD": "exception",
    "DIRECCION ERRONEA": "exception",
    "DIRECCIÓN ERRONEA": "exception",
    "CLIENTE NO TIENE EFECTIVO": "exception",
    "CLIENTE AUSENTE": "exception",
    "RECHAZA PRODUCTO": "exception",
    # Devolución (terminal negativo).
    "DEVOLUCION": "returned",
    "DEVOLUCIÓN": "returned",
    "DEVUELTA": "returned",
    "DEVUELTO": "returned",
    # Anulación / cancelación (terminal — doc sandbox: ANULADA es terminal).
    "ANULADA": "cancelled",
    "ANULADO": "cancelled",
    "CANCELADA": "cancelled",
    "CANCELADO": "cancelled",
}

TERMINAL_STATUSES = frozenset({"delivered", "returned", "cancelled"})

# ESPEJO de _ORDER_STATUS_RANK (aveonline_webhook.py / meli_webhook.py). El
# avance a 'delivered' es MONOTÓNICO: nunca regresa ni pisa un terminal.
_ORDER_STATUS_RANK: dict[str, int] = {
    "pending": 0, "pending_payment": 0, "confirmed": 1,
    "processing": 2, "shipped": 3, "delivered": 4, "cancelled": 5,
}

# Rank del ciclo de vida del SHIPMENT para el gate anti-retroceso de la
# notificación (la RPC ya impide que `shipments.status` retroceda en DB; esto
# impide ADEMÁS avisar al cliente un salto hacia atrás — p.ej. un historico
# viejo "RECOGIDA" llegando cuando el envío ya va "EN REPARTO"). exception va
# al nivel de in_transit: la novedad y su recuperación SÍ se notifican.
_SHIPMENT_NOTIFY_RANK: dict[str, int] = {
    "quoted": 0, "labeled": 0, "pending": 1, "picked_up": 2,
    "in_transit": 3, "exception": 3, "delivered": 4, "returned": 4,
    "cancelled": 5,
}


def map_raw_status(raw_status: str) -> str:
    """Mapea raw status Aveonline → canónico interno. Default: 'pending'."""
    if not raw_status:
        return "pending"
    key = str(raw_status).strip().upper()
    return RAW_STATE_TO_INTERNAL.get(key, "pending")


def is_status_regression(prev_status: str, new_status: str) -> bool:
    """True si notificar `new_status` sería un retroceso frente a `prev_status`."""
    return _SHIPMENT_NOTIFY_RANK.get(new_status, 0) < _SHIPMENT_NOTIFY_RANK.get(prev_status, 0)


def parse_occurred_at(fecha: str) -> Optional[str]:
    """Parsea fecha Aveonline → ISO8601 UTC (espejo de _parse_occurred_at del
    webhook): "YYYY-MM-DD HH:MM:SS", "YYYY/MM/DD HH:MM:SS am/pm" o ISO8601.
    None si no matchea (occurred_at es best-effort; la RPC es fail-open con NULL)."""
    if not fecha:
        return None
    s = fecha.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %I:%M:%S %p"):
        try:
            return datetime.strptime(s.upper(), fmt).replace(
                tzinfo=timezone.utc,
            ).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def record_shipment_tracking_event(
    supabase: Any,
    *,
    tenant_id: str,
    shipment_id: Optional[str],
    order_id: Optional[str],
    guia: str,
    nombre_estado: str,
    fecha: str,
    raw_payload: dict,
) -> bool:
    """Registra un evento del poll vía la MISMA RPC del webhook (dedup atómico
    + guard monotónico en DB). Retorna True SOLO si el evento es nuevo.

    external_event_id: `"{guia}|poll:{nombre_estado}|{fecha}"`. El webhook usa
    `"{guia}|{estado_id}|{fecha}"` — el poll no recibe estado_id, así que el
    tag `poll:` + el nombre crudo da un id ESTABLE cross-ciclo (el mismo estado
    sin cambios dedupa → no re-notifica) y distinguible del path webhook en la
    tabla (forensics de qué path descubrió el estado).
    """
    internal_status = map_raw_status(nombre_estado)
    external_event_id = f"{guia}|poll:{str(nombre_estado).strip().upper()}|{fecha}"
    try:
        res = supabase.rpc(
            "fn_record_shipment_tracking_event",
            {
                "p_tenant_id": tenant_id,
                "p_shipment_id": shipment_id,
                "p_order_id": order_id,
                "p_provider": "aveonline",
                "p_external_event_id": external_event_id,
                "p_raw_status": nombre_estado,
                "p_raw_estado_id": None,
                "p_internal_status": internal_status,
                "p_description": None,
                "p_occurred_at": parse_occurred_at(fecha),
                "p_raw": raw_payload,
            },
        ).execute()
        return bool(res.data) if not isinstance(res.data, bool) else res.data
    except Exception as exc:
        logger.warning(
            "[SHIPMENT_POLL] fn_record_shipment_tracking_event err "
            "tenant=%s guia=%s: %s",
            tenant_id, guia, exc,
        )
        return False


def advance_order_to_delivered(
    supabase: Any, tenant_id: str, order_id: str, current_status: Optional[str],
) -> bool:
    """Espejo de `_advance_order_to_delivered` (BLOQUE F-6 del webhook): avanza
    `orders.status` a 'delivered' cuando el envío se entrega. Forward-only y
    monotónico (rank): solo desde confirmed/processing/shipped (NUNCA desde
    pending/pending_payment — prepago impago no se marca entregado). El UPDATE
    re-filtra por rank en SQL → race-safe. Best-effort: no propaga.
    """
    if _ORDER_STATUS_RANK.get(current_status or "", 0) >= _ORDER_STATUS_RANK["delivered"]:
        return False
    _delivered_rank = _ORDER_STATUS_RANK["delivered"]
    advanceable = [s for s, r in _ORDER_STATUS_RANK.items() if 0 < r < _delivered_rank]
    try:
        upd = (
            supabase.table("orders")
            .update({"status": "delivered"})
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .in_("status", advanceable)
            .execute()
        )
        advanced = bool(upd.data)
        if advanced:
            logger.info(
                "[SHIPMENT_POLL] order %s → status delivered (tenant=%s)", order_id, tenant_id,
            )
        return advanced
    except Exception as exc:
        logger.warning("[SHIPMENT_POLL] order advance→delivered err order=%s: %s", order_id, exc)
        return False


# ── Notificación al cliente (WA + email) y al operador (Telegram) ────────────

# Etiquetas es-CO del enum interno para el email (espejo del criterio Rev. 112
# del SST: mostrar el nombre real del courier cuando existe, nunca el enum en
# inglés crudo).
_INTERNAL_STATUS_ES = {
    "pending": "En preparación",
    "in_transit": "En camino",
    "delivered": "Entregado",
    "exception": "Novedad en la entrega",
    "returned": "Devuelto",
}


def _status_label(raw_status: str, internal_status: str) -> str:
    rs = (raw_status or "").strip()
    if rs:
        return rs.capitalize() if rs.isupper() else rs
    return _INTERNAL_STATUS_ES.get((internal_status or "").strip().lower(), internal_status)


def _compose_status_email_html(
    *,
    customer_name: str,
    order_short: str,
    heading: str,
    body: str,
    tenant_name: str,
) -> str:
    """Misma tipografía Arial/#2c3e50 del ciclo de vida de emails del pedido
    (paridad con _compose_refund_completed_email_html)."""
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px;color:#2c3e50">{heading}, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">{body}</p>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Pedido <strong>#{order_short}</strong><br/>— {tenant_name or 'nuestra tienda'}
  </p>
</div>
</body></html>"""


async def _send_status_email(
    supabase: Any,
    *,
    tenant_id: str,
    order_id: str,
    email: str,
    customer_name: str,
    internal_status: str,
    raw_status: str,
    carrier: str,
    tracking_number: str,
) -> None:
    """Email transaccional del cambio de estado. Best-effort con Idempotency-Key
    `{tenant}:{order}:shipment_status:{internal}` → dedup cross-path (si el
    webhook ya notificó el mismo estado, Resend deduplica 24h)."""
    short_id = str(order_id)[:8].upper()
    label = _status_label(raw_status, internal_status)
    carrier_str = (carrier or "tu transportadora").strip()
    if internal_status == "delivered":
        heading = "📬 Tu pedido fue entregado"
        body = (
            f"Tu pedido llegó vía <strong>{carrier_str}</strong> "
            f"(guía {tracking_number}). ¿Todo llegó perfecto? "
            f"Escríbenos por WhatsApp y cuéntanos."
        )
    elif internal_status == "exception":
        heading = "⚠️ Novedad con tu envío"
        body = (
            f"Tu pedido tuvo un inconveniente con <strong>{carrier_str}</strong> "
            f"(guía {tracking_number}). Motivo reportado: <strong>{label}</strong>. "
            f"Ya estamos revisando con la transportadora."
        )
    else:  # in_transit
        heading = "🚚 Tu envío salió en ruta"
        body = (
            f"Tu pedido va en camino con <strong>{carrier_str}</strong> "
            f"(guía {tracking_number}). Estado: <strong>{label}</strong>."
        )
    try:
        tenant_name = ""
        try:
            ten = (
                supabase.table("tenants")
                .select("name").eq("id", tenant_id).single().execute()
            ).data
            tenant_name = (ten or {}).get("name") or ""
        except Exception:
            pass
        html = _compose_status_email_html(
            customer_name=customer_name, order_short=short_id,
            heading=heading, body=body, tenant_name=tenant_name,
        )
        ok = await _send_email_via_resend(
            to=email,
            subject=f"{heading} — Pedido #{short_id}",
            html=html,
            text=_html_to_text(html),
            idempotency_key=f"{tenant_id}:{order_id}:shipment_status:{internal_status}"[:256],
        )
        if not ok:
            logger.warning(
                "[SHIPMENT_POLL] shipment status email no entregado order=%s",
                short_id,
            )
    except Exception as exc:
        logger.warning(
            "[SHIPMENT_POLL] email status falló order=%s: %s", short_id, exc,
        )


async def notify_client_shipment_status(
    supabase: Any,
    *,
    tenant_id: str,
    shipment: dict,
    internal_status: str,
    raw_status: str,
) -> None:
    """Despacha la notificación del cambio de estado detectado por el poll.

    Paridad con `_notify_status_change` del webhook (SST): WA + email al
    cliente para in_transit/delivered/exception; alerta al OPERADOR (Telegram)
    para exception/returned. Best-effort: errores se loguean, NO se propagan
    (el status ya quedó persistido por la RPC — la notificación nunca lo revierte).
    """
    order_id = shipment.get("order_id")
    if not order_id:
        logger.info(
            "[SHIPMENT_POLL] shipment %s sin order_id — skip notif client",
            shipment.get("id"),
        )
        return

    conversation_id = None
    email = ""
    customer_name = "cliente"
    try:
        order_res = (
            supabase.table("orders")
            .select("conversation_id, contacts(name, email)")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .limit(1).execute()
        )
        order = (order_res.data or [{}])[0]
        conversation_id = order.get("conversation_id")
        contact = order.get("contacts") or {}
        email = (contact.get("email") or "").strip()
        customer_name = contact.get("name") or "cliente"
    except Exception as exc:
        logger.warning("[SHIPMENT_POLL] order lookup err order=%s: %s", order_id, exc)
        return

    carrier = shipment.get("carrier") or ""
    tracking_number = shipment.get("tracking_number") or ""
    tracking_url = shipment.get("tracking_url") or ""
    short_id = str(order_id)[:8].upper()

    if internal_status == "in_transit" and conversation_id:
        # Copy espejo de _notify_client_shipment_in_transit (wompi_webhook.py).
        carrier_str = (carrier or "tu transportadora").strip()
        status_line = f" ({raw_status})" if raw_status else ""
        tracking_line = (
            f"\n\n🔍 *Rastrea tu envío*:\n{tracking_url}"
            if tracking_url else ""
        )
        text = (
            f"🚚 *Tu envío salió en ruta*{status_line}\n\n"
            f"Pedido *#{short_id}* va contigo con *{carrier_str}*.\n"
            f"Guía: `{tracking_number}`"
            f"{tracking_line}"
        )
        try:
            _enqueue_whatsapp_outbound(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                text=text, log_tag="SHIPMENT_POLL_WA_IN_TRANSIT",
            )
        except Exception as exc:
            logger.warning("[SHIPMENT_POLL] WA in_transit notif err: %s", exc)

    elif internal_status == "delivered" and conversation_id:
        # Copy espejo de _notify_client_shipment_delivered (wompi_webhook.py).
        carrier_str = (carrier or "el courier").strip()
        text = (
            f"📬 *Tu pedido fue entregado*\n\n"
            f"*#{short_id}* llegó vía *{carrier_str}* (guía `{tracking_number}`).\n\n"
            f"¿Todo llegó perfecto? Cuéntame por aquí, tu opinión nos "
            f"ayuda muchísimo. ¡Gracias por confiar en nosotros! 💛"
        )
        try:
            _enqueue_whatsapp_outbound(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                text=text, log_tag="SHIPMENT_POLL_WA_DELIVERED",
            )
        except Exception as exc:
            logger.warning("[SHIPMENT_POLL] WA delivered notif err: %s", exc)

    elif internal_status == "exception" and conversation_id:
        # Copy espejo de _notify_client_shipment_exception (wompi_webhook.py).
        carrier_str = (carrier or "el courier").strip()
        reason_line = (
            f"\n\nMotivo reportado: *{raw_status}*"
            if raw_status else ""
        )
        text = (
            f"⚠️ *Novedad con tu envío*\n\n"
            f"Pedido *#{short_id}* tuvo un inconveniente con *{carrier_str}* "
            f"(guía `{tracking_number}`).{reason_line}\n\n"
            f"Ya estamos revisando con la transportadora. Te confirmamos "
            f"por aquí en cuanto tengamos respuesta."
        )
        try:
            _enqueue_whatsapp_outbound(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                text=text, log_tag="SHIPMENT_POLL_WA_EXCEPTION",
            )
        except Exception as exc:
            logger.warning("[SHIPMENT_POLL] WA exception notif err: %s", exc)

    # Email transaccional (no requiere conversación WA) — in_transit/delivered/exception.
    if internal_status in {"in_transit", "delivered", "exception"} and email:
        await _send_status_email(
            supabase, tenant_id=tenant_id, order_id=order_id,
            email=email, customer_name=customer_name,
            internal_status=internal_status, raw_status=raw_status,
            carrier=carrier, tracking_number=tracking_number,
        )

    # Alerta al OPERADOR (BLOQUE F-7 del webhook): exception y returned
    # requieren acción humana (gestionar novedad / contactar antes de re-despachar).
    if internal_status in {"exception", "returned"}:
        head = "⚠️ *Novedad en envío*" if internal_status == "exception" else "📦 *Devolución de envío*"
        action = (
            "El courier reportó una novedad. Gestiona (reintento / contacto cliente)."
            if internal_status == "exception"
            else "El paquete regresa. Contacta al cliente antes de re-despachar o reembolsar."
        )
        reason = (
            f"{head}\n"
            f"Pedido: `{short_id}`\n"
            f"Guía: `{tracking_number}` ({carrier or 'Aveonline'})\n"
            f"Estado courier: *{raw_status or internal_status}*\n\n"
            f"{action}\n"
            f"_(detectado por polling de respaldo — webhook Aveonline)_"
        )
        try:
            await notify_escalation_async(
                supabase, tenant_id=tenant_id, reason=reason, severity="warning",
            )
        except Exception as exc:
            logger.warning(
                "[SHIPMENT_POLL] operator alert err tenant=%s order=%s: %s",
                tenant_id, short_id, exc,
            )

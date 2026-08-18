"""Notificaciones transaccionales al cliente (extraído de routers/wompi_webhook.py — G12 corte 2).

Cluster cohesivo: enqueue de WhatsApp outbound (cola durable), humanizado de
estados de envío, envío de email transaccional vía Resend y las notificaciones
de post-pago/post-guía/post-venta al cliente final. Extraído verbatim
2026-08-13 — comportamiento idéntico; el router las importa (sus nombres quedan
en su namespace → callers y tests no se enteran).

NOTA: `_notify_client_refund_completed` tiene una RÉPLICA en el orchestrator
(`services/ai-orchestrator/refund_notifications.py`) — si editas el copy,
propaga el cambio allá (esa réplica existe porque este paquete no es
importable desde el proceso orchestrator).
"""
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from lib.email_templates import (
    _compose_payment_email_html,
    _compose_payment_failed_email_html,
    _compose_refund_completed_email_html,
    _compose_shipment_delivered_email_html,
    _compose_shipment_exception_email_html,
    _compose_shipment_in_transit_email_html,
    _compose_shipment_label_ready_email_html,
    _html_to_text,
    _mask_email,
)

logger = logging.getLogger(__name__)


def _enqueue_outbound_text(supabase, *, conversation_id: str, tenant_id: str, text: str) -> None:
    """Inserta mensaje outbound y lo encola en pgmq whatsapp_outbound_messages."""
    msg_res = supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "content_type": "text",
        "content": text,
        "processed": False,
        "processing_status": "pending",
    }).execute()
    if not (msg_res.data):
        logger.warning("[WOMPI] enqueue_outbound_sin_msg conv=%s", conversation_id)
        return
    new_msg = msg_res.data[0]

    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    customer_phone = (conv_res.data or [{}])[0].get("customer_phone", "")
    if not customer_phone:
        logger.warning("[WOMPI] enqueue_outbound_sin_phone conv=%s", conversation_id)
        return

    supabase.rpc(
        "enqueue_whatsapp_outbound_message",
        {"p_message": {
            "event_type": "whatsapp.outbound.send",
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": new_msg["id"],
            "customer_phone": customer_phone,
            "text": text,
            "client_message_id": str(uuid4()),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }, "p_delay": 0},
    ).execute()


def _enqueue_whatsapp_outbound(
    supabase, *, conversation_id: str, tenant_id: str, text: str,
    log_tag: str,
) -> None:
    """Encola un outbound WhatsApp + persiste en messages. Helper común
    para los 2 mensajes post-pago (pago confirmado + envío despachado).
    """
    msg_insert = supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "content_type": "text",
        "content": text,
        "processed": False,
        "processing_status": "pending",
    }).execute()
    if not msg_insert.data:
        logger.warning("[%s] no_persisted_outbound conv=%s", log_tag, conversation_id)
        return
    new_msg = msg_insert.data[0]
    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .limit(1).execute()
    )
    conv = (conv_res.data or [{}])[0]
    customer_phone = conv.get("customer_phone", "")
    if not customer_phone:
        logger.warning("[%s] sin_customer_phone conv=%s", log_tag, conversation_id)
        return
    queue_payload = {
        "event_type": "whatsapp.outbound.send",
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "message_id": new_msg["id"],
        "customer_phone": customer_phone,
        "text": text,
        "client_message_id": str(uuid4()),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase.rpc(
        "enqueue_whatsapp_outbound_message",
        {"p_message": queue_payload, "p_delay": 0},
    ).execute()
    logger.info("[%s] outbound encolado conv=%s", log_tag, conversation_id)


def _notify_client_refund_completed(
    supabase, *, order_id: str, amount_in_cents: int,
) -> None:
    """Notifica al cliente que el void llegó al ciclo bancario (status=VOIDED
    en Wompi confirmado). El reembolso aparecerá en su tarjeta en 1-2 días
    hábiles típicos post-VOIDED.

    Envía WhatsApp + email + actualiza audit refund_completed_at.

    SST de este flujo. Existe una RÉPLICA en el orchestrator
    (services/ai-orchestrator/refund_notifications.py) usada por el cron backup
    del worker (MA-9), porque este módulo NO es importable desde el proceso
    orchestrator (rootDir distinto en Render). Si editas el copy WhatsApp/email
    o el composer, propaga el cambio allá. La réplica tiene semántica de
    reintento (devuelve bool) y guard de idempotencia por refund_status.
    """
    try:
        # Webhook processing: descubre el tenant del order (ref del webhook).
        order = (
            supabase.table("orders")  # tenant_filter:exempt:webhook_resolution_lookup
            .select("tenant_id, conversation_id, cancellation_id")
            .eq("id", order_id).single().execute()
        ).data
    except Exception:
        return
    if not order:
        return

    tenant_id = order.get("tenant_id")
    conversation_id = order.get("conversation_id")
    cancellation_id = order.get("cancellation_id")
    short_id = order_id[:8].upper()
    amount_fmt = f"${amount_in_cents / 100:,.0f}".replace(",", ".")

    # BLOQUE H (review Fable): idempotencia cross-path con el cron backup del
    # orchestrator. Si el reembolso ya fue marcado 'completed' (p.ej. el poll
    # del worker notificó primero), NO re-notificar — el WhatsApp no tiene
    # Idempotency-Key propia y el cliente recibiría el mensaje duplicado.
    if cancellation_id and tenant_id:
        try:
            _cx = (
                supabase.table("order_cancellations")  # tenant_filter:exempt:webhook_resolution_lookup
                .select("refund_status")
                .eq("id", cancellation_id).single().execute()
            ).data
            if (_cx or {}).get("refund_status") == "completed":
                return
        except Exception:
            pass

    # WhatsApp.
    if conversation_id and tenant_id:
        try:
            text = (
                f"✅ *Reembolso confirmado*\n\n"
                f"Tu reembolso de *{amount_fmt} COP* del pedido "
                f"*#{short_id}* ya fue procesado por Wompi y enviado a tu "
                f"banco.\n\n"
                f"El dinero aparecerá en tu tarjeta en *1-2 días hábiles* "
                f"típicos (puede tardar más según tu banco emisor).\n\n"
                f"Si en 7 días no lo ves, escríbenos y te ayudamos a "
                f"rastrearlo con Wompi."
            )
            _enqueue_whatsapp_outbound(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                text=text, log_tag="WOMPI_WA_REFUND_DONE",
            )
        except Exception as exc:
            logger.warning(
                "[WOMPI] enqueue refund_completed WA failed order=%s: %s",
                order_id, exc,
            )

    # Email best-effort (reusa la plantilla existente con template_mode).
    if tenant_id:
        try:
            _send_payment_confirmation_email(
                supabase=supabase, order_id=order_id, tenant_id=tenant_id,
                template_mode="refund_completed",
            )
        except Exception as exc:
            logger.warning(
                "[WOMPI][EMAIL] refund_completed falló order=%s err=%s",
                order_id, exc,
            )

    # Audit — marcar refund_completed_at.
    if cancellation_id:
        try:
            from datetime import datetime, timezone
            supabase.table("order_cancellations").update({
                "refund_completed_at": datetime.now(timezone.utc).isoformat(),
                "refund_status": "completed",
            }).eq("id", cancellation_id).eq("tenant_id", tenant_id).execute()
        except Exception as exc:
            logger.warning(
                "[WOMPI] audit refund_completed_at update failed cid=%s: %s",
                cancellation_id, exc,
            )


def _notify_client_payment_approved(
    supabase, *, conversation_id: str, tenant_id: str, order_id: str
) -> None:
    """Etapa 1: pago APPROVED — confirmación inmediata sin tracking."""
    short_id = order_id[:8].upper()
    text = (
        f"*¡Pago confirmado!* ✅\n\n"
        f"Tu pedido *#{short_id}* está registrado. "
        f"Estamos preparando tu guía de envío — te aviso aquí mismo "
        f"cuando tu envío salga con el número de rastreo. "
        f"¡Gracias por tu compra!"
    )
    _enqueue_whatsapp_outbound(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        text=text, log_tag="WOMPI_WA_PAID",
    )


def _notify_client_shipment_label_ready(
    supabase, *, conversation_id: str, tenant_id: str, order_id: str,
    carrier: str, tracking_number: str, tracking_url: str,
) -> None:
    """Etapa 2 (post-guía Aveonline): GUÍA GENERADA (admin-state).

    NO promete "envío en camino" — la guía está lista pero el envío
    físico ocurre cuando el courier recoja + ponga EN RUTA. Esa
    confirmación llega vía webhook Aveonline `webhookEstadosGuias`
    en etapa 3 (in_transit → delivered).

    Mensaje breve + tracking number + link rastreo. Cliente sabe que
    el pedido está listo para despacho sin engaño sobre estado físico.
    """
    short_id = order_id[:8].upper()
    carrier_str = (carrier or "tu transportadora").strip()
    tracking_line = (
        f"\n\n🔍 *Rastrea tu envío*:\n{tracking_url}"
        if tracking_url else ""
    )
    text = (
        f"📋 *Guía asignada*\n\n"
        f"Tu pedido *#{short_id}* ya tiene guía con *{carrier_str}*.\n"
        f"Número: `{tracking_number}`\n\n"
        f"Te avisaré aquí cuando el courier recoja el paquete y vaya "
        f"en ruta hacia ti."
        f"{tracking_line}"
    )
    _enqueue_whatsapp_outbound(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        text=text, log_tag="WOMPI_WA_LABEL",
    )


def _notify_client_shipment_in_transit(
    supabase, *, conversation_id: str, tenant_id: str, order_id: str,
    carrier: str, tracking_number: str, tracking_url: str,
    raw_status: str = "",
) -> None:
    """Etapa 3 (post-webhook Aveonline EN RUTA): envío realmente despachado.

    Solo se llama desde el webhook handler de Aveonline cuando el courier
    confirma que el paquete salió a ruta. Garantiza verdad observable —
    nunca decimos "en camino" sin que el courier lo haya confirmado.
    """
    short_id = order_id[:8].upper()
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
    _enqueue_whatsapp_outbound(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        text=text, log_tag="WOMPI_WA_IN_TRANSIT",
    )


def _notify_client_shipment_delivered(
    supabase, *, conversation_id: str, tenant_id: str, order_id: str,
    carrier: str, tracking_number: str,
) -> None:
    """Etapa 4 (post-webhook Aveonline ENTREGADA): pedido entregado.

    Mensaje de cierre + invitación a feedback. Se llama solo desde
    aveonline_webhook cuando el courier reporta entrega.
    """
    short_id = order_id[:8].upper()
    carrier_str = (carrier or "el courier").strip()
    text = (
        f"📬 *Tu pedido fue entregado*\n\n"
        f"*#{short_id}* llegó vía *{carrier_str}* (guía `{tracking_number}`).\n\n"
        f"¿Todo llegó perfecto? Cuéntame por aquí, tu opinión nos "
        f"ayuda muchísimo. ¡Gracias por confiar en nosotros! 💛"
    )
    _enqueue_whatsapp_outbound(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        text=text, log_tag="WOMPI_WA_DELIVERED",
    )


def _notify_client_shipment_exception(
    supabase, *, conversation_id: str, tenant_id: str, order_id: str,
    carrier: str, tracking_number: str, raw_status: str = "",
) -> None:
    """Etapa novedad (post-webhook Aveonline EN NOVEDAD/DEVUELTA).

    Aviso al cliente — no promete solución automática (cada novedad
    puede requerir intervención humana). Inbox alerta a operador en
    paralelo.
    """
    short_id = order_id[:8].upper()
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
    _enqueue_whatsapp_outbound(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        text=text, log_tag="WOMPI_WA_EXCEPTION",
    )


_INTERNAL_STATUS_ES = {
    "pending": "En preparación",
    "pending_generation": "En preparación",
    "quoted": "En preparación",
    "simulated": "En preparación",
    "labeled": "Guía generada",
    "picked_up": "Recogido por el courier",
    "in_transit": "En camino",
    "delivered": "Entregado",
    "exception": "Novedad en la entrega",
    "returned": "Devuelto",
    "cancelled": "Cancelado",
}


def _humanize_shipment_status(raw_status: str = "", internal_status: str = "") -> str:
    """Etiqueta es-CO para el cliente.

    Prioridad:
      1. `raw_status` = nombre_estado real del courier (p. ej. "EN REPARTO",
         "CLIENTE AUSENTE"). Se presenta capitalizado (evita el ALL CAPS del
         courier) manteniendo paridad con la notificación WhatsApp.
      2. Traducción del enum canónico interno → es-CO (nunca inglés crudo).
    """
    rs = (raw_status or "").strip()
    if rs:
        return rs.capitalize() if rs.isupper() else rs
    return _INTERNAL_STATUS_ES.get((internal_status or "").strip().lower(), "")


def _send_payment_confirmation_email(
    supabase, *, order_id: str, tenant_id: str,
    template_mode: str = "payment_confirmed",
    raw_status: str = "",
) -> None:
    """Envía email al cliente con el detalle del pedido pagado.

    Best-effort: si falla por cualquier razón (RESEND_API_KEY ausente,
    contact sin email, network) NO bloquea el flow del webhook.

    `template_mode`:
      • "payment_confirmed" (etapa 1, post-Wompi APPROVED): email
        "Pago recibido" con desglose pedido + total. SIN tracking
        (aún no hay guía). Subject: "Pago recibido #{ID}".
      • "shipment_dispatched" (etapa 2, post-guía Aveonline OK): email
        "Tu envío está en camino" con tracking + carrier + botones
        rastrear/descargar guía. Subject: "Tu envío está en camino
        #{ID}".

    Lee Supabase de forma sync (httpx.Client) — `_process_wompi_event`
    es BackgroundTask sync. Evitamos asyncio.run() para mantener
    consistencia con el resto del handler.
    """
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        logger.info("[WOMPI][EMAIL] RESEND_API_KEY no configurada — skip")
        return

    # 1. Order + contact via JOIN.
    try:
        order_res = (
            supabase.table("orders")
            .select(
                "id, total_amount, shipping_cost, contact_id, "
                "contacts(name, email)"
            )
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        order = order_res.data or {}
    except Exception as exc:
        logger.warning("[WOMPI][EMAIL] error leyendo order: %s", exc)
        return

    contact = order.get("contacts") or {}
    email = (contact.get("email") or "").strip()
    if not email:
        logger.info(
            "[WOMPI][EMAIL] contact sin email order=%s — skip", order_id[:8],
        )
        return

    name = contact.get("name") or "cliente"
    total = int(float(order.get("total_amount") or 0))
    shipping = int(float(order.get("shipping_cost") or 0))
    subtotal = max(0, total - shipping)
    order_short = order_id.split("-")[0].upper()

    # 2. Order items para desglose.
    try:
        items_res = (
            supabase.table("order_items")
            .select("title, quantity, unit_price")
            .eq("order_id", order_id).eq("tenant_id", tenant_id)
            .execute()
        )
        items = items_res.data or []
    except Exception:
        items = []

    # 3. Tenant name.
    tenant_name = ""
    try:
        ten_res = (
            supabase.table("tenants")
            .select("name").eq("id", tenant_id).single().execute()
        )
        tenant_name = (ten_res.data or {}).get("name") or ""
    except Exception:
        pass

    # 4. Tracking info desde shipments (si guía paso 7.5 corrió OK).
    carrier = ""
    tracking_number = ""
    tracking_url = ""
    label_url = ""
    shipment_status = ""
    try:
        # Rev. 112 GAP — puede haber 2 filas por orden (fallo
        # pending_generation + retry con tracking). Ordenar por created_at desc
        # para leer la fila más reciente (la del retry exitoso con tracking),
        # evitando el email shipment_label_ready sin guía por leer la stale.
        sh_res = (
            supabase.table("shipments")
            .select("carrier, tracking_number, tracking_url, label_url, status")
            .eq("order_id", order_id).eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(1).execute()
        )
        sh = (sh_res.data or [{}])[0]
        carrier = sh.get("carrier") or ""
        tracking_number = sh.get("tracking_number") or ""
        tracking_url = sh.get("tracking_url") or ""
        label_url = sh.get("label_url") or ""
        shipment_status = sh.get("status") or ""
    except Exception:
        pass

    # Si modo "payment_confirmed" no incluimos tracking aunque exista
    # (el flow está orquestado para enviar pago primero, despacho después).
    if template_mode == "payment_confirmed":
        html = _compose_payment_email_html(
            customer_name=name, order_short=order_short, items=items,
            subtotal=subtotal, shipping=shipping, total=total,
            carrier=carrier, tenant_name=tenant_name,
            # NO tracking en etapa 1 — guía aún no generada.
            tracking_number="", tracking_url="", label_url="",
            shipment_status="",
        )
        subject = f"Pago recibido — Pedido #{order_short}"
    elif template_mode == "payment_failed":
        # Rev. 109 BRECHA email DECLINED: cliente debe saber por email +
        # WhatsApp que su pago no se procesó. Mantenemos copy empático,
        # sin asignar culpa, e invitamos a reintentar.
        html = _compose_payment_failed_email_html(
            customer_name=name, order_short=order_short, items=items,
            subtotal=subtotal, shipping=shipping, total=total,
            carrier=carrier, tenant_name=tenant_name,
        )
        subject = f"Pago no procesado — Pedido #{order_short}"
    elif template_mode == "shipment_label_ready":
        html = _compose_shipment_label_ready_email_html(
            customer_name=name, order_short=order_short, items=items,
            subtotal=subtotal, shipping=shipping, total=total,
            carrier=carrier, tenant_name=tenant_name,
            tracking_number=tracking_number, tracking_url=tracking_url,
            label_url=label_url, shipment_status=shipment_status,
        )
        subject = f"📋 Guía generada — Pedido #{order_short}"
    elif template_mode == "shipment_in_transit":
        html = _compose_shipment_in_transit_email_html(
            customer_name=name, order_short=order_short,
            carrier=carrier, tenant_name=tenant_name,
            tracking_number=tracking_number, tracking_url=tracking_url,
            raw_status=_humanize_shipment_status(raw_status, shipment_status),
        )
        subject = f"🚚 Tu envío salió en ruta — Pedido #{order_short}"
    elif template_mode == "shipment_delivered":
        html = _compose_shipment_delivered_email_html(
            customer_name=name, order_short=order_short,
            carrier=carrier, tenant_name=tenant_name,
            tracking_number=tracking_number,
        )
        subject = f"📬 Pedido entregado #{order_short}"
    elif template_mode == "shipment_exception":
        html = _compose_shipment_exception_email_html(
            customer_name=name, order_short=order_short,
            carrier=carrier, tenant_name=tenant_name,
            tracking_number=tracking_number,
            raw_status=_humanize_shipment_status(raw_status, shipment_status),
        )
        subject = f"⚠️ Novedad con tu envío — Pedido #{order_short}"
    elif template_mode == "refund_completed":
        # Rev. 109 fix UAT live BUG 33 — confirmación cliente que el void
        # llegó al ciclo bancario (status=VOIDED en Wompi). El dinero
        # aparece en su tarjeta en 1-2 días hábiles típicos post-VOIDED.
        # Rev. 112 GAP — extraído a composer (antes inline en el dispatcher:
        # inconsistencia estructural con los otros 6 templates).
        html = _compose_refund_completed_email_html(
            customer_name=name, order_short=order_short,
            total=total, tenant_name=tenant_name,
        )
        subject = f"✅ Reembolso confirmado — Pedido #{order_short}"
    else:
        # Default fallback: comportamiento previo (email único con todo).
        html = _compose_payment_email_html(
            customer_name=name, order_short=order_short, items=items,
            subtotal=subtotal, shipping=shipping, total=total,
            carrier=carrier, tenant_name=tenant_name,
            tracking_number=tracking_number, tracking_url=tracking_url,
            label_url=label_url, shipment_status=shipment_status,
        )
        subject = f"Confirmación pedido #{order_short} — {tenant_name or 'tu compra'}"

    # Default NO productivo (noreply@commerce-ops.local). El dominio remitente
    # productivo (verificado en Resend) es config externa → RESEND_FROM_EMAIL.
    from_email = os.getenv(
        "RESEND_FROM_EMAIL", "Konvi <noreply@commerce-ops.local>",
    )
    # Rev. 112 GAP — Idempotency-Key (Resend, doc §2.1 dossier: 256 chars,
    # expira 24 h). Determinístico por orden+etapa → un reprocesamiento de
    # webhook con checksum distinto NO duplica el email al cliente.
    idempotency_key = f"{tenant_id}:{order_id}:{template_mode}"[:256]
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key,
                },
                json={
                    "from": from_email,
                    "to": [email],
                    "subject": subject,
                    "html": html,
                    # Rev. 112 GAP — parte text/plain (mejor scoring anti-spam;
                    # multipart recomendado por Resend).
                    "text": _html_to_text(html),
                },
            )
        # Parseamos el id de Resend para trazabilidad (antes se descartaba).
        resend_id = ""
        try:
            resend_id = ((resp.json() or {}).get("id") or "")
        except Exception:
            resend_id = ""

        masked = _mask_email(email)
        if resp.status_code in (200, 202):
            logger.info(
                "[WOMPI][EMAIL] enviado to=%s order=%s mode=%s resend_id=%s",
                masked, order_id[:8], template_mode, resend_id or "?",
            )
        elif resp.status_code == 429:
            # Cuota (free tier 100/día) o rate-limit — señal distinta, alertable.
            logger.error(
                "[WOMPI][EMAIL] resend RATE/QUOTA 429 to=%s order=%s mode=%s body=%s",
                masked, order_id[:8], template_mode, resp.text[:200],
            )
        elif 400 <= resp.status_code < 500:
            # 4xx = config/payload (from no verificado, key inválida) — bug de
            # activación, requiere acción operador.
            logger.error(
                "[WOMPI][EMAIL] resend 4xx status=%s to=%s order=%s mode=%s body=%s",
                resp.status_code, masked, order_id[:8], template_mode,
                resp.text[:200],
            )
        else:
            # 5xx = Resend caído — transitorio (Wompi/Aveonline reintentan el
            # webhook; el Idempotency-Key evita duplicar si el 5xx fue parcial).
            logger.error(
                "[WOMPI][EMAIL] resend 5xx status=%s to=%s order=%s mode=%s body=%s",
                resp.status_code, masked, order_id[:8], template_mode,
                resp.text[:200],
            )
    except Exception as exc:
        logger.warning(
            "[WOMPI][EMAIL] httpx err to=%s order=%s mode=%s: %s",
            _mask_email(email), order_id[:8], template_mode, exc,
        )

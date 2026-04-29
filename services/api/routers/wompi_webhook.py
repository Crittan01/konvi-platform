"""
Webhook de Wompi — receptor de eventos de pago.

Flujo:
  1. Wompi hace POST → respondemos 200 inmediatamente
  2. BackgroundTask valida firma y procesa el evento de forma asíncrona
  3. Si APPROVED: confirma order + descuenta stock + notifica cliente vía WhatsApp

Política de reintentos de Wompi:
  Si no recibe 2xx: reintenta en 30 min, 3 h y 24 h (máx 3 intentos).

Referencia oficial: https://docs.wompi.co/en/docs/colombia/eventos/
Algoritmo de firma validado 2026-04-24 — SHA256 simple, no HMAC.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client
from integrations.wompi_client import verify_event_signature, get_tenant_wompi_creds, create_payment_link_sync

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Wompi Webhook"])

WOMPI_TXN_APPROVED = "APPROVED"
WOMPI_RETRY_STATUSES = {"DECLINED", "ERROR", "VOIDED"}
WOMPI_PAYMENT_LINK_TTL_MINUTES = int(os.getenv("WOMPI_PAYMENT_LINK_TTL_MINUTES", "30"))


@router.post("/wompi")
async def wompi_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe eventos de Wompi. Responde 200 inmediatamente.
    El procesamiento real ocurre en BackgroundTask.
    """
    try:
        payload = await request.json()
    except Exception:
        # Wompi envía JSON; body inválido no debe provocar retry en su lado
        return JSONResponse(status_code=200, content={"received": True})

    background_tasks.add_task(_process_wompi_event, payload)
    return JSONResponse(status_code=200, content={"received": True})


def _process_wompi_event(payload: dict) -> None:
    event_name = payload.get("event", "")

    # ── 1. Solo procesar transaction.updated (antes de cualquier DB lookup) ──
    if event_name != "transaction.updated":
        logger.info("[WOMPI] evento_ignorado event=%s", event_name)
        return

    txn = payload.get("data", {}).get("transaction", {})
    txn_id = txn.get("id", "")
    # Identificador único del evento. Wompi no expone formalmente `event.id`
    # en docs públicas — el `signature.checksum` es la mejor alternativa
    # (cambia con cada payload exacto). Si el merchant ya procesó este
    # checksum, el evento es duplicado.
    sig = payload.get("signature", {}) or {}
    event_uid = (sig.get("checksum") or "").strip()
    txn_status = txn.get("status", "")
    amount_in_cents = txn.get("amount_in_cents", 0)
    payment_link_id = txn.get("payment_link_id")
    wompi_reference = txn.get("reference", "")

    logger.info(
        "[WOMPI] evento_recibido txn_id=%s status=%s link=%s ref=%s amount_cents=%s",
        txn_id, txn_status, payment_link_id, wompi_reference, amount_in_cents,
    )

    supabase = _get_service_client()

    # ── 2. Correlacionar payment_link_id → order_id → tenant_id ──────────────
    # Necesitamos el tenant_id para cargar su events_key desde Vault y verificar la firma.
    # El SELECT es de solo lectura; si el link no existe, la firma fallará igualmente.
    order_id = _get_order_id_by_link(supabase, payment_link_id) if payment_link_id else None
    tenant_id_for_sig: str | None = None
    if order_id:
        order_preview = _get_order_by_id(supabase, order_id)
        tenant_id_for_sig = (order_preview or {}).get("tenant_id")

    # ── 3. Verificar firma con events_key del tenant ──────────────────────────
    events_key: str = ""
    if tenant_id_for_sig:
        _, events_key_val, _ = get_tenant_wompi_creds(supabase, tenant_id_for_sig)
        events_key = events_key_val or ""
    if not verify_event_signature(payload, events_key):
        logger.warning("[WOMPI] firma_invalida event=%s link=%s tenant=%s", event_name, payment_link_id, tenant_id_for_sig)
        return

    # ── 3.5. Dedup de eventos duplicados por checksum (Wompi reintenta en
    # 30m/3h/24h cuando merchant responde no-2xx; la firma SHA256 del payload
    # es el identificador más confiable porque no se documenta `event.id`
    # estable). INSERT con ON CONFLICT DO NOTHING — si la fila ya existía,
    # `data` viene vacía y descartamos el evento.
    if event_uid and tenant_id_for_sig:
        try:
            supabase.table("wompi_events_seen").insert({
                "event_id": event_uid,
                "tenant_id": tenant_id_for_sig,
                "event_type": event_name,
                "transaction_id": txn_id or None,
                "reference": wompi_reference or None,
                "status": txn_status or None,
            }).execute()
        except Exception as exc:
            # Confiamos SOLO en la excepción de PK duplicada para descartar.
            # Postgres levanta SQLSTATE 23505; postgrest mapea a APIError con
            # "duplicate key" en el mensaje.
            msg = str(exc)
            if "duplicate key" in msg or "23505" in msg:
                logger.info(
                    "[WOMPI] evento_duplicado checksum=%s txn=%s — descartado por dedup",
                    event_uid[:12], txn_id,
                )
                return
            # Cualquier otro error (red, schema, mock test sin tabla): NO
            # bloquear procesamiento — la idempotencia upstream (orden ya
            # confirmed → skip) protege de doble decremento.
            logger.warning(
                "[WOMPI] dedup_check_failed checksum=%s err=%s — continúa procesamiento",
                event_uid[:12], exc,
            )

    # ── 4. Registrar/actualizar pago en tabla payments (idempotente por txn_id) ─
    try:
        was_duplicate = _upsert_payment_record(
            supabase=supabase,
            wompi_txn_id=txn_id,
            wompi_link_id=payment_link_id,
            order_id=order_id,
            amount_in_cents=amount_in_cents,
            wompi_status=txn_status,
            raw_webhook=payload,
        )
        if was_duplicate:
            logger.info("[WOMPI] pago_replay txn_id=%s status=%s — registro ya existía, actualizado", txn_id, txn_status)
    except Exception as e:
        logger.error("[WOMPI] error_upsert_pago txn_id=%s error=%s", txn_id, e)

    if txn_status != WOMPI_TXN_APPROVED:
        logger.info("[WOMPI] pago_no_aprobado txn_id=%s status=%s", txn_id, txn_status)
        # Para DECLINED/ERROR/VOIDED: si la orden sigue en pending_payment, ofrecer reintento
        if txn_status in WOMPI_RETRY_STATUSES and order_id:
            _maybe_offer_payment_retry(supabase, order_id=order_id, txn_status=txn_status)
        return

    # ── 5. Verificar que encontramos la orden ─────────────────────────────────
    if not order_id:
        logger.warning("[WOMPI] pago_sin_orden txn_id=%s link=%s — APPROVED pero sin order_id correlacionado", txn_id, payment_link_id)
        return

    order = _get_order_by_id(supabase, order_id)
    if not order:
        logger.warning("[WOMPI] orden_no_encontrada order_id=%s txn_id=%s", order_id, txn_id)
        return

    order_id = order["id"]
    tenant_id = order["tenant_id"]
    conversation_id = order.get("conversation_id")
    current_status = order.get("status", "")

    # Guard idempotente: si la orden ya fue confirmada, Wompi puede reintentar el webhook
    if current_status == "confirmed":
        logger.info(
            "[WOMPI] orden_ya_confirmada order_id=%s txn_id=%s — idempotente, skip",
            order_id, txn_id,
        )
        return

    # ── 6. Confirmar orden y descontar stock ──────────────────────────────────
    try:
        _confirm_order(supabase, order_id, tenant_id)
        logger.info("[WOMPI] orden_confirmada order_id=%s txn_id=%s tenant=%s", order_id, txn_id, tenant_id)
    except Exception as e:
        logger.error("[WOMPI] error_confirmando_orden order_id=%s txn_id=%s error=%s", order_id, txn_id, e)
        return

    # ── 7. Notificar al cliente vía WhatsApp (outbound queue) ─────────────────
    if conversation_id:
        try:
            _notify_client_payment_approved(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                order_id=order_id,
            )
            logger.info("[WOMPI] notificacion_encolada conv=%s order=%s", conversation_id, order_id)
        except Exception as e:
            logger.error("[WOMPI] error_notificacion conv=%s order=%s error=%s", conversation_id, order_id, e)
    else:
        logger.info("[WOMPI] sin_conversation_id order=%s — sin notificación WhatsApp", order_id)

    # ── 8. Marcar el evento como procesado (audit trail). Si falla este UPDATE
    # no es crítico — el dedup ya bloqueó duplicados al inicio.
    if event_uid:
        try:
            supabase.table("wompi_events_seen").update(
                {"processed_at": datetime.now(timezone.utc).isoformat()}
            ).eq("event_id", event_uid).execute()
        except Exception as exc:
            logger.warning("[WOMPI] dedup_mark_processed_failed checksum=%s err=%s", event_uid[:12], exc)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _maybe_offer_payment_retry(supabase, *, order_id: str, txn_status: str) -> None:
    """
    Si el pedido sigue en pending_payment y tiene conversación asociada,
    intenta generar un nuevo link de pago y notificar al cliente.
    Idempotente: si la orden ya fue cancelada o confirmada, no hace nada.
    """
    order = _get_order_by_id(supabase, order_id)
    if not order:
        return
    if order.get("status") != "pending_payment":
        logger.info(
            "[WOMPI] retry_skip order=%s status=%s — no está en pending_payment",
            order_id, order.get("status"),
        )
        return

    conversation_id = order.get("conversation_id")
    tenant_id = order.get("tenant_id")
    if not conversation_id or not tenant_id:
        logger.info("[WOMPI] retry_skip order=%s — sin conversation_id o tenant_id", order_id)
        return

    logger.info("[WOMPI] iniciando_retry order=%s txn_status=%s", order_id, txn_status)
    try:
        private_key, _, environment = get_tenant_wompi_creds(supabase, tenant_id)
        if not private_key:
            logger.warning("[WOMPI] retry_sin_clave order=%s tenant=%s — notificando fallo sin nuevo link", order_id, tenant_id)
            _enqueue_payment_failed_msg(supabase, conversation_id=conversation_id, tenant_id=tenant_id, order_id=order_id)
            return

        total_amount = float(order.get("total_amount") or 0)
        amount_in_cents = int(total_amount * 100)
        if amount_in_cents < 150_000:
            logger.warning("[WOMPI] retry_monto_bajo order=%s amount=%s", order_id, amount_in_cents)
            _enqueue_payment_failed_msg(supabase, conversation_id=conversation_id, tenant_id=tenant_id, order_id=order_id)
            return

        # Obtener contacto completo para customer_data Wompi (rev. 68)
        contact_res = (
            supabase.table("orders")
            .select("contacts(name, phone, email, document_type, document_number)")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        contact = ((contact_res.data or [{}])[0].get("contacts") or {})
        contact_name = contact.get("name") or "Cliente"

        short_id = order_id[:8].upper()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=WOMPI_PAYMENT_LINK_TTL_MINUTES)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        link_data = create_payment_link_sync(
            private_key=private_key,
            environment=environment,
            order_id=order_id,
            name=f"Pedido #{short_id} — {contact_name}"[:100],
            description=f"Reintento pedido #{short_id}",
            amount_in_cents=amount_in_cents,
            expires_at=expires_at,
            contact=contact,  # rev. 68
        )

        supabase.table("payments").insert({
            "tenant_id": tenant_id,
            "order_id": order_id,
            "provider": "wompi",
            "wompi_link_id": link_data["link_id"],
            "checkout_url": link_data["checkout_url"],
            "amount_in_cents": amount_in_cents,
            "currency": "COP",
            "status": "pending",
            "wompi_status": "ACTIVE",
        }).execute()

        text = (
            f"⚠️ Hubo un inconveniente con tu pago del pedido *#{short_id}*.\n\n"
            f"No te preocupes, aquí tienes un nuevo enlace:\n"
            f"💳 {link_data['checkout_url']}\n\n"
            f"⏰ Válido por {WOMPI_PAYMENT_LINK_TTL_MINUTES} minutos."
        )
        _enqueue_outbound_text(supabase, conversation_id=conversation_id, tenant_id=tenant_id, text=text)
        logger.info("[WOMPI] retry_link_enviado order=%s link_id=%s", order_id, link_data["link_id"])

    except Exception as e:
        logger.error("[WOMPI] error_retry order=%s error=%s", order_id, e)
        _enqueue_payment_failed_msg(supabase, conversation_id=conversation_id, tenant_id=tenant_id, order_id=order_id)


_PAYMENT_FAILED_VARIANTS = [
    "Hmm, tu pago del pedido *#{short_id}* no se completó. 😕\n\nSi quieres, te conecto con un {role} para terminar la compra juntos.",
    "El pago del pedido *#{short_id}* no pasó esta vez. 🙏\n\nDime si prefieres que un {role} te acompañe a destrabarlo o intentarlo de nuevo.",
    "Tu pago del pedido *#{short_id}* quedó pendiente.\n\n¿Te gustaría que un {role} te ayude a finalizar la compra?",
]


def _get_tenant_escalation_role(supabase, tenant_id: str) -> str:
    """Lee tenants.escalation_role (asesor/especialista/consultor/agente).
    Default 'asesor' si no está configurado o falla la consulta.
    """
    try:
        r = supabase.table("tenants").select("escalation_role").eq("id", tenant_id).limit(1).execute()
        if r.data and r.data[0].get("escalation_role"):
            return str(r.data[0]["escalation_role"]).strip().lower() or "asesor"
    except Exception:
        pass
    return "asesor"


def _enqueue_payment_failed_msg(supabase, *, conversation_id: str, tenant_id: str, order_id: str) -> None:
    """Encola mensaje de pago fallido. 3 variantes rotativas por order_id (estable).
    Usa el escalation_role configurado por tenant (asesor/especialista/consultor/agente)."""
    import hashlib
    short_id = order_id[:8].upper()
    idx = int(hashlib.md5(order_id.encode("utf-8")).hexdigest(), 16) % len(_PAYMENT_FAILED_VARIANTS)
    role = _get_tenant_escalation_role(supabase, tenant_id)
    text = _PAYMENT_FAILED_VARIANTS[idx].format(short_id=short_id, role=role)
    _enqueue_outbound_text(supabase, conversation_id=conversation_id, tenant_id=tenant_id, text=text)


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


def _upsert_payment_record(
    supabase,
    *,
    wompi_txn_id: str,
    wompi_link_id,
    order_id: str,
    amount_in_cents: int,
    wompi_status: str,
    raw_webhook: dict,
) -> bool:
    """Persiste/actualiza el pago. Retorna True si era un registro existente (replay)."""
    existing = None
    if wompi_txn_id:
        res = (
            supabase.table("payments")
            .select("id, tenant_id")
            .eq("wompi_txn_id", wompi_txn_id)
            .limit(1)
            .execute()
        )
        existing = (res.data or [None])[0]

    if existing:
        supabase.table("payments").update({
            "wompi_status": wompi_status,
            "status": "approved" if wompi_status == WOMPI_TXN_APPROVED else wompi_status.lower(),
            "raw_webhook": raw_webhook,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", existing["id"]).execute()
        return True  # replay: registro ya existía

    if not order_id:
        logger.warning("[WOMPI] sin_order_id_para_insert txn_id=%s — payment no registrado", wompi_txn_id)
        return False

    order_res = (
        supabase.table("orders")
        .select("tenant_id")
        .eq("id", order_id)
        .limit(1)
        .execute()
    )
    tenant_id = (order_res.data or [{}])[0].get("tenant_id", "")
    if not tenant_id:
        logger.warning("[WOMPI] sin_tenant_id order_id=%s — payment no registrado", order_id)
        return False

    supabase.table("payments").insert({
        "tenant_id": tenant_id,
        "order_id": order_id,
        "provider": "wompi",
        "wompi_link_id": wompi_link_id,
        "wompi_txn_id": wompi_txn_id,
        "amount_in_cents": amount_in_cents,
        "currency": "COP",
        "wompi_status": wompi_status,
        "status": "approved" if wompi_status == WOMPI_TXN_APPROVED else "pending",
        "raw_webhook": raw_webhook,
    }).execute()
    return False  # nuevo registro


def _get_order_id_by_link(supabase, wompi_link_id: str):
    """Resuelve order_id desde wompi_link_id via tabla payments."""
    try:
        res = (
            supabase.table("payments")
            .select("order_id")
            .eq("wompi_link_id", wompi_link_id)
            .limit(1)
            .execute()
        )
        data = res.data or []
        return data[0]["order_id"] if data else None
    except Exception as e:
        logger.error("[WOMPI] Error resolviendo order por link %s: %s", wompi_link_id, e)
        return None


def _get_order_by_id(supabase, order_id: str):
    try:
        res = (
            supabase.table("orders")
            .select("id, tenant_id, status, conversation_id, contact_id")
            .eq("id", order_id)
            .limit(1)
            .execute()
        )
        return (res.data or [None])[0]
    except Exception as e:
        logger.error("[WOMPI] Error buscando order %s: %s", order_id, e)
        return None


def _confirm_order(supabase, order_id: str, tenant_id: str) -> None:
    from routers.orders import _decrement_stock_on_confirm

    supabase.table("orders").update({
        "status": "confirmed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).eq("tenant_id", tenant_id).execute()

    _decrement_stock_on_confirm(supabase, order_id, tenant_id)


def _notify_client_payment_approved(
    supabase, *, conversation_id: str, tenant_id: str, order_id: str
) -> None:
    short_id = order_id[:8].upper()
    text = (
        f"✅ *¡Pago confirmado!*\n\n"
        f"Tu pedido *#{short_id}* está registrado y en preparación. "
        f"Pronto te enviamos información de tu envío. ¡Gracias por tu compra! 🎉"
    )

    # Persistir mensaje outbound
    msg_insert = supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "content_type": "text",
        "content": text,
        "processed": False,
        "processing_status": "pending",
    }).execute()

    if not (msg_insert.data):
        logger.warning("[WOMPI] No se pudo persistir mensaje outbound para conv %s", conversation_id)
        return

    new_msg = msg_insert.data[0]

    # Obtener customer_phone de la conversación
    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    conv = (conv_res.data or [{}])[0]
    customer_phone = conv.get("customer_phone", "")
    if not customer_phone:
        logger.warning("[WOMPI] Sin customer_phone para conv %s — skip outbound", conversation_id)
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
    logger.info("[WOMPI] Notificación de pago encolada para conv %s", conversation_id)

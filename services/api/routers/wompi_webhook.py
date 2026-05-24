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

    # ── 2.5. Detección de webhook huérfano (Capa C) ──────────────────────────
    # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (Opción A+C):
    # Cuando el operador eliminaba un contacto que tenía un payment_link
    # Wompi activo (TTL ~30 min) y el cliente pagaba ese link después de
    # eliminado, Wompi enviaba el webhook APPROVED pero NUESTRA DB ya no
    # tenía el `payments` row → `order_id=None`. Antes este caso producía
    # un misleading "firma_invalida" log (no se puede verificar sin
    # `events_key` del tenant). Wompi NO expone endpoint para invalidar
    # payment_links → única defensa = guard de purga (Capa A) + audit log
    # claro aquí para reconciliación manual con dashboard Wompi.
    #
    # La Capa A previene NUEVOS huérfanos. Esta Capa C captura:
    #   - Huérfanos legacy (purges previas a 2026-05-21).
    #   - Race conditions extremas (purge entre check y delete).
    #   - Webhooks fraudulentos con payment_link_id inexistente (atacante).
    #
    # No persistimos en tabla porque `wompi_events_seen.tenant_id` es
    # NOT NULL. El log con prefijo `[WOMPI][ORPHAN]` es greppable para
    # auditoría. Si reconciliación se vuelve regular, crear tabla
    # `wompi_orphan_events` en migration futura.
    if payment_link_id and not order_id:
        logger.warning(
            "[WOMPI][ORPHAN] webhook_sin_orden link=%s txn_id=%s ref=%s "
            "status=%s amount_cents=%s — Wompi reporta pago pero no hay "
            "fila `payments` que matchee (contacto purgado o link inválido). "
            "Reconciliar manualmente con dashboard Wompi si APPROVED.",
            payment_link_id, txn_id, wompi_reference, txn_status, amount_in_cents,
        )
        return

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
        # Para DECLINED/ERROR/VOIDED: liberar reservas activas + ofrecer reintento.
        if txn_status in WOMPI_RETRY_STATUSES and order_id:
            _release_stock_reservations_for_order(supabase, order_id=order_id, txn_status=txn_status)
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

    # Guard idempotente: si la orden está en estado terminal, NO la reabrimos.
    # Estados terminales: 'confirmed' (pago OK) y 'cancelled' (cliente canceló
    # o flujo descartó). Un APPROVED tardío (rev. 79) no debe reabrir una
    # orden cancelada — sería incoherente con los datos del cliente.
    TERMINAL_STATES = {"confirmed", "cancelled"}
    if current_status in TERMINAL_STATES:
        logger.info(
            "[WOMPI] orden_estado_terminal order_id=%s txn_id=%s status=%s — idempotente, skip",
            order_id, txn_id, current_status,
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

    # ── 7.5. Email Etapa 1: "Pago recibido" (Resend, best-effort) ─────────────
    # Inmediato — desglose pedido + total. SIN tracking (guía aún no
    # generada). Founder UX 2026-05-24: separar pago de envío en 2 emails
    # estilo Amazon/MercadoLibre. Mejor UX si Aveonline falla — cliente
    # igual tiene confirmación pago.
    try:
        _send_payment_confirmation_email(
            supabase=supabase, order_id=order_id, tenant_id=tenant_id,
            template_mode="payment_confirmed",
        )
    except Exception as e:
        logger.warning(
            "[WOMPI][EMAIL] payment_confirmed falló order=%s err=%s",
            order_id, e,
        )

    # ── 7.6. Generación guía Aveonline (best-effort, ~10-15s) ─────────────────
    # simulate=True por default — tenant setea AVEONLINE_GENERATE_REAL_GUIDES
    # =true para guías facturables reales.
    guide_ok = False
    try:
        guide_ok = _generate_shipping_guide(
            supabase=supabase, order_id=order_id, tenant_id=tenant_id,
        ) is True
    except Exception as e:
        logger.warning(
            "[WOMPI][AVEONLINE] generación guía falló order=%s err=%s",
            order_id, e,
        )

    # ── 7.7. Etapa 2 (solo si guía OK): Email + WhatsApp "Envío en camino" ────
    # Si Aveonline rechazó la guía → cliente solo recibe email/WA pago
    # confirmado (etapa 1). El operador puede generar manual desde Inbox.
    if guide_ok:
        try:
            _send_payment_confirmation_email(
                supabase=supabase, order_id=order_id, tenant_id=tenant_id,
                template_mode="shipment_dispatched",
            )
        except Exception as e:
            logger.warning(
                "[WOMPI][EMAIL] shipment_dispatched falló order=%s err=%s",
                order_id, e,
            )
        # Notif WhatsApp con tracking — lee shipment row recién creado.
        try:
            sh_res = (
                supabase.table("shipments")
                .select("carrier, tracking_number, tracking_url")
                .eq("order_id", order_id).limit(1).execute()
            )
            sh_row = (sh_res.data or [{}])[0]
            if conversation_id and sh_row.get("tracking_number"):
                _notify_client_shipment_dispatched(
                    supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    order_id=order_id,
                    carrier=sh_row.get("carrier") or "",
                    tracking_number=sh_row.get("tracking_number") or "",
                    tracking_url=sh_row.get("tracking_url") or "",
                )
        except Exception as e:
            logger.warning(
                "[WOMPI_WA_SHIPPED] notif envío en camino falló "
                "order=%s err=%s", order_id, e,
            )

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

def _release_stock_reservations_for_order(supabase, *, order_id: str, txn_status: str) -> None:
    """
    Rev. 78 — Libera reservas activas vinculadas a la conversación de la orden
    cuando Wompi notifica DECLINED/VOIDED/ERROR. Sin esto, el stock queda
    bloqueado hasta el TTL 35min aunque el pago ya falló definitivamente.

    Idempotente: el RPC solo afecta filas status='active'.
    """
    order = _get_order_by_id(supabase, order_id)
    if not order:
        return
    conversation_id = order.get("conversation_id")
    if not conversation_id:
        logger.info(
            "[WOMPI] release_skip order=%s — sin conversation_id, no hay reservas a liberar",
            order_id,
        )
        return
    try:
        res = supabase.rpc(
            "rpc_stock_reservation_release_by_conversation",
            {"p_conversation_id": conversation_id},
        ).execute()
        released = res.data if isinstance(res.data, int) else (res.data or 0)
        logger.info(
            "[WOMPI] reservas_liberadas order=%s conv=%s status=%s count=%s",
            order_id, conversation_id, txn_status, released,
        )
    except Exception as exc:
        logger.error(
            "[WOMPI] error_liberando_reservas order=%s conv=%s err=%s",
            order_id, conversation_id, exc,
        )


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
    """Persiste/actualiza el pago. Retorna True si era un registro existente (replay).

    Rev. 104 (F0-2 / BUG-3): el lookup busca por `wompi_txn_id` Y por
    `wompi_link_id`. Antes solo buscaba por `wompi_txn_id`, ignorando que
    `payment_link_tool` crea la fila inicial con `wompi_link_id` poblado y
    `wompi_txn_id=NULL`. Cuando el webhook APPROVED llegaba, el SELECT
    fallaba → INSERT chocaba con UNIQUE → orden quedaba en `confirmed`
    pero `payments.status='PENDING'` (auditabilidad rota).
    """
    existing = None
    # 1) Lookup por wompi_txn_id (replay del mismo evento).
    if wompi_txn_id:
        res = (
            supabase.table("payments")
            .select("id, tenant_id")
            .eq("wompi_txn_id", wompi_txn_id)
            .limit(1)
            .execute()
        )
        existing = (res.data or [None])[0]

    # 2) Si no encontró por txn_id, buscar por wompi_link_id (fila pre-existente
    #    creada por payment_link_tool con txn_id NULL — primer webhook APPROVED).
    if not existing and wompi_link_id and order_id:
        res = (
            supabase.table("payments")
            .select("id, tenant_id, wompi_txn_id")
            .eq("order_id", order_id)
            .eq("wompi_link_id", wompi_link_id)
            .limit(1)
            .execute()
        )
        existing = (res.data or [None])[0]

    if existing:
        # Update: incluye wompi_txn_id si la fila lo tenía NULL (primer hit).
        update_payload = {
            "wompi_status": wompi_status,
            "status": "approved" if wompi_status == WOMPI_TXN_APPROVED else wompi_status.lower(),
            "raw_webhook": raw_webhook,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if wompi_txn_id and not existing.get("wompi_txn_id"):
            update_payload["wompi_txn_id"] = wompi_txn_id
        supabase.table("payments").update(update_payload).eq("id", existing["id"]).execute()
        return True  # replay o complete-pre-existing

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


def _notify_client_shipment_dispatched(
    supabase, *, conversation_id: str, tenant_id: str, order_id: str,
    carrier: str, tracking_number: str, tracking_url: str,
    eta: str = "",
) -> None:
    """Etapa 2: guía Aveonline generada — confirma envío + tracking real.

    Mensaje natural separado del de pago. Cliente recibe primero
    "Pago confirmado" inmediato, después este cuando la guía esté lista
    (~14s en promedio). Mantiene momentum + transparencia.
    """
    short_id = order_id[:8].upper()
    eta_str = f" (entrega estimada: {eta})" if eta else ""
    carrier_str = (carrier or "tu transportadora").strip()
    tracking_line = (
        f"\n\n🔍 *Rastrea tu envío*:\n{tracking_url}"
        if tracking_url else ""
    )
    text = (
        f"📦 *Tu envío está en camino*\n\n"
        f"Pedido *#{short_id}* salió con *{carrier_str}*{eta_str}.\n"
        f"Guía: `{tracking_number}`"
        f"{tracking_line}"
    )
    _enqueue_whatsapp_outbound(
        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        text=text, log_tag="WOMPI_WA_SHIPPED",
    )


# ─── Email post-pago al cliente (Rev. 107) ────────────────────────────────────

def _send_payment_confirmation_email(
    supabase, *, order_id: str, tenant_id: str,
    template_mode: str = "payment_confirmed",
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
            .eq("order_id", order_id)
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
        sh_res = (
            supabase.table("shipments")
            .select("carrier, tracking_number, tracking_url, label_url, status")
            .eq("order_id", order_id)
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
    elif template_mode == "shipment_dispatched":
        html = _compose_shipment_dispatched_email_html(
            customer_name=name, order_short=order_short, items=items,
            subtotal=subtotal, shipping=shipping, total=total,
            carrier=carrier, tenant_name=tenant_name,
            tracking_number=tracking_number, tracking_url=tracking_url,
            label_url=label_url, shipment_status=shipment_status,
        )
        subject = f"📦 Tu envío está en camino — Pedido #{order_short}"
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

    from_email = os.getenv(
        "RESEND_FROM_EMAIL", "Konvi <noreply@commerce-ops.local>",
    )
    import httpx
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
                    "to": [email],
                    "subject": subject,
                    "html": html,
                },
            )
        if resp.status_code in (200, 202):
            logger.info(
                "[WOMPI][EMAIL] enviado a=%s order=%s",
                email, order_id[:8],
            )
        else:
            logger.warning(
                "[WOMPI][EMAIL] resend status=%s body=%s",
                resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        logger.warning("[WOMPI][EMAIL] httpx err: %s", exc)


# ─── Guía Aveonline post-pago (Rev. 107) ──────────────────────────────────────

def _generate_shipping_guide(
    supabase, *, order_id: str, tenant_id: str,
) -> bool:
    """Genera guía Aveonline tras pago APPROVED (best-effort).

    Solo aplica si el tenant tiene `tenant_shipping_provider_config.
    active_provider='aveonline'`. Si está en 'envia' o cualquier otro,
    skip (los demás providers tienen su propia mecánica).

    simulate=True por default → NO factura. Tenant setea
    AVEONLINE_GENERATE_REAL_GUIDES=true (env) cuando esté listo.

    Best-effort: si falla, log warning + persiste row pending en
    shipments para que operador genere manual desde Inbox.

    Returns:
        True si guía generó OK + shipment persistido con tracking_number
        (caller dispara etapa 2: email "envío en camino" + WA tracking).
        False si skip (provider != aveonline / contact incompleto /
        Aveonline rechazó). Caller no dispara etapa 2.
    """
    # 1. Provider check.
    try:
        cfg = (
            supabase.table("tenant_shipping_provider_config")
            .select("active_provider")
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        provider = ((cfg.data or {}).get("active_provider") or "").lower()
    except Exception:
        provider = ""

    if provider != "aveonline":
        logger.info(
            "[WOMPI][AVEONLINE] tenant=%s provider=%s — skip guía (no aveonline)",
            tenant_id, provider or "none",
        )
        return False

    # 2. Cargar order + contact + tenant shipping_origin + shipping_meta.
    try:
        order_res = (
            supabase.table("orders")
            .select(
                "id, total_amount, shipping_cost, contact_id, "
                "contacts(name, email, phone, shipping_phone, "
                "document_type, document_number, address)"
            )
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        order = order_res.data or {}
    except Exception as exc:
        logger.warning("[WOMPI][AVEONLINE] no pude leer order: %s", exc)
        return False

    contact = order.get("contacts") or {}
    if not contact.get("name") or not contact.get("phone"):
        logger.info(
            "[WOMPI][AVEONLINE] order=%s contact incompleto — skip guía",
            order_id[:8],
        )
        return False

    addr = contact.get("address") or {}
    # Bug runtime KAIU 2026-05-24: schema mismatch — contacts.address usa
    # `line1` (canónico), tenants.shipping_origin usa `street`. Aquí
    # tomamos `line1` con fallback a `street` para tolerar ambos.
    addr_street = addr.get("line1") or addr.get("street") or ""
    if not addr.get("city") or not addr_street:
        logger.info(
            "[WOMPI][AVEONLINE] order=%s sin dirección — skip guía "
            "(addr keys=%s)",
            order_id[:8], list(addr.keys()),
        )
        return False

    # 3. Tenant shipping_origin (sender).
    try:
        ten = (
            supabase.table("tenants")
            .select("name, shipping_origin, telefono_contacto, email_contacto, nit")
            .eq("id", tenant_id).single().execute()
        )
        tenant = ten.data or {}
    except Exception:
        tenant = {}

    origin = tenant.get("shipping_origin") or {}
    if not origin.get("city") or not origin.get("street"):
        logger.warning(
            "[WOMPI][AVEONLINE] tenant=%s sin shipping_origin completo — skip",
            tenant_id[:8],
        )
        return False

    # 4. Cart shipping_meta → idtransportador (rate_id).
    try:
        cart = (
            supabase.table("conversation_carts")
            .select("shipping_meta")
            .eq("tenant_id", tenant_id)
            .order("updated_at", desc=True).limit(1).execute()
        )
        sm = ((cart.data or [{}])[0]).get("shipping_meta") or {}
    except Exception:
        sm = {}

    carrier_rate_id = sm.get("rate_id") or ""
    # Rev. 107 — persistir carrier_name real (SERVIENTREGA/ENVIA/etc.)
    # en lugar del provider name ("aveonline"). El cliente espera ver
    # "Envío SERVIENTREGA $7.530" en resumen post-pago, no "aveonline".
    selected_carrier_name = (sm.get("carrier") or "").strip()
    if not carrier_rate_id:
        logger.warning(
            "[WOMPI][AVEONLINE] order=%s sin carrier rate_id — skip",
            order_id[:8],
        )
        return False

    # 5. Construir payload + invocar generate_guide.
    import asyncio
    try:
        from integrations.aveonline_client import AveonlineClient

        cli = AveonlineClient(tenant_id, supabase)

        addr_full = " ".join(filter(None, [
            addr_street,
            f"apto {addr['apartment']}" if addr.get("apartment") else None,
            addr.get("building_type") or None,
            f"torre {addr['tower']}" if addr.get("tower") else None,
        ]))

        sender = {
            "nit": tenant.get("nit") or "",
            "nombre": (origin.get("name") or tenant.get("name") or "")[:80],
            "direccion": origin.get("street") or "",
            "barrio": "",
            "telefono": tenant.get("telefono_contacto") or origin.get("phone") or "",
            "celular": tenant.get("telefono_contacto") or origin.get("phone") or "",
            "email": tenant.get("email_contacto") or "",
        }
        recipient = {
            "doc": contact.get("document_number") or "",
            "nombre": contact.get("name") or "",
            "direccion": addr_full or addr.get("street") or "",
            "barrio": addr.get("neighborhood") or "",
            "telefono": (contact.get("shipping_phone") or contact.get("phone") or "").lstrip("+"),
            "celular": (contact.get("shipping_phone") or contact.get("phone") or "").lstrip("+"),
            "email": contact.get("email") or "",
        }
        package = {
            "weight_kg": 0.5,  # default conservador (KAIU son productos pequeños)
            "length_cm": 15, "width_cm": 10, "height_cm": 5,
            "declared_value_cop": int(float(order.get("total_amount") or 0)),
            "units": 1,
            "content": "Productos cosmética artesanal",
        }
        simulate = os.getenv("AVEONLINE_GENERATE_REAL_GUIDES", "false").lower() != "true"

        # Bug runtime KAIU 2026-05-24: Aveonline rechaza city raw
        # ("Bogotá D.C." → "No se pudo generar la guia."). Requiere
        # formato canónico "BOGOTA(CUNDINAMARCA)". Aplicamos el mismo
        # normalizador del cotizador para coherencia origin/destination.
        from integrations.aveonline_client import to_aveonline_city_format

        origin_city_norm = to_aveonline_city_format(
            origin.get("city") or "", origin.get("state") or "",
        )
        dest_city_norm = to_aveonline_city_format(
            addr.get("city") or "", addr.get("state") or "",
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(cli.generate_guide(
                origin={
                    "dane": origin.get("dane_code") or "",
                    "city": origin_city_norm or origin.get("city") or "",
                },
                destination={
                    "dane": "",
                    "city": dest_city_norm or addr.get("city") or "",
                },
                package=package,
                carrier={"idtransportador": carrier_rate_id},
                sender=sender,
                recipient=recipient,
                simulate=simulate,
            ))
        finally:
            loop.close()
    except Exception as exc:
        logger.warning(
            "[WOMPI][AVEONLINE] generate_guide error order=%s: %s",
            order_id[:8], exc,
        )
        return False

    # Origin/destination address dicts para satisfacer NOT NULL constraint.
    origin_addr_jsonb = {
        "city": origin.get("city"),
        "street": origin.get("street"),
        "dane_code": origin.get("dane_code"),
        "phone": tenant.get("telefono_contacto") or origin.get("phone"),
        "name": origin.get("name") or tenant.get("name"),
    }
    destination_addr_jsonb = {
        "city": addr.get("city"),
        "street": addr.get("street"),
        "apartment": addr.get("apartment"),
        "tower": addr.get("tower"),
        "building_type": addr.get("building_type"),
        "neighborhood": addr.get("neighborhood"),
    }
    # Schema shipments requiere `parcels` NOT NULL (JSONB lista paquetes).
    parcels_jsonb = [{
        "weight_kg": 0.5,
        "length_cm": 15, "width_cm": 10, "height_cm": 5,
        "declared_value_cop": int(float(order.get("total_amount") or 0)),
        "units": 1,
        "content": "Productos cosmética artesanal",
    }]

    if not result.get("ok"):
        logger.warning(
            "[WOMPI][AVEONLINE] guía no generada order=%s code=%s err=%s",
            order_id[:8], result.get("code"), result.get("error"),
        )
        # Persistir shipment row "pending" para que operador intervenga.
        try:
            supabase.table("shipments").insert({
                "tenant_id": tenant_id,
                "order_id": order_id,
                # Rev. 107: persistir carrier_name real del cart si existe
                # (SERVIENTREGA/ENVIA/etc.), fallback "aveonline" provider.
                "carrier": selected_carrier_name or "aveonline",
                "status": "pending_generation",
                "origin_address": origin_addr_jsonb,
                "destination_address": destination_addr_jsonb,
                "parcels": parcels_jsonb,
                "quote_response": {
                    "error": result.get("error"),
                    "code": result.get("code"),
                    "simulated": simulate,
                },
            }).execute()
        except Exception as exc:
            logger.warning(
                "[WOMPI][AVEONLINE] persist pending shipment falló: %s", exc,
            )
        return False

    # 6. Persistir shipment con tracking real.
    try:
        supabase.table("shipments").insert({
            "tenant_id": tenant_id,
            "order_id": order_id,
            # Prioridad: carrier name del response Aveonline (más
            # canónico) > carrier del cart > provider name fallback.
            "carrier": (
                result.get("carrier_name") or selected_carrier_name or "aveonline"
            ),
            "status": "labeled" if not simulate else "simulated",
            "tracking_number": result.get("tracking_number"),
            "tracking_url": result.get("tracking_url"),
            "label_url": result.get("label_url"),
            "origin_address": origin_addr_jsonb,
            "destination_address": destination_addr_jsonb,
            "parcels": parcels_jsonb,
        }).execute()
        logger.info(
            "[WOMPI][AVEONLINE] guía %s order=%s tracking=%s "
            "(simulate=%s)",
            "SIMULADA" if simulate else "REAL",
            order_id[:8], result.get("tracking_number"), simulate,
        )
    except Exception as exc:
        logger.warning("[WOMPI][AVEONLINE] persist shipment err: %s", exc)
        return False
    return True


def _fmt_cop(value: int) -> str:
    """Formato COP estilo WhatsApp del bot: $18.000 (punto miles)."""
    return f"${value:,.0f}".replace(",", ".")


def _compose_payment_email_html(
    *,
    customer_name: str,
    order_short: str,
    items: list,
    subtotal: int,
    shipping: int,
    total: int,
    carrier: str,
    tenant_name: str,
    tracking_number: str = "",
    tracking_url: str = "",
    label_url: str = "",
    shipment_status: str = "",
) -> str:
    """HTML inline-styled (compatibilidad clientes email).

    Si la guía Aveonline se generó OK (paso 7.5 wompi_webhook), incluye
    sección tracking con número, carrier, link PDF guía + sticker label.
    Si guía aún no generada → sección omitida (mensaje "te avisaremos").
    """
    rows = []
    for it in items:
        qty = int(it.get("quantity") or 1)
        title = str(it.get("title") or "Producto")
        unit_price = int(float(it.get("unit_price") or 0))
        line_total = unit_price * qty
        rows.append(
            f'<tr>'
            f'<td style="padding:8px 0;border-bottom:1px solid #f0f0f0">'
            f'{qty}× {title}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid #f0f0f0;'
            f'text-align:right">{_fmt_cop(line_total)} COP</td>'
            f'</tr>'
        )
    items_html = "".join(rows) or '<tr><td colspan="2">(sin detalle de items)</td></tr>'
    ship_label = f"Envío ({carrier})" if carrier else "Envío"

    # Sección tracking — solo si hay número de guía válido.
    tracking_html = ""
    if tracking_number:
        is_simulated = (shipment_status or "").lower() == "simulated"
        sim_tag = (
            ' <span style="background:#fff3cd;color:#856404;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:600">SIMULADA</span>'
            if is_simulated else ""
        )
        track_btn = (
            f'<a href="{tracking_url}" style="display:inline-block;background:#2c3e50;'
            f'color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;'
            f'font-weight:600;margin-right:8px">🚚 Rastrear envío</a>'
            if tracking_url else ""
        )
        label_btn = (
            f'<a href="{label_url}" style="display:inline-block;background:#fff;'
            f'color:#2c3e50;padding:10px 18px;border-radius:6px;text-decoration:none;'
            f'font-weight:600;border:1px solid #2c3e50">📄 Descargar guía PDF</a>'
            if label_url else ""
        )
        tracking_html = f"""
  <div style="background:#f8f9fa;border-radius:8px;padding:16px 20px;margin:20px 0">
    <h3 style="margin:0 0 12px;font-size:16px;color:#2c3e50">📦 Información de envío{sim_tag}</h3>
    <p style="margin:0 0 8px;font-size:14px"><strong>Transportadora:</strong> {carrier or '—'}</p>
    <p style="margin:0 0 12px;font-size:14px"><strong>Número de guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:2px 6px;
            border-radius:4px;border:1px solid #e8eef2">{tracking_number}</span>
    </p>
    {track_btn}{label_btn}
  </div>"""

    next_step_html = (
        '<p style="margin:24px 0 8px;color:#5a6772">'
        'Tu pedido ya tiene guía generada. Hacemos seguimiento y te '
        'avisaremos en cada cambio de estado del envío.</p>'
        if tracking_number else
        '<p style="margin:24px 0 8px;color:#5a6772">'
        'Tu pedido ya está en preparación. Te avisaremos cuando '
        'despache con tu número de guía.</p>'
    )

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">Pago confirmado, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Gracias por tu compra en <strong>{tenant_name or 'nuestra tienda'}</strong>.
    Aquí tienes el detalle de tu pedido <strong>#{order_short}</strong>.
  </p>

  <table style="width:100%;border-collapse:collapse;margin:16px 0">
    <thead>
      <tr><th style="text-align:left;padding:8px 0;border-bottom:2px solid #2c3e50">Producto</th>
          <th style="text-align:right;padding:8px 0;border-bottom:2px solid #2c3e50">Total</th></tr>
    </thead>
    <tbody>{items_html}</tbody>
    <tfoot>
      <tr><td style="padding:8px 0">Subtotal</td>
          <td style="text-align:right">{_fmt_cop(subtotal)} COP</td></tr>
      <tr><td style="padding:4px 0">{ship_label}</td>
          <td style="text-align:right">{_fmt_cop(shipping)} COP</td></tr>
      <tr><td style="padding:12px 0;font-weight:bold;border-top:2px solid #2c3e50">Total</td>
          <td style="text-align:right;padding:12px 0;font-weight:bold;border-top:2px solid #2c3e50">
            {_fmt_cop(total)} COP</td></tr>
    </tfoot>
  </table>
{tracking_html}
  {next_step_html}

  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Recibiste este email porque pagaste un pedido. Si no fuiste tú,
    contacta al vendedor inmediatamente.
  </p>
</div>
</body></html>"""


def _compose_shipment_dispatched_email_html(
    *,
    customer_name: str,
    order_short: str,
    items: list,
    subtotal: int,
    shipping: int,
    total: int,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
    tracking_url: str,
    label_url: str,
    shipment_status: str,
) -> str:
    """Email etapa 2: "Tu envío está en camino".

    Foco del mensaje: tracking + carrier + acciones (rastrear/descargar).
    Recordatorio resumido del pedido al final (no es lo principal —
    el cliente ya tuvo el email 1 "Pago recibido" con desglose).
    """
    is_simulated = (shipment_status or "").lower() == "simulated"
    sim_tag = (
        ' <span style="background:#fff3cd;color:#856404;padding:2px 8px;'
        'border-radius:4px;font-size:11px;font-weight:600">SIMULADA</span>'
        if is_simulated else ""
    )
    carrier_str = (carrier or "tu transportadora").strip()
    track_btn = (
        f'<a href="{tracking_url}" style="display:inline-block;background:#2c3e50;'
        f'color:#fff;padding:12px 22px;border-radius:6px;text-decoration:none;'
        f'font-weight:600;margin-right:8px;margin-bottom:8px">🚚 Rastrear envío</a>'
        if tracking_url else ""
    )
    label_btn = (
        f'<a href="{label_url}" style="display:inline-block;background:#fff;'
        f'color:#2c3e50;padding:12px 22px;border-radius:6px;text-decoration:none;'
        f'font-weight:600;border:1px solid #2c3e50;margin-bottom:8px">📄 Descargar guía PDF</a>'
        if label_url else ""
    )
    # Resumen compacto del pedido (recordatorio).
    rows = []
    for it in items:
        qty = int(it.get("quantity") or 1)
        title = str(it.get("title") or "Producto")
        rows.append(
            f'<li style="margin:4px 0;color:#5a6772">{qty}× {title}</li>'
        )
    items_html = "".join(rows) or "<li>(sin detalle)</li>"

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">📦 Tu envío está en camino, {customer_name}{sim_tag}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> en <strong>{tenant_name or 'nuestra tienda'}</strong>
    ya tiene guía generada. ¡Pronto lo recibes!
  </p>

  <div style="background:#f8f9fa;border-radius:8px;padding:20px;margin:24px 0">
    <p style="margin:0 0 8px;font-size:14px"><strong>Transportadora:</strong> {carrier_str}</p>
    <p style="margin:0 0 16px;font-size:14px"><strong>Número de guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:3px 8px;
            border-radius:4px;border:1px solid #e8eef2;font-size:15px">{tracking_number}</span>
    </p>
    {track_btn}{label_btn}
  </div>

  <p style="margin:24px 0 8px;color:#5a6772;font-size:13px">
    <strong>Resumen del pedido:</strong>
  </p>
  <ul style="margin:0;padding-left:20px;font-size:13px">{items_html}</ul>
  <p style="margin:8px 0 0;color:#9aa4ad;font-size:12px">
    Total pagado: <strong>{_fmt_cop(total)} COP</strong> (envío {_fmt_cop(shipping)} COP incluido)
  </p>

  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Cualquier inquietud sobre tu envío, responde a este email o contáctanos
    por WhatsApp. ¡Gracias por tu compra!
  </p>
</div>
</body></html>"""

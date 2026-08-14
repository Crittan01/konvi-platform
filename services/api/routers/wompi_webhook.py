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
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client
from dependencies.security import _client_ip, webhook_rate_limit_check
from integrations.wompi_client import (
    create_payment_link_sync,
    get_tenant_wompi_creds,
    is_void_eligible,
    payment_link_ttl_minutes,
    verify_event_signature,
    void_transaction_sync,
)

# G12 corte 2: notificaciones al cliente extraídas a lib/client_notifications.py
# (los nombres quedan en este namespace por el import — callers/tests intactos).
from lib.client_notifications import (  # noqa: F401
    _INTERNAL_STATUS_ES,
    _enqueue_outbound_text,
    _enqueue_whatsapp_outbound,
    _humanize_shipment_status,
    _notify_client_payment_approved,
    _notify_client_refund_completed,
    _notify_client_shipment_delivered,
    _notify_client_shipment_exception,
    _notify_client_shipment_in_transit,
    _notify_client_shipment_label_ready,
    _send_payment_confirmation_email,
    _surface_email_failure,
)

# G12: plantillas de email extraídas a lib/email_templates.py (los nombres
# quedan en este namespace por el import — callers y tests no se enteran).
from lib.email_templates import (  # noqa: F401
    _compose_payment_email_html,
    _compose_payment_failed_email_html,
    _compose_refund_completed_email_html,
    _compose_shipment_delivered_email_html,
    _compose_shipment_exception_email_html,
    _compose_shipment_in_transit_email_html,
    _compose_shipment_label_ready_email_html,
    _fmt_cop,
    _html_to_text,
    _mask_email,
)

# G12 corte 3: generación de guías extraída a lib/shipping_guides.py
# (los nombres quedan en este namespace por el import — callers/tests intactos).
from lib.shipping_guides import (  # noqa: F401
    _generate_shipping_guide,
    _generate_shipping_guide_async,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Wompi Webhook"])

WOMPI_TXN_APPROVED = "APPROVED"
WOMPI_RETRY_STATUSES = {"DECLINED", "ERROR", "VOIDED"}
# TTL del link regenerado: ÚNICA fuente payment_link_ttl_minutes() (env
# WOMPI_PAYMENT_LINK_TTL_MINUTES, default 30) — compartida con la creación en
# orders.py. Se resuelve por llamada, no al importar.


@router.post("/wompi")
async def wompi_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe eventos de Wompi. Responde 200 inmediatamente.
    El procesamiento real ocurre en BackgroundTask.
    """
    # Rate-limit per-IP ANTES de procesar (paridad con aveonline/meli — Ola 0):
    # el path de dinero era el ÚNICO webhook sin rate-limit → flood = amplificación
    # de DB + saturación del threadpool. bucket sin tenant_id (protege por-atacante).
    # Fail-open: un error del limiter NUNCA debe dropear un webhook de pago legítimo.
    try:
        ip = _client_ip(request)
        allowed, retry_after = webhook_rate_limit_check(
            _get_service_client(), ip=ip, bucket="webhook.wompi", limit=200, window_seconds=60,
        )
        if not allowed:
            logger.warning("[WOMPI][WH] rate_limited ip=%s retry_after=%s", ip, retry_after)
            return JSONResponse(status_code=429, content={"received": False, "message": "rate limited"})
    except Exception as _rl_exc:  # noqa: BLE001 — fail-open: no dropear webhook de pago
        logger.warning("[WOMPI][WH] rate-limit check falló (fail-open): %s", _rl_exc)

    try:
        payload = await request.json()
    except Exception:
        # Wompi envía JSON; body inválido no debe provocar retry en su lado
        return JSONResponse(status_code=200, content={"received": True})

    # ── W2 DURABILIDAD: persistir el payload CRUDO en el inbox ANTES del 200 ACK.
    # Wompi no reintenta un 200 ni ofrece pull por reference → si el proceso muere
    # entre este ACK y el fin del procesamiento en background, el evento de dinero
    # se perdería. El inbox lo captura durable; el worker reconcilia lo no procesado.
    # Best-effort: si el insert falla NO bloqueamos el ACK (degradamos al flujo
    # previo para ESTE evento). Idempotente por checksum.
    # Solo capturamos `transaction.updated` (los únicos que _process_wompi_event
    # procesa / mueven dinero); el resto se ignora igual → no ensuciamos el inbox y
    # se reduce la superficie de payloads forjados (persist corre antes de verificar
    # la firma; el atacante solo lograría filas inertes, acotadas por rate-limit +
    # cleanup, rechazadas en la verificación de firma del re-drive).
    if payload.get("event") == "transaction.updated":
        checksum = ((payload.get("signature") or {}).get("checksum") or "").strip()
        try:
            _persist_inbox(_get_service_client(), checksum, payload)
        except Exception as _inbox_exc:  # noqa: BLE001
            logger.warning("[WOMPI][INBOX] persist falló (best-effort): %s", _inbox_exc)

    background_tasks.add_task(_process_wompi_event_durable, payload)
    return JSONResponse(status_code=200, content={"received": True})


# ─── W2 · Durabilidad (inbox transaccional) ────────────────────────────────────

def _persist_inbox(supabase, checksum: str, payload: dict) -> None:
    """Persiste el payload crudo en wompi_webhook_inbox (idempotente por checksum).
    Sin checksum no hay clave de dedup → se omite (cae al flujo no-durable)."""
    if not checksum:
        return
    try:
        supabase.table("wompi_webhook_inbox").insert({
            "checksum": checksum,
            "raw_payload": payload,
        }).execute()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "duplicate key" in msg or "23505" in msg:
            return  # ya capturado (reintento de Wompi o re-drive del worker)
        raise


def _mark_inbox_processed(supabase, checksum: str) -> None:
    """Marca el evento como procesado (desenlace terminal). Idempotente."""
    if not checksum:
        return
    try:
        supabase.table("wompi_webhook_inbox").update(
            {"processed_at": datetime.now(timezone.utc).isoformat()}
        ).eq("checksum", checksum).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WOMPI][INBOX] mark_processed falló checksum=%s err=%s", checksum[:12], exc)


def _record_inbox_error(supabase, checksum: str, err: str) -> None:
    """Guarda el último error + incrementa attempts (best-effort, para dead-letter)."""
    if not checksum:
        return
    try:
        # attempts se incrementa vía RPC atómica del worker en el re-drive; aquí solo
        # dejamos rastro del error del intento en-proceso.
        supabase.table("wompi_webhook_inbox").update(
            {"last_error": (err or "")[:500]}
        ).eq("checksum", checksum).execute()
    except Exception:  # noqa: BLE001
        pass


def _process_wompi_event_durable(payload: dict) -> None:
    """Envuelve _process_wompi_event para la durabilidad W2.

    Si _process_wompi_event RETORNA (incluidos sus early-returns de eventos
    ignorados/huérfanos/duplicados/no-aprobados) es un desenlace TERMINAL → marca
    el inbox procesado. Si LANZA o el proceso crashea mid-procesamiento, la fila
    queda processed_at NULL → el worker la reconcilia (re-POST). La idempotencia
    de dinero la garantiza el dedup wompi_events_seen + el guard de estado terminal.
    """
    checksum = ((payload.get("signature") or {}).get("checksum") or "").strip()
    try:
        _process_wompi_event(payload)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[WOMPI] proceso_falló checksum=%s err=%s — inbox queda para reconciliación",
            (checksum[:12] if checksum else "?"), exc,
        )
        _record_inbox_error(_get_service_client(), checksum, str(exc))
        return
    _mark_inbox_processed(_get_service_client(), checksum)


def _handle_orphan_payment(
    *,
    supabase,
    order: dict,
    txn_id: str,
    amount_in_cents: int,
    payload: dict,
    current_status: str,
) -> None:
    """Un pago APPROVED llegó sobre una orden en estado terminal: el dinero entró y NO hay
    pedido que lo respalde.

    Escenario real y frecuente (no un borde): el cliente recibe el link de pago, luego aplica un
    cupón o cambia el carrito. El bot invalida la orden y crea otra — pero Wompi NO expone API
    para invalidar un `payment_link` (lo documenta `wompi_client`), así que el link viejo sigue
    pagable ~30 min. Si el cliente paga el viejo: PAGÓ Y NO TIENE PEDIDO.

    Antes esto se descartaba con un `logger.info` y nadie se enteraba. El pago SÍ quedaba en
    `payments` (se registra antes de este punto), así que el rastro existía — pero sin alerta,
    sin intento de anulación y sin nada que lo hiciera consultable como "pago huérfano".

    Qué hace ahora:
      1. ERROR (visible en Sentry) con los datos accionables.
      2. Intenta el VOID automático si aplica (solo CARD pre-settlement, per el dossier Wompi).
      3. Marca `payments.status` para que sea CONSULTABLE: 'orphan_voided' si se anuló, o
         'orphan_refund_pending' si hay que devolver a mano (NEQUI/PSE/Bancolombia no se pueden
         voidear: los fondos ya se transfirieron).
    """
    order_id = order["id"]
    tenant_id = order["tenant_id"]
    txn = ((payload.get("data") or {}).get("transaction") or {})
    method = (txn.get("payment_method_type") or "").upper()
    paid_at = txn.get("finalized_at") or txn.get("created_at")

    logger.error(
        "[WOMPI][ORPHAN] pago APPROVED sobre orden en estado '%s' — el cliente PAGÓ y no hay "
        "pedido que lo respalde. order_id=%s txn_id=%s monto=%s método=%s",
        current_status, order_id, txn_id, amount_in_cents, method or "desconocido",
    )

    nuevo_estado = "orphan_refund_pending"
    if is_void_eligible(method, paid_at):
        try:
            private_key, _, environment = get_tenant_wompi_creds(supabase, tenant_id)
            if private_key:
                res = void_transaction_sync(
                    private_key=private_key, environment=environment, transaction_id=txn_id,
                )
                if (res or {}).get("status") == "VOIDED":
                    nuevo_estado = "orphan_voided"
                    logger.warning(
                        "[WOMPI][ORPHAN] void OK txn_id=%s order_id=%s — el cobro se anuló",
                        txn_id, order_id,
                    )
                else:
                    logger.error(
                        "[WOMPI][ORPHAN] void RECHAZADO txn_id=%s res=%s — queda reembolso manual",
                        txn_id, res,
                    )
            else:
                logger.error(
                    "[WOMPI][ORPHAN] sin private_key del tenant %s — no se pudo intentar el void",
                    tenant_id,
                )
        except Exception as exc:  # noqa: BLE001
            # El void es best-effort: si falla, el pago queda marcado para reembolso manual.
            # NO se propaga: el webhook debe cerrar igual (Wompi bloquea la API ante 5xx).
            logger.error("[WOMPI][ORPHAN] void falló txn_id=%s: %s", txn_id, exc)
    else:
        logger.error(
            "[WOMPI][ORPHAN] método '%s' NO admite void (solo CARD pre-settlement) — "
            "REQUIERE REEMBOLSO MANUAL de %s centavos al cliente. order_id=%s txn_id=%s",
            method or "desconocido", amount_in_cents, order_id, txn_id,
        )

    # Deja el pago CONSULTABLE: `payments.status` pasa a reflejar que es huérfano, para poder
    # listar "pagos que necesitan devolución" en vez de tener que cruzar logs.
    try:
        supabase.table("payments").update({"status": nuevo_estado}).eq(
            "wompi_txn_id", txn_id
        ).eq("tenant_id", tenant_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[WOMPI][ORPHAN] no se pudo marcar el pago %s como '%s': %s",
            txn_id, nuevo_estado, exc,
        )


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
    # W3-F1: raise_on_error=True → un flake de Vault PROPAGA (inbox sin procesar →
    # reconcilia) en vez de degradar a events_key='' → 'firma_invalida' → pago perdido.
    events_key: str = ""
    if tenant_id_for_sig:
        _, events_key_val, _ = get_tenant_wompi_creds(supabase, tenant_id_for_sig, raise_on_error=True)
        events_key = events_key_val or ""
    if not verify_event_signature(payload, events_key):
        logger.warning("[WOMPI] firma_invalida event=%s link=%s tenant=%s", event_name, payment_link_id, tenant_id_for_sig)
        return

    # ── 3.5. Dedup de eventos duplicados por checksum (Wompi reintenta en
    # 30m/3h/24h cuando merchant responde no-2xx; la firma SHA256 del payload
    # es el identificador más confiable porque no se documenta `event.id`
    # estable). El row se marca processed_at al FINAL del flujo (paso 8).
    #
    # W2 DURABILIDAD (crítico): el dedup debe distinguir "YA PROCESADO por completo"
    # de "recibido pero INCOMPLETO" (crash entre este INSERT y _confirm_order). Si
    # tratáramos la mera EXISTENCIA como duplicado (return), un evento cuyo 1er
    # intento crasheó antes de confirmar NUNCA se confirmaría: ni el reintento nativo
    # de Wompi ni el re-drive del inbox W2 podrían completarlo (ambos chocan aquí).
    # Regla: descartar SOLO si processed_at IS NOT NULL; si es NULL, reprocesar.
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
                # El row ya existe — ¿fue procesado por completo o quedó incompleto?
                already_processed = None
                try:
                    _chk = (
                        supabase.table("wompi_events_seen")  # tenant_filter:exempt:webhook_dedup_idempotent_event_id_unique
                        .select("processed_at")
                        .eq("event_id", event_uid)
                        .limit(1)
                        .execute()
                    )
                    already_processed = (_chk.data or [{}])[0].get("processed_at")
                except Exception as _chk_exc:  # noqa: BLE001
                    # W3-F2: un fallo TRANSITORIO del processed-check NO debe descartar
                    # el evento (return terminal → pago perdido si estaba incompleto).
                    # PROPAGA → el wrapper deja el inbox sin procesar → el worker re-drivea.
                    # El re-drive es idempotente: si YA estaba procesado, el dedup del
                    # re-intento lo detectará (processed_at NOT NULL → skip); si no, lo
                    # completa. Reconciliar es más seguro que perder el evento.
                    logger.error(
                        "[WOMPI] dedup_processed_check_failed checksum=%s err=%s — PROPAGA para reconciliación",
                        event_uid[:12], _chk_exc,
                    )
                    raise
                if already_processed:
                    logger.info(
                        "[WOMPI] evento_duplicado checksum=%s txn=%s — YA procesado, descartado",
                        event_uid[:12], txn_id,
                    )
                    return
                # Recibido antes pero NO completado (crash previo) → reprocesar.
                logger.warning(
                    "[WOMPI] evento_incompleto checksum=%s txn=%s — recibido sin procesar (crash previo), REPROCESANDO",
                    event_uid[:12], txn_id,
                )
            else:
                # Cualquier otro error (red, schema, mock test sin tabla): NO
                # bloquear procesamiento — el guard de estado terminal de la orden
                # protege de doble decremento.
                logger.warning(
                    "[WOMPI] dedup_check_failed checksum=%s err=%s — continúa procesamiento",
                    event_uid[:12], exc,
                )

    # ── 4. Registrar/actualizar pago en tabla payments (idempotente por txn_id) ─
    # Se inicializa ANTES del try: si el upsert falla, el except continúa el flujo y más abajo
    # se consulta `was_duplicate` para distinguir un replay idempotente de un pago huérfano.
    # False es además la opción SEGURA: si no pudimos registrar el pago, no sabemos que sea un
    # duplicado, así que se trata como huérfano (que alerta) en vez de descartarlo en silencio.
    was_duplicate = False
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
        # Rev. 109 fix UAT live BUG 33 — Si VOIDED Y la orden ya estaba
        # cancelled (caso auto-void post-cancel pipeline), NO ofrecer retry
        # ni liberar stock (ya se hizo). Notificar al cliente que el
        # reembolso bancario está confirmado por Wompi.
        if (
            txn_status == "VOIDED" and order_id
            and _is_post_cancel_void(supabase, order_id=order_id)
        ):
            _notify_client_refund_completed(
                supabase, order_id=order_id, amount_in_cents=amount_in_cents,
            )
            return
        # Para DECLINED/ERROR/VOIDED (no cancel-driven): liberar reservas + retry.
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
    #
    # EXCEPCIÓN — BLOQUE A (item 4) reconciliación de webhook perdido: si la orden
    # fue auto-cancelada por el SWEEPER de TTL (`cancelled_by_actor='system_auto'`),
    # un APPROVED tardío SÍ debe confirmarla. Es la única vía documentada de recuperar
    # un pago cuyo webhook se perdió: Wompi no ofrece pull por reference/link (doc
    # oficial verificada 2026-07-10), así que sin esto el sweeper cancela a los 35 min
    # una orden realmente pagada y el reintento de Wompi (3h/24h) la encontraría en
    # 'cancelled' → dinero perdido. Solo se revierten auto-cancels del SISTEMA (nunca
    # de operador/cliente/pipeline), y la validación de monto/moneda (5b, abajo) protege
    # contra reconciliaciones erróneas (link mal correlacionado, cobro parcial).
    TERMINAL_STATES = {"confirmed", "cancelled"}
    _reconcile_ttl_cancel = (
        current_status == "cancelled"
        and (order.get("cancelled_by_actor") or "") == "system_auto"
    )
    if current_status in TERMINAL_STATES and not _reconcile_ttl_cancel:
        # Antes: TODOS estos casos se descartaban con un log INFO. Pero no son el mismo caso:
        # solo uno es realmente idempotente; los otros dos son DINERO QUE ENTRÓ y que nadie
        # atendía.
        #
        # (a) REPLAY del mismo webhook sobre una orden ya confirmada → idempotente de verdad.
        #     `was_duplicate` (paso 4) lo distingue: el txn ya estaba en el ledger.
        # (b) Pago HUÉRFANO sobre una orden CANCELADA. Escenario real y frecuente: el cliente
        #     recibe el link, luego aplica un cupón o cambia el carrito; el bot invalida la orden
        #     y crea otra — pero Wompi NO expone API para invalidar un payment_link (lo documenta
        #     wompi_client) y el link viejo sigue pagable ~30 min. Si el cliente paga el viejo:
        #     PAGÓ Y NO TIENE PEDIDO.
        # (c) Pago DISTINTO sobre una orden ya confirmada = posible DOBLE COBRO.
        #
        # El pago YA quedó registrado en `payments` (paso 4, antes de este punto), así que el
        # dinero deja rastro. Lo que faltaba era que alguien ACTUARA. Ahora: se eleva a ERROR
        # (visible en Sentry), se intenta el void automático si aplica, y si no se puede se
        # marca para reembolso manual.
        if was_duplicate and current_status == "confirmed":
            logger.info(
                "[WOMPI] replay_idempotente order_id=%s txn_id=%s status=%s — el txn ya estaba "
                "en el ledger, skip",
                order_id, txn_id, current_status,
            )
            return

        _handle_orphan_payment(
            supabase=supabase,
            order=order,
            txn_id=txn_id,
            amount_in_cents=amount_in_cents,
            payload=payload,
            current_status=current_status,
        )
        return
    if _reconcile_ttl_cancel:
        logger.warning(
            "[WOMPI][RECONCILE] APPROVED tardío sobre orden auto-cancelada por TTL "
            "order_id=%s txn_id=%s — se revierte el auto-cancel y se confirma (webhook perdido)",
            order_id, txn_id,
        )

    # ── 5b. Validar monto/moneda antes de confirmar (A11 audit 2026-06-25) ───
    # Defensa payment-integrity: Wompi reporta APPROVED pero el monto cobrado
    # debe coincidir con el total de la orden (link = total al crearlo). Un
    # mismatch (link mal correlacionado, tampering, cobro parcial) NO debe
    # confirmar la orden — fail-closed + log para revisión manual.
    order_total = order.get("total_amount")
    # F16: fail-closed si falta el total (antes `is not None` saltaba la validación en silencio y
    # confirmaba con cualquier monto). Con el select corregido esto solo ocurriría en un dato corrupto.
    if order_total is None:
        logger.error(
            "[WOMPI] order sin total_amount order_id=%s txn_id=%s — NO se confirma (revisión manual)",
            order_id, txn_id,
        )
        return
    expected_cents = int(round(float(order_total) * 100))
    if int(amount_in_cents or 0) != expected_cents:
        logger.error(
            "[WOMPI] monto_mismatch order_id=%s txn_id=%s amount_cents=%s "
            "esperado_cents=%s — NO se confirma (revisión manual)",
            order_id, txn_id, amount_in_cents, expected_cents,
        )
        return
    _txn_currency = (txn.get("currency") or "").upper()
    if _txn_currency and _txn_currency != "COP":
        logger.error(
            "[WOMPI] moneda_invalida order_id=%s txn_id=%s currency=%s — "
            "solo COP; NO se confirma (revisión manual)",
            order_id, txn_id, _txn_currency,
        )
        return

    # ── 6. Confirmar orden y descontar stock ──────────────────────────────────
    # W2 DURABILIDAD: un fallo TRANSITORIO aquí (DB flake) es money-crítico. Antes se
    # tragaba (except→return) → el wrapper durable lo veía como retorno normal → marcaba
    # el inbox procesado → NUNCA se reconciliaba → orden PAGADA sin confirmar. Ahora se
    # PROPAGA: el wrapper deja el inbox sin procesar → el worker re-drivea. El re-drive es
    # idempotente (dedup processed-aware + guard de estado terminal: si un intento previo
    # sí confirmó, el guard 'confirmed' lo salta y marca procesado).
    _confirm_order(supabase, order_id, tenant_id)
    logger.info("[WOMPI] orden_confirmada order_id=%s txn_id=%s tenant=%s", order_id, txn_id, tenant_id)

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

    # ── 7.7. Etapa 2 (solo si guía OK): Email + WhatsApp "Guía generada" ──────
    # Cambio rev. 108 — el copy ya NO promete "envío en camino" porque la
    # guía generada solo significa que Aveonline asignó tracking, no que el
    # courier lo recogió. El estado físico real llega vía webhook Aveonline
    # (in_transit → delivered) en etapa 3+. Si Aveonline rechazó la guía →
    # cliente solo recibe email/WA pago confirmado (etapa 1).
    if guide_ok:
        try:
            _send_payment_confirmation_email(
                supabase=supabase, order_id=order_id, tenant_id=tenant_id,
                template_mode="shipment_label_ready",
            )
        except Exception as e:
            logger.warning(
                "[WOMPI][EMAIL] shipment_label_ready falló order=%s err=%s",
                order_id, e,
            )
        # Notif WhatsApp con tracking — lee shipment row recién creado.
        try:
            sh_res = (
                supabase.table("shipments")
                .select("carrier, tracking_number, tracking_url")
                .eq("order_id", order_id).eq("tenant_id", tenant_id).limit(1).execute()
            )
            sh_row = (sh_res.data or [{}])[0]
            if conversation_id and sh_row.get("tracking_number"):
                # Etapa 2: guía generada (NO "envío en camino" — eso espera
                # confirmación física vía webhook Aveonline EN RUTA).
                _notify_client_shipment_label_ready(
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
            # tenant_filter:exempt:webhook_dedup_idempotent_event_id_unique
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

    # ── Rev. 109 BRECHA: Email DECLINED ──────────────────────────────────
    # Cliente debe enterarse por email tan rápido como por WhatsApp que el
    # pago no se procesó. Especialmente importante si cliente NO está mirando
    # WhatsApp en el momento. Resend best-effort.
    try:
        _send_payment_confirmation_email(
            supabase=supabase, order_id=order_id, tenant_id=tenant_id,
            template_mode="payment_failed",
        )
    except Exception as e:
        logger.warning(
            "[WOMPI][EMAIL] payment_failed falló order=%s err=%s",
            order_id, e,
        )
    try:
        private_key, _, environment = get_tenant_wompi_creds(supabase, tenant_id)
        if not private_key:
            logger.warning("[WOMPI] retry_sin_clave order=%s tenant=%s — notificando fallo sin nuevo link", order_id, tenant_id)
            _enqueue_payment_failed_msg(supabase, conversation_id=conversation_id, tenant_id=tenant_id, order_id=order_id)
            return

        total_amount = float(order.get("total_amount") or 0)
        # int(round(...)) — NO int(x*100): la multiplicación float puede quedar apenas
        # por debajo del entero (150000.02*100 = 15000001.9999… → int=15000001, 1 cent
        # menos) → link con monto menor → el guard de monto (línea ~263, que usa
        # int(round)) RECHAZA → orden pagada varada. Canónico = round.
        amount_in_cents = int(round(total_amount * 100))
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
        ttl_minutes = payment_link_ttl_minutes()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
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
            f"⏰ Válido por {ttl_minutes} minutos."
        )
        _enqueue_outbound_text(supabase, conversation_id=conversation_id, tenant_id=tenant_id, text=text)
        logger.info("[WOMPI] retry_link_enviado order=%s link_id=%s", order_id, link_data["link_id"])

    except Exception as e:
        logger.error("[WOMPI] error_retry order=%s error=%s", order_id, e)
        _enqueue_payment_failed_msg(supabase, conversation_id=conversation_id, tenant_id=tenant_id, order_id=order_id)


# Rev. 109 UAT live BUG 13: emojis 😕 y 🙏 removidos. La whitelist agentic
# permite 📋🚚✅ solamente; mantenemos coherencia cross-canal.
_PAYMENT_FAILED_VARIANTS = [
    "Hmm, tu pago del pedido *#{short_id}* no se completó.\n\nSi quieres, te conecto con un {role} para terminar la compra juntos.",
    "El pago del pedido *#{short_id}* no pasó esta vez.\n\nDime si prefieres que un {role} te acompañe a destrabarlo o intentarlo de nuevo.",
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
    # Webhook resolution: Wompi sólo trae sus refs globales (txn_id/link_id); el
    # tenant se DESCUBRE de la fila resuelta. No hay tenant_id que filtrar aún.
    if wompi_txn_id:
        res = (
            supabase.table("payments")  # tenant_filter:exempt:webhook_resolution_lookup
            # `status` + `amount_in_cents` alimentan la máquina de estados del ledger.
            .select("id, tenant_id, wompi_txn_id, status, amount_in_cents")
            .eq("wompi_txn_id", wompi_txn_id)
            .limit(1)
            .execute()
        )
        existing = (res.data or [None])[0]

    # 2) Si no encontró por txn_id, buscar por wompi_link_id (fila pre-existente
    #    creada por payment_link_tool con txn_id NULL — primer webhook APPROVED).
    if not existing and wompi_link_id and order_id:
        res = (
            supabase.table("payments")  # tenant_filter:exempt:webhook_resolution_lookup
            .select("id, tenant_id, wompi_txn_id, status, amount_in_cents")
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

        # ── Máquina de estados del LIBRO DE PAGOS (UAT 2026-07-20) ────────────
        # Esta función corre ANTES de los guards de monto/moneda/estado-terminal
        # del flujo (paso 4 vs paso 5b) y antes escribía `status` sin ninguna
        # restricción → el ledger podía contradecir a la orden en AMBAS
        # direcciones, ambas reproducidas en UAT:
        #
        #   (a) DECLINED tardío sobre un pago ya APROBADO (Wompi reintenta a
        #       30m/3h/24h; con 2 intentos sobre el MISMO link el txn_id no
        #       matchea y el lookup por (order_id, link_id) pega en la fila
        #       aprobada) → orden 'confirmed' con pago 'declined'.
        #   (b) APPROVED con monto que NO corresponde: el guard de monto impide
        #       confirmar la orden (bien), pero el ledger igual quedaba
        #       'approved' → pago inexistente registrado como cobrado.
        #
        # No es pérdida de dinero (el estado de la ORDEN se protege correctamente),
        # pero `payments` es la fuente de verdad de conciliación
        # (docs/operations/runbooks/wompi-payment-reconciliation.md). Reglas:
        #   1. Nunca degradar un pago ya aprobado.
        #   2. Nunca marcar aprobado si el monto no coincide con el registrado.
        # En ambos casos se preserva `raw_webhook` (auditoría íntegra) y sólo se
        # congela `status`/`wompi_status`.
        _prev_status = (existing.get("status") or "").lower()
        if _prev_status == "approved" and wompi_status != WOMPI_TXN_APPROVED:
            logger.warning(
                "[WOMPI] ledger_no_degrada order_id=%s txn_id=%s prev=approved "
                "entrante=%s — se conserva 'approved' (evento posterior/fuera de orden)",
                order_id, wompi_txn_id, wompi_status,
            )
            update_payload.pop("status", None)
            update_payload.pop("wompi_status", None)
        elif wompi_status == WOMPI_TXN_APPROVED:
            _row_amount = existing.get("amount_in_cents")
            if _row_amount is not None and int(amount_in_cents or 0) != int(_row_amount):
                logger.error(
                    "[WOMPI] ledger_monto_mismatch order_id=%s txn_id=%s "
                    "entrante_cents=%s registrado_cents=%s — NO se marca aprobado",
                    order_id, wompi_txn_id, amount_in_cents, _row_amount,
                )
                update_payload.pop("status", None)
                update_payload.pop("wompi_status", None)

        if wompi_txn_id and not existing.get("wompi_txn_id"):
            update_payload["wompi_txn_id"] = wompi_txn_id
        supabase.table("payments").update(update_payload).eq("id", existing["id"]).eq("tenant_id", existing["tenant_id"]).execute()
        return True  # replay o complete-pre-existing

    if not order_id:
        logger.warning("[WOMPI] sin_order_id_para_insert txn_id=%s — payment no registrado", wompi_txn_id)
        return False

    # Webhook resolution: descubre el tenant del order para el INSERT del payload.
    order_res = (
        supabase.table("orders")  # tenant_filter:exempt:webhook_resolution_lookup
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
    """Resuelve order_id desde wompi_link_id via tabla payments.

    W3-F1 DURABILIDAD: distingue 'no encontrado' (query OK, 0 filas → None) de
    'error de LECTURA' (excepción transitoria → PROPAGA). Antes tragaba el error y
    devolvía None → el flujo lo trataba como huérfano/sin-orden → el wrapper durable
    marcaba el inbox procesado → el pago se perdía para siempre. Ahora un flake deja
    el inbox sin procesar → el worker re-drivea (idempotente)."""
    res = (
        supabase.table("payments")  # tenant_filter:exempt:webhook_resolution_lookup
        .select("order_id")
        .eq("wompi_link_id", wompi_link_id)
        .limit(1)
        .execute()
    )
    data = res.data or []
    return data[0]["order_id"] if data else None


def _get_order_by_id(supabase, order_id: str):
    """W3-F1 DURABILIDAD: 'no encontrado' (0 filas → None) vs 'error de LECTURA'
    (excepción → PROPAGA). Un flake transitorio no debe verse como orden inexistente
    (que marcaría el inbox procesado con el pago sin confirmar); ahora reconcilia."""
    res = (
        supabase.table("orders")  # tenant_filter:exempt:webhook_resolution_lookup
        # F16: total_amount es OBLIGATORIO — sin él el guard de monto (5b) quedaba muerto
        # (order_total siempre None → salta la comparación → confirmaba con CUALQUIER monto) y el
        # retry post-DECLINED leía 0 → siempre "monto bajo" → nunca regeneraba link (venta perdida).
        # BLOQUE A (item 4): cancelled_by_actor para reconciliar un APPROVED tardío
        # contra una orden auto-cancelada por el sweeper de TTL (webhook perdido).
        .select("id, tenant_id, status, conversation_id, contact_id, total_amount, cancelled_by_actor")
        .eq("id", order_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def _confirm_order(supabase, order_id: str, tenant_id: str) -> None:
    from routers.orders import _decrement_stock_on_confirm

    # NOTA W3-F3 (DIFERIDO — no reordenar sin migración): se evaluó decrementar el stock
    # ANTES del flip para cerrar el oversell del crash-recovery (crash entre flip y
    # decremento → 'confirmed' sin descuento → el guard terminal del re-drive lo salta).
    # PERO el reorder introduce un DOBLE decremento en el sub-caso soft-reserve: run 1
    # consume reservas (movement reason='reservation_consumed', marca cart 'converted');
    # tras un crash, el re-drive no re-encuentra el cart → cae al decremento DIRECTO
    # (reason='sale') cuyo ON CONFLICT (order,variation,'sale') NO ve el movement previo
    # 'reservation_consumed' → descuenta 2x → falso agotado + sobre-reposición al cancelar.
    # _decrement_stock_on_confirm NO es idempotente CROSS-PATH (dos reasons, dos índices).
    # Fix correcto = unificar la clave de idempotencia de stock_movements entre ambos paths
    # (migración) — W3-remainder. Se mantiene el orden histórico (flip → decremento).
    supabase.table("orders").update({
        "status": "confirmed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).eq("tenant_id", tenant_id).execute()

    _decrement_stock_on_confirm(supabase, order_id, tenant_id)




def _is_post_cancel_void(supabase, *, order_id: str) -> bool:
    """True si la orden ya estaba cancelled vía pipeline (cancel_order)
    y el void que llega ahora es la confirmación bancaria del refund.

    Distingue del caso "cliente intentó pagar y declinó" (DECLINED/ERROR)
    donde sí queremos ofrecer retry.
    """
    try:
        # Webhook processing: resuelve estado del order por su id (ref del webhook).
        row = (
            supabase.table("orders")  # tenant_filter:exempt:webhook_resolution_lookup
            .select("status, cancellation_id")
            .eq("id", order_id).single().execute()
        ).data
        if not row:
            return False
        if (row.get("status") or "").lower() != "cancelled":
            return False
        # Confirmar que el cancel pipeline marcó refund_method=wompi_void_auto.
        cid = row.get("cancellation_id")
        if not cid:
            return False
        cancel_row = (
            supabase.table("order_cancellations")  # tenant_filter:exempt:webhook_resolution_lookup
            .select("refund_method")
            .eq("id", cid).single().execute()
        ).data
        return (
            (cancel_row or {}).get("refund_method") == "wompi_void_auto"
        )
    except Exception as exc:
        logger.warning(
            "[WOMPI] _is_post_cancel_void check failed order=%s: %s",
            order_id, exc,
        )
        return False














# ─── Email post-pago al cliente (Rev. 107) ────────────────────────────────────

# Rev. 112 GAP emails_tx — el enum interno (inglés) NO debe filtrarse al
# cliente. Cuando existe el nombre_estado real del courier (Aveonline, es-CO)
# lo mostramos; si no, traducimos el enum canónico a una etiqueta es-CO.












# ─── Guía Aveonline post-pago (Rev. 107) ──────────────────────────────────────




















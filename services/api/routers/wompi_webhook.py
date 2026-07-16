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
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client
from dependencies.security import _client_ip, webhook_rate_limit_check
from integrations.wompi_client import (
    create_payment_link_sync,
    get_tenant_wompi_creds,
    verify_event_signature,
)

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
                    logger.warning(
                        "[WOMPI] dedup_processed_check_failed checksum=%s err=%s — descarta (comportamiento previo)",
                        event_uid[:12], _chk_exc,
                    )
                    return  # ante duda, no arriesgar doble-proceso
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
        logger.info(
            "[WOMPI] orden_estado_terminal order_id=%s txn_id=%s status=%s — idempotente, skip",
            order_id, txn_id, current_status,
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
    # Webhook resolution: Wompi sólo trae sus refs globales (txn_id/link_id); el
    # tenant se DESCUBRE de la fila resuelta. No hay tenant_id que filtrar aún.
    if wompi_txn_id:
        res = (
            supabase.table("payments")  # tenant_filter:exempt:webhook_resolution_lookup
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
            supabase.table("payments")  # tenant_filter:exempt:webhook_resolution_lookup
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
    """Resuelve order_id desde wompi_link_id via tabla payments."""
    try:
        res = (
            supabase.table("payments")  # tenant_filter:exempt:webhook_resolution_lookup
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


# ─── Email post-pago al cliente (Rev. 107) ────────────────────────────────────

# Rev. 112 GAP emails_tx — el enum interno (inglés) NO debe filtrarse al
# cliente. Cuando existe el nombre_estado real del courier (Aveonline, es-CO)
# lo mostramos; si no, traducimos el enum canónico a una etiqueta es-CO.
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


def _mask_email(email: str) -> str:
    """Enmascara el local-part para logs (Habeas Data — coherente con el
    hasheo de teléfonos del resto de la plataforma). Conserva el dominio,
    útil para diagnosticar deliverability por proveedor."""
    e = (email or "").strip()
    local, sep, domain = e.partition("@")
    if not sep:
        return "***"
    head = local[:2]
    return f"{head}{'*' * max(1, len(local) - len(head))}@{domain}"


def _html_to_text(html: str) -> str:
    """Deriva un cuerpo text/plain mínimo del HTML (mejor scoring anti-spam;
    Resend recomienda multipart). Best-effort: strip de tags + colapso de
    espacios. No pretende fidelidad tipográfica."""
    import re
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|tr|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _surface_email_failure(
    reason: str, *, tenant_id: str = "", order_id: str = "",
    template_mode: str = "", status_code=None, detail: str = "",
) -> None:
    """Surfacing de fallos de envío a Sentry (no-op si SENTRY_DSN vacío).

    NO rompe el flujo (best-effort). El log ya se emitió en el caller; esto
    añade una señal alertable distinta del éxito silencioso."""
    try:
        from observability import capture_exception
        capture_exception(
            RuntimeError(f"resend_email_failed: {reason}"),
            tenant_id=tenant_id,
            order_id=(order_id or "")[:8],
            template_mode=template_mode,
            status_code=status_code,
            detail=(detail or "")[:200],
        )
    except Exception:
        pass


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
    import httpx
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
            _surface_email_failure(
                "rate_or_quota_429", tenant_id=tenant_id, order_id=order_id,
                template_mode=template_mode, status_code=429,
                detail=resp.text[:200],
            )
        elif 400 <= resp.status_code < 500:
            # 4xx = config/payload (from no verificado, key inválida) — bug de
            # activación, requiere acción operador.
            logger.error(
                "[WOMPI][EMAIL] resend 4xx status=%s to=%s order=%s mode=%s body=%s",
                resp.status_code, masked, order_id[:8], template_mode,
                resp.text[:200],
            )
            _surface_email_failure(
                "client_4xx", tenant_id=tenant_id, order_id=order_id,
                template_mode=template_mode, status_code=resp.status_code,
                detail=resp.text[:200],
            )
        else:
            # 5xx = Resend caído — transitorio (Wompi/Aveonline reintentan el
            # webhook; el Idempotency-Key evita duplicar si el 5xx fue parcial).
            logger.error(
                "[WOMPI][EMAIL] resend 5xx status=%s to=%s order=%s mode=%s body=%s",
                resp.status_code, masked, order_id[:8], template_mode,
                resp.text[:200],
            )
            _surface_email_failure(
                "server_5xx", tenant_id=tenant_id, order_id=order_id,
                template_mode=template_mode, status_code=resp.status_code,
                detail=resp.text[:200],
            )
    except Exception as exc:
        logger.warning(
            "[WOMPI][EMAIL] httpx err to=%s order=%s mode=%s: %s",
            _mask_email(email), order_id[:8], template_mode, exc,
        )
        _surface_email_failure(
            "transport_exception", tenant_id=tenant_id, order_id=order_id,
            template_mode=template_mode, detail=str(exc)[:200],
        )


# ─── Guía Aveonline post-pago (Rev. 107) ──────────────────────────────────────

def _generate_shipping_guide(
    supabase, *, order_id: str, tenant_id: str,
) -> bool:
    """Wrapper SYNC para callers sync (wompi BackgroundTask).

    Usa asyncio.run() — funciona porque BackgroundTask sync NO tiene
    event loop activo. Para callers async (endpoint FastAPI), usar
    `_generate_shipping_guide_async` directamente con await.
    """
    import asyncio as _aio
    # UAT founder 2026-07-10: pausa configurable ANTES de generar la guía en el path
    # automático post-pago (ventana de cancelación/edición + evita guía "instantánea").
    try:
        _delay = float(os.getenv("GUIDE_GENERATION_DELAY_SECONDS", "60"))
    except ValueError:
        _delay = 60.0
    return _aio.run(
        _generate_shipping_guide_async(
            supabase, order_id=order_id, tenant_id=tenant_id,
            delay_seconds=max(0.0, _delay),
        )
    )


async def _generate_shipping_guide_async(
    supabase, *, order_id: str, tenant_id: str, delay_seconds: float = 0.0,
) -> bool:
    """Genera guía Aveonline tras pago APPROVED (best-effort).

    Solo aplica si el tenant tiene `tenant_shipping_provider_config.
    active_provider='aveonline'`. Si está en 'envia' o cualquier otro,
    skip (los demás providers tienen su propia mecánica).

    simulate=True por default → NO factura. Tenant setea
    AVEONLINE_GENERATE_REAL_GUIDES=true (env) cuando esté listo.

    Best-effort: si falla, log warning + persiste row pending en
    shipments para que operador genere manual desde Inbox.

    delay_seconds (UAT founder 2026-07-10): pausa previa SOLO en el path automático
    post-pago (webhook la pasa desde GUIDE_GENERATION_DELAY_SECONDS, default 60s) —
    (a) da ventana de cancelación/edición antes de generar (con guías reales = antes
    de facturar), (b) evita la sensación "robótica" de guía instantánea. El path
    manual del operador (orders.py) NO pasa delay (respuesta inmediata).

    Returns:
        True si guía generó OK + shipment persistido con tracking_number
        (caller dispara etapa 2: email "envío en camino" + WA tracking).
        False si skip (provider != aveonline / contact incompleto /
        Aveonline rechazó). Caller no dispara etapa 2.
    """
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    # 1. Provider check.
    tenant_real_guides = False  # BLOQUE B (item 3): default fail-safe (simulado)
    try:
        cfg = (
            supabase.table("tenant_shipping_provider_config")
            .select("active_provider, real_guides_enabled")
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        provider = ((cfg.data or {}).get("active_provider") or "").lower()
        tenant_real_guides = bool((cfg.data or {}).get("real_guides_enabled"))
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
                "id, total_amount, shipping_cost, contact_id, payment_method, "
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
    # A2 finiquito 2026-06-23: schema canónico `street` (rev. 110).
    # Audit live 2026-06-23: 5/5 contactos productivos KAIU usan `street`.
    # Fallback `line1` preservado 30 días defensivo por retries de webhooks
    # legacy con snapshot serializado pre-deploy (adversarial #12).
    addr_street = addr.get("street") or addr.get("line1") or ""
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

    # 4. Cart shipping_meta → idtransportador (rate_id). BUG F5 (guía cruzada): filtrar por el cart QUE
    # CONVIRTIÓ A ESTA ORDEN (converted_order_id), no el último del tenant → evita usar el carrier de otra
    # orden bajo concurrencia. Sin cart vinculado → sm vacío → carrier_rate_id vacío (path degradado seguro).
    try:
        cart = (
            supabase.table("conversation_carts")
            .select("shipping_meta")
            .eq("tenant_id", tenant_id)
            .eq("converted_order_id", order_id)
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
    _claim_id = None  # BLOQUE B item 5: def antes del try — el except grande lo referencia
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
        # Rev. 108 Fase B — COD: si orden tiene payment_method='cod',
        # pasar `cod_enabled=True` + `valorrecaudo=total_amount` al cliente
        # Aveonline. El courier recauda al entregar (campo `contraentrega=1`).
        order_total = int(float(order.get("total_amount") or 0))
        # valorDeclarado del seguro = valor de la MERCANCÍA (subtotal de productos), NO el total con envío
        # (auditoría coherencia 2026-07-01, LOW #1): se asegura el producto, no el flete. Fallback al total
        # si no hay shipping_cost. valorrecaudo (COD) SÍ es el total (el courier recauda productos + envío).
        shipping_cost = int(float(order.get("shipping_cost") or 0))
        merchandise_cop = max(order_total - shipping_cost, 0) or order_total
        is_cod = (order.get("payment_method") or "credit").lower() == "cod"
        # F5: reusar peso/dims COTIZADOS (shipping_meta.weight_inputs, persistidos por el quote) → la guía
        # sale con el peso real y no sobre-declara ni dispara reajuste retroactivo. Fallback a default solo si
        # el cart no cotizó (guía sin quote previo). `sm` = shipping_meta del cart de ESTA orden (arriba).
        _wi = (sm or {}).get("weight_inputs") or {}
        # UAT founder 2026-07-10: dscontenido de la guía era un hardcode ("Productos
        # cosmética artesanal") inválido multi-tenant y para reclamos ante el carrier.
        # Derivar del contenido REAL del pedido (títulos de order_items, ≤90 chars).
        guide_content = "Pedido"
        try:
            _items_res = (
                supabase.table("order_items")
                .select("title, quantity")
                .eq("order_id", order_id)
                .eq("tenant_id", tenant_id)  # ADR-0025: filtro explícito por tenant (lint)
                .limit(5)
                .execute()
            )
            _titles = [
                f"{int(r.get('quantity') or 1)}x {str(r.get('title') or '').strip()}"
                for r in (_items_res.data or []) if r.get("title")
            ]
            if _titles:
                guide_content = ("; ".join(_titles))[:90]
        except Exception as _it_exc:
            logger.debug("[WOMPI][AVEONLINE] items para dscontenido falló: %s", _it_exc)
        package = {
            "weight_kg": float(_wi.get("weight_kg") or 0.5),  # default conservador si no hay cotización
            "length_cm": float(_wi.get("length_cm") or 15),
            "width_cm": float(_wi.get("width_cm") or 10),
            "height_cm": float(_wi.get("height_cm") or 5),
            "declared_value_cop": merchandise_cop,
            "units": 1,
            "content": guide_content,
            "cod_enabled": is_cod,
            "valorrecaudo": order_total if is_cod else 0,
        }
        # BLOQUE B (item 3): guía real solo si AMBOS — master global de plataforma
        # (kill-switch) Y activación per-tenant (real_guides_enabled). Default false en
        # ambos → simulado (fail-safe). Activar guías reales es acción founder por-tenant.
        _master_real = os.getenv("AVEONLINE_GENERATE_REAL_GUIDES", "false").lower() == "true"
        simulate = not (_master_real and tenant_real_guides)

        # Bug runtime KAIU 2026-05-24: Aveonline rechaza city raw
        # ("Bogotá D.C." → "No se pudo generar la guia."). Requiere
        # formato canónico "BOGOTA(CUNDINAMARCA)". Aplicamos el mismo
        # normalizador del cotizador para coherencia origin/destination.
        from integrations.aveonline_client import to_aveonline_city_format
        from lib.dane_resolver import resolve_dane_from_city

        origin_city_norm = to_aveonline_city_format(
            origin.get("city") or "", origin.get("state") or "",
        )
        dest_city_norm = to_aveonline_city_format(
            addr.get("city") or "", addr.get("state") or "",
        )

        # Bug fix rev. 109 (2026-05-31): Aveonline `generarGuia2` rechaza
        # destino sin DANE numérico ("No se puede generar la guia").
        # Precedencia destino:
        #   1. cart.shipping_meta.dane_code — el bot lo resolvió al cotizar
        #      (shipping_quote_tool._persist_destination_city_to_cart). Fuente
        #      más reciente: el cliente acaba de declarar la ciudad este turn.
        #   2. contact.address.dane_code — si el save_address tool lo persistió
        #      (post-rev.109 lo hará; backwards-compat para addresses viejas).
        #   3. DIVIPOLA via lib.dane_resolver — defensa final.
        # Origin solo usa (1)+(3) porque tenants.shipping_origin_dane SÍ está
        # garantizado al configurar Settings.
        origin_dane = (
            origin.get("dane_code")
            or resolve_dane_from_city(origin.get("city") or "", origin.get("state"))
        )
        dest_dane = (
            sm.get("dane_code")
            or addr.get("dane_code")
            or resolve_dane_from_city(addr.get("city") or "", addr.get("state"))
        )

        # BLOQUE B (item 5) — claim-before-bill (idempotencia anti guía DUPLICADA facturable).
        # Se computan los jsonb (NOT NULL de shipments) y se INSERTA una fila 'generating'
        # ANTES de facturar. El índice único parcial (tenant_id, order_id) WHERE status IN
        # ('generating','labeled','simulated') hace fallar un 2º INSERT concurrente/retry →
        # esa invocación NO factura (evita cobro duplicado real por webhook doble / cron).
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
        # Schema shipments requiere `parcels` NOT NULL. F5: peso/dims cotizados de la guía.
        # UAT founder 2026-07-10: declared_value alineado a lo REALMENTE declarado a
        # Aveonline (merchandise_cop = mercancía sin flete), no al total con envío.
        parcels_jsonb = [{
            "weight_kg": float(_wi.get("weight_kg") or 0.5),
            "length_cm": float(_wi.get("length_cm") or 15),
            "width_cm": float(_wi.get("width_cm") or 10),
            "height_cm": float(_wi.get("height_cm") or 5),
            "declared_value_cop": merchandise_cop,
            "units": 1,
            "content": guide_content,
        }]
        try:
            _claim = supabase.table("shipments").insert({
                "tenant_id": tenant_id,
                "order_id": order_id,
                "carrier": selected_carrier_name or "aveonline",
                "status": "generating",
                "origin_address": origin_addr_jsonb,
                "destination_address": destination_addr_jsonb,
                "parcels": parcels_jsonb,
            }).execute()
            _claim_id = (_claim.data or [{}])[0].get("id")
        except Exception as _claim_exc:
            # unique_violation (o error DB): ya hay guía en progreso/generada para esta orden
            # → NO facturar (idempotente). El 2º webhook/retry/cron de reconciliación cae aquí.
            logger.info(
                "[WOMPI][AVEONLINE] guía ya reclamada/generada order=%s — skip idempotente: %s",
                order_id[:8], _claim_exc,
            )
            return False
        if not _claim_id:
            logger.warning(
                "[WOMPI][AVEONLINE] claim shipment sin id order=%s — abort", order_id[:8],
            )
            return False

        # Rev. 108 fix arquitectónico — ahora función async. Antes
        # usaba asyncio.new_event_loop() + run_until_complete, lo cual
        # fallaba ("Cannot run the event loop while another loop is
        # running") cuando se invoca desde context async (endpoint
        # FastAPI). Solución: función async, callers la awaitean directo.
        result = await cli.generate_guide(
            origin={
                "dane": origin_dane,
                "city": origin_city_norm or origin.get("city") or "",
            },
            destination={
                "dane": dest_dane,
                "city": dest_city_norm or addr.get("city") or "",
            },
            package=package,
            carrier={"idtransportador": carrier_rate_id},
            sender=sender,
            recipient=recipient,
            simulate=simulate,
        )
    except Exception as exc:
        # Excepción al facturar. Distinguir por si HUBO dinero en juego:
        #  - simulate=True → NO hubo cobro (guía simulada) → mover a 'pending_generation'
        #    (fuera del índice único) para permitir reintento seguro. Evita que el caso común
        #    (real guides OFF por default) quede varado silenciosamente.
        #  - simulate=False (guía REAL) → un TIMEOUT pudo facturar (AMBIGUO). Money-safe: dejar
        #    'generating' (en el índice → bloquea auto-retry) para resolución manual del operador
        #    (verificar en Aveonline) en vez de arriesgar doble cobro. Se persiste el error para
        #    que NO sea silencioso (el shipment queda con quote_response.error visible).
        _ambiguous_real = not simulate
        if _claim_id:  # None si la excepción ocurrió antes del claim (nada que actualizar)
            try:
                supabase.table("shipments").update({
                    "status": "generating" if _ambiguous_real else "pending_generation",
                    "quote_response": {
                        "error": str(exc)[:500],
                        "simulated": simulate,
                        "ambiguous_bill": _ambiguous_real,
                    },
                }).eq("id", _claim_id).eq("tenant_id", tenant_id).execute()
            except Exception as _upd_exc:
                logger.warning("[WOMPI][AVEONLINE] update claim tras excepción falló: %s", _upd_exc)
        logger.warning(
            "[WOMPI][AVEONLINE] generate_guide error order=%s simulate=%s (%s): %s",
            order_id[:8], simulate,
            "REAL ambiguo → claim 'generating', resolución manual" if _ambiguous_real
            else "simulado → 'pending_generation', reintentable",
            exc,
        )
        return False

    if not result.get("ok"):
        logger.warning(
            "[WOMPI][AVEONLINE] guía no generada order=%s code=%s err=%s",
            order_id[:8], result.get("code"), result.get("error"),
        )
        # Aveonline respondió NOT-OK → definitivamente NO facturó → mover el claim a
        # 'pending_generation' (fuera del índice único) para permitir un reintento seguro.
        # 2 intentos: si el UPDATE falla, el claim quedaría 'generating' bloqueando el retry.
        for _attempt in (1, 2):
            try:
                supabase.table("shipments").update({
                    "status": "pending_generation",
                    "quote_response": {
                        "error": result.get("error"),
                        "code": result.get("code"),
                        "simulated": simulate,
                    },
                }).eq("id", _claim_id).eq("tenant_id", tenant_id).execute()
                break
            except Exception as exc:
                logger.warning(
                    "[WOMPI][AVEONLINE] update pending shipment falló (intento %d): %s",
                    _attempt, exc,
                )
        return False

    # 6. Actualizar el claim con el tracking real (labeled/simulated). La guía YA se generó/
    #    facturó → guardar el tracking es crítico. 2 intentos; si falla una guía REAL, log a
    #    nivel error con el tracking (recuperable) — la guía existe en Aveonline aunque la DB falle.
    _upd_fields = {
        # Prioridad: carrier name del response Aveonline (más canónico) >
        # carrier del cart > provider name fallback.
        "carrier": (
            result.get("carrier_name") or selected_carrier_name or "aveonline"
        ),
        "status": "labeled" if not simulate else "simulated",
        "tracking_number": result.get("tracking_number"),
        "tracking_url": result.get("tracking_url"),
        "label_url": result.get("label_url"),
    }
    _persisted = False
    for _attempt in (1, 2):
        try:
            supabase.table("shipments").update(_upd_fields).eq(
                "id", _claim_id).eq("tenant_id", tenant_id).execute()
            _persisted = True
            break
        except Exception as exc:
            logger.warning(
                "[WOMPI][AVEONLINE] persist shipment err (intento %d): %s", _attempt, exc,
            )
    if not _persisted and not simulate:
        # Guía REAL facturada cuyo tracking NO se persistió → recuperación manual desde este log.
        logger.error(
            "[WOMPI][AVEONLINE] GUÍA REAL FACTURADA sin persistir order=%s tracking=%s "
            "label=%s (claim %s queda 'generating') — recuperar manualmente",
            order_id[:8], result.get("tracking_number"), result.get("label_url"),
            str(_claim_id)[:8],
        )
        return False
    logger.info(
        "[WOMPI][AVEONLINE] guía %s order=%s tracking=%s (simulate=%s)",
        "SIMULADA" if simulate else "REAL",
        order_id[:8], result.get("tracking_number"), simulate,
    )
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
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
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


def _compose_payment_failed_email_html(
    *,
    customer_name: str,
    order_short: str,
    items: list,
    subtotal: int,
    shipping: int,
    total: int,
    carrier: str,
    tenant_name: str,
) -> str:
    """Rev. 109 BRECHA — email cuando Wompi rechaza pago.

    Copy empático sin culpar al cliente. Invita a reintentar y aclara
    que el pedido SIGUE reservado (stock liberado pero podrá reintentarse
    si genera nuevo link). Diseño consistente con _compose_payment_email_html
    (colores tenants + tipografía).
    """
    # Rev. 109 fix bug founder UAT: usar _fmt_cop (NO divide /100) + 'unit_price'
    # (no 'unit_price_cents'). order_items.unit_price y orders.total_amount /
    # shipping_cost están en PESOS, no cents. Consistencia con
    # _compose_payment_email_html existente.
    items_rows = "".join(
        f"""<tr>
          <td style="padding:8px 4px;color:#1f2937;border-bottom:1px solid #e5e7eb;">
            {int(it.get('quantity') or 1)}× {it.get('title', 'Producto')}
          </td>
          <td style="padding:8px 4px;color:#6b7280;text-align:right;
                     border-bottom:1px solid #e5e7eb;">
            {_fmt_cop(int(float(it.get('unit_price') or 0)) * int(it.get('quantity') or 1))} COP
          </td>
        </tr>"""
        for it in (items or [])
    )

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Pago no procesado</title></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,
             BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:560px;margin:0 auto;padding:32px 24px;background:#fff;">
  <h1 style="color:#b45309;font-size:22px;margin:0 0 16px;">
    Hola {customer_name},
  </h1>
  <p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 16px;">
    Tu pago del <strong>Pedido #{order_short}</strong> de
    <strong>{tenant_name}</strong> no se procesó esta vez.
  </p>
  <p style="color:#6b7280;font-size:14px;line-height:1.6;margin:0 0 20px;">
    Puede ser por validación bancaria, saldo insuficiente o un error
    momentáneo. No te preocupes — tu pedido queda registrado para que
    puedas reintentarlo sin perder los datos.
  </p>

  <div style="background:#fef3c7;padding:14px 16px;border-radius:6px;
              border-left:3px solid #f59e0b;margin:20px 0;">
    <strong style="color:#92400e;">¿Qué hacer ahora?</strong><br/>
    <span style="color:#78350f;font-size:14px;">
      Revisa tu WhatsApp: allí seguimos el proceso para completar tu pago.
      Si necesitas ayuda o no recibes un nuevo mensaje, responde a ese chat
      y un especialista de nuestro equipo te asiste.
    </span>
  </div>

  <h3 style="color:#1f2937;font-size:16px;margin:24px 0 8px;">
    Resumen del pedido
  </h3>
  <table width="100%" cellspacing="0" cellpadding="0"
         style="border-collapse:collapse;">
    {items_rows}
    <tr>
      <td style="padding:8px 4px;color:#6b7280;">Subtotal</td>
      <td style="padding:8px 4px;color:#6b7280;text-align:right;">
        {_fmt_cop(subtotal)} COP</td>
    </tr>
    <tr>
      <td style="padding:8px 4px;color:#6b7280;">Envío ({carrier or '-'})</td>
      <td style="padding:8px 4px;color:#6b7280;text-align:right;">
        {_fmt_cop(shipping)} COP</td>
    </tr>
    <tr>
      <td style="padding:12px 4px;color:#1f2937;font-weight:600;
                 border-top:2px solid #e5e7eb;">Total a pagar</td>
      <td style="padding:12px 4px;color:#1f2937;font-weight:600;
                 text-align:right;border-top:2px solid #e5e7eb;">
        {_fmt_cop(total)} COP</td>
    </tr>
  </table>

  <p style="color:#9ca3af;font-size:12px;margin:32px 0 0;text-align:center;">
    Este es un correo automático de <strong>{tenant_name}</strong>.<br/>
    Para soporte, responde por WhatsApp.
  </p>
</div>
</body></html>"""


def _compose_shipment_label_ready_email_html(
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
    """Email etapa 2 (post-guía generada): "Guía generada — saldrá pronto".

    Rev. 108 — el copy ya NO promete "envío en camino". La guía generada
    solo significa que el courier asignó tracking; el despacho físico
    ocurre cuando el courier recoja el paquete (estado EN RUTA reportado
    vía webhook). Hasta entonces, mensaje preciso: "lista para despacho".
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
        f'font-weight:600;margin-right:8px;margin-bottom:8px">🔍 Rastrear envío</a>'
        if tracking_url else ""
    )
    label_btn = (
        f'<a href="{label_url}" style="display:inline-block;background:#fff;'
        f'color:#2c3e50;padding:12px 22px;border-radius:6px;text-decoration:none;'
        f'font-weight:600;border:1px solid #2c3e50;margin-bottom:8px">📄 Descargar guía PDF</a>'
        if label_url else ""
    )
    rows = []
    for it in items:
        qty = int(it.get("quantity") or 1)
        title = str(it.get("title") or "Producto")
        rows.append(
            f'<li style="margin:4px 0;color:#5a6772">{qty}× {title}</li>'
        )
    items_html = "".join(rows) or "<li>(sin detalle)</li>"

    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">📋 Guía asignada, {customer_name}{sim_tag}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> en <strong>{tenant_name or 'nuestra tienda'}</strong>
    ya tiene número de guía. El courier lo recogerá pronto y te avisaré
    aquí cuando salga en ruta.
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
    Cualquier inquietud, responde a este email o escríbenos por WhatsApp.
    ¡Gracias por tu compra!
  </p>
</div>
</body></html>"""


def _compose_shipment_in_transit_email_html(
    *,
    customer_name: str,
    order_short: str,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
    tracking_url: str,
    raw_status: str = "",
) -> str:
    """Email etapa 3 (post-webhook EN RUTA): envío físicamente despachado."""
    carrier_str = (carrier or "el courier").strip()
    track_btn = (
        f'<a href="{tracking_url}" style="display:inline-block;background:#2c3e50;'
        f'color:#fff;padding:12px 22px;border-radius:6px;text-decoration:none;'
        f'font-weight:600">🔍 Rastrear envío</a>'
        if tracking_url else ""
    )
    status_line = (
        f'<p style="margin:0 0 8px;color:#5a6772;font-size:13px">'
        f'Estado actual: <strong>{raw_status}</strong></p>'
        if raw_status else ""
    )
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">🚚 Tu envío salió en ruta, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> de <strong>{tenant_name or 'nuestra tienda'}</strong>
    ya está en camino con <strong>{carrier_str}</strong>.
  </p>
  <div style="background:#f8f9fa;border-radius:8px;padding:20px;margin:24px 0">
    {status_line}
    <p style="margin:0 0 16px;font-size:14px"><strong>Guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:3px 8px;
            border-radius:4px;border:1px solid #e8eef2;font-size:15px">{tracking_number}</span>
    </p>
    {track_btn}
  </div>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Te avisaré aquí mismo cuando el courier confirme la entrega.
  </p>
</div>
</body></html>"""


def _compose_shipment_delivered_email_html(
    *,
    customer_name: str,
    order_short: str,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
) -> str:
    """Email etapa 4 (post-webhook ENTREGADA): pedido entregado."""
    carrier_str = (carrier or "el courier").strip()
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">📬 Pedido entregado, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> de <strong>{tenant_name or 'nuestra tienda'}</strong>
    fue entregado vía <strong>{carrier_str}</strong> (guía <code>{tracking_number}</code>).
  </p>
  <p style="margin:16px 0;color:#2c3e50;font-size:15px">
    ¿Todo llegó perfecto? Cuéntanos respondiendo a este email — tu opinión
    nos ayuda a mejorar.
  </p>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    ¡Gracias por confiar en nosotros! 💛
  </p>
</div>
</body></html>"""


def _compose_shipment_exception_email_html(
    *,
    customer_name: str,
    order_short: str,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
    raw_status: str = "",
) -> str:
    """Email etapa novedad: alerta + invitación a contactar."""
    carrier_str = (carrier or "el courier").strip()
    reason_line = (
        f'<p style="margin:0 0 8px;font-size:14px">'
        f'<strong>Motivo reportado:</strong> {raw_status}</p>'
        if raw_status else ""
    )
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">⚠️ Novedad con tu envío, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> tuvo un inconveniente con
    <strong>{carrier_str}</strong>.
  </p>
  <div style="background:#fff8e1;border-radius:8px;padding:20px;margin:24px 0;border:1px solid #ffe082">
    {reason_line}
    <p style="margin:0;font-size:14px"><strong>Guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:3px 8px;
            border-radius:4px;border:1px solid #e8eef2;font-size:15px">{tracking_number}</span>
    </p>
  </div>
  <p style="margin:16px 0;color:#2c3e50;font-size:14px">
    Ya estamos revisando con la transportadora. Si tienes información
    relevante (dirección alterna, horario disponible) responde a este
    email o por WhatsApp para acelerar la solución.
  </p>
</div>
</body></html>"""


def _compose_refund_completed_email_html(
    *,
    customer_name: str,
    order_short: str,
    total: int,
    tenant_name: str,
) -> str:
    """Rev. 112 GAP — confirmación de reembolso (VOIDED en Wompi).

    Extraído del dispatcher a composer para paridad estructural con los
    demás templates. Usa `_fmt_cop` (pesos, no cents) y la misma tipografía
    Arial/#2c3e50 del resto del ciclo de vida.
    """
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px;color:#059669">✅ Reembolso confirmado, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu reembolso de <strong>{_fmt_cop(total)} COP</strong> del pedido
    <strong>#{order_short}</strong> ya fue procesado por Wompi y enviado
    al sistema bancario.
  </p>
  <p style="margin:0 0 16px;color:#5a6772">
    El dinero aparecerá en tu tarjeta en <strong>1-2 días hábiles</strong>
    típicos. Puede tardar más según tu banco emisor.
  </p>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Si en 7 días no lo ves reflejado, escríbenos y te ayudamos a rastrearlo
    con Wompi.<br/>— {tenant_name or 'nuestra tienda'}
  </p>
</div>
</body></html>"""

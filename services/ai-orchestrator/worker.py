import asyncio
import logging
import os
import sys  # A11 audit 2026-06-25 (P0 BUG_REAL Clase A): el cron hard-delete usa `sys.path` (~L1881) con `sys` no importado a nivel módulo → NameError al ejecutar.
import time
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from agentic.dispatcher import dispatch_message as _agentic_dispatch_message
from conversation_contract import PROCESSING_STATUS_PROCESSING
from notifications import dispatch_human_takeover_event
from refund_notifications import notify_client_refund_completed
from whatsapp_sender import (
    send_whatsapp_message,
    send_whatsapp_template,
    TEMPLATE_ERR_TEMPLATE_NOT_APPROVED,
    TEMPLATE_ERR_TEMPLATE_NOT_FOUND,
)

logger = logging.getLogger("orchestrator.worker")

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "3"))
MAX_PROCESSING_ATTEMPTS = int(os.getenv("MAX_PROCESSING_ATTEMPTS", "5"))
# F5 bot_engine — rate-limit inbound→LLM POR CONVERSACIÓN (protección de costo
# Gemini). Un contacto que inunda mensajes (loop/abuso) no debe disparar una
# llamada LLM por cada uno. Cap generoso: un cliente legítimo nunca lo alcanza;
# frena ráfagas anómalas. 0 ⇒ desactivado. Reusa el RPC distribuido
# rate_limit_hit (migración 20260425 distributed_rate_limiter), sin estado local.
INBOUND_LLM_RATE_LIMIT = int(os.getenv("INBOUND_LLM_RATE_LIMIT", "30"))
INBOUND_LLM_RATE_WINDOW_SECONDS = int(os.getenv("INBOUND_LLM_RATE_WINDOW_SECONDS", "60"))
# Rev. 85 — debounce/coalescing window. Si el cliente envía múltiples
# mensajes rápidos, esperamos esta ventana antes de procesar para juntar
# en un solo input al LLM (no perder contexto al ver solo el último msg).
MESSAGE_COALESCE_WINDOW_SECONDS = int(os.getenv("MESSAGE_COALESCE_WINDOW_SECONDS", "5"))
# 2026-06-27 (founder) — DEBOUNCE: la ventana se reinicia con cada mensaje nuevo (espera
# SILENCIO de WINDOW segundos desde el ÚLTIMO mensaje, no una ventana fija desde el primero).
# Así un cliente que escribe en varios ENTER con pausas <WINDOW dice TODO antes de que el bot
# responda. TOPE total para no esperar indefinidamente si escribe sin parar.
MESSAGE_COALESCE_MAX_TOTAL_SECONDS = int(os.getenv("MESSAGE_COALESCE_MAX_TOTAL_SECONDS", "25"))
# 2026-06-27 (ADR worker-robustez Capa A) — recuperación PERIÓDICA de mensajes
# huérfanos en 'processing'. Antes el sweep solo corría en startup → un mensaje
# atascado por una carrera de coalescing quedaba bloqueado hasta el próximo restart.
# Umbral GENEROSO (muy por encima del procesamiento real ~9-60s) para NUNCA reclamar
# un mensaje legítimamente en curso → evita doble procesamiento. Configurable.
STALE_PROCESSING_RECLAIM_MINUTES = int(os.getenv("STALE_PROCESSING_RECLAIM_MINUTES", "3"))
STALE_PROCESSING_SWEEP_INTERVAL_SECONDS = int(
    os.getenv("STALE_PROCESSING_SWEEP_INTERVAL_SECONDS", "60")
)
HUMAN_TAKEOVER_QUEUE_ENABLED = os.getenv("HUMAN_TAKEOVER_QUEUE_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
HUMAN_TAKEOVER_QUEUE_POLL_BATCH = int(os.getenv("HUMAN_TAKEOVER_QUEUE_POLL_BATCH", "10"))
HUMAN_TAKEOVER_QUEUE_VT_SECONDS = int(os.getenv("HUMAN_TAKEOVER_QUEUE_VT_SECONDS", "90"))
# BLOQUE J (robustez): tope de reintentos (read_ct de pgmq) antes de dead-letter.
# Sin esto, un evento que falla persistentemente (Telegram unreachable, todos los
# emails Resend fallando) se re-entrega para siempre cada VT.
HUMAN_TAKEOVER_MAX_READ_CT = int(os.getenv("HUMAN_TAKEOVER_MAX_READ_CT", "10"))
WHATSAPP_OUTBOUND_QUEUE_ENABLED = os.getenv("WHATSAPP_OUTBOUND_QUEUE_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
WHATSAPP_OUTBOUND_QUEUE_POLL_BATCH = int(os.getenv("WHATSAPP_OUTBOUND_QUEUE_POLL_BATCH", "20"))
WHATSAPP_OUTBOUND_QUEUE_VT_SECONDS = int(os.getenv("WHATSAPP_OUTBOUND_QUEUE_VT_SECONDS", "90"))
WHATSAPP_OUTBOUND_MAX_ATTEMPTS = int(os.getenv("WHATSAPP_OUTBOUND_MAX_ATTEMPTS", "5"))
IDEMPOTENCY_CLEANUP_ENABLED = os.getenv("IDEMPOTENCY_CLEANUP_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS = int(os.getenv("IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS", "3600"))
IDEMPOTENCY_CLEANUP_BATCH = int(os.getenv("IDEMPOTENCY_CLEANUP_BATCH", "2000"))
PENDING_PAYMENT_RELEASE_ENABLED = os.getenv("PENDING_PAYMENT_RELEASE_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
PENDING_PAYMENT_RELEASE_INTERVAL_SECONDS = int(os.getenv("PENDING_PAYMENT_RELEASE_INTERVAL_SECONDS", "600"))
# TTL antes de que el cron cancele una orden `pending_payment` sin pago.
# Diseñado intencionalmente 5 min POR ENCIMA de WOMPI_PAYMENT_LINK_TTL_MINUTES
# (30 min) para dejar una ventana de regeneración:
#   • 0–30 min: link Wompi vigente (bucket a en payment_link_tool reutiliza).
#   • 30–35 min: link expirado pero orden viva (bucket b regenera).
#   • > 35 min sin nuevo intent: cron cancela.
# Si esta constante baja del TTL del link, el cron cerraría órdenes mientras
# el link aún está vivo. Mantener relación: PENDING_PAYMENT_TTL_MINUTES >=
# WOMPI_PAYMENT_LINK_TTL_MINUTES + 5. Detalles: docs/adr/0011-payment-link-lifecycle.md.
PENDING_PAYMENT_TTL_MINUTES = int(os.getenv("PENDING_PAYMENT_TTL_MINUTES", "35"))
# Rev. 103 F1 — Recordatorio de pago dentro de la CSW (24h Meta).
# Solo dispara free-form si la ventana sigue abierta. Sin template messages,
# fuera de CSW Meta rechaza el envío con #131047 — F2 (templates HSM)
# resolverá ese caso. F1 cubre 80% de pedidos: el cliente acaba de pedir el
# link, su último inbound es de hace minutos, CSW abierta.
PAYMENT_REMINDER_ENABLED = os.getenv("PAYMENT_REMINDER_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
PAYMENT_REMINDER_INTERVAL_SECONDS = int(os.getenv("PAYMENT_REMINDER_INTERVAL_SECONDS", "60"))
# Cuándo recordar (default 25 min después de generar el link, dejando 5 min
# antes del expiry de 30 min de Wompi y antes de que el TTL interno cancele
# la orden a los 35 min).
PAYMENT_REMINDER_DELAY_MINUTES = int(os.getenv("PAYMENT_REMINDER_DELAY_MINUTES", "25"))
PAYMENT_REMINDER_WINDOW_MINUTES = int(os.getenv("PAYMENT_REMINDER_WINDOW_MINUTES", "5"))
# Ventana CSW de Meta — fuente: developers.facebook.com (24h tras último
# mensaje del cliente). Si cambia el SLA de Meta, ajustar aquí.
META_CSW_HOURS = int(os.getenv("META_CSW_HOURS", "24"))

# Sem 7 F2 item 6.b — Cron HSM cart_abandoned_24h MARKETING fuera CSW.
# Dispara template MARKETING cart_abandoned_24h_v1 a carritos sin actividad
# >24h cuyo cliente tiene consent_given=TRUE (Habeas Data Ley 1581).
# Costo: ~$0.025 USD/msg (MARKETING tier). ROI esperado positivo por recovery.
# Rev. 109 P1 #1 — Polling backup Wompi (MA-9 universal pattern).
# Si Wompi nunca envía el webhook `transaction.updated` con status=VOIDED
# (visto en sandbox UAT 2026-05-28), el cron lo detecta consultando GET
# /transactions/{id} para órdenes canceladas con refund_method=
# wompi_void_auto cuya payment local sigue marcada APPROVED. Garantiza
# que el cliente reciba notificación de refund aún si webhook falla.
WOMPI_VOID_POLL_ENABLED = os.getenv("WOMPI_VOID_POLL_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
WOMPI_VOID_POLL_INTERVAL_SECONDS = int(
    os.getenv("WOMPI_VOID_POLL_INTERVAL_SECONDS", "1800"),  # 30 min default
)
WOMPI_VOID_POLL_LOOKBACK_HOURS = int(
    os.getenv("WOMPI_VOID_POLL_LOOKBACK_HOURS", "48"),
)

# W2 — Reconciliación del inbox durable Wompi. Re-drive de webhooks de pago
# perdidos por crash del proceso API entre el 200 ACK y el fin del procesamiento
# (Wompi no reintenta un 200 ni ofrece pull por reference). El worker re-POSTea el
# payload crudo a la API → reusa el flujo verificado completo (firma + dedup +
# confirm). Ver migración 20260714000000_wompi_webhook_inbox.
WOMPI_INBOX_RECONCILE_ENABLED = os.getenv("WOMPI_INBOX_RECONCILE_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
WOMPI_INBOX_RECONCILE_INTERVAL_SECONDS = int(
    os.getenv("WOMPI_INBOX_RECONCILE_INTERVAL_SECONDS", "180"),  # 3 min
)
WOMPI_INBOX_MIN_AGE_SECONDS = int(os.getenv("WOMPI_INBOX_MIN_AGE_SECONDS", "120"))  # 2 min grace
WOMPI_INBOX_MAX_ATTEMPTS = int(os.getenv("WOMPI_INBOX_MAX_ATTEMPTS", "5"))
WORKER_API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")

CART_ABANDONED_REMINDER_ENABLED = os.getenv("CART_ABANDONED_REMINDER_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
CART_ABANDONED_REMINDER_INTERVAL_SECONDS = int(
    os.getenv("CART_ABANDONED_REMINDER_INTERVAL_SECONDS", "300")  # cada 5min
)
# Mínimo de horas desde última actividad del carrito para disparar el HSM.
# Debe ser > META_CSW_HOURS porque dentro CSW free-form ya cubrió (cero costo).
CART_ABANDONED_THRESHOLD_HOURS = int(
    os.getenv("CART_ABANDONED_THRESHOLD_HOURS", "24")
)
# Tope superior para no enviar recordatorios infinitos (carrito >7d se abandona).
CART_ABANDONED_MAX_AGE_HOURS = int(
    os.getenv("CART_ABANDONED_MAX_AGE_HOURS", "72")
)
# Descuento default que ofrece el template MARKETING (placeholder {{3}}).
# Tenants pueden override per-tenant en futuro. Hoy 10% por default.
CART_ABANDONED_DISCOUNT_LABEL = os.getenv("CART_ABANDONED_DISCOUNT_LABEL", "10%")
# Gap F7-25 (2026-07-04) — Quiet hours para el HSM MARKETING cart_abandoned.
# Meta Marketing + buena praxis Colombia: no promociones de madrugada. Ventana
# silenciosa por defecto 21:00–08:00 hora Colombia (UTC-5 fijo, sin DST). SOLO
# aplica a MARKETING (cart_abandoned); los recordatorios de pago (UTILITY /
# transaccional) NO se silencian. DESACTIVADO por default: (a) es decisión de
# producto qué ventana usar, (b) mantiene deterministas los tests que corren el
# cron sin mockear el reloj. Founder habilita en render.yaml tras confirmar franja.
CART_ABANDONED_QUIET_HOURS_ENABLED = os.getenv(
    "CART_ABANDONED_QUIET_HOURS_ENABLED", "false"
).lower() in {"1", "true", "yes", "on"}
CART_ABANDONED_QUIET_START_HOUR = int(os.getenv("CART_ABANDONED_QUIET_START_HOUR", "21"))
CART_ABANDONED_QUIET_END_HOUR = int(os.getenv("CART_ABANDONED_QUIET_END_HOUR", "8"))
# UTC-5 fijo (America/Bogota no observa DST). Configurable por si cambia el país.
COLOMBIA_UTC_OFFSET_HOURS = int(os.getenv("COLOMBIA_UTC_OFFSET_HOURS", "-5"))
# Gap F7-26 (2026-07-04) — cap per-tenant de HSM MARKETING por ciclo: evita
# ráfagas que disparen META_RATE_LIMIT en un solo WABA (limit(50) es global).
# 0 = sin cap.
CART_ABANDONED_MAX_PER_TENANT_PER_CYCLE = int(
    os.getenv("CART_ABANDONED_MAX_PER_TENANT_PER_CYCLE", "15")
)
# Anti-hibernación Render Free: ping al propio endpoint /health para prevenir que
# el servicio web se hiberne. Solo necesario en plan Free (sin keep-alive nativo).
ANTI_HIBERNATION_ENABLED = os.getenv("ANTI_HIBERNATION_ENABLED", "false").lower() in {
    "1", "true", "yes", "on"
}
ANTI_HIBERNATION_PING_URL = os.getenv("ANTI_HIBERNATION_PING_URL", "")
ANTI_HIBERNATION_INTERVAL_SECONDS = int(os.getenv("ANTI_HIBERNATION_INTERVAL_SECONDS", "840"))  # 14 min

# Rev. 109 founder 2026-05-28 — SLA tracker para human_takeover sin
# respuesta humana. Cierra el loop "super delicado" del escalado: si el
# bot promete especialista y nadie responde, alerta al operador.
HUMAN_TAKEOVER_SLA_CHECK_INTERVAL_SECONDS = int(
    os.getenv("HUMAN_TAKEOVER_SLA_CHECK_INTERVAL_SECONDS", "600")  # 10 min
)
HUMAN_TAKEOVER_SLA_HOURS = int(
    os.getenv("HUMAN_TAKEOVER_SLA_HOURS", "2")  # threshold 2h por defecto
)

# Rev. 109 J.2.4.4 Fase 2 — Tenant hard-delete cron.
TENANT_HARD_DELETE_ENABLED = os.getenv(
    "TENANT_HARD_DELETE_ENABLED", "false"
).lower() in {"1", "true", "yes", "on"}
TENANT_HARD_DELETE_INTERVAL_SECONDS = int(
    os.getenv("TENANT_HARD_DELETE_INTERVAL_SECONDS", "21600")  # 6h default
)
TENANT_HARD_DELETE_BATCH_SIZE = int(
    os.getenv("TENANT_HARD_DELETE_BATCH_SIZE", "10")  # 10 tenants per ciclo
)

# Rev. 109 J.2.11 — Tenant provider health metrics cron.
HEALTH_METRICS_ENABLED = os.getenv(
    "HEALTH_METRICS_ENABLED", "true"
).lower() in {"1", "true", "yes", "on"}
HEALTH_METRICS_INTERVAL_SECONDS = int(
    os.getenv("HEALTH_METRICS_INTERVAL_SECONDS", "300")  # 5 min default
)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
# A0.2c 2026-05-31: SUPABASE_SECRET_KEY (canónico) con fallback legacy SERVICE_ROLE_KEY.
SUPABASE_SERVICE_KEY = (
    os.getenv("SUPABASE_SECRET_KEY", "")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
)


def _round_robin_dequeue_by_tenant(
    pending: list[dict], max_total: int,
) -> list[dict]:
    """Reordena pending messages round-robin por `tenant_id` para fairness.

    Sem 7 F2 cierre 2026-05-21 — pregunta arquitectónica founder UAT:
    "Esta pensando para encolamiento de mensajes... entre tenants?".

    ANTES: el worker tomaba `limit(10) order(created_at)` global → FIFO
    estricto. Si tenant A tenía 100 msgs y tenant B tenía 1, el msg de
    B esperaba hasta que A se vaciara (en práctica: 10 ciclos de poll
    a 3s = 30s de latencia para B). Fairness ROTA.

    AHORA: round-robin entre tenants disponibles. Cada vuelta agrega 1
    mensaje del FIFO interno de cada tenant. Con tenants A(100) y B(1)
    → output: [A1, B1, A2, A3, A4, ...] — B no espera, intercala.

    Si solo hay 1 tenant activo (caso KAIU hoy), comportamiento idéntico
    al legacy (FIFO de ese tenant).

    Args:
        pending: lista de mensajes ya ordenada por created_at asc.
        max_total: cap de mensajes a devolver.

    Returns:
        Lista de hasta `max_total` mensajes intercalados por tenant.
    """
    if not pending:
        return []
    # Preservar orden FIFO dentro de cada tenant (pending viene asc por
    # created_at).
    by_tenant: dict[str, list[dict]] = {}
    tenant_order: list[str] = []  # mantiene orden de primer-visto
    for msg in pending:
        tid = str(msg.get("tenant_id") or "")
        if tid not in by_tenant:
            by_tenant[tid] = []
            tenant_order.append(tid)
        by_tenant[tid].append(msg)

    out: list[dict] = []
    while len(out) < max_total and any(by_tenant[tid] for tid in tenant_order):
        for tid in tenant_order:
            queue = by_tenant[tid]
            if not queue:
                continue
            out.append(queue.pop(0))
            if len(out) >= max_total:
                break
    return out


class OrchestratorWorker:
    """
    Worker de polling que detecta mensajes entrantes no procesados
    y dispara el ciclo de orquestación IA → WhatsApp por cada uno.

    Patrón: Background Worker de Render (sin HTTP).
    Intervalo: configurable via env POLL_INTERVAL_SECONDS (default 3s).
    """

    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError(
                "Faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY "
                "(o SUPABASE_SERVICE_ROLE_KEY legacy)"
            )
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        self._running = False
        # A11 audit 2026-06-25: heartbeat para que /health detecte worker
        # colgado/muerto (Render no auto-reinicia si /health sigue 200).
        self.last_heartbeat_ts = time.time()
        self._queue_runtime_enabled = HUMAN_TAKEOVER_QUEUE_ENABLED
        self._wa_queue_runtime_enabled = WHATSAPP_OUTBOUND_QUEUE_ENABLED
        self._cleanup_enabled = IDEMPOTENCY_CLEANUP_ENABLED
        self._last_cleanup_at = 0.0
        self._release_enabled = PENDING_PAYMENT_RELEASE_ENABLED
        self._last_release_at = 0.0
        self._reminder_enabled = PAYMENT_REMINDER_ENABLED
        self._last_reminder_at = 0.0
        self._cart_abandoned_enabled = CART_ABANDONED_REMINDER_ENABLED
        self._last_cart_abandoned_at = 0.0
        # Rev. 109 P1 #1 — Polling backup Wompi VOIDED.
        self._wompi_void_poll_enabled = WOMPI_VOID_POLL_ENABLED
        self._last_wompi_void_poll_at = 0.0
        # W2 — reconciliación del inbox durable Wompi.
        self._wompi_inbox_reconcile_enabled = WOMPI_INBOX_RECONCILE_ENABLED
        self._last_wompi_inbox_reconcile_at = 0.0
        self._last_wompi_inbox_cleanup_at = 0.0
        self._last_sla_check_at = 0.0
        # Capa A worker-robustez — recuperación periódica de mensajes huérfanos.
        self._last_stale_sweep_at = 0.0
        self._anti_hibernation_enabled = ANTI_HIBERNATION_ENABLED and bool(ANTI_HIBERNATION_PING_URL)
        self._last_ping_at = 0.0
        # Rev. 109 J.2.4.4 Fase 2 — Tenant hard-delete cron timestamps.
        self._tenant_hard_delete_enabled = TENANT_HARD_DELETE_ENABLED
        self._last_tenant_hard_delete_at = 0.0
        # Rev. 109 J.2.11 — health metrics cron timestamps.
        self._health_metrics_enabled = HEALTH_METRICS_ENABLED
        self._last_health_metrics_at = 0.0
        # Snapshot del último status per (tenant, provider, metric) para
        # detectar transiciones healthy → warning/critical (alerta Telegram).
        # F7: fallback in-memory. La fuente autoritativa (survive-restart) es la
        # RPC fn_claim_health_alert; si no existe (migración no aplicada) se
        # degrada a este snapshot. El flag se apaga en el primer fallo de la RPC.
        self._health_status_snapshot: dict[tuple[str, str, str], str] = {}
        self._health_alert_persistent = True
        self._metrics = {
            "poll_cycles": 0,
            "inbound_seen": 0,
            "takeover_events_seen": 0,
            "wa_outbound_events_seen": 0,
            "wa_outbound_sent": 0,
            "wa_outbound_failed": 0,
            "idempotency_cleanup_runs": 0,
            "idempotency_cleanup_deleted": 0,
            "last_cleanup_deleted": 0,
            "expired_orders_cancelled": 0,
            "payment_reminders_sent": 0,
            "payment_reminders_skipped_csw_closed": 0,
            # Sem 7 F2 item 6.b: HSM templates fallback fuera CSW
            "payment_reminders_sent_via_hsm": 0,
            "payment_reminders_hsm_failed": 0,
            "payment_reminders_hsm_not_approved": 0,
            "cart_abandoned_reminders_sent": 0,
            "cart_abandoned_reminders_skipped_no_consent": 0,
            "cart_abandoned_reminders_hsm_failed": 0,
            "cart_abandoned_reminders_hsm_not_approved": 0,
            # F7 gaps 2026-07-04 (worker_jobs closure).
            "payment_reminders_skipped_human_takeover": 0,  # gap F7-7
            "cart_abandoned_skipped_quiet_hours": 0,        # gap F7-25
            "wompi_void_notify_failed": 0,                  # gap F7-14
            "wompi_inbox_depth": 0,                         # W3 T3-01 — backlog sin procesar (gauge)
            "wompi_inbox_dead_lettered": 0,                 # W3 T3-01 — eventos de dinero en dead-letter (alertable)
            "poll_job_errors": 0,                           # Ola 0 — jobs aislados que fallaron
            "sla_notify_failed": 0,                         # gap F7-15
            # F5 bot_engine — rate-limit inbound→LLM (protección costo Gemini).
            "inbound_llm_rate_limited": 0,
        }

    def stop(self):
        self._running = False

    async def run(self):
        self._running = True
        logger.info(f"Worker activo — polling cada {POLL_INTERVAL_SECONDS}s")
        await self._sweep_stale_messages_on_startup()

        while self._running:
            # Heartbeat al tope del loop: si _poll_cycle se cuelga, el timestamp
            # NO avanza → /health lo detecta stale → 503 → Render reinicia.
            self.last_heartbeat_ts = time.time()
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error(f"Error en ciclo de polling: {e}", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _run_job(self, name: str, coro):
        """Aísla un job del ciclo (Ola 0): si falla, loguea + métrica pero NO aborta
        los jobs siguientes. Antes un fallo en un job (p.ej. void poll) tumbaba el
        resto del ciclo — SLA, hard-delete y health dejaban de correr."""
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 — fault isolation deliberada
            self._metrics["poll_job_errors"] = self._metrics.get("poll_job_errors", 0) + 1
            # Sin exc_info=True: el traceback completo puede arrastrar PII de cliente a
            # Sentry (scrubber sistémico va en W1). Tipo + mensaje truncado bastan para
            # diagnosticar QUÉ job y QUÉ clase de error, con menor superficie de PII.
            logger.error(
                "[WORKER] job '%s' falló (aislado, ciclo continúa): %s: %.200s",
                name, type(exc).__name__, str(exc),
            )

    async def _poll_cycle(self):
        """Ejecuta ciclo de inbound + notificaciones operacionales + mantenimiento.

        Cada job va aislado (`_run_job`): un fallo transitorio en uno NO impide que
        corran los demás (dinero/SLA/retención no deben quedar bloqueados por, p.ej.,
        un blip del poll inbound)."""
        self._metrics["poll_cycles"] += 1
        # Capa A — recuperación periódica de mensajes huérfanos en 'processing'
        # (carrera de coalescing/claim). ANTES del poll inbound para que un mensaje
        # re-encolado entre de inmediato al ciclo.
        await self._run_job("sweep_stale_processing", self._sweep_stale_processing_if_due())
        await self._run_job("poll_inbound", self._poll_inbound_messages())
        await self._run_job("human_takeover_notif", self._poll_human_takeover_notifications())
        await self._run_job("whatsapp_outbound", self._poll_whatsapp_outbound_messages())
        await self._run_job("idempotency_cleanup", self._run_idempotency_cleanup_if_due())
        await self._run_job("payment_reminders", self._send_payment_reminders_if_due())
        await self._run_job("cart_abandoned", self._send_cart_abandoned_reminders_if_due())
        await self._run_job("release_pending_payment", self._release_expired_pending_payment_orders())
        await self._run_job("wompi_void_poll", self._poll_wompi_pending_voids_if_due())
        await self._run_job("wompi_inbox_reconcile", self._reconcile_wompi_inbox_if_due())
        await self._run_job("anti_hibernation", self._anti_hibernation_ping_if_due())
        await self._run_job("takeover_sla", self._check_human_takeover_sla_if_due())
        await self._run_job("tenant_hard_delete", self._run_tenant_hard_delete_if_due())
        await self._run_job("health_metrics", self._collect_health_metrics_if_due())

    def _combine_by_conversation(self, msgs: list[dict]) -> list[dict]:
        """Rev. 85 — combina mensajes consecutivos de la MISMA conversación en uno solo
        (el último con el content combinado por `\n\n`), marcando los anteriores como
        'processed' (coalesced). Mensajes de convs distintas pasan independientes.

        Evita el bug donde "Hola" como último msg tras un flujo de compra hacía al bot
        resetear al saludo y perder el contexto previo. Síncrono (sin espera) — la espera
        de la ventana vive en `_coalesce_claimed_by_conversation`.
        """
        if not msgs:
            return msgs
        from collections import OrderedDict
        by_conv: dict = OrderedDict()
        for m in msgs:
            by_conv.setdefault(m["conversation_id"], []).append(m)

        coalesced: list[dict] = []
        for conv_id, conv_msgs in by_conv.items():
            if len(conv_msgs) >= 2:
                conv_msgs = sorted(conv_msgs, key=lambda m: str(m.get("created_at") or ""))
                older_ids = [m["id"] for m in conv_msgs[:-1]]
                conv_tenant_id = conv_msgs[0]["tenant_id"]
                # F48 — Claim NO-terminal (patrón claim->work->finalize). Antes se
                # marcaban los fragmentos viejos a estado TERMINAL 'processed' ANTES
                # del CAS/dispatch → si el dispatch fallaba quedaban IRRECUPERABLES
                # (el sweep periódico solo reclama 'processing') y el retry perdía el
                # turno combinado. Ahora se reclaman a 'processing'; se finalizan a
                # 'coalesced_into_next' SOLO tras dispatch OK; en except vuelven a
                # 'pending' (el próximo poll re-combina el turno COMPLETO); si el
                # worker muere, el sweep periódico los reclama. El CAS-guard
                # 'pending' evita pisar el claim de otro worker.
                try:
                    self.supabase.table("messages").update({
                        "processing_status": PROCESSING_STATUS_PROCESSING,
                        "last_error": None,
                    }).in_("id", older_ids).eq("tenant_id", conv_tenant_id).eq(
                        "processing_status", "pending").execute()
                except Exception as exc:
                    logger.warning("[COALESCE] no pude reclamar fragmentos viejos: %s", exc)
                last = dict(conv_msgs[-1])
                last["content"] = "\n\n".join(str(m.get("content") or "") for m in conv_msgs)
                last["_coalesced_ids"] = older_ids
                last["_coalesced_tenant_id"] = conv_tenant_id
                logger.info(
                    "[COALESCE] conv=%s coalesce %d mensajes en uno (chars=%d)",
                    conv_id[:8], len(conv_msgs), len(last["content"]),
                )
                coalesced.append(last)
            else:
                coalesced.append(conv_msgs[0])
        return coalesced

    @staticmethod
    def _batch_ages(pending: list[dict], now: datetime) -> tuple[float, float]:
        """Devuelve (oldest_age, newest_age) en segundos del lote pending.
          • oldest_age = edad del mensaje MÁS VIEJO (para el tope total).
          • newest_age = edad del mensaje MÁS NUEVO = tiempo desde el ÚLTIMO mensaje
            (para el debounce de silencio). inf si no hay timestamps válidos → procesar ya.
        """
        oldest = 0.0
        newest = float("inf")
        for m in pending:
            ts = m.get("created_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                age = (now - dt).total_seconds()
            except (ValueError, TypeError):
                continue
            oldest = max(oldest, age)
            newest = min(newest, age)
        return oldest, newest

    @staticmethod
    def _is_quiet_hour_colombia(now_dt: datetime) -> bool:
        """Gap F7-25 — True si `now_dt` (UTC) cae en la franja silenciosa de
        Colombia para HSM MARKETING. Ventana [start, end) en hora local; soporta
        cruce de medianoche (ej. 21→8). start==end o flag off ⇒ nunca silencia."""
        if not CART_ABANDONED_QUIET_HOURS_ENABLED:
            return False
        start = CART_ABANDONED_QUIET_START_HOUR % 24
        end = CART_ABANDONED_QUIET_END_HOUR % 24
        if start == end:
            return False
        local_hour = (now_dt.hour + COLOMBIA_UTC_OFFSET_HOURS) % 24
        if start < end:
            return start <= local_hour < end
        # Ventana que cruza medianoche (ej. 21:00–08:00).
        return local_hour >= start or local_hour < end

    @staticmethod
    def _cap_per_tenant(rows: list[dict], cap: int) -> list[dict]:
        """Gap F7-26 — limita a `cap` filas por tenant_id preservando orden.
        cap<=0 ⇒ sin límite. Evita ráfagas de HSM sobre un único WABA."""
        if cap <= 0:
            return rows
        counts: dict[str, int] = {}
        out: list[dict] = []
        for r in rows:
            tid = str(r.get("tenant_id") or "")
            if counts.get(tid, 0) >= cap:
                continue
            counts[tid] = counts.get(tid, 0) + 1
            out.append(r)
        return out

    async def _coalesce_pending_by_conversation(self, pending: list[dict]) -> list[dict]:
        """DEBOUNCE NO-BLOQUEANTE por conversación (2026-06-27, founder + review adversarial).

        Para cada conversación con mensajes en el lote, re-fetchea TODOS sus pending
        (scopeado por tenant+conversación) y mide el SILENCIO: procesa la conversación SOLO si
        su ÚLTIMO mensaje ya tiene >= MESSAGE_COALESCE_WINDOW_SECONDS (el cliente dejó de
        escribir) o el más viejo llegó al tope MESSAGE_COALESCE_MAX_TOTAL_SECONDS. Las que
        siguen "tecleando" se DEJAN pending y se re-evalúan en el próximo poll (~cada
        POLL_INTERVAL_SECONDS) — SIN bloquear el ciclo (NO hay sleep).

        Por qué no-bloqueante + por-conversación (review adversarial 2026-06-27):
          • Un sleep en el ciclo congelaba el envío de salientes y el mantenimiento hasta el
            tope. Ahora el "esperar" es implícito: se omite la conversación y se revisa luego.
          • El silencio/tope se miden POR conversación (no sobre el lote global), así un
            mensaje viejo de OTRA conversación (o uno recuperado por el sweep) ya no corta el
            debounce de una conversación activa (bug [A1]).
          • El re-fetch está scopeado a la conversación → no secuestra mensajes ajenos ni
            pierde fragmentos nuevos por el límite global (bug [C1]).

        Devuelve los mensajes combinados de las conversaciones LISTAS (puede ser []).
        """
        if not pending:
            return pending

        from collections import OrderedDict
        convs: "OrderedDict" = OrderedDict()
        for m in pending:
            convs[(m["tenant_id"], m["conversation_id"])] = True

        now = datetime.now(timezone.utc)
        ready: list[dict] = []
        for tenant_id, conv_id in convs:
            # Re-fetch SCOPED: todos los pending de ESTA conversación (no perder fragmentos
            # ni mezclar otras convs). Límite holgado por si hay muchos fragmentos.
            try:
                res = (
                    self.supabase.table("messages")  # tenant_filter:exempt:cron_cross_tenant_inbound_polling
                    .select("id, tenant_id, conversation_id, content, content_type, processing_attempts, created_at")
                    .eq("direction", "inbound")
                    .eq("processing_status", "pending")
                    .eq("tenant_id", tenant_id)
                    .eq("conversation_id", conv_id)
                    .order("created_at", desc=False)
                    .limit(25)
                    .execute()
                )
                conv_msgs = res.data or []
            except Exception as exc:
                logger.warning("[COALESCE] re-fetch conv=%s falló: %s", conv_id[:8], exc)
                # Fail-safe: procesar lo que ya teníamos de esta conv (no colgar el turno).
                conv_msgs = [m for m in pending if m.get("conversation_id") == conv_id]

            if not conv_msgs:
                continue
            oldest_age, newest_age = self._batch_ages(conv_msgs, now)
            if newest_age >= MESSAGE_COALESCE_WINDOW_SECONDS:
                ready.extend(conv_msgs)            # silencio → listo
            elif oldest_age >= MESSAGE_COALESCE_MAX_TOTAL_SECONDS:
                logger.info(
                    "[COALESCE] conv=%s tope %ds (primero hace %.1fs); proceso ya",
                    conv_id[:8], MESSAGE_COALESCE_MAX_TOTAL_SECONDS, oldest_age,
                )
                ready.extend(conv_msgs)            # tope → listo (no colgar)
            else:
                logger.info(
                    "[COALESCE] conv=%s aún escribiendo (último hace %.1fs); re-evalúo próximo poll",
                    conv_id[:8], newest_age,
                )
                # NO se procesa este ciclo → queda pending → próximo poll (~POLL_INTERVAL).

        return self._combine_by_conversation(ready)

    def _inbound_llm_rate_limited(self, tenant_id: str, conversation_id: str) -> bool:
        """True si la conversación superó el cap inbound→LLM en la ventana.

        F5 bot_engine — protección de costo Gemini. Reusa el RPC distribuido
        `rate_limit_hit(p_key, p_limit, p_window_seconds)` (migración 20260425)
        con key `{tenant_id}:inbound_llm:{conversation_id}`. Fail-open: si el
        RPC falla (DB hiccup), NO bloqueamos al cliente (preferible pagar el
        turno que dejar mudo al bot por un error de infra). Cap<=0 ⇒ desactivado.
        """
        if INBOUND_LLM_RATE_LIMIT <= 0:
            return False
        try:
            key = f"{tenant_id}:inbound_llm:{conversation_id}"
            res = self.supabase.rpc("rate_limit_hit", {
                "p_key": key,
                "p_limit": INBOUND_LLM_RATE_LIMIT,
                "p_window_seconds": INBOUND_LLM_RATE_WINDOW_SECONDS,
            }).execute()
            rows = res.data or []
            row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else {})
            # allowed=True mientras count<=limit → rate_limited = NOT allowed.
            return not bool(row.get("allowed", True))
        except Exception as exc:
            logger.warning(
                "[INBOUND_RATE_LIMIT] RPC falló conv=%s: %s — fail-open",
                str(conversation_id)[:8], exc,
            )
            return False

    async def _poll_inbound_messages(self):
        """Busca mensajes inbound pendientes y los orquesta.

        Rev. 85 — Coalescing: agrupa por conversation_id. Si una conv
        tiene múltiples mensajes pendientes (cliente envió varios
        seguidos), espera la ventana de debounce y los junta en un solo
        input al LLM. Evita que el último mensaje (típicamente "Hola"
        o follow-up corto) domine el contexto y haga al bot perder el
        flujo previo.

        Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (pregunta arquitectónica):
        Encolamiento por tenant — fairness round-robin. ANTES: FIFO global
        ordenado por created_at, top 10. Si tenant A tiene 100 msgs y tenant
        B tiene 1, B esperaba 10 ciclos de poll (~30s) para ser procesado
        porque A monopolizaba la cola.
        AHORA: traer ventana mayor (50 mensajes top-FIFO), aplicar round-robin
        por tenant_id para que cada tenant reciba al menos 1 turn por ciclo
        cuando tenga mensajes pendientes. Reordena los 10 finales que se
        procesarán este ciclo. Con N=1 tenant activo el comportamiento es
        idéntico al legacy (FIFO).
        """
        # Selección amplia (50) para muestrear varios tenants; luego
        # round-robin filtra a 10 procesables.
        result = (
            self.supabase.table("messages")  # tenant_filter:exempt:cron_cross_tenant_inbound_polling
            .select("id, tenant_id, conversation_id, content, content_type, processing_attempts, created_at")
            .eq("direction", "inbound")
            .eq("processing_status", "pending")
            .order("created_at", desc=False)
            .limit(50)
            .execute()
        )

        pending = _round_robin_dequeue_by_tenant(result.data or [], max_total=10)
        if not pending:
            return
        self._metrics["inbound_seen"] += len(pending)

        logger.info(f"📬 {len(pending)} mensaje(s) pendiente(s) encontrado(s)")

        # Coalesce-first: agrupar fragmentos del mismo cliente ANTES de reclamar (preserva
        # el coalescing — el claim-first lo dispersaba). La carrera de claim se maneja con
        # la red de seguridad (Capa A recuperación periódica + reset en except), sin romper
        # el coalescing.
        pending = await self._coalesce_pending_by_conversation(pending)

        # Procesar en secuencia (reclamar atómicamente + despachar) para no sobrecargar Gemini.
        for msg in pending:
            # F45: latir POR MENSAJE — un batch de N mensajes con Gemini lento (cascada ~63s/mensaje)
            # superaba HEALTH_HEARTBEAT_STALE_SECONDS=120 → /health 503 → Render reiniciaba a mitad del
            # batch (riesgo de respuesta duplicada si el kill cae entre send y mark). El worker está VIVO
            # aunque Gemini esté lento; un solo mensaje colgado >120s sigue disparando el restart real.
            self.last_heartbeat_ts = time.time()
            attempts = int(msg.get("processing_attempts") or 0) + 1
            if attempts > MAX_PROCESSING_ATTEMPTS:
                try:
                    self.supabase.table("messages").update({
                        "processing_status": "failed",
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": "max_attempts_exceeded",
                    }).eq("id", msg["id"]).eq("tenant_id", msg["tenant_id"]).eq(
                        "processing_status", "pending").execute()
                except Exception as exc:
                    logger.warning("No pude marcar failed %s: %s", msg["id"], exc)
                logger.warning(
                    "Mensaje %s marcado failed por max_attempts=%s",
                    msg["id"], MAX_PROCESSING_ATTEMPTS,
                )
                continue
            # Lock atómico (CAS): solo procesamos si sigue 'pending'.
            lock_res = self.supabase.table("messages").update({
                "processing_attempts": attempts,
                "processing_status": PROCESSING_STATUS_PROCESSING,
                "last_error": None,
            }).eq("id", msg["id"]).eq("tenant_id", msg["tenant_id"]).eq(
                "processing_status", "pending").execute()
            if not lock_res.data:
                logger.info(
                    "Mensaje %s ya fue tomado por otro worker. Saltando.", msg["id"]
                )
                continue
            # F5 bot_engine — rate-limit inbound→LLM por conversación (protección
            # de costo Gemini). Si la conversación superó el cap en la ventana, NO
            # despachamos al LLM: marcamos el mensaje procesado con skip_reason y
            # seguimos. Silencioso por diseño (una ráfaga anómala no debe generar
            # ni costo LLM ni costo outbound). CAS-guard ya nos dio el lock.
            if self._inbound_llm_rate_limited(msg["tenant_id"], msg["conversation_id"]):
                self._metrics["inbound_llm_rate_limited"] += 1
                logger.warning(
                    "[INBOUND_RATE_LIMIT] conv=%s tenant=%s superó %d msg/%ds — "
                    "skip LLM (protección costo)",
                    str(msg["conversation_id"])[:8], str(msg["tenant_id"])[:8],
                    INBOUND_LLM_RATE_LIMIT, INBOUND_LLM_RATE_WINDOW_SECONDS,
                )
                try:
                    self.supabase.table("messages").update({
                        "processing_status": "processed",
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "skip_reason": "inbound_llm_rate_limited",
                    }).eq("id", msg["id"]).eq("tenant_id", msg["tenant_id"]).eq(
                        "processing_status", PROCESSING_STATUS_PROCESSING).execute()
                except Exception as _rl_exc:
                    logger.warning(
                        "[INBOUND_RATE_LIMIT] no pude marcar processed %s: %s",
                        msg["id"], _rl_exc,
                    )
                continue
            try:
                # ADR-0018 Fase B+C: dispatcher decide legacy/agentic/shadow según flags.
                await _agentic_dispatch_message(
                    self.supabase,
                    message_id=msg["id"],
                    tenant_id=msg["tenant_id"],
                    conversation_id=msg["conversation_id"],
                    content=msg["content"],
                    content_type=msg["content_type"],
                )
                # F48 — Dispatch OK: recién AHORA finalizamos los fragmentos coalesced
                # a terminal (antes se marcaban 'processed' antes del dispatch, lo que
                # los volvía irrecuperables ante fallo). Si el dispatch hubiera fallado,
                # el except los devuelve a 'pending' para re-combinar el turno completo.
                _coalesced_ids = msg.get("_coalesced_ids")
                if _coalesced_ids:
                    try:
                        self.supabase.table("messages").update({
                            "processing_status": "processed",
                            "processed": True,
                            "processed_at": datetime.now(timezone.utc).isoformat(),
                            "skip_reason": "coalesced_into_next",
                        }).in_("id", _coalesced_ids).eq(
                            "tenant_id", msg["_coalesced_tenant_id"]).eq(
                            "processing_status", PROCESSING_STATUS_PROCESSING).execute()
                    except Exception as _fin_exc:
                        logger.warning(
                            "[COALESCE] no pude finalizar fragmentos coalesced %s: %s",
                            _coalesced_ids, _fin_exc,
                        )
            except Exception as e:
                logger.error(
                    f"Error procesando mensaje {msg['id']}: {e}", exc_info=True
                )
                # Worker-robustez (except-fix): si el dispatch lanzó (mensaje 'processing')
                # sin que el core lo marcara, quedaría HUÉRFANO. Lo reseteamos con CAS-guard
                # (solo si SIGUE 'processing', sin pisar lo que el core ya marcó): failed si
                # superó max attempts, si no pending para reintentar.
                try:
                    # F48 — mismo destino para el último fragmento Y los coalesced:
                    # retry->'pending' (el próximo poll re-combina el turno completo),
                    # max-attempts->'failed' (evita que el sweep los resucite como
                    # turnos parciales sueltos). CAS-guard 'processing' en todos.
                    _coalesced_ids = msg.get("_coalesced_ids") or []
                    _coalesced_tid = msg.get("_coalesced_tenant_id")
                    if attempts >= MAX_PROCESSING_ATTEMPTS:
                        self.supabase.table("messages").update({
                            "processing_status": "failed",
                            "processed": True,
                            "processed_at": datetime.now(timezone.utc).isoformat(),
                            "last_error": f"dispatch_exception_max_attempts: {str(e)[:180]}",
                        }).eq("id", msg["id"]).eq("tenant_id", msg["tenant_id"]).eq(
                            "processing_status", "processing").execute()
                        # Turno agotado: cerrar también los fragmentos coalesced.
                        if _coalesced_ids:
                            self.supabase.table("messages").update({
                                "processing_status": "failed",
                                "processed": True,
                                "processed_at": datetime.now(timezone.utc).isoformat(),
                                "last_error": "coalesced_turn_failed_max_attempts",
                            }).in_("id", _coalesced_ids).eq(
                                "tenant_id", _coalesced_tid).eq(
                                "processing_status", "processing").execute()
                    else:
                        self.supabase.table("messages").update({
                            "processing_status": "pending",
                            "last_error": f"dispatch_exception_retry: {str(e)[:180]}",
                        }).eq("id", msg["id"]).eq("tenant_id", msg["tenant_id"]).eq(
                            "processing_status", "processing").execute()
                        # Devolver los fragmentos coalesced a 'pending': el próximo poll
                        # re-combina el TURNO COMPLETO (no solo el último fragmento).
                        if _coalesced_ids:
                            self.supabase.table("messages").update({
                                "processing_status": "pending",
                            }).in_("id", _coalesced_ids).eq(
                                "tenant_id", _coalesced_tid).eq(
                                "processing_status", "processing").execute()
                except Exception as _reset_exc:
                    logger.error(
                        "No pude resetear mensaje %s tras excepción de dispatch: %s",
                        msg["id"], _reset_exc,
                    )

    async def _poll_human_takeover_notifications(self):
        """
        Consume eventos de takeover desde Supabase Queues (pgmq) y despacha
        por canales habilitados del tenant.
        """
        if not self._queue_runtime_enabled:
            return
        if not hasattr(self.supabase, "rpc"):
            return

        try:
            res = self.supabase.rpc(
                "dequeue_human_takeover_notifications",
                {
                    "p_vt": max(1, HUMAN_TAKEOVER_QUEUE_VT_SECONDS),
                    "p_qty": max(1, HUMAN_TAKEOVER_QUEUE_POLL_BATCH),
                },
            ).execute()
        except Exception as exc:
            text = str(exc).lower()
            if "does not exist" in text or "dequeue_human_takeover_notifications" in text:
                logger.warning(
                    "Queue de takeover no disponible aún (falta migración). "
                    "Se desactiva consumo en este proceso."
                )
                self._queue_runtime_enabled = False
                return
            logger.error("Error leyendo cola de takeover: %s", exc)
            return

        events = res.data or []
        if not events:
            return

        logger.info("📣 %s evento(s) takeover en cola", len(events))
        self._metrics["takeover_events_seen"] += len(events)

        for event in events:
            msg_id = event.get("msg_id")
            payload = event.get("message")

            if not msg_id:
                logger.warning("Evento takeover sin msg_id: %s", event)
                continue

            if not isinstance(payload, dict):
                logger.warning("Payload inválido en msg_id=%s. Se ACK para evitar bloqueo.", msg_id)
                self._ack_human_takeover_message(msg_id)
                continue

            try:
                handled = await dispatch_human_takeover_event(self.supabase, payload)
            except Exception as exc:
                logger.error("Error despachando takeover msg_id=%s: %s", msg_id, exc, exc_info=True)
                handled = False

            if handled:
                self._ack_human_takeover_message(msg_id)
            else:
                # BLOQUE J (robustez): dead-letter tras N reintentos. read_ct lo
                # expone el RPC (pgmq.read incrementa el contador por lectura). Si
                # el evento falla persistentemente, ACK (delete) + alerta para que
                # NO se re-entregue infinitamente; el operador queda notificado del
                # escalamiento perdido por el log/Sentry.
                read_ct = int(event.get("read_ct") or 0)
                if read_ct >= HUMAN_TAKEOVER_MAX_READ_CT:
                    # NO loguear el payload crudo: lleva customer_phone (PII) y
                    # Sentry LoggingIntegration captura ERROR sin scrub de mensaje
                    # → violaría "NUNCA PII a Sentry" (observability._before_send).
                    # Solo IDs no-PII para diagnóstico.
                    logger.error(
                        "[TAKEOVER] DEAD-LETTER msg_id=%s tras %d reintentos — "
                        "ACK para no re-entregar. Escalamiento NO despachado por "
                        "push (revisar canales del tenant=%s conv=%s); el operador "
                        "aún lo ve en el Inbox (conversación en human_takeover).",
                        msg_id, read_ct,
                        str(payload.get("tenant_id") or "?")[:8],
                        str(payload.get("conversation_id") or "?")[:8],
                    )
                    self._metrics["takeover_events_dead_lettered"] = (
                        self._metrics.get("takeover_events_dead_lettered", 0) + 1
                    )
                    self._ack_human_takeover_message(msg_id)
                else:
                    logger.warning(
                        "Takeover msg_id=%s no ACK (retry %d/%d tras VT)",
                        msg_id, read_ct, HUMAN_TAKEOVER_MAX_READ_CT,
                    )

    def _ack_human_takeover_message(self, msg_id: int) -> None:
        try:
            self.supabase.rpc("ack_human_takeover_notification", {"p_msg_id": msg_id}).execute()
        except Exception as exc:
            logger.error("No se pudo ACK msg_id=%s: %s", msg_id, exc)

    async def _poll_whatsapp_outbound_messages(self):
        """
        Consume cola durable de outbound humano y realiza envío real a WhatsApp.
        """
        if not self._wa_queue_runtime_enabled:
            return
        if not hasattr(self.supabase, "rpc"):
            return

        try:
            res = self.supabase.rpc(
                "dequeue_whatsapp_outbound_messages",
                {
                    "p_vt": max(1, WHATSAPP_OUTBOUND_QUEUE_VT_SECONDS),
                    "p_qty": max(1, WHATSAPP_OUTBOUND_QUEUE_POLL_BATCH),
                },
            ).execute()
        except Exception as exc:
            text = str(exc).lower()
            if "does not exist" in text or "dequeue_whatsapp_outbound_messages" in text:
                logger.warning(
                    "Queue outbound WhatsApp no disponible aún (falta migración). "
                    "Se desactiva consumo en este proceso."
                )
                self._wa_queue_runtime_enabled = False
                return
            logger.error("Error leyendo cola outbound WhatsApp: %s", exc)
            return

        events = res.data or []
        if not events:
            return

        logger.info("📤 %s outbound message(s) en cola", len(events))
        self._metrics["wa_outbound_events_seen"] += len(events)
        for event in events:
            msg_id = event.get("msg_id")
            read_ct = int(event.get("read_ct") or 0)
            payload = event.get("message")

            if not msg_id:
                logger.warning("Outbound event sin msg_id: %s", event)
                continue

            if not isinstance(payload, dict):
                logger.warning("Payload outbound inválido msg_id=%s. ACK para desbloquear cola.", msg_id)
                self._ack_whatsapp_outbound_message(msg_id)
                continue

            tenant_id = str(payload.get("tenant_id") or "").strip()
            to_phone = str(payload.get("customer_phone") or "").strip()
            text = str(payload.get("text") or "").strip()
            message_id = str(payload.get("message_id") or "").strip()
            # Rev. 109 P0-2 — soporte attachments imagen outbound humano.
            # Si hay image_link, text se vuelve OPCIONAL (servirá como caption).
            image_link = str(payload.get("image_link") or "").strip() or None
            image_caption = str(payload.get("image_caption") or "").strip() or None

            # Validación: tenant+phone+message_id obligatorios SIEMPRE.
            # text obligatorio SOLO si NO hay image_link (modo legacy texto).
            if not tenant_id or not to_phone or not message_id:
                logger.error("Payload outbound incompleto msg_id=%s payload=%s", msg_id, payload)
                self._mark_outbound_failed(tenant_id, message_id, "invalid_outbound_payload")
                self._ack_whatsapp_outbound_message(msg_id)
                continue
            if not text and not image_link:
                logger.error(
                    "Payload outbound sin text ni image_link msg_id=%s payload=%s",
                    msg_id, payload,
                )
                self._mark_outbound_failed(tenant_id, message_id, "invalid_outbound_payload")
                self._ack_whatsapp_outbound_message(msg_id)
                continue

            try:
                # Si hay image_link → tipo imagen Meta. Caption opcional = text si existe.
                # Si NO hay image_link → texto plain (modo legacy preservado).
                if image_link:
                    meta_message_id = await send_whatsapp_message(
                        tenant_id=tenant_id,
                        supabase=self.supabase,
                        to_phone=to_phone,
                        image_link=image_link,
                        image_caption=image_caption or (text if text else None),
                    )
                else:
                    meta_message_id = await send_whatsapp_message(
                        tenant_id=tenant_id,
                        supabase=self.supabase,
                        to_phone=to_phone,
                        text=text,
                    )
            except Exception as exc:
                logger.error("Error enviando outbound msg_id=%s: %s", msg_id, exc, exc_info=True)
                meta_message_id = None

            if meta_message_id:
                # Meta ya entregó. ACK pgmq sí o sí (NO podemos reenviar y duplicar al cliente).
                # Si DB falla, _mark_outbound_sent registra ack_pending para reconciliar después.
                ack_ok = self._mark_outbound_sent(tenant_id, message_id, str(meta_message_id))
                self._ack_whatsapp_outbound_message(msg_id)
                if ack_ok:
                    self._metrics["wa_outbound_sent"] += 1
                else:
                    self._metrics["wa_outbound_ack_pending"] = self._metrics.get("wa_outbound_ack_pending", 0) + 1
                continue

            if read_ct >= max(1, WHATSAPP_OUTBOUND_MAX_ATTEMPTS):
                logger.error(
                    "Outbound msg_id=%s alcanzó max intentos (%s). Se marca failed y ACK.",
                    msg_id,
                    WHATSAPP_OUTBOUND_MAX_ATTEMPTS,
                )
                self._mark_outbound_failed(tenant_id, message_id, "outbound_send_failed_max_attempts")
                self._ack_whatsapp_outbound_message(msg_id)
                self._metrics["wa_outbound_failed"] += 1
            else:
                logger.warning("Outbound msg_id=%s no enviado; retry tras VT (read_ct=%s)", msg_id, read_ct)

    async def _run_idempotency_cleanup_if_due(self):
        if not self._cleanup_enabled:
            return
        if not hasattr(self.supabase, "rpc"):
            return

        now = time.time()
        if self._last_cleanup_at and (now - self._last_cleanup_at) < max(60, IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS):
            return

        self._last_cleanup_at = now
        # Limpiar también ventanas de rate limit expiradas (tabla distribuida)
        try:
            self.supabase.rpc(
                "cleanup_expired_rate_limit_windows",
                {"p_limit": 5000},
            ).execute()
        except Exception:
            pass  # La función puede no existir si la migración no está aplicada aún

        # Rev. 69 — cleanup del dedup distribuido de webhooks MeLi.
        try:
            self.supabase.rpc("cleanup_expired_meli_webhook_dedup").execute()
        except Exception:
            pass  # La función puede no existir si la migración rev. 69 no está aplicada

        # Rev. 109 (F.10 cierre / MA-2) — cleanup grace period expirado en
        # tenant_webhook_secrets. NULL-out previous_secret_hash + grace_period_until
        # cuando grace_period_until < NOW(). Defense-in-depth: el verify_inbound_secret()
        # Python ya chequea timestamp, pero borrar el hash zombie reduce surface.
        try:
            self.supabase.rpc("fn_cleanup_webhook_secrets").execute()
        except Exception:
            pass  # La función puede no existir si la migración 20260614110000 no está aplicada

        # Rev. 71 — cleanup del bot_source_log (TTL 30 días, append-only).
        try:
            self.supabase.rpc("cleanup_expired_bot_source_log", {"retention_days": 30}).execute()
        except Exception:
            pass  # La función puede no existir si la migración rev. 71 no está aplicada

        # F111 (audit 2026-07-03) — cleanup de outbound_idempotency_cache (MA-1). La
        # migración 20260514150000 creó tabla + RPC outbound_idempotency_cleanup ('llamar
        # daily') pero NADIE la agendó → si algún IntegrationClient empieza a registrar
        # entradas, la tabla crecería sin poda. Se agenda junto al resto del cleanup.
        try:
            self.supabase.rpc("outbound_idempotency_cleanup", {}).execute()
        except Exception:
            pass  # La función puede no existir si la migración MA-1 no está aplicada

        try:
            res = self.supabase.rpc(
                "cleanup_expired_idempotency_keys",
                {"p_limit": max(1, IDEMPOTENCY_CLEANUP_BATCH)},
            ).execute()
            raw = res.data
            if isinstance(raw, list):
                value = raw[0] if raw else 0
                if isinstance(value, dict):
                    value = next(iter(value.values()), 0)
                deleted = int(value or 0)
            else:
                deleted = int(raw or 0)
            self._metrics["idempotency_cleanup_runs"] += 1
            self._metrics["idempotency_cleanup_deleted"] += deleted
            self._metrics["last_cleanup_deleted"] = deleted
            logger.info(
                "🧹 Idempotency cleanup ejecutado: deleted=%s limit=%s",
                deleted,
                IDEMPOTENCY_CLEANUP_BATCH,
            )
        except Exception as exc:
            text = str(exc).lower()
            if "does not exist" in text or "cleanup_expired_idempotency_keys" in text:
                logger.warning(
                    "Función cleanup_expired_idempotency_keys no disponible aún (falta migración). "
                    "Se desactiva mantenimiento en este proceso."
                )
                self._cleanup_enabled = False
                return
            logger.error("Error ejecutando cleanup de idempotency keys: %s", exc)

    async def _anti_hibernation_ping_if_due(self) -> None:
        """
        Hace un GET al endpoint /health de los servicios web para evitar la
        hibernación de Render Free (hiberna tras 15 min de inactividad).
        Solo activo cuando ANTI_HIBERNATION_ENABLED=true y ANTI_HIBERNATION_PING_URL configurada.

        Ejemplo de configuración:
          ANTI_HIBERNATION_ENABLED=true
          ANTI_HIBERNATION_PING_URL=https://konvi-web.onrender.com/api/health,https://konvi-api.onrender.com/health
        """
        if not self._anti_hibernation_enabled:
            return
        now = time.time()
        if now - self._last_ping_at < max(60, ANTI_HIBERNATION_INTERVAL_SECONDS):
            return
        self._last_ping_at = now

        import httpx
        urls = [u.strip() for u in ANTI_HIBERNATION_PING_URL.split(",") if u.strip()]
        for url in urls:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url)
                    logger.debug("[PING] %s → %s", url, resp.status_code)
            except Exception as exc:
                logger.warning("[PING] Error haciendo ping a %s: %s", url, exc)

    async def _check_human_takeover_sla_if_due(self) -> None:
        """Rev. 109 founder 2026-05-28 — SLA tracker para escalaciones.

        Cierra el loop "super delicado": el bot promete especialista,
        cambia status a human_takeover, notifica vía Telegram… pero ¿qué
        pasa si nadie responde en X horas? El cliente queda esperando.

        Este check:
          1. Cada N min (default 10), busca convs `status='human_takeover'`.
          2. Para cada una, identifica `escalated_at` (último audit row
             `content_type='escalation_audit'`).
          3. Verifica si hubo respuesta humana después (outbound text
             post-escalación).
          4. Si NO Y han pasado >SLA_HOURS desde escalated_at → notifica
             Telegram al operador del tenant.
          5. Idempotencia: inserta audit row `content_type='sla_breach_audit'`
             para no re-alertar (append-only flag).

        F6: la antigüedad de la escalación se ancla en `conversations.human_takeover_at`
        (estampado por trigger BEFORE UPDATE al entrar a human_takeover), que NO se
        renueva con inbounds del cliente. `escalation_audit` sigue delimitando "¿respondió
        el operador?" y el texto de alerta.
        """
        now = time.time()
        if now - self._last_sla_check_at < max(60, HUMAN_TAKEOVER_SLA_CHECK_INTERVAL_SECONDS):
            return
        self._last_sla_check_at = now

        sla_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=HUMAN_TAKEOVER_SLA_HOURS)
        ).isoformat()

        try:
            # Convs en human_takeover desde hace ≥ SLA_HOURS. F6: se gatea por human_takeover_at (instante
            # de escalación, estampado por trigger) que NO se renueva con inbounds — antes usaba
            # last_interaction_at, que el cliente renovaba escribiendo → escaladas activas nunca disparaban.
            # Fallback defensivo vía .or_(): si human_takeover_at es NULL (edge legacy/insert-directo), usa
            # last_interaction_at para no perder cobertura (post-migración+backfill no debería haber NULLs).
            convs_res = (
                self.supabase.table("conversations")  # tenant_filter:exempt:cron_cross_tenant_sla_check
                .select("id, tenant_id, customer_phone, human_takeover_at, last_interaction_at")
                .eq("status", "human_takeover")
                .or_(
                    f"human_takeover_at.lt.{sla_cutoff},"
                    f"and(human_takeover_at.is.null,last_interaction_at.lt.{sla_cutoff})"
                )
                .limit(50)
                .execute()
            )
            convs = convs_res.data or []
        except Exception as exc:
            logger.warning("[SLA] error consultando convs takeover: %s", exc)
            return

        if not convs:
            return

        logger.info("[SLA] %d conv(s) takeover potencialmente sin respuesta", len(convs))

        for conv in convs:
            conv_id = conv.get("id")
            tenant_id = conv.get("tenant_id")
            customer_phone = conv.get("customer_phone") or "?"
            if not (conv_id and tenant_id):
                continue

            try:
                # 1. Encontrar escalated_at — último escalation_audit.
                # tenant_filter:exempt:cron_cross_tenant_sla_check
                escalation_audit = (
                    self.supabase.table("messages")  # tenant_filter:exempt:cron_cross_tenant_sla_check
                    .select("created_at")
                    .eq("conversation_id", conv_id)
                    .eq("content_type", "escalation_audit")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if not escalation_audit.data:
                    # Sin audit row, no podemos calcular SLA. Skip.
                    continue
                escalated_at_iso = escalation_audit.data[0]["created_at"]

                # 2. ¿Ya alertamos previamente esta breach?
                # tenant_filter:exempt:cron_cross_tenant_sla_check
                breach_audit = (
                    self.supabase.table("messages")  # tenant_filter:exempt:cron_cross_tenant_sla_check
                    .select("id")
                    .eq("conversation_id", conv_id)
                    .eq("content_type", "sla_breach_audit")
                    .gt("created_at", escalated_at_iso)
                    .limit(1)
                    .execute()
                )
                if breach_audit.data:
                    # Ya notificada — skip idempotencia.
                    continue

                # 3. ¿Hubo respuesta del OPERADOR post-escalación? F6: solo cuentan outbound marcados
                # sent_by='operator' (los que envía send_agent_message/image desde el Inbox), NO cualquier
                # outbound text. Antes contaba cualquiera → la DESPEDIDA que el LLM genera al escalar (outbound
                # text, sin marca) se contaba como "operador respondió" → el SLA NUNCA disparaba (falso-negativo).
                # tenant_filter:exempt:cron_cross_tenant_sla_check
                human_response = (
                    self.supabase.table("messages")  # tenant_filter:exempt:cron_cross_tenant_sla_check
                    .select("id")
                    .eq("conversation_id", conv_id)
                    .eq("direction", "outbound")
                    .eq("payload->>sent_by", "operator")
                    .gt("created_at", escalated_at_iso)
                    .limit(1)
                    .execute()
                )
                if human_response.data:
                    # Operador respondió — no es breach.
                    continue

                # 4. SLA breach. Enviar notif Telegram + audit row.
                logger.warning(
                    "[SLA] BREACH conv=%s tenant=%s — sin respuesta humana "
                    "hace ≥%dh desde escalación %s",
                    conv_id[:8], tenant_id[:8], HUMAN_TAKEOVER_SLA_HOURS,
                    escalated_at_iso,
                )

                notify_ok = False
                try:
                    from telegram_notifications import notify_escalation_async
                    await notify_escalation_async(
                        self.supabase,
                        tenant_id=tenant_id,
                        conversation_id=conv_id,
                        reason=(
                            f"⏰ SLA BREACH — cliente {customer_phone} sin "
                            f"respuesta humana hace ≥{HUMAN_TAKEOVER_SLA_HOURS}h. "
                            f"Conversación escalada el {escalated_at_iso}. "
                            f"Por favor responder lo antes posible."
                        ),
                        severity="critical",
                    )
                    notify_ok = True
                except Exception as exc:
                    logger.warning(
                        "[SLA] notify Telegram falló conv=%s: %s — NO se estampa "
                        "breach audit, se reintenta el próximo ciclo", conv_id, exc,
                    )

                # Gap F7-15 — el breach audit ES la marca de idempotencia (paso 2).
                # Si la notif falló (transitorio), NO lo insertamos → el próximo
                # ciclo reintenta la alerta. Antes se insertaba SIEMPRE, así que un
                # fallo transitorio de Telegram descartaba la alerta para siempre.
                if not notify_ok:
                    self._metrics["sla_notify_failed"] += 1
                    continue

                # 5. Audit row para idempotencia (no re-notificar).
                try:
                    self.supabase.table("messages").insert({
                        "conversation_id": conv_id,
                        "tenant_id": tenant_id,
                        "direction": "outbound",
                        "content_type": "sla_breach_audit",
                        "content": "",
                        "payload": {
                            "escalated_at": escalated_at_iso,
                            "sla_threshold_hours": HUMAN_TAKEOVER_SLA_HOURS,
                            "notified_at": datetime.now(timezone.utc).isoformat(),
                            "source": "worker_sla_check",
                        },
                        "processed": True,
                        "processing_status": "processed",
                    }).execute()
                except Exception as exc:
                    logger.warning("[SLA] audit insert falló conv=%s: %s", conv_id, exc)

            except Exception as exc:
                logger.error("[SLA] error procesando conv=%s: %s", conv_id, exc)
                continue

    async def _reclaim_stale_inbound(
        self, *, threshold_minutes: int, statuses: list[str], label: str,
    ) -> None:
        """Core reusable: re-encola mensajes inbound atascados que llevan más de
        `threshold_minutes` sin avanzar (created_at < cutoff). Reestablece a 'pending'
        salvo que superen MAX_PROCESSING_ATTEMPTS (→ 'failed'). CAS-guard en el reset.

        Umbral GENEROSO por diseño: muy por encima del tiempo real de procesamiento
        (~9-60s) para NUNCA reclamar un mensaje legítimamente en curso (evita doble
        procesamiento). Sin columna processing_started_at, `created_at` es el proxy: en
        operación normal el mensaje se reclama segundos tras crearse, así que created_at
        ≈ tiempo de claim. (`processing_started_at` sería el fix perfecto bajo carga
        pesada — follow-up con migración.)
        """
        stale_cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)
        ).isoformat()
        try:
            stale_res = (
                self.supabase.table("messages")  # tenant_filter:exempt:cron_cross_tenant_startup_recovery
                # A11 audit 2026-06-25 (P0 BUG_REAL Clase A): incluir tenant_id —
                # las updates posteriores hacen .eq("tenant_id", msg["tenant_id"])
                # y sin él en el SELECT lanzaban KeyError → recuperación rota.
                .select("id, processing_attempts, tenant_id")
                .eq("direction", "inbound")
                .in_("processing_status", statuses)
                .lt("created_at", stale_cutoff)
                .limit(100)
                .execute()
            )
            stale = stale_res.data or []
            if not stale:
                if label == "STARTUP":
                    logger.info("[STARTUP] Sin mensajes atascados — OK")
                return

            recovered = 0
            abandoned = 0
            for msg in stale:
                attempts = int(msg.get("processing_attempts") or 0)
                if attempts >= MAX_PROCESSING_ATTEMPTS:
                    self.supabase.table("messages").update({
                        "processing_status": "failed",
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": f"abandoned_{label.lower()}_max_attempts",
                    }).eq("id", msg["id"]).eq("tenant_id", msg["tenant_id"]).execute()
                    abandoned += 1
                else:
                    # CAS-guard: solo re-encolar si SIGUE en uno de los statuses
                    # objetivo (no pisar un mensaje que recién completó).
                    res = self.supabase.table("messages").update({
                        "processing_status": "pending",
                    }).eq("id", msg["id"]).eq("tenant_id", msg["tenant_id"]).in_(
                        "processing_status", statuses).execute()
                    if res.data:
                        recovered += 1

            logger.warning(
                "[%s] Sweep mensajes atascados (>%dmin, %s): %s re-encolados, %s abandonados",
                label, threshold_minutes, statuses, recovered, abandoned,
            )
        except Exception as exc:
            logger.error("[%s] Error en sweep de mensajes atascados: %s", label, exc)

    async def _sweep_stale_messages_on_startup(self) -> None:
        """Al iniciar: re-encola mensajes 'pending'/'processing' atascados >5min.
        Escenario típico: el worker anterior se reinició dejando mensajes huérfanos."""
        await self._reclaim_stale_inbound(
            threshold_minutes=5, statuses=["pending", "processing"], label="STARTUP",
        )

    async def _sweep_stale_processing_if_due(self) -> None:
        """Capa A worker-robustez — recuperación PERIÓDICA (no solo en startup) de
        mensajes huérfanos en 'processing'. Garantiza que una carrera de coalescing/claim
        nunca deje a un cliente sin respuesta, haya restart o no. Corre cada
        STALE_PROCESSING_SWEEP_INTERVAL_SECONDS; reclama 'processing' >umbral."""
        now = time.time()
        if self._last_stale_sweep_at and (
            now - self._last_stale_sweep_at
        ) < max(30, STALE_PROCESSING_SWEEP_INTERVAL_SECONDS):
            return
        self._last_stale_sweep_at = now
        await self._reclaim_stale_inbound(
            threshold_minutes=STALE_PROCESSING_RECLAIM_MINUTES,
            statuses=["processing"], label="PERIODIC",
        )

    async def _send_payment_reminders_if_due(self) -> None:
        """Rev. 103 F1 — Recordatorio de pago dentro de la CSW (Meta 24h).

        Para cada orden en `pending_payment` con created_at en el rango
        [delay, delay+window) y sin recordatorio previo, verifica que la
        ventana de servicio al cliente (CSW) de Meta siga abierta — i.e.
        el último mensaje INBOUND del cliente fue hace menos de
        META_CSW_HOURS. Si está abierta, envía free-form (gratis); si está
        cerrada, marca el reminder como salteado y deja la orden seguir su
        flujo normal de expiry. F2 (templates HSM) cubrirá el out-of-CSW.

        Idempotente: usa orders.payment_reminder_sent_at como flag.
        """
        if not self._reminder_enabled:
            return

        now = time.time()
        if now - self._last_reminder_at < max(30, PAYMENT_REMINDER_INTERVAL_SECONDS):
            return
        self._last_reminder_at = now

        now_dt = datetime.now(timezone.utc)
        # Rango: orders creadas entre (now - delay - window) y (now - delay).
        # Ej. delay=25, window=5 → orders creadas hace 25-30 min.
        upper_cutoff = (now_dt - timedelta(minutes=PAYMENT_REMINDER_DELAY_MINUTES)).isoformat()
        lower_cutoff = (
            now_dt - timedelta(minutes=PAYMENT_REMINDER_DELAY_MINUTES + PAYMENT_REMINDER_WINDOW_MINUTES)
        ).isoformat()

        try:
            stale_res = (
                self.supabase.table("orders")  # tenant_filter:exempt:cron_cross_tenant_payment_reminder
                .select("id, tenant_id, conversation_id, created_at, "
                        "conversations(customer_phone, status)")
                .eq("status", "pending_payment")
                .is_("payment_reminder_sent_at", "null")
                .lt("created_at", upper_cutoff)
                .gte("created_at", lower_cutoff)
                .limit(50)
                .execute()
            )
            stale = stale_res.data or []
        except Exception as exc:
            logger.error("[REMINDER] Error consultando orders pendientes: %s", exc)
            return
        if not stale:
            return

        csw_cutoff = (now_dt - timedelta(hours=META_CSW_HOURS)).isoformat()

        for order in stale:
            # BLOQUE J (robustez): latir por ítem. El loop hace hasta 50 iteraciones
            # con I/O de red (query last-inbound + HSM send timeout 10s c/u); sin este
            # heartbeat un ciclo lento superaba HEALTH_HEARTBEAT_STALE_SECONDS=120 →
            # /health 503 → Render reiniciaba a mitad del batch. Mismo patrón que el
            # poll de voids (_poll_wompi_pending_voids_if_due).
            self.last_heartbeat_ts = time.time()
            order_id = order.get("id")
            tenant_id = order.get("tenant_id")
            conversation_id = order.get("conversation_id")
            conv = order.get("conversations") or {}
            customer_phone = conv.get("customer_phone") if isinstance(conv, dict) else None

            if not (order_id and tenant_id and conversation_id and customer_phone):
                logger.warning("[REMINDER] order=%s con datos incompletos — skip",
                               (order_id or "?")[:8])
                continue

            # Gap F7-7 — NO inyectar recordatorios del bot en conversaciones que
            # un operador está atendiendo (human_takeover). Si el operador tomó la
            # conversación, él gestiona el cobro; el bot no debe meterse. No se
            # quema la idempotencia: si el takeover termina dentro de la ventana
            # (~5 min) el recordatorio podría salir en el próximo ciclo, y si no,
            # la orden sale de la ventana de forma natural.
            conv_status = (conv.get("status") if isinstance(conv, dict) else None) or ""
            if conv_status == "human_takeover":
                self._metrics["payment_reminders_skipped_human_takeover"] += 1
                logger.info(
                    "[REMINDER] order=%s conv en human_takeover — skip (operador atiende)",
                    order_id[:8],
                )
                continue

            try:
                last_in_res = (
                    self.supabase.table("messages")  # tenant_filter:exempt:cron_cross_tenant_payment_reminder
                    .select("created_at")
                    .eq("conversation_id", conversation_id)
                    .eq("direction", "inbound")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                last_inbound_rows = last_in_res.data or []
            except Exception as exc:
                logger.warning("[REMINDER] No pude verificar CSW conv=%s: %s",
                               conversation_id[:8], exc)
                continue

            csw_open = bool(
                last_inbound_rows
                and (last_inbound_rows[0].get("created_at") or "") >= csw_cutoff
            )
            if not csw_open:
                # Fuera de CSW: free-form bloqueado por Meta. Intentar HSM
                # template payment_reminder_v1 (Sem 7 F2 item 6.b).
                # Si template no APPROVED → marcar skipped + métrica.
                # Si HSM envía OK → marcar sent_via_hsm + métrica.
                hsm_handled = await self._try_send_payment_reminder_hsm(
                    order_id=order_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    customer_phone=customer_phone,
                    now_dt=now_dt,
                )
                # Gap F7-28 — la métrica skipped_csw_closed SOLO cuenta cuando el
                # HSM NO envió. Antes se incrementaba ANTES del intento HSM → si el
                # HSM salía, la misma orden contaba como 'skipped_csw_closed' Y
                # 'sent_via_hsm' (doble conteo que mentía en /status).
                if not hsm_handled:
                    self._metrics["payment_reminders_skipped_csw_closed"] += 1
                    # HSM no aplicó (template no aprobado o falló). Igualmente
                    # marcamos idempotencia para no reintentar — el cron solo
                    # debería disparar 1 vez por orden.
                    try:
                        self.supabase.table("orders").update({
                            "payment_reminder_sent_at": now_dt.isoformat(),
                        }).eq("id", order_id).eq("tenant_id", tenant_id).is_(
                            "payment_reminder_sent_at", "null",
                        ).execute()
                    except Exception:
                        pass
                    logger.info(
                        "[REMINDER] CSW cerrada — order=%s skip (HSM no disponible)",
                        order_id[:8],
                    )
                continue

            short_id = str(order_id)[:8].upper()
            # Gap F7-23 — minutos restantes derivados de la config real (TTL de
            # cancelación − delay del recordatorio) en vez de "5 min" hardcodeado.
            # Si el founder ajusta PENDING_PAYMENT_TTL_MINUTES / DELAY, el copy no
            # miente. Default: 35 − 25 = 10 min antes de que el cron libere la orden.
            remaining_min = max(
                1, PENDING_PAYMENT_TTL_MINUTES - PAYMENT_REMINDER_DELAY_MINUTES
            )
            text = (
                f"Te quedan unos *{remaining_min} min* para usar el link de pago "
                f"de tu pedido *#{short_id}*.\n\n"
                f"Si necesitas más tiempo o ayuda, escríbeme y lo resolvemos."
            )
            try:
                meta_message_id = await send_whatsapp_message(
                    tenant_id=tenant_id,
                    supabase=self.supabase,
                    to_phone=customer_phone,
                    text=text,
                )
            except Exception as exc:
                logger.error("[REMINDER] Error enviando WA order=%s: %s",
                             order_id[:8], exc)
                continue

            if not meta_message_id:
                logger.warning("[REMINDER] send_whatsapp_message no devolvió id — order=%s",
                               order_id[:8])
                continue

            # Persistir outbound en messages para que aparezca en Inbox.
            try:
                self.supabase.table("messages").insert({
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "direction": "outbound",
                    "content_type": "text",
                    "content": text,
                    "meta_message_id": meta_message_id,
                    "processing_status": "processed",
                    "processed": True,
                    "processed_at": now_dt.isoformat(),
                }).execute()
            except Exception as exc:
                logger.warning("[REMINDER] No pude persistir outbound order=%s: %s",
                               order_id[:8], exc)

            # Marcar idempotencia.
            try:
                upd = (
                    self.supabase.table("orders")
                    .update({"payment_reminder_sent_at": now_dt.isoformat()})
                    .eq("id", order_id)
                    .eq("tenant_id", tenant_id)
                    .is_("payment_reminder_sent_at", "null")
                    .execute()
                )
                if upd.data:
                    self._metrics["payment_reminders_sent"] += 1
                    logger.info(
                        "[REMINDER] order=%s recordatorio enviado a %s (CSW abierta)",
                        order_id[:8], customer_phone,
                    )
            except Exception as exc:
                logger.warning("[REMINDER] No pude marcar idempotencia order=%s: %s",
                               order_id[:8], exc)

    # ── Sem 7 F2 item 6.b — HSM payment_reminder fuera CSW ──────────────────

    async def _try_send_payment_reminder_hsm(
        self,
        *,
        order_id: str,
        tenant_id: str,
        conversation_id: str,
        customer_phone: str,
        now_dt: datetime,
    ) -> bool:
        """Intenta enviar HSM template payment_reminder_v1 cuando CSW está
        cerrada. Retorna True si HSM envió OK (marcado idempotente + persistido
        outbound). False si template no APPROVED, falló o data incompleta —
        caller marca skipped.

        Costo: ~$0.004 USD/msg (UTILITY tier fuera CSW). Compensa con creces
        si recupera al menos 1 de cada 10 pedidos abandonados (ROI ~200x).
        """
        # Fetch datos completos de la orden para hidratar template
        try:
            order_res = (
                self.supabase.table("orders")
                .select("id, total_amount, contact_id")
                .eq("id", order_id)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            order_rows = order_res.data or []
        except Exception as exc:
            logger.error("[REMINDER_HSM] error fetch order=%s: %s",
                         order_id[:8], exc)
            return False
        if not order_rows:
            return False
        order = order_rows[0]
        total_amount = float(order.get("total_amount") or 0)

        # Resolver nombre cliente via contacts si disponible.
        # Gap F7-13 — además respetar el soft opt-out (STOP). lib/whatsapp_optout
        # define que consent_revoked_at filtra TODO HSM proactivo outbound (sin
        # distinguir categoría: incluye este UTILITY). Un cliente que dijo BAJA no
        # debe recibir el template fuera de CSW. El path cart_abandoned ya lo
        # respetaba; el de payment_reminder no → se cierra la asimetría.
        customer_name = "cliente"
        contact_id = order.get("contact_id")
        if contact_id:
            try:
                contact_res = (
                    self.supabase.table("contacts")
                    # F44: la columna real es `name` (first_name/full_name no existen)
                    .select("name, consent_revoked_at")
                    .eq("id", contact_id)
                    .eq("tenant_id", tenant_id)
                    .limit(1)
                    .execute()
                )
                contact_rows = contact_res.data or []
                if contact_rows:
                    if contact_rows[0].get("consent_revoked_at"):
                        logger.info(
                            "[REMINDER_HSM] order=%s cliente con soft opt-out "
                            "(consent_revoked_at) — no se envía HSM proactivo "
                            "(Ley 1581 Art.9 + Meta Policy)",
                            order_id[:8],
                        )
                        return False
                    full = (contact_rows[0].get("name") or "").strip()
                    customer_name = full.split(" ")[0] if full else "cliente"
            except Exception:
                pass

        # Resolver checkout_url del payment más reciente
        checkout_url = ""
        try:
            pay_res = (
                self.supabase.table("payments")
                .select("checkout_url, created_at")
                .eq("order_id", order_id)
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            pay_rows = pay_res.data or []
            if pay_rows:
                checkout_url = (pay_rows[0].get("checkout_url") or "").strip()
        except Exception:
            pass
        if not checkout_url:
            logger.warning(
                "[REMINDER_HSM] order=%s sin checkout_url — no se puede armar template",
                order_id[:8],
            )
            return False

        # Format total: $87.500 (entero, punto cada 3).
        # Sem 7 F2 cierre 2026-05-20 — P5: sin sufijo " COP" (UX limpio).
        try:
            pesos = int(total_amount)  # total_amount ya está en pesos en orders schema
            total_str = f"${pesos:,}".replace(",", ".")
        except Exception:
            total_str = "$0"

        order_number = str(order_id)[:8].upper()

        body_params = [customer_name, order_number, total_str, checkout_url]

        msg_id, err = await send_whatsapp_template(
            tenant_id=tenant_id,
            supabase=self.supabase,
            to_phone=customer_phone,
            template_name="payment_reminder_v1",
            language="es_CO",
            body_params=body_params,
        )

        if err in (TEMPLATE_ERR_TEMPLATE_NOT_APPROVED, TEMPLATE_ERR_TEMPLATE_NOT_FOUND):
            self._metrics["payment_reminders_hsm_not_approved"] += 1
            logger.info(
                "[REMINDER_HSM] order=%s template payment_reminder_v1 no disponible "
                "(err=%s). Submitear via scripts/admin/submit_template_to_meta.py",
                order_id[:8], err,
            )
            return False

        if err:
            self._metrics["payment_reminders_hsm_failed"] += 1
            logger.warning(
                "[REMINDER_HSM] order=%s falló HSM send: %s",
                order_id[:8], err,
            )
            return False

        # OK: marcar idempotencia + persistir outbound en messages
        try:
            self.supabase.table("messages").insert({
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "direction": "outbound",
                "content_type": "template",
                "content": (
                    f"[TEMPLATE payment_reminder_v1] {customer_name}, recordatorio "
                    f"pago orden {order_number} por {total_str}"
                ),
                "meta_message_id": msg_id,
                "processing_status": "processed",
                "processed": True,
                "processed_at": now_dt.isoformat(),
            }).execute()
        except Exception as exc:
            logger.warning("[REMINDER_HSM] no pude persistir outbound order=%s: %s",
                           order_id[:8], exc)

        try:
            self.supabase.table("orders").update({
                "payment_reminder_sent_at": now_dt.isoformat(),
            }).eq("id", order_id).eq("tenant_id", tenant_id).is_(
                "payment_reminder_sent_at", "null",
            ).execute()
        except Exception:
            pass

        self._metrics["payment_reminders_sent_via_hsm"] += 1
        logger.info(
            "[REMINDER_HSM] ✓ order=%s template payment_reminder_v1 enviado "
            "to=%s meta_msg_id=%s",
            order_id[:8], customer_phone, msg_id,
        )
        return True

    async def _send_cart_abandoned_reminders_if_due(self) -> None:
        """Sem 7 F2 item 6.b — Cron HSM cart_abandoned_24h_v1 MARKETING.

        Detecta carritos sin actividad >CART_ABANDONED_THRESHOLD_HOURS (24h
        default) y <CART_ABANDONED_MAX_AGE_HOURS (72h default) cuyo cliente:
          - Tiene customer_phone
          - Tiene consent_given=TRUE en contacts (Habeas Data Ley 1581)
          - NO recibió abandoned_reminder previo (idempotencia)
        y dispara template MARKETING cart_abandoned_24h_v1.

        Costo: ~$0.025 USD/msg. Compensa con recovery de carritos
        abandonados que de otra forma se perderían 100%.

        NO cubre carritos dentro CSW <24h — el bot conversacional + F1
        recordatorios free-form ya los cubren gratis. Este cron es
        complementario para los que se fueron y no volvieron.
        """
        if not self._cart_abandoned_enabled:
            return
        now = time.time()
        if now - self._last_cart_abandoned_at < max(
            60, CART_ABANDONED_REMINDER_INTERVAL_SECONDS,
        ):
            return
        self._last_cart_abandoned_at = now

        now_dt = datetime.now(timezone.utc)
        # Gap F7-25 — quiet hours Colombia para el HSM MARKETING. No se quema
        # idempotencia: se difiere el ciclo; los carritos siguen elegibles y el
        # próximo ciclo (ya fuera de la franja) los procesa. Solo MARKETING.
        if self._is_quiet_hour_colombia(now_dt):
            self._metrics["cart_abandoned_skipped_quiet_hours"] += 1
            logger.debug(
                "[CART_ABANDONED] quiet hours Colombia (%02d:00–%02d:00) — difiero ciclo",
                CART_ABANDONED_QUIET_START_HOUR % 24, CART_ABANDONED_QUIET_END_HOUR % 24,
            )
            return
        upper_cutoff = (now_dt - timedelta(hours=CART_ABANDONED_THRESHOLD_HOURS)).isoformat()
        lower_cutoff = (now_dt - timedelta(hours=CART_ABANDONED_MAX_AGE_HOURS)).isoformat()

        # Buscar carritos en open/abandoned con updated_at en rango [24h, 72h]
        # sin recordatorio enviado.
        try:
            carts_res = (
                self.supabase.table("conversation_carts")  # tenant_filter:exempt:cron_cross_tenant_cart_abandoned_cleanup
                .select(
                    "id, tenant_id, conversation_id, contact_id, status, "
                    "updated_at, conversations(customer_phone)"
                )
                .in_("status", ["open", "abandoned"])
                .is_("abandoned_reminder_sent_at", "null")
                .lt("updated_at", upper_cutoff)
                .gte("updated_at", lower_cutoff)
                .limit(50)
                .execute()
            )
            carts = carts_res.data or []
        except Exception as exc:
            logger.error("[CART_ABANDONED] error consultando carts: %s", exc)
            return

        if not carts:
            return

        # Gap F7-26 — cap per-tenant/ciclo: el limit(50) es global; sin esto un
        # tenant con 50 carritos dispararía 50 HSM de golpe y podría chocar con
        # META_RATE_LIMIT en su WABA. Los que no entran este ciclo siguen
        # elegibles (idempotencia intacta) y salen en ciclos siguientes.
        carts = self._cap_per_tenant(carts, CART_ABANDONED_MAX_PER_TENANT_PER_CYCLE)

        for cart in carts:
            # BLOQUE J (robustez): latir por ítem — mismo motivo que el loop de
            # payment reminders (I/O de red por carrito, hasta 50, HSM timeout 10s).
            self.last_heartbeat_ts = time.time()
            cart_id = cart.get("id")
            tenant_id = cart.get("tenant_id")
            conversation_id = cart.get("conversation_id")
            contact_id = cart.get("contact_id")
            conv = cart.get("conversations") or {}
            customer_phone = conv.get("customer_phone") if isinstance(conv, dict) else None

            if not (cart_id and tenant_id and conversation_id and customer_phone):
                continue

            # Habeas Data Ley 1581: necesita consent_given=TRUE explícito
            # para enviar MARKETING. Sin consent → skip.
            # A11 fix: además respetar consent_revoked_at — un soft opt-out
            # (STOP) deja consent_given=TRUE pero setea consent_revoked_at;
            # enviar marketing HSM a quien dijo STOP viola Ley 1581 Art.9 +
            # Meta Policy. El gate antes solo miraba consent_given.
            consent_ok = False
            lookup_failed = False   # F44: distinguir "lookup falló" de "consent denegado"
            customer_name = "cliente"
            if contact_id:
                try:
                    contact_res = (
                        self.supabase.table("contacts")
                        # F44: la columna real es `name` (first_name/full_name NO existen → APIError
                        # tragado → consent_ok siempre False → skipeaba TODO quemando la idempotencia).
                        .select("consent_given, consent_revoked_at, name")
                        .eq("id", contact_id)
                        .eq("tenant_id", tenant_id)
                        .limit(1)
                        .execute()
                    )
                    contact_rows = contact_res.data or []
                    if contact_rows:
                        consent_ok = (
                            bool(contact_rows[0].get("consent_given"))
                            and not contact_rows[0].get("consent_revoked_at")
                        )
                        full = (contact_rows[0].get("name") or "").strip()
                        customer_name = full.split(" ")[0] if full else "cliente"
                except Exception as exc:
                    lookup_failed = True
                    logger.warning(
                        "[CART_ABANDONED] lookup contacto falló cart=%s: %s — reintentar luego",
                        str(cart_id)[:8], exc,
                    )

            if lookup_failed:
                # F44: NO quemar la idempotencia si el lookup falló (transitorio) — reintentar próximo ciclo.
                continue

            if not consent_ok:
                self._metrics["cart_abandoned_reminders_skipped_no_consent"] += 1
                # Marcar idempotencia igualmente — no reintentar
                try:
                    self.supabase.table("conversation_carts").update({
                        "abandoned_reminder_sent_at": now_dt.isoformat(),
                    }).eq("id", cart_id).eq("tenant_id", tenant_id).is_(
                        "abandoned_reminder_sent_at", "null",
                    ).execute()
                except Exception:
                    pass
                logger.info(
                    "[CART_ABANDONED] cart=%s skipped (sin consent_given marketing — "
                    "Habeas Data Ley 1581)",
                    str(cart_id)[:8],
                )
                continue

            # Items del carrito — resumen corto
            cart_summary = "tu carrito"
            try:
                items_res = (
                    self.supabase.table("conversation_cart_items")
                    # F44: conversation_cart_items NO tiene product_title → embed a products(title).
                    .select("quantity, products(title)")
                    .eq("cart_id", cart_id)
                    .eq("tenant_id", tenant_id)
                    .limit(3)
                    .execute()
                )
                items = items_res.data or []
                if items:
                    parts = []
                    for it in items:
                        title = ((it.get("products") or {}).get("title") or "").strip()
                        qty = int(it.get("quantity") or 1)
                        if title:
                            parts.append(f"{title} x{qty}" if qty > 1 else title)
                    if parts:
                        cart_summary = ", ".join(parts[:3])
                        if len(items) > 3:
                            cart_summary += " y más"
            except Exception:
                pass

            body_params = [customer_name, cart_summary, CART_ABANDONED_DISCOUNT_LABEL]

            msg_id, err = await send_whatsapp_template(
                tenant_id=tenant_id,
                supabase=self.supabase,
                to_phone=customer_phone,
                template_name="cart_abandoned_24h_v1",
                language="es_CO",
                body_params=body_params,
            )

            if err in (TEMPLATE_ERR_TEMPLATE_NOT_APPROVED, TEMPLATE_ERR_TEMPLATE_NOT_FOUND):
                self._metrics["cart_abandoned_reminders_hsm_not_approved"] += 1
                # Idempotencia: si template no está aprobado, no reintentar
                # cada 5min. Mark + skip.
                try:
                    self.supabase.table("conversation_carts").update({
                        "abandoned_reminder_sent_at": now_dt.isoformat(),
                    }).eq("id", cart_id).eq("tenant_id", tenant_id).is_(
                        "abandoned_reminder_sent_at", "null",
                    ).execute()
                except Exception:
                    pass
                logger.info(
                    "[CART_ABANDONED] cart=%s template no disponible (err=%s)",
                    str(cart_id)[:8], err,
                )
                continue

            if err:
                self._metrics["cart_abandoned_reminders_hsm_failed"] += 1
                logger.warning(
                    "[CART_ABANDONED] cart=%s HSM falló: %s",
                    str(cart_id)[:8], err,
                )
                continue

            # OK: persistir outbound + marcar idempotencia
            try:
                self.supabase.table("messages").insert({
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "direction": "outbound",
                    "content_type": "template",
                    "content": (
                        f"[TEMPLATE cart_abandoned_24h_v1] {customer_name}, "
                        f"recordatorio carrito: {cart_summary}"
                    ),
                    "meta_message_id": msg_id,
                    "processing_status": "processed",
                    "processed": True,
                    "processed_at": now_dt.isoformat(),
                }).execute()
            except Exception as exc:
                logger.warning("[CART_ABANDONED] no pude persistir outbound cart=%s: %s",
                               str(cart_id)[:8], exc)

            try:
                self.supabase.table("conversation_carts").update({
                    "abandoned_reminder_sent_at": now_dt.isoformat(),
                }).eq("id", cart_id).eq("tenant_id", tenant_id).is_(
                    "abandoned_reminder_sent_at", "null",
                ).execute()
            except Exception:
                pass

            self._metrics["cart_abandoned_reminders_sent"] += 1
            logger.info(
                "[CART_ABANDONED] ✓ cart=%s template cart_abandoned_24h_v1 enviado "
                "to=%s meta_msg_id=%s",
                str(cart_id)[:8], customer_phone, msg_id,
            )

    async def _poll_wompi_pending_voids_if_due(self) -> None:
        """Rev. 109 P1 #1 — Polling backup Wompi VOIDED (Plan MA-9).

        Detecta payments cuya orden está cancelled con refund_method=
        wompi_void_auto pero el local wompi_status sigue APPROVED (porque
        Wompi nunca envió el webhook transaction.updated). Consulta GET
        /transactions/{id} a Wompi; si retorna VOIDED, actualiza local
        + dispara notify_client_refund_completed.

        Ventana lookback configurable (default 48h). Frecuencia
        configurable (default 30min).
        """
        if not self._wompi_void_poll_enabled:
            return
        now = time.time()
        interval = max(60, WOMPI_VOID_POLL_INTERVAL_SECONDS)
        if now - self._last_wompi_void_poll_at < interval:
            return
        self._last_wompi_void_poll_at = now

        try:
            # Buscar payments approved cuya orden está cancelled con
            # refund_method=wompi_void_auto en últimas LOOKBACK_HOURS.
            cutoff_iso = (
                datetime.now(timezone.utc)
                - timedelta(hours=WOMPI_VOID_POLL_LOOKBACK_HOURS)
            ).isoformat()
            # Schema PostgREST: 2 FKs entre orders y order_cancellations.
            # Especificamos orders_cancellation_id_fkey (la 1:1 vía link).
            res = (
                self.supabase.table("payments")  # tenant_filter:exempt:cron_cross_tenant_wompi_void_polling
                .select(
                    "id, tenant_id, order_id, wompi_txn_id, amount_in_cents, "
                    "wompi_status, updated_at, orders(status, cancellation_id, "
                    "order_cancellations!orders_cancellation_id_fkey"
                    "(refund_method, refund_status))",
                )
                .eq("wompi_status", "APPROVED")
                .gte("updated_at", cutoff_iso)
                .limit(50)
                .execute()
            )
        except Exception as exc:
            logger.warning("[WOMPI_POLL] query candidates falló: %s", exc)
            return

        candidates = res.data or []
        if not candidates:
            return

        # Filter only those linked to cancelled+wompi_void_auto.
        eligible = []
        for p in candidates:
            order = p.get("orders") or {}
            if (order.get("status") or "").lower() != "cancelled":
                continue
            cancellations = order.get("order_cancellations") or []
            if isinstance(cancellations, list):
                # PostgREST embed retorna lista para 1:1 via FK.
                cr = cancellations[0] if cancellations else {}
            else:
                cr = cancellations
            if (cr or {}).get("refund_method") != "wompi_void_auto":
                continue
            eligible.append(p)

        if not eligible:
            return

        logger.info(
            "[WOMPI_POLL] %d candidatos void pendientes (lookback=%dh)",
            len(eligible), WOMPI_VOID_POLL_LOOKBACK_HOURS,
        )

        # BLOQUE H (review Fable MEDIUM): la ventana lookback (48h por
        # payments.updated_at) acota silenciosamente el reintento F7-14 — un
        # fallo de notificación persistente (pgmq caído, email inválido) haría
        # que el candidato salga de la ventana y wompi_status quede APPROVED
        # para siempre, sin señal. Alertar cuando un candidato elegible se
        # acerca al borde (>50% de la ventana) para que NO se pierda en silencio.
        _stale_cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=WOMPI_VOID_POLL_LOOKBACK_HOURS / 2)
        )
        for _p in eligible:
            _upd = _p.get("updated_at")
            if not _upd:
                continue
            try:
                _upd_dt = datetime.fromisoformat(str(_upd).replace("Z", "+00:00"))
            except Exception:
                continue
            if _upd_dt < _stale_cutoff:
                logger.error(
                    "[WOMPI_POLL] STUCK refund void order=%s payment=%s "
                    "sin notificar hace >%.0fh (se acerca al age-out de %dh) — "
                    "requiere intervención",
                    str(_p.get("order_id"))[:8], str(_p.get("id"))[:8],
                    WOMPI_VOID_POLL_LOOKBACK_HOURS / 2,
                    WOMPI_VOID_POLL_LOOKBACK_HOURS,
                )

        # Para cada uno: GET txn a Wompi. Si VOIDED, notificar + sincronizar.
        for p in eligible:
            # Gap F7-18 — latir por candidato. El GET a Wompi es I/O de red (hasta
            # 10s × 50 candidatos); sin este heartbeat un ciclo lento superaba
            # HEALTH_HEARTBEAT_STALE_SECONDS → /health 503 → Render reiniciaba a
            # mitad del poll. El worker está VIVO aunque Wompi tarde.
            self.last_heartbeat_ts = time.time()
            txn_id = p.get("wompi_txn_id")
            tenant_id = p.get("tenant_id")
            order_id = p.get("order_id")
            amount = int(p.get("amount_in_cents") or 0)
            if not (txn_id and tenant_id and order_id):
                continue
            try:
                from integrations.wompi_client import (
                    get_tenant_wompi_creds, wompi_base_url,
                )
                pk, _, env = get_tenant_wompi_creds(self.supabase, tenant_id)
                if not pk:
                    continue
                import httpx
                url = f"{wompi_base_url(env or 'sandbox')}/transactions/{txn_id}"
                # Gap F7-18 — AsyncClient + await: NO bloquea el event loop del
                # worker (antes httpx.Client síncrono congelaba TODO el ciclo).
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(
                        url, headers={"Authorization": f"Bearer {pk}"},
                    )
                if r.status_code >= 400:
                    continue
                data = (r.json() or {}).get("data") or {}
                if (data.get("status") or "").upper() != "VOIDED":
                    continue

                # Gap F7-14 — NOTIFICAR ANTES de sincronizar wompi_status. Antes se
                # marcaba VOIDED primero y, si la notif fallaba, el caso salía del
                # radar (el filtro de elegibles exige wompi_status='APPROVED') → el
                # cliente jamás se enteraba del reembolso. Ahora, si la notif falla,
                # NO tocamos el estado local: el candidato sigue elegible y se
                # reintenta el próximo ciclo. Coste: en el caso raro de crash entre
                # notif y update, el próximo ciclo re-notifica (aviso duplicado,
                # nunca pérdida de dinero) — preferible a nunca informar.
                #
                # BLOQUE H P0-1 (auditoría 2026-07-12): el lazy import de
                # wompi_webhook._notify_client_refund_completed NUNCA resolvía en
                # este proceso (ModuleNotFoundError 'dependencies' local; en Render
                # services/api/ ni existe — rootDir=services/ai-orchestrator) → la
                # notif fallaba SIEMPRE y el sync a VOIDED jamás ocurría. Réplica
                # local en refund_notifications.py (devuelve bool: el canal
                # primario gobierna; email best-effort con Idempotency-Key).
                notified = await notify_client_refund_completed(
                    self.supabase, order_id=order_id, tenant_id=tenant_id,
                    amount_in_cents=amount,
                )
                if not notified:
                    self._metrics["wompi_void_notify_failed"] += 1
                    logger.warning(
                        "[WOMPI_POLL] notif refund falló order=%s — NO se marca "
                        "VOIDED (sigue elegible), reintento próximo ciclo",
                        order_id[:8],
                    )
                    continue

                # Notif OK → recién ahora sincronizar local a VOIDED.
                self.supabase.table("payments").update({
                    "wompi_status": "VOIDED",
                }).eq("wompi_txn_id", txn_id).eq("tenant_id", tenant_id).execute()
                logger.info(
                    "[WOMPI_POLL] notif OK + sync VOIDED txn=%s order=%s tenant=%s",
                    txn_id, order_id[:8], tenant_id[:8],
                )
            except Exception as exc:
                logger.warning(
                    "[WOMPI_POLL] check txn=%s falló: %s", txn_id, exc,
                )

    async def _reconcile_wompi_inbox_if_due(self) -> None:
        """W2 — Reconciliación del inbox durable Wompi (re-drive de webhooks perdidos).

        La API persiste cada webhook Wompi en `wompi_webhook_inbox` ANTES del 200 ACK.
        Si el proceso API crashea entre el ACK y el fin del procesamiento en background,
        la fila queda `processed_at IS NULL`. Aquí reclamamos atómicamente esas filas
        (más viejas que el grace, con attempts < max) y re-POSTeamos el payload crudo a
        /api/v1/webhooks/wompi → reusa el flujo verificado completo (firma + dedup +
        confirm). La idempotencia de dinero la garantiza wompi_events_seen + el guard de
        estado terminal de la orden, así que un re-drive de un evento ya procesado es
        inocuo. Tras MAX_ATTEMPTS la fila queda como dead-letter (last_error) para
        revisión manual.
        """
        now = time.time()

        # W3 GAP-PII: el cleanup corre SIEMPRE, DESACOPLADO del flag de re-drive. La
        # tabla guarda el payload CRUDO con PII del pagador (Ley 1581); si se desactivara
        # el reconcile, sin esto la PII se acumularía sin purga. Throttle 6h; retención
        # 7d procesadas / 30d dead-letter (RPC cleanup_wompi_inbox).
        if now - self._last_wompi_inbox_cleanup_at > 21600:
            self._last_wompi_inbox_cleanup_at = now
            try:
                cl = self.supabase.rpc("cleanup_wompi_inbox", {}).execute()
                _purged = cl.data if isinstance(cl.data, int) else (cl.data or 0)
                if _purged:
                    logger.info("[WOMPI_INBOX] cleanup purgó %s filas", _purged)
            except Exception as exc:
                logger.warning("[WOMPI_INBOX] cleanup falló: %s", exc)

        # Re-drive (gated por el flag): reclamar + re-POSTear filas sin procesar.
        if not self._wompi_inbox_reconcile_enabled:
            return
        interval = max(30, WOMPI_INBOX_RECONCILE_INTERVAL_SECONDS)
        if now - self._last_wompi_inbox_reconcile_at < interval:
            return
        self._last_wompi_inbox_reconcile_at = now

        try:
            res = self.supabase.rpc(
                "claim_wompi_inbox_batch",
                {
                    "p_limit": 20,
                    "p_min_age_seconds": WOMPI_INBOX_MIN_AGE_SECONDS,
                    "p_max_attempts": WOMPI_INBOX_MAX_ATTEMPTS,
                },
            ).execute()
        except Exception as exc:
            logger.warning("[WOMPI_INBOX] claim falló: %s", exc)
            return

        rows = res.data or []
        # W3 T3-01: gauge de backlog observable (filas reclamadas este ciclo).
        self._metrics["wompi_inbox_depth"] = len(rows)
        if not rows:
            return

        logger.warning(
            "[WOMPI_INBOX] %d webhook(s) sin procesar → re-drive (posible crash post-ACK)",
            len(rows),
        )

        import httpx
        url = f"{WORKER_API_URL}/api/v1/webhooks/wompi"
        for row in rows:
            checksum = (row.get("checksum") or "")[:12]
            payload = row.get("raw_payload")
            attempts = row.get("attempts") or 0
            if not isinstance(payload, dict):
                logger.warning("[WOMPI_INBOX] payload no-dict checksum=%s — skip", checksum)
                continue
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(url, json=payload)
                logger.info(
                    "[WOMPI_INBOX] re-drive checksum=%s attempt=%d → %s",
                    checksum, attempts, resp.status_code,
                )
            except Exception as exc:
                logger.warning(
                    "[WOMPI_INBOX] re-drive checksum=%s attempt=%d falló: %s",
                    checksum, attempts, exc,
                )
            if attempts >= WOMPI_INBOX_MAX_ATTEMPTS:
                self._metrics["wompi_inbox_dead_lettered"] = (
                    self._metrics.get("wompi_inbox_dead_lettered", 0) + 1
                )
                # logger.error → LoggingIntegration lo envía a Sentry (alertable);
                # el conteo alimenta health_metrics para el evaluador de SLOs (W7 T3-EVAL).
                logger.error(
                    "[WOMPI_INBOX][DEAD_LETTER] checksum=%s alcanzó %d intentos — "
                    "requiere reconciliación MANUAL con dashboard Wompi",
                    checksum, attempts,
                )

    async def _release_expired_pending_payment_orders(self) -> None:
        """
        Cancela pedidos en pending_payment que superaron el TTL sin recibir pago.
        Ejecutado cada PENDING_PAYMENT_RELEASE_INTERVAL_SECONDS (default 10 min).

        pending_payment = stock NO decrementado todavía → cancelar no requiere
        reversar stock; solo cambia el estado para liberar la "reserva conceptual"
        y limpiar el backlog de pedidos sin cobrar.

        Lifecycle de payment links (Plan A.0.1, ADR-0011):

          ─── 0 min ──── 30 min ───── 35 min ─────────────────────►
              link #1   bucket(a)→   bucket(b)→     cron cancela
              vivo      reusa link   regenera link  si NO hay payment
                                     test_G77I9U    activo
                                     test_8yaKgJ    último

        El cron NO cancela una orden si tiene un `payments.pending` reciente.
        Esa regla preserva el bucket (b) de payment_link_tool: si el cliente
        regenera el link a t=33min, el último payment es fresco y la orden
        sigue viva. Solo cuando el último payment supera el TTL (35min sin
        nuevo intent) la orden se cancela.

        Sin esta regla, había una race condition (caso runtime 2026-05-05
        order #3E10CB92): bucket (b) regeneró link a 08:35:32; cron canceló
        orden a 08:36:06 (34s después) → cliente recibió link válido pero
        contra orden cancelled → si pagaba, webhook Wompi llegaba a estado
        inconsistente.
        """
        if not self._release_enabled:
            return

        now = time.time()
        if now - self._last_release_at < max(60, PENDING_PAYMENT_RELEASE_INTERVAL_SECONDS):
            return
        self._last_release_at = now

        now_dt = datetime.now(timezone.utc)
        cutoff_iso = (
            now_dt - timedelta(minutes=PENDING_PAYMENT_TTL_MINUTES)
        ).isoformat()

        try:
            stale_res = (
                self.supabase.table("orders")  # tenant_filter:exempt:cron_cross_tenant_pending_payment_release
                .select("id, tenant_id")
                .eq("status", "pending_payment")
                .lt("created_at", cutoff_iso)
                .limit(50)
                .execute()
            )
            stale = stale_res.data or []
            if not stale:
                return

            cancelled = 0
            # C' residual money-path (2026-07-18): contamos cuántas de las canceladas
            # TENÍAN un link de pago creado. No podemos saber per-orden SI el cliente
            # pagó (Wompi no permite consultar por reference; sin el txn_id del webhook
            # no hay pull). El webhook tardío (retry Wompi ≤24h) reconcilia el caso común
            # revirtiendo el auto-cancel. El RESIDUAL (24h de fallo total del webhook) se
            # detecta por AGREGADO: un PICO de cancelled_with_link (ej. durante un outage
            # de webhook.konvi.co) señala que pudimos cancelar órdenes PAGADAS → revisar
            # el panel de Wompi. En operación normal son abandonos (señal baja).
            cancelled_with_link = 0
            for order in stale:
                # F5 reconciliación (dinero) — NUNCA cancelar una orden con un pago
                # APPROVED. Si el pago quedó registrado approved pero el confirm de la
                # orden falló (partial failure), la orden sigue en pending_payment; el
                # cron la cancelaría → se perdería el dinero del cliente. En su lugar la
                # dejamos viva (los reintentos de webhook de Wompi 30m/3h/24h la
                # confirman; si no, confirmación manual) + CRITICAL + métrica.
                try:
                    paid_res = (
                        self.supabase.table("payments")
                        .select("id, wompi_txn_id")
                        .eq("order_id", order["id"])
                        .eq("tenant_id", order["tenant_id"])
                        .eq("status", "approved")
                        .limit(1)
                        .execute()
                    )
                    if paid_res.data:
                        logger.critical(
                            "[RELEASE] order=%s tiene pago APPROVED (txn=%s) pero sigue "
                            "pending_payment — NO se cancela (confirm fallido). Reconciliar: "
                            "esperar reintento webhook Wompi o confirmar manualmente.",
                            order["id"][:8],
                            (paid_res.data[0].get("wompi_txn_id") or "?"),
                        )
                        self._metrics.setdefault("paid_orders_protected_from_cancel", 0)
                        self._metrics["paid_orders_protected_from_cancel"] += 1
                        continue
                except Exception as exc:
                    # Conservador ante error: no cancelar (mejor un zombie que cancelar
                    # una orden potencialmente pagada).
                    logger.warning(
                        "[RELEASE] lookup pago approved falló order=%s: %s — skip",
                        order["id"][:8], exc,
                    )
                    continue

                # Guard: no cancelar si hay payment pending fresco (cliente
                # regeneró link recientemente vía bucket (b)).
                try:
                    fresh_pay_res = (
                        self.supabase.table("payments")
                        .select("id, created_at")
                        .eq("order_id", order["id"])
                        .eq("tenant_id", order["tenant_id"])
                        .eq("status", "pending")
                        .gte("created_at", cutoff_iso)
                        .limit(1)
                        .execute()
                    )
                    if fresh_pay_res.data:
                        # Hay intent de pago activo (≤ TTL min) — no cancelar.
                        logger.debug(
                            "[RELEASE] order=%s skip — payment fresco %s",
                            order["id"][:8],
                            fresh_pay_res.data[0].get("created_at"),
                        )
                        continue
                except Exception as exc:
                    # Si el lookup falla, conservador: no cancelar (mejor un
                    # zombie que cancelar una orden válida con cliente
                    # esperando pago).
                    logger.warning(
                        "[RELEASE] lookup payments falló order=%s: %s — skip",
                        order["id"][:8], exc,
                    )
                    continue

                # Gap F7-10 — estampar metadata canónica de cancelación para que la
                # expiración por TTL sea distinguible en DB/reportes (antes solo
                # status='cancelled' → indistinguible de cualquier otra cancelación).
                # `cancelled_by_actor='system_auto'` es el valor de enum previsto
                # para "auto-cancel por TTL expirado" (migración 20260606000000).
                # No se crea fila en order_cancellations: para pending_payment no hay
                # pago/envío que reversar y el flujo canónico (refund/retracto/
                # triage) no aplica; ver needs_founder si se requiere el registro
                # formal para retención documental.
                res = (
                    self.supabase.table("orders")
                    .update({
                        "status": "cancelled",
                        "cancelled_at": now_dt.isoformat(),
                        "cancelled_by_actor": "system_auto",
                    })
                    .eq("id", order["id"])
                    .eq("tenant_id", order["tenant_id"])
                    .eq("status", "pending_payment")  # guard contra race condition
                    .execute()
                )
                if res.data:
                    cancelled += 1
                    # C' — ¿la orden cancelada tenía un link de pago? (residual money-path,
                    # ver comentario arriba). +1 query por cancelada (cron, no hot-path).
                    try:
                        link_res = (
                            self.supabase.table("payments")
                            .select("wompi_link_id")
                            .eq("order_id", order["id"])
                            .eq("tenant_id", order["tenant_id"])
                            .limit(5)
                            .execute()
                        )
                        if any((p or {}).get("wompi_link_id") for p in (link_res.data or [])):
                            cancelled_with_link += 1
                    except Exception:
                        pass  # el conteo es best-effort; no romper la cancelación

            if cancelled:
                self._metrics["expired_orders_cancelled"] += cancelled
                logger.info(
                    "⏱️ Pedidos pending_payment expirados cancelados: %s (TTL=%smin)",
                    cancelled,
                    PENDING_PAYMENT_TTL_MINUTES,
                )
            if cancelled_with_link:
                self._metrics.setdefault("expired_cancelled_with_payment_link", 0)
                self._metrics["expired_cancelled_with_payment_link"] += cancelled_with_link
                logger.warning(
                    "[RELEASE] %s/%s órdenes canceladas por TTL TENÍAN link de pago activo. "
                    "En operación normal son abandonos; un PICO (o durante un outage de "
                    "webhook.konvi.co) puede indicar órdenes PAGADAS canceladas → verificar el "
                    "panel de Wompi y reconciliar. Wompi no permite consultar por reference: sin "
                    "el txn_id del webhook no se automatiza la detección per-orden.",
                    cancelled_with_link, cancelled,
                )
        except Exception as exc:
            logger.error("Error liberando pending_payment expirados: %s", exc)

    def metrics_snapshot(self) -> dict:
        return dict(self._metrics)

    def _ack_whatsapp_outbound_message(self, msg_id: int) -> None:
        try:
            self.supabase.rpc("ack_whatsapp_outbound_message", {"p_msg_id": msg_id}).execute()
        except Exception as exc:
            logger.error("No se pudo ACK outbound msg_id=%s: %s", msg_id, exc)

    def _mark_outbound_sent(self, tenant_id: str, message_id: str, meta_message_id: str) -> bool:
        """Marca outbound como processed con retry transaccional.

        Razón B2: Meta ya recibió el mensaje (tenemos meta_message_id). Si el
        UPDATE en DB falla, NO podemos reenviar a Meta sin duplicar al cliente.
        Reintentamos UPDATE 3 veces con backoff. Si todos fallan, fallback a
        marcar el mensaje como 'ack_pending' (estado de reconciliación) — el
        worker NO reintentará el envío a Meta.
        """
        backoffs_ms = [100, 300, 1000]
        for attempt, delay in enumerate(backoffs_ms, start=1):
            try:
                (
                    self.supabase.table("messages")
                    .update(
                        {
                            "meta_message_id": meta_message_id,
                            "processing_status": "processed",
                            "processed": True,
                            "processed_at": datetime.now(timezone.utc).isoformat(),
                            "last_error": None,
                        }
                    )
                    .eq("id", message_id)
                    .eq("tenant_id", tenant_id)
                    .execute()
                )
                return True
            except Exception as exc:
                logger.warning(
                    "outbound.ack_db_retry attempt=%s/%s message_id=%s err=%s",
                    attempt, len(backoffs_ms), message_id, exc,
                )
                if attempt < len(backoffs_ms):
                    time.sleep(delay / 1000.0)
        # Los 3 retries fallaron: dejar el mensaje en ack_pending para reconciliar manualmente.
        logger.error(
            "outbound.ack_pending tenant=%s message_id=%s meta_message_id=%s — DB UPDATE falló 3 veces",
            tenant_id, message_id, meta_message_id,
        )
        try:
            (
                self.supabase.table("messages")
                .update(
                    {
                        "meta_message_id": meta_message_id,
                        "processing_status": "ack_pending",
                        "last_error": "ack_pending: meta entregó, db update falló",
                    }
                )
                .eq("id", message_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
        except Exception as exc:
            logger.critical(
                "outbound.ack_pending_also_failed message_id=%s err=%s — requiere reconciliación manual",
                message_id, exc,
            )
        return False

    async def _run_tenant_hard_delete_if_due(self) -> None:
        """Rev. 109 J.2.4.4 Fase 2 — Hard-delete tenants cuyo grace period expiró.

        Cron interval (default 6h). Process batch (default 10 tenants/ciclo).
        Cada tenant: snapshot ARCHIVE_BEFORE_HARD_DELETE a Storage bucket
        'offboarding-archive' → invoca RPC fn_hard_delete_tenant atómica.

        Idempotente: ya marcados deleted_at se saltan automáticamente vía
        fn_list_tenants_pending_hard_delete (filtra deleted_at IS NULL).
        Tolerante a errores: 1 tenant que falla NO detiene los demás.

        DESACTIVADO por default (TENANT_HARD_DELETE_ENABLED=false). Founder
        debe habilitar en Render env tras validar Fase 2 en staging.
        """
        if not self._tenant_hard_delete_enabled:
            return
        if not hasattr(self.supabase, "rpc"):
            return

        now = time.time()
        if (
            self._last_tenant_hard_delete_at
            and (now - self._last_tenant_hard_delete_at) < max(60, TENANT_HARD_DELETE_INTERVAL_SECONDS)
        ):
            return
        self._last_tenant_hard_delete_at = now

        # Lazy import — evita circular si el lib no está cargado al boot.
        # Fix audit 2026-05-29: usar Path relativo en lugar de hardcoded VM
        # path (que solo existía en la VM de dev, NO en Render → ImportError
        # silente + cron 0 deletes en producción).
        # Pattern canónico usado en worker.py:1582 con _Path(__file__).resolve().
        try:
            from pathlib import Path as _Path  # noqa: PLC0415
            _api_root = _Path(__file__).resolve().parents[1] / "api"
            if str(_api_root) not in sys.path:
                sys.path.insert(0, str(_api_root))
            from lib.tenant_offboarding import (  # noqa: PLC0415
                hard_delete_tenant,
                list_tenants_pending_hard_delete,
                TenantOffboardingError,
            )
        except ImportError as exc:
            logger.warning(
                "[OFFBOARDING-CRON] No se pudo importar lib.tenant_offboarding: %s. "
                "Hard-delete cron desactivado en este proceso.",
                exc,
            )
            self._tenant_hard_delete_enabled = False
            return

        pending = list_tenants_pending_hard_delete(self.supabase, limit=TENANT_HARD_DELETE_BATCH_SIZE)
        if not pending:
            return

        logger.info("[OFFBOARDING-CRON] %s tenant(s) pending hard-delete", len(pending))

        for row in pending:
            tenant_id = row.get("tenant_id")
            if not tenant_id:
                continue
            try:
                result = hard_delete_tenant(self.supabase, str(tenant_id))
                logger.info(
                    "[OFFBOARDING-CRON] Hard-deleted tenant=%s archive=%s rows=%s",
                    tenant_id, result.get("archive_path"), result.get("total_archived_rows"),
                )
                self._metrics.setdefault("tenant_hard_delete_count", 0)
                self._metrics["tenant_hard_delete_count"] += 1
            except TenantOffboardingError as exc:
                logger.warning(
                    "[OFFBOARDING-CRON] Skip tenant=%s (no elegible): %s",
                    tenant_id, exc,
                )
            except Exception as exc:
                logger.error(
                    "[OFFBOARDING-CRON] Error hard-delete tenant=%s: %s. "
                    "Continuando con próximos tenants.",
                    tenant_id, exc, exc_info=True,
                )

    def _mark_outbound_failed(self, tenant_id: str, message_id: str, reason: str) -> bool:
        """Marca un outbound como 'failed'. Devuelve True si el UPDATE quedó.

        BLOQUE J (robustez + review): era la ÚNICA escritura DB del consumidor
        outbound sin protección — un error transitorio del UPDATE propagaba y
        abortaba el resto del batch + los crons siguientes del mismo tick. Ahora:
        (1) retry 3x con backoff (mismo patrón que _mark_outbound_sent) para que un
        fallo transitorio de DB casi nunca deje el row mal etiquetado; (2) si los
        3 fallan, NO propaga (no tumba el ciclo) pero registra un log ERROR + métrica
        `wa_outbound_mark_failed_stuck` → el mislabel deja de ser SILENCIOSO
        (reconciliable: un row failed que quedó 'pending' tiene meta_message_id NULL).
        El caller ACK igual (no podemos re-encolar sin arriesgar reenvío duplicado).
        """
        if not tenant_id or not message_id:
            return False
        backoffs_ms = [100, 300, 1000]
        for attempt, delay in enumerate(backoffs_ms, start=1):
            try:
                (
                    self.supabase.table("messages")
                    .update(
                        {
                            "processing_status": "failed",
                            "processed": True,
                            "processed_at": datetime.now(timezone.utc).isoformat(),
                            "last_error": reason[:1000],
                        }
                    )
                    .eq("id", message_id)
                    .eq("tenant_id", tenant_id)
                    .execute()
                )
                return True
            except Exception as exc:
                logger.warning(
                    "[OUTBOUND] mark_failed retry %s/%s msg=%s: %s",
                    attempt, len(backoffs_ms), message_id, exc,
                )
                if attempt < len(backoffs_ms):
                    time.sleep(delay / 1000.0)
        # Los 3 fallaron: no abortar el ciclo, pero dejar señal alertable.
        self._metrics["wa_outbound_mark_failed_stuck"] = (
            self._metrics.get("wa_outbound_mark_failed_stuck", 0) + 1
        )
        logger.error(
            "[OUTBOUND] mark_failed_stuck tenant=%s msg=%s — DB UPDATE falló 3x; "
            "el row puede quedar mal etiquetado (reconciliar por meta_message_id NULL)",
            (tenant_id or "?")[:8], message_id,
        )
        return False

    async def _collect_health_metrics_if_due(self) -> None:
        """Rev. 109 J.2.11 — Refresca métricas de salud de las 5 integraciones
        per-tenant cada N segundos (default 5min). UPSERTea en
        tenant_provider_health. Detecta transiciones healthy → warning/critical
        y notifica al operador via Telegram (reusa notify_escalation_async).

        Errores per provider NO bloquean los demás. Si lib no carga, gate self.
        """
        if not self._health_metrics_enabled:
            return
        now = time.time()
        if (
            self._last_health_metrics_at
            and (now - self._last_health_metrics_at) < max(60, HEALTH_METRICS_INTERVAL_SECONDS)
        ):
            return
        self._last_health_metrics_at = now

        try:
            from health_metrics import collect_all_for_tenant, upsert_metrics  # noqa: PLC0415
        except ImportError as exc:
            logger.warning("[HEALTH] health_metrics module no disponible: %s", exc)
            self._health_metrics_enabled = False
            return

        # Listar tenants activos (con al menos 1 integration connected).
        try:
            res = (
                self.supabase.table("tenant_integrations")  # tenant_filter:exempt:cron_cross_tenant_health_metrics
                .select("tenant_id")
                .eq("status", "connected")
                .execute()
            )
            tenant_rows = res.data or []
            tenant_ids = sorted({r.get("tenant_id") for r in tenant_rows if r.get("tenant_id")})
        except Exception as exc:
            logger.warning("[HEALTH] Error listando tenants activos: %s", exc)
            return

        # F7: incluir tenants con Telegram configurado en notification_settings
        # (Telegram NO vive en tenant_integrations — ver _collect_telegram_health).
        # Se une ANTES del guard para no perder tenants Telegram-only.
        try:
            tg_res = (
                self.supabase.table("notification_settings")  # tenant_filter:exempt:cron_cross_tenant_health_metrics
                .select("tenant_id")
                .eq("channel", "telegram")
                .eq("enabled", True)
                .execute()
            )
            tg_ids = {r.get("tenant_id") for r in (tg_res.data or []) if r.get("tenant_id")}
            tenant_ids = sorted(set(tenant_ids) | tg_ids)
        except Exception as exc:
            logger.warning("[HEALTH] Error listando tenants con Telegram: %s", exc)

        if not tenant_ids:
            return

        for tenant_id in tenant_ids:
            try:
                # D-F7 async-hygiene — los collectors hacen HTTP síncrono
                # (httpx.Client, timeout 10s: Graph API WhatsApp + Telegram
                # getWebhookInfo) además de queries supabase bloqueantes. Invocarlos
                # directo desde el event loop lo CONGELABA hasta 10-15s POR TENANT.
                # Arquitectura real (server.py): el worker corre en su PROPIO event
                # loop en un thread de fondo; uvicorn sirve /health en el loop del
                # thread principal. Congelar el loop del worker no bloquea a uvicorn,
                # pero SÍ frena la actualización de last_heartbeat_ts que /health lee
                # → el heartbeat quedaba stale y Render marcaba unhealthy. asyncio.to_thread
                # mueve el IO bloqueante (httpx sync + supabase sync) a otro thread →
                # el loop del worker respira y sigue latiendo. Se preserva la firma sync
                # de los collectors (tests los llaman síncronos) y el await es secuencial
                # (sin acceso concurrente al mismo supabase client).
                metrics = await asyncio.to_thread(
                    collect_all_for_tenant, self.supabase, str(tenant_id),
                )
                # F7 — Telegram health-check: collect_telegram (health_metrics.py)
                # lee tenant_integrations, pero la config de Telegram vive en
                # notification_settings desde la unificación rev.109 → nunca
                # reportaba. Complementamos aquí SOLO si el collector no emitió
                # ninguna métrica de Telegram (evita duplicar si se arregla allá).
                if not any(getattr(m, "provider", None) == "telegram" for m in metrics):
                    metrics = metrics + await asyncio.to_thread(
                        self._collect_telegram_health, str(tenant_id),
                    )
                await asyncio.to_thread(
                    upsert_metrics, self.supabase, str(tenant_id), metrics,
                )
                # Detectar transiciones para alertar Telegram operador.
                await self._notify_health_transitions(str(tenant_id), metrics)
            except Exception as exc:
                logger.error(
                    "[HEALTH] Error en tenant=%s: %s", tenant_id, exc, exc_info=True,
                )

    async def _notify_health_transitions(
        self, tenant_id: str, metrics: list,
    ) -> None:
        """Detecta transiciones HEALTHY → WARNING/CRITICAL y notifica al
        operador del tenant via Telegram (reusa notify_escalation_async)."""
        try:
            from telegram_notifications import notify_escalation_async  # noqa: PLC0415
        except ImportError:
            return

        transitions = []
        for m in metrics:
            # F7: claim persistente (survive-restart). Fallback in-memory si la
            # migración no está aplicada. Ambos comparten la MISMA semántica:
            # alertar solo al pasar de {None,healthy,unknown} a {warning,critical}.
            if self._claim_health_alert(tenant_id, m.provider, m.metric, m.status):
                transitions.append(m)

        if not transitions:
            return

        critical_count = sum(1 for m in transitions if m.status == "critical")
        warning_count = sum(1 for m in transitions if m.status == "warning")
        lines = [
            f"🚨 *Alerta salud integraciones* tenant={tenant_id[:8]}",
            f"{critical_count} crítica · {warning_count} advertencia",
            "",
        ]
        for m in transitions[:5]:
            icon = "🔴" if m.status == "critical" else "🟡"
            lines.append(f"{icon} {m.provider}.{m.metric} = {m.value}")
        if len(transitions) > 5:
            lines.append(f"… +{len(transitions) - 5} más")

        # Fix audit 2026-05-29: la firma real de notify_escalation_async es
        # (supabase, *, tenant_id, conversation_id=None, reason, severity).
        # Antes pasaba title/body/priority que NO existen — TypeError silente.
        try:
            await notify_escalation_async(
                self.supabase,
                tenant_id=tenant_id,
                reason="\n".join(lines),
                severity="critical" if critical_count else "warning",
            )
        except Exception as exc:
            logger.warning(
                "[HEALTH] notify_escalation_async falló tenant=%s: %s",
                tenant_id, exc,
            )

    def _claim_health_alert(
        self, tenant_id: str, provider: str, metric: str, status: str,
    ) -> bool:
        """F7 — decide si alertar por (tenant, provider, metric) SIN re-spamear
        tras un restart del worker.

        Fuente autoritativa: RPC fn_claim_health_alert (estado persistente en
        provider_health_alert_dedup). Si la RPC/tabla no existe (migración no
        aplicada), degrada al snapshot in-memory con la MISMA semántica:
        alertar solo al pasar de {None,healthy,unknown} a {warning,critical}.
        """
        key = (tenant_id, provider, metric)
        if self._health_alert_persistent:
            try:
                res = self.supabase.rpc(
                    "fn_claim_health_alert",
                    {
                        "p_tenant_id": tenant_id,
                        "p_provider": provider,
                        "p_metric": metric,
                        "p_status": status,
                    },
                ).execute()
                val = res.data
                if isinstance(val, list):
                    val = val[0] if val else False
                if isinstance(val, dict):
                    val = next(iter(val.values()), False)
                # Mantener el snapshot in-memory en sync por si la RPC cae luego.
                self._health_status_snapshot[key] = status
                return bool(val)
            except Exception as exc:
                # NO deshabilitar permanentemente la RPC: un blip transitorio no
                # debe volver la tabla persistente stale para siempre. Se reintenta
                # la RPC cada ciclo; el fallback in-memory cubre SOLO el ciclo que
                # falló (el loop de salud es infrecuente → costo despreciable, y la
                # tabla provider_health_alert_dedup sigue siendo autoritativa).
                logger.warning(
                    "[HEALTH] fn_claim_health_alert no disponible este ciclo (%s) — "
                    "fallback dedup in-memory por este ciclo; reintento el próximo", exc,
                )

        prev_status = self._health_status_snapshot.get(key)
        self._health_status_snapshot[key] = status
        return prev_status in {None, "healthy", "unknown"} and status in {"warning", "critical"}

    def _collect_telegram_health(self, tenant_id: str) -> list:
        """F7 — Telegram health-check leyendo notification_settings (NO
        tenant_integrations).

        Desde la unificación rev.109 la config de Telegram (bot_token cifrado en
        Vault + enabled) vive en notification_settings, por lo que collect_telegram
        de health_metrics.py — que consulta tenant_integrations — nunca reportaba.
        Replicamos aquí getWebhookInfo con la misma semántica de estado.

        Best-effort y self-contained: cualquier fallo NO rompe el ciclo de salud.
        """
        try:
            from health_metrics import HealthMetric  # noqa: PLC0415
        except ImportError:
            return []

        try:
            res = (
                self.supabase.table("notification_settings")
                .select("enabled, config")
                .eq("tenant_id", tenant_id)
                .eq("channel", "telegram")
                .limit(1)
                .execute()
            )
            rows = res.data or []
        except Exception as exc:
            logger.warning("[HEALTH] Telegram: error leyendo notification_settings tenant=%s: %s", tenant_id, exc)
            return []

        if not rows or not rows[0].get("enabled"):
            return []

        config = rows[0].get("config") or {}
        secret_id = config.get("bot_token_secret_id")
        bot_token = None
        if secret_id:
            try:
                from vault_helper import VaultHelper  # noqa: PLC0415
                bot_token = VaultHelper(self.supabase).read_secret(secret_id)
            except Exception as exc:
                logger.warning("[HEALTH] Telegram: error resolviendo bot_token tenant=%s: %s", tenant_id, exc)

        if not bot_token:
            return [HealthMetric(
                provider="telegram",
                metric="config",
                value="missing bot_token",
                status="critical",
                detail={"reason": "bot_token no resoluble desde Vault"},
            )]

        try:
            import httpx  # noqa: PLC0415
            # httpx.Client síncrono OK aquí: este método se invoca vía
            # asyncio.to_thread desde _collect_health_metrics_if_due (D-F7), así el
            # getWebhookInfo (timeout 10s) NO bloquea el event loop del worker.
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"https://api.telegram.org/bot{bot_token}/getWebhookInfo")
                if resp.status_code != 200:
                    return [HealthMetric(
                        provider="telegram",
                        metric="api_reachability",
                        value=f"HTTP {resp.status_code}",
                        status="critical",
                        detail={"body": resp.text[:200]},
                    )]
                data = resp.json()
        except Exception as exc:
            return [HealthMetric(
                provider="telegram",
                metric="api_reachability",
                value=f"error: {type(exc).__name__}",
                status="critical",
                detail={"error": str(exc)[:200]},
            )]

        info = data.get("result") or {}
        pending = int(info.get("pending_update_count") or 0)
        last_error = info.get("last_error_message")

        if pending >= 50:
            status = "critical"
        elif pending >= 10:
            status = "warning"
        else:
            status = "healthy" if not last_error else "warning"

        metrics = [HealthMetric(
            provider="telegram",
            metric="pending_update_count",
            value=str(pending),
            threshold="<10 deseado · ≥50 crítico",
            status=status,
            detail={"webhook_info": info},
        )]
        if last_error:
            metrics.append(HealthMetric(
                provider="telegram",
                metric="last_webhook_error",
                value=str(last_error)[:200],
                status="warning",
            ))
        return metrics

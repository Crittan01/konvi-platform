import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from orchestrator import build_and_run_orchestration
from conversation_contract import PROCESSING_STATUS_PROCESSING
from notifications import dispatch_human_takeover_event
from whatsapp_sender import send_whatsapp_message

logger = logging.getLogger("orchestrator.worker")

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "3"))
MAX_PROCESSING_ATTEMPTS = int(os.getenv("MAX_PROCESSING_ATTEMPTS", "5"))
# Rev. 85 — debounce/coalescing window. Si el cliente envía múltiples
# mensajes rápidos, esperamos esta ventana antes de procesar para juntar
# en un solo input al LLM (no perder contexto al ver solo el último msg).
MESSAGE_COALESCE_WINDOW_SECONDS = int(os.getenv("MESSAGE_COALESCE_WINDOW_SECONDS", "5"))
HUMAN_TAKEOVER_QUEUE_ENABLED = os.getenv("HUMAN_TAKEOVER_QUEUE_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
HUMAN_TAKEOVER_QUEUE_POLL_BATCH = int(os.getenv("HUMAN_TAKEOVER_QUEUE_POLL_BATCH", "10"))
HUMAN_TAKEOVER_QUEUE_VT_SECONDS = int(os.getenv("HUMAN_TAKEOVER_QUEUE_VT_SECONDS", "90"))
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
# Anti-hibernación Render Free: ping al propio endpoint /health para prevenir que
# el servicio web se hiberne. Solo necesario en plan Free (sin keep-alive nativo).
ANTI_HIBERNATION_ENABLED = os.getenv("ANTI_HIBERNATION_ENABLED", "false").lower() in {
    "1", "true", "yes", "on"
}
ANTI_HIBERNATION_PING_URL = os.getenv("ANTI_HIBERNATION_PING_URL", "")
ANTI_HIBERNATION_INTERVAL_SECONDS = int(os.getenv("ANTI_HIBERNATION_INTERVAL_SECONDS", "840"))  # 14 min
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


class OrchestratorWorker:
    """
    Worker de polling que detecta mensajes entrantes no procesados
    y dispara el ciclo de orquestación IA → WhatsApp por cada uno.

    Patrón: Background Worker de Render (sin HTTP).
    Intervalo: configurable via env POLL_INTERVAL_SECONDS (default 3s).
    """

    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("Faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        self._running = False
        self._queue_runtime_enabled = HUMAN_TAKEOVER_QUEUE_ENABLED
        self._wa_queue_runtime_enabled = WHATSAPP_OUTBOUND_QUEUE_ENABLED
        self._cleanup_enabled = IDEMPOTENCY_CLEANUP_ENABLED
        self._last_cleanup_at = 0.0
        self._release_enabled = PENDING_PAYMENT_RELEASE_ENABLED
        self._last_release_at = 0.0
        self._reminder_enabled = PAYMENT_REMINDER_ENABLED
        self._last_reminder_at = 0.0
        self._anti_hibernation_enabled = ANTI_HIBERNATION_ENABLED and bool(ANTI_HIBERNATION_PING_URL)
        self._last_ping_at = 0.0
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
        }

    def stop(self):
        self._running = False

    async def run(self):
        self._running = True
        logger.info(f"Worker activo — polling cada {POLL_INTERVAL_SECONDS}s")
        await self._sweep_stale_messages_on_startup()

        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error(f"Error en ciclo de polling: {e}", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_cycle(self):
        """Ejecuta ciclo de inbound + notificaciones operacionales + mantenimiento."""
        self._metrics["poll_cycles"] += 1
        await self._poll_inbound_messages()
        await self._poll_human_takeover_notifications()
        await self._poll_whatsapp_outbound_messages()
        await self._run_idempotency_cleanup_if_due()
        await self._send_payment_reminders_if_due()
        await self._release_expired_pending_payment_orders()
        await self._anti_hibernation_ping_if_due()

    async def _coalesce_pending_by_conversation(self, pending: list[dict]) -> list[dict]:
        """Rev. 85 — Coalesce mensajes consecutivos del mismo cliente.

        Si una conversación tiene un mensaje que llegó hace <5s, esperamos
        el resto de la ventana antes de procesar — eso da tiempo a que
        lleguen mensajes adicionales del cliente que quería continuar.

        Cuando hay 2+ mensajes pendientes de la misma conversación tras la
        ventana, los unimos en un solo input al LLM (separados por `\n\n`)
        y marcamos los anteriores como `processed` con metadata indicando
        que fueron coalesced. El último mensaje original es el que pasa
        al orchestrator con el contenido combinado.

        Esto evita el bug observado donde "Hola" como último msg después
        de un flujo de compra hacía al bot resetear al saludo y perder
        el contexto previo.
        """
        if not pending:
            return pending
        # Agrupar por conversation_id manteniendo orden cronológico
        from collections import OrderedDict
        by_conv: dict = OrderedDict()
        for m in pending:
            by_conv.setdefault(m["conversation_id"], []).append(m)

        # Si hay solo una conv y todos los mensajes son recientes, vale
        # la pena esperar la ventana para que lleguen más.
        max_age = 0.0
        now = datetime.now(timezone.utc)
        for msgs in by_conv.values():
            for m in msgs:
                ts = m.get("created_at")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    age = (now - dt).total_seconds()
                    if age > max_age:
                        max_age = age
                except (ValueError, TypeError):
                    continue
        if max_age < MESSAGE_COALESCE_WINDOW_SECONDS:
            wait_more = MESSAGE_COALESCE_WINDOW_SECONDS - max_age
            logger.info(
                "[COALESCE] mensajes recientes (max_age=%.1fs); esperando %.1fs",
                max_age, wait_more,
            )
            await asyncio.sleep(wait_more)
            # Re-fetch tras la espera para capturar nuevos pendings.
            re_result = (
                self.supabase.table("messages")
                .select("id, tenant_id, conversation_id, content, content_type, processing_attempts, created_at")
                .eq("direction", "inbound")
                .eq("processing_status", "pending")
                .order("created_at", desc=False)
                .limit(10)
                .execute()
            )
            pending = re_result.data or pending
            by_conv.clear()
            for m in pending:
                by_conv.setdefault(m["conversation_id"], []).append(m)

        # Ahora coalescer cada conv que tenga 2+ mensajes
        coalesced: list[dict] = []
        for conv_id, msgs in by_conv.items():
            if len(msgs) >= 2:
                # Marcar los anteriores como processed (coalesced)
                older_ids = [m["id"] for m in msgs[:-1]]
                try:
                    self.supabase.table("messages").update({
                        "processing_status": "processed",
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "skip_reason": "coalesced_into_next",
                    }).in_("id", older_ids).execute()
                except Exception as exc:
                    logger.warning("[COALESCE] no pude marcar coalesced: %s", exc)
                # El último msg lleva el content combinado
                last = dict(msgs[-1])
                combined = "\n\n".join(str(m.get("content") or "") for m in msgs)
                last["content"] = combined
                logger.info(
                    "[COALESCE] conv=%s coalesce %d mensajes en uno (chars=%d)",
                    conv_id[:8], len(msgs), len(combined),
                )
                coalesced.append(last)
            else:
                coalesced.extend(msgs)
        return coalesced

    async def _poll_inbound_messages(self):
        """Busca mensajes inbound pendientes y los orquesta.

        Rev. 85 — Coalescing: agrupa por conversation_id. Si una conv
        tiene múltiples mensajes pendientes (cliente envió varios
        seguidos), espera la ventana de debounce y los junta en un solo
        input al LLM. Evita que el último mensaje (típicamente "Hola"
        o follow-up corto) domine el contexto y haga al bot perder el
        flujo previo.
        """
        # Selección de mensajes pendientes — hasta 10 por ciclo para no saturar
        result = (
            self.supabase.table("messages")
            .select("id, tenant_id, conversation_id, content, content_type, processing_attempts, created_at")
            .eq("direction", "inbound")
            .eq("processing_status", "pending")
            .order("created_at", desc=False)
            .limit(10)
            .execute()
        )

        pending = result.data or []
        if not pending:
            return
        self._metrics["inbound_seen"] += len(pending)

        logger.info(f"📬 {len(pending)} mensaje(s) pendiente(s) encontrado(s)")

        # Rev. 85 — Coalesce: agrupar por conversation_id. Si la conv tiene
        # mensajes muy recientes (<5s), esperar el resto de la ventana para
        # capturar mensajes adicionales que lleguen mientras esperamos.
        pending = await self._coalesce_pending_by_conversation(pending)

        # Procesar en secuencia para no sobrecargar la API de Gemini
        for msg in pending:
            try:
                attempts = int(msg.get("processing_attempts") or 0) + 1
                if attempts > MAX_PROCESSING_ATTEMPTS:
                    self.supabase.table("messages").update({
                        "processing_status": "failed",
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": "max_attempts_exceeded",
                    }).eq("id", msg["id"]).execute()
                    logger.warning(
                        "Mensaje %s marcado failed por max_attempts=%s",
                        msg["id"],
                        MAX_PROCESSING_ATTEMPTS,
                    )
                    continue

                # Lock atómico (compare-and-swap): solo procesamos si el mensaje
                # sigue en 'pending'. Si otro worker ya lo cambió, el update
                # retorna data vacía y saltamos.
                lock_res = self.supabase.table("messages").update({
                    "processing_attempts": attempts,
                    "processing_status": PROCESSING_STATUS_PROCESSING,
                    "last_error": None,
                }).eq("id", msg["id"]).eq("processing_status", "pending").execute()

                if not lock_res.data:
                    logger.info(
                        "Mensaje %s ya fue tomado por otro worker. Saltando.", msg["id"]
                    )
                    continue

                # Rev. 75 — V2 cancelado, llamada directa al orquestador único.
                # Razón: V2 modular era experimento de 22h (commit b153054)
                # con dependencias cruzadas hacia el monolito V1 maduro
                # (22 días + 37 commits + fixes rev. 70-73). Quedarse con
                # ambos era deuda incremental sin payoff claro. Cuando se
                # quiera modularidad, se refactoriza V1 orgánicamente sobre
                # código probado.
                await build_and_run_orchestration(
                    supabase=self.supabase,
                    message_id=msg["id"],
                    tenant_id=msg["tenant_id"],
                    conversation_id=msg["conversation_id"],
                    content=msg["content"],
                    content_type=msg["content_type"],
                )
            except Exception as e:
                logger.error(
                    f"Error procesando mensaje {msg['id']}: {e}", exc_info=True
                )
                # El core orquestador intenta registrar failed. Continuar con el siguiente.

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
                logger.warning("Takeover msg_id=%s no ACK (retry tras VT)", msg_id)

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

            if not tenant_id or not to_phone or not text or not message_id:
                logger.error("Payload outbound incompleto msg_id=%s payload=%s", msg_id, payload)
                self._mark_outbound_failed(tenant_id, message_id, "invalid_outbound_payload")
                self._ack_whatsapp_outbound_message(msg_id)
                continue

            try:
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

        # Rev. 71 — cleanup del bot_source_log (TTL 30 días, append-only).
        try:
            self.supabase.rpc("cleanup_expired_bot_source_log", {"retention_days": 30}).execute()
        except Exception:
            pass  # La función puede no existir si la migración rev. 71 no está aplicada

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
          ANTI_HIBERNATION_PING_URL=https://commerce-ops-web.onrender.com/api/health,https://commerce-ops-api.onrender.com/health
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

    async def _sweep_stale_messages_on_startup(self) -> None:
        """
        Al iniciar el worker, reestablece mensajes atascados en 'pending' o 'processing'
        que llevan más de 5 minutos sin avanzar.

        Escenario típico: el worker anterior se reinició (Render Free hiberna / deploy)
        dejando mensajes en 'processing' que nunca completaron. Sin este sweep, esos
        mensajes quedarían bloqueados indefinidamente porque el nuevo loop solo consume
        mensajes nuevos.

        Solo reestablece a 'pending' si no superaron MAX_PROCESSING_ATTEMPTS.
        """
        stale_cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()

        try:
            stale_res = (
                self.supabase.table("messages")
                .select("id, processing_attempts")
                .eq("direction", "inbound")
                .in_("processing_status", ["pending", "processing"])
                .lt("created_at", stale_cutoff)
                .limit(100)
                .execute()
            )
            stale = stale_res.data or []
            if not stale:
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
                        "last_error": "abandoned_at_startup_max_attempts",
                    }).eq("id", msg["id"]).execute()
                    abandoned += 1
                else:
                    self.supabase.table("messages").update({
                        "processing_status": "pending",
                    }).eq("id", msg["id"]).in_("processing_status", ["pending", "processing"]).execute()
                    recovered += 1

            logger.info(
                "[STARTUP] Sweep completado: %s mensajes re-encolados, %s abandonados (max_attempts)",
                recovered, abandoned,
            )
        except Exception as exc:
            logger.error("[STARTUP] Error en sweep de startup: %s", exc)

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
                self.supabase.table("orders")
                .select("id, tenant_id, conversation_id, created_at, "
                        "conversations(customer_phone)")
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
            order_id = order.get("id")
            tenant_id = order.get("tenant_id")
            conversation_id = order.get("conversation_id")
            conv = order.get("conversations") or {}
            customer_phone = conv.get("customer_phone") if isinstance(conv, dict) else None

            if not (order_id and tenant_id and conversation_id and customer_phone):
                logger.warning("[REMINDER] order=%s con datos incompletos — skip",
                               (order_id or "?")[:8])
                continue

            try:
                last_in_res = (
                    self.supabase.table("messages")
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
                # Fuera de CSW: free-form bloqueado por Meta. Mark como
                # salteado para no reintentar; F2 (templates) lo manejará.
                self._metrics["payment_reminders_skipped_csw_closed"] += 1
                try:
                    self.supabase.table("orders").update({
                        "payment_reminder_sent_at": now_dt.isoformat(),
                    }).eq("id", order_id).is_("payment_reminder_sent_at", "null").execute()
                except Exception:
                    pass
                logger.info(
                    "[REMINDER] CSW cerrada — order=%s skip (F2 pendiente: HSM template)",
                    order_id[:8],
                )
                continue

            short_id = str(order_id)[:8].upper()
            text = (
                f"Te queda *5 min* para usar el link de pago de tu pedido "
                f"*#{short_id}*.\n\n"
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
                self.supabase.table("orders")
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
            for order in stale:
                # Guard: no cancelar si hay payment pending fresco (cliente
                # regeneró link recientemente vía bucket (b)).
                try:
                    fresh_pay_res = (
                        self.supabase.table("payments")
                        .select("id, created_at")
                        .eq("order_id", order["id"])
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

                res = (
                    self.supabase.table("orders")
                    .update({
                        "status": "cancelled",
                    })
                    .eq("id", order["id"])
                    .eq("status", "pending_payment")  # guard contra race condition
                    .execute()
                )
                if res.data:
                    cancelled += 1

            if cancelled:
                self._metrics["expired_orders_cancelled"] += cancelled
                logger.info(
                    "⏱️ Pedidos pending_payment expirados cancelados: %s (TTL=%smin)",
                    cancelled,
                    PENDING_PAYMENT_TTL_MINUTES,
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

    def _mark_outbound_failed(self, tenant_id: str, message_id: str, reason: str) -> None:
        if not tenant_id or not message_id:
            return
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

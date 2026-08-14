"""Crons comerciales del worker (extraído de worker.py — G12, clase mixin).

Cluster cohesivo de jobs periódicos de dinero/post-venta:
  • Payment reminders (recordatorio de pago pendiente CSW/HSM).
  • Reversal constancias (constancia de reversión al cliente).
  • Receipts/comprobantes (emisión + acuse WhatsApp + email).

Las constantes de tuning de estos jobs viven aquí (incl. META_CSW_HOURS y
PENDING_PAYMENT_TTL_MINUTES, compartidas — worker.py las re-importa a su
namespace). Extraído verbatim 2026-08-13 — comportamiento idéntico:
`OrchestratorWorker(WorkerCommerceCronsMixin)` hereda estos métodos.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from lib.outbound_gate import Categoria, puede_enviar_proactivo, registrar_bloqueo
from whatsapp_sender import (
    TEMPLATE_ERR_TEMPLATE_NOT_APPROVED,
    TEMPLATE_ERR_TEMPLATE_NOT_FOUND,
    send_whatsapp_message,
    send_whatsapp_template,
)

logger = logging.getLogger(__name__)

META_CSW_HOURS = int(os.getenv("META_CSW_HOURS", "24"))

PENDING_PAYMENT_TTL_MINUTES = int(os.getenv("PENDING_PAYMENT_TTL_MINUTES", "35"))

PAYMENT_REMINDER_DELAY_MINUTES = int(os.getenv("PAYMENT_REMINDER_DELAY_MINUTES", "25"))

PAYMENT_REMINDER_INTERVAL_SECONDS = int(os.getenv("PAYMENT_REMINDER_INTERVAL_SECONDS", "60"))

PAYMENT_REMINDER_WINDOW_MINUTES = int(os.getenv("PAYMENT_REMINDER_WINDOW_MINUTES", "5"))

REVERSAL_SWEEP_INTERVAL_SECONDS = int(os.getenv("REVERSAL_SWEEP_INTERVAL_SECONDS", "300"))

REVERSAL_BATCH = int(os.getenv("REVERSAL_BATCH", "50"))

RECEIPT_ISSUE_INTERVAL_SECONDS = int(os.getenv("RECEIPT_ISSUE_INTERVAL_SECONDS", "600"))

RECEIPT_MIN_AGE_MINUTES = int(os.getenv("RECEIPT_MIN_AGE_MINUTES", "10"))

RECEIPT_WINDOW_HOURS = int(os.getenv("RECEIPT_WINDOW_HOURS", "72"))

RECEIPT_BATCH = int(os.getenv("RECEIPT_BATCH", "50"))


class WorkerCommerceCronsMixin:
    """Ver docstring del módulo. Los métodos usan self.* del worker."""

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
            # Única puerta de salida de los mensajes proactivos. Antes este camino solo
            # miraba `human_takeover`: un cliente que escribió STOP recibía "ya no
            # recibirás mensajes nuestros" y el recordatorio le seguía llegando. El camino
            # HSM sí lo filtraba, así que dos caminos aplicaban reglas distintas a la
            # misma persona.
            _decision = puede_enviar_proactivo(
                self.supabase, tenant_id=tenant_id,
                categoria=Categoria.TRANSACCIONAL,
                conversation_id=conversation_id,
            )
            if not _decision:
                registrar_bloqueo(_decision, canal="recordatorio_pago", referencia=order_id[:8])
                self._metrics["proactivos_bloqueados"] = (
                    self._metrics.get("proactivos_bloqueados", 0) + 1
                )
                continue

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

    async def _sweep_reversals_if_due(self) -> None:
        """Entrega las constancias de reversión y avisa cuando el dinero salió dos veces.

        LA CONSTANCIA. Decreto 1074 art. 2.2.2.51.4: el proveedor "deberá emitir
        constancia" de la queja, con fecha y causal. Emitirla y dejarla en una tabla no
        cumple nada: el art. 2.2.2.51.7 num. 6 se la exige al consumidor como contenido de
        la notificación a SU banco, así que si no la tiene en la mano no puede ejercer el
        derecho. Por eso se remite, igual que el acuse del comprobante.

        EL DOBLE PAGO. Art. 2.2.2.51.10 contempla expresamente que el dinero salga por los
        dos caminos —el operador reembolsa mientras el emisor reversa en paralelo— y que el
        consumidor deba devolverlo. Sin esta alerta sería invisible: nadie está mirando las
        dos cosas al tiempo, y no se puede reclamar lo que no se sabe que se pagó.
        """
        if not self._reversal_enabled:
            return
        if not hasattr(self.supabase, "rpc"):
            return

        now = time.time()
        if now - self._last_reversal_at < max(60, REVERSAL_SWEEP_INTERVAL_SECONDS):
            return
        self._last_reversal_at = now

        await self._deliver_reversal_constancias()
        await self._alert_reversal_double_payments()

    async def _deliver_reversal_constancias(self) -> None:
        try:
            pendientes = self.supabase.rpc(
                "rpc_find_constancias_por_entregar",
                {"p_csw_hours": META_CSW_HOURS, "p_limit": REVERSAL_BATCH},
            ).execute().data or []
        except Exception as exc:
            logger.warning("[REVERSION] no pude buscar constancias por entregar: %s", exc)
            return

        from lib.reversion_pago import texto_constancia

        for r in pendientes:
            # Latido por ÍTEM, igual que los demás loops con I/O de red (inbound, guías,
            # voids de Wompi). `run()` late UNA vez por ciclo y `/health` corta a los 120 s:
            # con Meta degradado, 13 envíos de 10 s de timeout pasan de ese umbral, Render
            # reinicia el worker a mitad del barrido y —como `_last_reversal_at` vuelve a
            # 0.0— arranca por las mismas filas. Eso es un crash loop.
            self.last_heartbeat_ts = time.time()
            rid, tenant_id = r.get("reversal_id"), r.get("tenant_id")
            conv_id, radicado = r.get("conversation_id"), r.get("radicado")
            if not (rid and tenant_id and conv_id):
                continue

            # La ventana de servicio de 24 h de Meta. El acuse del comprobante ya la
            # respeta; la constancia —que es la obligación más dura de las dos— no lo hacía
            # y mandaba free-form a ciegas. Cuando Meta la rechaza (131047),
            # `send_whatsapp_message` devuelve None sin lanzar, así que el barrido no
            # marcaba nada y reintentaba cada 300 s para siempre; y como la cola va por
            # `constancia_emitida_at ASC LIMIT 50`, esas filas envenenadas tapaban a las
            # constancias nuevas que sí eran entregables.
            if not r.get("dentro_de_csw"):
                self._metrics["reversal_constancias_failed"] += 1
                logger.warning(
                    "[REVERSION] %s sin entregar: fuera de la ventana de 24h de Meta. "
                    "Hay que hacérsela llegar por otro medio — sin ella el comprador no "
                    "puede notificar a su emisor (Decreto 1074 art. 2.2.2.51.7 num. 6).",
                    radicado,
                )
                self._marcar_constancia(rid, tenant_id, "fuera_de_ventana_csw")
                continue

            texto = texto_constancia(r.get("constancia") or {})
            try:
                conv = (
                    self.supabase.table("conversations")
                    .select("customer_phone")
                    .eq("id", conv_id).eq("tenant_id", tenant_id)
                    .limit(1).execute()
                )
                telefono = (conv.data or [{}])[0].get("customer_phone")
                if not telefono:
                    # Se marca como fallida y NO se reintenta: sin teléfono el barrido
                    # giraría para siempre. La constancia sigue existiendo y el operador la
                    # ve en el reclamo, que es donde puede hacer algo al respecto.
                    self._marcar_constancia(rid, tenant_id, "sin_telefono")
                    continue
                meta_id = await send_whatsapp_message(
                    tenant_id=tenant_id, supabase=self.supabase,
                    to_phone=telefono, text=texto,
                )
            except Exception as exc:
                logger.error("[REVERSION] fallo entregando %s: %s", radicado, exc)
                continue

            if not meta_id:
                # No se marca: el próximo barrido reintenta. Sin esta constancia el
                # consumidor no puede notificar a su banco — darla por perdida al primer
                # fallo le cerraría el trámite.
                logger.error("[REVERSION] %s no salió — se reintenta", radicado)
                continue

            if not self._marcar_constancia(rid, tenant_id, None):
                continue  # otro tick ganó la carrera

            self._metrics["reversal_constancias_sent"] += 1
            logger.info("[REVERSION] constancia %s entregada", radicado)
            try:
                self.supabase.table("messages").insert({
                    "conversation_id": conv_id,
                    "tenant_id": tenant_id,
                    "direction": "outbound",
                    "content_type": "text",
                    "content": texto,
                    "meta_message_id": meta_id,
                    "processed": True,
                    "processing_status": "processed",
                }).execute()
            except Exception as exc:
                logger.warning("[REVERSION] constancia entregada pero no persistida: %s", exc)

    async def _alert_reversal_double_payments(self) -> None:
        try:
            dobles = self.supabase.rpc(
                "rpc_find_dobles_pagos_sin_avisar", {"p_limit": REVERSAL_BATCH},
            ).execute().data or []
        except Exception as exc:
            logger.warning("[REVERSION] no pude buscar dobles pagos: %s", exc)
            return

        for d in dobles:
            rid, tenant_id, radicado = d.get("reversal_id"), d.get("tenant_id"), d.get("radicado")
            if not (rid and tenant_id):
                continue
            detalle = (
                f"Reversión {radicado}: el dinero salió por los DOS caminos "
                f"(reembolso directo ${d.get('reembolso') or 0} y reversión del emisor "
                f"${d.get('reversion') or 0}). Decreto 1074 art. 2.2.2.51.10: el consumidor "
                f"debe devolver esos recursos. Hay que contactarlo."
            )
            # `notify_escalation_async` NO lanza: devuelve False cuando el tenant no
            # tiene Telegram habilitado, cuando falta el chat_id, cuando Vault no resuelve
            # el token o cuando Telegram responde error. Ignorar el retorno hacía que se
            # marcara como avisado un aviso que nunca salió — y la fila desaparecía de la
            # cola PARA SIEMPRE. En un tenant nuevo, que es el estado por defecto, nadie se
            # enteraba de que había pagado dos veces la misma compra.
            avisado = False
            try:
                from telegram_notifications import notify_escalation_async
                avisado = bool(await notify_escalation_async(
                    self.supabase, tenant_id=tenant_id,
                    conversation_id=None, reason=detalle,
                ))
            except Exception as exc:
                logger.warning("[REVERSION] no pude avisar el doble pago de %s: %s",
                               radicado, exc)

            if not avisado:
                # Sin marcar: se reintenta. Un doble pago que nadie ve es plata perdida, y
                # el art. 2.2.2.51.10 pone en cabeza del vendedor reclamarla.
                logger.error(
                    "[REVERSION] DOBLE PAGO en %s y el aviso NO salió — %s", radicado, detalle,
                )
                continue

            if self._marcar_doble_pago_avisado(rid, tenant_id):
                self._metrics["reversal_double_payments"] += 1
                logger.error("[REVERSION] DOBLE PAGO en %s — %s", radicado, detalle)

    def _marcar_constancia(self, reversal_id, tenant_id, fallida) -> bool:
        """True si esta corrida fue la que marcó. False si otra ya lo había hecho."""
        try:
            res = self.supabase.rpc("rpc_mark_constancia_entregada", {
                "p_reversal_id": reversal_id, "p_tenant_id": tenant_id,
                "p_fallida": fallida,
            }).execute()
            return bool(res.data)
        except Exception as exc:
            logger.error("[REVERSION] no pude marcar la constancia %s: %s", reversal_id, exc)
            return False

    def _marcar_doble_pago_avisado(self, reversal_id, tenant_id) -> bool:
        try:
            res = self.supabase.rpc("rpc_mark_doble_pago_avisado", {
                "p_reversal_id": reversal_id, "p_tenant_id": tenant_id,
            }).execute()
            return bool(res.data)
        except Exception as exc:
            logger.error("[REVERSION] no pude marcar el aviso de %s: %s", reversal_id, exc)
            return False

    async def _issue_receipts_if_due(self) -> None:
        """Emite el comprobante de los pedidos confirmados que aún no lo tienen.

        Ley 1480 art. 50 lit. d) obliga a remitir acuse de recibo del pedido a más tardar
        el DÍA CALENDARIO SIGUIENTE. Hoy el comprador no recibe ningún documento.

        POR QUÉ UN BARRIDO Y NO UN TRIGGER: hay cinco caminos a 'confirmed' repartidos en
        tres servicios, así que enganchar la emisión en cada uno garantiza que el sexto no
        la tenga. Pero un trigger tampoco sirve — en contra entrega el pedido nace
        confirmado y sus `order_items` se insertan DESPUÉS, así que vería subtotal 0
        contra un total mayor, concluiría "cifras incoherentes" y no emitiría nunca.
        Diferir unos minutos resuelve ambas cosas y sigue estando holgadamente dentro
        del plazo legal.

        Un pedido cuyas cifras no cuadran NO recibe comprobante: se registra y se alerta.
        Documentar una contradicción es peor que no documentar (art. 26).

        Este barrido solo EMITE. La entrega al comprador es el paso siguiente.
        """
        if not self._receipt_enabled:
            return
        if not hasattr(self.supabase, "rpc"):
            return

        now = time.time()
        if now - self._last_receipt_at < max(60, RECEIPT_ISSUE_INTERVAL_SECONDS):
            return
        self._last_receipt_at = now

        try:
            res = self.supabase.rpc(
                "rpc_find_orders_pending_receipt",
                {
                    "p_min_age_minutes": RECEIPT_MIN_AGE_MINUTES,
                    "p_window_hours": RECEIPT_WINDOW_HOURS,
                    "p_limit": RECEIPT_BATCH,
                },
            ).execute()
            pendientes = res.data or []
        except Exception as exc:
            logger.warning("[COMPROBANTE] no pude buscar pedidos sin comprobante: %s", exc)
            return

        for p in pendientes:
            order_id, tenant_id = p.get("order_id"), p.get("tenant_id")
            if not (order_id and tenant_id):
                continue
            try:
                r = self.supabase.rpc(
                    "rpc_issue_receipt",
                    {"p_order_id": order_id, "p_tenant_id": tenant_id},
                ).execute()
                fila = (r.data or [{}])[0] if isinstance(r.data, list) else (r.data or {})
            except Exception as exc:
                logger.error("[COMPROBANTE] fallo emitiendo order=%s: %s",
                             str(order_id)[:8], exc)
                continue

            motivo = fila.get("motivo")
            if motivo == "cifras_incoherentes":
                self._metrics["receipts_blocked_incoherent"] += 1
                logger.error(
                    "[COMPROBANTE] order=%s tenant=%s SIN comprobante: sus cifras no cuadran. "
                    "Corregir el pedido antes de documentarlo (Ley 1480 art. 26).",
                    str(order_id)[:8], str(tenant_id)[:8],
                )
                continue
            if motivo:
                logger.warning("[COMPROBANTE] order=%s no emitido: %s", str(order_id)[:8], motivo)
                continue
            if fila.get("ya_existia"):
                continue

            self._metrics["receipts_issued"] += 1
            logger.info(
                "[COMPROBANTE] %s emitido para order=%s tenant=%s",
                fila.get("numero"), str(order_id)[:8], str(tenant_id)[:8],
            )

        await self._send_receipt_acks()
        await self._send_receipt_emails()

        # Red que atrapa lo que el trigger de cancelación no cubrió: filas anteriores a
        # él, o una anulación que falló. Un comprobante vivo sobre un pedido cancelado es
        # un comprador con un documento que afirma una compra que ya no existe.
        try:
            colgados = self.supabase.rpc(
                "rpc_find_receipts_to_void", {"p_limit": RECEIPT_BATCH},
            ).execute().data or []
        except Exception as exc:
            logger.warning("[COMPROBANTE] no pude buscar comprobantes por anular: %s", exc)
            return

        for c in colgados:
            order_id, tenant_id = c.get("order_id"), c.get("tenant_id")
            if not (order_id and tenant_id):
                continue
            try:
                self.supabase.rpc("rpc_void_receipt", {
                    "p_order_id": order_id, "p_tenant_id": tenant_id,
                    "p_reason": "pedido cancelado (reconciliación)",
                }).execute()
                self._metrics["receipts_voided"] += 1
                logger.warning(
                    "[COMPROBANTE] %s anulado por reconciliación — el pedido %s está cancelado",
                    c.get("numero"), str(order_id)[:8],
                )
            except Exception as exc:
                logger.error("[COMPROBANTE] no pude anular el de order=%s: %s",
                             str(order_id)[:8], exc)

    def _texto_acuse(self, numero, total, forma_pago) -> str:
        """El acuse que ve el comprador. CORTO a propósito.

        Va a `messages`, que alimenta el contexto conversacional del LLM. Meter acá el
        documento completo costaría tokens en CADA turno posterior y le daría al modelo
        un texto lleno de cifras para parafrasear — choca con "el LLM no decide verdad
        transaccional" y con el hallazgo de UAT del "total mentido". El detalle completo
        va por correo y por la consola.

        No dice "factura": no lo es, y aparentarlo sería inducir a error (art. 30).
        """
        try:
            monto = f"${int(round(float(total or 0))):,}".replace(",", ".")
        except (TypeError, ValueError):
            monto = "—"
        pago = "contra entrega" if (forma_pago or "") == "cod" else "pago en línea"
        return (
            f"📄 *Comprobante {numero}*\n"
            f"Total: *{monto}* COP · {pago}\n\n"
            f"Es tu comprobante de compra. Guárdalo para cualquier reclamo o garantía."
        )

    async def _send_receipt_acks(self) -> None:
        """Le remite al comprador el acuse de su comprobante.

        Ley 1480 art. 50 lit. d) habla de REMITIR el acuse, no de tenerlo disponible:
        emitirlo y dejarlo en una tabla no cumple nada.

        WhatsApp es el canal primario por COBERTURA, no por estética — `contacts.phone`
        es NOT NULL mientras `contacts.email` es opcional, y el envío de correo se salta
        en silencio cuando no hay dirección. Llega al 100% de los compradores.

        Fuera de la ventana de servicio de Meta no se puede escribir free-form y las
        plantillas están diferidas: se marca el motivo en vez de intentar y fallar con un
        error opaco. Un acuse que nunca sale no puede ser indistinguible de uno pendiente.
        """
        if not self._receipt_ack_enabled:
            return
        try:
            pendientes = self.supabase.rpc(
                "rpc_find_receipts_pending_ack",
                {"p_csw_hours": META_CSW_HOURS, "p_limit": RECEIPT_BATCH},
            ).execute().data or []
        except Exception as exc:
            logger.warning("[COMPROBANTE] no pude buscar acuses pendientes: %s", exc)
            return

        for r in pendientes:
            receipt_id, tenant_id = r.get("receipt_id"), r.get("tenant_id")
            conv_id = r.get("conversation_id")
            if not (receipt_id and tenant_id and conv_id):
                continue

            if not r.get("dentro_de_csw"):
                self._metrics["receipt_acks_out_of_window"] += 1
                logger.warning(
                    "[COMPROBANTE] %s sin remitir: fuera de la ventana de 24h de Meta. "
                    "Queda disponible en la consola y por correo.", r.get("numero"),
                )
                self._marcar_acuse(receipt_id, tenant_id, None, "fuera_de_ventana_csw")
                continue

            texto = self._texto_acuse(r.get("numero"), r.get("total"), r.get("forma_pago"))
            try:
                conv = (
                    self.supabase.table("conversations")
                    .select("customer_phone")
                    .eq("id", conv_id).eq("tenant_id", tenant_id)
                    .limit(1).execute()
                )
                telefono = (conv.data or [{}])[0].get("customer_phone")
                if not telefono:
                    self._marcar_acuse(receipt_id, tenant_id, None, "sin_telefono")
                    continue
                meta_id = await send_whatsapp_message(
                    tenant_id=tenant_id, supabase=self.supabase,
                    to_phone=telefono, text=texto,
                )
            except Exception as exc:
                logger.error("[COMPROBANTE] fallo remitiendo %s: %s", r.get("numero"), exc)
                continue

            if not meta_id:
                # No se marca nada: el próximo barrido reintenta. Un acuse tiene plazo
                # legal, así que darlo por perdido en el primer fallo sería peor.
                logger.error("[COMPROBANTE] %s no salió — se reintenta", r.get("numero"))
                continue

            if not self._marcar_acuse(receipt_id, tenant_id, "whatsapp", None):
                # Otro tick ganó la carrera: no re-persistir el mensaje.
                continue

            self._metrics["receipt_acks_sent"] += 1
            try:
                self.supabase.table("messages").insert({
                    "conversation_id": conv_id,
                    "tenant_id": tenant_id,
                    "direction": "outbound",
                    "content_type": "text",
                    "content": texto,
                    "meta_message_id": meta_id,
                    "processed": True,
                    "processing_status": "processed",
                }).execute()
            except Exception as exc:
                logger.warning("[COMPROBANTE] acuse enviado pero no persistido: %s", exc)

    async def _send_receipt_emails(self) -> None:
        """Le manda al comprador el DETALLE COMPLETO del comprobante por correo.

        Es un barrido HERMANO del acuse por WhatsApp, no un paso dentro de él, y la razón
        es concreta: el barrido de acuses excluye las filas con `ack_skipped_reason` y las
        que no tienen conversación — que son exactamente la población que el correo viene
        a rescatar. Hasta ahora el worker prometía "queda disponible por correo" sobre
        filas que habían quedado fuera para siempre.

        Los dos canales son independientes a propósito: un comprobante puede haber llegado
        por uno y no por el otro, y el estado tiene que poder decirlo.
        """
        if not self._receipt_email_enabled:
            return
        if not hasattr(self.supabase, "rpc"):
            return

        try:
            pendientes = self.supabase.rpc(
                "rpc_find_receipts_pending_email", {"p_limit": RECEIPT_BATCH},
            ).execute().data or []
        except Exception as exc:
            logger.warning("[COMPROBANTE][EMAIL] no pude buscar pendientes: %s", exc)
            return

        for r in pendientes:
            receipt_id, tenant_id = r.get("receipt_id"), r.get("tenant_id")
            if not (receipt_id and tenant_id):
                continue

            destinatario = r.get("email")
            if not destinatario:
                # No es un fallo: es un hecho del comprador. Se marca con motivo para que
                # no quede pendiente para siempre, y el acuse de WhatsApp ya lo cubrió.
                self._marcar_email(receipt_id, tenant_id, None, "comprador_sin_correo")
                continue

            try:
                from receipt_email import send_receipt_email  # noqa: PLC0415
                ok = await send_receipt_email(
                    receipt_id=receipt_id, tenant_id=tenant_id,
                    numero=r.get("numero"), snapshot=r.get("snapshot") or {},
                    destinatario=destinatario,
                    politica=self._politica_cancelacion(tenant_id),
                    # Del SNAPSHOT, no del tenant vivo: el comprobante debe apuntar al
                    # correo que el vendedor tenía cuando se emitió.
                    responder_a=((r.get("snapshot") or {}).get("vendedor") or {}).get("email"),
                )
            except Exception as exc:
                logger.error("[COMPROBANTE][EMAIL] fallo enviando %s: %s", r.get("numero"), exc)
                self._metrics["receipt_emails_failed"] += 1
                continue

            if not ok:
                # No se marca: el próximo barrido reintenta. Un comprobante tiene plazo
                # legal, así que darlo por perdido en el primer fallo sería peor.
                self._metrics["receipt_emails_failed"] += 1
                logger.error("[COMPROBANTE][EMAIL] %s no salió — se reintenta", r.get("numero"))
                continue

            if self._marcar_email(receipt_id, tenant_id, destinatario, None):
                self._metrics["receipt_emails_sent"] += 1
                logger.info("[COMPROBANTE][EMAIL] %s enviado", r.get("numero"))

    def _politica_cancelacion(self, tenant_id: str) -> dict:
        """Condiciones de retracto del tenant. Se LEEN, no se hardcodean: son
        configurables por comerciante. Los mínimos de ley los aplica el renderizador."""
        try:
            res = (
                self.supabase.table("tenant_cancellation_policy")
                .select("enable_retracto_flow, retracto_window_business_days, "
                        "retracto_return_paid_by, manual_refund_legal_days")
                .eq("tenant_id", tenant_id)
                .limit(1).execute()
            )
            return (res.data or [{}])[0]
        except Exception as exc:
            logger.warning("[COMPROBANTE][EMAIL] sin política de cancelación de %s: %s",
                           str(tenant_id)[:8], exc)
            return {}

    def _marcar_email(self, receipt_id, tenant_id, email_to, motivo) -> bool:
        """True si esta corrida fue la que marcó. Espejo de `_marcar_acuse`."""
        try:
            res = self.supabase.rpc("rpc_mark_receipt_email", {
                "p_receipt_id": receipt_id, "p_tenant_id": tenant_id,
                "p_email": email_to, "p_skipped": motivo,
            }).execute()
            return bool(res.data)
        except Exception as exc:
            logger.error("[COMPROBANTE][EMAIL] no pude marcar %s: %s", receipt_id, exc)
            return False

    def _marcar_acuse(self, receipt_id, tenant_id, canal, motivo) -> bool:
        """True si esta corrida fue la que marcó. False si otra ya lo había hecho."""
        try:
            res = self.supabase.rpc("rpc_mark_receipt_ack", {
                "p_receipt_id": receipt_id, "p_tenant_id": tenant_id,
                "p_channel": canal, "p_skipped": motivo,
            }).execute()
            return bool(res.data)
        except Exception as exc:
            logger.error("[COMPROBANTE] no pude marcar el acuse de %s: %s", receipt_id, exc)
            return False

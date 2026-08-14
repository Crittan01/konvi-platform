"""Gates determinísticos pre-LLM del dispatcher agentic (extraído de
agentic/dispatcher.py — G12). Decisiones binarias que NO pasan por el modelo:
opt-out/re-optin Habeas Data, derechos ARCO (export/rectify/erase), detección
de menor de edad, escalación a humano y handoff del router determinístico.

Extraído verbatim 2026-08-13 — comportamiento idéntico. Los lazy imports
`from orchestrator import ...` dentro de estas funciones se movieron con ellas
(el ciclo orchestrator↔dispatcher sigue gestionado igual — ver G15 en PLAN).
dispatcher.py los re-importa a su namespace (callers/tests intactos).
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_contact_id(supabase: Any, tenant_id: str, conversation_id: str):
    """Resuelve el contact_id de una conversación (None si no se encuentra).

    F2: `conversations` NO tiene columna contact_id — el vínculo canónico es
    customer_phone → contacts.phone (patrón rev.104, orchestrator.py:1942). La versión
    previa consultaba conversations.contact_id → APIError 400 silenciado → SIEMPRE None →
    mi F6 self-service (Art.14) nunca corría y el paper-trail quedaba con contact_id NULL.
    """
    try:
        conv = (
            supabase.table("conversations").select("customer_phone")
            .eq("id", conversation_id).eq("tenant_id", tenant_id)
            .limit(1).execute()
        )
        phone = ((conv.data or [{}])[0].get("customer_phone") or "").lstrip("+")
        if not phone:
            return None
        ctc = (
            supabase.table("contacts").select("id")
            .eq("tenant_id", tenant_id)
            .or_(f"phone.eq.{phone},phone.eq.+{phone}")
            .limit(1).execute()
        )
        return (ctc.data or [{}])[0].get("id")
    except Exception:
        return None


def _log_habeas_event(
    supabase: Any, *, tenant_id: str, conversation_id: str, event: str, evidence: dict,
) -> None:
    """Registra un evento Habeas Data en consent_audit_log (append-only, Ley 1581) — el registro
    canónico para la SIC. Best-effort: NO bloquea la escalación (la seguridad es escalar; esto es el
    paper-trail). Resuelve contact_id de la conversación (nullable si no se encuentra)."""
    try:
        # F2: resolver por customer_phone→contacts (conversations no tiene contact_id).
        contact_id = _resolve_contact_id(supabase, tenant_id, conversation_id)
        supabase.table("consent_audit_log").insert({
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "event": event,
            "source": "whatsapp",
            "conversation_id": conversation_id,
            "evidence": evidence,
        }).execute()
    except Exception as exc:
        logger.warning(
            "[HABEAS_DATA] consent_audit_log(%s) insert falló conv=%s: %s",
            event, conversation_id, exc,
        )


async def _handle_data_rights_if_intent(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> bool:
    """Habeas Data Ley 1581 (palanca 3): si el mensaje es una solicitud de derechos
    de datos NO-keyword ("borren mis datos", "retiro mi consentimiento", "derecho al
    olvido"), garantiza el side-effect seguro: ESCALA a humano + ACUSA recibo. NO
    auto-ejecuta borrados (un DSR exige verificación + plazo legal; lo tramita un
    asesor vía data_subject_request). Retorna True si procesó → el caller NO avanza al
    LLM. Determinístico: no depende de que el LLM lo maneje bien."""
    if content_type != "text":
        return False
    from lib.habeas_data_request import (
        detect_data_rights_request, DATA_RIGHTS_ACK_TEXT,
    )
    matched = detect_data_rights_request(content)
    if not matched:
        return False
    from lib.habeas_data_request import classify_data_rights_request
    kind = classify_data_rights_request(content) or "suppression"

    from orchestrator import (
        _send_outbound_text, _mark_message_processing, PROCESSING_STATUS_PROCESSED,
    )

    # ── Art. 14 (ACCESO) → SELF-SERVICE: el bot responde con el resumen ENMASCARADO
    #    de los datos del titular (decisión founder Opción A). NO escala — lo resuelve
    #    el bot. El resumen enmascara teléfono/documento; el reporte completo se pide
    #    formalmente al tenant. Si no hay contacto resoluble, cae a escalación (no
    #    exponer datos sin titular claro).
    if kind == "access":
        contact_id = _resolve_contact_id(supabase, tenant_id, conversation_id)
        if contact_id:
            _log_habeas_event(
                supabase, tenant_id=tenant_id, conversation_id=conversation_id,
                event="export_request",
                evidence={
                    "message_text": content[:200],
                    "matched_phrase": matched[:120],
                    "gate": "agentic.dispatcher._handle_data_rights_if_intent",
                    "kind": "access",
                    "action": "self_service_masked_summary",
                },
            )
            try:
                from orchestrator import _build_customer_data_summary
                summary = _build_customer_data_summary(supabase, contact_id, tenant_id)
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id,
                    tenant_id=tenant_id, text=summary,
                )
            except Exception as exc:
                logger.error(
                    "[HABEAS_DATA] resumen self-service Art.14 falló conv=%s: %s",
                    conversation_id, exc,
                )
            try:
                _mark_message_processing(
                    supabase, tenant_id, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
            except Exception:
                pass
            logger.info(
                "[HABEAS_DATA] acceso Art.14 self-service conv=%s contact=%s",
                (conversation_id or "?")[:8], contact_id[:8],
            )
            return True

    # ── Supresión / rectificación (o acceso sin contacto) → ESCALAR + paper-trail.
    # Un borrado (Art.15/16) exige verificación de identidad + plazo legal; una
    # rectificación (Art.16) NO se auto-edita desde el chat. Lo tramita un asesor.
    _log_habeas_event(
        supabase, tenant_id=tenant_id, conversation_id=conversation_id,
        event="data_rights_request",
        evidence={
            "message_text": content[:200],
            "matched_phrase": matched[:120],
            "gate": "agentic.dispatcher._handle_data_rights_if_intent",
            "kind": kind,
            "action": "escalated_human_takeover",
        },
    )
    # 1. Acuse de recibo al cliente (Ley 1581: confirmar que se registró).
    try:
        await _send_outbound_text(
            supabase=supabase, conversation_id=conversation_id,
            tenant_id=tenant_id, text=DATA_RIGHTS_ACK_TEXT,
        )
    except Exception as exc:
        logger.error("[HABEAS_DATA] send ack falló conv=%s: %s", conversation_id, exc)
    # 2. Escalar a humano. FAIL-SAFE (auditoría 2026-06-26 #2): si el UPDATE
    # falla, reintentar una vez; si igual falla, log CRITICAL + la notificación
    # le pide al operador PAUSA MANUAL. NO dejar la conversación activa
    # silenciosamente tras un DSR (sería incumplir la promesa Ley 1581).
    status_set = False
    for _attempt in range(2):
        try:
            supabase.table("conversations").update({
                "status": "human_takeover",
            }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
            status_set = True
            break
        except Exception as exc:
            logger.warning(
                "[HABEAS_DATA] status update intento %d falló: %s", _attempt + 1, exc,
            )
    if not status_set:
        logger.critical(
            "[HABEAS_DATA] NO se pudo pausar la conversación conv=%s tras DSR — "
            "requiere PAUSA MANUAL del operador (Ley 1581)", conversation_id,
        )
    # 3. Notificar al operador — INDEPENDIENTE del status (es la señal de escalación).
    _pause_warn = "" if status_set else (
        "\n⚠️ *La auto-pausa del bot FALLÓ — pausa esta conversación MANUALMENTE ya.*"
    )
    try:
        from telegram_notifications import notify_escalation_async
        await notify_escalation_async(
            supabase, tenant_id=tenant_id, conversation_id=conversation_id,
            reason=(
                f"⚖️ *Solicitud Habeas Data (Ley 1581)*\n"
                f"El cliente pidió ejercer derechos sobre sus datos: "
                f"«{matched[:120]}».\n\nConversación pasó a human_takeover. "
                f"Acción: tramitar el DSR (data_subject_request) + responder al cliente."
                f"{_pause_warn}"
            ),
            severity="critical",
        )
    except Exception as exc:
        logger.warning("[HABEAS_DATA] telegram notif falló: %s", exc)
    # 4. Marcar procesado — NO avanzar al LLM.
    try:
        _mark_message_processing(
            supabase, tenant_id, message_id,
            processing_status=PROCESSING_STATUS_PROCESSED,
        )
    except Exception:
        pass
    logger.info(
        "[HABEAS_DATA] DSR detectado conv=%s phrase=%r → escalado a humano",
        (conversation_id or "?")[:8], matched[:80],
    )
    return True


async def _handle_minor_intent_if_applicable(
    supabase,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> bool:
    """Decreto 1377/2013 Art. 7 (PRIORIDAD MÁXIMA): si el cliente declara/sugiere ser MENOR de edad, el
    tratamiento de sus datos sin autorización del representante legal es ILEGAL → NO se continúa NINGÚN flujo
    comercial. Responde pidiendo el representante + escala a humano (operador adulto valida identidad) +
    notifica. Determinístico (pre-LLM), espejo del gate data-rights. Retorna True → el caller NO avanza al LLM.

    Portado del path legacy (orchestrator.py:7758) que en el path AGENTIC no corría → un menor autodeclarado
    seguía siendo atendido por el bot (gap de cumplimiento). El human_takeover_at lo estampa el trigger DB."""
    if content_type != "text":
        return False
    from safety.consent_gates import detect_minor_intent
    if not detect_minor_intent(content):
        return False

    # 0. Paper-trail Ley 1581 / Decreto 1377 Art. 7: registrar la detección de menor.
    _log_habeas_event(
        supabase, tenant_id=tenant_id, conversation_id=conversation_id,
        event="minor_detected",
        evidence={
            "message_text": content[:200],
            "gate": "agentic.dispatcher._handle_minor_intent_if_applicable",
            "legal_basis": "Decreto 1377/2013 Art. 7",
            "action": "escalated_human_takeover",
        },
    )

    from orchestrator import (
        _send_outbound_text, _mark_message_processing, PROCESSING_STATUS_PROCESSED,
    )
    minor_text = (
        "Por nuestra política de protección de datos no podemos continuar con la compra directamente "
        "contigo (Habeas Data Ley 1581/2012, Decreto 1377 Art. 7). Necesitamos que tu padre, madre o "
        "tutor legal nos escriba a este chat para autorizar la operación. Mientras tanto, un asesor del "
        "equipo te contactará si lo necesitas."
    )
    # 1. Responder al cliente (cordial, cita legal).
    try:
        await _send_outbound_text(
            supabase=supabase, conversation_id=conversation_id,
            tenant_id=tenant_id, text=minor_text,
        )
    except Exception as exc:
        logger.error("[MINOR] send falló conv=%s: %s", conversation_id, exc)
    # 2. Escalar a humano (fail-safe con reintento — no dejar al bot atendiendo a un menor). El trigger
    #    stamp_human_takeover_at pone human_takeover_at automáticamente.
    status_set = False
    for _attempt in range(2):
        try:
            supabase.table("conversations").update({
                "status": "human_takeover",
            }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
            status_set = True
            break
        except Exception as exc:
            logger.warning("[MINOR] status update intento %d falló: %s", _attempt + 1, exc)
    if not status_set:
        logger.critical(
            "[MINOR] NO se pudo pausar la conversación conv=%s tras detectar menor — "
            "requiere PAUSA MANUAL del operador (Decreto 1377 Art. 7)", conversation_id,
        )
    # 3. Notificar al operador (INDEPENDIENTE del status).
    _pause_warn = "" if status_set else (
        "\n⚠️ *La auto-pausa del bot FALLÓ — pausa esta conversación MANUALMENTE ya.*"
    )
    try:
        from telegram_notifications import notify_escalation_async
        await notify_escalation_async(
            supabase, tenant_id=tenant_id, conversation_id=conversation_id,
            reason=(
                f"🚸 *Menor de edad autodeclarado (Decreto 1377/2013 Art. 7)*\n"
                f"El cliente declaró/sugirió ser menor: «{content[:120]}».\n\nConversación pasó a "
                f"human_takeover. Acción: validar identidad del representante legal antes de continuar."
                f"{_pause_warn}"
            ),
            severity="critical",
        )
    except Exception as exc:
        logger.warning("[MINOR] telegram notif falló: %s", exc)
    # 4. Marcar procesado — NO avanzar al LLM.
    try:
        _mark_message_processing(
            supabase, tenant_id, message_id,
            processing_status=PROCESSING_STATUS_PROCESSED,
        )
    except Exception:
        pass
    logger.info("[MINOR] menor detectado conv=%s → escalado a humano", (conversation_id or "?")[:8])
    return True


async def _escalate_conversation_to_human(
    supabase: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    reason: str,
) -> None:
    """Marca conversation.status='human_takeover' + audit + notifica al equipo.

    F5 bot_engine #3 — reusa el patrón canónico del tool escalate_to_human
    (agentic/tools/escalation.py) para el path no-texto (document). Best-effort:
    ni el audit ni la notificación bloquean; el cambio de status es lo crítico.
    """
    try:
        supabase.table("conversations").update({
            "status": "human_takeover",
        }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
    except Exception as exc:
        logger.warning(
            "[NONTEXT_ESCALATE] conv=%s no pude marcar human_takeover: %s",
            conversation_id[:8], exc,
        )
        return
    try:
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "escalation_audit",
            "content": "",
            "payload": {"reason": reason, "source": "nontext_dispatch"},
            "processed": True,
            "processing_status": "processed",
        }).execute()
    except Exception:
        pass
    try:
        from telegram_notifications import notify_escalation_async
        await notify_escalation_async(
            supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            reason=reason,
        )
    except Exception:
        pass


async def _consume_router_handoff(
    supabase: Any, tenant_id: str, conversation_id: str,
) -> bool:
    """A8 — Side-effect REAL del handoff sintético del agent_router.

    Cuando el router clasifica un inbound para un rol que NINGÚN agente del
    tenant cubre, devuelve `_HANDOFF_SYNTHETIC_AGENT` con `_needs_human_handoff`.
    Este helper materializa la escalación (mismo patrón que la tool
    escalate_to_human y FakeEscalationInvariant): status=human_takeover + audit
    append-only + notificar operador. Retorna True si marcó takeover.
    """
    _reason = (
        "Consulta fuera del alcance de los agentes configurados — "
        "requiere asesor humano (router handoff)."
    )
    try:
        supabase.table("conversations").update({
            "status": "human_takeover",
        }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
    except Exception as exc:
        logger.error(
            "[AGENTIC_DISPATCH] handoff sintético: error marcando status "
            "conv=%s: %s — operador podría NO ser notificado",
            (conversation_id or "?")[:8], exc,
        )
        return False

    # Audit append-only (no bloquea — status ya cambiado).
    try:
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "escalation_audit",
            "content": "",
            "payload": {"reason": _reason, "source": "agent_router_handoff"},
            "processed": True,
            "processing_status": "processed",
        }).execute()
    except Exception:
        pass

    # Notificar operador (best-effort; Path B DB-trigger→pgmq→worker respalda).
    try:
        from telegram_notifications import notify_escalation_async
        await notify_escalation_async(
            supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            reason=_reason,
        )
    except Exception:
        pass
    return True


async def _handle_optout_if_keyword(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> bool:
    """Detecta STOP/BAJA/CANCELAR/UNSUBSCRIBE/... y procesa opt-out completo.

    Migración del path legacy `orchestrator.py:6924-7010` al dispatcher
    agentic. Mismo patrón:
      1. Detect via `is_optout_keyword`.
      2. `soft_revoke_consent` en contacts (consent_revoked_at=NOW).
      3. `_log_consent_event` para audit Habeas Data.
      4. `mark_conversation_opted_out` (status='opted_out').
      5. Enviar OPTOUT_CONFIRMATION_TEXT al cliente vía WhatsApp.
      6. Persistir el outbound en messages para Inbox.
      7. Marcar message inbound como processed (no re-loop).

    Returns True si procesó opt-out (caller debe NO avanzar al LLM).
    Returns False si no era keyword (caller sigue al LLM normal).
    """
    if content_type != "text":
        return False
    try:
        from lib.whatsapp_optout import (  # noqa: PLC0415
            OPTOUT_CONFIRMATION_TEXT,
            is_optout_keyword,
            mark_conversation_opted_out,
            soft_revoke_consent,
        )
    except Exception:
        # Lib no disponible (migración faltante) — degradar silent.
        return False

    if not is_optout_keyword(content):
        return False

    # Resolver contact_id + phone para la conv.
    try:
        conv_res = (
            supabase.table("conversations")
            .select("customer_phone")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if not (conv_res.data or []):
            return False
        customer_phone = conv_res.data[0].get("customer_phone") or ""
        if not customer_phone:
            return False

        contact_res = (
            supabase.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", customer_phone)
            .limit(1)
            .execute()
        )
        contact_id = (contact_res.data or [{}])[0].get("id")
        if not contact_id:
            # Sin contact en DB → no podemos revocar. Procesar como mensaje
            # normal (raro pero posible si el connector no creó el contact).
            return False
    except Exception as exc:
        logger.warning("[OPTOUT_GATE] lookup conv/contact falló: %s", exc)
        return False

    # DESAMBIGUACIÓN de keywords ambiguas ("cancelar", "salir").
    # En un canal de COMPRA, un cliente con un pedido vivo que escribe "Cancelar" casi siempre
    # quiere cancelar SU PEDIDO, no dejar de recibir mensajes. Tratarlo como opt-out lo dejaba
    # MUDO DE POR VIDA (solo revive con SUSCRIBIR/START/REACTIVAR, que nadie adivina) y encima
    # su pedido seguía vivo — el peor de los dos mundos.
    # Con un pedido activo, se deja pasar el mensaje al bot, que atiende la intención real.
    # Las keywords INEQUÍVOCAS (STOP, BAJA, UNSUBSCRIBE, "cancelar suscripción"...) siguen dando
    # de baja siempre, así que el derecho del titular a revocar NO se pierde.
    try:
        from lib.whatsapp_optout import is_ambiguous_optout_keyword  # noqa: PLC0415

        if is_ambiguous_optout_keyword(content):
            activa = (
                supabase.table("orders")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("conversation_id", conversation_id)
                .not_.in_("status", ["cancelled", "delivered"])
                .limit(1)
                .execute()
            )
            if activa.data:
                logger.info(
                    "[OPTOUT_GATE] '%s' con pedido activo conv=%s — NO se da de baja, "
                    "se deja que el bot atienda la intención (probablemente cancelar el pedido)",
                    content.strip()[:20], conversation_id[:8],
                )
                return False
    except Exception as exc:  # noqa: BLE001
        # Ante duda, se conserva el comportamiento previo (dar de baja): es la dirección segura
        # para Habeas Data — nunca ignorar una posible revocación por un fallo de lookup.
        logger.warning("[OPTOUT_GATE] chequeo de pedido activo falló (se procesa la baja): %s", exc)

    logger.info(
        "[OPTOUT_GATE] STOP detectado msg=%s conv=%s contact=%s",
        message_id[:8], conversation_id[:8], contact_id[:8] if contact_id else "?",
    )

    # 1. Revoca consent.
    try:
        soft_revoke_consent(
            supabase,
            tenant_id=tenant_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            phone=customer_phone,
        )
    except Exception as exc:
        logger.error("[OPTOUT_GATE] soft_revoke_consent falló: %s", exc)
        return False

    # 2. Audit log Habeas Data Art. 9 trail (opcional — si falla no rompe).
    try:
        from orchestrator import _log_consent_event  # noqa: PLC0415
        _log_consent_event(
            supabase,
            tenant_id=tenant_id,
            contact_id=contact_id,
            phone=customer_phone,
            event="revoked",
            source="whatsapp",
            conversation_id=conversation_id,
            evidence={
                "trigger": "stop_keyword",
                "keyword_matched": content.strip().lower(),
                "rev": "109_dispatcher_gate",
                "path": "agentic_dispatcher",
            },
        )
    except Exception as exc:
        logger.warning("[OPTOUT_GATE] audit log falló (no crítico): %s", exc)

    # 3. Marca conv opted_out (visibilidad UI Inbox).
    try:
        mark_conversation_opted_out(
            supabase,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("[OPTOUT_GATE] mark_conversation_opted_out falló: %s", exc)

    # 4. Envía confirmación canónica al cliente.
    try:
        from whatsapp_sender import send_whatsapp_message  # noqa: PLC0415
        meta_msg_id = await send_whatsapp_message(
            tenant_id=tenant_id,
            supabase=supabase,
            to_phone=customer_phone,
            text=OPTOUT_CONFIRMATION_TEXT,
        )
    except Exception as exc:
        logger.error("[OPTOUT_GATE] send confirmación falló: %s", exc)
        meta_msg_id = None

    # 5. Persistir outbound en messages para que aparezca en Inbox.
    try:
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "text",
            "content": OPTOUT_CONFIRMATION_TEXT,
            "meta_message_id": meta_msg_id,
            "processed": True,
            "processing_status": "processed",
        }).execute()
    except Exception as exc:
        logger.error("[OPTOUT_GATE] persist outbound falló: %s", exc)

    # 6. Marcar message inbound como processed (no re-loop).
    try:
        supabase.table("messages").update({
            "processing_status": "processed",
            "processed": True,
        }).eq("id", message_id).eq("tenant_id", tenant_id).execute()
    except Exception as exc:
        logger.warning("[OPTOUT_GATE] mark inbound processed falló: %s", exc)

    return True


async def _handle_reoptin_if_keyword(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> bool:
    """Detecta START/SUSCRIBIR/REACTIVAR y procesa re-opt-in (FINDING-A 2026-06-25).

    Cierra la promesa de OPTOUT_CONFIRMATION_TEXT ("escríbenos cuando quieras"):
    un contacto opted_out queda atascado porque el gate de status lo skipea.
    Espejo de `_handle_optout_if_keyword`:
      1. is_optin_keyword(content).
      2. Resolver contact_id + phone.
      3. SOLO procede si la conv está 'opted_out' (un 'start' en conv activa →
         return False, deja al LLM responder).
      4. restore_consent (limpia consent_revoked_at — obligatorio, ver lib).
      5. _log_consent_event(event='granted') — Habeas Data Art.9 re-consent.
         (event='granted', NO 'reoptin': el CHECK de consent_audit_log solo
         permite {granted,revoked,rectified,export_request,portability,pii_access}.)
      6. conv.status → 'bot_active'.
      7. Enviar OPTIN_CONFIRMATION_TEXT + persistir outbound + mark processed.

    Returns True si procesó re-opt-in (caller NO avanza al LLM).
    Returns False si no aplica (caller sigue su flujo normal → skip/LLM).
    """
    if content_type != "text":
        return False
    try:
        from lib.whatsapp_optout import (  # noqa: PLC0415
            CONVERSATION_STATUS_BOT_ACTIVE,
            OPTIN_CONFIRMATION_TEXT,
            is_optin_keyword,
            restore_consent,
        )
    except Exception:
        return False

    if not is_optin_keyword(content):
        return False

    # Resolver conv (status + phone) + contact_id.
    try:
        conv_res = (
            supabase.table("conversations")
            .select("status, customer_phone")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        conv_row = (conv_res.data or [{}])[0]
        # SOLO re-opt-in si la conv está actualmente opted_out. Un 'start' en
        # una conv activa es un mensaje normal → return False (lo maneja el LLM).
        if conv_row.get("status") != "opted_out":
            return False
        customer_phone = conv_row.get("customer_phone") or ""
        if not customer_phone:
            return False

        contact_res = (
            supabase.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", customer_phone)
            .limit(1)
            .execute()
        )
        contact_id = (contact_res.data or [{}])[0].get("id")
        if not contact_id:
            return False
    except Exception as exc:
        logger.warning("[REOPTIN_GATE] lookup conv/contact falló: %s", exc)
        return False

    logger.info(
        "[REOPTIN_GATE] re-opt-in detectado msg=%s conv=%s contact=%s",
        message_id[:8], conversation_id[:8], contact_id[:8],
    )

    # 1. Restaurar consent (limpia consent_revoked_at — obligatorio para que el
    # connector NO re-fuerce opted_out en el próximo inbound).
    try:
        ok = restore_consent(
            supabase,
            tenant_id=tenant_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
        )
        if not ok:
            logger.error("[REOPTIN_GATE] restore_consent no actualizó filas")
            return False
    except Exception as exc:
        logger.error("[REOPTIN_GATE] restore_consent falló: %s", exc)
        return False

    # 2. Audit Habeas Data Art.9 (re-consent explícito). event='granted'.
    try:
        from orchestrator import _log_consent_event  # noqa: PLC0415
        _log_consent_event(
            supabase,
            tenant_id=tenant_id,
            contact_id=contact_id,
            phone=customer_phone,
            event="granted",
            source="whatsapp",
            conversation_id=conversation_id,
            evidence={
                "trigger": "reoptin_keyword",
                "keyword_matched": content.strip().lower(),
                "path": "agentic_dispatcher",
            },
        )
    except Exception as exc:
        logger.warning("[REOPTIN_GATE] audit log falló (no crítico): %s", exc)

    # 3. Reactivar conv (status → bot_active).
    try:
        supabase.table("conversations").update({
            "status": CONVERSATION_STATUS_BOT_ACTIVE,
        }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
    except Exception as exc:
        logger.error("[REOPTIN_GATE] reactivar conv falló: %s", exc)

    # 4. Confirmación al cliente.
    try:
        from whatsapp_sender import send_whatsapp_message  # noqa: PLC0415
        meta_msg_id = await send_whatsapp_message(
            tenant_id=tenant_id,
            supabase=supabase,
            to_phone=customer_phone,
            text=OPTIN_CONFIRMATION_TEXT,
        )
    except Exception as exc:
        logger.error("[REOPTIN_GATE] send confirmación falló: %s", exc)
        meta_msg_id = None

    # 5. Persistir outbound en messages (Inbox).
    try:
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "text",
            "content": OPTIN_CONFIRMATION_TEXT,
            "meta_message_id": meta_msg_id,
            "processed": True,
            "processing_status": "processed",
        }).execute()
    except Exception as exc:
        logger.error("[REOPTIN_GATE] persist outbound falló: %s", exc)

    # 6. Marcar inbound processed.
    try:
        supabase.table("messages").update({
            "processing_status": "processed",
            "processed": True,
        }).eq("id", message_id).eq("tenant_id", tenant_id).execute()
    except Exception as exc:
        logger.warning("[REOPTIN_GATE] mark inbound processed falló: %s", exc)

    return True

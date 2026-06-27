"""Dispatcher legacy ↔ agentic.

ADR-0018 Fase B + C. Punto único donde el worker decide:

  • Si tenant.agentic_enabled=True (Fase C cutover) → invoca agentic full
    (envía outbound al cliente).
  • Si AGENTIC_SHADOW_ENABLED=True (Fase B shadow) → invoca agentic
    SILENCIOSAMENTE en paralelo + loggea para comparar con legacy.
    Legacy responde al cliente.
  • Else → solo legacy (default, comportamiento pre-refactor).

Production-grade:
  • Errores del agentic NUNCA afectan al cliente (legacy responde igual).
  • Shadow mode timeout = 30s (no bloquea polling cycle).
  • Audit log completo: TODO turn agentic (shadow + cutover) se persiste
    en `agentic_shadow_log` con `mode='shadow'|'cutover'` (rev. 107 cierre
    arquitectónico — antes cutover solo emitía a stdout y los logs rotaban).
    Helper único: `_persist_turn_audit()`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Feature flags operativos.
AGENTIC_SHADOW_ENABLED = os.getenv("AGENTIC_SHADOW_ENABLED", "false").lower() == "true"
AGENTIC_SHADOW_TIMEOUT_S = float(os.getenv("AGENTIC_SHADOW_TIMEOUT_S", "30"))


async def is_tenant_agentic_enabled(supabase: Any, tenant_id: str) -> bool:
    """Lee `tenant_integrations.meta.agentic_enabled` del row dedicado
    `provider='agentic'` del tenant.

    Default False si el row no existe (preserva backward compat — sin
    activación explícita, comportamiento legacy).

    Diseño: usamos un row dedicado por provider='agentic' (consistente
    con el patrón whatsapp/wompi/envia/meli existente) en lugar de
    mezclar el flag en meta de otro provider. Esto evita race
    conditions en updates concurrentes a meta de otros providers.
    """
    try:
        res = (
            supabase.table("tenant_integrations")
            .select("meta")
            .eq("tenant_id", tenant_id)
            .eq("provider", "agentic")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return False
        meta = rows[0].get("meta") or {}
        return bool(meta.get("agentic_enabled"))
    except Exception as exc:
        logger.warning(
            "[AGENTIC_DISPATCH] error leyendo flag tenant=%s: %s — default False",
            tenant_id, exc,
        )
        return False


try:
    from observability import track_op as _track_op
except Exception:
    def _track_op(*args, **kwargs):  # noqa
        def decorator(f):
            return f
        return decorator


@_track_op("agentic.dispatch_message")
async def dispatch_message(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """Punto único de dispatch. Decide legacy/agentic/shadow basado en flags.

    NO retorna nada — el outbound se envía dentro del path elegido.

    Comportamiento:
      0. Si conv.status ∈ {human_takeover, closed} → SKIP (gate previo
         a cualquier path). El operador tomó la conversación o ya cerró
         — el bot debe permanecer en silencio total.
      1. Si tenant.agentic_enabled=True → agentic FULL (envía outbound).
      2. Elif AGENTIC_SHADOW_ENABLED=True → legacy responde al cliente +
         agentic shadow corre en paralelo y loggea silenciosamente.
      3. Else → solo legacy.
    """
    # Re-opt-in gate (FINDING-A 2026-06-25) — DEBE correr ANTES del skip de
    # status: 'opted_out' ∈ _SKIP_STATUSES, así que un cliente que envía
    # START/SUSCRIBIR/REACTIVAR sería skipped sin reactivarse jamás (la
    # confirmación de opt-out le prometió poder volver). Habeas Data Art.9:
    # re-consent explícito vía keyword inequívoco.
    try:
        if await _handle_reoptin_if_keyword(
            supabase,
            message_id=message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content=content,
            content_type=content_type,
        ):
            return
    except Exception as exc:
        logger.warning("[REOPTIN_GATE] error en reoptin handler: %s", exc)
        # FAIL-SAFE: si era keyword de re-optin y falló, NO reactivar — la conv
        # sigue opted_out → skip natural abajo. Sin re-engagement accidental.

    # Gate de conversation status — rev. 107 cierre runtime KAIU 2026-05-23.
    # El bot legacy ya tenía este gate en orchestrator.py:6754, pero el
    # agentic dispatcher saltaba al `_run_agentic_full` SIN verificar.
    # Resultado: bot respondía a mensajes en conv human_takeover/closed
    # sobre-escribiendo la intervención del operador.
    if _should_skip_for_conv_status(supabase, tenant_id, conversation_id):
        _mark_message_skipped(supabase, tenant_id, message_id)
        return

    # Rev. 109 founder 2026-05-29 — Opt-out STOP gate (Habeas Data Ley 1581 ART. 9 +
    # Meta Business Policy). ANTES estaba SOLO en orchestrator.py:6932 path legacy.
    # KAIU usa agentic → el detector NUNCA disparaba. Detectado en UAT exhaustivo.
    # Resuelve compliance regulatorio + UX: cliente envía STOP → confirmación
    # canónica + revoca consent + marca conv opted_out + NO invoca LLM.
    try:
        await _handle_optout_if_keyword(
            supabase,
            message_id=message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content=content,
            content_type=content_type,
        )
        # Si el detector procesó el opt-out, _handle_optout_if_keyword marca
        # el message como processed y retorna True. Verificamos status conv
        # post-handle: si quedó opted_out, no avanzar al LLM.
        post_handle_status = _get_conversation_status_safe(supabase, tenant_id, conversation_id)
        if post_handle_status == "opted_out":
            return
    except Exception as exc:
        logger.warning("[OPTOUT_GATE] error en optout handler: %s", exc)
        # A11 audit (Clase C): FAIL-CLOSED. Si el mensaje ERA un keyword de
        # opt-out y su procesamiento falló, NO avanzamos al LLM — responder a
        # quien pidió parar es la dirección insegura (Habeas Data Art.9). El
        # error queda en logs para revisión. NO-STOP no se afecta (sigue al LLM).
        if _optout_failclosed_should_skip(content):
            logger.warning(
                "[OPTOUT_GATE] fail-closed: STOP keyword con handler fallido "
                "conv=%s — skip (no se invoca LLM)", conversation_id,
            )
            _mark_message_skipped(supabase, tenant_id, message_id)
            return

    # A11 2026-06-26 (palanca 3) — Habeas Data DSR gate: solicitudes de derechos
    # de datos NO-keyword ("borren mis datos", "retiro mi consentimiento", "derecho
    # al olvido") se escalan a humano + acusan recibo DETERMINÍSTICAMENTE (Ley 1581
    # exige manejo verificado por un asesor; NO auto-borramos). Corre DESPUÉS de STOP
    # (más específico) y del skip de status. Cierra el gap legal en todos los estados.
    try:
        if await _handle_data_rights_if_intent(
            supabase,
            message_id=message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content=content,
            content_type=content_type,
        ):
            return
    except Exception as exc:
        logger.warning("[HABEAS_DATA_GATE] error en data-rights handler: %s", exc)
        # FAIL-SAFE: si ERA solicitud de datos y el handler falló, NO avanzar al
        # LLM (responder mal a un DSR es la dirección legalmente insegura) → skip.
        from lib.habeas_data_request import is_data_rights_request
        if is_data_rights_request(content):
            _mark_message_skipped(supabase, tenant_id, message_id)
            return

    agentic_enabled = await is_tenant_agentic_enabled(supabase, tenant_id)

    if agentic_enabled:
        # Cutover: agentic es la ÚNICA fuente de verdad para tenants
        # migrados (Plan A.2 strangler-fig). NO existe fallback al legacy
        # V1 porque sus heurísticas (TIER2 category-lock, variant_confirmation,
        # explicit_products_in_inbound) son no-determinísticas y pueden
        # alucinar items inexistentes en escenarios específicos.
        # Rev. 109 UAT live BUG 38 — fix arquitectónico: si agentic crashea,
        # responder degraded honesto + escalation a operador. Cliente recibe
        # respuesta garantizada (no fallback a comportamiento impredecible).
        try:
            await _run_agentic_full(
                supabase,
                message_id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                content=content,
                content_type=content_type,
            )
            return
        except Exception as exc:
            logger.error(
                "[AGENTIC_DISPATCH] agentic full falló tenant=%s conv=%s: "
                "%s — degraded mode (NO fallback legacy)",
                tenant_id, conversation_id, exc,
                exc_info=True,
            )
            await _emit_degraded_response_and_escalate(
                supabase,
                message_id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                error=exc,
            )
            return

    # Path legacy SOLO para tenants explícitamente NO migrados a agentic.
    # Producción: KAIU + futuros tenants con agentic_enabled=True NUNCA
    # llegan aquí.
    from orchestrator import build_and_run_orchestration
    await build_and_run_orchestration(
        supabase=supabase,
        message_id=message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        content=content,
        content_type=content_type,
    )

    # Shadow mode: si flag activo Y agentic NO se ejecutó como full,
    # corre agentic en paralelo (silencioso) para comparar.
    if AGENTIC_SHADOW_ENABLED and not agentic_enabled:
        # No await — fire-and-forget con timeout interno.
        asyncio.create_task(_run_agentic_shadow_safe(
            supabase,
            message_id=message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content=content,
            content_type=content_type,
        ))


# ─── Degraded response helper (rev. 109 BUG 38) ─────────────────────────────


async def _emit_degraded_response_and_escalate(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    error: BaseException,
) -> None:
    """Degraded path con escalation diferida (rev. 109 BUG 38 + founder UX).

    Comportamiento:
      • 1er fallo en la conversación (en ventana 10 min): mensaje natural
        + invita reintento. NO escala. Cliente puede reintentar con otras
        palabras → flow recupera transparente.
      • 2do fallo consecutivo del mismo cliente en <10 min: ahora SÍ
        human_takeover + Telegram notif (patrón crítico, no transitorio).

    Razón: la mayoría de crashes son transitorios (saturación LLM, edge
    case pydantic). El cliente reintenta con frase distinta y funciona.
    Saturar al operador con cada crash transitorio es ruido. Solo escalar
    cuando hay patrón insistente.
    """
    from orchestrator import (
        _send_outbound_text,
        _mark_message_processing,
        PROCESSING_STATUS_FAILED,
    )

    # Marcar este mensaje como failed primero (afecta el conteo).
    try:
        _mark_message_processing(
            supabase, tenant_id, message_id,
            processing_status=PROCESSING_STATUS_FAILED,
        )
    except Exception:
        pass

    # Contar failed previos del cliente en ventana 10 min (excluyendo el actual).
    from datetime import datetime, timedelta, timezone
    _since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    failed_recent = 1  # asumimos al menos 1 (el actual) por defensa.
    try:
        rows = (
            supabase.table("messages")
            .select("id", count="exact")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)  # A6.2.7: defensa cross-tenant
            .eq("direction", "inbound")
            .eq("processing_status", PROCESSING_STATUS_FAILED)
            .gte("created_at", _since)
            .execute()
        )
        failed_recent = int(getattr(rows, "count", None) or len(rows.data or []))
    except Exception:
        pass

    is_repeat_failure = failed_recent >= 2

    if is_repeat_failure:
        degraded_text = (
            "Mmm, sigo sin entenderte bien. "
            "Mejor te paso con alguien del equipo que te ayuda enseguida."
        )
    else:
        degraded_text = (
            "Mmm, no te entendí del todo. "
            "¿Me lo cuentas de otra forma?"
        )

    try:
        await _send_outbound_text(
            supabase=supabase,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            text=degraded_text,
        )
    except Exception as send_exc:
        logger.error(
            "[AGENTIC_DEGRADED] send outbound falló conv=%s: %s",
            conversation_id, send_exc, exc_info=True,
        )

    if is_repeat_failure:
        try:
            supabase.table("conversations").update({
                "status": "human_takeover",
            }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
        except Exception as st_exc:
            logger.warning(
                "[AGENTIC_DEGRADED] status update falló conv=%s: %s",
                conversation_id, st_exc,
            )
        try:
            from telegram_notifications import notify_escalation_async
            await notify_escalation_async(
                supabase, tenant_id=tenant_id,
                conversation_id=conversation_id,
                reason=(
                    f"🚨 *Cliente con fallas repetidas*\n"
                    f"{failed_recent} mensajes consecutivos sin procesar "
                    f"en últimos 10 min.\n\nÚltimo error: "
                    f"`{str(error)[:200]}`\n\nConversación pasó a "
                    f"human_takeover. Acción: responder cliente + revisar "
                    f"logs orchestrator."
                ),
                severity="critical",
            )
        except Exception as tg_exc:
            logger.warning(
                "[AGENTIC_DEGRADED] telegram notif falló: %s", tg_exc,
            )

    logger.info(
        "[AGENTIC_DEGRADED] conv=%s failed_recent=%d repeat=%s",
        conversation_id[:8], failed_recent, is_repeat_failure,
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

    from orchestrator import (
        _send_outbound_text, _mark_message_processing, PROCESSING_STATUS_PROCESSED,
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


# ─── Tenant prompt context loader (A6.2.1 finiquito 2026-06-23) ─────────────


@dataclass
class TenantPromptContext:
    """Datos del tenant inyectados al system_prompt (identity + philosophy +
    business_ops). Extraído de `_run_agentic_full` (super-audit worwkgukx HIGH
    gap) para hacer testeable el manejo de error del lookup DB — antes vivía
    inline con `except Exception: pass` que silenciaba fallos y reintroducía
    la causa raíz P1 (bot improvisa) sin señal."""

    name: str = "el negocio"
    pitch: Optional[str] = None
    tone: Optional[str] = None
    philosophy: Optional[dict] = None
    shipping_origin: Optional[dict] = None
    store_locations: Optional[list] = None
    store_type: Optional[str] = None
    support_schedule: Optional[dict] = None
    social_links: Optional[dict] = None
    after_hours_message: Optional[str] = None


def _load_tenant_prompt_context(
    supabase: Any,
    tenant_id: str,
    *,
    default_name: str = "el negocio",
) -> TenantPromptContext:
    """Carga identity + philosophy + business_ops del tenant para el prompt.

    Degradación graceful: si la query DB falla (timeout, RLS, columna
    faltante), retorna el context con defaults (name=default_name, resto None)
    + emite logger.warning con el tenant_id para diagnóstico. NO reraise — un
    fallo de business_ops no debe tumbar el turno del cliente, pero TAMPOCO
    debe ser silencioso (lección A6.2.1: el `except: pass` previo reintroducía
    P1 invisible si la DB fallaba).
    """
    ctx = TenantPromptContext(name=default_name)
    try:
        ten_row = (
            supabase.table("tenants")
            .select(
                "name, business_pitch, tono_comunicacion, "
                "mision, vision, valores, "
                # A2 finiquito 2026-06-23 — business_ops block.
                "shipping_origin, store_locations, store_type, "
                "support_schedule, social_links, after_hours_message",
            )
            .eq("id", tenant_id).single().execute()
        )
        td = ten_row.data or {}
        ctx.name = td.get("name") or ctx.name
        ctx.pitch = td.get("business_pitch") or None
        ctx.tone = td.get("tono_comunicacion") or None
        # Rev. 109 auditoría — inyectar filosofía completa al system_prompt.
        if any(td.get(k) for k in ("mision", "vision", "valores")):
            ctx.philosophy = {
                "mision": td.get("mision"),
                "vision": td.get("vision"),
                "valores": td.get("valores"),
            }
        # A2 finiquito — business_ops fields.
        ctx.shipping_origin = td.get("shipping_origin") or None
        ctx.store_locations = td.get("store_locations") or None
        ctx.store_type = td.get("store_type") or None
        ctx.support_schedule = td.get("support_schedule") or None
        ctx.social_links = td.get("social_links") or None
        ctx.after_hours_message = td.get("after_hours_message") or None
    except Exception as exc:
        # A6.2.1 finiquito 2026-06-23 (super-audit worwkgukx HIGH gap):
        # ANTES `except: pass` silenciaba fallos DB → TODOS los kwargs
        # business_ops + philosophy quedaban None → bot improvisaba
        # horarios/despacho como pre-Fase 0, sin señal. Reintroducción
        # silenciosa de P1. Ahora logueamos con tenant_id para diagnóstico.
        logger.warning(
            "[AGENTIC_TENANT_LOAD] fallo cargando tenant=%s business_ops/"
            "philosophy (bot operará SIN esos datos → posible improvisación): "
            "%s: %s",
            tenant_id, type(exc).__name__, exc,
        )
    return ctx


async def _compose_purchase_outbound_canonical(
    *,
    supabase: Any,
    tenant_id: str,
    conversation_id: str,
    contact_id: str,
    contact: Optional[dict],
    customer_name: Optional[str],
    catalog: Any,
    content: str,
    agent: Any,
    intent_resolution: dict,
) -> str:
    """ADR-0026 Pieza C — compone el outbound del path pre-LLM purchase usando el
    renderizador canónico (Pieza B) con el cart REAL + destino persistido (Pieza A).

    - Subtotal SIEMPRE real (del cart, no parcial).
    - Si el add invalidó un envío con ciudad conocida → recotiza determinísticamente y
      presenta opciones (sin repreguntar la ciudad).
    - Fallback seguro a compose_outbound_from_resolution si no hay cart.
    """
    from agentic.purchase_intent_resolver import compose_outbound_from_resolution
    from tools.cart_tool import get_cart_with_items, get_shipping_destination
    from agentic.cart_render import render_cart_state_snapshot

    cart = None
    try:
        cart = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning("[ADR0026] get_cart_with_items falló en pre-LLM purchase: %s", exc)
    if not cart:
        # Sin cart legible → fallback al composer legacy (no rompemos el turno).
        return compose_outbound_from_resolution(
            intent_resolution, customer_name=customer_name,
        )

    destination = get_shipping_destination(cart, contact)
    requote_options = None
    # Recotización determinística: solo si el envío quedó pendiente CON ciudad conocida
    # y el agente permite cotizar.
    if (bool(cart.get("requires_requote")) and destination and destination.get("city")
            and _agent_permits_tool(agent, "quote_shipping")):
        try:
            from agentic.tools.shipping import QuoteShippingTool, QuoteShippingArgs
            from agentic.tools.base import ToolContext
            _ctx = ToolContext(
                tenant_id=tenant_id, conversation_id=conversation_id,
                contact_id=contact_id, supabase=supabase,
                catalog_cache=catalog, logger=logger,
                extras={"recent_inbound_texts": [content]},
            )
            _res = await QuoteShippingTool().execute(
                QuoteShippingArgs(city=destination["city"]), _ctx)
            if _res and _res.success:
                requote_options = (_res.data or {}).get("options") or None
                # Recargar cart: el re-quote pudo refrescar quoted_options/meta.
                cart = get_cart_with_items(
                    supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                ) or cart
            logger.info(
                "[ADR0026] pre-LLM purchase auto-recotización conv=%s city=%s opts=%s",
                conversation_id, destination["city"],
                len(requote_options or []),
            )
        except Exception as exc:
            logger.warning("[ADR0026] auto-recotización pre-LLM falló: %s", exc)

    return render_cart_state_snapshot(
        cart=cart, contact=contact, destination=destination,
        customer_name=customer_name, requote_options=requote_options,
    )


# ─── Agentic full path (cutover) ───────────────────────────────────────────


async def _run_agentic_full(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """Cutover: agentic compone outbound y lo envía al cliente."""
    # Imports early (rev. 109 fix UAT live BUG 23): el multimodal block
    # de abajo necesita _send_outbound_text + _mark_message_processing
    # para responder degraded honesto al cliente cuando Gemini multimodal
    # falla. Importarlos al inicio evita NameError + silent fallthrough.
    from orchestrator import (
        _send_outbound_text,
        _mark_message_processing,
        PROCESSING_STATUS_PROCESSED,
    )

    # ── Rev. 109 Día 4 — Multimodal pipeline ──
    # Si el inbound es audio/imagen/video, descargamos el media de Meta y
    # pedimos a Gemini multimodal una interpretación textual. El resto del
    # flow agentic ve el content reemplazado (transparente).
    if content_type in {"audio", "image", "video"}:
        try:
            from agentic.multimodal import (
                process_inbound_media, format_for_agentic,
            )
            # Cargar media_id + media_mime desde columnas directas
            # (connector-whatsapp/parser.py persiste así en messages).
            _mrow = (
                supabase.table("messages")
                .select("media_id, media_mime, media_url")
                .eq("id", message_id)
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            _m = _mrow.data or {}
            _media_id = _m.get("media_id")
            _media_mime = _m.get("media_mime")
            mm_result = await process_inbound_media(
                tenant_id=tenant_id,
                supabase=supabase,
                media_id=_media_id,
                media_mime=_media_mime,
                media_type=content_type,
                caption=content if not content.startswith("[") else None,
            )
            if mm_result and mm_result.text:
                original_content = content
                content = format_for_agentic(mm_result, original_content)
                logger.info(
                    "[MULTIMODAL_DISPATCH] conv=%s type=%s replaced chars=%d→%d",
                    conversation_id[:8], content_type,
                    len(original_content), len(content),
                )
                # Rev. 109 fix UX founder: persistir transcripción en
                # messages.content para que el operador del Inbox vea el
                # TEXTO REAL del audio/imagen/video, no el placeholder
                # "[Audio recibido]". media_id / media_url quedan intactos
                # (audio original sigue accesible).
                _media_label = {
                    "audio": "🎤 Audio",
                    "image": "📷 Imagen",
                    "video": "🎬 Video",
                }.get(content_type, content_type.capitalize())
                _inbox_text = f"{_media_label}: {mm_result.text}"
                try:
                    supabase.table("messages").update({
                        "content": _inbox_text,
                    }).eq("id", message_id).eq("tenant_id", tenant_id).execute()
                except Exception as _upd_exc:
                    logger.warning(
                        "[MULTIMODAL_DISPATCH] persist transcription falló "
                        "conv=%s: %s", conversation_id[:8], _upd_exc,
                    )
            else:
                # Rev. 109 fix UAT live: multimodal degraded → bot DEBE
                # informar honestamente al cliente, no responder genérico.
                # Mensaje empático que invita a reintentar / escribir.
                logger.warning(
                    "[MULTIMODAL_DISPATCH] conv=%s type=%s DEGRADED → "
                    "responde al cliente honesto, no procesar como texto",
                    conversation_id[:8], content_type,
                )
                _media_label = {
                    "audio": "audio",
                    "image": "imagen",
                    "video": "video",
                }.get(content_type, "media")
                _degraded_msg = (
                    f"Recibí tu {_media_label}, pero estoy teniendo "
                    f"dificultades técnicas para procesarlo en este momento. "
                    f"¿Podrías escribirme el mensaje, o intentar de nuevo "
                    f"en unos minutos? Si prefieres, te conecto con un "
                    f"especialista del equipo."
                )
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id,
                    tenant_id=tenant_id, text=_degraded_msg,
                )
                _mark_message_processing(
                    supabase, tenant_id, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                # history/contact aún no cargados en este punto — passes
                # vacíos para state machine (igual el state resolver lee
                # cart/conv directo de DB, no depende del history).
                _resolve_and_persist_agentic_state(
                    supabase=supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id, contact={},
                    history=[],
                )
                return
        except Exception as mm_exc:
            logger.warning(
                "[MULTIMODAL_DISPATCH] conv=%s type=%s falló: %s — content original",
                conversation_id[:8], content_type, mm_exc,
            )
    # ── /multimodal ──

    # Import los tools para que se auto-registren.
    import agentic.tools.catalog  # noqa: F401
    import agentic.tools.cart  # noqa: F401
    import agentic.tools.contact  # noqa: F401
    import agentic.tools.shipping  # noqa: F401
    import agentic.tools.payment  # noqa: F401
    import agentic.tools.escalation  # noqa: F401
    import agentic.tools.orders  # noqa: F401
    import agentic.tools.knowledge  # noqa: F401
    import agentic.tools.media  # noqa: F401
    import agentic.tools.claims  # noqa: F401  # Rev. 109 founder 2026-05-28

    from agentic.agent import run_agentic_turn
    from agentic.system_prompt import build_system_prompt
    from agentic.invariants import (
        apply_invariants,
        CanonicalCategoriesInvariant,
        CartRenderCoherenceInvariant,
        ConsentRequiredInvariant,
        EmptyPromiseInvariant,
        FakeEscalationInvariant,
        NoDecorativeEmojiInvariant, PassiveClosingInvariant,
        NoInternalsExposureInvariant,
        PaymentCoherenceInvariant,
        PIICoherenceInvariant,
        PIISaveTruthfulnessInvariant,
        PostToolCoherenceInvariant, SummaryCoherenceInvariant,
        RequotePendingSummaryInvariant,
        VariantAvailabilityAssertionInvariant,
        InvariantOutcome,
    )

    # Cargar context (catalog, contact, history) — reusa helpers legacy.
    from orchestrator import (
        _get_conversation_history,
        _fetch_contact_for_phone,
        _get_conversation_customer_phone,
        _mark_message_processing,
        _send_outbound_text,
        PROCESSING_STATUS_PROCESSED,
    )
    from tools.catalog_tool import get_tenant_catalog

    # get_tenant_catalog es async — debe awaitearse.
    catalog = await get_tenant_catalog(supabase, tenant_id)
    history = await _get_conversation_history(supabase, tenant_id, conversation_id)
    customer_phone = _get_conversation_customer_phone(supabase, tenant_id, conversation_id)
    # Rev. 108 — auto-upsert contact si no existe (paridad con orchestrator V1
    # línea 6833). Sin esto, record_consent + save_pii fallan con NO_CONTACT
    # cuando un cliente nuevo escribe (o tras reset --hard).
    # consent_given=False default — el bot pedirá consent explícito vía
    # record_consent antes de save_pii.
    if customer_phone:
        try:
            supabase.table("contacts").upsert(
                {
                    "tenant_id": tenant_id,
                    "phone": customer_phone,
                    "shipping_phone": customer_phone,
                    "consent_given": False,
                },
                on_conflict="tenant_id,phone",
                ignore_duplicates=True,
            ).execute()
        except Exception as exc:
            logger.warning(
                "[AGENTIC_DISPATCH] contact upsert falló phone=%s: %s",
                customer_phone, exc,
            )
    # `_fetch_contact_for_phone` retorna tuple (contact_id, contact_record).
    if customer_phone:
        contact_id, contact = _fetch_contact_for_phone(supabase, tenant_id, customer_phone)
    else:
        contact_id, contact = None, {}

    # System prompt — Rev. 107 fix: leer tenant.name real desde DB
    # (antes default "el negocio" → bot decía "Bienvenida a Sara Camila,
    # cosmética artesanal natural" usando agent_name como tenant name).
    # A6.2.1 finiquito 2026-06-23 — extraído a helper testeable
    # `_load_tenant_prompt_context` (super-audit worwkgukx). El manejo de
    # error (logger.warning en vez de `except: pass`) ahora es testeable.
    _tpc = _load_tenant_prompt_context(supabase, tenant_id, default_name="el negocio")
    tenant_name = _tpc.name
    tenant_pitch = _tpc.pitch
    tenant_tone = _tpc.tone
    tenant_philosophy = _tpc.philosophy
    tenant_shipping_origin = _tpc.shipping_origin
    tenant_store_locations = _tpc.store_locations
    tenant_store_type = _tpc.store_type
    tenant_support_schedule = _tpc.support_schedule
    tenant_social_links = _tpc.social_links
    tenant_after_hours_message = _tpc.after_hours_message

    # Rev. 108 holístico — cargar capacidades carrier (canonical + tenant
    # override) para que el bot SIEMPRE sepa qué carriers soportan COD,
    # mínimos de recaudo, devolución cobrada, etc. Bloque inyectado al
    # system_prompt para responder asertivamente sin perder contexto.
    carriers_caps: list[dict] = []
    try:
        from lib.carrier_capabilities import get_all_capabilities_for_tenant
        carriers_caps = [
            c.as_dict() for c in get_all_capabilities_for_tenant(
                supabase, tenant_id=tenant_id,
            )
        ]
    except Exception as _cap_exc:
        logger.warning(
            "[CARRIER_CAPS] no pude cargar canonical capabilities tenant=%s: %s — "
            "prompt sin bloque [CARRIERS]",
            tenant_id[:8], _cap_exc,
        )

    # Rev. 108 modular — cargar payment methods enabled per-tenant.
    # Bot conoce qué métodos ofrecer ANTES de hablar con el cliente.
    payment_methods_cfg: dict = {}
    try:
        from lib.tenant_payment_methods import get_tenant_payment_methods
        payment_methods_cfg = get_tenant_payment_methods(
            supabase, tenant_id=tenant_id,
        ).as_dict()
    except Exception as _pm_exc:
        logger.warning(
            "[PAYMENT_METHODS] no pude cargar tenant=%s: %s — prompt sin bloque",
            tenant_id[:8], _pm_exc,
        )

    # Rev. 109 founder 2026-05-28 — cupones activos como fuente de verdad.
    # Bug A.0.1 detectado en UAT: agente marketing afirmaba "no hay promos"
    # sin consultar DB. Patrón cart-as-SoT: el LLM no decide verdad
    # transaccional. Inyectamos cupones activos al system_prompt igual
    # que catalog/payment_methods/carriers.
    active_coupons: list[dict] = []
    try:
        _now_iso = __import__("datetime").datetime.utcnow().isoformat()
        _coupons_res = (
            supabase.table("coupons")
            .select(
                "code, discount_type, discount_value, min_subtotal_cents, "
                "max_redemptions, redemptions_count, valid_until",
            )
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .gt("valid_until", _now_iso)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        # Filtro adicional: descartar cupones con redemptions agotadas.
        # (postgrest no admite comparar 2 columnas en .lt directo)
        for c in (_coupons_res.data or []):
            max_red = c.get("max_redemptions")
            used = c.get("redemptions_count") or 0
            if max_red is None or int(used) < int(max_red):
                active_coupons.append(c)
    except Exception as _coup_exc:
        logger.warning(
            "[COUPONS] no pude cargar tenant=%s: %s — prompt sin bloque",
            tenant_id[:8], _coup_exc,
        )

    # Rev. 109 ADR-0017 — Multi-agente per-tenant con router pre-LLM.
    # Si tenant tiene >1 agente activo, agent_router clasifica el inbound
    # por heurística (cero costo LLM) y elige el agente apropiado.
    # Si tenant tiene 1 agente → default (backward-compat).
    try:
        from lib.tenant_agents import get_active_agent
        _agent = get_active_agent(
            supabase, tenant_id=tenant_id, inbound_text=content,
        )
    except Exception:
        _agent = {"name": "Sara Camila"}

    # A8 #3 finiquito (audit §6) — observabilidad del agente activo. Antes el
    # persona_block (role_description) llegaba al LLM pero NO se trackeaba qué
    # rol lo renderizó → imposible auditar/debuggear "el bot se presentó como
    # agente X". Log per-turn del agente + rol + si inyecta persona.
    logger.info(
        "[AGENTIC_AGENT] conv=%s agent=%s role=%s has_persona=%s handoff=%s",
        conversation_id[:8] if conversation_id else "?",
        _agent.get("name") or "?", _agent.get("role") or "default",
        bool(_agent.get("role_description")),
        bool(_agent.get("_needs_human_handoff")),
    )

    # A8 finiquito (audit §1 #8 + §6) — Handoff sintético con consumer REAL.
    # Si el agent_router determinó que NINGÚN agente del tenant cubre este
    # inbound (_needs_human_handoff), antes el flag se ignoraba: el bot
    # respondía "te contacto con un asesor" pero NADIE era notificado y la conv
    # NO se marcaba human_takeover → promesa rota. Acá ejecutamos el side-effect
    # REAL. El LLM igual corre con el role_description del agente sintético
    # (mensaje cálido al cliente, sin tools), pero ahora SÍ hay atención humana.
    if _agent.get("_needs_human_handoff"):
        await _consume_router_handoff(supabase, tenant_id, conversation_id)

    # Rev. 109 auditoría — pitch/tone YA NO se duplican en ai_agents.
    # Única fuente verdad: tenants.business_pitch + tenants.tono_comunicacion.
    # Filosofía completa inyectada como bloque dedicado al system_prompt.
    system_prompt = build_system_prompt(
        tenant_name=tenant_name,
        catalog=catalog,
        agent_name=_agent.get("name") or "Sara Camila",
        tenant_pitch=tenant_pitch,
        tenant_tone=tenant_tone,
        contact_record=contact or {},
        carriers=carriers_caps,
        payment_methods=payment_methods_cfg,
        tenant_philosophy=tenant_philosophy,
        agent_role_description=_agent.get("role_description"),
        active_coupons=active_coupons,
        # A2 finiquito 2026-06-23 — business_ops block (cierra Bug #1 audit §1).
        shipping_origin=tenant_shipping_origin,
        store_locations=tenant_store_locations,
        store_type=tenant_store_type,
        support_schedule=tenant_support_schedule,
        social_links=tenant_social_links,
        after_hours_message=tenant_after_hours_message,
    )

    # ── Pre-LLM resolver determinístico: variant selection continuation ──
    # Rev. 107 fix runtime founder 2026-05-24 conv 8c845cc0: bot preguntó
    # "15ml o 30ml?", cliente respondió "15ml". Gemini fallaba con
    # STOP+empty (saturación SDK 19 tools × 20K chars prompt × history).
    # Cuando el contexto es 100% determinístico (bot ofreció variantes,
    # cliente respondió variante), bypaseamos Gemini y resolvemos directo.
    # NO es parche — es el mismo patrón ya usado por `image_send_tool`,
    # `shipping_quote_tool`, `order_status_tool` en flow legacy V1.

    # PRE-LLM #-0.5: Payment method AVAILABILITY (rev. 108 modular).
    # Antes de COD/credit intent resolvers, verificar si el método que
    # el cliente está mencionando está habilitado per-tenant.
    # Si NO disponible → forzar cart al método AVAILABLE + marcar contexto.
    # El LLM (con [MÉTODOS DE PAGO] block en system_prompt) compone
    # respuesta asertiva naturalmente. Esto NO bypassea — modifica state
    # determinísticamente y deja al LLM hacer gloss natural.
    try:
        from agentic.payment_method_availability_resolver import (
            detect_unavailable_payment_method,
        )
        unavailable_pm = detect_unavailable_payment_method(
            supabase, tenant_id=tenant_id, inbound_text=content,
        )
        if unavailable_pm:
            logger.info(
                "[AGENTIC_PRE_LLM] payment_method_availability conv=%s "
                "requested=%s enabled=%s — forcing cart al método disponible",
                conversation_id[:8],
                unavailable_pm["requested_method"],
                unavailable_pm["available_methods"],
            )
            # Forzar cart al primer método disponible (si hay).
            available = unavailable_pm["available_methods"]
            if available:
                forced_method = (
                    "credit" if "online_wompi" in available else "cod"
                )
                try:
                    cart_q = (
                        supabase.table("conversation_carts")
                        .select("id")
                        .eq("tenant_id", tenant_id)
                        .eq("conversation_id", conversation_id)
                        .in_("status", ["open", "checkout"])
                        .order("created_at", desc=True).limit(1).execute()
                    )
                    if cart_q.data:
                        supabase.table("conversation_carts").update({
                            "payment_method": forced_method,
                        }).eq("id", cart_q.data[0]["id"]).eq("tenant_id", tenant_id).execute()
                except Exception:
                    pass
    except Exception as exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] payment_method_availability crashed: %s — skip",
            exc,
        )

    # PRE-LLM #-1: Domain filter — Meta Business Policy + Ley 23/1981
    # Colombia (ejercicio ilegal de medicina) + INVIMA (cosméticos NO son
    # medicamentos). Rev. 109 fix UAT live BUG 36.
    # Si el cliente pregunta consulta médica/diagnóstico O intenta comprar
    # medicamento → bot redirige a profesional/droguería y NO procesa con
    # LLM (LLM tendía a "recomendar productos para curar gripa" — claim
    # médico ilegal + violación Meta Policy).
    try:
        from safety import (
            detect_medical_query as _detect_medical_query,
            detect_drug_purchase_request as _detect_drug_purchase_request,
        )
        _medical_hit = _detect_medical_query(content)
        _drug_hit = _detect_drug_purchase_request(content) if not _medical_hit else False
        if _medical_hit or _drug_hit:
            if _medical_hit:
                _redirect = (
                    "Entiendo tu inquietud. Soy asistente de venta de "
                    "productos de KAIU Living Natural — no estoy "
                    "capacitada para dar recomendaciones médicas ni "
                    "diagnosticar condiciones de salud.\n\n"
                    "Para temas de salud te recomiendo consultar a un "
                    "profesional médico o tu EPS.\n\n"
                    "¿Te puedo ayudar con algún producto de nuestra "
                    "tienda?"
                )
                _log_reason = "medical_query"
            else:
                _redirect = (
                    "Lo siento, no vendemos medicamentos. Por norma de "
                    "WhatsApp Business + regulación colombiana (INVIMA), "
                    "los medicamentos solo pueden adquirirse en "
                    "droguerías/farmacias autorizadas.\n\n"
                    "¿Te puedo ayudar con algún producto de cosmética "
                    "natural KAIU?"
                )
                _log_reason = "drug_purchase"
            await _send_outbound_text(
                supabase=supabase, conversation_id=conversation_id,
                tenant_id=tenant_id, text=_redirect,
            )
            _mark_message_processing(
                supabase, tenant_id, message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            _resolve_and_persist_agentic_state(
                supabase=supabase, tenant_id=tenant_id,
                conversation_id=conversation_id, contact=contact,
                history=history,
            )
            logger.info(
                "[AGENTIC_PRE_LLM] domain_filter blocked conv=%s reason=%s",
                conversation_id[:8], _log_reason,
            )
            return
    except Exception as exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] domain_filter crashed: %s — fall-through LLM",
            exc,
        )

    # PRE-LLM #-0.5: Recipient intent — envío a tercero (BUG 37 enforcement).
    # Cuando cliente dice "es para mi mamá: Maria, CC X, Cel Y", persistimos
    # los datos del receptor en cart.shipping_meta.recipient ANTES del LLM.
    # Sin esto, LLM agentic elegía save_contact_field (path familiar) y
    # sobrescribía datos del titular WhatsApp (violación Habeas Data Ley 1581).
    # Si el cart no existe aún → solo marcamos shipping_meta y el LLM
    # completa flow normal. NO bloquea, solo prepara estado correcto.
    try:
        from agentic.shipping_recipient_intent_resolver import (
            detect_recipient_intent,
        )
        _recip_match = detect_recipient_intent(content)
        if _recip_match and (
            _recip_match.name or _recip_match.phone or _recip_match.document_number
        ):
            try:
                from tools.cart_tool import (
                    get_cart_with_items,
                    set_shipping_recipient as _set_recipient,
                    ensure_cart as _ensure_cart_r,
                )
                # Cart puede no existir aún (cliente menciona receptor antes
                # de elegir producto). Si no hay, lo creamos vacío para
                # persistir la intent y que el LLM downstream lo respete.
                _cart_r = get_cart_with_items(
                    supabase, conversation_id=conversation_id,
                    tenant_id=tenant_id,
                )
                if not _cart_r:
                    _cart_r = _ensure_cart_r(
                        supabase, conversation_id=conversation_id,
                        tenant_id=tenant_id, contact_id=contact_id,
                    )
                _set_recipient(
                    supabase,
                    cart_id=_cart_r["id"],
                    tenant_id=tenant_id,
                    name=_recip_match.name,
                    document_type=_recip_match.document_type,
                    document_number=_recip_match.document_number,
                    phone=_recip_match.phone,
                    address=None,  # LLM completa address turn-by-turn
                )
                logger.info(
                    "[AGENTIC_PRE_LLM] recipient_intent set conv=%s "
                    "name=%s doc=%s phone=%s",
                    conversation_id[:8],
                    _recip_match.name, _recip_match.document_number,
                    _recip_match.phone,
                )
            except Exception as _r_exc:
                logger.warning(
                    "[AGENTIC_PRE_LLM] recipient_intent persist falló: %s",
                    _r_exc,
                )
    except Exception as exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] recipient_intent_resolver crashed: %s — skip",
            exc,
        )

    # PRE-LLM #0: COD intent marker. Rev. 108 Fase B.
    # NO es bypass — solo marca el cart con payment_method='cod' cuando
    # el cliente menciona explícitamente "contraentrega"/"pago al recibir".
    # Downstream tools (shipping_quote_tool, payment_link_tool,
    # _generate_shipping_guide) leen el flag y ramifican.
    # Si no hay cart aún → log + continue (LLM responde info COD del prompt).
    try:
        from agentic.cod_intent_resolver import (
            detect_cod_intent, detect_credit_intent,
        )
        cod_match = detect_cod_intent(content)
        credit_match = detect_credit_intent(content) if not cod_match else None

        # Rev. 108 modular — short-circuit si tenant NO tiene COD enabled.
        # Aunque el cliente diga "contraentrega", si el tenant configuró
        # método=cod disabled, NO marcamos cart con 'cod' (sería falso
        # positivo). El resolver de availability ya forzó cart=credit
        # arriba; aquí solo confirmamos que no re-flipeamos.
        if cod_match:
            try:
                from lib.tenant_payment_methods import is_method_enabled
                if not is_method_enabled(
                    supabase, tenant_id=tenant_id, method="cod",
                ):
                    logger.info(
                        "[AGENTIC_PRE_LLM] cod_intent matched but tenant has "
                        "method='cod' DISABLED — skip mark (resolver "
                        "payment_method_availability ya forzó credit)"
                    )
                    cod_match = None  # disable downstream marking
            except Exception:
                pass

        if cod_match:
            try:
                cart_row = (
                    supabase.table("conversation_carts")
                    .select("id, payment_method")
                    .eq("conversation_id", conversation_id)
                    .eq("tenant_id", tenant_id)
                    .in_("status", ["open", "checkout"])
                    .order("created_at", desc=True).limit(1).execute()
                )
                if cart_row.data:
                    cid = cart_row.data[0]["id"]
                    cur_method = cart_row.data[0].get("payment_method", "credit")
                    if cur_method != "cod":
                        supabase.table("conversation_carts").update({
                            "payment_method": "cod",
                        }).eq("id", cid).eq("tenant_id", tenant_id).execute()
                        logger.info(
                            "[AGENTIC_PRE_LLM] conv=%s cart=%s payment_method "
                            "credit → cod (intent: %s)",
                            conversation_id, cid[:8],
                            cod_match.get("matched_text", "?"),
                        )
            except Exception as exc:
                logger.warning(
                    "[AGENTIC_PRE_LLM] mark COD cart failed conv=%s: %s",
                    conversation_id, exc,
                )
        elif credit_match:
            # Cliente cambió de COD a credit explícito — revertir.
            try:
                cart_row = (
                    supabase.table("conversation_carts")
                    .select("id, payment_method")
                    .eq("conversation_id", conversation_id)
                    .eq("tenant_id", tenant_id)
                    .in_("status", ["open", "checkout"])
                    .order("created_at", desc=True).limit(1).execute()
                )
                if cart_row.data and cart_row.data[0].get("payment_method") == "cod":
                    cid = cart_row.data[0]["id"]
                    supabase.table("conversation_carts").update({
                        "payment_method": "credit",
                    }).eq("id", cid).eq("tenant_id", tenant_id).execute()
                    logger.info(
                        "[AGENTIC_PRE_LLM] conv=%s cart=%s payment_method "
                        "cod → credit (intent: %s)",
                        conversation_id, cid[:8],
                        credit_match.get("matched_text", "?"),
                    )
            except Exception as exc:
                logger.warning(
                    "[AGENTIC_PRE_LLM] mark CREDIT cart failed conv=%s: %s",
                    conversation_id, exc,
                )
    except Exception as exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] cod_intent_resolver crashed: %s — skip", exc,
        )

    # PRE-LLM #0.4: coupon intent (rev. 109 UAT live BUG 16). Cliente
    # menciona código de cupón → aplicar/revocar deterministicamente.
    # Sin esto el LLM no tiene tool para cupones → escala a humano.
    try:
        from lib.coupon_detector import (
            detect_coupon_intent as _detect_coupon_intent,
            INTENT_APPLY as _INTENT_APPLY,
            INTENT_REMOVE as _INTENT_REMOVE,
        )
        from lib import coupons as _coupon_helpers

        _coupon_intent = _detect_coupon_intent(content)
        if _coupon_intent:
            _cart_lookup = (
                supabase.table("conversation_carts")
                .select(
                    "id, status, subtotal_cents, shipping_cents, "
                    "total_cents, coupon_id, coupon_code, discount_cents"
                )
                .eq("tenant_id", tenant_id)
                .eq("conversation_id", conversation_id)
                .in_("status", ["open", "checkout"])
                .order("created_at", desc=True).limit(1).execute()
            )
            _cart_rows = _cart_lookup.data or []
            _coupon_response: Optional[str] = None
            _coupon_event_type: Optional[str] = None
            _coupon_event_payload: dict = {}
            _coupon_cart_id: Optional[str] = None

            if not _cart_rows:
                if _coupon_intent.intent == _INTENT_APPLY:
                    _coupon_response = (
                        "Aún no tienes un pedido en curso. Cuando agregues "
                        "productos podemos aplicar tu cupón."
                    )
                else:
                    _coupon_response = "No tienes ningún cupón aplicado."
            else:
                _cart = _cart_rows[0]
                _coupon_cart_id = _cart["id"]
                if _cart["status"] == "checkout":
                    _coupon_response = (
                        "*El cupón debe aplicarse antes de generar el link "
                        "de pago.*\nSi quieres usarlo, dime y cancelamos el "
                        "link actual para rehacer el pedido."
                    )
                elif _coupon_intent.intent == _INTENT_REMOVE:
                    _prev_code = _cart.get("coupon_code")
                    _prev_id = _cart.get("coupon_id")
                    _revoked = _coupon_helpers.revoke_coupon(
                        supabase, tenant_id=tenant_id,
                        cart_id=_coupon_cart_id, reason="user_removed",
                    )
                    if _revoked:
                        _coupon_response = "Cupón removido."
                        _coupon_event_type = "coupon_revoked"
                        _coupon_event_payload = {
                            "coupon_id": _prev_id, "code": _prev_code,
                            "reason": "user_removed",
                        }
                    else:
                        _coupon_response = "No tenías ningún cupón aplicado."
                elif _coupon_intent.intent == _INTENT_APPLY:
                    if not _coupon_intent.code:
                        _coupon_response = (
                            "No detecté el código del cupón. ¿Me lo confirmas?"
                        )
                    else:
                        _result = _coupon_helpers.apply_coupon(
                            supabase, tenant_id=tenant_id,
                            cart_id=_coupon_cart_id, code=_coupon_intent.code,
                        )
                        if _result.ok:
                            _desc_str = f"${_result.discount_cents / 100:,.0f}".replace(",", ".")
                            _coupon_response = (
                                f"Cupón *{_result.coupon_code}* aplicado: "
                                f"descuento -{_desc_str} COP.\n"
                                f"¿En qué más te puedo ayudar?"
                            )
                            _coupon_event_type = "coupon_applied"
                            _coupon_event_payload = {
                                "coupon_id": _result.coupon_id,
                                "code": _result.coupon_code,
                                "discount_cents": _result.discount_cents,
                            }
                        else:
                            _coupon_response = _result.user_message

            if _coupon_response:
                if _coupon_event_type and _coupon_cart_id:
                    try:
                        supabase.table("cart_events").insert({
                            "cart_id": _coupon_cart_id,
                            "tenant_id": tenant_id,
                            "event_type": _coupon_event_type,
                            "event_payload": _coupon_event_payload,
                            "triggered_by": "bot",
                            "correlation_id": message_id,
                        }).execute()
                    except Exception:
                        pass
                logger.info(
                    "[AGENTIC_PRE_LLM] coupon_intent conv=%s intent=%s code=%s",
                    conversation_id[:8], _coupon_intent.intent,
                    _coupon_intent.code,
                )
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id,
                    tenant_id=tenant_id, text=_coupon_response,
                )
                _mark_message_processing(
                    supabase, tenant_id, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                _resolve_and_persist_agentic_state(
                    supabase=supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id, contact=contact,
                    history=history,
                )
                return
    except Exception as _coup_exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] coupon_intent crashed: %s — skip", _coup_exc,
        )

    # PRE-LLM #0.42: cancel/retracto intent (rev. 109 producción Ley 1480).
    # Cliente solicita cancelar pedido (pre-entrega) o retractar (post-entrega).
    # Detección + triage de escalation + invocación pipeline arquitectónico.
    try:
        from agentic.cancel_intent_resolver import (
            detect_cancel_intent as _detect_cancel,
            find_cancelable_orders_for_conversation as _find_cancelable,
            find_order_by_short_id as _find_by_short,
        )

        _cancel_match = _detect_cancel(content)
        if _cancel_match:
            # Resolver order_id
            target_order_id: Optional[str] = None
            # Rev. 109 fix UAT live BUG 28: track si cliente mencionó un
            # order_id explícito que NO existe → mensaje específico, no
            # fall-through al LLM.
            _explicit_id_not_found = False
            if _cancel_match.order_id_long:
                target_order_id = _cancel_match.order_id_long
            elif _cancel_match.order_id_short:
                _found = _find_by_short(
                    supabase, tenant_id=tenant_id,
                    short_id=_cancel_match.order_id_short,
                )
                if _found:
                    target_order_id = _found["id"]
                else:
                    _explicit_id_not_found = True
            else:
                # No order_id mencionado → buscar única orden cancelable
                _orders = _find_cancelable(
                    supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id,
                )
                if len(_orders) == 1:
                    target_order_id = _orders[0]["id"]
                elif len(_orders) > 1:
                    # Ambiguity → preguntar cuál
                    _list_str = "\n".join(
                        f"* *#{o['short_id']}* — ${o['total_amount']:,.0f} COP "
                        f"({o['status']})".replace(",", ".")
                        for o in _orders
                    )
                    _ambig_msg = (
                        f"Tienes varios pedidos activos. ¿Cuál quieres "
                        f"{('retractar' if _cancel_match.intent == 'retracto' else 'cancelar')}?\n\n{_list_str}"
                    )
                    await _send_outbound_text(
                        supabase=supabase, conversation_id=conversation_id,
                        tenant_id=tenant_id, text=_ambig_msg,
                    )
                    _mark_message_processing(
                        supabase, tenant_id, message_id,
                        processing_status=PROCESSING_STATUS_PROCESSED,
                    )
                    _resolve_and_persist_agentic_state(
                        supabase=supabase, tenant_id=tenant_id,
                        conversation_id=conversation_id, contact=contact,
                        history=history,
                    )
                    return
                else:
                    # 2026-06-26 (conversación real, founder S11): si NO hay orden
                    # pero SÍ un carrito con items, el cliente quiere ABANDONAR el
                    # carrito (no cancelar una orden) → acusar coherente + marcar
                    # abandonado. Sin esto el bot decía "no encuentro pedidos para
                    # cancelar" — incoherente con "ya no quiero nada".
                    _abandoned_cart = False
                    try:
                        _oc = (
                            supabase.table("conversation_carts")
                            .select("id")
                            .eq("tenant_id", tenant_id)
                            .eq("conversation_id", conversation_id)
                            .eq("status", "open")
                            .limit(1).execute()
                        )
                        if _oc.data:
                            _cid = _oc.data[0]["id"]
                            _it = (
                                supabase.table("conversation_cart_items")
                                .select("id")
                                .eq("tenant_id", tenant_id)
                                .eq("cart_id", _cid).limit(1).execute()
                            )
                            if _it.data:
                                supabase.table("conversation_carts").update(
                                    {"status": "abandoned"}
                                ).eq("id", _cid).eq("tenant_id", tenant_id).execute()
                                _abandoned_cart = True
                    except Exception as _exc:
                        logger.warning("[CANCEL] abandon cart check falló: %s", _exc)
                    if _abandoned_cart:
                        _no_msg = (
                            "Listo, descarté lo que tenías en el carrito — no "
                            "quedó nada pendiente. Cuando quieras retomar o ver "
                            "algo más, aquí estoy."
                        )
                    else:
                        _no_msg = (
                            "No encuentro pedidos activos para cancelar en esta "
                            "conversación. ¿Tienes el número del pedido (8 "
                            "caracteres después del #)? También te conecto con "
                            "un especialista si prefieres."
                        )
                    await _send_outbound_text(
                        supabase=supabase, conversation_id=conversation_id,
                        tenant_id=tenant_id, text=_no_msg,
                    )
                    _mark_message_processing(
                        supabase, tenant_id, message_id,
                        processing_status=PROCESSING_STATUS_PROCESSED,
                    )
                    _resolve_and_persist_agentic_state(
                        supabase=supabase, tenant_id=tenant_id,
                        conversation_id=conversation_id, contact=contact,
                        history=history,
                    )
                    return

            # Rev. 109 fix UAT live BUG 28: cliente mencionó order_id
            # explícito que NO existe (pudo haber sido eliminado o typo).
            # Respuesta directa, no fall-through al LLM.
            if _explicit_id_not_found:
                _short = _cancel_match.order_id_short or "?"
                _not_found_msg = (
                    f"No encuentro el pedido *#{_short}* en nuestro sistema. "
                    f"Puede haber sido cancelado anteriormente o el número "
                    f"estar incompleto.\n\n"
                    f"¿Tienes el número exacto (8 caracteres después del #)? "
                    f"También te conecto con un especialista si prefieres."
                )
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id,
                    tenant_id=tenant_id, text=_not_found_msg,
                )
                _mark_message_processing(
                    supabase, tenant_id, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                _resolve_and_persist_agentic_state(
                    supabase=supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id, contact=contact,
                    history=history,
                )
                return

            if target_order_id:
                if _cancel_match.intent == "cancel_order":
                    # Pre-entrega cancellation pipeline.
                    from lib.order_cancellation import (
                        cancel_order, CancellationRequest,
                    )
                    _cancel_result = await cancel_order(
                        supabase,
                        CancellationRequest(
                            order_id=target_order_id,
                            tenant_id=tenant_id,
                            actor="customer",
                            reason_code="customer_request",
                            reason_text=_cancel_match.reason_text,
                            conversation_id=conversation_id,
                        ),
                    )
                    await _send_outbound_text(
                        supabase=supabase, conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=_cancel_result.customer_message,
                    )
                    _mark_message_processing(
                        supabase, tenant_id, message_id,
                        processing_status=PROCESSING_STATUS_PROCESSED,
                    )

                    # Si requiere escalación → marcar conv human_takeover
                    if _cancel_result.requires_escalation:
                        try:
                            supabase.table("conversations").update({
                                "status": "human_takeover",
                            }).eq("id", conversation_id).eq(
                                "tenant_id", tenant_id,
                            ).execute()
                        except Exception:
                            pass

                    # Notif Telegram operador si requiere acción
                    if _cancel_result.operator_notification:
                        try:
                            from telegram_notifications import (
                                notify_escalation_async,
                            )
                            await notify_escalation_async(
                                supabase, tenant_id=tenant_id,
                                conversation_id=conversation_id,
                                reason=_cancel_result.operator_notification,
                            )
                        except Exception as _t_exc:
                            logger.warning(
                                "[CANCEL] telegram notif falló: %s", _t_exc,
                            )

                    logger.info(
                        "[AGENTIC_PRE_LLM] cancel_order conv=%s order=%s "
                        "status=%s escalated=%s",
                        conversation_id[:8], target_order_id[:8],
                        _cancel_result.status, _cancel_result.requires_escalation,
                    )
                    _resolve_and_persist_agentic_state(
                        supabase=supabase, tenant_id=tenant_id,
                        conversation_id=conversation_id, contact=contact,
                        history=history,
                    )
                    return

                if _cancel_match.intent == "retracto":
                    # Post-entrega: escalación inicial al especialista. RMA
                    # flow tiene complejidad legal (5d hábiles, validación
                    # producto, refund 30d) que requiere humano experto.
                    short_id = target_order_id[:8].upper()

                    # Rev. 109 backlog #1 — Retracto categories multi-tenant.
                    # Si el tenant configuró flag `retracto_excluded=true`
                    # en productos del pedido (cosmética abierta /
                    # software descargable / perecederos / lo que sea),
                    # citar razones específicas con producto + ley.
                    _retracto_check = None
                    try:
                        from lib.retracto import (
                            check_retracto_eligibility,
                            format_excluded_message,
                        )
                        _retracto_check = check_retracto_eligibility(
                            supabase,
                            order_id=target_order_id,
                            tenant_id=tenant_id,
                        )
                    except Exception as _r_exc:
                        logger.warning(
                            "[RETRACTO] check eligibility crashed: %s — "
                            "fallback mensaje genérico", _r_exc,
                        )

                    if (_retracto_check
                            and not _retracto_check.eligible
                            and _retracto_check.excluded_items):
                        # Mensaje específico con productos excluidos.
                        _retracto_msg = format_excluded_message(
                            _retracto_check, short_id,
                        )
                    else:
                        # Mensaje cauteloso genérico (BUG 40 fix existente).
                        _retracto_msg = (
                            f"Entiendo que quieres retractarte del pedido "
                            f"*#{short_id}*.\n\n"
                            f"La *Ley 1480 Art. 47* otorga 5 días hábiles desde "
                            f"la entrega para retractarse. Sin embargo, su "
                            f"*parágrafo* excluye algunas categorías "
                            f"(productos abiertos de uso íntimo, perecederos, "
                            f"personalizados, etc.).\n\n"
                            f"Te conecto con un especialista para validar si tu "
                            f"caso aplica según la política del tenant + estado "
                            f"del producto. Si aplica, procesamos devolución y "
                            f"reembolso en *máximo 30 días calendario* (Art. 49)."
                        )
                    # Rev. 109 fix UAT live BUG 39 — persistir audit row
                    # order_cancellations para trazabilidad SIC + visibilidad
                    # operador en panel.
                    try:
                        import uuid as _uuid
                        from datetime import datetime as _dt, timezone as _tz
                        _audit_id = str(_uuid.uuid4())
                        supabase.table("order_cancellations").insert({
                            "id": _audit_id,
                            "tenant_id": tenant_id,
                            "order_id": target_order_id,
                            "conversation_id": conversation_id,
                            "cancelled_by_actor": "customer",
                            "status": "pending",
                            "reason_code": "retracto_art_47",
                            "reason_text": (
                                _cancel_match.reason_text or "retracto solicitado"
                            )[:300],
                            "escalated_to_operator": True,
                            "escalation_reason": (
                                "RETRACTO_EXCLUDED_PRODUCTS"
                                if (_retracto_check
                                    and not _retracto_check.eligible
                                    and _retracto_check.excluded_items)
                                else "ORDER_DELIVERED"
                            ),
                            "legal_basis": "ley_1480_art_47",
                        }).execute()
                        supabase.table("orders").update({
                            "cancellation_id": _audit_id,
                        }).eq("id", target_order_id).eq(
                            "tenant_id", tenant_id,
                        ).execute()
                        logger.info(
                            "[RETRACTO] audit creado id=%s order=%s",
                            _audit_id[:8], target_order_id[:8],
                        )
                    except Exception as _e:
                        logger.warning(
                            "[RETRACTO] audit insert falló order=%s: %s",
                            target_order_id[:8], _e,
                        )
                    await _send_outbound_text(
                        supabase=supabase, conversation_id=conversation_id,
                        tenant_id=tenant_id, text=_retracto_msg,
                    )
                    try:
                        supabase.table("conversations").update({
                            "status": "human_takeover",
                        }).eq("id", conversation_id).eq(
                            "tenant_id", tenant_id,
                        ).execute()
                    except Exception:
                        pass
                    try:
                        from telegram_notifications import (
                            notify_escalation_async,
                        )
                        await notify_escalation_async(
                            supabase, tenant_id=tenant_id,
                            conversation_id=conversation_id,
                            reason=(
                                f"🚨 Retracto Ley 1480 — Pedido #{short_id}\n"
                                f"Cliente: \"{_cancel_match.reason_text[:200]}\"\n"
                                f"Acción: validar ventana 5d hábiles, generar "
                                f"etiqueta retorno, coordinar refund "
                                f"(30 días calendario máx Ley 1480)."
                            ),
                        )
                    except Exception:
                        pass
                    _mark_message_processing(
                        supabase, tenant_id, message_id,
                        processing_status=PROCESSING_STATUS_PROCESSED,
                    )
                    _resolve_and_persist_agentic_state(
                        supabase=supabase, tenant_id=tenant_id,
                        conversation_id=conversation_id, contact=contact,
                        history=history,
                    )
                    return
    except Exception as _can_exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] cancel_intent crashed: %s — skip", _can_exc,
        )

    # PRE-LLM #0.45: image request (rev. 109 UAT live BUG 18). Cliente
    # pide foto/imagen de producto → resolver determinístico envía la
    # imagen directamente sin que el LLM decida. El image_send_tool ya
    # existe (legacy), solo lo enganchamos al agentic dispatcher.
    # Rev. 109 fix UAT live BUG 26: skip si inbound es media — cliente
    # ESTÁ ENVIANDO un media, NO pidiendo que le mandemos uno.
    if content_type not in {"audio", "image", "video"}:
        try:
            from tools.image_send_tool import (
                handle_image_request_if_applicable as _handle_image_request,
            )
            _recent_msgs = (
                supabase.table("messages")
                .select("direction, content, content_type, created_at")
                .eq("conversation_id", conversation_id)
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True).limit(10).execute().data or []
            )
            _img_result = await _handle_image_request(
                supabase=supabase,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                query_text=content,
                recent_messages=_recent_msgs,
            )
            if _img_result.handled:
                customer_phone = _get_conversation_customer_phone(
                    supabase, tenant_id, conversation_id,
                )
                if _img_result.image_link:
                    # Rev. 109 fix BUG 27: send_whatsapp_message firma real es
                    # (to_phone, image_link, image_caption) — no media_url.
                    try:
                        from whatsapp_sender import send_whatsapp_message
                        await send_whatsapp_message(
                            tenant_id=tenant_id,
                            supabase=supabase,
                            to_phone=customer_phone,
                            image_link=_img_result.image_link,
                            image_caption=_img_result.image_caption or "",
                        )
                    except Exception as _img_exc:
                        logger.warning(
                            "[AGENTIC_PRE_LLM] image_send falló conv=%s: %s",
                            conversation_id[:8], _img_exc,
                        )
                elif _img_result.response_text:
                    await _send_outbound_text(
                        supabase=supabase, conversation_id=conversation_id,
                        tenant_id=tenant_id, text=_img_result.response_text,
                    )
                _mark_message_processing(
                    supabase, tenant_id, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                logger.info(
                    "[AGENTIC_PRE_LLM] image_request handled conv=%s link=%s",
                    conversation_id[:8], bool(_img_result.image_link),
                )
                _resolve_and_persist_agentic_state(
                    supabase=supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id, contact=contact,
                    history=history,
                )
                return
        except Exception as _img_exc:
            logger.warning(
                "[AGENTIC_PRE_LLM] image_request crashed: %s — skip", _img_exc,
            )

    # PRE-LLM #0.5: consent intent. Rev. 108 fix arquitectónico.
    # El LLM no llama record_consent confiablemente tras "Sí acepto",
    # causando loop infinito (no-pii-pre-consent invariant rewrites).
    # Determinístico: si último outbound del bot pidió consent + cliente
    # respondió afirmativo + contact existe → marca consent_given=True
    # + audit log directo. Skip si no aplica contexto.
    try:
        from agentic.consent_intent_resolver import detect_consent_intent
        # Leer último outbound del bot.
        last_out_q = (
            supabase.table("messages")
            .select("content")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .eq("direction", "outbound")
            .order("created_at", desc=True).limit(1).execute()
        )
        last_bot_msg = (
            (last_out_q.data or [{}])[0].get("content") or ""
        )
        consent_match = detect_consent_intent(content, last_bot_msg)
        if consent_match and contact_id:
            new_consent = consent_match["intent"] == "consent_granted"
            try:
                # A11 UAT fix: setear timestamps denormalizados al otorgar.
                # Antes solo se flipeaba consent_given → consent_date/consent_given_at
                # quedaban NULL (UI Tenant Console sin fecha + export SAR sin
                # "Otorgado en"). El audit log canónico SÍ los tenía, pero estas
                # columnas alimentan UI + reporte SAR Habeas Data.
                from datetime import datetime as _dt, timezone as _tz
                _consent_fields = {"consent_given": new_consent}
                if new_consent:
                    _now_iso = _dt.now(_tz.utc).isoformat()
                    _consent_fields["consent_date"] = _now_iso
                    _consent_fields["consent_given_at"] = _now_iso
                    # Re-grant tras revocación: limpiar marca de revocación.
                    _consent_fields["consent_revoked_at"] = None
                supabase.table("contacts").update(
                    _consent_fields
                ).eq("id", contact_id).eq("tenant_id", tenant_id).execute()
                # Audit log Habeas Data
                supabase.table("consent_audit_log").insert({
                    "tenant_id": tenant_id,
                    "contact_id": contact_id,
                    "event": "granted" if new_consent else "revoked",
                    "source": "whatsapp",
                    "conversation_id": conversation_id,
                    "evidence": {
                        "consent_text": content[:200],
                        "tool": "agentic.consent_intent_resolver",
                        "matched_pattern": consent_match.get("matched_pattern"),
                        "auto_detected": True,
                    },
                }).execute()
                logger.info(
                    "[AGENTIC_PRE_LLM] conv=%s consent_intent matched '%s' → "
                    "contact=%s consent_given=%s",
                    conversation_id, consent_match["intent"],
                    contact_id[:8], new_consent,
                )
                # Refrescar contact_record para que el resto del flow lo vea.
                contact = (
                    {**contact, "consent_given": new_consent}
                    if isinstance(contact, dict) else
                    {"consent_given": new_consent}
                )
            except Exception as exc:
                logger.warning(
                    "[AGENTIC_PRE_LLM] consent_intent persist falló conv=%s: %s",
                    conversation_id, exc,
                )
    except Exception as exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] consent_intent_resolver crashed: %s — skip", exc,
        )

    # PRE-LLM #0.7: carrier selection determinística.
    # Rev. 108 fix arquitectónico — el LLM no llama select_carrier
    # confiablemente cuando el cliente nombra un carrier post-quote.
    # Resultado: cart.shipping_cents=0 → resumen sin envío. Determinístico:
    # detecta nombre de carrier en inbound vs quoted_options del cart →
    # llama select_carrier_for_cart inline.
    try:
        from agentic.carrier_select_resolver import (
            detect_carrier_selection_intent,
        )
        # Reusar last_bot_msg que ya se leyó arriba (consent_intent_resolver).
        carrier_match = detect_carrier_selection_intent(
            supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=content,
            last_bot_outbound=last_bot_msg if 'last_bot_msg' in locals() else "",
        )
        # A8 #1 — solo si el agente activo permite select_carrier.
        if carrier_match and _agent_permits_tool(_agent, "select_carrier"):
            try:
                from agentic.legacy_adapters import select_carrier_for_cart
                sel = await select_carrier_for_cart(
                    supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    rate_id=carrier_match["rate_id"],
                    rate_data=carrier_match["rate_data"],
                )
                if sel and sel.get("ok"):
                    logger.info(
                        "[AGENTIC_PRE_LLM] conv=%s carrier_select detected "
                        "'%s' → persisted (confidence=%.2f)",
                        conversation_id,
                        carrier_match["carrier_code"],
                        carrier_match["confidence"],
                    )
                else:
                    logger.warning(
                        "[AGENTIC_PRE_LLM] carrier_select_for_cart failed conv=%s: %s",
                        conversation_id, sel,
                    )
            except Exception as exc:
                logger.warning(
                    "[AGENTIC_PRE_LLM] carrier_select persist falló conv=%s: %s",
                    conversation_id, exc,
                )
    except Exception as exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] carrier_select_resolver crashed: %s — skip", exc,
        )

    # PRE-LLM #1: purchase intent multi-producto. Casos típicos cliente:
    #   "Necesito 3 jabones coco 100g y un sérum hialurónico"
    #   "Quiero 2 aceites de almendras"
    # Bypass Gemini cuando el inbound tiene intent claro + productos
    # identificables. Gemini falla con STOP+empty para inbounds complejos.
    from agentic.purchase_intent_resolver import (
        try_resolve_purchase_intent, compose_outbound_from_resolution,
    )
    intent_resolution = try_resolve_purchase_intent(
        inbound_text=content,
        catalog=catalog,
    )
    # A8 #1 — el resolver solo entra si el agente activo permite add_to_cart
    # (un agente Claims/Support sin add_to_cart cae al LLM, que respeta su scope).
    if (intent_resolution
            and (intent_resolution.get("resolved") or intent_resolution.get("ambiguous"))
            and _agent_permits_tool(_agent, "add_to_cart")):
        from agentic.tools.cart import AddToCartTool, AddToCartArgs
        from agentic.tools.base import ToolContext
        tool = AddToCartTool()
        ctx = ToolContext(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            supabase=supabase,
            catalog_cache=catalog,
            logger=logger,
            extras={"recent_inbound_texts": [content], "bypass_variant_guard": True},
        )
        all_added = True
        added_results = []
        for item in intent_resolution.get("resolved") or []:
            args = AddToCartArgs(
                product_id=item["product_id"],
                variation_id=item["variation_id"],
                quantity=item["qty"],
            )
            try:
                res = await tool.execute(args, ctx)
            except Exception as exc:
                logger.warning(
                    "[AGENTIC_PRE_LLM] purchase_intent add_to_cart raise: %s",
                    exc,
                )
                all_added = False
                break
            added_results.append(res)
            if not res.success:
                all_added = False
                break

        if all_added:
            customer_name = (contact or {}).get("name") if contact else None
            # Solo primer nombre, más natural.
            if customer_name and " " in customer_name:
                customer_name = customer_name.split(" ", 1)[0]
            # ADR-0026 Pieza C: el path pre-LLM purchase deja de componer outbound
            # CIEGO (subtotal parcial + repreguntar ciudad). Recarga el cart real y usa
            # el renderizador canónico (Pieza B) con el destino persistido (Pieza A). Si
            # el add invalidó un envío con ciudad conocida, recotiza determinísticamente.
            if intent_resolution.get("ambiguous"):
                # Mix con variante ambigua: el foco es preguntar la variante; pasamos el
                # subtotal REAL del cart para no mostrar subtotal parcial.
                _cart_sub = None
                try:
                    from tools.cart_tool import get_cart_with_items as _gcwi
                    _cmix = _gcwi(supabase, conversation_id=conversation_id, tenant_id=tenant_id)
                    if _cmix:
                        _cart_sub = int(_cmix.get("subtotal_cents") or 0) // 100
                except Exception:
                    pass
                outbound = compose_outbound_from_resolution(
                    intent_resolution, customer_name=customer_name, cart_subtotal_cop=_cart_sub,
                )
            else:
                outbound = await _compose_purchase_outbound_canonical(
                    supabase=supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id, contact_id=contact_id,
                    contact=contact, customer_name=customer_name,
                    catalog=catalog, content=content, agent=_agent,
                    intent_resolution=intent_resolution,
                )
            logger.info(
                "[AGENTIC_PRE_LLM] conv=%s purchase_intent resolved=%d "
                "ambiguous=%d — bypaseando Gemini",
                conversation_id,
                len(intent_resolution.get("resolved") or []),
                len(intent_resolution.get("ambiguous") or []),
            )
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=outbound,
            )
            _mark_message_processing(
                supabase, tenant_id, message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            # Construir AgenticTurnResult sintético para el audit logger.
            from agentic.agent import AgenticTurnResult
            synthetic_result = AgenticTurnResult(
                outbound_text=outbound,
                tool_calls_executed=len(added_results),
                tool_call_log=[{
                    "tool": "add_to_cart",
                    "args": {
                        "product_id": it["product_id"],
                        "variation_id": it["variation_id"],
                        "quantity": it["qty"],
                    },
                    "result": r.data,
                } for it, r in zip(intent_resolution.get("resolved") or [], added_results)],
                finish_reason="DETERMINISTIC_RESOLVER",
            )
            _persist_turn_audit(
                supabase=supabase,
                mode="cutover",
                message_id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=content,
                result=synthetic_result,
                elapsed_s=0.0,
                final_text=outbound,
                invariant_outcome="ok",
                invariant_name="purchase_intent_bypass",
                system_prompt_chars=0,
                history_turns=len(history or []),
            )
            # Rev. 109 — actualizar agentic_state aun cuando el bypass
            # short-circuita el LLM (badge UI stays fresh).
            _resolve_and_persist_agentic_state(
                supabase=supabase, tenant_id=tenant_id,
                conversation_id=conversation_id, contact=contact,
                history=history,
            )
            return  # turn handled.
        else:
            logger.warning(
                "[AGENTIC_PRE_LLM] purchase_intent matched pero algún "
                "add_to_cart falló — caemos a Gemini"
            )

    # PRE-LLM #2: variant selection continuation (response corta a bot question).
    from agentic.variant_continuation import try_resolve_variant_continuation
    variant_match = try_resolve_variant_continuation(
        inbound_text=content,
        history=history,
        catalog=catalog,
    )
    if variant_match and _agent_permits_tool(_agent, "add_to_cart"):  # A8 #1
        logger.info(
            "[AGENTIC_PRE_LLM] conv=%s variant_continuation matched: "
            "product=%s variant=%s — bypaseando Gemini",
            conversation_id, variant_match["product_title"],
            variant_match["variant_label"],
        )
        from agentic.tools.cart import AddToCartTool, AddToCartArgs
        from agentic.tools.base import ToolContext
        tool = AddToCartTool()
        args = AddToCartArgs(
            product_id=variant_match["product_id"],
            variation_id=variant_match["variation_id"],
            quantity=1,
        )
        ctx = ToolContext(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            supabase=supabase,
            catalog_cache=catalog,
            logger=logger,
            extras={"recent_inbound_texts": [content], "bypass_variant_guard": True},
        )
        try:
            tool_result = await tool.execute(args, ctx)
        except Exception as exc:
            logger.warning(
                "[AGENTIC_PRE_LLM] variant_continuation add_to_cart falló: %s",
                exc,
            )
            tool_result = None

        if tool_result and tool_result.success:
            # Componer respuesta natural sin LLM.
            price_str = f"${int(variant_match['unit_price_cop']):,}".replace(
                ",", ".",
            )
            outbound = (
                f"Listo, agregué 1 *{variant_match['product_title']}* de "
                f"{variant_match['variant_label']} por *{price_str} COP* "
                f"a tu carrito.\n\n"
                f"Sumamos algo más al pedido o ya coordinamos el envío? "
                f"Dime a qué ciudad lo enviamos."
            )
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=outbound,
            )
            _mark_message_processing(
                supabase, tenant_id, message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            from agentic.agent import AgenticTurnResult
            synthetic_result = AgenticTurnResult(
                outbound_text=outbound,
                tool_calls_executed=1,
                tool_call_log=[{
                    "tool": "add_to_cart",
                    "args": args.model_dump(),
                    "result": tool_result.data,
                }],
                finish_reason="DETERMINISTIC_RESOLVER",
            )
            _persist_turn_audit(
                supabase=supabase,
                mode="cutover",
                message_id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=content,
                result=synthetic_result,
                elapsed_s=0.0,
                final_text=outbound,
                invariant_outcome="ok",
                invariant_name="variant_continuation_bypass",
                system_prompt_chars=0,
                history_turns=len(history or []),
            )
            _resolve_and_persist_agentic_state(
                supabase=supabase, tenant_id=tenant_id,
                conversation_id=conversation_id, contact=contact,
                history=history,
            )
            return  # turn handled — no LLM needed.
        else:
            logger.warning(
                "[AGENTIC_PRE_LLM] variant_continuation matched pero "
                "add_to_cart falló: %s — caemos a Gemini",
                getattr(tool_result, "data", None),
            )

    # PRE-LLM #3: shipping intent. Si cart tiene items + cliente
    # menciona ciudad colombiana inequívoca → quote_shipping directo.
    # Bug runtime UAT E2 2026-05-24: Gemini fallaba STOP+empty para
    # "envíalo a Medellín" → EmptyPromise rewrite a CTA genérico.
    from agentic.shipping_resolver import try_resolve_shipping_intent
    # Cart has items?
    cart_has_items = False
    try:
        cart_row = (
            supabase.table("conversation_carts")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .eq("status", "open")
            .limit(1).execute()
        )
        if cart_row.data:
            items_row = (
                supabase.table("conversation_cart_items")
                .select("id", count="exact", head=True)
                .eq("cart_id", cart_row.data[0]["id"])
                .eq("tenant_id", tenant_id)
                .execute()
            )
            cart_has_items = bool(getattr(items_row, "count", 0) or 0)
    except Exception:
        cart_has_items = False

    shipping_match = try_resolve_shipping_intent(
        inbound_text=content,
        cart_has_items=cart_has_items,
    )
    if shipping_match and _agent_permits_tool(_agent, "quote_shipping"):  # A8 #1
        logger.info(
            "[AGENTIC_PRE_LLM] conv=%s shipping_intent matched city=%s "
            "— bypaseando Gemini",
            conversation_id, shipping_match["city"],
        )
        from agentic.tools.shipping import QuoteShippingTool, QuoteShippingArgs
        from agentic.tools.base import ToolContext
        ship_tool = QuoteShippingTool()
        ship_args = QuoteShippingArgs(city=shipping_match["city"])
        ship_ctx = ToolContext(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            supabase=supabase,
            catalog_cache=catalog,
            logger=logger,
            extras={"recent_inbound_texts": [content]},
        )
        try:
            ship_result = await ship_tool.execute(ship_args, ship_ctx)
        except Exception as exc:
            logger.warning(
                "[AGENTIC_PRE_LLM] shipping_intent quote_shipping raise: %s",
                exc,
            )
            ship_result = None

        if ship_result and ship_result.success:
            opts = (ship_result.data or {}).get("options") or []
            if opts:
                # Compose outbound natural.
                customer_name = (contact or {}).get("name") if contact else None
                if customer_name and " " in customer_name:
                    customer_name = customer_name.split(" ", 1)[0]
                greeting = f"Perfecto, {customer_name}. " if customer_name else "Perfecto. "
                city_show = (ship_result.data or {}).get(
                    "destination", {}
                ).get("city") or shipping_match["city"]
                bullets = []
                for o in opts:
                    price = int(o.get("price_cop") or 0)
                    price_str = f"${price:,}".replace(",", ".")
                    eta = o.get("eta_date") or ""
                    eta_str = f" ({eta})" if eta else ""
                    bullets.append(
                        f"* *{o.get('carrier')}*{eta_str}: *{price_str} COP*"
                    )
                outbound = (
                    f"{greeting}Para el envío a *{city_show}*, tenemos estas opciones:\n\n"
                    + "\n".join(bullets)
                    + "\n\nCuál prefieres?"
                )

                # Rev. 108 Fase B fix arquitectónico — aplicar invariant
                # `payment_coherence` EN el bypass también. Antes el
                # bypass salteaba el pipeline de invariants, permitiendo
                # mostrar cotización sin que cliente haya definido modo
                # de pago. Eso oculta el costo real (COD puede diferir).
                # Rev. 109: PaymentMethodExplicit consolidado en PaymentCoherence.
                from agentic.invariants import (
                    PaymentCoherenceInvariant, InvariantOutcome,
                )
                payment_inv = PaymentCoherenceInvariant()
                inv_result = await payment_inv.validate(
                    candidate_text=outbound,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    contact_id=contact_id,
                    supabase=supabase,
                    tool_call_log=[{
                        "tool": "quote_shipping",
                        "args": {"city": shipping_match["city"]},
                        "result": ship_result.data,
                    }],
                    inbound_text=content,
                )
                if inv_result.outcome == InvariantOutcome.REWRITE:
                    outbound = inv_result.replacement_text or outbound
                    logger.info(
                        "[AGENTIC_PRE_LLM] payment_coherence REWRITE conv=%s "
                        "— preguntando modo de pago antes de cotizar",
                        conversation_id,
                    )

                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=outbound,
                )
                _mark_message_processing(
                    supabase, tenant_id, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                from agentic.agent import AgenticTurnResult
                synthetic_result = AgenticTurnResult(
                    outbound_text=outbound,
                    tool_calls_executed=1,
                    tool_call_log=[{
                        "tool": "quote_shipping",
                        "args": {"city": shipping_match["city"]},
                        "result": ship_result.data,
                    }],
                    finish_reason="DETERMINISTIC_RESOLVER",
                )
                _persist_turn_audit(
                    supabase=supabase,
                    mode="cutover",
                    message_id=message_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    inbound_text=content,
                    result=synthetic_result,
                    elapsed_s=0.0,
                    final_text=outbound,
                    invariant_outcome="ok",
                    invariant_name="shipping_intent_bypass",
                    system_prompt_chars=0,
                    history_turns=len(history or []),
                )
                _resolve_and_persist_agentic_state(
                    supabase=supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id, contact=contact,
                    history=history,
                )
                return
        else:
            logger.warning(
                "[AGENTIC_PRE_LLM] shipping_intent matched pero "
                "quote_shipping falló: %s — caemos a Gemini",
                getattr(ship_result, "data", None),
            )
    # ─── /pre-LLM resolver ───

    # ── Rev. 109 — Agentic State Machine (helper unificado) ──
    # Resolver determinístico del estado actual del Inbox.
    # Reutilizado por: el LLM path (para per-state prompt) Y los pre-LLM
    # bypass paths (purchase_intent / shipping_intent) para mantener
    # `conversations.agentic_state` siempre actualizado.
    _resolved_state = _resolve_and_persist_agentic_state(
        supabase=supabase,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact=contact,
        history=history,
    )
    # ─── /state machine ───

    # ── Rev. 109 Día 2 — Per-state prompt + tools subset ──
    # Si el resolver determinó un estado, usar el mini-prompt + subset
    # de tools. Reduce ~50-70% size del prompt + carga cognitiva LLM.
    # Fallback al monolito si falla la composición (defensa profundidad).
    _allowed_tools: Optional[set[str]] = None
    if _resolved_state is not None:
        try:
            from agentic.prompt import build_prompt_for_state, tools_for_state
            # ADR-0026 Pieza C — snapshot factual del carrito para el LLM (estados de
            # checkout): subtotal real + estado de envío + ciudad conocida → no inventa ni
            # repregunta. Falla-seguro: si no se puede leer, el prompt va sin el bloque.
            _cart_snapshot = None
            try:
                from agentic.prompt.builder import _CART_STATE_STATES
                if _resolved_state in _CART_STATE_STATES:
                    from tools.cart_tool import get_cart_with_items
                    from agentic.cart_render import render_cart_facts_for_llm
                    _csnap_cart = get_cart_with_items(
                        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    )
                    if _csnap_cart and _csnap_cart.get("items"):
                        _cart_snapshot = render_cart_facts_for_llm(_csnap_cart, contact)
            except Exception as _cs_exc:
                logger.warning("[ADR0026] cart_snapshot LLM falló: %s", _cs_exc)
            system_prompt = build_prompt_for_state(
                state=_resolved_state,
                tenant_name=tenant_name,
                tenant_pitch=tenant_pitch,
                tenant_tone=tenant_tone,
                catalog=catalog,
                contact_record=contact or {},
                carriers=carriers_caps,
                payment_methods=payment_methods_cfg,
                active_coupons=active_coupons,
                cart_snapshot=_cart_snapshot,
                # Fase 0 finiquito 2026-06-23 — V3 per-state recibe los 6 kwargs
                # business_ops (root-cause analysis wujbdgrhk). Cierra bug verificado
                # runtime trace 2026-06-23T17:39 HAS_BUSINESS_OPS_MARKER:False — bot
                # improvisaba horarios/despacho/sedes/redes porque V3 NO los recibía.
                # Inyectados solo en _BUSINESS_OPS_STATES (decisión Q3).
                shipping_origin=tenant_shipping_origin,
                store_locations=tenant_store_locations,
                store_type=tenant_store_type,
                support_schedule=tenant_support_schedule,
                social_links=tenant_social_links,
                after_hours_message=tenant_after_hours_message,
            )
            _allowed_tools = set(tools_for_state(_resolved_state))
            logger.info(
                "[AGENTIC_PER_STATE] conv=%s state=%s prompt=%dch tools=%d",
                conversation_id[:8], _resolved_state.value,
                len(system_prompt), len(_allowed_tools),
            )
        except Exception as _ps_exc:
            logger.warning(
                "[AGENTIC_PER_STATE] build falló conv=%s state=%s: %s — "
                "fallback a monolito",
                conversation_id[:8], _resolved_state.value, _ps_exc,
            )
            _allowed_tools = None  # monolito = todas las tools

    # A8 #2 finiquito (audit §6) — fsm_states_allowed enforcement + tools
    # intersection del agente activo. Helper puro testeable (ver
    # _compute_agent_allowed_tools): si el estado resuelto está fuera del subset
    # de estados del agente, NO se aplica su restricción de tools este turn.
    _allowed_tools, _agent_out_of_state = _compute_agent_allowed_tools(
        _allowed_tools, _agent, _resolved_state,
    )
    if _agent_out_of_state:
        logger.warning(
            "[AGENTIC_FSM_STATES] conv=%s agent=%s estado=%s FUERA de "
            "fsm_states_allowed — ignorando restricción de tools del agente "
            "este turn (sirve con toolset del estado)",
            conversation_id[:8], _agent.get("name") or "?",
            _resolved_state.value if _resolved_state else "?",
        )
    elif isinstance(_allowed_tools, set):
        logger.info(
            "[AGENTIC_AGENT_TOOLS] conv=%s agent=%s tools_allowed=%d",
            conversation_id[:8], _agent.get("name") or "?", len(_allowed_tools),
        )
    # ─── /per-state ───

    # Ejecutar agente.
    started_at = time.monotonic()
    result = await run_agentic_turn(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        inbound_text=content,
        contact_record=contact or {},
        catalog=catalog,
        history=history,
        supabase=supabase,
        system_prompt=system_prompt,
        allowed_tools=_allowed_tools,
    )
    elapsed = time.monotonic() - started_at

    # ── Rev. 109 UAT live BUG 8 — re-marcar COD post-LLM ─────────────
    # Si el cliente expresó intent COD en este turn pero el cart no
    # existía PRE-LLM (typical: cliente NUEVO dice "comprar X contraentrega"
    # en 1 mensaje), el cod_intent_resolver no pudo marcar el cart. Ahora
    # que add_to_cart YA creó el cart, lo marcamos como cod.
    try:
        from agentic.cod_intent_resolver import detect_cod_intent
        if detect_cod_intent(content):
            _cart_post = (
                supabase.table("conversation_carts")
                .select("id, payment_method")
                .eq("conversation_id", conversation_id)
                .eq("tenant_id", tenant_id)
                .in_("status", ["open", "checkout"])
                .order("created_at", desc=True).limit(1).execute()
            )
            if _cart_post.data and _cart_post.data[0].get("payment_method") != "cod":
                # Verificar que tenant TIENE COD enabled antes de marcar.
                try:
                    from lib.tenant_payment_methods import is_method_enabled
                    if is_method_enabled(supabase, tenant_id=tenant_id, method="cod"):
                        supabase.table("conversation_carts").update({
                            "payment_method": "cod",
                        }).eq("id", _cart_post.data[0]["id"]).eq("tenant_id", tenant_id).execute()
                        logger.info(
                            "[AGENTIC_POST_LLM] conv=%s cart=%s marked COD "
                            "post-LLM (intent detected pre, cart created during)",
                            conversation_id[:8], _cart_post.data[0]["id"][:8],
                        )
                except Exception:
                    pass
    except Exception as _cod_exc:
        logger.warning(
            "[AGENTIC_POST_LLM] cod re-mark falló conv=%s: %s",
            conversation_id[:8], _cod_exc,
        )
    # ── /COD post-LLM ──

    # Snapshot pre-invariants — usado para persistir audit incluso si el
    # flow termina temprano (degraded text sin invariants completos).
    system_prompt_chars = len(system_prompt or "")
    history_turns = len(history or [])

    # Rev. 107: manejo activo de empty_output en agent.py — si el agentic
    # produce outbound_text (incluso degraded), confiamos en él. Solo si
    # `result.error` está set (excepción real Gemini) o outbound vacío SIN
    # error (escenario inesperado) caemos a legacy.
    if result.error and not result.outbound_text:
        # Excepción real Gemini (network/api error) — ahí sí ERROR + fallback.
        raise RuntimeError(f"agentic_failed: {result.error}")
    if not result.outbound_text:
        # Escenario inesperado (no error, no texto). Loggear y fallback.
        logger.warning(
            "[AGENTIC_DISPATCH] empty outbound sin error tenant=%s conv=%s "
            "truncated=%s reason=%s — fallback a legacy",
            tenant_id, conversation_id, result.truncated, result.truncated_reason,
        )
        raise RuntimeError("agentic_failed: empty_output_unexpected")
    if result.truncated and result.truncated_reason and \
            result.truncated_reason.startswith("empty_output:"):
        # Recovery se activó (degraded text al cliente). Log INFO honesto.
        logger.info(
            "[AGENTIC_RECOVERY] conv=%s reason=%s → degraded response enviada",
            conversation_id, result.truncated_reason,
        )

    # 2026-06-26 (founder, recotización DETERMINÍSTICA): si un tool mutó el carrito
    # ESTE turno y el envío quedó pendiente de recotizar CON una ciudad conocida,
    # recotizamos automáticamente y REEMPLAZAMOS el outbound del LLM con las opciones
    # reales (total correcto + ciudad conocida). Cierra el rough edge del add-a-mitad
    # de checkout (el LLM decía un subtotal de display equivocado + "a qué ciudad").
    if not getattr(result, "requires_silent_escalation", False):
        try:
            _CART_MUT = {"add_to_cart", "update_cart_item_quantity", "remove_cart_item"}
            _mutated = any(
                c.get("tool") in _CART_MUT and "error" not in (c.get("result") or {})
                for c in (result.tool_call_log or [])
            )
            if _mutated:
                _rq = (
                    supabase.table("conversation_carts")
                    .select("requires_requote, shipping_meta")
                    .eq("tenant_id", tenant_id)
                    .eq("conversation_id", conversation_id)
                    .in_("status", ["open", "checkout"])
                    .order("updated_at", desc=True).limit(1).execute()
                )
                _rqrow = (_rq.data or [{}])[0]
                _known_city = (_rqrow.get("shipping_meta") or {}).get("city")
                if _rqrow.get("requires_requote") and _known_city:
                    from agentic.tools.shipping import QuoteShippingTool, QuoteShippingArgs
                    from agentic.tools.base import ToolContext
                    _rqctx = ToolContext(
                        tenant_id=tenant_id, conversation_id=conversation_id,
                        contact_id=contact_id, supabase=supabase,
                        catalog_cache=catalog, logger=logger,
                        extras={"recent_inbound_texts": [content]},
                    )
                    _rqres = await QuoteShippingTool().execute(
                        QuoteShippingArgs(city=_known_city), _rqctx)
                    _opts = (_rqres.data or {}).get("options") or [] if (_rqres and _rqres.success) else []
                    if _opts:
                        _bul = []
                        for _o in _opts:
                            _p = int(_o.get("price_cop") or 0)
                            _ps = f"${_p:,}".replace(",", ".")
                            _eta = _o.get("eta_date") or ""
                            _bul.append(
                                f"* *{_o.get('carrier')}*{f' ({_eta})' if _eta else ''}: *{_ps} COP*")
                        _city_show = (_rqres.data or {}).get("destination", {}).get("city") or _known_city
                        result.outbound_text = (
                            f"Listo, actualicé tu pedido. Como cambió el contenido, recalculé "
                            f"el envío a *{_city_show}*:\n\n" + "\n".join(_bul) + "\n\n¿Cuál prefieres?"
                        )
                        logger.info(
                            "[AGENTIC_REQUOTE] auto-recotización post-mutación conv=%s city=%s opts=%d",
                            conversation_id, _known_city, len(_opts),
                        )
        except Exception as _rqexc:
            logger.warning("[AGENTIC_REQUOTE] auto-requote falló: %s", _rqexc)

    # Aplicar invariants Python (anti-hallu + style + flow guards).
    # Orden importa:
    #   1. cart_state + consent (semánticos: anti-hallu de cart/PII)
    #   2. summary_coherence (semántico: total/items vs cart real DB)
    #   3. passive_closing (semántico: rewrite cierre pasivo → CTA por estado)
    #   4. no_emoji (cosmético: strip sobre el texto final)
    #
    # IMPORTANTE rev. 107 (2026-05-24): si el agente activó
    # `requires_silent_escalation`, el `outbound_text` es el mensaje
    # degraded determinístico ("déjame revisar con mi equipo") — NO un
    # output del LLM normal. Los invariants semánticos (cart_state,
    # empty_promise, passive_closing) podrían rewritearlo y sabotear la
    # escalación silenciosa. Solo aplicamos cosméticos (no_emoji).
    is_silent_escalation = getattr(result, "requires_silent_escalation", False)
    if is_silent_escalation:
        invariant_set = [
            NoInternalsExposureInvariant(),
            NoDecorativeEmojiInvariant(),
        ]
    else:
        invariant_set = [
            # Rev. 108 CONSOLIDADO (founder 2026-05-27) — cart render
            # coherence: 4 cases (cart-state coherente con tool, items
            # affirmed vs real, add_to_cart pricing, category completeness).
            CartRenderCoherenceInvariant(),
            ConsentRequiredInvariant(),
            # Rev. 108 CONSOLIDADO — payment coherence: 2 cases (cliente
            # debe especificar modo antes de pago, outbound léxico
            # coherente con cart.payment_method).
            PaymentCoherenceInvariant(),
            # A11 2026-06-26 — ANTES de SummaryCoherence: si el envío está
            # pendiente de recotizar (item agregado a mitad de checkout invalidó
            # el envío), el bot NO debe presentar resumen/total sin envío
            # (Total=Subtotal engaña). Reescribe a recotizar. Principio #4.
            RequotePendingSummaryInvariant(),
            SummaryCoherenceInvariant(),
            PIICoherenceInvariant(),
            # Rev. 109 UAT live BUG 19: bot afirma "guardé X" sin invocar tool.
            PIISaveTruthfulnessInvariant(),
            PostToolCoherenceInvariant(),
            EmptyPromiseInvariant(),
            # Rev. 109 founder 2026-05-28 "super delicado" — detecta fake
            # escalation (LLM promete especialista sin invocar tool) y
            # FUERZA el side-effect real para garantizar atención humana.
            FakeEscalationInvariant(),
            PassiveClosingInvariant(),
            # Rev. 109 UAT live — normaliza variaciones del LLM al naming
            # canónico de categorías (Sérums Faciales → Sérums, Kits de
            # Cuidado → Kits). Aplica SOLO en outbounds que listen
            # categorías; no toca textos de cotización/pago/etc.
            CanonicalCategoriesInvariant(),
            # A11 2026-06-26 — verdad transaccional de variantes (principio #4):
            # si el bot afirma falsamente "solo X presentación" / niega una
            # variante que SÍ está en stock, lo reescribe a la verdad completa
            # consultando el catálogo real (cierra el hueco de _NO_CATALOG_STATES
            # donde el prompt omite el catálogo en checkout). ADR-0024 binario.
            VariantAvailabilityAssertionInvariant(),
            # A11 2026-06-26 — red de contenido final: el bot NUNCA expone su
            # mecánica interna (KB/sistema/catálogo) al cliente. Después de los
            # invariants de correctitud (sus rewrites ya son exposure-free),
            # antes del cosmético.
            NoInternalsExposureInvariant(),
            NoDecorativeEmojiInvariant(),
        ]
    invariant_result = await apply_invariants(
        invariant_set,
        candidate_text=result.outbound_text,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        supabase=supabase,
        tool_call_log=result.tool_call_log,
        inbound_text=content,
    )
    final_text = (
        invariant_result.replacement_text
        if invariant_result.outcome != InvariantOutcome.OK
        else result.outbound_text
    )

    # A11 2026-06-26 — OBSERVABILIDAD: trace estructurado por turno (1 línea
    # greppable). Hace visible la decisión del bot — estado FSM resuelto, tools
    # invocados, invariant que intervino, si hubo rewrite — para diagnosticar
    # incoherencias al instante (antes había que leer código). Lo consume también
    # el harness adversarial (scripts/uat/coherence_scenarios.py).
    try:
        _trace_tools = [t.get("tool") for t in (result.tool_call_log or [])]
        _trace_inv = (
            f"{invariant_result.invariant_name}:{invariant_result.outcome.value}"
            if invariant_result.outcome != InvariantOutcome.OK else "ok"
        )
        logger.info(
            "[AGENTIC_TRACE] conv=%s state=%s tools=%s invariant=%s rewrote=%s",
            conversation_id[:8],
            getattr(_resolved_state, "value", None) or "fallback",
            _trace_tools,
            _trace_inv,
            invariant_result.outcome != InvariantOutcome.OK,
        )
    except Exception:
        pass  # el trace NUNCA debe romper el turno

    # Enviar outbound al cliente.
    await _send_outbound_text(
        supabase=supabase,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        text=final_text,
    )
    _mark_message_processing(
        supabase, tenant_id, message_id,
        processing_status=PROCESSING_STATUS_PROCESSED,
    )

    # Rev. 107 founder feedback: si el agente agotó recoveries y produjo
    # mensaje degraded ("déjame revisar con mi equipo"), escalar
    # silenciosamente para que un especialista del equipo intervenga.
    # Evita el patrón "bot mudo" — el cliente percibe que algo se está
    # gestionando con humanos, no que el bot falló.
    if getattr(result, "requires_silent_escalation", False):
        try:
            supabase.table("conversations").update({
                "status": "human_takeover",
            }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
            logger.info(
                "[AGENTIC_DISPATCH] silent_escalation conv=%s reason=%s — "
                "operador debe intervenir",
                conversation_id[:8],
                result.truncated_reason,
            )
            # Best-effort notificación al operador.
            try:
                from telegram_notifications import notify_escalation_async
                await notify_escalation_async(
                    supabase,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    reason=(
                        f"silent_escalation: agentic agotó recoveries "
                        f"({result.truncated_reason})"
                    ),
                )
            except Exception:
                pass
        except Exception as exc:
            logger.warning(
                "[AGENTIC_DISPATCH] silent_escalation falló conv=%s: %s",
                conversation_id[:8], exc,
            )

    # Audit log estructurado del tool_call_log completo (production-grade
    # observability — sin esto los bugs runtime son ciegos).
    for idx, call in enumerate(result.tool_call_log):
        result_data = call.get("result") or {}
        is_failure = "error" in result_data
        log_fn = logger.warning if is_failure else logger.info
        log_fn(
            "[AGENTIC_TOOL] conv=%s call[%d]=%s success=%s result=%s",
            conversation_id[:8], idx, call.get("tool"),
            not is_failure,
            json.dumps(result_data, default=str)[:300],
        )

    logger.info(
        "[AGENTIC_FULL] conv=%s tools=%d elapsed=%.2fs invariant=%s finish=%s",
        conversation_id[:8], result.tool_calls_executed, elapsed,
        invariant_result.invariant_name, result.finish_reason,
    )

    # Persistir audit DESPUÉS de enviar outbound (rev. 107 cierre arquitectónico).
    # Aunque el send falle abajo, el audit habrá sido escrito — más útil
    # tener registro de "intentamos enviar X" que no tener nada.
    _persist_turn_audit(
        supabase,
        mode="cutover",
        message_id=message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        inbound_text=content,
        result=result,
        elapsed_s=elapsed,
        final_text=final_text,
        invariant_outcome=invariant_result.outcome.value
        if hasattr(invariant_result.outcome, "value")
        else str(invariant_result.outcome),
        invariant_name=invariant_result.invariant_name,
        system_prompt_chars=system_prompt_chars,
        history_turns=history_turns,
    )


# ─── Agentic shadow path (Fase B) ──────────────────────────────────────────


async def _run_agentic_shadow_safe(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """Wrapper de shadow con timeout + try/except — NUNCA propaga error."""
    try:
        await asyncio.wait_for(
            _run_agentic_shadow(
                supabase,
                message_id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                content=content,
                content_type=content_type,
            ),
            timeout=AGENTIC_SHADOW_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[AGENTIC_SHADOW] timeout conv=%s — descartado",
            conversation_id[:8],
        )
    except Exception as exc:
        logger.warning(
            "[AGENTIC_SHADOW] error conv=%s: %s — descartado (legacy OK)",
            conversation_id[:8], exc,
        )


async def _run_agentic_shadow(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """Shadow: agentic compone respuesta SILENCIOSA + loggea para comparar."""
    import agentic.tools.catalog  # noqa: F401
    import agentic.tools.cart  # noqa: F401
    import agentic.tools.contact  # noqa: F401
    import agentic.tools.shipping  # noqa: F401
    import agentic.tools.payment  # noqa: F401
    import agentic.tools.escalation  # noqa: F401
    import agentic.tools.claims  # noqa: F401  # Rev. 109 founder 2026-05-28

    from agentic.agent import run_agentic_turn
    from agentic.system_prompt import build_system_prompt
    from orchestrator import (
        _get_conversation_history,
        _fetch_contact_for_phone,
        _get_conversation_customer_phone,
    )
    from tools.catalog_tool import get_tenant_catalog

    catalog = await get_tenant_catalog(supabase, tenant_id)
    history = await _get_conversation_history(supabase, tenant_id, conversation_id)
    customer_phone = _get_conversation_customer_phone(supabase, tenant_id, conversation_id)
    if customer_phone:
        contact_id, contact = _fetch_contact_for_phone(supabase, tenant_id, customer_phone)
    else:
        contact_id, contact = None, {}

    # Rev. 109 backlog #2 — Multi-agente per-tenant en shadow path también.
    try:
        from lib.tenant_agents import get_active_agent
        _agent_shadow = get_active_agent(supabase, tenant_id=tenant_id)
    except Exception:
        _agent_shadow = {"name": "Sara Camila"}

    system_prompt = build_system_prompt(
        tenant_name=os.getenv("TENANT_DEFAULT_NAME", "el negocio"),
        catalog=catalog,
        agent_name=_agent_shadow.get("name") or "Sara Camila",
        agent_role_description=_agent_shadow.get("role_description"),
    )

    started_at = time.monotonic()
    result = await run_agentic_turn(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        inbound_text=content,
        contact_record=contact or {},
        catalog=catalog,
        history=history,
        supabase=supabase,
        system_prompt=system_prompt,
    )
    elapsed_s = time.monotonic() - started_at

    _persist_turn_audit(
        supabase,
        mode="shadow",
        message_id=message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        inbound_text=content,
        result=result,
        elapsed_s=elapsed_s,
        final_text=None,                # shadow no envía outbound → no hay final post-invariant
        invariant_outcome=None,
        invariant_name=None,
        system_prompt_chars=len(system_prompt or ""),
        history_turns=len(history or []),
    )

    logger.info(
        "[AGENTIC_SHADOW] conv=%s tools=%d elapsed=%.2fs truncated=%s finish=%s",
        conversation_id[:8], result.tool_calls_executed, elapsed_s,
        result.truncated, result.finish_reason,
    )


# ─── State machine helper unificado (rev. 109) ─────────────────────────────


def _resolve_and_persist_agentic_state(
    *,
    supabase: Any,
    tenant_id: str,
    conversation_id: str,
    contact: Optional[dict],
    history: Optional[list],
) -> Optional[Any]:
    """Resuelve + persiste el estado agentic en `conversations.agentic_state`.

    Reutilizable por:
      • El LLM path principal (per-state prompt + tools subset).
      • Los pre-LLM bypass paths (purchase_intent / shipping_intent /
        cod_intent) — mantiene el badge UI fresco aun cuando el LLM no
        se invoca.

    NO bloquea ningún turno si falla. Defensive a:
      • Migration `agentic_state` column pendiente en remote (skip persist).
      • Schema mismatches en cart (skip cart-derived rules).

    Returns:
      AgenticState resuelto o None si el resolver falla.
    """
    try:
        from agentic.state_machine import StateResolver
        from agentic.state_machine.resolver import build_context_from_records

        try:
            _conv_row = (
                supabase.table("conversations")
                .select("status, agentic_state")
                .eq("id", conversation_id)
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            _has_state_column = True
        except Exception:
            _conv_row = (
                supabase.table("conversations")
                .select("status")
                .eq("id", conversation_id)
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            _has_state_column = False
        _conv = _conv_row.data or {}

        _cart_row = (
            supabase.table("conversation_carts")
            .select(
                "id, status, payment_method, shipping_cents, shipping_meta, "
                "converted_order_id"
            )
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .in_("status", ["open", "checkout"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        _cart = (_cart_row.data or [None])[0]
        if _cart:
            _meta = _cart.get("shipping_meta") or {}
            _cart["carrier_code"] = _meta.get("carrier") or None
            _cart["payment_link"] = None
            _items_count_row = (
                supabase.table("conversation_cart_items")
                .select("id", count="exact", head=True)
                .eq("cart_id", _cart["id"])
                .eq("tenant_id", tenant_id)
                .execute()
            )
            _cart["items_count"] = int(
                getattr(_items_count_row, "count", 0) or 0
            )
            if _cart.get("status") == "checkout" and _cart.get("converted_order_id"):
                _cart["payment_link"] = "checkout"

        # FIX A11: cargar la última orden + su pago para que POST_PAYMENT sea
        # ALCANZABLE. Antes order/payment nunca se pasaban → has_active_order
        # siempre False → el estado post-venta (resolver.py regla 2) era dead.
        # Scope SEGURO: solo cuando NO hay cart activo con items, así una orden
        # vieja aprobada NO empuja a POST_PAYMENT mientras el cliente arma un
        # pedido NUEVO (POST_PAYMENT precede a las reglas de cart). Tras
        # confirmar orden el cart pasa a 'converted' (orders.py:560) → sale del
        # filtro [open,checkout] → _cart None → se carga la orden. Defensivo.
        _order = None
        _payment = None
        _cart_items_for_order = int((_cart or {}).get("items_count") or 0)
        if not _cart or _cart_items_for_order == 0:
            try:
                _order_row = (
                    supabase.table("orders")
                    .select("id, status")
                    .eq("conversation_id", conversation_id)
                    .eq("tenant_id", tenant_id)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                _order = (_order_row.data or [None])[0]
                if _order:
                    _pay_row = (
                        supabase.table("payments")
                        .select("status")
                        .eq("order_id", _order["id"])
                        .eq("tenant_id", tenant_id)
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    _payment = (_pay_row.data or [None])[0]
            except Exception:
                _order = None
                _payment = None

        _ctx = build_context_from_records(
            conversation=_conv,
            cart=_cart,
            contact=contact or {},
            order=_order,
            payment=_payment,
            history_len=len(history or []),
        )
        _state = StateResolver().resolve(_ctx)
        _prev_state = _conv.get("agentic_state")
        if _has_state_column and _state.value != _prev_state:
            try:
                supabase.table("conversations").update(
                    {"agentic_state": _state.value}
                ).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
            except Exception as _upd_exc:
                logger.warning(
                    "[AGENTIC_STATE] update failed conv=%s: %s",
                    conversation_id[:8], _upd_exc,
                )
            logger.info(
                "[AGENTIC_STATE] conv=%s %s→%s (cart_items=%s consent=%s)",
                conversation_id[:8],
                _prev_state or "NULL",
                _state.value,
                _ctx.cart_items_count,
                _ctx.contact_consent_given,
            )
        elif not _has_state_column:
            logger.info(
                "[AGENTIC_STATE] conv=%s state=%s (column ausente)",
                conversation_id[:8], _state.value,
            )
        return _state
    except Exception as _state_exc:
        logger.warning(
            "[AGENTIC_STATE] resolver falló conv=%s: %s",
            conversation_id[:8], _state_exc,
        )
        return None


# ─── Persistencia universal de audit (rev. 107) ────────────────────────────


def _persist_turn_audit(
    supabase: Any,
    *,
    mode: str,                          # 'shadow' | 'cutover'
    message_id: Optional[str],
    tenant_id: str,
    conversation_id: str,
    inbound_text: str,
    result: Any,                        # AgenticTurnResult
    elapsed_s: float,
    final_text: Optional[str],
    invariant_outcome: Optional[str],
    invariant_name: Optional[str],
    system_prompt_chars: Optional[int],
    history_turns: Optional[int],
) -> None:
    """Persiste el audit del turn en `agentic_shadow_log`.

    Best-effort: si falla, loggea WARNING pero NO afecta al cliente. La
    pérdida de un audit es preferible a interrumpir el flow de respuesta.

    `mode`:
      • 'shadow' → legacy responde al cliente, agentic loggea silencioso.
      • 'cutover' → agentic respondió al cliente (Fase C).

    Captura `finish_reason` desde `result.finish_reason` (rev. 107) lo que
    permite diagnosticar empty_output sin depender de logs stdout.
    """
    try:
        row = {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "mode": mode,
            "inbound_text": (inbound_text or "")[:500],
            "agentic_outbound": (result.outbound_text or "")[:2000],
            "tool_calls_executed": result.tool_calls_executed,
            "tool_call_log": json.dumps(result.tool_call_log[:30]),
            "truncated": result.truncated,
            "truncated_reason": result.truncated_reason,
            "error": result.error,
            "elapsed_seconds": round(elapsed_s, 3),
            "finish_reason": result.finish_reason,
            "invariant_outcome": invariant_outcome,
            "invariant_name": invariant_name,
            "final_text": (final_text or "")[:2000] if final_text else None,
            "system_prompt_chars": system_prompt_chars,
            "history_turns": history_turns,
        }
        supabase.table("agentic_shadow_log").insert(row).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    except Exception as exc:
        logger.warning(
            "[AGENTIC_AUDIT] persist falló mode=%s conv=%s: %s",
            mode, conversation_id[:8], exc,
        )


# ─── Gate de conversation status (Rev. 107) ────────────────────────────────


_SKIP_STATUSES = frozenset({"human_takeover", "closed", "opted_out"})


def _should_skip_for_conv_status(supabase: Any, tenant_id: str, conversation_id: str) -> bool:
    """True si la conv está en estado donde el bot NO debe responder.

    Estados de skip:
      • human_takeover — el operador tomó la conv (rev. 107).
      • closed — conv archivada manualmente o por timeout.
      • opted_out — cliente revocó consent (Habeas Data Ley 1581).
        Fix founder 2026-05-28: el bot debe respetar opt-out EN CUALQUIER
        SITUACIÓN, no solo cuando llega un STOP. Combinado con el gate del
        connector (db_persistence._upsert_conversation), garantiza que un
        cliente revocado nunca recibe respuesta auto del bot — solo humano
        puede re-engagement manual desde Inbox.

    Best-effort lectura — si falla, NO skipea (default: dejar pasar para
    que el legacy aplique su propio gate como segunda defensa).
    """
    try:
        res = (
            supabase.table("conversations")
            .select("status")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return False
        status = (rows[0].get("status") or "").lower()
        return status in _SKIP_STATUSES
    except Exception as exc:
        logger.warning(
            "[AGENTIC_DISPATCH] error leyendo conv status %s: %s — default no-skip",
            conversation_id[:8], exc,
        )
        return False


def _mark_message_skipped(supabase: Any, tenant_id: str, message_id: str) -> None:
    """Marca el message como skipped por status conv (human_takeover /
    closed / opted_out). Mismo behavior que el path legacy."""
    try:
        supabase.table("messages").update({
            "processing_status": "skipped",
            "skip_reason": "conv_status_no_bot",
            "processed": True,
        }).eq("id", message_id).eq("tenant_id", tenant_id).execute()
        logger.info(
            "[AGENTIC_DISPATCH] msg=%s skipped (conv status no-bot)",
            message_id[:8],
        )
    except Exception as exc:
        logger.warning(
            "[AGENTIC_DISPATCH] error marcando msg=%s skipped: %s",
            message_id[:8], exc,
        )


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


def _agent_permits_tool(agent, tool_name: str) -> bool:
    """A8 #1 — True si el agente activo permite ejecutar `tool_name` en un
    resolver pre-LLM.

    SEGURO POR CONSTRUCCIÓN: un agente sin `tools_allowed` (None = agente
    default, caso KAIU single-agent) permite TODO → cero cambio de
    comportamiento. Solo restringe cuando `tools_allowed` es una lista explícita
    (multi-agente). El handoff sintético (tools_allowed=[]) no permite ninguna
    tool pre-LLM (correcto: solo debe emitir el mensaje de handoff).

    Cierra audit §1 #8: antes los resolvers pre-LLM (purchase_intent→add_to_cart,
    carrier_select, coupon, cancel, shipping, recipient) ejecutaban su tool ANTES
    de que el dispatcher intersectara `agent.tools_allowed` → un agente Claims
    sin add_to_cart podía agregar al carrito vía el resolver.
    """
    if not isinstance(agent, dict):
        return True
    allowed = agent.get("tools_allowed")
    if allowed is None:
        return True  # agente default — sin restricción
    return tool_name in {str(t) for t in (allowed or [])}


def _compute_agent_allowed_tools(state_tools, agent, resolved_state):
    """A8 #2 — combina el toolset del estado con la restricción del agente activo.

    - Si el agente tiene `fsm_states_allowed` y el estado resuelto está FUERA →
      out_of_state=True y NO se aplica su restricción de tools (se devuelve
      state_tools tal cual; el cliente se sirve con el toolset del estado).
      Decisión low-touch no-disruptiva (vs downgrade GREETING / escalar).
    - Si el agente está en-estado (o sin restricción de estados) y tiene
      `tools_allowed` → se intersecta con state_tools (Support nunca expone
      add_to_cart aunque el estado lo permita).

    Helper puro (sin side-effects) → testeable. Retorna (allowed_tools, out_of_state).
    """
    out_of_state = bool(
        isinstance(agent, dict)
        and agent.get("fsm_states_allowed") is not None
        and resolved_state is not None
        and resolved_state.value not in agent.get("fsm_states_allowed")
    )
    agent_tools = agent.get("tools_allowed") if isinstance(agent, dict) else None
    if agent_tools and isinstance(agent_tools, list) and not out_of_state:
        agent_set = {str(t) for t in agent_tools if t}
        if state_tools is None:
            return agent_set, out_of_state
        return (state_tools & agent_set), out_of_state
    return state_tools, out_of_state


# ─── Opt-out gate (Rev. 109 founder 2026-05-29) ─────────────────────────────


def _get_conversation_status_safe(supabase: Any, tenant_id: str, conversation_id: str) -> str:
    """Lee status conv silencioso — usado por opt-out gate post-handle."""
    try:
        res = (
            supabase.table("conversations")
            .select("status")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return (rows[0].get("status") or "").lower() if rows else ""
    except Exception:
        return ""


def _optout_failclosed_should_skip(content: Any) -> bool:
    """A11 audit (Clase C — fail-closed): tras un error en el handler de opt-out,
    ¿NO responder (silencio) en vez de avanzar al LLM?

    Sí cuando el contenido era un keyword de opt-out (STOP/BAJA/CANCELAR):
    responder a quien pidió parar viola Habeas Data Ley 1581 Art.9 + Meta
    Business Policy. Ante incertidumbre por error, esa es la dirección segura.
    Cheap y sin DB (solo regex) — no puede empeorar el fallo original.
    """
    try:
        from lib.whatsapp_optout import is_optout_keyword  # noqa: PLC0415
        return bool(is_optout_keyword(content))
    except Exception:
        return False


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

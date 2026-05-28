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
    # Gate de conversation status — rev. 107 cierre runtime KAIU 2026-05-23.
    # El bot legacy ya tenía este gate en orchestrator.py:6754, pero el
    # agentic dispatcher saltaba al `_run_agentic_full` SIN verificar.
    # Resultado: bot respondía a mensajes en conv human_takeover/closed
    # sobre-escribiendo la intervención del operador.
    if _should_skip_for_conv_status(supabase, conversation_id):
        _mark_message_skipped(supabase, message_id)
        return

    agentic_enabled = await is_tenant_agentic_enabled(supabase, tenant_id)

    if agentic_enabled:
        # Cutover: agentic responde al cliente.
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
            # Fallback a legacy si agentic crashea (defensa en producción).
            logger.error(
                "[AGENTIC_DISPATCH] agentic full falló tenant=%s conv=%s: %s — "
                "fallback a legacy",
                tenant_id, conversation_id, exc,
                exc_info=True,
            )
            # cae al legacy abajo.

    # Path legacy (default + fallback).
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
    # ── Rev. 109 Día 4 — Multimodal pipeline ──
    # Si el inbound es audio/imagen/video, descargamos el media de Meta y
    # pedimos a Gemini multimodal una interpretación textual. El resto del
    # flow agentic ve el content reemplazado (transparente).
    if content_type in {"audio", "image", "video"}:
        try:
            from agentic.multimodal import (
                process_inbound_media, format_for_agentic,
            )
            # Cargar media_id + media_mime desde messages.meta.
            _mrow = (
                supabase.table("messages")
                .select("meta")
                .eq("id", message_id)
                .single()
                .execute()
            )
            _meta = (_mrow.data or {}).get("meta") or {}
            _media_id = _meta.get("media_id")
            _media_mime = _meta.get("media_mime")
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
            else:
                logger.info(
                    "[MULTIMODAL_DISPATCH] conv=%s type=%s fallback al content "
                    "original (procesamiento no disponible)",
                    conversation_id[:8], content_type,
                )
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

    from agentic.agent import run_agentic_turn
    from agentic.system_prompt import build_system_prompt
    from agentic.invariants import (
        apply_invariants,
        CanonicalCategoriesInvariant,
        CartRenderCoherenceInvariant,
        ConsentRequiredInvariant,
        EmptyPromiseInvariant,
        NoDecorativeEmojiInvariant, PassiveClosingInvariant,
        PaymentCoherenceInvariant,
        PIICoherenceInvariant,
        PIISaveTruthfulnessInvariant,
        PostToolCoherenceInvariant, SummaryCoherenceInvariant,
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
    history = await _get_conversation_history(supabase, conversation_id)
    customer_phone = _get_conversation_customer_phone(supabase, conversation_id)
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
    tenant_name = "el negocio"
    tenant_pitch = None
    tenant_tone = None
    try:
        ten_row = (
            supabase.table("tenants")
            .select("name, business_pitch, tono_comunicacion")
            .eq("id", tenant_id).single().execute()
        )
        td = ten_row.data or {}
        tenant_name = td.get("name") or tenant_name
        tenant_pitch = td.get("business_pitch") or None
        tenant_tone = td.get("tono_comunicacion") or None
    except Exception:
        pass

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

    system_prompt = build_system_prompt(
        tenant_name=tenant_name,
        catalog=catalog,
        tenant_pitch=tenant_pitch,
        tenant_tone=tenant_tone,
        contact_record=contact or {},
        carriers=carriers_caps,
        payment_methods=payment_methods_cfg,
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
                        }).eq("id", cart_q.data[0]["id"]).execute()
                except Exception:
                    pass
    except Exception as exc:
        logger.warning(
            "[AGENTIC_PRE_LLM] payment_method_availability crashed: %s — skip",
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
                        }).eq("id", cid).execute()
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
                    }).eq("id", cid).execute()
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
                    supabase, message_id,
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
                supabase.table("contacts").update({
                    "consent_given": new_consent,
                }).eq("id", contact_id).eq("tenant_id", tenant_id).execute()
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
        if carrier_match:
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
    if intent_resolution and (intent_resolution.get("resolved") or intent_resolution.get("ambiguous")):
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
            outbound = compose_outbound_from_resolution(
                intent_resolution, customer_name=customer_name,
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
                supabase, message_id,
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
    if variant_match:
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
                supabase, message_id,
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
                .execute()
            )
            cart_has_items = bool(getattr(items_row, "count", 0) or 0)
    except Exception:
        cart_has_items = False

    shipping_match = try_resolve_shipping_intent(
        inbound_text=content,
        cart_has_items=cart_has_items,
    )
    if shipping_match:
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
                    supabase, message_id,
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
            system_prompt = build_prompt_for_state(
                state=_resolved_state,
                tenant_name=tenant_name,
                tenant_pitch=tenant_pitch,
                tenant_tone=tenant_tone,
                catalog=catalog,
                contact_record=contact or {},
                carriers=carriers_caps,
                payment_methods=payment_methods_cfg,
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
                        }).eq("id", _cart_post.data[0]["id"]).execute()
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
        invariant_set = [NoDecorativeEmojiInvariant()]
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
            SummaryCoherenceInvariant(),
            PIICoherenceInvariant(),
            # Rev. 109 UAT live BUG 19: bot afirma "guardé X" sin invocar tool.
            PIISaveTruthfulnessInvariant(),
            PostToolCoherenceInvariant(),
            EmptyPromiseInvariant(),
            PassiveClosingInvariant(),
            # Rev. 109 UAT live — normaliza variaciones del LLM al naming
            # canónico de categorías (Sérums Faciales → Sérums, Kits de
            # Cuidado → Kits). Aplica SOLO en outbounds que listen
            # categorías; no toca textos de cotización/pago/etc.
            CanonicalCategoriesInvariant(),
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

    # Enviar outbound al cliente.
    await _send_outbound_text(
        supabase=supabase,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        text=final_text,
    )
    _mark_message_processing(
        supabase, message_id,
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

    from agentic.agent import run_agentic_turn
    from agentic.system_prompt import build_system_prompt
    from orchestrator import (
        _get_conversation_history,
        _fetch_contact_for_phone,
        _get_conversation_customer_phone,
    )
    from tools.catalog_tool import get_tenant_catalog

    catalog = await get_tenant_catalog(supabase, tenant_id)
    history = await _get_conversation_history(supabase, conversation_id)
    customer_phone = _get_conversation_customer_phone(supabase, conversation_id)
    if customer_phone:
        contact_id, contact = _fetch_contact_for_phone(supabase, tenant_id, customer_phone)
    else:
        contact_id, contact = None, {}

    system_prompt = build_system_prompt(
        tenant_name=os.getenv("TENANT_DEFAULT_NAME", "el negocio"),
        catalog=catalog,
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
                .single()
                .execute()
            )
            _has_state_column = True
        except Exception:
            _conv_row = (
                supabase.table("conversations")
                .select("status")
                .eq("id", conversation_id)
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
                .execute()
            )
            _cart["items_count"] = int(
                getattr(_items_count_row, "count", 0) or 0
            )
            if _cart.get("status") == "checkout" and _cart.get("converted_order_id"):
                _cart["payment_link"] = "checkout"

        _ctx = build_context_from_records(
            conversation=_conv,
            cart=_cart,
            contact=contact or {},
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
        supabase.table("agentic_shadow_log").insert(row).execute()
    except Exception as exc:
        logger.warning(
            "[AGENTIC_AUDIT] persist falló mode=%s conv=%s: %s",
            mode, conversation_id[:8], exc,
        )


# ─── Gate de conversation status (Rev. 107) ────────────────────────────────


_SKIP_STATUSES = frozenset({"human_takeover", "closed"})


def _should_skip_for_conv_status(supabase: Any, conversation_id: str) -> bool:
    """True si la conv está en estado donde el bot NO debe responder.

    El operador tomó la conversación (human_takeover) o ya está cerrada.
    Best-effort lectura — si falla, NO skipea (default: dejar pasar para
    que el legacy aplique su propio gate como segunda defensa).
    """
    try:
        res = (
            supabase.table("conversations")
            .select("status")
            .eq("id", conversation_id)
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


def _mark_message_skipped(supabase: Any, message_id: str) -> None:
    """Marca el message como skipped por status conv. Mismo behavior que
    el path legacy (orchestrator.py SKIP_REASON_HUMAN_TAKEOVER)."""
    try:
        supabase.table("messages").update({
            "processing_status": "skipped",
            "skip_reason": "human_takeover_or_closed",
            "processed": True,
        }).eq("id", message_id).execute()
        logger.info(
            "[AGENTIC_DISPATCH] msg=%s skipped (conv status no-bot)",
            message_id[:8],
        )
    except Exception as exc:
        logger.warning(
            "[AGENTIC_DISPATCH] error marcando msg=%s skipped: %s",
            message_id[:8], exc,
        )

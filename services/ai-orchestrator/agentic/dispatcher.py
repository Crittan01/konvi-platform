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
  • Audit log completo en `agentic_shadow_log` (Fase B) o en
    `messages.metadata.agentic_audit` (Fase C).
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
      1. Si tenant.agentic_enabled=True → agentic FULL (envía outbound).
      2. Elif AGENTIC_SHADOW_ENABLED=True → legacy responde al cliente +
         agentic shadow corre en paralelo y loggea silenciosamente.
      3. Else → solo legacy.
    """
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
    # Import los tools para que se auto-registren.
    import agentic.tools.catalog  # noqa: F401
    import agentic.tools.cart  # noqa: F401
    import agentic.tools.contact  # noqa: F401
    import agentic.tools.shipping  # noqa: F401
    import agentic.tools.payment  # noqa: F401
    import agentic.tools.escalation  # noqa: F401

    from agentic.agent import run_agentic_turn
    from agentic.system_prompt import build_system_prompt
    from agentic.invariants import (
        apply_invariants, CartStateInvariant, ConsentRequiredInvariant,
        NoDecorativeEmojiInvariant, PassiveClosingInvariant, InvariantOutcome,
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
    # `_fetch_contact_for_phone` retorna tuple (contact_id, contact_record).
    if customer_phone:
        contact_id, contact = _fetch_contact_for_phone(supabase, tenant_id, customer_phone)
    else:
        contact_id, contact = None, {}

    # System prompt (con tenant config — Fase 0 usa default).
    system_prompt = build_system_prompt(
        tenant_name=os.getenv("TENANT_DEFAULT_NAME", "el negocio"),
        catalog=catalog,
    )

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
    )
    elapsed = time.monotonic() - started_at

    if result.error or not result.outbound_text:
        # Agentic falló — raise para que el dispatcher caiga a legacy.
        raise RuntimeError(f"agentic_failed: {result.error or 'empty_output'}")

    # Aplicar invariants Python (anti-hallu + style + flow guards).
    # Orden importa:
    #   1. cart_state + consent (semánticos: anti-hallu de cart/PII)
    #   2. passive_closing (semántico: rewrite cierre pasivo → CTA por estado)
    #   3. no_emoji (cosmético: strip sobre el texto final)
    invariant_result = await apply_invariants(
        [
            CartStateInvariant(),
            ConsentRequiredInvariant(),
            PassiveClosingInvariant(),
            NoDecorativeEmojiInvariant(),
        ],
        candidate_text=result.outbound_text,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        supabase=supabase,
        tool_call_log=result.tool_call_log,
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
        "[AGENTIC_FULL] conv=%s tools=%d elapsed=%.2fs invariant=%s",
        conversation_id[:8], result.tool_calls_executed, elapsed,
        invariant_result.invariant_name,
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

    # Persistir el log (best-effort, NO bloquea).
    try:
        supabase.table("agentic_shadow_log").insert({
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "inbound_text": content[:500],
            "agentic_outbound": (result.outbound_text or "")[:2000],
            "tool_calls_executed": result.tool_calls_executed,
            "tool_call_log": json.dumps(result.tool_call_log[:30]),
            "truncated": result.truncated,
            "truncated_reason": result.truncated_reason,
            "error": result.error,
            "elapsed_seconds": round(elapsed_s, 3),
        }).execute()
    except Exception as exc:
        logger.warning(
            "[AGENTIC_SHADOW] persist falló conv=%s: %s",
            conversation_id[:8], exc,
        )

    logger.info(
        "[AGENTIC_SHADOW] conv=%s tools=%d elapsed=%.2fs truncated=%s",
        conversation_id[:8], result.tool_calls_executed, elapsed_s,
        result.truncated,
    )

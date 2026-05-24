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
        apply_invariants, CartStateInvariant, ConsentRequiredInvariant,
        EmptyPromiseInvariant,
        NoDecorativeEmojiInvariant, PassiveClosingInvariant,
        PIICoherenceInvariant,
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

    system_prompt = build_system_prompt(
        tenant_name=tenant_name,
        catalog=catalog,
        tenant_pitch=tenant_pitch,
        tenant_tone=tenant_tone,
        contact_record=contact or {},
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
            CartStateInvariant(),
            ConsentRequiredInvariant(),
            SummaryCoherenceInvariant(),
            PIICoherenceInvariant(),
            PostToolCoherenceInvariant(),
            EmptyPromiseInvariant(),
            PassiveClosingInvariant(),
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

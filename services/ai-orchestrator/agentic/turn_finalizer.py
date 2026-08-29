"""TurnFinalizer — B-2 Fase 1 (2026-08-28, INV-B §4 ítem 9).

UNA etapa post-decisión para el path LLM del dispatcher — extraída VERBATIM de
`dispatcher._run_agentic_full` (strangler: comportamiento idéntico; el harness
B-3 certifica). Unifica lo que antes era la cola inline del turno:

  1. Trace estructurado (`AGENTIC_TRACE` — 1 línea greppable por turno).
  2. Race-gate operador↔bot (B-1 F7): si el operador habló mid-turn, el
     outbound se DESCARTA (la palabra la tiene el humano) → marca processed y
     TERMINA sin audit ni summary (exactamente como el código original).
  3. Envío por el embudo (`_send_outbound_text`) + mark processed.
  4. Escalación por BLOCK de invariant (B-0 F4) — si no es silent.
  5. Escalación silenciosa (rev. 107 — recoveries agotados).
  6. Audit logs por tool call + `AGENTIC_FULL`.
  7. Persistencia del audit del turno (`agentic_shadow_log`).
  8. Regen del resumen rodante (fire-and-forget).

Ciclo de imports: `dispatcher` importa este módulo a nivel top → los helpers
de `orchestrator` y el propio `dispatcher._persist_turn_audit` se importan
LAZY en call time (patrón estándar del repo — ver dispatcher/deterministic_gates).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class FinalizeTurnInput:
    """Todo lo que la etapa final necesita del turno (post-decisión)."""

    supabase: Any
    tenant_id: str
    conversation_id: str
    message_id: str
    inbound_text: str
    result: Any                       # AgenticTurnResult
    final_text: str
    invariant_result: Any
    is_silent_escalation: bool
    resolved_state: Optional[Any]
    system_prompt_chars: int
    history_turns: int
    elapsed: float
    started_iso: str


async def finalize_agentic_turn(inp: FinalizeTurnInput) -> None:
    """Ejecuta la etapa final del turno LLM (ver docstring del módulo)."""
    from orchestrator import (  # lazy: ciclo orchestrator↔dispatcher gestionado
        _send_outbound_text,
        _mark_message_processing,
        PROCESSING_STATUS_PROCESSED,
    )
    # Lazy en call time: dispatcher importa este módulo a nivel top.
    from agentic.dispatcher import _persist_turn_audit

    supabase = inp.supabase
    tenant_id = inp.tenant_id
    conversation_id = inp.conversation_id
    message_id = inp.message_id
    content = inp.inbound_text
    result = inp.result
    final_text = inp.final_text
    invariant_result = inp.invariant_result
    elapsed = inp.elapsed
    started_iso = inp.started_iso

    # A11 2026-06-26 — OBSERVABILIDAD: trace estructurado por turno (1 línea
    # greppable). Hace visible la decisión del bot — estado FSM resuelto, tools
    # invocados, invariant que intervino, si hubo rewrite — para diagnosticar
    # incoherencias al instante (antes había que leer código). Lo consume también
    # el harness adversarial (scripts/uat/coherence_scenarios.py).
    from agentic.invariants import InvariantOutcome  # local: enum del pipeline
    try:
        _trace_tools = [t.get("tool") for t in (result.tool_call_log or [])]
        _trace_inv = (
            f"{invariant_result.invariant_name}:{invariant_result.outcome.value}"
            if invariant_result.outcome != InvariantOutcome.OK else "ok"
        )
        logger.info(
            "[AGENTIC_TRACE] conv=%s state=%s tools=%s invariant=%s rewrote=%s model=%s",
            conversation_id[:8],
            getattr(inp.resolved_state, "value", None) or "fallback",
            _trace_tools,
            _trace_inv,
            invariant_result.outcome != InvariantOutcome.OK,
            getattr(result, "model_used", None) or "?",
        )
    except Exception:
        pass  # el trace NUNCA debe romper el turno

    # Enviar outbound al cliente.
    # B-1 (F7, auditoría bot 2026-08-21): race operador↔bot — si el operador
    # tomó la conversación Y ya habló mientras este turno se procesaba
    # (outbound sent_by='operator' posterior al inicio del turno LLM), el
    # outbound compuesto se descarta: la palabra la tiene el humano (antes el
    # bot vendía ENCIMA del operador — gate de status solo se chequeaba al
    # inicio del turno). Las escalaciones propias del turno (tool / FakeEsc /
    # silent) no escriben sent_by='operator' → su despedida sí sale.
    try:
        _op_msgs = (
            supabase.table("messages")
            .select("id", count="exact", head=True)
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .eq("direction", "outbound")
            .eq("payload->>sent_by", "operator")
            .gt("created_at", started_iso)
            .execute()
        )
        if getattr(_op_msgs, "count", 0) or 0:
            logger.warning(
                "[AGENTIC_DISPATCH] operador activo mid-turn conv=%s — "
                "outbound descartado (la palabra la tiene el humano)",
                conversation_id[:8],
            )
            _mark_message_processing(
                supabase, tenant_id, message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return
    except Exception as _race_exc:  # noqa: BLE001 — fail-open: no dropear por un check
        logger.info(
            "[AGENTIC_DISPATCH] race-check operador falló (fail-open): %s",
            _race_exc,
        )

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

    # B-0 F4 2026-08-21 — BLOCK de invariant (guard de dinero/verdad caído
    # — fail-closed A4 — o intervención de dinero): el cliente recibe
    # DEGRADED_GENERIC ("te respondo en un momento") pero antes NADIE era
    # notificado → seguimiento prometido que no existía. Escalación
    # silenciosa (human_takeover + audit + Telegram) con throttle de 10 min
    # por conversación. No aplica en el path `requires_silent_escalation`:
    # ese ya escala en el bloque de abajo (su invariant_set es solo
    # cosmético, pero por defensa evitamos doble escalación).
    if (
        invariant_result.outcome == InvariantOutcome.BLOCK
        and not inp.is_silent_escalation
    ):
        try:
            from agentic.invariant_escalation import escalate_invariant_block
            await escalate_invariant_block(
                supabase,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                invariant_name=invariant_result.invariant_name,
                reason=invariant_result.reason,
            )
        except Exception as _ib_exc:
            logger.warning(
                "[AGENTIC_DISPATCH] invariant_block escalation falló "
                "conv=%s: %s",
                conversation_id[:8], _ib_exc,
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
        system_prompt_chars=inp.system_prompt_chars,
        history_turns=inp.history_turns,
    )

    # B-1 (memoria): regenerar el resumen rodante si la conversación lo
    # amerita (>ventana + >=SUMMARY_REGEN_MIN_NEW mensajes nuevos). El
    # outbound recién enviado ya está persistido (queda dentro de la ventana;
    # se plegará en futuras regeneraciones). Fire-and-forget.
    try:
        from agentic.conversation_summary import maybe_update_conversation_summary
        from orchestrator import CONVERSATION_HISTORY_LIMIT as _HIST_LIMIT
        await maybe_update_conversation_summary(
            supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            history_limit=_HIST_LIMIT,
        )
    except Exception as _sum_exc:  # noqa: BLE001 — NUNCA rompe el turno
        logger.info(
            "[SUMMARY] update post-turn falló conv=%s: %s (best-effort)",
            conversation_id[:8], _sum_exc,
        )

"""Sub-handler de READY_FOR_SUMMARY — corrección de datos.

Sem 1 refactor (ADR-0017) — migración desde bypass del orchestrator
(legacy líneas 9227-9245 antes del refactor).

Comportamiento:
  Cliente en READY_FOR_SUMMARY dice "cambia el email" / "el nombre está
  mal" / similar → handler:
    1. Detecta el campo a corregir (`_detect_correction_intent`).
    2. Limpia ese campo en `contacts` (`_clear_contact_field`).
    3. Emite prompt determinístico pidiendo el nuevo valor.
    4. Marca el message processed y short-circuit.

Prioridad 50: corre ANTES del `ReadyForSummaryHandler` (priority 100)
porque la corrección DESCARTA el resumen actual. Si el usuario pide
corrección, NO queremos emitir resumen primero.

Patrón priority-based de strangler-fig: sub-handlers especializados
delante del handler default del estado.
"""
from __future__ import annotations

from typing import Optional

from fsm.handlers.base import HandlerResult, StateHandler, TurnInput
from fsm.handlers.dispatcher import register


class ReadyForSummaryCorrectionHandler:
    """Detecta intent de corrección de dato dentro de READY_FOR_SUMMARY
    y pide el nuevo valor. Corre antes que el resumen default."""

    applies_to_states = frozenset({"READY_FOR_SUMMARY"})
    priority = 50  # antes que ready_for_summary.deterministic_summary (100)
    name = "ready_for_summary.correction"

    async def handle(self, turn: TurnInput) -> Optional[HandlerResult]:
        # Late imports — orchestrator sigue siendo source-of-truth de
        # estos detectores (extracción a intent/ programada en Sem 2).
        from orchestrator import (
            _detect_correction_intent,
            _clear_contact_field,
            _pick_variant,
            _today_seed,
            _CORRECTION_PROMPT_VARIANTS,
        )

        if not turn.contact_id:
            return None

        correction_field = _detect_correction_intent(turn.inbound_text or "")
        if not correction_field:
            return None

        # Side-effect: limpiar el campo en DB.
        # (Side-effects en handlers son OK en Sem 1; Sem 3 los moveremos
        # a `emit_events` declarativos.)
        if turn.supabase is not None:
            try:
                _clear_contact_field(
                    turn.supabase, turn.contact_id, turn.tenant_id, correction_field,
                )
            except Exception:
                # Si el clear falla, igual emitimos prompt — el cliente
                # puede dar el nuevo valor y la persistencia ocurrirá
                # en el siguiente turn vía CONTACT USYNC.
                pass

        variants = _CORRECTION_PROMPT_VARIANTS.get(correction_field) or [
            "Sin problema. ¿Qué dato quieres corregir?",
            "Listo, ¿qué dato actualizo?",
        ]
        reply = _pick_variant(variants, seed=_today_seed(turn.conversation_id))

        return HandlerResult(
            outbound_text=reply,
            handler_name=self.name,
            log_extras={"correction_field": correction_field},
        )


register(ReadyForSummaryCorrectionHandler())

"""Dispatcher de state handlers — punto único de invocación.

Sem 1 refactor (ADR-0017). Reemplaza los 13 bypasses dispersos del
orchestrator con una dispatch table priority-ordered per-state.

Diseño:
  • Registry global: `_REGISTRY: dict[state, list[StateHandler]]`.
  • Cada handler se registra vía `register(handler)` al importar su
    módulo. Orden de registro NO importa — la prioridad lo gobierna.
  • `dispatch(turn)`: itera handlers aplicables al state actual en
    orden de prioridad ascendente; retorna el primer HandlerResult.
  • Si NINGÚN handler aplica → retorna None → caller (orchestrator)
    continúa al LLM.

Observabilidad:
  • Logging estructurado per dispatch: estado, # handlers evaluados,
    cuál disparó (o "no_match").
  • Audit log opcional para forensics.
"""
from __future__ import annotations

import logging
from typing import Optional

from fsm.handlers.base import HandlerResult, StateHandler, TurnInput

logger = logging.getLogger(__name__)

# Registry global keyed por state. Cada lista se mantiene ordenada
# por priority ascendente al registrar.
_REGISTRY: dict[str, list[StateHandler]] = {}


def register(handler: StateHandler) -> None:
    """Registra un handler en el dispatcher.

    Idempotente por nombre: registrar el mismo handler dos veces
    reemplaza el anterior (útil para hot-reload en tests).
    """
    for state in handler.applies_to_states:
        bucket = _REGISTRY.setdefault(state, [])
        # Reemplazar si ya existe handler con mismo nombre.
        bucket[:] = [h for h in bucket if h.name != handler.name]
        bucket.append(handler)
        bucket.sort(key=lambda h: h.priority)
    logger.debug(
        "[HANDLER_DISPATCH] register name=%s priority=%s states=%s",
        handler.name, handler.priority, sorted(handler.applies_to_states),
    )


def unregister(handler_name: str) -> None:
    """Remueve un handler por nombre (útil para tests)."""
    for bucket in _REGISTRY.values():
        bucket[:] = [h for h in bucket if h.name != handler_name]


def clear_registry() -> None:
    """Vacía el registry (solo tests)."""
    _REGISTRY.clear()


def get_handlers_for_state(state: str) -> list[StateHandler]:
    """Inspección: lista de handlers registrados para un state.

    Útil para tests + debugging. Orden = priority ascendente.
    """
    return list(_REGISTRY.get(state, []))


async def dispatch(turn: TurnInput) -> Optional[HandlerResult]:
    """Invoca handlers aplicables al `turn.display_state` en orden de
    prioridad. Retorna el primer HandlerResult no-None, o None si
    ningún handler aplicó.

    Contrato:
      • Handler que retorna HandlerResult → corto-circuita el dispatch
        (a menos que HandlerResult.short_circuit=False, reservado para
        casos futuros tipo "enriquecimiento + continúa").
      • Excepción en handler → loggea WARNING, continúa al siguiente
        (degradación graceful — un handler roto no debe colapsar el
        turn).
    """
    state = turn.display_state
    candidates = _REGISTRY.get(state, [])
    if not candidates:
        logger.debug(
            "[HANDLER_DISPATCH] no handlers state=%s conv=%s",
            state, turn.conversation_id[:8] if turn.conversation_id else "?",
        )
        return None

    evaluated = 0
    for handler in candidates:
        evaluated += 1
        try:
            result = await handler.handle(turn)
        except Exception as exc:
            logger.warning(
                "[HANDLER_DISPATCH] handler=%s raised %s — skipping",
                handler.name, exc, exc_info=True,
            )
            continue
        if result is None:
            continue
        logger.info(
            "[HANDLER_DISPATCH] resolved state=%s handler=%s "
            "(evaluated=%d/%d) conv=%s",
            state, handler.name, evaluated, len(candidates),
            turn.conversation_id[:8] if turn.conversation_id else "?",
        )
        if not result.short_circuit:
            # Reservado para futuro: handlers no terminales que enriquecen
            # turn state sin emitir outbound. Por ahora no se usa.
            continue
        return result

    logger.debug(
        "[HANDLER_DISPATCH] no_match state=%s evaluated=%d conv=%s",
        state, evaluated,
        turn.conversation_id[:8] if turn.conversation_id else "?",
    )
    return None

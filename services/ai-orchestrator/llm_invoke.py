"""
LLM cascade wrapper — Rev. 80.

Robustece la invocación de Gemini ante 503/UNAVAILABLE/429/RESOURCE_EXHAUSTED:

  Intentos 1-N1: modelo primario (gemini-3.1-flash-lite) con backoff exponencial.
  Intentos N1-N2: modelo fallback (gemini-3.5-flash) con backoff.
  Si TODO falla: retorna respuesta degradada con requires_human=True para
  que el bot escale a un asesor en vez de quedarse mudo.

Configurable vía .env:
  GEMINI_MODEL              — modelo primario (default: gemini-3.1-flash-lite)
  GEMINI_FALLBACK_MODEL     — modelo de respaldo (default: gemini-3.5-flash)
  GEMINI_MAX_RETRIES        — total de intentos (default: 8)
  GEMINI_FALLBACK_AFTER     — switch a fallback tras N intentos (default: 2)
  LLM_CASCADE_DEADLINE_SECONDS — presupuesto total por turno (default: 100;
    0 = sin deadline). A5 2026-08-02: sin deadline, 8 intentos × timeout 30s
    + backoff ≈ 5 min peor caso > heartbeat Render 120s (worker.py: restart
    a mitad de turno → posible outbound duplicado). Agotado el budget, la
    cascada corta intentos nuevos y cae al path degraded existente.

NO maneja errores no-transitorios (4xx no-429): los re-lanza para que el
caller decida (típicamente bug de prompt/schema → no reintentar).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger("orchestrator.llm")


# ─── Configuración ───────────────────────────────────────────────────────────

# Primario/fallback invertidos (2026-07-07): antes primary=3.5-flash (frontier, caro
# y hoy saturado 503) / fallback=lite. Ahora primary=3.1-flash-lite (GA, ~3s, "frontier
# a fracción del costo") para latencia/costo del bot en alto volumen; 3.5-flash queda de
# fallback de escalación. (Track 6, deprecations oficiales 2026-08-22: 3.1-flash-lite
# tiene shutdown 2027-05-07 → reemplazo 3.5-flash-lite; 2.5-flash NO tiene fecha de
# retiro anunciada — corregido el comentario previo que afirmaba 2026-10-16.)
DEFAULT_PRIMARY_MODEL = "gemini-3.1-flash-lite"
DEFAULT_FALLBACK_MODEL = "gemini-3.5-flash"
DEFAULT_MAX_RETRIES = 8
# Fix latencia (2026-07-07): bajado de 4→2. Con timeout por llamada (~30s), probar
# el primario 4 veces antes de fallar-over daba ~120s cuando el primario se satura
# (503 "high demand"). Con 2, el bot promueve al fallback (gemini-3.1-flash-lite,
# ~4s, disponible) mucho antes. Override por env GEMINI_FALLBACK_AFTER (1 = aún más
# agresivo). El primario sano responde en el 1er intento → sin failover.
DEFAULT_FALLBACK_AFTER = 2
# A5 (2026-08-02) — presupuesto total de tiempo por turno. Sin deadline, el
# peor caso (8 intentos × timeout ~30s + backoff hasta 63s) ≈ 5 min, muy por
# encima del heartbeat Render de 120s (worker.py F45) → restart a mitad de
# turno y posible outbound duplicado. 100s deja margen bajo los 120s. La
# cascada NO interrumpe una llamada en vuelo (el timeout por llamada lo hace);
# corta intentos NUEVOS y cae al path degraded existente.
DEFAULT_CASCADE_DEADLINE_SECONDS = 100


def _cfg_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _cfg_str(key: str, default: str) -> str:
    return os.getenv(key, default) or default


# ─── Tipos de respuesta ──────────────────────────────────────────────────────

@dataclass
class CascadeResult:
    """Resultado del invoke. `response` es el objeto del SDK Gemini cuando
    todo OK; `degraded=True` cuando todos los intentos fallaron."""
    response: Optional[Any]
    model_used: Optional[str]
    attempts: int
    degraded: bool
    last_error: Optional[str] = None


DEGRADED_RESPONSE_JSON = (
    '{"should_respond": true, '
    '"response_text": "Disculpa, estoy teniendo dificultades técnicas para responderte ahora mismo. '
    'En un momento un asesor humano se pondrá en contacto contigo para ayudarte. '
    'Gracias por tu paciencia. \U0001F64F", '
    '"confidence": 0.0, '
    '"requires_human": true, '
    '"intent_detected": "system_degraded"}'
)


# ─── Detección de errores transitorios ───────────────────────────────────────

_TRANSIENT_TOKENS = (
    "503", "504", "429",
    "unavailable", "service unavailable", "deadline exceeded",
    "resource_exhausted", "resource exhausted",
    "rate limit", "too many requests",
    "timeout", "timed out",
    "internal", "internal_error",
    "connection", "reset by peer",
    "high demand",
)


def _is_transient(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(tok in text for tok in _TRANSIENT_TOKENS)


def _backoff_seconds(attempt: int) -> float:
    """Backoff exponencial truncado: 1s, 2s, 4s, 8s, 16s, 16s, 16s, 16s..."""
    return float(min(16, 2 ** max(0, attempt - 1)))


# ─── Wrapper principal ───────────────────────────────────────────────────────

def generate_with_cascade(
    invoke_fn: Callable[[str], Any],
    *,
    primary_model: Optional[str] = None,
    fallback_model: Optional[str] = None,
    max_retries: Optional[int] = None,
    fallback_after: Optional[int] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    deadline_seconds: Optional[float] = None,
    clock: Optional[Callable[[], float]] = None,
) -> CascadeResult:
    """Invoca `invoke_fn(model_name)` con cascada y backoff.

    Args:
        invoke_fn: closure que recibe el nombre del modelo y devuelve la
            respuesta del SDK Gemini. El caller arma el prompt + config.
        primary_model: modelo principal (default GEMINI_MODEL del env).
        fallback_model: modelo de respaldo cuando primary se satura.
        max_retries: total de intentos (default 8).
        fallback_after: tras N intentos del primario, switch al fallback.
        sleep_fn: inyectable para tests.
        deadline_seconds: presupuesto total del turno (default
            LLM_CASCADE_DEADLINE_SECONDS del env, 100s; 0 = sin deadline).
            Agotado, no se lanzan intentos nuevos → path degraded existente.
        clock: inyectable para tests (default time.monotonic).

    Returns:
        CascadeResult con .response (SDK obj) o .degraded=True.

    Errores no-transitorios se re-lanzan inmediatamente.
    """
    primary = primary_model or _cfg_str("GEMINI_MODEL", DEFAULT_PRIMARY_MODEL)
    fallback = fallback_model or _cfg_str("GEMINI_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)
    total = max_retries if max_retries is not None else _cfg_int(
        "GEMINI_MAX_RETRIES", DEFAULT_MAX_RETRIES,
    )
    switch_at = fallback_after if fallback_after is not None else _cfg_int(
        "GEMINI_FALLBACK_AFTER", DEFAULT_FALLBACK_AFTER,
    )
    deadline = deadline_seconds if deadline_seconds is not None else _cfg_int(
        "LLM_CASCADE_DEADLINE_SECONDS", DEFAULT_CASCADE_DEADLINE_SECONDS,
    )
    # Resolver sleep_fn en runtime (no en def-time) para que `patch(
    # 'llm_invoke.time.sleep')` funcione en tests sin tener que pasar
    # sleep_fn explícito por cada caller.
    actual_sleep = sleep_fn if sleep_fn is not None else time.sleep
    monotonic = clock if clock is not None else time.monotonic
    started = monotonic()

    def _budget_exhausted() -> bool:
        return deadline > 0 and (monotonic() - started) >= deadline

    last_exc: Optional[BaseException] = None
    attempts_done = 0
    for attempt in range(1, total + 1):
        if _budget_exhausted():
            # A5 — deadline agotado: NO lanzar otro intento (cada uno puede
            # costar hasta el timeout de 30s). Cae al degraded de abajo.
            logger.error(
                "[LLM_CASCADE] deadline agotado (%.1fs >= %ss) tras %d "
                "intentos — degraded sin más retries",
                monotonic() - started, deadline, attempts_done,
            )
            break
        attempts_done = attempt
        model_name = primary if attempt <= switch_at else fallback
        try:
            resp = invoke_fn(model_name)
            logger.info(
                "[LLM_CASCADE] attempt=%d model=%s status=ok", attempt, model_name,
            )
            return CascadeResult(
                response=resp, model_used=model_name,
                attempts=attempt, degraded=False,
            )
        except BaseException as exc:  # noqa: BLE001 — capturamos amplio para logging
            last_exc = exc
            transient = _is_transient(exc)
            logger.warning(
                "[LLM_CASCADE] attempt=%d model=%s status=fail transient=%s err=%s",
                attempt, model_name, transient, str(exc)[:240],
            )
            if not transient:
                # Bug de schema / prompt → re-lanzamos al caller.
                raise
            if attempt < total:
                sleep_for = _backoff_seconds(attempt)
                if deadline > 0:
                    # No dormir más allá del budget: el próximo chequeo de
                    # deadline decidirá si aún hay tiempo para otro intento.
                    remaining = deadline - (monotonic() - started)
                    if remaining <= 0:
                        continue  # el chequeo al inicio del loop corta
                    sleep_for = min(sleep_for, remaining)
                actual_sleep(sleep_for)

    # Todos los intentos fallaron con errores transitorios (o deadline
    # agotado) → degradar.
    err_str = str(last_exc) if last_exc else "unknown"
    logger.error(
        "[LLM_CASCADE] degradado tras %d intentos (last_err=%s)",
        attempts_done, err_str[:240],
    )
    return CascadeResult(
        response=None, model_used=None, attempts=attempts_done, degraded=True,
        last_error=err_str,
    )


def degraded_response_text() -> str:
    """JSON serializado de respuesta degradada para entregar al cliente.

    Compatible con `OrchestratorOutput` del orchestrator: should_respond=True,
    requires_human=True para escalar inmediatamente.
    """
    return DEGRADED_RESPONSE_JSON

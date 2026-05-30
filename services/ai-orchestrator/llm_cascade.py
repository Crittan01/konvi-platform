"""LLM Cascade multi-vendor — rev. 109 Día 3.

Extiende llm_invoke.py (2-tier Gemini) a cascade 4-tier:
  Tier 1: gemini-2.5-flash-lite       (default — barato, rápido)
  Tier 2: gemini-2.5-flash             (escalado — tool calling complejo)
  Tier 3: gemini-2.5-pro               (rescue tier 1 — razonamiento)
  Tier 4: claude-sonnet-4-5            (rescue tier 2 — vendor distinto)

Tier 4 (Claude) es text-only "ultimo recurso": cuando los 3 tiers Gemini
fallan, generamos un texto de respuesta natural sin tool calling para
NO dejar al cliente con mensaje degraded. Es resilience cross-vendor.

ENV configurables:
  LLM_CASCADE_TIERS  — lista separada por coma: "gemini-2.5-flash-lite,
                       gemini-2.5-flash,gemini-2.5-pro,claude-sonnet-4-5"
  LLM_TIER_PROMOTE_AFTER  — promueve al siguiente tier tras N fails (default: 2)
  ANTHROPIC_API_KEY        — opcional; sin esta key, Claude tier se omite.

API:
    result = cascade_invoke(
        gemini_invoker=lambda model: client.models.generate_content(...),
        claude_invoker=lambda: claude_rescue(system_prompt, user_msg),
        tiers=["gemini-2.5-flash-lite", "gemini-2.5-flash",
               "gemini-2.5-pro", "claude-sonnet-4-5"],
    )

Compatible con llm_invoke.generate_with_cascade existente (2-tier
Gemini-only) — quien quiera 4-tier multi-vendor migra a este módulo.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("orchestrator.llm.cascade")


_DEFAULT_TIERS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "claude-sonnet-4-5",
]


def _env_tiers() -> list[str]:
    raw = os.getenv("LLM_CASCADE_TIERS", "").strip()
    if not raw:
        return list(_DEFAULT_TIERS)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or list(_DEFAULT_TIERS)


def _vendor_of(model: str) -> str:
    """Inferir vendor desde el nombre del modelo."""
    name = model.lower()
    if name.startswith("gemini") or name.startswith("google/"):
        return "gemini"
    if name.startswith("claude") or name.startswith("anthropic/"):
        return "anthropic"
    raise ValueError(f"unknown LLM vendor for model: {model}")


_TRANSIENT_TOKENS = (
    "503", "504", "429",
    "unavailable", "service unavailable", "deadline exceeded",
    "resource_exhausted", "resource exhausted",
    "rate limit", "too many requests",
    "timeout", "timed out",
    "internal", "internal_error",
    "connection", "reset by peer",
    "high demand",
    # Síntomas Gemini saturado conocidos.
    "empty_output", "finish=stop_no_text",
)


def _is_transient(exc_or_text: Any) -> bool:
    text = str(exc_or_text).lower()
    return any(tok in text for tok in _TRANSIENT_TOKENS)


def _backoff_seconds(attempt_in_tier: int) -> float:
    """Backoff 1, 3, 7, 15, 31, ... (truncado a 31s).

    Pattern `2^n - 1` da más espacio entre reintentos que el clásico
    `2^(n-1)` (1, 2, 4, 8). Mejor para saturaciones reales del proveedor
    (Gemini 503) — da tiempo a que la cola del backend se libere.
    """
    return float(min(31, (2 ** max(1, attempt_in_tier)) - 1))


@dataclass
class CascadeOutcome:
    """Resultado normalizado de la cascade."""
    response: Optional[Any] = None
    model_used: Optional[str] = None
    vendor_used: Optional[str] = None
    tier_index: int = -1
    total_attempts: int = 0
    degraded: bool = False
    last_error: Optional[str] = None
    tiers_tried: list[str] = field(default_factory=list)


def cascade_invoke(
    *,
    gemini_invoker: Callable[[str], Any],
    claude_invoker: Optional[Callable[[], Any]] = None,
    tiers: Optional[list[str]] = None,
    attempts_per_tier: int = 2,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> CascadeOutcome:
    """Invoca la cascade multi-vendor.

    Args:
      gemini_invoker(model) — closure que invoca Gemini SDK con el model
        dado. Re-lanza excepciones (cascade decide retry/promote).
      claude_invoker() — closure SIN args que invoca Claude (rescue text-
        only). Opcional; si ANTHROPIC_API_KEY no existe, la cascade omite
        el tier Claude automáticamente.
      tiers — orden de modelos. Default ENV o `_DEFAULT_TIERS`.
      attempts_per_tier — reintentos por tier antes de promoter (default 2).

    Returns:
      CascadeOutcome con .response (objeto SDK) o .degraded=True si todos
      los tiers cayeron.
    """
    actual_sleep = sleep_fn if sleep_fn is not None else time.sleep
    tier_list = tiers if tiers is not None else _env_tiers()
    has_claude_key = bool(os.getenv("ANTHROPIC_API_KEY"))

    outcome = CascadeOutcome()
    last_exc: Optional[BaseException] = None

    for tier_idx, model in enumerate(tier_list):
        vendor = _vendor_of(model)
        outcome.tiers_tried.append(model)

        # Skip Claude tier si no hay API key.
        if vendor == "anthropic" and (
            not has_claude_key or claude_invoker is None
        ):
            logger.info(
                "[CASCADE] skip tier=%d model=%s — sin ANTHROPIC_API_KEY "
                "o claude_invoker",
                tier_idx, model,
            )
            continue

        for attempt in range(1, attempts_per_tier + 1):
            outcome.total_attempts += 1
            try:
                if vendor == "gemini":
                    resp = gemini_invoker(model)
                else:
                    resp = claude_invoker()  # type: ignore[misc]
                logger.info(
                    "[CASCADE] tier=%d model=%s vendor=%s attempt=%d status=ok",
                    tier_idx, model, vendor, attempt,
                )
                outcome.response = resp
                outcome.model_used = model
                outcome.vendor_used = vendor
                outcome.tier_index = tier_idx
                return outcome
            except BaseException as exc:  # noqa: BLE001
                last_exc = exc
                transient = _is_transient(exc)
                logger.warning(
                    "[CASCADE] tier=%d model=%s vendor=%s attempt=%d "
                    "status=fail transient=%s err=%s",
                    tier_idx, model, vendor, attempt, transient,
                    str(exc)[:240],
                )
                if not transient:
                    # Bug de schema/prompt — re-lanzar (no cascade).
                    raise
                if attempt < attempts_per_tier:
                    actual_sleep(_backoff_seconds(attempt))
        # Tier agotó intentos — promover al siguiente.
        logger.info(
            "[CASCADE] tier=%d model=%s exhausted → promote",
            tier_idx, model,
        )

    # Todos los tiers cayeron.
    outcome.degraded = True
    outcome.last_error = str(last_exc) if last_exc else "all_tiers_failed"
    logger.error(
        "[CASCADE] DEGRADED — todos los tiers cayeron (%d intentos totales)",
        outcome.total_attempts,
    )
    return outcome

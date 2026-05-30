"""Webhook rate limiting (rev. 105 Sem 2 F.1).

TokenBucket algorithm in-memory thread-safe. Apropiado para single-process
FastAPI; en multi-worker escenarios futuros (Render Pro autoscaling) se
puede swap a Redis-backed bucket.

Configuración típica per integration (basado en SLAs documentados de cada
provider):
  - Wompi:    capacity=120, refill_per_sec=2     (200 webhooks/min sostenido)
  - MeLi:     capacity=300, refill_per_sec=5     (300 webhooks/min)
  - Meta:     capacity=600, refill_per_sec=10    (alto volumen HSM en marketing)
  - Envia:    capacity=60, refill_per_sec=1      (modesto, shipments)
  - Telegram: capacity=120, refill_per_sec=2     (operadores comandos)

Granularidad: por (tenant_id, integration). Tenant A no afecta tenant B.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .errors import RateLimitExceededError


@dataclass
class TokenBucketRule:
    """Configuración de bucket. Inmutable post-creación."""
    capacity: int           # tokens máximos al estar full
    refill_per_sec: float   # tokens por segundo refill
    cost_per_request: int = 1  # tokens consumidos por cada webhook (default 1)

    def __post_init__(self):
        if self.capacity <= 0:
            raise ValueError("capacity debe ser > 0")
        if self.refill_per_sec <= 0:
            raise ValueError("refill_per_sec debe ser > 0")
        if self.cost_per_request <= 0:
            raise ValueError("cost_per_request debe ser > 0")


@dataclass
class _BucketState:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    """In-memory bucket store keyed por (tenant_id, integration).

    Thread-safe via RLock (FastAPI puede correr múltiples requests concurrentes
    en un mismo proceso uvicorn worker). NO compartido entre procesos —
    para autoscaling Render multi-worker, swap a Redis backend en sesión
    dedicada (Sem 11 F.6 observability).
    """

    def __init__(self):
        self._buckets: dict[tuple[str, str], _BucketState] = {}
        self._lock = threading.RLock()

    def _refill(self, state: _BucketState, rule: TokenBucketRule, now: float) -> None:
        """In-place refill basado en tiempo transcurrido."""
        elapsed = now - state.last_refill
        if elapsed > 0:
            state.tokens = min(
                rule.capacity,
                state.tokens + elapsed * rule.refill_per_sec,
            )
            state.last_refill = now

    def consume(
        self,
        *,
        tenant_id: str,
        integration: str,
        rule: TokenBucketRule,
    ) -> None:
        """Intenta consumir cost_per_request tokens. Levanta
        RateLimitExceededError con retry_after si bucket vacío."""
        key = (tenant_id, integration)
        now = time.time()
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                # Bucket nuevo: arranca lleno.
                state = _BucketState(
                    tokens=float(rule.capacity),
                    last_refill=now,
                )
                self._buckets[key] = state
            self._refill(state, rule, now)

            if state.tokens >= rule.cost_per_request:
                state.tokens -= rule.cost_per_request
                return

            # Calcular retry_after: tiempo necesario para refill suficientes tokens.
            tokens_needed = rule.cost_per_request - state.tokens
            seconds_needed = tokens_needed / rule.refill_per_sec
            retry_after = max(1, math.ceil(seconds_needed))
            raise RateLimitExceededError(retry_after_seconds=retry_after)

    def reset(self, tenant_id: Optional[str] = None) -> None:
        """Borra buckets (todos o de un tenant). Para tests / admin."""
        with self._lock:
            if tenant_id is None:
                self._buckets.clear()
            else:
                keys_to_del = [k for k in self._buckets if k[0] == tenant_id]
                for k in keys_to_del:
                    del self._buckets[k]

    def get_remaining(
        self,
        *,
        tenant_id: str,
        integration: str,
        rule: TokenBucketRule,
    ) -> float:
        """Helper read-only — retorna tokens disponibles sin consumir.
        Útil para metrics / debug."""
        key = (tenant_id, integration)
        now = time.time()
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                return float(rule.capacity)
            self._refill(state, rule, now)
            return state.tokens


# Singleton por proceso. NO compartido entre uvicorn workers — limitación
# documentada arriba.
_GLOBAL_LIMITER = TokenBucketLimiter()


def get_global_limiter() -> TokenBucketLimiter:
    """Acceso al limiter global del proceso. Inyectable en tests
    construyendo TokenBucketLimiter() local."""
    return _GLOBAL_LIMITER


def _reset_global_limiter() -> None:
    """Helper para tests."""
    _GLOBAL_LIMITER.reset()

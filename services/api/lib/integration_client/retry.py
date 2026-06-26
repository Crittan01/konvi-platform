"""Retry policy con exponential backoff + jitter (rev. 105 Sem 2 F.2).

Patrón AWS / Google / FAANG: backoff exponencial con jitter para evitar
thundering herd cuando muchos clientes reintentan al mismo tiempo.

Configuración típica per provider:
  - Wompi:    max_attempts=3, base_delay=1s, max_delay=30s
  - Envia:    max_attempts=4, base_delay=2s, max_delay=60s (más permisivo)
  - Meta:     max_attempts=3, base_delay=1s, max_delay=15s
  - MeLi:     max_attempts=3, base_delay=1s, max_delay=20s
  - Resend:   max_attempts=3, base_delay=1s, max_delay=15s

NO se intenta retry de errores 4xx (ProviderRejectedError) — esos son
deterministicamente NO retriable. Solo 5xx + timeout + network → retry.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from .errors import IntegrationClientError, RetryBudgetExceededError

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """Configuración inmutable de retry. Cada cliente puede tener su propia."""
    max_attempts: int = 3
        # Total intentos incluyendo el primero. max=3 = primer intento + 2 retries.
    base_delay_seconds: float = 1.0
        # Delay base. Real delay = base * (2^attempt) + random jitter.
    max_delay_seconds: float = 30.0
        # Cap superior para evitar delays excesivos.
    jitter_seconds: float = 0.5
        # Random jitter [0, jitter_seconds] sumado a cada delay.

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("max_attempts debe ser ≥ 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds debe ser ≥ 0")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError(
                "max_delay_seconds debe ser ≥ base_delay_seconds"
            )

    def compute_delay(self, attempt: int) -> float:
        """Calcula delay para attempt N (0-indexed). Exponential + jitter."""
        if attempt < 0:
            raise ValueError("attempt debe ser ≥ 0")
        backoff = self.base_delay_seconds * (2 ** attempt)
        jitter = random.uniform(0.0, self.jitter_seconds)
        return min(backoff + jitter, self.max_delay_seconds)


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    is_retriable: Callable[[Exception], bool] = lambda e: True,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Ejecuta fn() con retry async. is_retriable decide si una excepción
    justifica retry (default: todas). sleep es inyectable para tests."""
    last_error: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return await fn()
        except Exception as e:
            last_error = e
            if not is_retriable(e):
                # No retriable: levantar inmediatamente sin gastar más intentos.
                raise
            if attempt + 1 >= policy.max_attempts:
                break
            delay = policy.compute_delay(attempt)
            await sleep(delay)
    raise RetryBudgetExceededError(
        attempts=policy.max_attempts,
        last_error=last_error,
    )


def retry_sync(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    is_retriable: Callable[[Exception], bool] = lambda e: True,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Versión sync de retry_async. Útil para clientes HTTP sync."""
    last_error: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if not is_retriable(e):
                raise
            if attempt + 1 >= policy.max_attempts:
                break
            delay = policy.compute_delay(attempt)
            sleep(delay)
    raise RetryBudgetExceededError(
        attempts=policy.max_attempts,
        last_error=last_error,
    )


def default_is_retriable(error: Exception) -> bool:
    """Default heurística — retry solo errores marcados retriable=True."""
    if isinstance(error, IntegrationClientError):
        return error.retriable
    # Excepciones genéricas (httpx.TimeoutException, ConnectionError) → retry.
    return True

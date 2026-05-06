"""Circuit breaker (rev. 105 Sem 2 F.2).

Patrón Hystrix simplificado. State machine:

  CLOSED ─(fail_count >= threshold)→ OPEN
    ↑                                  │
    │                          (timeout passed)
    │                                  ↓
    └──(success)─── HALF_OPEN ←────────┘
                        │
                        └─(fail)→ OPEN

Cuando OPEN: requests fallan rápido con CircuitOpenError sin gastar tiempo
en provider caído. Tras `open_duration_seconds`, transición a HALF_OPEN
permite UN request de prueba. Si pasa → CLOSED. Si falla → OPEN nuevamente.

Configuración típica:
  - failure_threshold=5: 5 fallos consecutivos abren el circuit
  - open_duration_seconds=30: pausa 30s antes de probar
  - half_open_max_requests=1: solo 1 request en half-open (no thundering herd)

State per provider (key="envia", "wompi", etc.). Single-process in-memory;
multi-worker requiere Redis sync (sesión Sem 11 observability).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum

from .errors import CircuitOpenError


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    open_duration_seconds: float = 30.0
    half_open_max_requests: int = 1

    def __post_init__(self):
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold debe ser ≥ 1")
        if self.open_duration_seconds <= 0:
            raise ValueError("open_duration_seconds debe ser > 0")
        if self.half_open_max_requests < 1:
            raise ValueError("half_open_max_requests debe ser ≥ 1")


@dataclass
class _CircuitState:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0
    half_open_in_flight: int = 0


class CircuitBreaker:
    """Per-key state machine. key suele ser provider name ('envia', 'wompi')
    o (provider, tenant_id) para granularidad mayor.

    Thread-safe via RLock (FastAPI request handlers concurrentes en mismo
    proceso uvicorn). NO compartido entre procesos."""

    def __init__(self, config: CircuitBreakerConfig | None = None):
        self._config = config or CircuitBreakerConfig()
        self._states: dict[str, _CircuitState] = {}
        self._lock = threading.RLock()

    def _get_state(self, key: str) -> _CircuitState:
        if key not in self._states:
            self._states[key] = _CircuitState()
        return self._states[key]

    def _transition_to_half_open_if_due(
        self, state: _CircuitState, now: float
    ) -> None:
        """Si OPEN y pasó open_duration_seconds, transición a HALF_OPEN."""
        if state.state == CircuitState.OPEN:
            if now - state.opened_at >= self._config.open_duration_seconds:
                state.state = CircuitState.HALF_OPEN
                state.half_open_in_flight = 0

    def before_request(self, key: str) -> None:
        """Llamar antes de hacer el request. Levanta CircuitOpenError si
        circuit está OPEN o HALF_OPEN saturado."""
        now = time.time()
        with self._lock:
            state = self._get_state(key)
            self._transition_to_half_open_if_due(state, now)

            if state.state == CircuitState.OPEN:
                opens_until = (
                    state.opened_at + self._config.open_duration_seconds - now
                )
                raise CircuitOpenError(key, max(0.0, opens_until))

            if state.state == CircuitState.HALF_OPEN:
                if state.half_open_in_flight >= self._config.half_open_max_requests:
                    # No permitimos más requests de prueba simultáneos.
                    raise CircuitOpenError(key, 0.5)  # mini delay
                state.half_open_in_flight += 1

    def record_success(self, key: str) -> None:
        """Llamar tras request exitoso. Resetea counters y cierra circuit."""
        with self._lock:
            state = self._get_state(key)
            if state.state == CircuitState.HALF_OPEN:
                state.half_open_in_flight = max(0, state.half_open_in_flight - 1)
            state.consecutive_failures = 0
            state.state = CircuitState.CLOSED
            state.opened_at = 0.0

    def record_failure(self, key: str) -> None:
        """Llamar tras request fallido. Incrementa counter; abre circuit si
        cruza threshold."""
        now = time.time()
        with self._lock:
            state = self._get_state(key)
            if state.state == CircuitState.HALF_OPEN:
                # Half-open + fail → vuelve a OPEN inmediatamente.
                state.half_open_in_flight = max(0, state.half_open_in_flight - 1)
                state.state = CircuitState.OPEN
                state.opened_at = now
                state.consecutive_failures += 1
                return

            state.consecutive_failures += 1
            if state.consecutive_failures >= self._config.failure_threshold:
                state.state = CircuitState.OPEN
                state.opened_at = now

    def get_state(self, key: str) -> CircuitState:
        """Read-only. Útil para health checks / dashboard."""
        with self._lock:
            return self._get_state(key).state

    def reset(self, key: str | None = None) -> None:
        """Resetea estado (todo o por key). Para tests / admin."""
        with self._lock:
            if key is None:
                self._states.clear()
            else:
                self._states.pop(key, None)

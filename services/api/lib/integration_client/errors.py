"""IntegrationClient — excepciones tipadas (rev. 105 Sem 2 F.2).

Jerarquía:
  IntegrationClientError (base)
    ├── ProviderUnavailableError    — provider 5xx / network / timeout
    ├── ProviderRejectedError       — provider 4xx (validación, auth, etc.)
    ├── CircuitOpenError            — circuit breaker abierto, no se intenta
    ├── RateLimitLocalError         — bucket local agotado (no se intenta)
    ├── RetryBudgetExceededError    — agotó retries sin éxito
    └── ResponseValidationError     — provider 200 pero body indica error
"""
from __future__ import annotations

from typing import Any, Optional


class IntegrationClientError(Exception):
    """Base para errores del cliente HTTP."""
    http_status: Optional[int] = None
    retriable: bool = False


class ProviderUnavailableError(IntegrationClientError):
    """Provider devolvió 5xx, timeout o network error. Retriable."""
    retriable = True

    def __init__(self, message: str, status: Optional[int] = None,
                 cause: Optional[Exception] = None):
        super().__init__(message)
        self.http_status = status
        self.cause = cause


class ProviderRejectedError(IntegrationClientError):
    """Provider devolvió 4xx — validación, auth, recurso no encontrado.
    NO retriable (el retry no cambiará el outcome)."""
    retriable = False

    def __init__(self, message: str, status: int, response_body: Optional[Any] = None):
        super().__init__(message)
        self.http_status = status
        self.response_body = response_body


class RateLimitLocalError(IntegrationClientError):
    """Bucket local agotado pre-request. Distinto de ProviderRejectedError 429
    (que sería el remoto). Caller decide si encolar, alertar o retornar
    degraded al usuario. NO retriable inmediato — sugiere retry_after."""
    retriable = False
    http_status = 429

    def __init__(self, provider: str, retry_after_seconds: int):
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Rate limit local agotado para {provider}, "
            f"reintentar en ~{retry_after_seconds}s"
        )


class CircuitOpenError(IntegrationClientError):
    """Circuit breaker abierto. No intentamos request — provider sigue caído.
    Caller puede esperar o retornar degraded response al usuario."""
    retriable = False  # respect circuit breaker decision
    http_status = 503

    def __init__(self, provider: str, opens_until_seconds: float):
        self.provider = provider
        self.opens_until_seconds = opens_until_seconds
        super().__init__(
            f"Circuit breaker abierto para {provider}, "
            f"reintentar en ~{opens_until_seconds:.1f}s"
        )


class RetryBudgetExceededError(IntegrationClientError):
    """Agotó retries sin éxito. Caller debe degradar (alerta, fallback,
    encolar para retry posterior, etc.)."""
    retriable = False

    def __init__(self, attempts: int, last_error: Optional[Exception] = None):
        self.attempts = attempts
        self.last_error = last_error
        msg = f"Retry budget exceeded tras {attempts} intentos"
        if last_error:
            msg += f". Último error: {last_error}"
        super().__init__(msg)


class ResponseValidationError(IntegrationClientError):
    """Provider devolvió HTTP 200 pero body indica error semántico
    (ej. Envia `meta:"error"` en HTTP 200)."""
    retriable = False
    http_status = 200  # técnicamente fue 200

    def __init__(self, message: str, response_body: Optional[Any] = None):
        super().__init__(message)
        self.response_body = response_body

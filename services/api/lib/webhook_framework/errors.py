"""Webhook framework — excepciones tipadas (rev. 105 Sem 2 F.1).

Jerarquía:
  WebhookError (base)
    ├── SignatureError       — firma inválida / faltante
    ├── DuplicateEventError  — evento ya procesado (idempotency)
    └── RateLimitExceededError — token bucket agotado

Estas excepciones permiten al handler base mapear a HTTP status codes
correctamente: 401 (firma), 200 (duplicate, silente), 429 (rate limit).
"""
from __future__ import annotations


class WebhookError(Exception):
    """Base para errores controlados del framework webhook."""
    http_status: int = 400


class SignatureError(WebhookError):
    """Firma de webhook inválida, faltante, o expirada."""
    http_status = 401

    def __init__(self, message: str = "Webhook signature inválida"):
        super().__init__(message)


class DuplicateEventError(WebhookError):
    """Evento ya procesado — caller debería retornar 200 silente
    (provider lo lee como ack y no reintenta)."""
    http_status = 200

    def __init__(self, integration: str, event_uid: str):
        self.integration = integration
        self.event_uid = event_uid
        super().__init__(
            f"Duplicate event ({integration}, {event_uid}) — already processed"
        )


class RateLimitExceededError(WebhookError):
    """TokenBucket agotado. Caller retorna 429 con Retry-After header."""
    http_status = 429

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Rate limit exceeded — retry after {retry_after_seconds}s"
        )

"""Webhook framework — utilidades compartidas (lo que quedó con adopción real).

G14 (auditoría 2026-08-13): la ABC `WebhookHandler` + `signature.py` +
`idempotency.py` se RETIRARON por 0 adopción — los 4 webhooks vivos
(Wompi, MeLi, Aveonline, Telegram) son ad-hoc con su hardening propio
verificado por tests (firmas, dedup, IP allowlist, ACK inmediato); forzarlos
a una ABC genérica no aportaba y cada provider difiere de verdad.

Lo que SÍ tiene consumo productivo (vía `lib/integration_client/base.py`):
  - rate_limit: TokenBucketRule/TokenBucketLimiter per (tenant, integration)
  - errors: jerarquía WebhookError (incl. RateLimitExceededError)

Tests: `tests/test_webhook_rate_limit.py` (+ `test_integration_client.py`).
"""
from .errors import (
    DuplicateEventError,
    RateLimitExceededError,
    SignatureError,
    WebhookError,
)

__all__ = [
    "WebhookError",
    "SignatureError",
    "DuplicateEventError",
    "RateLimitExceededError",
]

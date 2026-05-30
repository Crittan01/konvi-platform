"""Webhook framework genérico (rev. 105 Sem 2 F.1).

Patrón template-method para webhooks inbound de los 5 providers (Wompi, MeLi,
Meta, Envia, Telegram). Consolida verify_signature + idempotency + rate_limit
+ normalize en un flow uniforme.

Componentes (ver módulos individuales):
  - base: WebhookHandler abstract + handle() flow standard
  - signature: SignatureStrategy + 4 implementaciones canónicas
  - idempotency: IdempotencyStrategy wrappeando F.4 webhook_dedup
  - rate_limit: TokenBucketRule per (tenant, integration)
  - errors: excepciones tipadas (WebhookError jerarquía)

Uso típico (cuando se refactorice un webhook existente, ej. Sem 4 Envia):

    from lib.webhook_framework import WebhookHandler
    from lib.webhook_framework.signature import URLSecretTokenStrategy
    from lib.webhook_framework.idempotency import GenericIdempotency
    from lib.webhook_framework.rate_limit import TokenBucketRule

    class AveonlineWebhookHandler(WebhookHandler):
        integration = "aveonline"
        signature_strategy = URLSecretTokenStrategy()
        idempotency_strategy = GenericIdempotency()
        rate_limit = TokenBucketRule(capacity=60, refill_per_sec=1)

        async def normalize(self, payload: dict) -> dict:
            # Mapear payload Aveonline → schema interno shipment_tracking_events
            return {...}

        async def enqueue(self, normalized: dict) -> None:
            # pgmq publish para procesamiento asíncrono.
            ...

NO consumidores aún (rev. 105 Sem 2 F.1 deja el framework ready). Refactor
de webhooks existentes (Wompi, MeLi) y nuevos (Envia, Telegram, Meta) se
hace en Sem 4-5 (P0 integraciones) cuando consuman este framework.
"""
from .base import WebhookHandler
from .errors import (
    WebhookError,
    SignatureError,
    DuplicateEventError,
    RateLimitExceededError,
)

__all__ = [
    "WebhookHandler",
    "WebhookError",
    "SignatureError",
    "DuplicateEventError",
    "RateLimitExceededError",
]

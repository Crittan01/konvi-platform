"""IntegrationClient framework (rev. 105 Sem 2 F.2).

Componentes para clientes HTTP outbound multi-tenant con:
  - Retry exponential backoff + jitter (retry.py)
  - Circuit breaker state machine (circuit.py)
  - Outbound idempotency cache (idempotency.py + MA-1 migration)
  - Rate limiting per (tenant_id, provider) via TokenBucket de F.1
  - Error mapping tipado (errors.py)
  - Template-method execute() flow (base.py)

Uso típico cuando se refactoricen clientes existentes (Sem 4-5 P0 integraciones):

    class EnviaClient(IntegrationClient):
        provider = "envia"

        def get_base_url(self):
            return "https://api.envia.com/"

        def get_auth_headers(self):
            return {"Authorization": f"Bearer {self.api_key}"}

        def validate_response(self, status, body):
            if status == 200 and body.get("meta") == "error":
                raise ResponseValidationError(
                    f"Envia 200 OK pero meta=error: {body}",
                    response_body=body,
                )

NO consumidores aún. Existing clients (services/api/integrations/envia_client.py,
wompi_client.py, meli_client.py) siguen funcionando sin cambios.
"""
from .base import IntegrationClient
from .circuit import CircuitBreaker, CircuitBreakerConfig, CircuitState
from .errors import (
    CircuitOpenError,
    IntegrationClientError,
    ProviderRejectedError,
    ProviderUnavailableError,
    RateLimitLocalError,
    ResponseValidationError,
    RetryBudgetExceededError,
)
from .retry import RetryPolicy, retry_async, retry_sync, default_is_retriable

__all__ = [
    "IntegrationClient",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "RetryPolicy",
    "retry_async",
    "retry_sync",
    "default_is_retriable",
    "IntegrationClientError",
    "ProviderUnavailableError",
    "ProviderRejectedError",
    "CircuitOpenError",
    "RateLimitLocalError",
    "RetryBudgetExceededError",
    "ResponseValidationError",
]

# Re-exports de F.1 lazy (top-level import romperia test loader raw que
# carga sin sys.path setup). Caller importa explícitamente:
#   from lib.webhook_framework.rate_limit import TokenBucketRule
# o usa: integration_client.get_token_bucket_classes() helper si se prefiere.

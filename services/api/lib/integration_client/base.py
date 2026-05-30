"""IntegrationClient abstract base (rev. 105 Sem 2 F.2).

Template-method para clientes HTTP outbound de los 6 providers. Compone:
  - retry policy (exponential backoff + jitter)
  - circuit breaker (failure_threshold + open_duration)
  - idempotency cache (request_hash → cached response)
  - rate limit (TokenBucket reusado de F.1.rate_limit)
  - error mapping (HTTP status → IntegrationClient* error tipado)

Subclass concreta provee:
  - provider: str (canónico)
  - get_base_url() / get_auth_headers() / map_error()
  - normalize_response() opcional

El método `execute()` ejecuta el flow standard:
  1. circuit_breaker.before_request → CircuitOpenError si OPEN
  2. rate_limiter.consume → RateLimitLocalError si bucket vacío
  3. construye URL completa
  4. idempotency.lookup → return cached si hit
  5. retry_async wrapping http call
  6. validate_response semántico (ej. Envia meta:"error" en 200)
  7. circuit_breaker.record_success / record_failure
  8. idempotency.register tras 2xx success

Caller construye una instancia con todas las strategies inyectadas:

    client = EnviaClient(
        tenant_id=tenant_id,
        api_key="...",
        retry_policy=RetryPolicy(max_attempts=4),
        circuit_breaker=CircuitBreaker(),
        idempotency_enabled=True,
        rate_limit_rule=TokenBucketRule(capacity=60, refill_per_sec=1.0),
    )
    label = await client.execute(
        method="POST",
        path="/ship/generate/",
        body={"shipments": [...]},
    )
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from . import idempotency as idemp
from .circuit import CircuitBreaker
from .errors import (
    IntegrationClientError,
    ProviderRejectedError,
    ProviderUnavailableError,
    RateLimitLocalError,
    ResponseValidationError,
)
from .retry import RetryPolicy, default_is_retriable, retry_async

# Rate limiting: reuso del TokenBucket de F.1 (webhook_framework).
# Lazy import dentro de __init__/execute() para que test_integration_client.py
# (que carga este módulo via importlib raw sin sys.path setup) no necesite
# resolver lib.webhook_framework.

logger = logging.getLogger(__name__)


class IntegrationClient(ABC):
    """Subclass por provider. Inyectar dependencias por constructor."""

    provider: str  # canónico ('aveonline', 'wompi', 'meli', 'meta', 'telegram', 'resend')

    def __init__(
        self,
        *,
        tenant_id: str,
        supabase_client: Optional[Any] = None,
        retry_policy: Optional[RetryPolicy] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        idempotency_enabled: bool = False,
        idempotency_ttl_seconds: int = idemp.DEFAULT_TTL_SECONDS,
        rate_limit_rule: Optional[Any] = None,  # TokenBucketRule (lazy)
        rate_limiter: Optional[Any] = None,     # TokenBucketLimiter (lazy)
        http_client: Optional[Any] = None,  # httpx.AsyncClient inyectable para tests
    ):
        self.tenant_id = tenant_id
        self._sb = supabase_client
        self.retry_policy = retry_policy or RetryPolicy()
        self.circuit_breaker = circuit_breaker
        self.idempotency_enabled = idempotency_enabled
        self.idempotency_ttl = idempotency_ttl_seconds
        self.rate_limit_rule = rate_limit_rule
        # Singleton global por defecto; inyectable en tests para aislamiento.
        if rate_limiter is not None:
            self._rate_limiter = rate_limiter
        elif rate_limit_rule is not None:
            from lib.webhook_framework.rate_limit import get_global_limiter
            self._rate_limiter = get_global_limiter()
        else:
            self._rate_limiter = None
        self._http = http_client

    # ── Abstractos ───────────────────────────────────────────────────────────

    @abstractmethod
    def get_base_url(self) -> str:
        """URL base del provider (e.g. 'https://api.aveonline.co/')."""

    @abstractmethod
    def get_auth_headers(self) -> dict[str, str]:
        """Headers de autenticación (Bearer, API-Key, etc.)."""

    def map_error(self, status: int, body: Any) -> Optional[IntegrationClientError]:
        """Override para mapear errores específicos del provider. Default
        retorna error genérico basado en status."""
        if 200 <= status < 300:
            return None
        if 400 <= status < 500:
            return ProviderRejectedError(
                f"{self.provider} HTTP {status}",
                status=status,
                response_body=body,
            )
        return ProviderUnavailableError(
            f"{self.provider} HTTP {status}", status=status,
        )

    def validate_response(self, status: int, body: Any) -> None:
        """Override para validar 200 OK con body indicando error semántico
        (ej. Envia `meta:"error"` HTTP 200). Levanta ResponseValidationError."""
        return None

    # ── Flow standard ────────────────────────────────────────────────────────

    async def execute(
        self,
        *,
        method: str,
        path: str,
        body: Any | None = None,
        params: Optional[dict[str, Any]] = None,
        extra_headers: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ejecuta request con todas las protecciones. Retorna
        {status, body, headers, cached: bool}.

        Levanta IntegrationClientError jerarquía según fallo. NO levanta
        excepciones genéricas (httpx.* etc.) — todas se mapean.
        """
        # 1. Circuit breaker check.
        if self.circuit_breaker is not None:
            self.circuit_breaker.before_request(self.provider)

        # 2. Rate limit consume (per tenant_id+provider, in-memory TokenBucket).
        #    Si bucket vacío levanta RateLimitLocalError (HTTP 429 semántico).
        #    NO cuenta como failure del circuit breaker — el provider no fue
        #    contactado, fue el caller quien excedió su quota local.
        if self.rate_limit_rule is not None and self._rate_limiter is not None:
            from lib.webhook_framework.errors import (
                RateLimitExceededError as _WebhookRLE,
            )
            try:
                self._rate_limiter.consume(
                    tenant_id=self.tenant_id,
                    integration=self.provider,
                    rule=self.rate_limit_rule,
                )
            except _WebhookRLE as e:
                raise RateLimitLocalError(
                    provider=self.provider,
                    retry_after_seconds=e.retry_after_seconds,
                ) from e

        # 3. Construir URL completa.
        url = self.get_base_url().rstrip("/") + "/" + path.lstrip("/")

        # 4. Idempotency cache lookup (POST/PUT/PATCH).
        request_hash: Optional[str] = None
        if self.idempotency_enabled and method.upper() in {"POST", "PUT", "PATCH"}:
            request_hash = idempotency_key or idemp.hash_request(method, url, body)
            if self._sb is not None:
                cached = idemp.lookup(
                    self._sb, self.provider, self.tenant_id, request_hash
                )
                if cached is not None:
                    if self.circuit_breaker is not None:
                        # Cached counts as success (no nueva interacción provider).
                        self.circuit_breaker.record_success(self.provider)
                    return {
                        "status": cached.status,
                        "body": cached.body,
                        "headers": cached.headers,
                        "cached": True,
                    }

        # 5. Retry-wrapped HTTP call.
        async def _do_request() -> dict[str, Any]:
            return await self._do_http(
                method=method,
                url=url,
                body=body,
                params=params,
                extra_headers=extra_headers,
            )

        try:
            response = await retry_async(
                _do_request,
                policy=self.retry_policy,
                is_retriable=default_is_retriable,
            )
        except IntegrationClientError as e:
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure(self.provider)
            raise

        # 6. Validar response semántico (ej. meta:"error" en 200).
        self.validate_response(response["status"], response["body"])

        # 7. Registrar circuit success.
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_success(self.provider)

        # 8. Cachear response (si idempotency enabled + 2xx + sb client).
        if (
            self.idempotency_enabled
            and request_hash is not None
            and self._sb is not None
            and 200 <= response["status"] < 300
        ):
            try:
                idemp.register(
                    self._sb,
                    self.provider,
                    self.tenant_id,
                    request_hash,
                    status=response["status"],
                    body=response["body"],
                    headers=response.get("headers"),
                    ttl_seconds=self.idempotency_ttl,
                )
            except Exception as e:  # pragma: no cover
                # Cache write failure NO debe romper el flow principal.
                logger.warning(
                    "[INTG] %s idempotency register falló (no crítico): %s",
                    self.provider, e,
                )

        response["cached"] = False
        return response

    # ── HTTP transport (override para tests) ─────────────────────────────────

    async def _do_http(
        self,
        *,
        method: str,
        url: str,
        body: Any | None,
        params: Optional[dict[str, Any]],
        extra_headers: Optional[dict[str, str]],
    ) -> dict[str, Any]:
        """Realiza el HTTP request real. Override en tests con stub. En
        producción usa httpx.AsyncClient."""
        headers = dict(self.get_auth_headers())
        if extra_headers:
            headers.update(extra_headers)

        if self._http is None:
            # Lazy import — httpx ya es dependency en services/api.
            import httpx  # noqa: PLC0415
            async with httpx.AsyncClient(timeout=30.0) as client:
                http_resp = await client.request(
                    method=method,
                    url=url,
                    json=body if body is not None else None,
                    params=params,
                    headers=headers,
                )
        else:
            http_resp = await self._http.request(
                method=method, url=url, json=body, params=params, headers=headers,
            )

        try:
            resp_body = http_resp.json() if http_resp.content else {}
        except (ValueError, AttributeError):
            resp_body = {"_raw": http_resp.text if hasattr(http_resp, "text") else ""}

        # Mapear error si status indica fallo.
        mapped = self.map_error(http_resp.status_code, resp_body)
        if mapped is not None:
            raise mapped

        return {
            "status": http_resp.status_code,
            "body": resp_body,
            "headers": dict(http_resp.headers) if hasattr(http_resp, "headers") else {},
        }

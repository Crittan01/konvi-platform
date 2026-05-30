"""WebhookHandler abstract base (rev. 105 Sem 2 F.1).

Template-method para webhooks inbound. Subclass concreta provee:
  - integration: str            (canónico: 'wompi'|'meli'|'meta'|'aveonline'|'telegram')
  - signature_strategy
  - idempotency_strategy
  - rate_limit (opcional)
  - extract_event_uid(payload) → str
  - resolve_tenant_id(payload, headers) → Optional[str]
  - normalize(payload) → dict   (mapeo a schema interno)
  - enqueue(normalized) → None  (pgmq publish o procesamiento sync)

El método `handle()` ejecuta el flow standard:
  1. signature verify
  2. parse JSON
  3. extract event_uid + tenant_id (resolver opcional)
  4. rate limit check (si configurado)
  5. idempotency check (raise DuplicateEventError → 200 silente)
  6. normalize payload
  7. enqueue (sync o pgmq)
  8. mark_processed

Errores tipados se mapean a HTTP responses por `to_http_response()`.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from .errors import (
    DuplicateEventError,
    RateLimitExceededError,
    SignatureError,
    WebhookError,
)
from .idempotency import IdempotencyStrategy
from .rate_limit import TokenBucketLimiter, TokenBucketRule, get_global_limiter
from .signature import SignatureStrategy

logger = logging.getLogger(__name__)


class WebhookHandler(ABC):
    """Subclass por integration. Atributos de clase son la "configuración";
    los métodos abstractos son los hooks específicos del provider."""

    # ── Atributos de clase (subclass debe definir) ─────────────────────────
    integration: str
    signature_strategy: SignatureStrategy
    idempotency_strategy: IdempotencyStrategy
    rate_limit: Optional[TokenBucketRule] = None
    rate_limiter: Optional[TokenBucketLimiter] = None  # default: global

    # ── Hooks abstractos (subclass debe implementar) ────────────────────────

    @abstractmethod
    def extract_event_uid(self, payload: dict[str, Any]) -> str:
        """Extrae el UID único del evento del payload. Wompi=event.id,
        MeLi=app_id|resource|sent, Meta=message.id, etc."""

    def resolve_tenant_id(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> Optional[str]:
        """Resuelve tenant_id del request. Override per integration. Default:
        None (handler usa fallback flow). Para webhooks que entran sin
        tenant context (Telegram /BotFather, Meta verify), retornar None
        es válido."""
        return None

    @abstractmethod
    async def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Mapea el payload del provider a schema interno (cart_events,
        shipments, payments, etc.)."""

    @abstractmethod
    async def enqueue(self, normalized: dict[str, Any]) -> None:
        """Publica el evento normalizado para procesamiento. Patrón típico:
        pgmq publish; alternativas: BackgroundTask FastAPI o procesamiento
        sync mismo handler (no recomendado para latencia provider)."""

    # ── Flow standard (no override) ─────────────────────────────────────────

    async def handle(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        query_params: dict[str, str],
        client_ip: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ejecuta el flow completo. Retorna dict para respuesta JSON.
        Levanta WebhookError jerarquía — caller mapea a HTTP via
        to_http_response().

        El caller en FastAPI típico:
            try:
                result = await handler.handle(raw_body=..., headers=..., ...)
                return JSONResponse(content=result, status_code=200)
            except WebhookError as e:
                return to_http_response(e)
        """
        # 1. Signature verify (raises SignatureError → 401)
        self.signature_strategy.verify(
            raw_body=raw_body,
            headers=headers,
            query_params=query_params,
            client_ip=client_ip,
        )

        # 2. Parse JSON.
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except (UnicodeDecodeError, ValueError) as e:
            raise WebhookError(f"Body no es JSON válido: {e}") from e

        # 3. Extract metadata.
        event_uid = self.extract_event_uid(payload)
        if not event_uid:
            raise WebhookError("event_uid no extraído del payload")
        tenant_id = self.resolve_tenant_id(payload, headers)

        # 4. Rate limit (opcional).
        if self.rate_limit is not None and tenant_id is not None:
            limiter = self.rate_limiter or get_global_limiter()
            limiter.consume(
                tenant_id=tenant_id,
                integration=self.integration,
                rule=self.rate_limit,
            )

        # 5. Idempotency check (raises DuplicateEventError → 200 silente).
        self.idempotency_strategy.check_duplicate(
            integration=self.integration,
            event_uid=event_uid,
            tenant_id=tenant_id,
            event_type=str(payload.get("event_type") or payload.get("type") or ""),
        )

        # 6. Normalize.
        try:
            normalized = await self.normalize(payload)
        except Exception as e:
            logger.error(
                "[WH_FW] %s normalize falló event=%s: %s",
                self.integration, event_uid, e,
            )
            raise WebhookError(f"normalize error: {e}") from e

        # 7. Enqueue (sync o async).
        try:
            await self.enqueue(normalized)
        except Exception as e:
            logger.error(
                "[WH_FW] %s enqueue falló event=%s: %s",
                self.integration, event_uid, e,
            )
            # NO marcar processed — provider reintentará.
            raise WebhookError(f"enqueue error: {e}") from e

        # 8. Mark processed (idempotente).
        self.idempotency_strategy.mark_processed(
            integration=self.integration,
            event_uid=event_uid,
        )

        return {"ok": True, "event_uid": event_uid, "integration": self.integration}


def to_http_response(error: WebhookError) -> dict[str, Any]:
    """Helper para FastAPI: mapea WebhookError jerarquía a payload + status.
    Caller construye JSONResponse(content=payload, status_code=status).
    """
    payload: dict[str, Any] = {"ok": False, "error": type(error).__name__, "detail": str(error)}
    headers: dict[str, str] = {}

    if isinstance(error, DuplicateEventError):
        # 200 silente — provider lee como ack y no reintenta.
        payload["ok"] = True
        payload["duplicate"] = True
        payload["integration"] = error.integration
        payload["event_uid"] = error.event_uid
    elif isinstance(error, RateLimitExceededError):
        headers["Retry-After"] = str(error.retry_after_seconds)

    return {
        "status": error.http_status,
        "payload": payload,
        "headers": headers,
    }

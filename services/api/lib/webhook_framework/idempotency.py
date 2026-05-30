"""Webhook idempotency strategies (rev. 105 Sem 2 F.1).

Wrappea F.4 webhook_dedup en interfaz consumible por WebhookHandler.

Patrón at-least-once safe:
  1. Antes de procesar, llamar `is_duplicate(integration, event_uid)`.
  2. Si True → DuplicateEventError (handler retorna 200 silente).
  3. Si False → procesar payload.
  4. Al terminar OK → llamar `mark_processed(integration, event_uid)`.
  5. Si falla procesamiento → NO marcar processed_at; provider reintentará.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from .errors import DuplicateEventError


class IdempotencyStrategy(ABC):
    """Contrato abstracto para idempotency check."""

    @abstractmethod
    def check_duplicate(
        self,
        *,
        integration: str,
        event_uid: str,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Levanta DuplicateEventError si duplicado. None si OK procesar."""

    @abstractmethod
    def mark_processed(
        self,
        *,
        integration: str,
        event_uid: str,
    ) -> bool:
        """Marca el evento como processed. Retorna True si actualizó fila."""


class GenericIdempotency(IdempotencyStrategy):
    """Idempotency vía F.4 webhook_dedup (tabla webhook_events_seen + RPCs).

    NOTA: requiere que F.4 ya esté aplicada en DB (commit 05f7417).
    Usa supabase client inyectado por constructor.
    """

    def __init__(self, supabase_client: Any):
        self._sb = supabase_client

    def check_duplicate(
        self,
        *,
        integration,
        event_uid,
        tenant_id=None,
        event_type=None,
        correlation_id=None,
    ):
        # Lazy import para evitar dependencia circular si lib/webhook_dedup
        # se carga en otro orden.
        try:
            from lib.webhook_dedup import is_duplicate  # noqa: PLC0415
        except ImportError:
            from ..webhook_dedup import is_duplicate  # type: ignore  # noqa: PLC0415

        if is_duplicate(
            self._sb,
            integration,
            event_uid,
            tenant_id=tenant_id,
            event_type=event_type,
            correlation_id=correlation_id,
        ):
            raise DuplicateEventError(integration, event_uid)

    def mark_processed(self, *, integration, event_uid):
        try:
            from lib.webhook_dedup import mark_processed  # noqa: PLC0415
        except ImportError:
            from ..webhook_dedup import mark_processed  # type: ignore  # noqa: PLC0415
        return mark_processed(self._sb, integration, event_uid)


class CallbackIdempotency(IdempotencyStrategy):
    """Strategy custom — caller provee callbacks para check + mark.
    Útil para tests, in-memory test, o backends alternativos."""

    def __init__(
        self,
        *,
        check_fn: Callable[..., bool],
        mark_fn: Callable[..., bool],
    ):
        self._check = check_fn
        self._mark = mark_fn

    def check_duplicate(
        self,
        *,
        integration,
        event_uid,
        tenant_id=None,
        event_type=None,
        correlation_id=None,
    ):
        if self._check(
            integration=integration,
            event_uid=event_uid,
            tenant_id=tenant_id,
            event_type=event_type,
            correlation_id=correlation_id,
        ):
            raise DuplicateEventError(integration, event_uid)

    def mark_processed(self, *, integration, event_uid):
        return self._mark(integration=integration, event_uid=event_uid)

"""Eventos de dominio (D6) — sin infraestructura nueva.

Las operaciones de escritura declaran y emiten `DomainEvent`; el bus es el
existente, mapeado por el adaptador de cada servicio: `cart_events` (16 tipos
canónicos), `audit_log` (`write_audit_event`), `messages` (`claim_audit`),
notificaciones WA/email/Telegram ya cableadas. Regla del contrato: escritura
sin evento = contrato inválido (verificable por test estructural).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """Hecho de negocio emitido por una operación (p.ej. `order.cancelled`)."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

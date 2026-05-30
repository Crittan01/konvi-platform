"""Channel Registry — pluggable adapter system (rev. 109 backlog #3).

Permite agregar canales nuevos (Messenger, Instagram, Web chat, SMS,
TikTok Shop, etc.) sin tocar el orchestrator. Cada canal implementa
`ChannelAdapter` Protocol (ver base.py) y se registra aquí.

Uso:

    # Lectura — orchestrator obtiene el adapter por channel string
    from lib.channels import get_channel_adapter
    adapter = get_channel_adapter("whatsapp")
    if adapter:
        await adapter.send_outbound(
            tenant_id=tid, recipient=phone, text="Hola", supabase=sb,
        )

    # Registro — un módulo de canal nuevo se auto-registra:
    from lib.channels import register_channel
    register_channel("messenger", MessengerAdapter())

Diseño:
  • Registry singleton _ADAPTERS dict.
  • Lookups O(1) por channel name.
  • Backward-compat total: si un canal NO tiene adapter registrado,
    callers caen al código legacy (whatsapp_sender, etc.).

Stubs ya registrados (placeholders sin implementación real):
  • 'whatsapp' — placeholder (legacy whatsapp_sender sigue activo).
  • 'web'      — placeholder para Storefront (#4 backlog).
  • 'messenger', 'instagram' — placeholders. Implementación cuando demand.

Para agregar un canal nuevo:
  1. Crear `services/api/lib/channels/messenger.py` con clase
     `MessengerAdapter` que implemente `ChannelAdapter` Protocol.
  2. Importarla aquí + register_channel('messenger', MessengerAdapter()).
  3. Connector externo (e.g. connector-messenger) usa el adapter para
     send_outbound + parse_inbound.
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import (
    ChannelAdapter,
    ComplianceVerdict,
    InboundMessage,
    OutboundResult,
)

logger = logging.getLogger("api.channels")


_ADAPTERS: dict[str, ChannelAdapter] = {}


def register_channel(name: str, adapter: ChannelAdapter) -> None:
    """Registra un adapter para un canal. Idempotente (sobreescribe)."""
    n = (name or "").strip().lower()
    if not n:
        raise ValueError("channel name no puede ser vacío")
    if not isinstance(adapter, ChannelAdapter):
        # Protocol runtime check; advierte pero permite registrar.
        logger.warning(
            "[CHANNELS] adapter for %r no cumple ChannelAdapter Protocol — "
            "puede romper en runtime",
            n,
        )
    _ADAPTERS[n] = adapter
    logger.info("[CHANNELS] registered adapter for channel=%r", n)


def get_channel_adapter(name: str) -> Optional[ChannelAdapter]:
    """Lookup. None si no hay adapter registrado (caller cae a legacy)."""
    n = (name or "").strip().lower()
    return _ADAPTERS.get(n)


def list_registered_channels() -> list[str]:
    """Para debug / health checks."""
    return sorted(_ADAPTERS.keys())


# ─── Stub adapters (placeholders sin implementación real) ───────────────────


class _StubAdapter:
    """Adapter placeholder. Loguea warning si se invoca — útil para
    detectar canales documentados pero NO implementados aún."""

    def __init__(self, channel: str):
        self._channel = channel

    def channel_name(self) -> str:
        return self._channel

    def parse_inbound(self, payload: dict) -> InboundMessage:
        raise NotImplementedError(
            f"stub adapter for channel={self._channel!r} — "
            "implement parse_inbound"
        )

    async def send_outbound(self, **kwargs) -> OutboundResult:
        logger.warning(
            "[CHANNELS] stub send_outbound channel=%r — not implemented yet",
            self._channel,
        )
        return OutboundResult(
            ok=False, error_code="STUB_ADAPTER",
            error_message=(
                f"Adapter for channel {self._channel!r} es un stub. "
                f"Implementación pendiente backlog."
            ),
        )

    def verify_signature(self, **kwargs) -> bool:
        # Stub: rechaza por defecto (security default-deny).
        return False

    async def compliance_check(self, **kwargs) -> ComplianceVerdict:
        return ComplianceVerdict(
            ok=False, reason_code="STUB_ADAPTER",
            user_message=f"Canal {self._channel!r} no implementado.",
        )


# Pre-registro de stubs para canales planeados (documentación viva).
# Cuando se implemente un canal real, su módulo de adapter sobreescribirá
# el stub con register_channel().
register_channel("whatsapp", _StubAdapter("whatsapp"))
register_channel("meli", _StubAdapter("meli"))
register_channel("telegram", _StubAdapter("telegram"))
register_channel("web", _StubAdapter("web"))
register_channel("messenger", _StubAdapter("messenger"))
register_channel("instagram", _StubAdapter("instagram"))
register_channel("sms", _StubAdapter("sms"))


__all__ = [
    "ChannelAdapter",
    "ComplianceVerdict",
    "InboundMessage",
    "OutboundResult",
    "register_channel",
    "get_channel_adapter",
    "list_registered_channels",
]

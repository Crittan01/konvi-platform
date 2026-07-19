"""Commerce Channel Registry — eje COMERCIO del sistema de adaptadores (ADR-0038).

Hermano de `lib/channels` (eje mensajería). Registry SEPARADO a propósito: así un
canal puede ser commerce-only (MeLi, sin `send_outbound`) o messaging-only
(WhatsApp, sin `publish_listing`) sin polución de stubs cruzados.

Uso:

    from lib.commerce import get_commerce_adapter
    adapter = get_commerce_adapter("meli")
    if adapter and "sync_stock" in adapter.capabilities():
        await adapter.sync_stock(tenant_id=tid, ref=ref, quantity=n, supabase=sb)

    # Un canal real se auto-registra sobreescribiendo el stub:
    from lib.commerce import register_commerce_channel
    register_commerce_channel("shopify", ShopifyCommerceAdapter())

Diseño:
  • Registry singleton _COMMERCE_ADAPTERS. Lookup O(1).
  • Stubs default-deny pre-registrados (documentación viva + fail-closed): writes
    devuelven ok=False/STUB_ADAPTER, verify_origin devuelve False, capabilities
    vacío. Nadie publica/vende por accidente antes de implementar el canal.
  • Backward-compat: mientras el adapter real no exista, los callers siguen
    usando la mecánica legacy (marketplace.py / meli_client.py). El adapter es el
    destino del refactor P1, no un reemplazo big-bang.
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import (
    CatalogItem,
    ChannelCategory,
    ChannelListingState,
    CommerceChannelAdapter,
    IngestedOrder,
    IngestedOrderLine,
    ListingRef,
    ListingValidation,
    OrderNotification,
    PriceSyncResult,
    PublishResult,
    RequiredAttribute,
    StockSyncResult,
)

logger = logging.getLogger("api.commerce")


_COMMERCE_ADAPTERS: dict[str, CommerceChannelAdapter] = {}


def register_commerce_channel(name: str, adapter: CommerceChannelAdapter) -> None:
    """Registra un adapter de comercio. Idempotente (sobreescribe el stub)."""
    n = (name or "").strip().lower()
    if not n:
        raise ValueError("commerce channel name no puede ser vacío")
    if not isinstance(adapter, CommerceChannelAdapter):
        logger.warning(
            "[COMMERCE] adapter for %r no cumple CommerceChannelAdapter Protocol "
            "— puede romper en runtime",
            n,
        )
    _COMMERCE_ADAPTERS[n] = adapter
    logger.info("[COMMERCE] registered commerce adapter for channel=%r", n)


def get_commerce_adapter(name: str) -> Optional[CommerceChannelAdapter]:
    """Lookup. None si no hay adapter registrado."""
    n = (name or "").strip().lower()
    return _COMMERCE_ADAPTERS.get(n)


def list_registered_commerce_channels() -> list[str]:
    """Para debug / health checks."""
    return sorted(_COMMERCE_ADAPTERS.keys())


# ─── Stub adapter (default-deny; fail-closed) ───────────────────────────────


class _StubCommerceAdapter:
    """Placeholder de un canal documentado pero NO implementado. Todo lo que
    escribe/publica falla explícito (ok=False/STUB_ADAPTER); verify_origin
    rechaza; capabilities vacío. Loguea al invocarse para detectar canales
    planeados que aún no tienen adapter real."""

    def __init__(self, channel: str):
        self._channel = channel

    def channel_name(self) -> str:
        return self._channel

    def capabilities(self) -> set:
        return set()

    def _deny_pub(self) -> PublishResult:
        logger.warning("[COMMERCE] stub write channel=%r — not implemented", self._channel)
        return PublishResult(
            ok=False, error_code="STUB_ADAPTER",
            error_message=f"Commerce adapter for {self._channel!r} es un stub.",
        )

    async def publish_listing(self, **kwargs) -> PublishResult:
        return self._deny_pub()

    async def update_listing(self, **kwargs) -> PublishResult:
        return self._deny_pub()

    async def pause_listing(self, **kwargs) -> PublishResult:
        return self._deny_pub()

    async def resume_listing(self, **kwargs) -> PublishResult:
        return self._deny_pub()

    async def close_listing(self, **kwargs) -> PublishResult:
        return self._deny_pub()

    async def sync_images(self, **kwargs) -> PublishResult:
        return self._deny_pub()

    async def sync_stock(self, **kwargs) -> StockSyncResult:
        logger.warning("[COMMERCE] stub sync_stock channel=%r", self._channel)
        return StockSyncResult(ok=False, error_code="STUB_ADAPTER")

    async def sync_price(self, **kwargs) -> PriceSyncResult:
        logger.warning("[COMMERCE] stub sync_price channel=%r", self._channel)
        return PriceSyncResult(ok=False, error_code="STUB_ADAPTER")

    async def fetch_categories(self, **kwargs) -> list:
        return []

    async def fetch_category_attributes(self, **kwargs) -> list:
        return []

    async def suggest_category(self, **kwargs) -> Optional[ChannelCategory]:
        return None

    def validate_for_publish(self, **kwargs) -> ListingValidation:
        return ListingValidation(ok=False, errors=["STUB_ADAPTER"])

    def verify_origin(self, **kwargs) -> bool:
        # Security default-deny.
        return False

    def parse_order_notification(self, payload: dict) -> OrderNotification:
        raise NotImplementedError(
            f"stub commerce adapter for {self._channel!r} — implement parse_order_notification"
        )

    async def fetch_order(self, **kwargs) -> IngestedOrder:
        raise NotImplementedError(
            f"stub commerce adapter for {self._channel!r} — implement fetch_order"
        )

    async def list_orders(self, **kwargs) -> list:
        return []

    async def fetch_listing(self, **kwargs) -> ChannelListingState:
        raise NotImplementedError(
            f"stub commerce adapter for {self._channel!r} — implement fetch_listing"
        )


# Pre-registro de stubs para los canales de comercio planeados (ADR-0038).
# El adapter real de cada canal sobreescribirá su stub con register_commerce_channel().
register_commerce_channel("meli", _StubCommerceAdapter("meli"))
register_commerce_channel("shopify", _StubCommerceAdapter("shopify"))
register_commerce_channel("web", _StubCommerceAdapter("web"))


__all__ = [
    "CommerceChannelAdapter",
    "CatalogItem", "ListingRef", "PublishResult", "StockSyncResult", "PriceSyncResult",
    "ChannelCategory", "RequiredAttribute", "ListingValidation",
    "IngestedOrder", "IngestedOrderLine", "OrderNotification", "ChannelListingState",
    "register_commerce_channel", "get_commerce_adapter", "list_registered_commerce_channels",
]

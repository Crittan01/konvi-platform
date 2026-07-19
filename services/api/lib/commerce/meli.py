"""MeliCommerceAdapter — implementación del eje COMERCIO para Mercado Libre (ADR-0038, P1).

Envuelve la mecánica MeLi existente (`integrations/meli_client.py`) detrás del
contrato `CommerceChannelAdapter`, resolviendo el token per-tenant internamente
(patrón OAuth existente: `get_valid_token` con single-flight refresh + Vault).

P1 = OUTBOUND (write) + reconcile — las operaciones que hoy soporta MeLi vía API
y mapean 1:1 a meli_client. Declaradas en capabilities(); el dispatcher salta las
que no están (degradación grácil):
  • sync_stock  → update_item_quantity        (item-level; variaciones vía update_listing)
  • sync_price  → update_item_price
  • update_listing → update_item_listing       (stock+precio, soporta variaciones)
  • pause/resume/close → update_item_status(paused/active/closed)
  • fetch_listing → get_item                   (reconciliación de drift)

NO declarado aún (honesto, viene en incrementos siguientes):
  • "publish"/"categories"/"attributes" — MeLi es import-only hasta P4 (POST /items).
  • "order_ingest" — la ingesta inbound (parse/fetch_order/verify_origin) se envuelve
    en el incremento P1-inbound; hoy la sigue manejando meli_webhook.py.

Invariante: el adapter es PURE I/O — NO escribe DB. Propaga rate-limit (429 /
Retry-After) al caller vía error_code/retry_after_seconds, sin acoplarlo a MeLi.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from integrations import meli_client

from .base import (
    CatalogItem,
    ChannelListingState,
    ListingRef,
    PriceSyncResult,
    PublishResult,
    StockSyncResult,
)

logger = logging.getLogger("api.commerce.meli")

_CAPABILITIES = frozenset({
    "update", "pause", "resume", "close",
    "sync_stock", "sync_price", "reconcile",
})


def _retry_after(exc: httpx.HTTPStatusError) -> Optional[int]:
    """Extrae Retry-After (segundos) de un 429/503 para propagar el rate-limit."""
    try:
        ra = exc.response.headers.get("Retry-After")
        return int(ra) if ra and ra.isdigit() else None
    except Exception:  # noqa: BLE001
        return None


class MeliCommerceAdapter:
    """Adapter de comercio para Mercado Libre. Stateless; el token se resuelve
    por-llamada desde Supabase."""

    def channel_name(self) -> str:
        return "meli"

    def capabilities(self) -> set:
        return set(_CAPABILITIES)

    # ── resolución de credencial per-tenant ──
    async def _token(self, tenant_id: str, supabase: Any) -> Optional[str]:
        sb = supabase
        if sb is None:
            # Lazy import para no acoplar el módulo al ciclo de dependencias.
            from dependencies.auth import _get_service_client
            sb = _get_service_client()
        return await meli_client.get_valid_token(sb, tenant_id)

    # ── B. Sync de campo ──
    async def sync_stock(self, *, tenant_id: str, ref: ListingRef, quantity: int,
                         siblings: Optional[list] = None, supabase: Any = None) -> StockSyncResult:
        tok = await self._token(tenant_id, supabase)
        if not tok:
            return StockSyncResult(ok=False, error_code="NO_TOKEN",
                                   error_message="Integración MeLi no conectada o token no disponible.")
        try:
            await meli_client.update_item_quantity(ref.external_id, quantity, tok)
            return StockSyncResult(ok=True, synced_quantity=max(0, quantity))
        except httpx.HTTPStatusError as e:
            return StockSyncResult(ok=False, error_code=str(e.response.status_code),
                                   error_message=str(e)[:200], retry_after_seconds=_retry_after(e))
        except Exception as e:  # noqa: BLE001
            return StockSyncResult(ok=False, error_code="ERROR", error_message=str(e)[:200])

    async def sync_price(self, *, tenant_id: str, ref: ListingRef, price: float,
                         compare_at: Optional[float] = None, supabase: Any = None) -> PriceSyncResult:
        tok = await self._token(tenant_id, supabase)
        if not tok:
            return PriceSyncResult(ok=False, error_code="NO_TOKEN")
        try:
            await meli_client.update_item_price(ref.external_id, price, tok)
            return PriceSyncResult(ok=True, synced_price=float(int(round(price))))
        except httpx.HTTPStatusError as e:
            return PriceSyncResult(ok=False, error_code=str(e.response.status_code),
                                   error_message=str(e)[:200], retry_after_seconds=_retry_after(e))
        except Exception as e:  # noqa: BLE001
            return PriceSyncResult(ok=False, error_code="ERROR", error_message=str(e)[:200])

    # ── A. Ciclo de vida ──
    async def update_listing(self, *, tenant_id: str, ref: ListingRef, item: CatalogItem,
                             supabase: Any = None) -> PublishResult:
        """Sync combinado stock+precio en un PUT. Variaciones: si item.raw trae
        'meli_variations' (armadas por el caller desde marketplace_listings), se
        envían; si no, es item-level."""
        tok = await self._token(tenant_id, supabase)
        if not tok:
            return PublishResult(ok=False, error_code="NO_TOKEN")
        meli_variations = (item.raw or {}).get("meli_variations") if item.raw else None
        try:
            await meli_client.update_item_listing(
                ref.external_id, item.available_quantity, item.price,
                item.compare_at_price, tok, meli_variations=meli_variations,
            )
            return PublishResult(ok=True, external_id=ref.external_id)
        except httpx.HTTPStatusError as e:
            return PublishResult(ok=False, error_code=str(e.response.status_code),
                                 error_message=str(e)[:200], retry_after_seconds=_retry_after(e))
        except Exception as e:  # noqa: BLE001
            return PublishResult(ok=False, error_code="ERROR", error_message=str(e)[:200])

    async def _set_status(self, tenant_id: str, ref: ListingRef, status: str, supabase: Any) -> PublishResult:
        tok = await self._token(tenant_id, supabase)
        if not tok:
            return PublishResult(ok=False, error_code="NO_TOKEN")
        try:
            await meli_client.update_item_status(ref.external_id, status, tok)
            return PublishResult(ok=True, external_id=ref.external_id)
        except httpx.HTTPStatusError as e:
            return PublishResult(ok=False, error_code=str(e.response.status_code),
                                 error_message=str(e)[:200], retry_after_seconds=_retry_after(e))
        except Exception as e:  # noqa: BLE001
            return PublishResult(ok=False, error_code="ERROR", error_message=str(e)[:200])

    async def pause_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> PublishResult:
        return await self._set_status(tenant_id, ref, "paused", supabase)

    async def resume_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> PublishResult:
        return await self._set_status(tenant_id, ref, "active", supabase)

    async def close_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> PublishResult:
        # 'closed' es irreversible en MeLi (delete lógico) — igual que el legacy.
        return await self._set_status(tenant_id, ref, "closed", supabase)

    # ── E. Reconciliación ──
    async def fetch_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> ChannelListingState:
        tok = await self._token(tenant_id, supabase)
        if not tok:
            return ChannelListingState(external_id=ref.external_id, status="unknown")
        data = await meli_client.get_item(ref.external_id, tok)
        return ChannelListingState(
            external_id=ref.external_id,
            status=data.get("status"),
            price=data.get("price"),
            available_quantity=data.get("available_quantity"),
            title=data.get("title"),
            permalink=data.get("permalink"),
            raw=data,
        )


def register() -> None:
    """Registra el adapter real, sobreescribiendo el stub `meli`. Idempotente."""
    from . import register_commerce_channel
    register_commerce_channel("meli", MeliCommerceAdapter())

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
import os
import re
from typing import Any, Optional

import httpx

from integrations import meli_client

from .base import (
    CatalogItem,
    ChannelCategory,
    ChannelListingState,
    IngestedOrder,
    IngestedOrderLine,
    ListingRef,
    ListingValidation,
    OrderNotification,
    PriceSyncResult,
    PublishResult,
    StockSyncResult,
)

logger = logging.getLogger("api.commerce.meli")

_CAPABILITIES = frozenset({
    "update", "pause", "resume", "close",
    "sync_stock", "sync_price", "reconcile",
    "order_ingest",
})

_ORDER_ID_RE = re.compile(r"/orders/([^/?#]+)")


def _allowed_meli_ips() -> frozenset:
    """Allowlist de IPs MeLi para verify_origin (MeLi NO firma los webhooks).
    Fuente: env MELI_WEBHOOK_ALLOWED_IPS (CSV). Si no está configurado, verify_origin
    DEFIERE (el webhook mantiene su verificación primaria hop-aware)."""
    raw = os.getenv("MELI_WEBHOOK_ALLOWED_IPS", "").strip()
    return frozenset(ip.strip() for ip in raw.split(",") if ip.strip())


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

    # ── D. Ingesta de pedidos (canal → Supabase; el CALLER persiste) ──
    def verify_origin(self, *, headers: dict, raw_body: bytes, tenant_id: str) -> bool:
        """MeLi NO firma los webhooks — única defensa = IP allowlist. Extrae la IP del
        leftmost X-Forwarded-For y la compara con el allowlist (env). Sin allowlist
        configurado → DEFIERE (True): el webhook mantiene la verificación primaria
        hop-aware (resolve_client_ip). La verificación completa migra aquí en P1.5."""
        allow = _allowed_meli_ips()
        if not allow:
            return True
        h = headers or {}
        xff = h.get("x-forwarded-for") or h.get("X-Forwarded-For") or ""
        ip = xff.split(",")[0].strip() if xff else ""
        return ip in allow

    def parse_order_notification(self, payload: dict) -> OrderNotification:
        """IPN (webhook) → OrderNotification. `resource` es la ruta a fetchear."""
        p = payload or {}
        resource = p.get("resource")
        m = _ORDER_ID_RE.search(resource or "")
        return OrderNotification(
            provider="meli",
            topic=p.get("topic", ""),
            resource=resource,
            external_order_id=m.group(1) if m else None,
            user_id=str(p["user_id"]) if p.get("user_id") is not None else None,
            raw=p,
        )

    async def fetch_order(self, *, tenant_id: str, external_order_id: str, supabase: Any = None) -> IngestedOrder:
        """GET /orders/{id} → IngestedOrder normalizado (PURE — sin DB, sin mapear a
        status interno, sin resolver variation_id: eso es del caller). `status` es el
        crudo de MeLi (el caller aplica MELI_ORDER_STATUS_MAP)."""
        tok = await self._token(tenant_id, supabase)
        if not tok:
            raise RuntimeError("NO_TOKEN: integración MeLi no conectada")
        url = f"{meli_client.MELI_API_URL}/orders/{external_order_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {tok}"})
            resp.raise_for_status()
            data = resp.json()
        buyer = data.get("buyer") or {}
        buyer_name = (
            f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
            or buyer.get("nickname", "")
        )
        lines = []
        for it in (data.get("order_items") or []):
            item = it.get("item") or {}
            iid = item.get("id")
            if not iid:
                continue
            lines.append(IngestedOrderLine(
                external_item_id=str(iid),
                quantity=int(it.get("quantity", 0) or 0),
                unit_price=float(it.get("unit_price", 0) or 0),
                variation_ref=str(item["variation_id"]) if item.get("variation_id") is not None else None,
                sku=item.get("seller_sku") or item.get("seller_custom_field"),
            ))
        return IngestedOrder(
            provider="meli",
            external_order_id=str(data.get("id", external_order_id)),
            status=data.get("status", ""),
            total_amount=float(data.get("total_amount", 0) or 0),
            currency=data.get("currency_id", "COP"),
            lines=lines,
            buyer={
                "external_user_id": str(buyer["id"]) if buyer.get("id") is not None else None,
                "name": buyer_name,
                "nickname": buyer.get("nickname"),
                "phone": (buyer.get("billing_info") or {}).get("phone") or buyer.get("phone"),
            },
            created_at_iso=data.get("date_created"),
            shipping=data.get("shipping"),
            raw=data,
        )

    async def list_orders(self, *, tenant_id: str, since_iso: str, supabase: Any = None) -> list:
        """Backfill (/orders/search o /myfeeds) — VERIFY-OFFICIAL-DOC (schema no
        confirmado en el dossier). No implementado hasta cerrar la doc; devuelve []."""
        logger.info("[COMMERCE][meli] list_orders backfill pendiente (VERIFY-DOC /myfeeds)")
        return []

    # ── NOT SUPPORTED hoy (honesto; NO declarado en capabilities) ──
    # MeLi es import-only hasta P4 (POST /items) + categorías/atributos (P3).
    async def publish_listing(self, *, tenant_id: str, item: CatalogItem, supabase: Any = None) -> PublishResult:
        return PublishResult(ok=False, error_code="NOT_SUPPORTED",
                             error_message="MeLi import-only: publish (POST /items) llega en P4.")

    async def sync_images(self, *, tenant_id: str, ref: ListingRef, image_urls: list, supabase: Any = None) -> PublishResult:
        return PublishResult(ok=False, error_code="NOT_SUPPORTED")

    async def fetch_categories(self, *, tenant_id: str, root: Optional[str] = None, supabase: Any = None) -> list:
        return []

    async def fetch_category_attributes(self, *, tenant_id: str, channel_category_id: str, supabase: Any = None) -> list:
        return []

    async def suggest_category(self, *, tenant_id: str, item: CatalogItem, supabase: Any = None) -> Optional[ChannelCategory]:
        return None

    def validate_for_publish(self, *, item: CatalogItem, required: list) -> ListingValidation:
        return ListingValidation(ok=False, errors=["NOT_SUPPORTED"])


def register() -> None:
    """Registra el adapter real, sobreescribiendo el stub `meli`. Idempotente."""
    from . import register_commerce_channel
    register_commerce_channel("meli", MeliCommerceAdapter())

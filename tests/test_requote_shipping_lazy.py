"""Tests del helper `requote_shipping_for_cart` (rev. 104, ADR-0011 §6.5).

Recotización lazy de envío post-modificación del cart. Pensado para
invocación silenciosa cuando `cart.requires_requote=true` (típicamente
tras `cart_tool.add_item` con orden previa invalidada).

Caso runtime motivador: cliente recibe link por 1×Coco con envío $7.310.
Agrega 1×Sérum → cart cambia (peso/dims), orden previa cancelada. Sin
recotización lazy, el resumen+link nuevos reusaban shipping=$7.310 stale
(extraído del history) en lugar de cotizar contra Envia con peso real.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.shipping_quote_tool import requote_shipping_for_cart  # noqa: E402


def _build_supabase_with_cart(
    *,
    items: list[dict] | None = None,
    shipping_meta: dict | None = None,
    customer_phone: str | None = "+573125835649",
):
    """Mock supabase para cart con shipping_meta + queries auxiliares."""
    items = items or []
    shipping_meta = shipping_meta or {"city": "Bogotá D.C."}
    conversation_row = {"id": "conv-1", "customer_phone": customer_phone}

    def _table(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.single.return_value = chain
        if name == "conversations":
            chain.execute.return_value = MagicMock(data=conversation_row)
        elif name == "tenants":
            chain.execute.return_value = MagicMock(data={
                "shipping_origin": {
                    "address_line": "Cra 1 # 1-1",
                    "city": "Bogotá D.C.",
                    "state": "Bogotá D.C.",
                    "country": "CO",
                    "dane_code": "11001",
                    "postal_code": "110111",
                    "phone": "+5713122222",
                    "name": "Tenant Origin",
                },
            })
        elif name == "contacts":
            chain.execute.return_value = MagicMock(data=[{
                "phone": customer_phone,
                "shipping_phone": customer_phone,
            }])
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain

    sb = MagicMock()
    sb.table.side_effect = _table
    sb._stub_items = items
    sb._stub_shipping_meta = shipping_meta
    return sb


def _stub_get_cart(items, shipping_meta):
    """Stub para get_cart_with_items que devuelve cart enriquecido."""
    def _impl(supabase, *, conversation_id, tenant_id):
        return {
            "id": "cart-1",
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "shipping_meta": shipping_meta,
            "subtotal_cents": sum(int(it.get("quantity", 1)) * int(it.get("unit_price_cents", 0))
                                  for it in items),
            "shipping_cents": int(shipping_meta.get("shipping_cents") or 0),
            "total_cents": 0,
            "requires_requote": True,
            "items": items,
            "version": 1,
        }
    return _impl


class RequoteShippingLazyTests(unittest.IsolatedAsyncioTestCase):

    async def test_returns_none_when_cart_empty(self):
        sb = _build_supabase_with_cart(items=[])
        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=_stub_get_cart([], {"city": "Bogotá D.C."})):
            result = await requote_shipping_for_cart(
                sb, tenant_id="tenant-1", conversation_id="conv-1",
            )
        self.assertIsNone(result)

    async def test_returns_none_when_no_city(self):
        items = [{
            "variation_id": "v-1", "product_id": "p-1",
            "quantity": 1, "unit_price_cents": 1800000,
            "variation": {"weight_kg": 0.065, "length_cm": 8, "width_cm": 5, "height_cm": 3},
            "product": {"title": "Coco"},
        }]
        shipping_meta = {"city": ""}  # no city
        sb = _build_supabase_with_cart(items=items, shipping_meta=shipping_meta)
        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=_stub_get_cart(items, shipping_meta)):
            result = await requote_shipping_for_cart(
                sb, tenant_id="tenant-1", conversation_id="conv-1",
            )
        self.assertIsNone(result)

    @patch("tools.shipping_quote_tool._request_shipping_quote", new_callable=AsyncMock)
    async def test_picks_cheapest_when_prev_service_was_economica(self, mock_request):
        mock_request.return_value = (200, {
            "highlights": {
                "cheapest": {
                    "carrier": "Coordinadora",
                    "service": "Ground",
                    "total_price": "9500",
                    "rate_id": "rate-cheap",
                },
                "fastest": {
                    "carrier": "Mensajeros Urbanos",
                    "service": "Ground",
                    "total_price": "14000",
                    "rate_id": "rate-fast",
                },
            },
        })
        items = [
            {
                "variation_id": "v-coco-60g", "product_id": "p-coco",
                "quantity": 1, "unit_price_cents": 1800000,
                "variation": {"weight_kg": 0.065, "length_cm": 8, "width_cm": 5, "height_cm": 3},
                "product": {"title": "Jabón Artesanal de Coco"},
            },
            {
                "variation_id": "v-serum-30ml", "product_id": "p-serum",
                "quantity": 1, "unit_price_cents": 8500000,
                "variation": {"weight_kg": 0.04, "length_cm": 3, "width_cm": 3, "height_cm": 10},
                "product": {"title": "Sérum de Vitamina C"},
            },
        ]
        shipping_meta = {
            "city": "Bogotá D.C.",
            "service_level": "Económica",
            "carrier": "Coordinadora Ground",
        }
        sb = _build_supabase_with_cart(items=items, shipping_meta=shipping_meta)

        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=_stub_get_cart(items, shipping_meta)):
            result = await requote_shipping_for_cart(
                sb, tenant_id="tenant-1", conversation_id="conv-1",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["service_level"], "Económica")
        self.assertEqual(result["shipping_cents"], 950000)  # $9.500
        self.assertEqual(result["carrier_name"], "Coordinadora")
        self.assertEqual(result["city"], "Bogotá D.C.")
        mock_request.assert_awaited_once()

    @patch("tools.shipping_quote_tool._request_shipping_quote", new_callable=AsyncMock)
    async def test_picks_fastest_when_prev_service_was_rapida(self, mock_request):
        mock_request.return_value = (200, {
            "highlights": {
                "cheapest": {"carrier": "Coordinadora", "total_price": "9500"},
                "fastest": {"carrier": "Mensajeros", "total_price": "14000"},
            },
        })
        items = [{
            "variation_id": "v-1", "product_id": "p-1",
            "quantity": 1, "unit_price_cents": 1800000,
            "variation": {"weight_kg": 0.1, "length_cm": 10, "width_cm": 6, "height_cm": 4},
            "product": {"title": "X"},
        }]
        shipping_meta = {"city": "Bogotá D.C.", "service_level": "Rápida"}
        sb = _build_supabase_with_cart(items=items, shipping_meta=shipping_meta)

        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=_stub_get_cart(items, shipping_meta)):
            result = await requote_shipping_for_cart(
                sb, tenant_id="tenant-1", conversation_id="conv-1",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["service_level"], "Rápida")
        self.assertEqual(result["shipping_cents"], 1400000)  # $14.000

    @patch("tools.shipping_quote_tool._request_shipping_quote", new_callable=AsyncMock)
    async def test_returns_none_when_envia_fails(self, mock_request):
        mock_request.return_value = (504, {"detail": "transient_timeout"})
        items = [{
            "variation_id": "v-1", "product_id": "p-1",
            "quantity": 1, "unit_price_cents": 1800000,
            "variation": {"weight_kg": 0.1, "length_cm": 10, "width_cm": 6, "height_cm": 4},
            "product": {"title": "X"},
        }]
        shipping_meta = {"city": "Bogotá D.C.", "service_level": "Económica"}
        sb = _build_supabase_with_cart(items=items, shipping_meta=shipping_meta)

        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=_stub_get_cart(items, shipping_meta)):
            result = await requote_shipping_for_cart(
                sb, tenant_id="tenant-1", conversation_id="conv-1",
            )
        self.assertIsNone(result)

    @patch("tools.shipping_quote_tool._request_shipping_quote", new_callable=AsyncMock)
    async def test_returns_none_when_no_cheapest_in_response(self, mock_request):
        mock_request.return_value = (200, {"highlights": {}})
        items = [{
            "variation_id": "v-1", "product_id": "p-1",
            "quantity": 1, "unit_price_cents": 1800000,
            "variation": {"weight_kg": 0.1, "length_cm": 10, "width_cm": 6, "height_cm": 4},
            "product": {"title": "X"},
        }]
        shipping_meta = {"city": "Bogotá D.C.", "service_level": "Económica"}
        sb = _build_supabase_with_cart(items=items, shipping_meta=shipping_meta)

        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=_stub_get_cart(items, shipping_meta)):
            result = await requote_shipping_for_cart(
                sb, tenant_id="tenant-1", conversation_id="conv-1",
            )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

"""P1 (ADR-0038) — MeliCommerceAdapter: envuelve meli_client tras el contrato.

Verifica delegación fiel a meli_client, resolución de token, propagación de
rate-limit (Retry-After), degradación grácil (capabilities), y que register()
sobreescribe el stub. Cero I/O real — meli_client mockeado.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SECRET_KEY", "k")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from lib import commerce as C  # noqa: E402
from lib.commerce.base import CatalogItem, CommerceChannelAdapter, ListingRef  # noqa: E402
from lib.commerce.meli import MeliCommerceAdapter  # noqa: E402


class _FakeResp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


class _FakeClient:
    def __init__(self, data): self._d = data
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, headers=None): return _FakeResp(self._d)

_SB = object()  # supabase inyectado (no se usa porque get_valid_token está mockeado)


def _http_error(status: int, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    req = httpx.Request("PUT", "https://api.mercadolibre.com/items/X")
    resp = httpx.Response(status, headers=headers, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


class CapabilitiesTests(unittest.TestCase):
    def test_declares_outbound_and_ingest_not_publish(self):
        caps = MeliCommerceAdapter().capabilities()
        for c in ("sync_stock", "sync_price", "update", "pause", "resume", "close", "reconcile", "order_ingest"):
            self.assertIn(c, caps)
        # Degradación grácil: MeLi HOY sin publish / categories / attributes (import-only).
        self.assertNotIn("publish", caps)
        self.assertNotIn("categories", caps)

    def test_channel_name(self):
        self.assertEqual(MeliCommerceAdapter().channel_name(), "meli")


class SyncStockTests(unittest.TestCase):
    def setUp(self):
        self.a = MeliCommerceAdapter()
        self.ref = ListingRef(provider="meli", external_id="MCO123")

    def test_ok_delegates_to_update_item_quantity(self):
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
             patch("lib.commerce.meli.meli_client.update_item_quantity", AsyncMock(return_value={})) as up:
            r = asyncio.run(self.a.sync_stock(tenant_id="t1", ref=self.ref, quantity=5, supabase=_SB))
            self.assertTrue(r.ok)
            self.assertEqual(r.synced_quantity, 5)
            up.assert_awaited_once_with("MCO123", 5, "TOK")

    def test_no_token(self):
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value=None)):
            r = asyncio.run(self.a.sync_stock(tenant_id="t1", ref=self.ref, quantity=5, supabase=_SB))
            self.assertFalse(r.ok)
            self.assertEqual(r.error_code, "NO_TOKEN")

    def test_rate_limit_propagated(self):
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
             patch("lib.commerce.meli.meli_client.update_item_quantity",
                   AsyncMock(side_effect=_http_error(429, retry_after=30))):
            r = asyncio.run(self.a.sync_stock(tenant_id="t1", ref=self.ref, quantity=5, supabase=_SB))
            self.assertFalse(r.ok)
            self.assertEqual(r.error_code, "429")
            self.assertEqual(r.retry_after_seconds, 30)

    def test_generic_error_caught(self):
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
             patch("lib.commerce.meli.meli_client.update_item_quantity", AsyncMock(side_effect=RuntimeError("boom"))):
            r = asyncio.run(self.a.sync_stock(tenant_id="t1", ref=self.ref, quantity=5, supabase=_SB))
            self.assertFalse(r.ok)
            self.assertEqual(r.error_code, "ERROR")


class SyncPriceAndStatusTests(unittest.TestCase):
    def setUp(self):
        self.a = MeliCommerceAdapter()
        self.ref = ListingRef(provider="meli", external_id="MCO9")

    def test_sync_price(self):
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
             patch("lib.commerce.meli.meli_client.update_item_price", AsyncMock(return_value={})) as up:
            r = asyncio.run(self.a.sync_price(tenant_id="t1", ref=self.ref, price=1999.7, supabase=_SB))
            self.assertTrue(r.ok)
            up.assert_awaited_once_with("MCO9", 1999.7, "TOK")

    def test_pause_resume_close_map_to_status(self):
        cases = [("pause_listing", "paused"), ("resume_listing", "active"), ("close_listing", "closed")]
        for method, status in cases:
            with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
                 patch("lib.commerce.meli.meli_client.update_item_status", AsyncMock(return_value={})) as up:
                r = asyncio.run(getattr(self.a, method)(tenant_id="t1", ref=self.ref, supabase=_SB))
                self.assertTrue(r.ok, method)
                up.assert_awaited_once_with("MCO9", status, "TOK")


class UpdateListingTests(unittest.TestCase):
    def test_passes_meli_variations_from_raw(self):
        a = MeliCommerceAdapter()
        ref = ListingRef(provider="meli", external_id="MCO1")
        item = CatalogItem(tenant_id="t1", product_id="p1", sku="S", title="X",
                           available_quantity=10, price=5000.0, compare_at_price=6000.0,
                           raw={"meli_variations": [{"id": 1, "available_quantity": 4}]})
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
             patch("lib.commerce.meli.meli_client.update_item_listing", AsyncMock(return_value={})) as up:
            r = asyncio.run(a.update_listing(tenant_id="t1", ref=ref, item=item, supabase=_SB))
            self.assertTrue(r.ok)
            args, kwargs = up.await_args
            self.assertEqual(args[0], "MCO1")
            self.assertEqual(kwargs.get("meli_variations"), [{"id": 1, "available_quantity": 4}])


class FetchListingTests(unittest.TestCase):
    def test_maps_item_fields(self):
        a = MeliCommerceAdapter()
        ref = ListingRef(provider="meli", external_id="MCO7")
        data = {"status": "active", "price": 1000, "available_quantity": 3,
                "title": "Prod", "permalink": "http://x"}
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
             patch("lib.commerce.meli.meli_client.get_item", AsyncMock(return_value=data)):
            s = asyncio.run(a.fetch_listing(tenant_id="t1", ref=ref, supabase=_SB))
            self.assertEqual(s.status, "active")
            self.assertEqual(s.available_quantity, 3)
            self.assertEqual(s.permalink, "http://x")


class ProtocolCompletenessTests(unittest.TestCase):
    def test_adapter_satisfies_full_protocol(self):
        # Todos los métodos del contrato existen (incl. not-supported honestos) →
        # isinstance pasa → sin warning de Protocol-incompleto al registrar.
        self.assertIsInstance(MeliCommerceAdapter(), CommerceChannelAdapter)

    def test_order_ingest_declared(self):
        self.assertIn("order_ingest", MeliCommerceAdapter().capabilities())


class InboundTests(unittest.TestCase):
    def setUp(self):
        self.a = MeliCommerceAdapter()

    def test_parse_order_notification(self):
        n = self.a.parse_order_notification(
            {"resource": "/orders/200000123", "user_id": 12345, "topic": "orders_v2"})
        self.assertEqual(n.provider, "meli")
        self.assertEqual(n.topic, "orders_v2")
        self.assertEqual(n.external_order_id, "200000123")
        self.assertEqual(n.user_id, "12345")

    def test_parse_order_notification_no_resource(self):
        n = self.a.parse_order_notification({"topic": "orders_v2"})
        self.assertIsNone(n.external_order_id)

    def test_fetch_order_normalizes(self):
        order = {
            "id": 200000123, "status": "paid", "total_amount": 50000, "currency_id": "COP",
            "date_created": "2026-07-19T10:00:00.000-05:00",
            "buyer": {"id": 999, "first_name": "Juan", "last_name": "Pérez", "nickname": "juanp",
                      "billing_info": {"phone": "3001234567"}},
            "order_items": [{"item": {"id": "MCO111", "variation_id": 55, "seller_sku": "SKU1"},
                             "quantity": 2, "unit_price": 25000}],
            "shipping": {"id": 888},
        }
        with patch("lib.commerce.meli.meli_client.get_valid_token", AsyncMock(return_value="TOK")), \
             patch("lib.commerce.meli.httpx.AsyncClient", return_value=_FakeClient(order)):
            o = asyncio.run(self.a.fetch_order(tenant_id="t1", external_order_id="200000123", supabase=object()))
        self.assertEqual(o.external_order_id, "200000123")
        self.assertEqual(o.status, "paid")   # crudo de MeLi (el caller mapea a interno)
        self.assertEqual(o.total_amount, 50000.0)
        self.assertEqual(len(o.lines), 1)
        self.assertEqual(o.lines[0].external_item_id, "MCO111")
        self.assertEqual(o.lines[0].quantity, 2)
        self.assertEqual(o.lines[0].variation_ref, "55")
        self.assertEqual(o.lines[0].sku, "SKU1")
        self.assertEqual(o.buyer["name"], "Juan Pérez")
        self.assertEqual(o.buyer["phone"], "3001234567")

    def test_verify_origin_defers_without_allowlist(self):
        with patch.dict(os.environ, {"MELI_WEBHOOK_ALLOWED_IPS": ""}, clear=False):
            self.assertTrue(self.a.verify_origin(headers={}, raw_body=b"", tenant_id="t"))

    def test_verify_origin_checks_ip_when_configured(self):
        with patch.dict(os.environ, {"MELI_WEBHOOK_ALLOWED_IPS": "1.2.3.4, 5.6.7.8"}):
            self.assertTrue(self.a.verify_origin(
                headers={"x-forwarded-for": "1.2.3.4, 9.9.9.9"}, raw_body=b"", tenant_id="t"))
            self.assertFalse(self.a.verify_origin(
                headers={"x-forwarded-for": "9.9.9.9"}, raw_body=b"", tenant_id="t"))


class NotSupportedTests(unittest.TestCase):
    def test_publish_and_validate_not_supported(self):
        a = MeliCommerceAdapter()
        item = CatalogItem(tenant_id="t", product_id="p", sku="s", title="x",
                           available_quantity=1, price=1.0)
        r = asyncio.run(a.publish_listing(tenant_id="t", item=item))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_code, "NOT_SUPPORTED")
        self.assertNotIn("publish", a.capabilities())  # degradación grácil
        v = a.validate_for_publish(item=item, required=[])
        self.assertFalse(v.ok)


class RegisterTests(unittest.TestCase):
    def test_register_overrides_stub(self):
        from lib.commerce.meli import register
        original = C.get_commerce_adapter("meli")
        try:
            register()
            a = C.get_commerce_adapter("meli")
            self.assertIsInstance(a, MeliCommerceAdapter)
            self.assertIn("sync_stock", a.capabilities())
        finally:
            C.register_commerce_channel("meli", original)  # restaurar stub


if __name__ == "__main__":
    unittest.main()

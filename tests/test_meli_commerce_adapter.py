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
from lib.commerce.base import CatalogItem, ListingRef  # noqa: E402
from lib.commerce.meli import MeliCommerceAdapter  # noqa: E402

_SB = object()  # supabase inyectado (no se usa porque get_valid_token está mockeado)


def _http_error(status: int, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    req = httpx.Request("PUT", "https://api.mercadolibre.com/items/X")
    resp = httpx.Response(status, headers=headers, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


class CapabilitiesTests(unittest.TestCase):
    def test_declares_outbound_not_publish(self):
        caps = MeliCommerceAdapter().capabilities()
        for c in ("sync_stock", "sync_price", "update", "pause", "resume", "close", "reconcile"):
            self.assertIn(c, caps)
        # Degradación grácil: MeLi HOY sin publish / categories / order_ingest.
        self.assertNotIn("publish", caps)
        self.assertNotIn("order_ingest", caps)

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

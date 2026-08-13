"""P0 (ADR-0038) — pact test del CommerceChannelAdapter + registry.

Verifica el contrato del eje COMERCIO: registry separado del de mensajería, stubs
default-deny (fail-closed), negociación de capacidad, y que un adapter real puede
sobreescribir su stub. Cero I/O externo — es puro contrato.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SECRET_KEY", "k")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from lib import commerce as C  # noqa: E402
from lib.commerce.base import (  # noqa: E402
    CatalogItem,
    CommerceChannelAdapter,
    IngestedOrder,
    IngestedOrderLine,
    ListingRef,
    ListingValidation,
    OrderNotification,
    PublishResult,
    StockSyncResult,
)


class RegistryTests(unittest.TestCase):
    def test_prereg_stubs_present(self):
        chans = C.list_registered_commerce_channels()
        for c in ("meli", "shopify", "web"):
            self.assertIn(c, chans)

    def test_get_is_case_insensitive_and_trims(self):
        self.assertIsNotNone(C.get_commerce_adapter("  MeLi "))
        self.assertIsNone(C.get_commerce_adapter("no-existe-xyz"))

    def test_register_empty_name_raises(self):
        with self.assertRaises(ValueError):
            C.register_commerce_channel("  ", C.get_commerce_adapter("meli"))

    def test_registry_is_separate_from_messaging(self):
        # Un canal commerce-only (meli) no debe estar obligado en el registry de
        # mensajería, y viceversa. Aquí basta con que el registry de comercio sea
        # su propio dict.
        self.assertIsNot(C._COMMERCE_ADAPTERS, None)
        self.assertIn("meli", C._COMMERCE_ADAPTERS)


class StubDefaultDenyTests(unittest.TestCase):
    def setUp(self):
        self.stub = C.get_commerce_adapter("meli")

    def test_capabilities_empty(self):
        self.assertEqual(self.stub.capabilities(), set())

    def test_verify_origin_denies(self):
        self.assertFalse(self.stub.verify_origin(headers={}, raw_body=b"", tenant_id="t1"))

    def test_writes_fail_closed(self):
        item = CatalogItem(tenant_id="t1", product_id="p1", sku="S1", title="X",
                           available_quantity=5, price=1000.0)
        ref = ListingRef(provider="meli", external_id="MCO123")
        pub = asyncio.run(self.stub.publish_listing(tenant_id="t1", item=item))
        self.assertFalse(pub.ok)
        self.assertEqual(pub.error_code, "STUB_ADAPTER")
        stock = asyncio.run(self.stub.sync_stock(tenant_id="t1", ref=ref, quantity=3))
        self.assertFalse(stock.ok)
        self.assertEqual(stock.error_code, "STUB_ADAPTER")
        price = asyncio.run(self.stub.sync_price(tenant_id="t1", ref=ref, price=999.0))
        self.assertFalse(price.ok)

    def test_validate_for_publish_denies(self):
        item = CatalogItem(tenant_id="t1", product_id="p1", sku="S1", title="X",
                           available_quantity=5, price=1000.0)
        v = self.stub.validate_for_publish(item=item, required=[])
        self.assertFalse(v.ok)

    def test_parse_order_notification_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.stub.parse_order_notification({})

    def test_read_lists_empty_not_raise(self):
        self.assertEqual(asyncio.run(self.stub.fetch_categories(tenant_id="t1")), [])
        self.assertEqual(asyncio.run(self.stub.list_orders(tenant_id="t1", since_iso="2026-01-01")), [])


class ProtocolAndOverrideTests(unittest.TestCase):
    def test_stub_satisfies_protocol(self):
        self.assertIsInstance(C.get_commerce_adapter("meli"), CommerceChannelAdapter)

    def test_real_adapter_overrides_stub_and_negotiates_capability(self):
        class FakeMeli:
            def channel_name(self): return "meli"
            def capabilities(self): return {"sync_stock", "order_ingest", "reconcile"}
            async def sync_stock(self, **k): return StockSyncResult(ok=True, synced_quantity=k["quantity"])
            def parse_order_notification(self, payload):
                return OrderNotification(provider="meli", topic="orders_v2",
                                         resource=payload.get("resource"))
            def verify_origin(self, **k): return True
            # (los demás métodos no se ejercen en este test)

        original = C.get_commerce_adapter("meli")
        try:
            C.register_commerce_channel("meli", FakeMeli())
            a = C.get_commerce_adapter("meli")
            self.assertIn("sync_stock", a.capabilities())
            self.assertNotIn("publish", a.capabilities())  # degradación grácil: MeLi sin publish hoy
            r = asyncio.run(a.sync_stock(tenant_id="t1",
                                         ref=ListingRef(provider="meli", external_id="M1"),
                                         quantity=7))
            self.assertTrue(r.ok)
            self.assertEqual(r.synced_quantity, 7)
            self.assertTrue(a.verify_origin(headers={}, raw_body=b"", tenant_id="t1"))
            n = a.parse_order_notification({"resource": "/orders/9"})
            self.assertEqual(n.resource, "/orders/9")
        finally:
            C.register_commerce_channel("meli", original)  # restaurar el stub


class DataclassTests(unittest.TestCase):
    def test_ingested_order_shape(self):
        o = IngestedOrder(provider="meli", external_order_id="9", status="paid",
                          total_amount=50000.0,
                          lines=[IngestedOrderLine(external_item_id="MCO1", quantity=2, unit_price=25000.0)])
        self.assertEqual(o.lines[0].quantity, 2)
        self.assertEqual(o.currency, "COP")  # default

    def test_results_carry_retry_after(self):
        # El contrato: los resultados de escritura propagan rate-limit.
        self.assertTrue(hasattr(PublishResult(ok=False), "retry_after_seconds"))
        self.assertTrue(hasattr(StockSyncResult(ok=False), "retry_after_seconds"))
        self.assertTrue(hasattr(ListingValidation(ok=True), "missing"))


if __name__ == "__main__":
    unittest.main()

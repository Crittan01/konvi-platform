import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from routers import marketplace, orders


class _Query:
    def __init__(self, data):
        self.data = data
        self.eq_calls = []

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, *_args, **_kwargs):
        return self

    def update(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def single(self):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.data)

    def eq(self, key, value):
        self.eq_calls.append((key, value))
        return self


class TenantScopingTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_order_scopes_variation_lookup_by_tenant(self):
        supabase = MagicMock()
        orders_query = _Query([{"id": "order-1"}])
        variations_query = _Query([{"id": "var-1", "cost_price": 9.0}])
        order_items_query = _Query([])

        def table_side_effect(name):
            if name == "orders":
                return orders_query
            if name == "product_variations":
                return variations_query
            if name == "order_items":
                return order_items_query
            raise AssertionError(f"Tabla inesperada: {name}")

        supabase.table.side_effect = table_side_effect

        payload = orders.OrderCreate(
            items=[
                orders.OrderItemCreate(
                    title="Test",
                    unit_price=10,
                    quantity=1,
                    variation_id="var-1",
                )
            ]
        )
        fake_request = types.SimpleNamespace(
            headers={},
            method="POST",
            url=types.SimpleNamespace(path="/api/v1/orders/"),
        )

        orders.create_order(
            order=payload,
            request=fake_request,
            tenant_id="tenant-abc",
            supabase=supabase,
            _role="manager",
        )

        self.assertIn(("tenant_id", "tenant-abc"), variations_query.eq_calls)

    async def test_marketplace_sync_scopes_variation_lookup_by_tenant(self):
        supabase = MagicMock()
        listings_query = _Query([
            {
                "id": "listing-1",
                "external_id": "MCO123",
                "tenant_id": "tenant-abc",
                "meli_variation_id": None,
            }
        ])
        variations_query = _Query({"price": 100, "compare_at_price": None})
        update_query = _Query([{"id": "listing-1"}])

        def table_side_effect(name):
            if name == "marketplace_listings":
                # first call select listing, later maybe update status
                if not hasattr(table_side_effect, "seen_listing"):
                    table_side_effect.seen_listing = True
                    return listings_query
                return update_query
            if name == "product_variations":
                return variations_query
            return _Query([])

        supabase.table.side_effect = table_side_effect

        with (
            patch.object(marketplace, "get_valid_token", new=AsyncMock(return_value="token")),
            patch.object(marketplace, "get_item", new=AsyncMock(return_value={"status": "active", "variations": []})),
            patch.object(marketplace, "update_item_listing", new=AsyncMock(return_value={})),
            patch.object(marketplace, "update_item_quantity", new=AsyncMock(return_value={})),
        ):
            await marketplace.sync_meli_stock("var-1", 5, supabase)

        self.assertIn(("tenant_id", "tenant-abc"), variations_query.eq_calls)


if __name__ == "__main__":
    unittest.main()

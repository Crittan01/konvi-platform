"""F4 — sync de stock a MeLi tras consumir reservas (flujo bot WhatsApp).

BUG: _decrement_stock_on_confirm, cuando la orden tenía reservas activas (ventas por
WhatsApp), las consumía vía RPC y hacía return temprano → se SALTABA el sync_meli_stock
del path de decremento directo → MeLi quedaba con stock viejo (oversell cross-canal).

Fix: _fire_meli_sync_for_order empuja el stock actualizado de cada variante de la orden
a MeLi (background, guardado: no-op sin listing MeLi). Este test verifica que se dispara
con (variation_id, new_stock) por cada variante distinta.
"""
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("INTERNAL_SERVICE_SECRET", "internal-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers import orders  # noqa: E402


class _Chain:
    def __init__(self, table, sb):
        self._table = table
        self._sb = sb
        self._id = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        if col == "id":
            self._id = val
        return self

    def single(self):
        return self

    def execute(self):
        if self._table == "order_items":
            return types.SimpleNamespace(data=self._sb.items)
        if self._table == "product_variations":
            sq = self._sb.stock.get(self._id)
            return types.SimpleNamespace(
                data={"stock_quantity": sq} if sq is not None else None
            )
        return types.SimpleNamespace(data=[])


class _FakeSb:
    def __init__(self, items, stock):
        self.items = items
        self.stock = stock

    def table(self, name):
        return _Chain(name, self)


class F4MeliSyncTests(unittest.TestCase):
    def test_fires_meli_sync_per_variation_with_new_stock(self):
        sb = _FakeSb(
            items=[{"variation_id": "v1"}, {"variation_id": "v2"}],
            stock={"v1": 5, "v2": 3},
        )
        with patch("routers.orders.sync_meli_stock", new=AsyncMock()) as mock_sync:
            orders._fire_meli_sync_for_order(sb, "order-1", "tenant-1")
        self.assertEqual(mock_sync.call_count, 2)
        mock_sync.assert_any_call("v1", 5, sb)
        mock_sync.assert_any_call("v2", 3, sb)

    def test_dedups_repeated_variation(self):
        sb = _FakeSb(
            items=[{"variation_id": "v1"}, {"variation_id": "v1"}],
            stock={"v1": 4},
        )
        with patch("routers.orders.sync_meli_stock", new=AsyncMock()) as mock_sync:
            orders._fire_meli_sync_for_order(sb, "order-1", "tenant-1")
        self.assertEqual(mock_sync.call_count, 1)
        mock_sync.assert_called_once_with("v1", 4, sb)

    def test_skips_variation_without_stock_row(self):
        sb = _FakeSb(items=[{"variation_id": "ghost"}], stock={})
        with patch("routers.orders.sync_meli_stock", new=AsyncMock()) as mock_sync:
            orders._fire_meli_sync_for_order(sb, "order-1", "tenant-1")
        mock_sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()

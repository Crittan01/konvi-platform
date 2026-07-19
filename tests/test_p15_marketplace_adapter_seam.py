"""P1.5 (ADR-0038) — seam de delegación del PUT de stock en sync_meli_stock.

Verifica que el money-path (marketplace.sync_meli_stock) delega el PUT al
CommerceChannelAdapter cuando declara capacidades, INYECTANDO el token ya resuelto
(sin 2ª resolución), y que:
  • en ok=True se actualizan los campos pull (invariante preservada);
  • en ok=False NO se tocan los campos pull (guard `if not put_ok: return`) y no lanza;
  • sin capacidad (o sin adapter) cae a la mecánica legacy IDÉNTICA.
Supabase, get_valid_token y get_item se mockean — cero I/O real.
"""
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SECRET_KEY", "k")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers import marketplace  # noqa: E402


class _Chain:
    """Cadena Supabase mínima; captura los .update() a marketplace_listings."""

    def __init__(self, table, sb):
        self._table = table
        self._sb = sb
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        if self._op == "update" and self._table == "marketplace_listings":
            self._sb.updates.append(self._payload)
            return types.SimpleNamespace(data=[{}])
        if self._table == "marketplace_listings":
            return types.SimpleNamespace(data=self._sb.listing)
        if self._table == "product_variations":
            return types.SimpleNamespace(data=self._sb.variation)
        return types.SimpleNamespace(data=[])


class _FakeSb:
    def __init__(self, listing, variation):
        self.listing = listing        # list → .data del SELECT del listing
        self.variation = variation    # dict|None → .data del .single() de la variante
        self.updates = []             # payloads de .update() capturados

    def table(self, name):
        return _Chain(name, self)


_LISTING = [{"id": "L1", "external_id": "MCO9", "tenant_id": "t1", "meli_variation_id": None}]
_MELI_ITEM = {"status": "active", "variations": [], "title": "Prod", "thumbnail": "http://t",
              "condition": "new", "category_id": "MCO1", "attributes": []}


def _adapter(caps, result_ok=True, error_code=None):
    a = MagicMock()
    a.capabilities.return_value = set(caps)
    res = MagicMock(ok=result_ok, error_code=error_code, error_message="x")
    a.sync_stock = AsyncMock(return_value=res)
    a.update_listing = AsyncMock(return_value=res)
    return a


def _synced_at_written(sb):
    return any(isinstance(u, dict) and "synced_at" in u for u in sb.updates)


class SeamItemLevelTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, adapter, variation=None):
        sb = _FakeSb(listing=_LISTING, variation=variation)
        with patch("routers.marketplace.get_commerce_adapter", return_value=adapter), \
             patch("routers.marketplace.get_valid_token", AsyncMock(return_value="TOKUAT")), \
             patch("routers.marketplace.get_item", AsyncMock(return_value=_MELI_ITEM)), \
             patch("routers.marketplace.update_item_quantity", AsyncMock()) as legacy_q, \
             patch("routers.marketplace.update_item_listing", AsyncMock()) as legacy_l:
            await marketplace.sync_meli_stock("v1", 4, sb)
        return sb, legacy_q, legacy_l

    async def test_delegates_with_injected_token_and_updates_pull(self):
        adapter = _adapter({"update", "sync_stock"}, result_ok=True)
        sb, legacy_q, _ = await self._run(adapter, variation=None)  # price None → sync_stock
        adapter.sync_stock.assert_awaited_once()
        _, kwargs = adapter.sync_stock.await_args
        self.assertEqual(kwargs["access_token"], "TOKUAT")   # token INYECTADO, no re-resuelto
        self.assertEqual(kwargs["quantity"], 4)
        legacy_q.assert_not_awaited()                        # NO llamó al legacy directo
        self.assertTrue(_synced_at_written(sb))              # pull-fields en éxito

    async def test_ok_false_skips_pull_and_does_not_raise(self):
        adapter = _adapter({"update", "sync_stock"}, result_ok=False, error_code="429")
        sb, _, _ = await self._run(adapter, variation=None)
        adapter.sync_stock.assert_awaited_once()
        self.assertFalse(_synced_at_written(sb))             # pull-fields NO tocados en fallo

    async def test_fallback_to_legacy_without_capability(self):
        adapter = _adapter(set(), result_ok=True)            # sin capacidades → legacy
        sb, legacy_q, _ = await self._run(adapter, variation=None)
        adapter.sync_stock.assert_not_awaited()
        legacy_q.assert_awaited_once_with("MCO9", 4, "TOKUAT")
        self.assertTrue(_synced_at_written(sb))              # legacy exitoso → pull

    async def test_partial_capability_falls_to_legacy_no_split_brain(self):
        adapter = _adapter({"update"}, result_ok=True)       # sólo una → gate único cae a legacy
        sb, legacy_q, _ = await self._run(adapter, variation=None)
        adapter.sync_stock.assert_not_awaited()
        legacy_q.assert_awaited_once_with("MCO9", 4, "TOKUAT")


class SeamMoneyPathTests(unittest.IsolatedAsyncioTestCase):
    """Rama de VENTA REAL: price!=None → update_listing con variaciones. Es el path
    representativo en prod (una variación con precio SIEMPRE toma esta rama)."""

    _VAR = {"price": 1000, "compare_at_price": 1500}
    _VARS_PUT = [{"id": 1, "available_quantity": 4}]

    async def _run(self, adapter, legacy_raises=False):
        sb = _FakeSb(listing=_LISTING, variation=self._VAR)
        legacy = AsyncMock(side_effect=Exception("boom") if legacy_raises else None)
        with patch("routers.marketplace.get_commerce_adapter", return_value=adapter), \
             patch("routers.marketplace.get_valid_token", AsyncMock(return_value="TOKUAT")), \
             patch("routers.marketplace.get_item", AsyncMock(return_value=_MELI_ITEM)), \
             patch("routers.marketplace._resolve_variations_for_put", return_value=self._VARS_PUT), \
             patch("routers.marketplace.update_item_listing", legacy), \
             patch("routers.marketplace.update_item_quantity", AsyncMock()):
            await marketplace.sync_meli_stock("v1", 4, sb)
        return sb, legacy

    async def test_delegates_update_listing_with_variations_and_token(self):
        adapter = _adapter({"update", "sync_stock"}, result_ok=True)
        sb, legacy = await self._run(adapter)
        adapter.update_listing.assert_awaited_once()
        _, kwargs = adapter.update_listing.await_args
        self.assertEqual(kwargs["access_token"], "TOKUAT")     # token INYECTADO
        self.assertEqual(kwargs["item"].raw["meli_variations"], self._VARS_PUT)
        self.assertEqual(kwargs["item"].available_quantity, 4)
        self.assertEqual(kwargs["item"].price, 1000.0)
        self.assertEqual(kwargs["item"].compare_at_price, 1500.0)
        legacy.assert_not_awaited()
        self.assertTrue(_synced_at_written(sb))

    async def test_ok_false_skips_pull(self):
        adapter = _adapter({"update", "sync_stock"}, result_ok=False, error_code="400")
        sb, _ = await self._run(adapter)
        adapter.update_listing.assert_awaited_once()
        self.assertFalse(_synced_at_written(sb))               # pull-fields NO tocados en fallo

    async def test_fallback_to_legacy_without_capability(self):
        # MEDIUM (review adversarial): la rama de venta REAL por legacy (variaciones) — antes
        # sin cobertura. Guarda contra swap de args / pérdida de variations_for_put.
        adapter = _adapter(set(), result_ok=True)
        sb, legacy = await self._run(adapter)
        adapter.update_listing.assert_not_awaited()
        legacy.assert_awaited_once_with("MCO9", 4, 1000.0, 1500.0, "TOKUAT", self._VARS_PUT)
        self.assertTrue(_synced_at_written(sb))                # legacy exitoso → pull

    async def test_partial_capability_falls_to_legacy_no_split_brain(self):
        adapter = _adapter({"update"}, result_ok=True)         # sólo una → gate único → legacy
        sb, legacy = await self._run(adapter)
        adapter.update_listing.assert_not_awaited()
        legacy.assert_awaited_once()

    async def test_legacy_raise_propagates_and_skips_pull(self):
        # El PUT legacy que LANZA (raise_for_status) → outer except del caller → NO pull-fields.
        adapter = _adapter(set(), result_ok=True)
        sb, legacy = await self._run(adapter, legacy_raises=True)
        legacy.assert_awaited_once()
        self.assertFalse(_synced_at_written(sb))               # raise → salta pull-fields


if __name__ == "__main__":
    unittest.main()

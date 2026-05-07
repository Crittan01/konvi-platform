"""Tests del cart/events (rev. 104, F1-6)."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]


def _load():
    path = REPO / "services/ai-orchestrator/cart/events.py"
    spec = importlib.util.spec_from_file_location("_cart_events_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cart_events_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class CartEventsEmitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def _mock_sb(self, *, raise_exc=False):
        sb = MagicMock()
        chain = MagicMock()
        if raise_exc:
            chain.insert.side_effect = Exception("DB down")
        else:
            chain.insert.return_value.execute.return_value = MagicMock(
                data=[{"id": "evt-uuid-1"}],
            )
        sb.table.return_value = chain
        return sb

    def test_emit_canonical_event_returns_id(self):
        sb = self._mock_sb()
        row_id = self.mod.emit(
            sb,
            cart_id="c1", tenant_id="t1",
            event_type=self.mod.EVT_ITEM_ADDED,
            payload={"product_id": "p1", "quantity": 2},
        )
        self.assertEqual(row_id, "evt-uuid-1")

    def test_emit_uses_cart_events_table(self):
        sb = self._mock_sb()
        self.mod.emit(
            sb, cart_id="c1", tenant_id="t1",
            event_type=self.mod.EVT_CARRIER_SELECTED,
            payload={"carrier": "Coordinadora", "shipping_cents": 731000},
        )
        sb.table.assert_called_with("cart_events")

    def test_emit_skips_when_cart_id_missing(self):
        sb = self._mock_sb()
        row_id = self.mod.emit(
            sb, cart_id="", tenant_id="t1",
            event_type=self.mod.EVT_ITEM_ADDED,
        )
        self.assertIsNone(row_id)
        sb.table.assert_not_called()

    def test_emit_skips_when_tenant_id_missing(self):
        sb = self._mock_sb()
        row_id = self.mod.emit(
            sb, cart_id="c1", tenant_id="",
            event_type=self.mod.EVT_ITEM_ADDED,
        )
        self.assertIsNone(row_id)

    def test_non_canonical_type_is_logged_but_inserted(self):
        sb = self._mock_sb()
        row_id = self.mod.emit(
            sb, cart_id="c1", tenant_id="t1",
            event_type="custom_event_x",
            payload={"k": "v"},
        )
        self.assertEqual(row_id, "evt-uuid-1")  # se insertó igual

    def test_db_error_returns_none_no_raise(self):
        sb = self._mock_sb(raise_exc=True)
        row_id = self.mod.emit(
            sb, cart_id="c1", tenant_id="t1",
            event_type=self.mod.EVT_ITEM_ADDED,
        )
        self.assertIsNone(row_id)

    def test_canonical_constants_match_set(self):
        # Smoke check — todas las EVT_* están en CANONICAL_EVENTS.
        for attr in dir(self.mod):
            if attr.startswith("EVT_"):
                self.assertIn(getattr(self.mod, attr), self.mod.CANONICAL_EVENTS)

    def test_coupon_events_canonical(self):
        # Sem 6 I.2 — los 3 eventos de cupones están en CANONICAL_EVENTS.
        self.assertIn(self.mod.EVT_COUPON_APPLIED, self.mod.CANONICAL_EVENTS)
        self.assertIn(self.mod.EVT_COUPON_REVOKED, self.mod.CANONICAL_EVENTS)
        self.assertIn(self.mod.EVT_COUPON_CONSUMED, self.mod.CANONICAL_EVENTS)
        # Verifica los strings canónicos.
        self.assertEqual(self.mod.EVT_COUPON_APPLIED, "coupon_applied")
        self.assertEqual(self.mod.EVT_COUPON_REVOKED, "coupon_revoked")
        self.assertEqual(self.mod.EVT_COUPON_CONSUMED, "coupon_consumed")

    def test_emit_coupon_applied_event(self):
        # Smoke: emitir un coupon_applied funciona como cualquier evento.
        sb = self._mock_sb()
        row_id = self.mod.emit(
            sb, cart_id="c1", tenant_id="t1",
            event_type=self.mod.EVT_COUPON_APPLIED,
            payload={
                "coupon_id": "coup-1", "code": "PROMO10",
                "type": "percent", "discount_cents": 10000,
            },
        )
        self.assertEqual(row_id, "evt-uuid-1")


if __name__ == "__main__":
    unittest.main()

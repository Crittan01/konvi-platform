"""Tests coupon engine (rev. 105 Sem 6 I.2 / ADR-0015).

Cubre:
  1. validate_coupon_applicable — todos los reasons
  2. compute_discount — los 3 tipos + edge cases
  3. apply_coupon — happy path + reject (cart con cupón, validation fail)
  4. revoke_coupon — happy + idempotente
  5. consume_redemption — atomic increment + overhang
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
api_root = REPO_ROOT / "services" / "api"
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))


# Cargar módulo lib.coupons aislado.
def _load_coupons():
    if "_coupons" in sys.modules:
        return sys.modules["_coupons"]
    spec = importlib.util.spec_from_file_location(
        "_coupons",
        REPO_ROOT / "services" / "api" / "lib" / "coupons.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_coupons"] = mod
    spec.loader.exec_module(mod)
    return mod


cp = _load_coupons()


# ─── validate_coupon_applicable ──────────────────────────────────────────────

NOW_FROZEN = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _make_coupon(**overrides) -> dict:
    base = {
        "id": "c-1",
        "code": "PROMO10",
        "discount_type": "percent",
        "discount_value": 10,
        "min_subtotal_cents": 0,
        "max_redemptions": None,
        "redemptions_count": 0,
        "valid_from": None,
        "valid_until": None,
        "is_active": True,
    }
    base.update(overrides)
    return base


class ValidateCouponApplicableTests(unittest.TestCase):
    def test_happy_path(self):
        r = cp.validate_coupon_applicable(_make_coupon(), 100000, now=NOW_FROZEN)
        self.assertTrue(r.ok)
        self.assertEqual(r.reason, "ok")

    def test_coupon_none_returns_not_found(self):
        r = cp.validate_coupon_applicable(None, 100000, now=NOW_FROZEN)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "coupon_not_found")

    def test_inactive_rejected(self):
        r = cp.validate_coupon_applicable(
            _make_coupon(is_active=False), 100000, now=NOW_FROZEN,
        )
        self.assertEqual(r.reason, "not_active")

    def test_invalid_discount_type(self):
        r = cp.validate_coupon_applicable(
            _make_coupon(discount_type="weird"), 100000, now=NOW_FROZEN,
        )
        self.assertEqual(r.reason, "invalid_discount_type")

    def test_before_valid_from(self):
        future = (NOW_FROZEN + timedelta(days=1)).isoformat()
        r = cp.validate_coupon_applicable(
            _make_coupon(valid_from=future), 100000, now=NOW_FROZEN,
        )
        self.assertEqual(r.reason, "before_valid_from")

    def test_expired(self):
        past = (NOW_FROZEN - timedelta(days=1)).isoformat()
        r = cp.validate_coupon_applicable(
            _make_coupon(valid_until=past), 100000, now=NOW_FROZEN,
        )
        self.assertEqual(r.reason, "expired")

    def test_min_subtotal_not_met(self):
        r = cp.validate_coupon_applicable(
            _make_coupon(min_subtotal_cents=200000), 100000, now=NOW_FROZEN,
        )
        self.assertEqual(r.reason, "min_subtotal_not_met")

    def test_max_redemptions_reached(self):
        r = cp.validate_coupon_applicable(
            _make_coupon(max_redemptions=5, redemptions_count=5),
            100000, now=NOW_FROZEN,
        )
        self.assertEqual(r.reason, "max_redemptions_reached")

    def test_max_redemptions_null_no_limit(self):
        r = cp.validate_coupon_applicable(
            _make_coupon(max_redemptions=None, redemptions_count=999999),
            100000, now=NOW_FROZEN,
        )
        self.assertTrue(r.ok)

    def test_user_message_renders(self):
        r = cp.validate_coupon_applicable(
            _make_coupon(is_active=False), 100000, now=NOW_FROZEN,
        )
        self.assertIn("disponible", r.user_message.lower())

    def test_naive_timestamps_treated_as_utc(self):
        # PostgreSQL tz-aware default. Si viene naive, asumimos UTC.
        future = datetime(2030, 1, 1)  # naive
        r = cp.validate_coupon_applicable(
            _make_coupon(valid_from=future.isoformat()),
            100000, now=NOW_FROZEN,
        )
        self.assertEqual(r.reason, "before_valid_from")


# ─── compute_discount ────────────────────────────────────────────────────────

class ComputeDiscountTests(unittest.TestCase):
    def test_percent_10(self):
        c = _make_coupon(discount_type="percent", discount_value=10)
        self.assertEqual(cp.compute_discount(c, 100000, 0), 10000)

    def test_percent_floor(self):
        # 99.999 cents = floor 9 cents (no fracciones).
        c = _make_coupon(discount_type="percent", discount_value=10)
        self.assertEqual(cp.compute_discount(c, 99, 0), 9)  # floor(99*10/100)=9

    def test_percent_capped_at_subtotal(self):
        # percent 100 → discount = subtotal completo.
        c = _make_coupon(discount_type="percent", discount_value=100)
        self.assertEqual(cp.compute_discount(c, 50000, 0), 50000)

    def test_percent_zero(self):
        c = _make_coupon(discount_type="percent", discount_value=0)
        self.assertEqual(cp.compute_discount(c, 100000, 0), 0)

    def test_fixed_amount_under_subtotal(self):
        c = _make_coupon(discount_type="fixed_amount", discount_value=15000)
        self.assertEqual(cp.compute_discount(c, 100000, 0), 15000)

    def test_fixed_amount_capped_at_subtotal(self):
        c = _make_coupon(discount_type="fixed_amount", discount_value=200000)
        self.assertEqual(cp.compute_discount(c, 50000, 0), 50000)

    def test_free_shipping(self):
        c = _make_coupon(discount_type="free_shipping", discount_value=999)
        # discount = shipping_cents (value ignorado).
        self.assertEqual(cp.compute_discount(c, 100000, 12000), 12000)

    def test_free_shipping_zero_shipping(self):
        c = _make_coupon(discount_type="free_shipping")
        self.assertEqual(cp.compute_discount(c, 100000, 0), 0)

    def test_invalid_type_returns_zero(self):
        c = _make_coupon(discount_type="weird", discount_value=100)
        self.assertEqual(cp.compute_discount(c, 100000, 0), 0)

    def test_negative_inputs_safe(self):
        c = _make_coupon(discount_type="percent", discount_value=10)
        self.assertEqual(cp.compute_discount(c, -100, 0), 0)
        self.assertEqual(cp.compute_discount(c, 100, -50), 0)


# ─── Fake Supabase ───────────────────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None, table_name: str = ""):
        self._store = store
        self._op = op
        self._payload = payload
        self._table = table_name
        self._filters: list[tuple[str, str, Any]] = []
        self._cols = "*"
        self._limit: int | None = None

    def select(self, cols: str = "*"):
        q = _FakeQuery(self._store, op="select", table_name=self._table)
        q._cols = cols
        return q

    def insert(self, payload: dict[str, Any]):
        return _FakeQuery(self._store, op="insert", payload=payload,
                          table_name=self._table)

    def update(self, payload: dict[str, Any]):
        return _FakeQuery(self._store, op="update", payload=payload,
                          table_name=self._table)

    def eq(self, col: str, val: Any):
        self._filters.append((col, "eq", val))
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for col, op, val in self._filters:
            if op == "eq" and row.get(col) != val:
                return False
        return True

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            if self._limit:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)
        if self._op == "insert":
            new_id = f"id-{len(self._store) + 1}"
            row = {**self._payload, "id": self._payload.get("id", new_id)}
            self._store.append(row)
            return SimpleNamespace(data=[row])
        if self._op == "update":
            updated = []
            for row in self._store:
                if self._matches(row):
                    for k, v in self._payload.items():
                        row[k] = v
                    updated.append(row)
            return SimpleNamespace(data=updated)
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeRpc:
    def __init__(self, name: str, args: dict, coupons_store: list[dict]):
        self._name = name
        self._args = args
        self._store = coupons_store

    def execute(self):
        if self._name == "coupon_increment_redemption":
            cid = self._args.get("p_coupon_id")
            for c in self._store:
                if c.get("id") == cid:
                    max_r = c.get("max_redemptions")
                    cnt = int(c.get("redemptions_count") or 0)
                    if max_r is None or cnt < int(max_r):
                        c["redemptions_count"] = cnt + 1
                        return SimpleNamespace(data=c["redemptions_count"])
                    return SimpleNamespace(data=None)
        return SimpleNamespace(data=None)


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict[str, Any]]] = {
            "coupons": [],
            "coupon_redemptions": [],
            "conversation_carts": [],
        }

    def table(self, name: str):
        return _FakeQuery(self._tables[name], table_name=name)

    def rpc(self, name: str, args: dict):
        return _FakeRpc(name, args, self._tables["coupons"])


# ─── apply_coupon ────────────────────────────────────────────────────────────

class ApplyCouponTests(unittest.TestCase):
    def _seed(
        self, *,
        cart_subtotal: int = 100000,
        cart_shipping: int = 12000,
        cart_coupon_id: str | None = None,
        coupon_overrides: dict | None = None,
    ):
        sb = _FakeSupabase()
        coupon = _make_coupon(**(coupon_overrides or {}))
        sb._tables["coupons"].append({
            **coupon, "tenant_id": "tenant-A",
        })
        sb._tables["conversation_carts"].append({
            "id": "cart-1",
            "tenant_id": "tenant-A",
            "subtotal_cents": cart_subtotal,
            "shipping_cents": cart_shipping,
            "total_cents": cart_subtotal + cart_shipping,
            "coupon_id": cart_coupon_id,
            "status": "open",
        })
        return sb

    def test_apply_happy_path(self):
        sb = self._seed()
        r = cp.apply_coupon(sb, "tenant-A", "cart-1", "PROMO10", now=NOW_FROZEN)
        self.assertTrue(r.ok)
        self.assertEqual(r.coupon_code, "PROMO10")
        self.assertEqual(r.discount_cents, 10000)
        # cart materializado actualizado.
        cart = sb._tables["conversation_carts"][0]
        self.assertEqual(cart["coupon_code"], "PROMO10")
        self.assertEqual(cart["discount_cents"], 10000)
        # total = subtotal + shipping - discount = 100000 + 12000 - 10000 = 102000.
        self.assertEqual(cart["total_cents"], 102000)
        # redemption row creada.
        self.assertEqual(len(sb._tables["coupon_redemptions"]), 1)
        self.assertEqual(sb._tables["coupon_redemptions"][0]["status"], "applied")

    def test_apply_coupon_not_found(self):
        sb = self._seed()
        r = cp.apply_coupon(sb, "tenant-A", "cart-1", "DOESNOTEXIST",
                            now=NOW_FROZEN)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "coupon_not_found")

    def test_apply_cart_not_found(self):
        sb = self._seed()
        r = cp.apply_coupon(sb, "tenant-A", "cart-DOES-NOT-EXIST", "PROMO10",
                            now=NOW_FROZEN)
        self.assertEqual(r.reason, "cart_not_found")

    def test_apply_cart_already_has_coupon(self):
        sb = self._seed(cart_coupon_id="other-coupon")
        r = cp.apply_coupon(sb, "tenant-A", "cart-1", "PROMO10", now=NOW_FROZEN)
        self.assertEqual(r.reason, "cart_already_has_coupon")

    def test_apply_min_subtotal_not_met(self):
        sb = self._seed(
            cart_subtotal=50000,
            coupon_overrides={"min_subtotal_cents": 100000},
        )
        r = cp.apply_coupon(sb, "tenant-A", "cart-1", "PROMO10", now=NOW_FROZEN)
        self.assertEqual(r.reason, "min_subtotal_not_met")
        # No insert ni update ocurrieron.
        self.assertEqual(len(sb._tables["coupon_redemptions"]), 0)
        self.assertIsNone(sb._tables["conversation_carts"][0].get("coupon_id"))

    def test_apply_free_shipping(self):
        sb = self._seed(
            cart_shipping=15000,
            coupon_overrides={
                "discount_type": "free_shipping",
                "discount_value": 0,
            },
        )
        r = cp.apply_coupon(sb, "tenant-A", "cart-1", "PROMO10", now=NOW_FROZEN)
        self.assertTrue(r.ok)
        self.assertEqual(r.discount_cents, 15000)
        cart = sb._tables["conversation_carts"][0]
        # total = 100000 + 15000 - 15000 = 100000.
        self.assertEqual(cart["total_cents"], 100000)


# ─── revoke_coupon ────────────────────────────────────────────────────────────

class RevokeCouponTests(unittest.TestCase):
    def _seed_with_applied(self):
        sb = _FakeSupabase()
        sb._tables["coupons"].append({
            **_make_coupon(), "tenant_id": "tenant-A",
        })
        sb._tables["conversation_carts"].append({
            "id": "cart-1",
            "tenant_id": "tenant-A",
            "subtotal_cents": 100000,
            "shipping_cents": 12000,
            "total_cents": 102000,
            "coupon_id": "c-1",
            "coupon_code": "PROMO10",
            "discount_cents": 10000,
            "status": "open",
        })
        sb._tables["coupon_redemptions"].append({
            "id": "r-1",
            "tenant_id": "tenant-A",
            "cart_id": "cart-1",
            "coupon_id": "c-1",
            "status": "applied",
            "discount_applied_cents": 10000,
        })
        return sb

    def test_revoke_happy(self):
        sb = self._seed_with_applied()
        ok = cp.revoke_coupon(sb, "tenant-A", "cart-1", reason="user_removed")
        self.assertTrue(ok)
        cart = sb._tables["conversation_carts"][0]
        self.assertIsNone(cart["coupon_id"])
        self.assertEqual(cart["discount_cents"], 0)
        # total = subtotal + shipping (sin descuento) = 112000.
        self.assertEqual(cart["total_cents"], 112000)
        # Redemption pasó a revoked.
        self.assertEqual(sb._tables["coupon_redemptions"][0]["status"], "revoked")
        self.assertEqual(
            sb._tables["coupon_redemptions"][0]["revoked_reason"],
            "user_removed",
        )

    def test_revoke_idempotente_sin_cupon(self):
        sb = _FakeSupabase()
        sb._tables["conversation_carts"].append({
            "id": "cart-1",
            "tenant_id": "tenant-A",
            "subtotal_cents": 100000,
            "shipping_cents": 0,
            "total_cents": 100000,
            "coupon_id": None,
            "status": "open",
        })
        ok = cp.revoke_coupon(sb, "tenant-A", "cart-1")
        self.assertFalse(ok)  # No-op idempotente.

    def test_revoke_cart_not_found(self):
        sb = _FakeSupabase()
        ok = cp.revoke_coupon(sb, "tenant-A", "cart-NOPE")
        self.assertFalse(ok)


# ─── consume_redemption ──────────────────────────────────────────────────────

class ConsumeRedemptionTests(unittest.TestCase):
    def _seed(self, *, max_redemptions: int | None = None,
              redemptions_count: int = 0):
        sb = _FakeSupabase()
        sb._tables["coupons"].append({
            **_make_coupon(
                max_redemptions=max_redemptions,
                redemptions_count=redemptions_count,
            ),
            "tenant_id": "tenant-A",
        })
        sb._tables["coupon_redemptions"].append({
            "id": "r-1",
            "tenant_id": "tenant-A",
            "cart_id": "cart-1",
            "coupon_id": "c-1",
            "status": "applied",
            "discount_applied_cents": 10000,
        })
        return sb

    def test_consume_happy(self):
        sb = self._seed(max_redemptions=10, redemptions_count=3)
        ok = cp.consume_redemption(sb, "tenant-A", "cart-1", "order-X")
        self.assertTrue(ok)
        self.assertEqual(sb._tables["coupons"][0]["redemptions_count"], 4)
        self.assertEqual(sb._tables["coupon_redemptions"][0]["status"], "consumed")
        self.assertEqual(sb._tables["coupon_redemptions"][0]["order_id"], "order-X")

    def test_consume_no_max_increments(self):
        sb = self._seed(max_redemptions=None, redemptions_count=999)
        ok = cp.consume_redemption(sb, "tenant-A", "cart-1", "order-X")
        self.assertTrue(ok)
        self.assertEqual(sb._tables["coupons"][0]["redemptions_count"], 1000)

    def test_consume_overhang_logs_warning(self):
        # max_redemptions ya alcanzado entre apply y APPROVED.
        sb = self._seed(max_redemptions=5, redemptions_count=5)
        ok = cp.consume_redemption(sb, "tenant-A", "cart-1", "order-X")
        self.assertTrue(ok)  # Se marca consumed igual (cliente conserva descuento).
        # Pero NO incrementa.
        self.assertEqual(sb._tables["coupons"][0]["redemptions_count"], 5)
        self.assertEqual(sb._tables["coupon_redemptions"][0]["status"], "consumed")

    def test_consume_no_redemption_applied(self):
        sb = self._seed()
        # Marcar la única redemption como ya consumed para simular doble call.
        sb._tables["coupon_redemptions"][0]["status"] = "consumed"
        ok = cp.consume_redemption(sb, "tenant-A", "cart-1", "order-X")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

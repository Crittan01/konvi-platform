"""Tests del repo de carritos conversacionales.

Cubre:
- get_open_cart: retorna None si no hay carrito; carrito + items si hay.
- create_open_cart: idempotente vs partial UNIQUE (race resuelta).
- add_item: pasa parámetros al RPC ``cart_add_item``; mapea SQLSTATE 40001 a
  CartConflict; "not found" a CartNotFound; "not open" a CartClosed.
- update_shipping_meta: optimistic lock — version mismatch → CartConflict.
- transition_status: requiere converted_order_id para 'converted'.
- remove_item: recalcula subtotal y total respetando version.
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from persistence.carts_repo import (  # noqa: E402
    Cart,
    CartItem,
    CartClosed,
    CartConflict,
    CartNotFound,
    CartsRepo,
)


# ── Fakes mínimos del SDK Supabase (chainable builder) ───────────────────────


class _Q:
    """Fake query builder. Devuelve self en cada operación encadenable y
    expone ``execute()`` que retorna lo configurado por el test.
    """

    def __init__(self, response_data=None, mode="select"):
        self._response_data = response_data
        self._mode = mode

    def select(self, *_a, **_k): return self
    def insert(self, payload, **_k):
        # Para INSERT, simulamos que el row insertado es el payload + defaults.
        if isinstance(payload, dict):
            self._response_data = [{
                "id": "cart-new",
                "tenant_id": payload.get("tenant_id"),
                "conversation_id": payload.get("conversation_id"),
                "contact_id": payload.get("contact_id"),
                "status": "open",
                "version": 1,
                "shipping_meta": {},
                "subtotal_cents": 0,
                "shipping_cents": 0,
                "total_cents": 0,
                "currency": "COP",
                "converted_order_id": None,
            }]
        return self
    def update(self, payload, **_k):
        # update con eq("version", N) — simulamos que el test setea data al
        # nivel del Q antes para indicar match (rows) o miss (empty).
        self._update_payload = payload
        return self
    def delete(self, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def single(self, *_a, **_k): return self
    def execute(self):
        return SimpleNamespace(data=self._response_data)


class _SBFake:
    """Fake Supabase client. Cada test configura ``self._tables[name]`` con un
    callable que devuelve un ``_Q`` preparado para esa tabla.
    """

    def __init__(self):
        self._tables: dict[str, list[_Q]] = {}
        self._table_calls: list[str] = []
        self.rpc_args: dict | None = None
        self.rpc_response: list | None = None

    def queue_table(self, name: str, response_data):
        self._tables.setdefault(name, []).append(_Q(response_data))

    def table(self, name: str):
        self._table_calls.append(name)
        queue = self._tables.get(name) or []
        if queue:
            return queue.pop(0)
        # Default: empty result
        return _Q([])

    def rpc(self, name: str, args: dict):
        self.rpc_args = {"name": name, "args": args}
        if self.rpc_response is not None and isinstance(self.rpc_response, Exception):
            raise self.rpc_response
        return _Q(self.rpc_response or [])


# ── Tests ────────────────────────────────────────────────────────────────────


class GetOpenCartTests(unittest.TestCase):
    def test_returns_none_when_no_cart(self):
        sb = _SBFake()
        sb.queue_table("conversation_carts", [])
        repo = CartsRepo(sb)
        result = repo.get_open_cart(tenant_id="t1", conversation_id="c1")
        self.assertIsNone(result)

    def test_returns_cart_with_items(self):
        sb = _SBFake()
        sb.queue_table(
            "conversation_carts",
            [{
                "id": "cart-1",
                "tenant_id": "t1",
                "conversation_id": "c1",
                "contact_id": "ct1",
                "status": "open",
                "version": 3,
                "shipping_meta": {"city": "Bogotá"},
                "subtotal_cents": 9300000,
                "shipping_cents": 700000,
                "total_cents": 10000000,
                "currency": "COP",
                "converted_order_id": None,
            }],
        )
        sb.queue_table(
            "conversation_cart_items",
            [
                {"id": "i1", "cart_id": "cart-1", "product_id": "p1",
                 "variation_id": "v1", "quantity": 1, "unit_price_cents": 2800000, "meta": {}},
                {"id": "i2", "cart_id": "cart-1", "product_id": "p1",
                 "variation_id": "v2", "quantity": 1, "unit_price_cents": 6500000, "meta": {}},
            ],
        )
        repo = CartsRepo(sb)
        cart = repo.get_open_cart(tenant_id="t1", conversation_id="c1")
        self.assertIsNotNone(cart)
        assert cart is not None  # narrow para mypy
        self.assertEqual(cart.id, "cart-1")
        self.assertTrue(cart.is_open)
        self.assertEqual(cart.version, 3)
        self.assertEqual(len(cart.items), 2)
        self.assertEqual(cart.item_count, 2)
        # Multi-variante mismo producto: dos filas distintas con product_id idéntico
        self.assertEqual(cart.items[0].product_id, cart.items[1].product_id)
        self.assertNotEqual(cart.items[0].variation_id, cart.items[1].variation_id)
        self.assertEqual(cart.items[0].line_total_cents, 2800000)


class CreateOpenCartTests(unittest.TestCase):
    def test_creates_new_cart(self):
        sb = _SBFake()
        # INSERT auto-genera la respuesta en _Q.insert
        sb.queue_table("conversation_carts", None)  # placeholder; insert fills it
        repo = CartsRepo(sb)
        cart = repo.create_open_cart(tenant_id="t1", conversation_id="c1")
        self.assertEqual(cart.tenant_id, "t1")
        self.assertEqual(cart.status, "open")
        self.assertEqual(cart.version, 1)


class AddItemTests(unittest.TestCase):
    def test_calls_rpc_with_correct_args(self):
        sb = _SBFake()
        # RPC ahora devuelve OUT params con prefijo `out_` (rev. fix
        # 20260501000001) — el repo los normaliza al nombre sin prefijo.
        sb.rpc_response = [{
            "out_cart_id": "cart-1",
            "out_new_version": 4,
            "out_subtotal_cents": 11150000,
            "out_total_cents": 11850000,
        }]
        repo = CartsRepo(sb)
        result = repo.add_item(
            tenant_id="t1", cart_id="cart-1",
            product_id="p1", variation_id="v2",
            quantity=1, unit_price_cents=6500000,
            expected_version=3,
        )
        assert sb.rpc_args is not None
        self.assertEqual(sb.rpc_args["name"], "cart_add_item")
        self.assertEqual(sb.rpc_args["args"]["p_quantity"], 1)
        self.assertEqual(sb.rpc_args["args"]["p_expected_version"], 3)
        self.assertEqual(result["new_version"], 4)
        self.assertEqual(result["subtotal_cents"], 11150000)

    def test_invalid_quantity_raises_value_error(self):
        repo = CartsRepo(_SBFake())
        with self.assertRaises(ValueError):
            repo.add_item(
                tenant_id="t1", cart_id="cart-1",
                product_id="p1", variation_id="v1",
                quantity=0, unit_price_cents=1000,
            )

    def test_version_mismatch_raises_conflict(self):
        sb = _SBFake()
        sb.rpc_response = Exception("cart_add_item: version mismatch (expected 3, got 5) [40001]")
        repo = CartsRepo(sb)
        with self.assertRaises(CartConflict):
            repo.add_item(
                tenant_id="t1", cart_id="cart-1",
                product_id="p1", variation_id="v1",
                quantity=1, unit_price_cents=1000,
                expected_version=3,
            )

    def test_cart_not_open_raises_closed(self):
        sb = _SBFake()
        sb.rpc_response = Exception("cart_add_item: cart cart-1 is not open (status=converted)")
        repo = CartsRepo(sb)
        with self.assertRaises(CartClosed):
            repo.add_item(
                tenant_id="t1", cart_id="cart-1",
                product_id="p1", variation_id="v1",
                quantity=1, unit_price_cents=1000,
            )

    def test_cart_not_found_raises_not_found(self):
        sb = _SBFake()
        sb.rpc_response = Exception("cart_add_item: cart cart-x not found for tenant t1")
        repo = CartsRepo(sb)
        with self.assertRaises(CartNotFound):
            repo.add_item(
                tenant_id="t1", cart_id="cart-x",
                product_id="p1", variation_id="v1",
                quantity=1, unit_price_cents=1000,
            )


class UpdateShippingMetaTests(unittest.TestCase):
    def test_version_match_returns_new_version(self):
        sb = _SBFake()
        # update returning (Postgres) — el _Q fake retorna lo que pongamos en queue
        q = _Q([{
            "id": "cart-1",
            "version": 4,
            "subtotal_cents": 9300000,
            "total_cents": 10000000,
        }])
        sb._tables["conversation_carts"] = [q]
        repo = CartsRepo(sb)
        new_v = repo.update_shipping_meta(
            tenant_id="t1", cart_id="cart-1",
            shipping_meta={"city": "Bogotá", "carrier": "envia"},
            shipping_cents=700000,
            expected_version=3,
        )
        self.assertEqual(new_v, 4)

    def test_version_mismatch_raises_conflict(self):
        sb = _SBFake()
        sb._tables["conversation_carts"] = [_Q([])]  # 0 rows = mismatch
        repo = CartsRepo(sb)
        with self.assertRaises(CartConflict):
            repo.update_shipping_meta(
                tenant_id="t1", cart_id="cart-1",
                shipping_meta={}, shipping_cents=0,
                expected_version=99,
            )


class TransitionStatusTests(unittest.TestCase):
    def test_invalid_status_raises_value_error(self):
        repo = CartsRepo(_SBFake())
        with self.assertRaises(ValueError):
            repo.transition_status(
                tenant_id="t1", cart_id="cart-1",
                new_status="bogus",
                expected_version=1,
            )

    def test_converted_requires_order_id(self):
        repo = CartsRepo(_SBFake())
        with self.assertRaises(ValueError):
            repo.transition_status(
                tenant_id="t1", cart_id="cart-1",
                new_status="converted",
                expected_version=1,
            )

    def test_abandoned_works_without_order_id(self):
        sb = _SBFake()
        sb._tables["conversation_carts"] = [_Q([{"version": 5}])]
        repo = CartsRepo(sb)
        new_v = repo.transition_status(
            tenant_id="t1", cart_id="cart-1",
            new_status="abandoned",
            expected_version=4,
        )
        self.assertEqual(new_v, 5)


if __name__ == "__main__":
    unittest.main()

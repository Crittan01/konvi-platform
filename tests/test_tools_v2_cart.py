"""Tests de ``tools_v2/cart_tools.py``.

Cubre:
- handle_add_item_to_cart con catálogo válido → llama repo.add_item con
  precio resuelto desde catálogo (NO confía en el LLM).
- variation_id no encontrado en catálogo → ok=False con error.
- repo levanta CartConflict → ok=False, retry=True.
- 1×10ml + 1×30ml mismo producto: dos llamadas con product_id idéntico,
  variation_id distinto, ambas suceden — repo recibe los args correctos.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from core.context import ConversationContext  # noqa: E402
from core.fsm import State  # noqa: E402
from persistence.carts_repo import Cart, CartConflict  # noqa: E402
from tools_v2.cart_tools import (  # noqa: E402
    handle_add_item_to_cart,
    handle_remove_item_from_cart,
)


class _FakeRepo:
    def __init__(self):
        self.add_calls: list[dict] = []
        self.remove_calls: list[dict] = []
        self.next_response: dict | Exception | None = None
        self.created_carts: list[Cart] = []

    def create_open_cart(self, *, tenant_id, conversation_id, contact_id):
        cart = Cart(
            id="cart-new",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            status="open",
            version=1,
            shipping_meta={},
            subtotal_cents=0,
            shipping_cents=0,
            total_cents=0,
            currency="COP",
            converted_order_id=None,
        )
        self.created_carts.append(cart)
        return cart

    def add_item(self, **kwargs):
        self.add_calls.append(kwargs)
        if isinstance(self.next_response, Exception):
            raise self.next_response
        return self.next_response or {
            "cart_id": kwargs["cart_id"],
            "new_version": 2,
            "subtotal_cents": kwargs["unit_price_cents"] * kwargs["quantity"],
            "total_cents": kwargs["unit_price_cents"] * kwargs["quantity"],
        }

    def remove_item(self, **kwargs):
        self.remove_calls.append(kwargs)
        return 99


def _build_ctx(*, cart=None, catalog=None) -> ConversationContext:
    return ConversationContext(
        tenant_id="t1",
        conversation_id="conv1",
        message_id="m1",
        contact_id="ct1",
        customer_phone="573125835649",
        content="dame 1 de 10ml y 1 de 30ml",
        content_type="text",
        fsm_state=State.NEEDS_SHIPPING_CITY,
        cart=cart,
        contact_record={},
        history=[],
        catalog=catalog or [],
    )


_LAVANDA_CATALOG = [{
    "id": "prod-lav",
    "title": "Aceite Esencial de Lavanda",
    "variants": [
        {"id": "var-10ml", "label": "10ml", "price": 28000, "stock": 5,
         "attributes": {"Volumen": "10ml"}},
        {"id": "var-30ml", "label": "30ml", "price": 65000, "stock": 5,
         "attributes": {"Volumen": "30ml"}},
    ],
}]


class AddItemToCartTests(unittest.TestCase):
    def test_resolves_price_from_catalog_not_llm(self):
        repo = _FakeRepo()
        existing_cart = Cart(
            id="cart-1", tenant_id="t1", conversation_id="conv1",
            contact_id=None, status="open", version=3,
            shipping_meta={}, subtotal_cents=0, shipping_cents=0,
            total_cents=0, currency="COP", converted_order_id=None,
        )
        ctx = _build_ctx(cart=existing_cart, catalog=_LAVANDA_CATALOG)
        result = asyncio.run(handle_add_item_to_cart(
            ctx=ctx,
            args={
                "product_id": "prod-lav",
                "variation_id": "var-10ml",
                "quantity": 1,
                # El LLM podría meter cualquier price aquí — DEBE ignorarlo
                # y leer del catálogo.
            },
            repo=repo,
        ))
        self.assertTrue(result["ok"])
        self.assertEqual(repo.add_calls[0]["unit_price_cents"], 2_800_000)
        # Cents = pesos × 100 — coherente con catalog.price=28000

    def test_two_calls_one_per_variation(self):
        """Caso real: 1×10ml + 1×30ml = dos function_calls distintas.
        El bug original era detectar esto como UN producto. Con tool calling
        el LLM emite dos add_item_to_cart, uno por variation_id."""
        repo = _FakeRepo()
        existing_cart = Cart(
            id="cart-1", tenant_id="t1", conversation_id="conv1",
            contact_id=None, status="open", version=1,
            shipping_meta={}, subtotal_cents=0, shipping_cents=0,
            total_cents=0, currency="COP", converted_order_id=None,
        )
        ctx = _build_ctx(cart=existing_cart, catalog=_LAVANDA_CATALOG)

        r1 = asyncio.run(handle_add_item_to_cart(
            ctx=ctx,
            args={"product_id": "prod-lav", "variation_id": "var-10ml", "quantity": 1},
            repo=repo,
        ))
        r2 = asyncio.run(handle_add_item_to_cart(
            ctx=ctx,
            args={"product_id": "prod-lav", "variation_id": "var-30ml", "quantity": 1},
            repo=repo,
        ))
        self.assertTrue(r1["ok"] and r2["ok"])
        self.assertEqual(len(repo.add_calls), 2)
        # Mismo producto, diferentes variantes — el caso que rompía antes
        self.assertEqual(repo.add_calls[0]["product_id"], repo.add_calls[1]["product_id"])
        self.assertNotEqual(
            repo.add_calls[0]["variation_id"],
            repo.add_calls[1]["variation_id"],
        )
        self.assertEqual(repo.add_calls[0]["unit_price_cents"], 2_800_000)
        self.assertEqual(repo.add_calls[1]["unit_price_cents"], 6_500_000)

    def test_creates_cart_if_none_exists(self):
        repo = _FakeRepo()
        ctx = _build_ctx(cart=None, catalog=_LAVANDA_CATALOG)
        result = asyncio.run(handle_add_item_to_cart(
            ctx=ctx,
            args={"product_id": "prod-lav", "variation_id": "var-10ml", "quantity": 1},
            repo=repo,
        ))
        self.assertTrue(result["ok"])
        self.assertEqual(len(repo.created_carts), 1)
        self.assertEqual(repo.created_carts[0].tenant_id, "t1")

    def test_unknown_variation_returns_error(self):
        repo = _FakeRepo()
        existing_cart = Cart(
            id="cart-1", tenant_id="t1", conversation_id="conv1",
            contact_id=None, status="open", version=1,
            shipping_meta={}, subtotal_cents=0, shipping_cents=0,
            total_cents=0, currency="COP", converted_order_id=None,
        )
        ctx = _build_ctx(cart=existing_cart, catalog=_LAVANDA_CATALOG)
        result = asyncio.run(handle_add_item_to_cart(
            ctx=ctx,
            args={"product_id": "prod-lav", "variation_id": "var-bogus", "quantity": 1},
            repo=repo,
        ))
        self.assertFalse(result["ok"])
        self.assertEqual(len(repo.add_calls), 0)

    def test_invalid_quantity_returns_error(self):
        repo = _FakeRepo()
        existing_cart = Cart(
            id="cart-1", tenant_id="t1", conversation_id="conv1",
            contact_id=None, status="open", version=1,
            shipping_meta={}, subtotal_cents=0, shipping_cents=0,
            total_cents=0, currency="COP", converted_order_id=None,
        )
        ctx = _build_ctx(cart=existing_cart, catalog=_LAVANDA_CATALOG)
        result = asyncio.run(handle_add_item_to_cart(
            ctx=ctx,
            args={"product_id": "prod-lav", "variation_id": "var-10ml", "quantity": 0},
            repo=repo,
        ))
        self.assertFalse(result["ok"])

    def test_cart_conflict_returns_retry_flag(self):
        repo = _FakeRepo()
        repo.next_response = CartConflict("version mismatch")
        existing_cart = Cart(
            id="cart-1", tenant_id="t1", conversation_id="conv1",
            contact_id=None, status="open", version=1,
            shipping_meta={}, subtotal_cents=0, shipping_cents=0,
            total_cents=0, currency="COP", converted_order_id=None,
        )
        ctx = _build_ctx(cart=existing_cart, catalog=_LAVANDA_CATALOG)
        result = asyncio.run(handle_add_item_to_cart(
            ctx=ctx,
            args={"product_id": "prod-lav", "variation_id": "var-10ml", "quantity": 1},
            repo=repo,
        ))
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("retry"))


class RemoveItemTests(unittest.TestCase):
    def test_no_cart_returns_error(self):
        repo = _FakeRepo()
        ctx = _build_ctx(cart=None, catalog=_LAVANDA_CATALOG)
        result = asyncio.run(handle_remove_item_from_cart(
            ctx=ctx, args={"variation_id": "var-10ml"}, repo=repo,
        ))
        self.assertFalse(result["ok"])

    def test_calls_repo_remove(self):
        repo = _FakeRepo()
        existing_cart = Cart(
            id="cart-1", tenant_id="t1", conversation_id="conv1",
            contact_id=None, status="open", version=4,
            shipping_meta={}, subtotal_cents=2_800_000, shipping_cents=0,
            total_cents=2_800_000, currency="COP", converted_order_id=None,
        )
        ctx = _build_ctx(cart=existing_cart, catalog=_LAVANDA_CATALOG)
        result = asyncio.run(handle_remove_item_from_cart(
            ctx=ctx, args={"variation_id": "var-10ml"}, repo=repo,
        ))
        self.assertTrue(result["ok"])
        self.assertEqual(len(repo.remove_calls), 1)
        self.assertEqual(repo.remove_calls[0]["variation_id"], "var-10ml")
        self.assertEqual(repo.remove_calls[0]["expected_version"], 4)


if __name__ == "__main__":
    unittest.main()

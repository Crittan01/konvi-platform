"""F1 (roadmap producción) — coherencia de DINERO: el descuento del cupón llega al total de la orden.

Cierra el bug CRÍTICO: create_order recomponía total = Σ(items)+shipping IGNORANDO el descuento del cart
→ orders.total_amount (y por ende el cobro Wompi) quedaba pleno mientras el cliente veía el total con
descuento. Ahora create_order lee conversation_carts.discount_cents por conversation_id y espeja la fórmula
del cart: total = max(0, subtotal + shipping - descuento).
"""
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402
from routers import orders as orders_mod  # noqa: E402
from routers.orders import OrderCreate, OrderItemCreate  # noqa: E402

_REQ = types.SimpleNamespace(headers={}, method="POST", url=types.SimpleNamespace(path="/api/v1/orders/"))


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op, self.rows = name, ctrl, "select", None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, rows, *a, **k):
        self.op = "insert"
        self.rows = rows
        return self

    def update(self, data, *a, **k):
        self.op = "update"
        self.rows = data
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return self.ctrl._exec(self)


class _Ctrl:
    """Fake supabase — respuestas por (tabla, op); captura los inserts; default [] (robusto)."""

    def __init__(self, responses):
        self.responses = responses
        self.captured = {}

    def table(self, name):
        return _Q(name, self)

    def _exec(self, q):
        if q.op == "insert":
            self.captured.setdefault(q.name, []).append(q.rows)
        return types.SimpleNamespace(data=self.responses.get((q.name, q.op), []))


async def _create(ctrl, payload):
    return orders_mod.create_order(
        order=payload, request=_REQ, tenant_id="t1", supabase=ctrl, _role="manager",
    )


def _payload(**kw):
    kw.setdefault("payment_link", True)
    kw.setdefault("payment_method", "credit")
    return OrderCreate(items=[OrderItemCreate(title="Prod", unit_price=kw.pop("unit_price"),
                                              quantity=kw.pop("qty"), variation_id="v1")], **kw)


class OrderDiscountCoherenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cart_discount_reaches_order_total(self):
        # subtotal 100 + envío 12 - descuento 10 = 102 ; discount_amount snapshot 10.
        # BLOQUE A (P1): el descuento se hereda solo con cart no-terminal + redención 'applied' viva.
        ctrl = _Ctrl({
            ("conversation_carts", "select"): [{"id": "cart-1", "status": "open", "discount_cents": 1000}],
            ("coupon_redemptions", "select"): [{"id": "red-1"}],           # redención viva ('applied')
            ("conversations", "select"): [{"id": "conv-1"}],               # F27: ownership FK
            ("orders", "insert"): [{"id": "order-1"}],
            ("product_variations", "select"): [{"id": "v1", "cost_price": 0}],  # F27: variation del tenant
            ("order_items", "insert"): [{"id": "oi-1"}],
        })
        await _create(ctrl, _payload(conversation_id="conv-1", shipping_cost=12.0, unit_price=100.0, qty=1))
        ins = ctrl.captured["orders"][0]
        self.assertEqual(ins["total_amount"], 102.0)   # << antes daba 112 (sin descuento)
        self.assertEqual(ins["discount_amount"], 10.0)

    async def test_stale_discount_sin_redencion_viva_no_se_aplica(self):
        """BLOQUE A (P1): cart con discount_cents pero SIN redención 'applied' viva
        (cupón ya consumido en un pago previo, o revocado) → el descuento NO se re-aplica.
        Cierra el doble-descuento en un 2º pedido manual del operador para la misma conversación."""
        ctrl = _Ctrl({
            ("conversation_carts", "select"): [{"id": "cart-c", "status": "open", "discount_cents": 1000}],
            ("coupon_redemptions", "select"): [],                          # NO hay redención viva
            ("conversations", "select"): [{"id": "conv-c"}],
            ("orders", "insert"): [{"id": "order-c"}],
            ("product_variations", "select"): [{"id": "v1", "cost_price": 0}],
            ("order_items", "insert"): [{"id": "oi-c"}],
        })
        await _create(ctrl, _payload(conversation_id="conv-c", shipping_cost=12.0, unit_price=100.0, qty=1))
        ins = ctrl.captured["orders"][0]
        self.assertEqual(ins["total_amount"], 112.0)   # subtotal 100 + envío 12, SIN descuento stale
        self.assertEqual(ins["discount_amount"], 0.0)

    async def test_no_cart_means_no_discount(self):
        ctrl = _Ctrl({
            ("conversation_carts", "select"): [],  # sin cart para esta conversación
            ("conversations", "select"): [{"id": "conv-x"}],               # F27: ownership FK
            ("orders", "insert"): [{"id": "order-2"}],
            ("product_variations", "select"): [{"id": "v1", "cost_price": 0}],  # F27: variation del tenant
            ("order_items", "insert"): [{"id": "oi-2"}],
        })
        await _create(ctrl, _payload(conversation_id="conv-x", shipping_cost=5.0, unit_price=50.0, qty=2))
        ins = ctrl.captured["orders"][0]
        self.assertEqual(ins["total_amount"], 105.0)   # 100 + 5, sin descuento
        self.assertEqual(ins["discount_amount"], 0.0)

    async def test_manual_order_without_conversation_skips_cart(self):
        # Path Inbox/manual (sin conversation_id): no toca conversation_carts, sin descuento.
        ctrl = _Ctrl({
            ("orders", "insert"): [{"id": "order-3"}],
            ("product_variations", "select"): [{"id": "v1", "cost_price": 0}],  # F27: variation del tenant
            ("order_items", "insert"): [{"id": "oi-3"}],
        })
        await _create(ctrl, _payload(shipping_cost=8.0, unit_price=40.0, qty=1))
        ins = ctrl.captured["orders"][0]
        self.assertEqual(ins["total_amount"], 48.0)
        self.assertEqual(ins["discount_amount"], 0.0)

    async def test_rejects_contact_from_other_tenant(self):
        # F27: contact_id que no pertenece al tenant → 404 (no fuga PII cross-tenant vía embed).
        ctrl = _Ctrl({
            ("contacts", "select"): [],  # el contacto NO existe en este tenant
            ("product_variations", "select"): [{"id": "v1", "cost_price": 0}],
        })
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, _payload(contact_id="ajeno", shipping_cost=0.0, unit_price=10.0, qty=1))
        self.assertEqual(cm.exception.status_code, 404)

    async def test_rejects_variation_from_other_tenant(self):
        # F27: variation_id que no pertenece al tenant → 422.
        ctrl = _Ctrl({
            ("product_variations", "select"): [],  # v1 no pertenece al tenant
        })
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, _payload(shipping_cost=0.0, unit_price=10.0, qty=1))
        self.assertEqual(cm.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

"""Paridad canal↔canal para pedidos (Track 5 M2.1 — criterio §7.2 del contrato).

La MISMA operación ejecutada vía el adaptador REST (router, canal consola/bot
por HTTP) y vía el domain service in-process debe producir:
  1. La MISMA secuencia de operaciones de dominio sobre la DB (mismas tablas,
     mismas ops, mismos payloads de escritura).
  2. Un resultado equivalente (mismo body de respuesta).

Es la semilla de los tests de paridad del contrato: cuando el bot adopte los
servicios en M3, esta familia crece a cada operación de los pilotos.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi.responses import JSONResponse  # noqa: E402
from konvi_domain import Actor, Channel, Role  # noqa: E402
from konvi_domain.orders import CreateOrderInput, OrderItemInput  # noqa: E402
from konvi_domain.orders import service as svc  # noqa: E402
from routers import orders as orders_mod  # noqa: E402
from routers.orders import OrderCreate, OrderItemCreate  # noqa: E402

_REQ = types.SimpleNamespace(headers={}, method="POST", url=types.SimpleNamespace(path="/api/v1/orders/"))


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op, self.rows = name, ctrl, "select", None
        self.filters: list = []

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, rows, *a, **k):
        self.op, self.rows = "insert", rows
        return self

    def update(self, data, *a, **k):
        self.op, self.rows = "update", data
        return self

    def eq(self, *a):
        self.filters.append(tuple(a))
        return self

    def in_(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a):
        return self

    def range(self, *a):
        return self

    def ilike(self, *a):
        return self

    def gte(self, *a):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return self.ctrl._exec(self)


class _Ctrl:
    """Fake supabase con registro completo de queries (para comparar caminos)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls: list[_Q] = []

    def table(self, name):
        return _Q(name, self)

    def _exec(self, q: _Q):
        self.calls.append(q)
        return types.SimpleNamespace(data=self.responses.get((q.name, q.op), []))


# Tablas de bookkeeping del ADAPTADOR (audit decorator, idempotency keys) — no
# son operaciones de dominio; la paridad se mide sobre las tablas de negocio.
_ADAPTER_BOOKKEEPING = {"audit_log", "idempotency_keys"}


def _trace(ctrl: _Ctrl) -> list:
    """Secuencia (tabla, op, filters, rows) de DOMINIO — la huella comparable."""
    return [
        (q.name, q.op, q.filters, q.rows)
        for q in ctrl.calls
        if q.name not in _ADAPTER_BOOKKEEPING
    ]


_RESPONSES = {
    ("contacts", "select"): [{"id": "c-1"}],
    ("conversations", "select"): [{"id": "conv-1"}],
    ("product_variations", "select"): [{"id": "v1", "cost_price": 25.0}],
    ("conversation_carts", "select"): [{"id": "cart-1", "status": "open", "discount_cents": 1000}],
    ("coupon_redemptions", "select"): [{"id": "red-1"}],
    ("orders", "insert"): [{
        # Echo realista de la fila insertada (la DB devuelve lo que se insertó):
        # total F1 = 100×2 + 10 envío − 10 descuento = 200.
        "id": "o-1", "tenant_id": "t1", "status": "pending_payment",
        "total_amount": 200.0, "discount_amount": 10.0,
    }],
    ("order_items", "insert"): [],
}


class ChannelParityTests(unittest.TestCase):
    def _payload(self) -> OrderCreate:
        return OrderCreate(
            contact_id="c-1",
            conversation_id="conv-1",
            notes="Paridad",
            shipping_cost=10.0,
            payment_link=True,
            payment_method="credit",
            items=[OrderItemCreate(title="Prod", unit_price=100.0, quantity=2, variation_id="v1")],
        )

    def test_create_via_rest_y_via_servicio_producen_lo_mismo(self):
        # Canal 1: adaptador REST (lo que la consola y el bot-HTTP invocan).
        ctrl_http = _Ctrl({k: list(v) for k, v in _RESPONSES.items()})
        http_result = orders_mod.create_order(
            order=self._payload(), request=_REQ, tenant_id="t1",
            supabase=ctrl_http, _role="manager",
        )

        # Canal 2: domain service in-process (el camino del bot en M3).
        ctrl_svc = _Ctrl({k: list(v) for k, v in _RESPONSES.items()})
        svc_result = svc.create_order(
            ctrl_svc,
            tenant_id="t1",
            input=CreateOrderInput(
                contact_id="c-1",
                conversation_id="conv-1",
                notes="Paridad",
                shipping_cost=10.0,
                payment_link=True,
                payment_method="credit",
                items=(OrderItemInput(title="Prod", unit_price=100.0, quantity=2, variation_id="v1"),),
            ),
            actor=Actor(channel=Channel.CONSOLE, tenant_id="t1", role=Role.MANAGER),
            on_confirm_stock=None,
        )

        # 1) Misma huella de dominio sobre la DB.
        self.assertEqual(_trace(ctrl_http), _trace(ctrl_svc))

        # 2) Resultado equivalente (total con descuento F1: 200 + 10 − 10 = 200).
        self.assertEqual(svc_result.body(), http_result)
        self.assertEqual(http_result["total_amount"], 200.0)
        self.assertEqual(http_result["discount_amount"], 10.0)

    def test_get_via_rest_y_via_servicio_producen_lo_mismo(self):
        row = {"id": "o-1", "total_amount": 5.0, "order_items": []}
        req_get = types.SimpleNamespace(headers={}, method="GET", url=types.SimpleNamespace(path="/api/v1/orders/o-1"))

        ctrl_http = _Ctrl({("orders", "select"): [row]})
        http_result = orders_mod.get_order(
            order_id="o-1", request=req_get, tenant_id="t1", supabase=ctrl_http,
        )

        ctrl_svc = _Ctrl({("orders", "select"): [row]})
        svc_result = svc.get_order(
            ctrl_svc, tenant_id="t1", order_id="o-1",
            actor=Actor(channel=Channel.CONSOLE, tenant_id="t1"),
        )

        self.assertEqual(_trace(ctrl_http), _trace(ctrl_svc))
        self.assertEqual(svc_result, http_result)

    def test_list_via_rest_y_via_servicio_producen_lo_mismo(self):
        staged = {("orders", "select"): [{"id": "o-1", "status": "confirmed"}]}
        req_list = types.SimpleNamespace(headers={}, method="GET", url=types.SimpleNamespace(path="/api/v1/orders/"))

        ctrl_http = _Ctrl(staged)
        http_result = orders_mod.list_orders(
            request=req_list, status="confirmed", contact_id=None, q=None,
            page=2, per_page=20, tenant_id="t1", supabase=ctrl_http,
        )

        ctrl_svc = _Ctrl(staged)
        svc_result = svc.list_orders(
            ctrl_svc, tenant_id="t1",
            actor=Actor(channel=Channel.CONSOLE, tenant_id="t1"),
            status="confirmed", limit=20, offset=20,
        )

        # Misma huella (list + counts) — el adaptador añade paginación pero la
        # secuencia de queries es la del servicio.
        self.assertEqual(_trace(ctrl_http), _trace(ctrl_svc))
        self.assertEqual(http_result["orders"], svc_result.orders)
        self.assertEqual(http_result["counts"], svc_result.counts)
        self.assertEqual(http_result["total"], svc_result.total)

    def test_adopt_winner_via_rest_devuelve_200_y_marca(self):
        """El path de carrera 23505 mantiene el contrato HTTP heredado (200 +
        adopted_existing) tras la extracción."""
        from fastapi import HTTPException  # noqa: F401  (referencia de tipo)

        class _Ctrl23505(_Ctrl):
            def _exec(self, q: _Q):
                if q.name == "orders" and q.op == "insert":
                    raise Exception(
                        'duplicate key value violates unique constraint '
                        '"uq_orders_one_pending_payment_per_conversation" (SQLSTATE 23505)'
                    )
                return super()._exec(q)

        winner = {"id": "o-win", "status": "pending_payment", "conversation_id": "conv-1"}
        ctrl = _Ctrl23505({
            **{k: list(v) for k, v in _RESPONSES.items()},
            ("orders", "select"): [winner],
            ("order_items", "select"): [{"order_id": "o-win", "title": "X"}],
        })
        result = orders_mod.create_order(
            order=self._payload(), request=_REQ, tenant_id="t1",
            supabase=ctrl, _role="manager",
        )
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 200)
        import json as _json
        body = _json.loads(bytes(result.body).decode())
        self.assertTrue(body["adopted_existing"])
        self.assertEqual(body["id"], "o-win")
        self.assertEqual(body["items"], [{"order_id": "o-win", "title": "X"}])


if __name__ == "__main__":
    unittest.main()

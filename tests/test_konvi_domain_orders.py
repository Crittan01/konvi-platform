"""Tests unitarios de konvi_domain.orders.service (Track 5 M2.1).

Verifican la lógica de dominio extraída intacta de services/api/routers/orders.py:
  1. create — total recomputado + herencia de cupón vivo (F1) + guards
  2. create — validación FKs anti-IDOR (F27) con DomainError tipados
  3. create — adopt-winner en carrera 23505 (B1)
  4. create — efectos COD / auto-confirm (hook inyectado, best-effort)
  5. get — 404 NOT_FOUND tipado
  6. list — filtros, búsqueda D7, conteos por estado, paginación
  7. list_by_contact — historial del contacto (hueco del contrato)

Patrón de fake calcado de tests/test_order_discount_coherence.py, extendido
con count/head (list) y respuestas staged como excepción (adopt-winner).
"""
from __future__ import annotations

import types
import unittest
from typing import Any

from konvi_domain import Actor, Channel, DomainError, ErrorCode, Role
from konvi_domain.orders import (
    PAYMENT_METHOD_COD,
    CreateOrderInput,
    OrderItemInput,
)
from konvi_domain.orders import service as svc

# ─── Fake supabase ───────────────────────────────────────────────────────────


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op, self.rows = name, ctrl, "select", None
        self.filters: list = []
        self.count_requested = False

    def select(self, *a, **k):
        self.op = "select"
        if k.get("count"):
            self.count_requested = True
        return self

    def insert(self, rows, *a, **k):
        self.op, self.rows = "insert", rows
        return self

    def update(self, data, *a, **k):
        self.op, self.rows = "update", data
        return self

    def eq(self, *a):
        self.filters.append(("eq", a))
        return self

    def in_(self, *a):
        return self

    def ilike(self, *a):
        return self

    def gte(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a):
        return self

    def range(self, *a):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return self.ctrl._exec(self)


class _Ctrl:
    """Fake supabase — respuestas por (tabla, op); una excepción staged se
    lanza; registra todas las queries ejecutadas para inspección."""

    def __init__(self, responses):
        self.responses = responses
        self.calls: list[_Q] = []
        self.captured: dict[str, list] = {}

    def table(self, name):
        return _Q(name, self)

    def _exec(self, q: _Q):
        self.calls.append(q)
        if q.op == "insert":
            self.captured.setdefault(q.name, []).append(q.rows)
        staged = self.responses.get((q.name, q.op), [])
        if isinstance(staged, Exception):
            raise staged
        count = None
        if isinstance(staged, dict):
            return types.SimpleNamespace(data=staged.get("data"), count=staged.get("count"))
        return types.SimpleNamespace(data=staged, count=count)


def _actor() -> Actor:
    return Actor(channel=Channel.CONSOLE, tenant_id="t1", role=Role.MANAGER)


def _input(**kw) -> CreateOrderInput:
    kw.setdefault("payment_method", "credit")
    items = kw.pop(
        "items",
        (OrderItemInput(title="Prod", unit_price=100.0, quantity=2, variation_id="v1"),),
    )
    return CreateOrderInput(items=items, **kw)


_OK_INSERT = [{"id": "o-1", "tenant_id": "t1", "status": "pending", "total_amount": 200.0}]


def _base_responses(**over):
    r = {
        ("contacts", "select"): [{"id": "c-1"}],
        ("conversations", "select"): [{"id": "conv-1"}],
        ("product_variations", "select"): [{"id": "v1", "cost_price": 40.0}],
        ("conversation_carts", "select"): [],
        ("coupon_redemptions", "select"): [],
        ("orders", "insert"): _OK_INSERT,
        ("orders", "select"): _OK_INSERT,
        ("orders", "update"): [_OK_INSERT[0]],
        ("order_items", "insert"): [],
        ("order_items", "select"): [],
    }
    r.update(over)
    return r


# ─── create ──────────────────────────────────────────────────────────────────


class CreateOrderServiceTests(unittest.TestCase):
    def test_happy_path_total_recomputado_y_items_con_costo(self):
        ctrl = _Ctrl(_base_responses())
        result = svc.create_order(ctrl, tenant_id="t1", input=_input(), actor=_actor())

        insert = ctrl.captured["orders"][0]
        self.assertEqual(insert["total_amount"], 200.0)      # 100×2, sin descuento
        self.assertEqual(insert["status"], "pending")
        self.assertEqual(insert["payment_method"], "credit")
        self.assertEqual(insert["discount_amount"], 0.0)
        items = ctrl.captured["order_items"][0]
        self.assertEqual(items[0]["unit_cost"], 40.0)        # cost_price de la variante
        self.assertEqual(items[0]["quantity"], 2)
        self.assertEqual(result.http_status, 201)
        self.assertFalse(result.adopted_existing)
        self.assertEqual(result.events[0].name, "order.created")
        body = result.body()
        self.assertEqual(body["id"], "o-1")
        self.assertEqual(len(body["items"]), 1)
        self.assertNotIn("adopted_existing", body)

    def test_descuento_del_cart_vivo_llega_al_total(self):
        """F1: cart open con discount_cents + redención applied → descuento."""
        ctrl = _Ctrl(_base_responses() | {
            ("conversation_carts", "select"): [
                {"id": "cart-1", "status": "open", "discount_cents": 3000},
            ],
            ("coupon_redemptions", "select"): [{"id": "red-1"}],
        })
        result = svc.create_order(
            ctrl, tenant_id="t1", input=_input(conversation_id="conv-1"), actor=_actor(),
        )
        insert = ctrl.captured["orders"][0]
        self.assertEqual(insert["discount_amount"], 30.0)    # 3000 cents → $30
        self.assertEqual(insert["total_amount"], 170.0)      # 200 − 30

    def test_descuento_ignorado_si_redencion_no_viva(self):
        """BLOQUE A: cart con discount pero redención NO applied → sin descuento."""
        ctrl = _Ctrl(_base_responses() | {
            ("conversation_carts", "select"): [
                {"id": "cart-1", "status": "open", "discount_cents": 3000},
            ],
            ("coupon_redemptions", "select"): [],  # consumida/revocada
        })
        svc.create_order(ctrl, tenant_id="t1", input=_input(conversation_id="conv-1"), actor=_actor())
        insert = ctrl.captured["orders"][0]
        self.assertEqual(insert["discount_amount"], 0.0)
        self.assertEqual(insert["total_amount"], 200.0)

    def test_fk_contact_no_pertenece_al_tenant(self):
        ctrl = _Ctrl(_base_responses() | {("contacts", "select"): []})
        with self.assertRaises(DomainError) as ctx:
            svc.create_order(ctrl, tenant_id="t1", input=_input(contact_id="otro"), actor=_actor())
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)
        self.assertEqual(ctx.exception.message, "Contacto no encontrado en este tenant")
        self.assertNotIn("orders", ctrl.captured)  # nunca insertó

    def test_variation_no_pertenece_al_tenant(self):
        ctrl = _Ctrl(_base_responses() | {("product_variations", "select"): []})
        with self.assertRaises(DomainError) as ctx:
            svc.create_order(ctrl, tenant_id="t1", input=_input(), actor=_actor())
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)
        self.assertEqual(ctx.exception.message, "variation_id no pertenece a este tenant")

    def test_adopt_winner_en_23505(self):
        """B1: el insert perdedor adopta la orden ganadora (200 + marca)."""
        winner = {"id": "o-win", "tenant_id": "t1", "status": "pending_payment",
                  "conversation_id": "conv-1", "total_amount": 999.0}
        ctrl = _Ctrl(_base_responses() | {
            ("orders", "insert"): Exception(
                'duplicate key value violates unique constraint '
                '"uq_orders_one_pending_payment_per_conversation" (SQLSTATE 23505)'
            ),
            ("orders", "select"): [winner],
            ("order_items", "select"): [{"order_id": "o-win", "title": "X"}],
        })
        result = svc.create_order(
            ctrl, tenant_id="t1",
            input=_input(conversation_id="conv-1", payment_link=True), actor=_actor(),
        )
        self.assertTrue(result.adopted_existing)
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.order["id"], "o-win")
        self.assertEqual(result.events[0].name, "order.adopted_existing")
        # Nunca insertó items nuevos ni re-insertó la orden
        self.assertNotIn("order_items", ctrl.captured)

    def test_23505_sin_ganadora_propaga(self):
        ctrl = _Ctrl(_base_responses() | {
            ("orders", "insert"): Exception("duplicate key value ... (SQLSTATE 23505)"),
            ("orders", "select"): [],  # sin ganadora visible
        })
        with self.assertRaises(Exception) as ctx:
            svc.create_order(
                ctrl, tenant_id="t1",
                input=_input(conversation_id="conv-1", payment_link=True), actor=_actor(),
            )
        self.assertIn("23505", str(ctx.exception))

    def test_cod_crea_confirmada_y_dispara_stock(self):
        calls: list = []
        ctrl = _Ctrl(_base_responses())
        result = svc.create_order(
            ctrl, tenant_id="t1", input=_input(payment_method=PAYMENT_METHOD_COD),
            actor=_actor(), on_confirm_stock=lambda sb, oid, tid: calls.append((oid, tid)),
        )
        insert = ctrl.captured["orders"][0]
        self.assertEqual(insert["status"], "confirmed")  # COD bypass
        self.assertEqual(calls, [("o-1", "t1")])

    def test_auto_confirm_actualiza_estado_y_stock(self):
        calls: list = []
        ctrl = _Ctrl(_base_responses())
        result = svc.create_order(
            ctrl, tenant_id="t1", input=_input(auto_confirm=True), actor=_actor(),
            on_confirm_stock=lambda sb, oid, tid: calls.append(oid),
        )
        updates = [q for q in ctrl.calls if q.name == "orders" and q.op == "update"]
        self.assertEqual(updates[0].rows, {"status": "confirmed"})
        self.assertEqual(calls, ["o-1"])
        self.assertEqual(result.order["status"], "confirmed")

    def test_stock_hook_falla_no_tumba_la_creacion(self):
        """Best-effort heredado: el efecto de stock nunca falla la operación."""
        def _boom(sb, oid, tid):
            raise RuntimeError("stock down")

        ctrl = _Ctrl(_base_responses())
        with self.assertLogs("konvi_domain.orders.service", level="ERROR"):
            result = svc.create_order(
                ctrl, tenant_id="t1", input=_input(payment_method=PAYMENT_METHOD_COD),
                actor=_actor(), on_confirm_stock=_boom,
            )
        self.assertEqual(result.order["id"], "o-1")

    def test_insert_vacio_es_upstream(self):
        ctrl = _Ctrl(_base_responses() | {("orders", "insert"): []})
        with self.assertRaises(DomainError) as ctx:
            svc.create_order(ctrl, tenant_id="t1", input=_input(), actor=_actor())
        self.assertEqual(ctx.exception.code, ErrorCode.UPSTREAM)


# ─── get / list ──────────────────────────────────────────────────────────────


class ReadOrderServiceTests(unittest.TestCase):
    def test_get_devuelve_fila(self):
        ctrl = _Ctrl({("orders", "select"): [{"id": "o-1", "total_amount": 5.0}]})
        row = svc.get_order(ctrl, tenant_id="t1", order_id="o-1", actor=_actor())
        self.assertEqual(row["id"], "o-1")

    def test_get_no_encontrado_es_not_found_tipado(self):
        ctrl = _Ctrl({("orders", "select"): []})
        with self.assertRaises(DomainError) as ctx:
            svc.get_order(ctrl, tenant_id="t1", order_id="nope", actor=_actor())
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)
        self.assertEqual(ctx.exception.message, "Pedido no encontrado")

    def test_list_paginacion_conteos_y_filtro_estado(self):
        ctrl = _Ctrl({
            ("orders", "select"): {"data": [{"id": "o-1"}], "count": 7},
        })
        page = svc.list_orders(
            ctrl, tenant_id="t1", actor=_actor(), status="confirmed", limit=20, offset=40,
        )
        self.assertEqual(page.total, 7)
        self.assertEqual(page.orders, [{"id": "o-1"}])
        # counts: all + los 7 estados en orden de presentación
        self.assertEqual(
            list(page.counts.keys()),
            ["all", "pending", "pending_payment", "confirmed", "processing",
             "shipped", "delivered", "cancelled"],
        )
        # el list query aplicó el filtro de estado
        list_q = ctrl.calls[0]
        self.assertIn(("eq", ("status", "confirmed")), list_q.filters)

    def test_list_busqueda_sin_coincidencias_fuerza_vacio(self):
        ctrl = _Ctrl({
            ("contacts", "select"): [],  # q no matchea ningún contacto
            ("orders", "select"): {"data": [], "count": 0},
        })
        page = svc.list_orders(ctrl, tenant_id="t1", actor=_actor(), q="xyz")
        self.assertEqual(page.orders, [])
        self.assertEqual(page.total, 0)
        # guard con id imposible aplicado al list query
        list_q = [q for q in ctrl.calls if q.name == "orders" and q.count_requested][0]
        self.assertIn(
            ("eq", ("contact_id", "00000000-0000-0000-0000-000000000000")), list_q.filters,
        )

    def test_list_by_contact_filtra_por_contacto(self):
        ctrl = _Ctrl({("orders", "select"): [{"id": "o-9"}]})
        rows = svc.list_orders_by_contact(
            ctrl, tenant_id="t1", contact_id="c-9", actor=_actor(), since_days=15, limit=3,
        )
        self.assertEqual(rows, [{"id": "o-9"}])
        q = ctrl.calls[0]
        self.assertIn(("eq", ("tenant_id", "t1")), q.filters)
        self.assertIn(("eq", ("contact_id", "c-9")), q.filters)


if __name__ == "__main__":
    unittest.main()

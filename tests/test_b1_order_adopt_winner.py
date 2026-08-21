"""B1 (auditoría money-path 2026-08-21) — carrera de órdenes duplicadas por conversación.

Cubre el lado API del fix (services/api/routers/orders.py create_order +
migración 20260821120000_orders_one_pending_payment_per_conversation):

  • Insert que choca con el índice único parcial (23505) → ADOPT-WINNER:
    re-lee la orden ganadora y la devuelve (200 + adopted_existing), nunca
    duplica ni explota con 500.
  • 23505 sin orden ganadora visible → 500 (el conflicto era otro).
  • Error no-23505 → 500 (comportamiento previo intacto).
  • Carrera simulada con dos threads concurrentes → una sola orden creada,
    ambos callers reciben el MISMO order_id.
  • Idempotency-Key replay (G3): misma key + mismo payload → respuesta
    guardada, sin insert nuevo.
"""
import json
import os
import sys
import threading
import types
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from dependencies.idempotency import payload_fingerprint  # noqa: E402
from routers import orders as orders_mod  # noqa: E402
from routers.orders import OrderCreate, OrderItemCreate  # noqa: E402

_REQ = types.SimpleNamespace(
    headers={}, method="POST", url=types.SimpleNamespace(path="/api/v1/orders/"),
)

_WINNER_ID = "11111111-2222-3333-4444-555555555555"
_23505 = (
    'duplicate key value violates unique constraint '
    '"uq_orders_one_pending_payment_per_conversation" (SQLSTATE 23505)'
)


class _Q:
    """Query chain mínima (patrón tests/test_order_discount_coherence.py)."""

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

    def delete(self, *a, **k):
        self.op = "delete"
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
    """Fake supabase por (tabla, op). El valor puede ser:

      • list              → data de la respuesta
      • Exception         → se levanta en execute()
      • callable(q)       → computa la respuesta (o levanta)
    """

    def __init__(self, responses):
        self.responses = responses
        self.captured = {}

    def table(self, name):
        return _Q(name, self)

    def _exec(self, q):
        if q.op == "insert":
            self.captured.setdefault(q.name, []).append(q.rows)
        handler = self.responses.get((q.name, q.op), [])
        if callable(handler):
            handler = handler(q)
        if isinstance(handler, Exception):
            raise handler
        return types.SimpleNamespace(data=handler)


def _payload(**kw):
    kw.setdefault("payment_link", True)
    kw.setdefault("payment_method", "credit")
    kw.setdefault("conversation_id", "conv-1")
    return OrderCreate(
        items=[OrderItemCreate(title="Prod", unit_price=100.0, quantity=1)],
        **kw,
    )


def _create(ctrl, payload, request=_REQ):
    return orders_mod.create_order(
        order=payload, request=request, tenant_id="t1", supabase=ctrl,
        _role="manager",
    )


class CreateOrderAdoptWinnerTests(unittest.TestCase):
    """El insert perdedor (23505) adopta la orden ganadora — nunca duplica."""

    def test_23505_adopts_winner_order(self):
        ctrl = _Ctrl({
            ("conversation_carts", "select"): [],
            ("conversations", "select"): [{"id": "conv-1"}],
            ("orders", "insert"): Exception(_23505),
            ("orders", "select"): [{
                "id": _WINNER_ID, "tenant_id": "t1", "status": "pending_payment",
                "total_amount": 100.0, "conversation_id": "conv-1",
                "created_at": "2026-08-21T10:00:00+00:00",
            }],
            ("order_items", "select"): [{
                "order_id": _WINNER_ID, "title": "Prod", "quantity": 1,
                "unit_price": 100.0,
            }],
        })
        result = _create(ctrl, _payload())
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 200)
        body = json.loads(bytes(result.body))
        self.assertEqual(body["id"], _WINNER_ID)
        self.assertTrue(body["adopted_existing"])
        self.assertEqual(len(body["items"]), 1)
        # El perdedor NO insertó items nuevos sobre la orden ganadora.
        self.assertNotIn("order_items", ctrl.captured)

    def test_23505_without_visible_winner_raises_500(self):
        ctrl = _Ctrl({
            ("conversation_carts", "select"): [],
            ("conversations", "select"): [{"id": "conv-1"}],
            ("orders", "insert"): Exception(_23505),
            ("orders", "select"): [],  # ganadora ya confirmada/cancelada
        })
        with self.assertRaises(HTTPException) as ctx:
            _create(ctrl, _payload())
        self.assertEqual(ctx.exception.status_code, 500)

    def test_non_duplicate_insert_error_raises_500(self):
        ctrl = _Ctrl({
            ("conversation_carts", "select"): [],
            ("conversations", "select"): [{"id": "conv-1"}],
            ("orders", "insert"): Exception("connection reset by peer"),
        })
        with self.assertRaises(HTTPException) as ctx:
            _create(ctrl, _payload())
        self.assertEqual(ctx.exception.status_code, 500)

    def test_happy_path_sin_conflicto_crea_201(self):
        """Control: sin 23505 el flujo es el de siempre (dict + items)."""
        ctrl = _Ctrl({
            ("conversation_carts", "select"): [],
            ("conversations", "select"): [{"id": "conv-1"}],
            ("orders", "insert"): [{"id": "order-new", "status": "pending_payment"}],
            ("order_items", "insert"): [{"id": "oi-1"}],
        })
        result = _create(ctrl, _payload())
        self.assertIsInstance(result, dict)
        self.assertEqual(result["id"], "order-new")
        self.assertNotIn("adopted_existing", result)


class CreateOrderRaceTests(unittest.TestCase):
    """Carrera simulada: dos llamadas concurrentes → una sola orden.

    El fake fuerza el solape real de ambos inserts con una barrera: el primero
    commitea, el segundo recibe 23505 (lo que haría el índice único parcial en
    Postgres) y cae al adopt-winner.
    """

    def test_dos_llamadas_concurrentes_una_sola_orden(self):
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        committed = []

        def _insert_orders(q):
            barrier.wait(timeout=10)
            with lock:
                if not committed:
                    committed.append(q.rows)
                    return [{
                        "id": _WINNER_ID, "status": "pending_payment",
                        "total_amount": 100.0, "conversation_id": "conv-race",
                    }]
            raise Exception(_23505)

        ctrl = _Ctrl({
            ("conversation_carts", "select"): [],
            ("conversations", "select"): [{"id": "conv-race"}],
            ("orders", "insert"): _insert_orders,
            ("orders", "select"): [{
                "id": _WINNER_ID, "tenant_id": "t1", "status": "pending_payment",
                "total_amount": 100.0, "conversation_id": "conv-race",
                "created_at": "2026-08-21T10:00:00+00:00",
            }],
            ("order_items", "select"): [],
            ("order_items", "insert"): [{"id": "oi-1"}],
        })

        results, errors = {}, {}

        def _worker(tag):
            try:
                results[tag] = _create(ctrl, _payload(conversation_id="conv-race"))
            except Exception as exc:  # noqa: BLE001
                errors[tag] = exc

        t1 = threading.Thread(target=_worker, args=("A",))
        t2 = threading.Thread(target=_worker, args=("B",))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        self.assertEqual(errors, {})
        self.assertEqual(len(committed), 1, "solo un insert pudo commitear")

        ids = set()
        adopted_flags = []
        for res in results.values():
            if isinstance(res, JSONResponse):
                body = json.loads(bytes(res.body))
                adopted_flags.append(body.get("adopted_existing"))
            else:
                body = res
                adopted_flags.append(body.get("adopted_existing"))
            ids.add(body["id"])
        self.assertEqual(ids, {_WINNER_ID}, "ambos callers reciben la MISMA orden")
        self.assertEqual(
            sorted(map(bool, adopted_flags)), [False, True],
            "exactamente un caller creó; el otro adoptó",
        )


class CreateOrderIdempotencyReplayTests(unittest.TestCase):
    """G3: misma Idempotency-Key + mismo payload → replay exacto, sin insert."""

    def test_replay_devuelve_respuesta_guardada_sin_insert(self):
        payload = _payload()
        key = "ordc:conv-1:abcdef1234567890"
        req = types.SimpleNamespace(
            headers={"Idempotency-Key": key}, method="POST",
            url=types.SimpleNamespace(path="/api/v1/orders/"),
        )
        stored_body = {"id": "order-stored", "status": "pending_payment", "items": []}
        ctrl = _Ctrl({
            ("idempotency_keys", "select"): [{
                "id": "ik-1",
                "request_hash": payload_fingerprint(payload.model_dump(mode="json")),
                "response_status": 201,
                "response_body": stored_body,
            }],
        })
        result = _create(ctrl, payload, request=req)
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.headers.get("Idempotency-Replayed"), "true")
        body = json.loads(bytes(result.body))
        self.assertEqual(body["id"], "order-stored")
        self.assertNotIn("orders", ctrl.captured, "replay NO inserta orden nueva")


if __name__ == "__main__":
    unittest.main()

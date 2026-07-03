"""F42 (CRÍTICO dinero) — al reutilizar una orden pending_payment cuyo monto quedó STALE (el cliente
aplicó un cupón o cambió de carrier DESPUÉS de generar el link), NO se debe cobrar el monto viejo:
se invalida la orden vieja (cancel + void payments) y el flujo crea una nueva con el monto correcto.

Test del helper crítico _invalidate_stale_pending_order (cancela por order_id con CAS + void payments).
"""
import os
import sys
import types
import unittest

os.environ.setdefault("INTERNAL_SERVICE_SECRET", "internal-secret")
os.environ.setdefault("API_URL", "http://localhost:8001")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools import payment_link_tool  # noqa: E402


class _Chain:
    def __init__(self, table, sink):
        self._t = table
        self._sink = sink
        self._payload = None
        self._filters = {}

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        self._sink.append((self._t, self._payload, self._filters))
        return types.SimpleNamespace(data=[{"id": "x"}])


class _FakeSb:
    def __init__(self):
        self.calls = []  # (table, payload, filters)

    def table(self, name):
        return _Chain(name, self.calls)


class F42InvalidateStalePendingOrderTests(unittest.TestCase):
    def test_cancels_order_and_voids_payments(self):
        sb = _FakeSb()
        payment_link_tool._invalidate_stale_pending_order(sb, "order-9", "tenant-1")

        orders = [c for c in sb.calls if c[0] == "orders"]
        payments = [c for c in sb.calls if c[0] == "payments"]
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(payments), 1)

        # Orden: cancelada con CAS por status='pending_payment' (no pisa una ya confirmada).
        _, o_payload, o_filters = orders[0]
        self.assertEqual(o_payload["status"], "cancelled")
        self.assertEqual(o_filters["id"], "order-9")
        self.assertEqual(o_filters["tenant_id"], "tenant-1")
        self.assertEqual(o_filters["status"], "pending_payment")

        # Payments: pending → voided, scoped por order + tenant.
        _, p_payload, p_filters = payments[0]
        self.assertEqual(p_payload["status"], "voided")
        self.assertEqual(p_filters["order_id"], "order-9")
        self.assertEqual(p_filters["tenant_id"], "tenant-1")
        self.assertEqual(p_filters["status"], "pending")


if __name__ == "__main__":
    unittest.main()

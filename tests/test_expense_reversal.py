"""
BLOQUE F-4 — endpoint de anulación (soft-void) de gastos: POST /expenses/{id}/reverse.

La UI (server action reverseExpense) ya lo llamaba pero NO existía → 404. Verifica:
  · owner + gasto vigente → 200, setea reversed_at/by/reason (trail).
  · non-owner → 403.  · gasto inexistente → 404.  · gasto ya anulado → 409.  · motivo corto → 422.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routers.expenses as expenses  # noqa: E402
from dependencies.auth import (  # noqa: E402
    get_current_role, get_current_tenant, get_current_user_id, get_service_client,
)
from dependencies.internal_auth import (  # noqa: E402
    get_service_client_internal_or_user,
    get_tenant_id_internal_or_user,
)

TENANT = "tenant-1"
USER = "user-9"


class _Q:
    def __init__(self, rows):
        self.rows = rows
        self._op = "select"
        self._f = {}
        self._single = False
        self._isnull = None
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, c, v):
        self._f[c] = v
        return self

    def is_(self, c, _v):
        self._isnull = c
        return self

    def maybe_single(self):
        self._single = True
        return self

    def _match(self, r):
        ok = all(r.get(c) == v for c, v in self._f.items())
        if self._isnull is not None:
            ok = ok and r.get(self._isnull) is None
        return ok
    def execute(self):
        matched = [r for r in self.rows if self._match(r)]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return SimpleNamespace(data=[dict(r) for r in matched])
        if self._single:
            return SimpleNamespace(data=(dict(matched[0]) if matched else None))
        return SimpleNamespace(data=[dict(r) for r in matched])


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
    def table(self, _name):
        return _Q(self.rows)


def _client(role, rows):
    app = FastAPI()
    app.include_router(expenses.router, prefix="/api/v1/expenses")
    fake = _FakeSupabase(rows)
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    app.dependency_overrides[get_service_client] = lambda: fake
    app.dependency_overrides[get_current_role] = lambda: role
    app.dependency_overrides[get_current_user_id] = lambda: USER
    # M15 (2026-08-02): reverse ganó RL_WRITE_DEFAULT; la dep de rate-limit
    # resuelve tenant/cliente vía dual-auth (A0.2c) → mismo override que las
    # deps JWT para que el test siga midiendo SOLO la lógica del endpoint.
    app.dependency_overrides[get_tenant_id_internal_or_user] = lambda: TENANT
    app.dependency_overrides[get_service_client_internal_or_user] = lambda: fake
    return TestClient(app, raise_server_exceptions=False), fake


def _expense(reversed_at=None):
    return {"id": "exp-1", "tenant_id": TENANT, "amount": 100, "reversed_at": reversed_at}


class ExpenseReversalTest(unittest.TestCase):
    def test_owner_reverses_active_expense(self):
        c, fake = _client("owner", [_expense()])
        r = c.post("/api/v1/expenses/exp-1/reverse", json={"reason": "duplicado"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(fake.rows[0]["reversed_at"])
        self.assertEqual(fake.rows[0]["reversed_by"], USER)
        self.assertEqual(fake.rows[0]["reversal_reason"], "duplicado")

    def test_non_owner_forbidden(self):
        for role in ("manager", "operator"):
            c, _ = _client(role, [_expense()])
            r = c.post("/api/v1/expenses/exp-1/reverse", json={"reason": "duplicado"})
            self.assertEqual(r.status_code, 403, role)

    def test_not_found(self):
        c, _ = _client("owner", [])
        r = c.post("/api/v1/expenses/nope/reverse", json={"reason": "duplicado"})
        self.assertEqual(r.status_code, 404)

    def test_already_reversed_409(self):
        c, _ = _client("owner", [_expense(reversed_at="2026-07-01T00:00:00Z")])
        r = c.post("/api/v1/expenses/exp-1/reverse", json={"reason": "duplicado"})
        self.assertEqual(r.status_code, 409)

    def test_reason_too_short_422(self):
        c, _ = _client("owner", [_expense()])
        r = c.post("/api/v1/expenses/exp-1/reverse", json={"reason": "x"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()

"""
BLOQUE F (F-1/F-2) — RBAC owner-only de finanzas.

Verifica que los GET de purchases (costos/márgenes) y el POST de expenses (crear gasto) exigen
OWNER: manager/operator → 403; owner → OK. (La RLS owner-only de las lecturas directas se cubre
en la migración 20260711120000; aquí se prueba el guard de la API.)
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routers.purchases as purchases  # noqa: E402
import routers.expenses as expenses  # noqa: E402
from dependencies.auth import get_current_role, get_current_tenant, get_service_client  # noqa: E402
from dependencies.internal_auth import (  # noqa: E402
    get_service_client_internal_or_user,
    get_tenant_id_internal_or_user,
)

TENANT = "tenant-1"


class _Q:
    def __init__(self, data):
        self._data = data
    def __getattr__(self, _name):
        # Cualquier método de la cadena (select/eq/order/limit/insert/...) retorna self.
        return lambda *a, **k: self
    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, data):
        self._data = data
    def table(self, _name):
        return _Q(self._data)


def _client(router, prefix, role, data):
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    app.dependency_overrides[get_service_client] = lambda: _FakeSupabase(data)
    app.dependency_overrides[get_current_role] = lambda: role
    # M15 (2026-08-02): expenses ganó RL_WRITE_DEFAULT; la dep de rate-limit
    # resuelve tenant/cliente vía dual-auth (A0.2c) → mismo override que las
    # deps JWT para que el test siga midiendo SOLO el guard RBAC.
    app.dependency_overrides[get_tenant_id_internal_or_user] = lambda: TENANT
    app.dependency_overrides[get_service_client_internal_or_user] = lambda: _FakeSupabase(data)
    return TestClient(app, raise_server_exceptions=False)


class FinanceRbacTest(unittest.TestCase):
    def test_purchases_get_suppliers_forbidden_for_non_owner(self):
        for role in ("manager", "operator"):
            c = _client(purchases.router, "/api/v1/purchases", role, [])
            r = c.get("/api/v1/purchases/suppliers")
            self.assertEqual(r.status_code, 403, f"role={role} debe ser 403 en GET suppliers")

    def test_purchases_get_suppliers_ok_for_owner(self):
        c = _client(purchases.router, "/api/v1/purchases", "owner", [])
        r = c.get("/api/v1/purchases/suppliers")
        self.assertEqual(r.status_code, 200)

    def test_purchases_list_pos_forbidden_for_non_owner(self):
        c = _client(purchases.router, "/api/v1/purchases", "manager", [])
        r = c.get("/api/v1/purchases/")
        self.assertEqual(r.status_code, 403)

    def test_expenses_create_forbidden_for_manager(self):
        c = _client(expenses.router, "/api/v1/expenses", "manager", [{"id": "e1"}])
        r = c.post("/api/v1/expenses/", json={"category": "x", "description": "y", "amount": 10})
        self.assertEqual(r.status_code, 403, "crear gasto debe ser owner-only (antes permitía manager)")

    def test_expenses_create_ok_for_owner(self):
        c = _client(expenses.router, "/api/v1/expenses", "owner", [{"id": "e1"}])
        r = c.post("/api/v1/expenses/", json={"category": "x", "description": "y", "amount": 10})
        # owner pasa el guard (el objetivo es que NO sea 403).
        self.assertNotEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()

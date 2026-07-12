"""
BLOQUE G-4 (decisión founder) — crear reclamos es owner/manager/OPERATOR.

Antes create_claim exigía require_write_role → el operator veía «Nuevo Reclamo» (la UI
lo expone: canWrite incluye operator) pero recibía 403. Se quitó el guard para alinear
la API con la UI. RESOLVER/reembolsar sigue restringido (owner/manager).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routers.claims as claims  # noqa: E402
from dependencies.auth import (  # noqa: E402
    get_current_role, get_current_tenant, get_service_client,
)
from dependencies.security import RL_WRITE_DEFAULT  # noqa: E402

TENANT = "tenant-1"
ORDER = {"id": "o1", "tenant_id": TENANT, "contact_id": "c1", "status": "delivered"}


class _Q:
    def __init__(self, name):
        self.name = name
        self._op = "select"
        self._payload = None
        self._single = False

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if self._op == "insert":
            return SimpleNamespace(data=[{**self._payload, "id": "cl-new"}])
        if self.name == "orders":
            return SimpleNamespace(data=(dict(ORDER) if self._single else [dict(ORDER)]))
        return SimpleNamespace(data=[])


class _FakeSB:
    def table(self, name):
        return _Q(name)


def _client(role):
    app = FastAPI()
    app.include_router(claims.router, prefix="/api/v1/claims")
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    app.dependency_overrides[get_service_client] = lambda: _FakeSB()
    app.dependency_overrides[get_current_role] = lambda: role
    app.dependency_overrides[RL_WRITE_DEFAULT] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


class ClaimCreateRbacTest(unittest.TestCase):
    def test_operator_can_create_claim(self):
        c = _client("operator")
        r = c.post("/api/v1/claims/", json={"order_id": "o1", "reason": "defective"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["status"], "open")

    def test_owner_and_manager_can_create_claim(self):
        for role in ("owner", "manager"):
            c = _client(role)
            r = c.post("/api/v1/claims/", json={"order_id": "o1", "reason": "wrong_item"})
            self.assertEqual(r.status_code, 201, f"{role}: {r.text}")


if __name__ == "__main__":
    unittest.main()

"""
BLOQUE G-2 — captura del monto REAL reembolsado en el reclamo (refund ledger).

patch_claim, al pasar un reclamo a 'refunded':
  · exige refunded_amount (sin él → 422); antes solo requested_amount (intención) existía.
  · lo persiste + refunded_at (write-once) → el KPI net-revenue resta esto, no requested_amount.
  · 'refunded' es FINAL: refunded→resolved (o cualquier otro) → 409 (antes pasaba y sacaba
    el reembolso del neteo).
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


class _Q:
    def __init__(self, store):
        self.store = store
        self._op = "select"
        self._payload = None
        self._single = False

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if self._op == "update":
            self.store.update(self._payload)
            return SimpleNamespace(data=[dict(self.store)])
        return SimpleNamespace(data=(dict(self.store) if self._single else [dict(self.store)]))


class _FakeSB:
    def __init__(self, store):
        self.store = store
    def table(self, _name):
        return _Q(self.store)


def _client(role, claim_store):
    app = FastAPI()
    app.include_router(claims.router, prefix="/api/v1/claims")
    fake = _FakeSB(claim_store)
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    app.dependency_overrides[get_service_client] = lambda: fake
    app.dependency_overrides[get_current_role] = lambda: role
    app.dependency_overrides[RL_WRITE_DEFAULT] = lambda: None  # bypass rate-limit en test
    return TestClient(app, raise_server_exceptions=False), claim_store


def _claim(status):
    return {"id": "cl1", "tenant_id": TENANT, "status": status,
            "order_id": "o1", "requested_amount": 500}


class ClaimRefundCaptureTest(unittest.TestCase):
    def test_refunded_requires_amount(self):
        c, _ = _client("manager", _claim("resolved"))
        r = c.patch("/api/v1/claims/cl1", json={"status": "refunded"})
        self.assertEqual(r.status_code, 422)

    def test_refunded_captures_amount_and_date(self):
        c, store = _client("manager", _claim("investigating"))
        r = c.patch("/api/v1/claims/cl1", json={"status": "refunded", "refunded_amount": 300})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(store["refunded_amount"], 300)
        self.assertIsNotNone(store.get("refunded_at"))
        self.assertEqual(store["status"], "refunded")

    def test_refunded_is_final_cannot_change(self):
        for target in ("resolved", "rejected", "open"):
            c, _ = _client("owner", _claim("refunded"))
            r = c.patch("/api/v1/claims/cl1", json={"status": target})
            self.assertEqual(r.status_code, 409, target)

    def test_non_refund_transition_unaffected(self):
        # resolved no exige refunded_amount.
        c, store = _client("manager", _claim("investigating"))
        r = c.patch("/api/v1/claims/cl1", json={"status": "resolved"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(store["status"], "resolved")
        self.assertIsNone(store.get("refunded_at"))

    def test_resolve_shortcut_cannot_override_refunded(self):
        # Review HIGH: POST /resolve era puerta lateral que sacaba el reembolso del neteo.
        c, store = _client("owner", _claim("refunded"))
        r = c.post("/api/v1/claims/cl1/resolve", json={"resolution_notes": "cerrar"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(store["status"], "refunded")  # sin mutar

    def test_correction_sets_amount_when_null(self):
        # Backfill histórico sin monto → path de corrección (PATCH solo refunded_amount).
        store = _claim("refunded")
        store["refunded_amount"] = None
        c, s = _client("manager", store)
        r = c.patch("/api/v1/claims/cl1", json={"refunded_amount": 250})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(s["refunded_amount"], 250)
        self.assertEqual(s["status"], "refunded")  # status intacto

    def test_correction_blocked_when_amount_present(self):
        # Write-once: si ya hay monto, no se re-escribe.
        store = _claim("refunded")
        store["refunded_amount"] = 100
        c, _ = _client("manager", store)
        r = c.patch("/api/v1/claims/cl1", json={"refunded_amount": 999})
        self.assertEqual(r.status_code, 409)

    def test_correction_rejected_on_non_refunded(self):
        c, _ = _client("manager", _claim("investigating"))
        r = c.patch("/api/v1/claims/cl1", json={"refunded_amount": 250})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()

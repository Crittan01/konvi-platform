"""Regresión A11 audit (2026-06-25) — red de seguridad para la Clase B.

La Clase B (dual-auth incompleto) pasó a producción porque NINGÚN test cubría el
path internal-service-secret a través de las dependencias TRANSVERSALES
(offboarding gate, rate-limit, plan-gating). Esos deps resolvían tenant/cliente
vía get_current_tenant/get_service_client (JWT-only) → toda llamada
service-to-service del orchestrator recibía 401 ANTES del internal-auth del
endpoint.

Este test ejercita la resolución de dependencias REAL de FastAPI (donde vivía el
bug — no se reproduce llamando las funciones directamente) con headers
internal-service, y asegura que TODAS las deps transversales lo aceptan.

Aislamiento: NO mutamos os.environ a nivel módulo (filtraría a otros tests).
Las flags/secret se parchean con `patch` scoped a cada test.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from dependencies.internal_auth import (  # noqa: E402
    get_tenant_id_internal_or_user,
    require_write_internal_or_user,
)
from dependencies.auth import reject_if_tenant_deleting  # noqa: E402
from dependencies.security import RL_WRITE_DEFAULT  # noqa: E402
from dependencies.plans import PLAN_ORDERS_CREATE  # noqa: E402

SECRET = "test-internal-secret-xyz"
TENANT = "tenant-abc"


def _make_app():
    """App con EXACTAMENTE el stack de deps transversales de un endpoint de
    escritura (orders POST): router-gate offboarding + tenant + role + rate-limit
    + plan — todas deben aceptar el path internal-service."""
    app = FastAPI()

    @app.post("/probe", dependencies=[Depends(reject_if_tenant_deleting)])
    async def probe(  # noqa: ANN201
        tenant_id: str = Depends(get_tenant_id_internal_or_user),
        _role: str = Depends(require_write_internal_or_user),
        _rl: None = Depends(RL_WRITE_DEFAULT),
        _plan: object = Depends(PLAN_ORDERS_CREATE),
    ):
        return {"tenant_id": tenant_id}

    return app


def _fake_sc_tenant_not_deleting():
    """Service client falso para el offboarding gate: tenants query → 0 rows
    (tenant no en deletion) → el gate retorna tenant_id."""
    sb = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = SimpleNamespace(data=[])
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value = chain
    return sb


# Patches scoped (NO leak): secret no vacío + enforcement off (los bodies de
# rate-limit/plan cortocircuitan, pero sus Depends igual se resuelven — que es
# justo lo que probamos).
def _scoped(fn):
    fn = patch("dependencies.internal_auth.INTERNAL_SERVICE_SECRET", SECRET)(fn)
    fn = patch("dependencies.plans.PLAN_ENFORCEMENT_ENABLED", False)(fn)
    fn = patch("dependencies.security.RATE_LIMIT_ENABLED", False)(fn)
    return fn


class DualAuthInternalServiceTests(unittest.TestCase):
    @_scoped
    @patch("dependencies.auth._get_service_client")
    def test_internal_service_secret_passes_all_cross_cutting_deps(self, mock_sc):
        """Con X-Internal-Service-Secret + X-Tenant-Id válidos, las 4 deps
        transversales resuelven sin 401 (el bug Clase B daba 401 aquí)."""
        mock_sc.return_value = _fake_sc_tenant_not_deleting()
        client = TestClient(_make_app(), raise_server_exceptions=False)
        resp = client.post(
            "/probe",
            json={},
            headers={"X-Internal-Service-Secret": SECRET, "X-Tenant-Id": TENANT},
        )
        self.assertEqual(resp.status_code, 200,
                         f"internal-service debe pasar el stack de deps; body={resp.text}")
        self.assertEqual(resp.json().get("tenant_id"), TENANT)

    @_scoped
    def test_no_auth_returns_401(self):
        """Sin secret ni JWT → 401 (el path JWT no encuentra Authorization)."""
        client = TestClient(_make_app(), raise_server_exceptions=False)
        resp = client.post("/probe", json={})
        self.assertEqual(resp.status_code, 401)

    @_scoped
    @patch("dependencies.auth._get_service_client")
    def test_wrong_secret_falls_through_to_jwt_401(self, mock_sc):
        """Secret incorrecto → no pasa internal → cae a JWT → 401 (no bypass)."""
        mock_sc.return_value = _fake_sc_tenant_not_deleting()
        client = TestClient(_make_app(), raise_server_exceptions=False)
        resp = client.post(
            "/probe",
            json={},
            headers={"X-Internal-Service-Secret": "WRONG", "X-Tenant-Id": TENANT},
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()

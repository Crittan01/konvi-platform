"""A12 (auditoría 2026-08-02) — audit trail del path dual-auth internal-secret.

Antes: una llamada con `X-Internal-Service-Secret` válido + `X-Tenant-Id`
AUTODECLARADO actuaba como cualquier tenant con rol owner sin dejar rastro.
Ahora `get_tenant_id_internal_or_user` registra cada llamada internal
autenticada en `api_security_events` (vía `record_api_security_event`, el mismo
helper fail-open del rate-limit): tenant declarado, path, método, resultado.

Reglas cubiertas:
  · secret + tenant UUID → retorna tenant + evento `internal_auth.ok` (200).
  · secret + tenant NO-UUID → retorna tenant PERO sin fila (guard FK tenants).
  · secret válido sin X-Tenant-Id → 400 (sin fila posible: tenant NOT NULL FK).
  · fallo del registro → NUNCA rompe la request (best-effort).
  · sin secret → cae al flujo JWT (`get_current_tenant`), sin evento internal.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi import HTTPException  # noqa: E402
from dependencies import internal_auth as I  # noqa: E402

SECRET = "test-internal-secret-xyz"
TENANT_UUID = "11111111-1111-1111-1111-111111111111"


def _req(headers, path="/api/v1/orders", method="POST"):
    """Request mínimo: headers + url.path + method (lo que el audit lee)."""
    r = MagicMock()
    r.headers = headers
    r.url = MagicMock(path=path)
    r.method = method
    return r


def _call(req):
    return asyncio.new_event_loop().run_until_complete(
        I.get_tenant_id_internal_or_user(req),
    )


class InternalAuthAuditTests(unittest.TestCase):
    def setUp(self):
        self._old = I.INTERNAL_SERVICE_SECRET
        I.INTERNAL_SERVICE_SECRET = SECRET

    def tearDown(self):
        I.INTERNAL_SERVICE_SECRET = self._old

    @patch("dependencies.observability.record_api_security_event")
    @patch("dependencies.internal_auth._get_service_client")
    def test_llamada_internal_registra_evento_ok(self, mock_sc, mock_rec):
        tid = _call(_req({
            "X-Internal-Service-Secret": SECRET,
            "X-Tenant-Id": TENANT_UUID,
            "user-agent": "python-httpx/0.28",
        }))
        self.assertEqual(tid, TENANT_UUID)
        mock_rec.assert_called_once()
        kw = mock_rec.call_args.kwargs
        self.assertEqual(kw["tenant_id"], TENANT_UUID)
        self.assertEqual(kw["event_type"], "internal_auth.ok")
        self.assertEqual(kw["status_code"], 200)
        self.assertEqual(kw["metadata"]["auth"], "internal_secret")
        self.assertEqual(kw["metadata"]["user_agent"], "python-httpx/0.28")

    @patch("dependencies.observability.record_api_security_event")
    @patch("dependencies.internal_auth._get_service_client")
    def test_tenant_no_uuid_no_inserta_fila(self, mock_sc, mock_rec):
        # El header se honra (comportamiento previo) pero la fila exige UUID
        # válido (FK api_security_events.tenant_id → tenants) → skip del insert.
        tid = _call(_req({
            "X-Internal-Service-Secret": SECRET,
            "X-Tenant-Id": "tenant-abc",
        }))
        self.assertEqual(tid, "tenant-abc")
        mock_rec.assert_not_called()

    @patch("dependencies.observability.record_api_security_event")
    @patch("dependencies.internal_auth._get_service_client")
    def test_secret_sin_tenant_400_con_log(self, mock_sc, mock_rec):
        with self.assertLogs("dependencies.internal_auth", level="WARNING") as cm:
            with self.assertRaises(HTTPException) as ctx:
                _call(_req({"X-Internal-Service-Secret": SECRET}))
        self.assertEqual(ctx.exception.status_code, 400)
        mock_rec.assert_not_called()
        self.assertTrue(any("SIN X-Tenant-Id" in m for m in cm.output))

    @patch("dependencies.observability.record_api_security_event")
    @patch("dependencies.internal_auth._get_service_client")
    def test_fallo_de_auditoria_no_rompe_la_request(self, mock_sc, mock_rec):
        mock_rec.side_effect = RuntimeError("db down")
        tid = _call(_req({
            "X-Internal-Service-Secret": SECRET,
            "X-Tenant-Id": TENANT_UUID,
        }))
        self.assertEqual(tid, TENANT_UUID)  # fail-open: la request siguió

    @patch("dependencies.observability.record_api_security_event")
    @patch("dependencies.internal_auth.get_current_tenant",
           new=AsyncMock(return_value="jwt-tenant"))
    def test_sin_secret_cae_a_jwt_sin_evento_internal(self, mock_rec):
        tid = _call(_req({}))
        self.assertEqual(tid, "jwt-tenant")
        mock_rec.assert_not_called()


if __name__ == "__main__":
    unittest.main()

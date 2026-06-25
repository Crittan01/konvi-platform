"""Regresión A11 audit — /agentic/metrics requiere auth + tenant_id.

Antes: endpoint público (Render lo sirve) con tenant_id opcional → dump de
métricas operativas cross-tenant sin autenticación. Fix: exige
X-Internal-Service-Secret + tenant_id obligatorio.

Se invoca el handler directamente (no TestClient) para no disparar el startup
event que lanzaría un worker real contra Supabase.
"""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SENTRY_DSN", "")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402

SECRET = "test-internal-secret"


class _Req:
    def __init__(self, secret=None):
        self.headers = {"X-Internal-Service-Secret": secret} if secret else {}


class MetricsAuthTests(unittest.TestCase):
    def test_no_secret_401(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", SECRET):
            with self.assertRaises(HTTPException) as ctx:
                server.agentic_metrics(_Req(), tenant_id="t1")
            self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_secret_401(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", SECRET):
            with self.assertRaises(HTTPException) as ctx:
                server.agentic_metrics(_Req("WRONG"), tenant_id="t1")
            self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_secret_missing_tenant_400(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", SECRET):
            with self.assertRaises(HTTPException) as ctx:
                server.agentic_metrics(_Req(SECRET), tenant_id=None)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_valid_secret_and_tenant_passes_auth(self):
        # Con secret + tenant_id válidos pasa los gates y llega a la lógica;
        # parcheamos el cómputo para no tocar DB → 200.
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", SECRET), \
             patch("agentic.observability.compute_agentic_metrics", return_value={"ok": True}):
            resp = server.agentic_metrics(_Req(SECRET), tenant_id="t1")
            self.assertEqual(getattr(resp, "status_code", None), 200)

    def test_empty_configured_secret_denies_all(self):
        # Defensa: si el secret no está configurado, NO se abre el endpoint.
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", ""):
            with self.assertRaises(HTTPException) as ctx:
                server.agentic_metrics(_Req("anything"), tenant_id="t1")
            self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()

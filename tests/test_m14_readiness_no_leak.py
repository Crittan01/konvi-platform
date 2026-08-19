"""M14 (auditoría 2026-08-02) — /health/ready sin leak de errores internos.

El endpoint es PÚBLICO (sin auth — lo golpea Render). Ante una DB caída
devolvía `detail=str(exc)[:200]`: mensajes internos de PostgREST/DB (host,
schema, hints de conexión) expuestos a cualquier cliente.

Fix: detalle genérico es-CO ("dependencia no disponible") hacia afuera; el
error completo queda en logs (warning truncado a 500 chars).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))


def _api_main():
    """Import robusto del main de la API (ver test_b0_mfa_gateway_enforce).

    El guard debe chequear `readiness_check` (no solo `.app`): el connector
    TAMBIÉN tiene `.app` — si otro test importó `main` del connector en este
    worker (o el sys.path[0] ya no es services/api al momento de re-importar),
    `.app` pasa y el test revienta con AttributeError (flake bajo xdist).
    """
    _m = sys.modules.get("main")
    if _m is None or not hasattr(_m, "readiness_check"):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
        sys.modules.pop("main", None)
        import main as _m
    return _m


class ReadinessNoLeakTests(unittest.TestCase):
    @patch("dependencies.auth._get_service_client")
    def test_db_caida_detalle_generico_sin_internos(self, mock_sc):
        mock_sc.side_effect = RuntimeError(
            "postgrest://db.xxx.supabase.co:5432 connection refused password=secret"
        )
        main = _api_main()
        response = MagicMock()
        body = main.readiness_check(response)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["checks"]["database"], "fail")
        self.assertEqual(body["detail"], "dependencia no disponible")
        # El mensaje interno NO se filtra en ningún campo del body.
        self.assertNotIn("postgrest", str(body))
        self.assertNotIn("5432", str(body))
        self.assertNotIn("password", str(body))

    @patch("dependencies.auth._get_service_client")
    def test_db_ok_ready_sin_detail(self, mock_sc):
        main = _api_main()
        response = MagicMock()
        body = main.readiness_check(response)
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["checks"]["database"], "ok")
        self.assertIsNone(body["detail"])


if __name__ == "__main__":
    unittest.main()

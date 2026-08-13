"""G2 — body-cap pre-lectura en el API gateway (services/api/main.py).

Sin límite, un request con Content-Length gigante obligaba al server a consumir
el body antes de cualquier rechazo → vector DoS trivial. El middleware
`body_size_limit_middleware` rechaza con 413
`{"detail": {"code": "PAYLOAD_TOO_LARGE", "msg": ...}}` ANTES de leer el body,
usando solo el header Content-Length. Límite: env MAX_REQUEST_BODY_BYTES
(default 2097152 = 2MB).
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "internal-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi.testclient import TestClient  # noqa: E402


def _api_main():
    """Import robusto del main de la API (mismo patrón que test_m14_readiness_no_leak):
    el connector también tiene `main.app` — si otro test lo importó primero en este
    worker, hay que forzar el de services/api."""
    _m = sys.modules.get("main")
    if _m is None or not hasattr(_m, "readiness_check"):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
        sys.modules.pop("main", None)
        import main as _m
    return _m


class BodyCapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = _api_main()
        # Sin context manager → NO dispara lifespan/startup contra Supabase.
        cls.client = TestClient(cls.main.app, raise_server_exceptions=False)

    def test_content_length_sobre_el_cap_da_413_json(self):
        r = self.client.post(
            "/api/v1/orders",
            headers={"Content-Length": str(10 * 1024 * 1024)},
        )
        self.assertEqual(r.status_code, 413)
        body = r.json()
        self.assertEqual(body["detail"]["code"], "PAYLOAD_TOO_LARGE")
        self.assertIn("msg", body["detail"])
        # El 413 pasa de vuelta por request_id/security_headers (quedó por dentro).
        self.assertIn("x-request-id", r.headers)
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")

    def test_request_normal_sin_header_grande_pasa(self):
        # /health es público y sin body → el middleware no interviene.
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)

    def test_default_2mb_cuando_env_ausente(self):
        env = dict(os.environ)
        env.pop("MAX_REQUEST_BODY_BYTES", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.main._max_request_body_bytes(), 2097152)
            # Justo EN el límite → pasa (cap inclusivo); /health responde 200.
            r_ok = self.client.get(
                "/health", headers={"Content-Length": "2097152"}
            )
            self.assertEqual(r_ok.status_code, 200)
            # 1 byte por encima → 413.
            r_big = self.client.get(
                "/health", headers={"Content-Length": "2097153"}
            )
            self.assertEqual(r_big.status_code, 413)

    def test_env_override_ajusta_el_cap(self):
        with patch.dict(os.environ, {"MAX_REQUEST_BODY_BYTES": "100"}):
            self.assertEqual(self.main._max_request_body_bytes(), 100)
            r = self.client.get("/health", headers={"Content-Length": "101"})
            self.assertEqual(r.status_code, 413)
            self.assertIn("100 bytes", r.json()["detail"]["msg"])
            r_ok = self.client.get("/health", headers={"Content-Length": "100"})
            self.assertEqual(r_ok.status_code, 200)

    def test_content_length_malformado_no_rompe(self):
        # El middleware no decide sobre headers inválidos: deja pasar y el
        # framework/server los rechaza. Nunca debe explotar con 500.
        r = self.client.get("/health", headers={"Content-Length": "no-es-numero"})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()

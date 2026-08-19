"""Rotación sin-caída de INTERNAL_SERVICE_SECRET (habilitador B2 del PLAN).

Ambos validadores (api `internal_auth` y orchestrator `server.py`) aceptan el
secret saliente vía `INTERNAL_SERVICE_SECRET_PREVIOUS` durante la ventana de
rotación. Fuera de la ventana la var queda vacía y solo el vigente pasa.

Patrón de invocación directa (como test_a11_metrics_auth): no se levanta
TestClient para no disparar startup contra Supabase.
"""
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from dependencies import internal_auth  # noqa: E402
import server  # noqa: E402  (orchestrator)

CURRENT = "secret-vigente-nuevo"
PREVIOUS = "secret-saliente-viejo"


class _Req:
    def __init__(self, secret=None):
        self.headers = {"X-Internal-Service-Secret": secret} if secret else {}


class ApiVerifyInternalSecretTests(unittest.TestCase):
    def test_current_accepted(self):
        with patch.object(internal_auth, "INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(internal_auth, "INTERNAL_SERVICE_SECRET_PREVIOUS", ""):
            self.assertTrue(internal_auth._verify_internal_secret(_Req(CURRENT)))

    def test_previous_accepted_during_window(self):
        with patch.object(internal_auth, "INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(internal_auth, "INTERNAL_SERVICE_SECRET_PREVIOUS", PREVIOUS):
            self.assertTrue(internal_auth._verify_internal_secret(_Req(PREVIOUS)))
            self.assertTrue(internal_auth._verify_internal_secret(_Req(CURRENT)))

    def test_previous_rejected_when_window_closed(self):
        """Ventana cerrada (PREVIOUS vacío): el saliente ya NO pasa."""
        with patch.object(internal_auth, "INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(internal_auth, "INTERNAL_SERVICE_SECRET_PREVIOUS", ""):
            self.assertFalse(internal_auth._verify_internal_secret(_Req(PREVIOUS)))

    def test_wrong_secret_denied(self):
        with patch.object(internal_auth, "INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(internal_auth, "INTERNAL_SERVICE_SECRET_PREVIOUS", PREVIOUS):
            self.assertFalse(internal_auth._verify_internal_secret(_Req("WRONG")))
            self.assertFalse(internal_auth._verify_internal_secret(_Req()))

    def test_fail_closed_when_unconfigured(self):
        """Sin secret configurado todo se niega (postura original preservada)."""
        with patch.object(internal_auth, "INTERNAL_SERVICE_SECRET", ""), \
             patch.object(internal_auth, "INTERNAL_SERVICE_SECRET_PREVIOUS", PREVIOUS):
            self.assertFalse(internal_auth._verify_internal_secret(_Req(CURRENT)))
            self.assertFalse(internal_auth._verify_internal_secret(_Req(PREVIOUS)))


class OrchestratorSecretRotationTests(unittest.TestCase):
    def test_current_accepted(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(server, "_INTERNAL_SERVICE_SECRET_PREVIOUS", ""):
            self.assertTrue(server._internal_secret_matches(CURRENT))

    def test_previous_accepted_during_window(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(server, "_INTERNAL_SERVICE_SECRET_PREVIOUS", PREVIOUS):
            self.assertTrue(server._internal_secret_matches(PREVIOUS))

    def test_previous_rejected_when_window_closed(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(server, "_INTERNAL_SERVICE_SECRET_PREVIOUS", ""):
            self.assertFalse(server._internal_secret_matches(PREVIOUS))

    def test_wrong_and_missing_denied(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", CURRENT), \
             patch.object(server, "_INTERNAL_SERVICE_SECRET_PREVIOUS", PREVIOUS):
            self.assertFalse(server._internal_secret_matches("WRONG"))
            self.assertFalse(server._internal_secret_matches(""))

    def test_fail_closed_when_unconfigured(self):
        with patch.object(server, "_INTERNAL_SERVICE_SECRET", ""), \
             patch.object(server, "_INTERNAL_SERVICE_SECRET_PREVIOUS", PREVIOUS):
            self.assertFalse(server._internal_secret_matches(CURRENT))


if __name__ == "__main__":
    unittest.main()

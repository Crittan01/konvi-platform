"""W1 — _client_ip toma el hop de la DERECHA del XFF (anti-spoofing, sistémico)."""
import os, sys, unittest
from unittest.mock import MagicMock
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
from dependencies.security import _client_ip  # noqa: E402

def _req(xff=None, host="9.9.9.9"):
    r = MagicMock()
    r.headers = {"x-forwarded-for": xff} if xff is not None else {}
    r.client = MagicMock(host=host)
    return r

class XffTrustedHopTests(unittest.TestCase):
    def test_toma_derecha_no_izquierda(self):
        # atacante prepend "1.1.1.1"; Render añade la real "3.3.3.3" al final
        self.assertEqual(_client_ip(_req("1.1.1.1, 2.2.2.2, 3.3.3.3")), "3.3.3.3")
    def test_spoof_izquierdo_ignorado(self):
        self.assertEqual(_client_ip(_req("evil-spoof, 4.4.4.4")), "4.4.4.4")
    def test_una_sola_entrada(self):
        self.assertEqual(_client_ip(_req("5.5.5.5")), "5.5.5.5")
    def test_sin_xff_usa_client_host(self):
        self.assertEqual(_client_ip(_req(None, host="7.7.7.7")), "7.7.7.7")

if __name__ == "__main__":
    unittest.main()

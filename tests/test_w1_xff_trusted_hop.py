"""W1 — _client_ip: helper XFF unificado.

Default = hop IZQUIERDO (comportamiento histórico, no rompe rate-limit/allowlist).
El trusted-hop desde la DERECHA (anti-spoofing) es ACTIVABLE por env una vez
verificado el manejo de X-Forwarded-For de Render (VALIDAR EN DOC OFICIAL).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
from dependencies import security  # noqa: E402
from dependencies.security import _client_ip  # noqa: E402


def _req(xff=None, host="9.9.9.9"):
    r = MagicMock()
    r.headers = {"x-forwarded-for": xff} if xff is not None else {}
    r.client = MagicMock(host=host)
    return r


class XffDefaultLeftmostTests(unittest.TestCase):
    """Default (env=0): leftmost, sin cambio de comportamiento."""

    def test_default_toma_izquierda(self):
        self.assertEqual(_client_ip(_req("1.1.1.1, 2.2.2.2, 3.3.3.3")), "1.1.1.1")

    def test_una_sola_entrada(self):
        self.assertEqual(_client_ip(_req("5.5.5.5")), "5.5.5.5")

    def test_sin_xff_usa_client_host(self):
        self.assertEqual(_client_ip(_req(None, host="7.7.7.7")), "7.7.7.7")

    def test_sin_xff_sin_client(self):
        r = MagicMock(headers={}, client=None)
        self.assertEqual(_client_ip(r), "unknown")


class XffTrustedHopFromRightTests(unittest.TestCase):
    """Con XFF_TRUSTED_HOPS_FROM_RIGHT>0 (activado tras verificar Render)."""

    def test_hop1_desde_derecha_unspoofable(self):
        # atacante prepend spoof; el hop real queda a la derecha
        with patch.object(security, "_XFF_HOPS_FROM_RIGHT", 1):
            self.assertEqual(_client_ip(_req("evil-spoof, 3.3.3.3")), "3.3.3.3")

    def test_hop2_desde_derecha(self):
        with patch.object(security, "_XFF_HOPS_FROM_RIGHT", 2):
            self.assertEqual(_client_ip(_req("a, real, cdn")), "real")

    def test_hops_mayor_que_lista_cae_a_izquierda(self):
        with patch.object(security, "_XFF_HOPS_FROM_RIGHT", 5):
            self.assertEqual(_client_ip(_req("only")), "only")


class TrustedClientIpHeaderTests(unittest.TestCase):
    """W5/T4-01 — TRUSTED_CLIENT_IP_HEADER (p.ej. cf-connecting-ip): solución robusta
    INMUNE al nº de hops del XFF (no requiere conocer la topología de Render)."""

    def _req(self, headers):
        r = MagicMock()
        r.headers = headers
        r.client = MagicMock(host="9.9.9.9")
        return r

    def test_usa_header_de_confianza_ignora_xff(self):
        with patch.object(security, "_TRUSTED_CLIENT_IP_HEADER", "cf-connecting-ip"):
            ip = _client_ip(self._req({
                "x-forwarded-for": "spoof1, spoof2, internal-render",
                "cf-connecting-ip": "200.1.2.3",
            }))
        self.assertEqual(ip, "200.1.2.3")  # el header gana, inmune al hop-count

    def test_header_ausente_cae_a_xff(self):
        with patch.object(security, "_TRUSTED_CLIENT_IP_HEADER", "cf-connecting-ip"):
            ip = _client_ip(self._req({"x-forwarded-for": "1.1.1.1, 2.2.2.2"}))
        self.assertEqual(ip, "1.1.1.1")  # sin el header → XFF (default leftmost)


if __name__ == "__main__":
    unittest.main()

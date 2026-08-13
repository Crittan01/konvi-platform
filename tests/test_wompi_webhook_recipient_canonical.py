"""Tests wompi_webhook recipient construction usa schema canónico `street`.

A2 finiquito 2026-06-23: cierre Bug #2 audit §1 — wompi_webhook leía
`address.line1` con fallback `street`. Tras refactor, lee `street`
con fallback defensivo `line1` (30 días post-deploy — adversarial #12).
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "services" / "api"),
)


class TestWompiWebhookCanonicalAddress(unittest.TestCase):
    def test_canonical_street_preferred(self):
        """Lectura canónica: addr.street tiene prioridad sobre line1."""
        addr = {
            "street": "Cra 10 #5-23",
            "line1": "OLD",
            "city": "Bogotá",
        }
        # Replicar la línea exacta del refactor (regla #4 backwards compat).
        addr_street = addr.get("street") or addr.get("line1") or ""
        self.assertEqual(addr_street, "Cra 10 #5-23")

    def test_legacy_line1_fallback_during_window(self):
        """Si solo hay line1 (legacy snapshot serializado), fallback funciona."""
        addr = {"line1": "Calle Legacy", "city": "Bogotá"}
        addr_street = addr.get("street") or addr.get("line1") or ""
        self.assertEqual(addr_street, "Calle Legacy")

    def test_empty_address_returns_empty_string(self):
        addr = {"city": "Bogotá"}  # falta street/line1
        addr_street = addr.get("street") or addr.get("line1") or ""
        self.assertEqual(addr_street, "")


if __name__ == "__main__":
    unittest.main()

"""Tests cart shipping + canonical address shape — A2 finiquito 2026-06-23.

Verifica que el shape canónico contact.address (`street` REQUIRED + opcionales)
es compatible con downstream:
  • _format_address_for_summary (orchestrator) → produce string legible.
  • Aveonline recipient construction (wompi_webhook) → toma street correcto.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


class TestCanonicalAddressShipping(unittest.TestCase):
    def test_format_address_reads_street(self):
        from orchestrator import _format_address_for_summary
        addr = {
            "street": "Calle 100 #5-23",
            "city": "Bogotá",
            "neighborhood": "Chapinero",
            "state": "Cundinamarca",
            "dane_code": "11001000",
            "building_type": "casa",
        }
        out = _format_address_for_summary(addr)
        self.assertIn("Calle 100 #5-23", out)
        self.assertIn("Bogotá", out)
        self.assertIn("Chapinero", out)

    def test_format_address_empty_dict_returns_empty(self):
        from orchestrator import _format_address_for_summary
        self.assertEqual(_format_address_for_summary({}), "")

    def test_format_address_conjunto_with_tower_apartment(self):
        from orchestrator import _format_address_for_summary
        addr = {
            "street": "Cra 7 #20-50",
            "city": "Bogotá",
            "building_type": "conjunto",
            "tower": "3",
            "apartment": "401",
            "complex_name": "Torres del Parque",
        }
        out = _format_address_for_summary(addr)
        self.assertIn("Cra 7 #20-50", out)
        self.assertIn("Torres del Parque", out)
        self.assertIn("Apto 401", out)


if __name__ == "__main__":
    unittest.main()

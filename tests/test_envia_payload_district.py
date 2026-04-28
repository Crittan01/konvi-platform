"""Tests del payload Envia con district (rev. 68).

Verifica que `_coerce_origin` y `_coerce_destination` en
shipping_quote_tool.py mapean correctamente address.neighborhood → district
para que carriers como Coordinadora/Servientrega reciban el barrio.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools.shipping_quote_tool import _coerce_origin, _coerce_destination  # noqa: E402


class CoerceOriginDistrictTests(unittest.TestCase):
    def test_origin_with_neighborhood_includes_district(self):
        out = _coerce_origin({
            "city": "Bogotá",
            "state": "DC",
            "country": "CO",
            "dane_code": "11001000",
            "neighborhood": "Chapinero",
        })
        self.assertIsNotNone(out)
        self.assertEqual(out["district"], "Chapinero")
        self.assertEqual(out["city"], "Bogotá")
        # _sanitize_dane_code convierte 8-dígitos con sufijo "000" a 5-dígitos.
        self.assertEqual(out["postalCode"], "11001")

    def test_origin_without_neighborhood_omits_district(self):
        out = _coerce_origin({
            "city": "Bogotá",
            "state": "DC",
            "country": "CO",
            "dane_code": "11001000",
        })
        self.assertIsNotNone(out)
        self.assertNotIn("district", out)

    def test_origin_empty_neighborhood_omits_district(self):
        out = _coerce_origin({
            "city": "Bogotá",
            "state": "DC",
            "country": "CO",
            "dane_code": "11001000",
            "neighborhood": "   ",
        })
        self.assertIsNotNone(out)
        self.assertNotIn("district", out)

    def test_origin_missing_required_returns_none(self):
        # Sin dane_code → None (no se puede cotizar)
        self.assertIsNone(_coerce_origin({"city": "Bogotá", "state": "DC"}))


class CoerceDestinationDistrictTests(unittest.TestCase):
    def test_destination_with_neighborhood_includes_district(self):
        out = _coerce_destination({
            "city": "Medellín",
            "state": "ANT",
            "country": "CO",
            "dane_code": "05001000",
            "neighborhood": "El Poblado",
        })
        self.assertIsNotNone(out)
        self.assertEqual(out["district"], "El Poblado")

    def test_destination_without_neighborhood_omits_district(self):
        out = _coerce_destination({
            "city": "Cali",
            "state": "VAL",
            "country": "CO",
            "dane_code": "76001000",
        })
        self.assertIsNotNone(out)
        self.assertNotIn("district", out)


if __name__ == "__main__":
    unittest.main()

"""Rev. 92.c — Tests del cambio en `_normalize_attributes_label`.

UX: cuando una variante tiene UN solo atributo (95% de los casos en
KAIU + típicamente en multi-tenant), la etiqueta debe ser solo el
valor. Si tiene MÚLTIPLES atributos, preservar "Key: Value, Key: Value"
para no perder semántica.

Esto evita "Presentaciones disponibles: Presentación: 60g, ..." en el
output del LLM, que se ve redundante y poco profesional.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.catalog_tool import _normalize_attributes_label  # noqa: E402


class SingleAttributeTests(unittest.TestCase):
    """Caso típico — un solo atributo: solo el valor."""

    def test_presentacion_returns_value_only(self):
        out = _normalize_attributes_label({"Presentación": "60g"}, "JAB-COC-60", 0)
        self.assertEqual(out, "60g")

    def test_volumen_returns_value_only(self):
        out = _normalize_attributes_label({"Volumen": "30ml"}, "VEG-ARG-30", 0)
        self.assertEqual(out, "30ml")

    def test_talla_returns_value_only(self):
        out = _normalize_attributes_label({"Talla": "M"}, "CAM-AZL-M", 0)
        self.assertEqual(out, "M")

    def test_strips_whitespace(self):
        out = _normalize_attributes_label({"Presentación": "  60g  "}, "X", 0)
        self.assertEqual(out, "60g")


class MultipleAttributesTests(unittest.TestCase):
    """Múltiples atributos: preservar Key: Value, Key: Value."""

    def test_color_plus_size_keeps_keys(self):
        out = _normalize_attributes_label(
            {"Color": "Rojo", "Talla": "M"}, "CAM-RJ-M", 0,
        )
        # Orden alfabético por key.
        self.assertEqual(out, "Color: Rojo, Talla: M")

    def test_three_attributes(self):
        out = _normalize_attributes_label(
            {"Color": "Negro", "Material": "Cuero", "Talla": "L"},
            "ZAP-NEG-L", 0,
        )
        self.assertEqual(out, "Color: Negro, Material: Cuero, Talla: L")


class FallbacksTests(unittest.TestCase):
    """Fallbacks cuando no hay atributos."""

    def test_no_attributes_uses_sku(self):
        out = _normalize_attributes_label({}, "SKU-X-001", 1)
        self.assertEqual(out, "sku: SKU-X-001")

    def test_none_attributes_uses_sku(self):
        out = _normalize_attributes_label(None, "SKU-X-001", 1)
        self.assertEqual(out, "sku: SKU-X-001")

    def test_no_attributes_no_sku_uses_index(self):
        out = _normalize_attributes_label({}, None, 3)
        self.assertEqual(out, "variante 3")

    def test_attributes_with_none_value_falls_back(self):
        # Si todos los atributos son None, debe caer a sku/fallback.
        out = _normalize_attributes_label({"Color": None}, "X", 0)
        self.assertEqual(out, "sku: X")

    def test_attributes_with_empty_string_falls_back(self):
        out = _normalize_attributes_label({"Color": "  "}, "X", 0)
        self.assertEqual(out, "sku: X")


if __name__ == "__main__":
    unittest.main()

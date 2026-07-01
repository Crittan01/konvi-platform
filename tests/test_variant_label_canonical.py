"""ADR-0029 F2 — label canónico de variante (única fórmula cross-surface).

Reemplaza las ≥3 fórmulas divergentes (catalog_tool, cart_tool, shipping_quote_tool). Fija que todas
las superficies rotulen la MISMA variante igual, y que KAIU (1 atributo) no regrese.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.catalog_contract import variant_label, canonicalize_unit_value  # noqa: E402


class VariantLabelTests(unittest.TestCase):
    def test_single_attribute_returns_value_kaiu(self):
        # Caso KAIU (todas las variantes tienen 1 atributo) — sin regresión.
        self.assertEqual(variant_label({"Volumen": "30ml"}), "30ml")
        self.assertEqual(variant_label({"Presentación": "60g"}), "60g")

    def test_unit_canonicalized(self):
        # "30 mililitros" → "30ml" en TODAS las superficies (antes solo shipping).
        self.assertEqual(variant_label({"Volumen": "30 mililitros"}), "30ml")
        self.assertEqual(variant_label({"Peso": "60 gramos"}), "60g")

    def test_multiple_attributes_semantic(self):
        # N atributos → 'Clave: Valor' en orden estable (misma salida cross-surface).
        self.assertEqual(variant_label({"Talla": "M", "Color": "Rojo"}), "Color: Rojo, Talla: M")

    def test_no_attributes_uses_sku_then_estandar(self):
        self.assertEqual(variant_label(None, "ABC-1"), "ABC-1")
        self.assertEqual(variant_label({}, None), "Estándar")
        self.assertEqual(variant_label({"x": None}, None), "Estándar")  # todos null → Estándar

    def test_canonicalize_idempotent_and_passthrough(self):
        self.assertEqual(canonicalize_unit_value("30ml"), "30ml")       # idempotente
        self.assertEqual(canonicalize_unit_value("Talla M"), "Talla M")  # sin unidad → literal

    def test_delegation_produces_same_across_callers(self):
        # Los wrappers de cada caller delegan en variant_label → misma salida.
        from tools.shipping_quote_tool import _variation_label
        from tools.catalog_tool import _normalize_attributes_label
        v = {"attributes": {"Volumen": "30ml"}, "sku": "S1"}
        self.assertEqual(_variation_label(v), "30ml")
        self.assertEqual(_normalize_attributes_label({"Volumen": "30ml"}, "S1", 0), "30ml")


if __name__ == "__main__":
    unittest.main()

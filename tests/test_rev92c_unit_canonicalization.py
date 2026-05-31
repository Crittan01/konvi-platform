"""Rev. 92.c — Tests de normalización de unidades.

Multi-tenant: cualquier tenant escribe la unidad de su variante como
quiera ("60 gramos", "60g", "60 gr"). El cliente la dice como quiera
también. El bot debe normalizar a forma canónica única para display y
matching.

Cobertura de unidades:
  • Peso: g, kg, mg.
  • Volumen: ml, l, cl, cc.
  • Imperial: oz, lb, in.
  • Largo: cm, m, mm.
  • Cantidad: u, pack.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.shipping_quote_tool import (  # noqa: E402
    _canonicalize_unit_value,
    _variation_label,
)


class WeightCanonicalizationTests(unittest.TestCase):

    def test_gramos_variants(self):
        for raw, expected in [
            ("60 gramos", "60g"),
            ("60 gramo", "60g"),
            ("60 gr", "60g"),
            ("60gms", "60g"),
            ("60g", "60g"),
            ("60 g", "60g"),
        ]:
            self.assertEqual(_canonicalize_unit_value(raw), expected,
                f"falló: {raw!r}")

    def test_kilogramos_variants(self):
        for raw, expected in [
            ("1 kilogramo", "1kg"),
            ("1 kilo", "1kg"),
            ("1 kg", "1kg"),
            ("1kg", "1kg"),
            ("2.5 kilos", "2.5kg"),
        ]:
            self.assertEqual(_canonicalize_unit_value(raw), expected,
                f"falló: {raw!r}")


class VolumeCanonicalizationTests(unittest.TestCase):

    def test_mililitros_variants(self):
        for raw, expected in [
            ("30 mililitros", "30ml"),
            ("30 mililitro", "30ml"),
            ("30 ml", "30ml"),
            ("30ml", "30ml"),
            ("30 mls", "30ml"),
            ("30cc", "30ml"),  # cc = ml en líquidos
        ]:
            self.assertEqual(_canonicalize_unit_value(raw), expected,
                f"falló: {raw!r}")

    def test_litros_variants(self):
        for raw, expected in [
            ("1 litro", "1l"),
            ("1 l", "1l"),
            ("1 lt", "1l"),
            ("0.5 litros", "0.5l"),
        ]:
            self.assertEqual(_canonicalize_unit_value(raw), expected,
                f"falló: {raw!r}")


class ImperialCanonicalizationTests(unittest.TestCase):

    def test_onzas(self):
        for raw, expected in [
            ("12 onzas", "12oz"),
            ("12 oz", "12oz"),
            ("12oz", "12oz"),
        ]:
            self.assertEqual(_canonicalize_unit_value(raw), expected)

    def test_libras(self):
        for raw, expected in [
            ("1 libra", "1lb"),
            ("1 lb", "1lb"),
            ("2 libras", "2lb"),
        ]:
            self.assertEqual(_canonicalize_unit_value(raw), expected)


class LengthCanonicalizationTests(unittest.TestCase):

    def test_cm_m_pulgadas(self):
        for raw, expected in [
            ("10 cm", "10cm"),
            ("10 centímetros", "10cm"),
            ("1 metro", "1m"),
            ("12 pulgadas", "12in"),
        ]:
            self.assertEqual(_canonicalize_unit_value(raw), expected)


class DecimalSeparatorTests(unittest.TestCase):

    def test_comma_to_dot(self):
        # Hispanohablantes a veces usan coma decimal.
        self.assertEqual(_canonicalize_unit_value("2,5 kg"), "2.5kg")
        self.assertEqual(_canonicalize_unit_value("0,5 ml"), "0.5ml")


class NoiseAndEdgeCases(unittest.TestCase):

    def test_empty_string_returns_unchanged(self):
        self.assertEqual(_canonicalize_unit_value(""), "")

    def test_unrecognized_unit_returns_unchanged(self):
        # "bla" no es unidad → preservar.
        self.assertEqual(_canonicalize_unit_value("30 bla"), "30 bla")

    def test_no_number_returns_unchanged(self):
        self.assertEqual(_canonicalize_unit_value("Talla M"), "Talla M")
        self.assertEqual(_canonicalize_unit_value("Rojo"), "Rojo")

    def test_idempotent(self):
        # Doble normalización = misma salida.
        once = _canonicalize_unit_value("60 gramos")
        twice = _canonicalize_unit_value(once)
        self.assertEqual(once, twice)


class VariationLabelIntegrationTests(unittest.TestCase):
    """Verifica que `_variation_label` aplica la canonicalización."""

    def test_normalizes_volumen_in_variant(self):
        v = {"attributes": {"Volumen": "30 mililitros"}, "sku": "X"}
        self.assertEqual(_variation_label(v), "30ml")

    def test_normalizes_presentacion_in_variant(self):
        v = {"attributes": {"Presentación": "60 gramos"}, "sku": "X"}
        self.assertEqual(_variation_label(v), "60g")

    def test_normalizes_in_multi_attribute_variant(self):
        v = {
            "attributes": {"Color": "Rojo", "Tamaño": "30 ml"},
            "sku": "X",
        }
        out = _variation_label(v)
        self.assertIn("30ml", out)
        self.assertIn("Color: Rojo", out)


if __name__ == "__main__":
    unittest.main()

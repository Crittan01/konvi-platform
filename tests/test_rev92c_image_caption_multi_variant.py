"""Rev. 92.c — Tests del caption multi-variant en image_send_tool.

UX: cuando un producto tiene varias presentaciones y el bot envía la
foto, el caption debe listar TODAS las variantes con sus precios (no
solo la "best_variation" que el resolver eligió). Para que el cliente
vea las opciones antes de elegir.

También valida la nueva versión de `_variation_label` (single-attr →
solo el valor).
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.shipping_quote_tool import _variation_label  # noqa: E402


class VariationLabelTests(unittest.TestCase):

    def test_single_attribute_returns_value_only(self):
        self.assertEqual(
            _variation_label({"attributes": {"Volumen": "30ml"}, "sku": "X"}),
            "30ml",
        )

    def test_single_attribute_presentacion(self):
        self.assertEqual(
            _variation_label({"attributes": {"Presentación": "60g"}, "sku": "X"}),
            "60g",
        )

    def test_multiple_attributes_keeps_keys(self):
        self.assertEqual(
            _variation_label({
                "attributes": {"Color": "Rojo", "Talla": "M"},
                "sku": "X",
            }),
            "Color: Rojo, Talla: M",
        )

    def test_no_attributes_uses_sku(self):
        self.assertEqual(
            _variation_label({"attributes": {}, "sku": "VEG-ARG-30"}),
            "VEG-ARG-30",
        )

    def test_strips_whitespace_and_canonicalizes(self):
        # Rev. 92.c — además de strip, canonicaliza a "30ml" (sin espacio).
        self.assertEqual(
            _variation_label({"attributes": {"Volumen": "  30 ml  "}}),
            "30ml",
        )


class CaptionLogicSpecTests(unittest.TestCase):
    """Tests documentales del comportamiento esperado del caption.

    El caption se construye dinámicamente en
    `tools.image_send_tool.handle_image_request_if_applicable` —
    estos tests verifican el contrato vía lectura del código.
    """

    def setUp(self):
        with open(
            "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/tools/image_send_tool.py",
            encoding="utf-8",
        ) as fh:
            self.src = fh.read()

    def test_caption_iterates_all_variants(self):
        # El código nuevo recorre TODAS las variantes, no solo la mejor.
        self.assertIn(
            'all_variants = product.get("product_variations")', self.src,
        )

    def test_caption_uses_bullets_for_multi_variant(self):
        # Multi-variant rendering con bullets `* `.
        self.assertIn("len(variant_lines) >= 2", self.src)
        self.assertIn('variant_lines.append(f"* {vlabel}', self.src)

    def test_caption_caps_at_6_variants(self):
        # Visualmente cap a 6 para no inflar el caption.
        self.assertIn("variant_lines[:6]", self.src)

    def test_caption_compact_for_single_variant(self):
        self.assertIn("len(variant_lines) == 1", self.src)


if __name__ == "__main__":
    unittest.main()

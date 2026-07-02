"""ADR-0029 F2 — atributos PRODUCT-LEVEL citables por el bot.

Cierra el gap HIGH de la auditoría: los atributos no-variante (Ingrediente activo, FPS, 100% puro)
ahora se persisten en products.attributes, catalog_tool los lee, y _render_catalog_block los emite al
prompt como HECHOS estructurados → el bot los CITA en vez de inventarlos.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.system_prompt import _render_catalog_block  # noqa: E402

_PRODUCT = {
    "title": "Sérum Facial de Bakuchiol",
    "description": "Alternativa natural al retinol.",
    "attributes": {"Ingrediente activo": "Bakuchiol", "FPS": "50", "Vacío": ""},
    "category": "Sérums",
    "variants": [{"attributes": {"Volumen": "30ml"}, "price": 60000, "stock_quantity": 5}],
    "price_min": 60000, "price_max": 60000,
}


class ProductLevelAttributesRenderTests(unittest.TestCase):
    def test_attributes_rendered_as_citable_specs(self):
        block = _render_catalog_block([_PRODUCT])
        self.assertIn("Especificaciones:", block)
        self.assertIn("Ingrediente activo: Bakuchiol", block)
        self.assertIn("FPS: 50", block)

    def test_empty_attribute_values_omitted(self):
        # "Vacío": "" no debe aparecer (no citar un hecho vacío).
        block = _render_catalog_block([_PRODUCT])
        self.assertNotIn("Vacío", block)

    def test_no_attributes_no_specs_line(self):
        prod = {**_PRODUCT, "attributes": {}}
        block = _render_catalog_block([prod])
        self.assertNotIn("Especificaciones:", block)


if __name__ == "__main__":
    unittest.main()

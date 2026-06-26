"""Regresión A11 — el bloque de catálogo del prompt incluye la DESCRIPCIÓN.

Bug (founder UAT conv +573125835649): el cliente preguntó "¿para qué sirven los
aceites esenciales?" y el bot respondió "la base de conocimiento no me da
detalles específicos de sus beneficios". Causa: products.description SÍ tiene los
beneficios ("antimicrobianas", "expectorante"...) pero _render_catalog_block solo
emitía título+variantes+precio → el LLM nunca veía los beneficios → consultaba la
KB (vacía de beneficios) → exponía la limitación al cliente.

Fix A: renderizar la descripción inline (truncada en límite de palabra).
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.system_prompt import _render_catalog_block  # noqa: E402

_PROD = {
    "id": "p1",
    "title": "Aceite Esencial de Árbol de Té",
    "description": "Aceite esencial puro de árbol de té. Propiedades antimicrobianas y antisépticas. Ideal para imperfecciones de la piel.",
    "variants": [{"id": "v1", "label": "10ml", "price": 15000}],
}


class CatalogBlockDescriptionTests(unittest.TestCase):
    def test_description_aparece_en_el_bloque(self):
        out = _render_catalog_block([_PROD])
        # El beneficio concreto debe estar en el contexto del LLM:
        self.assertIn("antimicrobianas", out)
        self.assertIn("antisépticas", out)
        # Sin perder título ni variantes:
        self.assertIn("Aceite Esencial de Árbol de Té", out)
        self.assertIn("10ml", out)

    def test_producto_sin_description_no_rompe(self):
        prod = dict(_PROD, description="")
        out = _render_catalog_block([prod])
        self.assertIn("Aceite Esencial de Árbol de Té", out)
        # No debe agregar una línea de descripción vacía:
        self.assertNotIn("\n    \n", out)

    def test_description_larga_se_trunca_en_palabra(self):
        prod = dict(_PROD, description="palabra " * 60)  # ~480 chars
        out = _render_catalog_block([prod])
        self.assertIn("…", out)
        # Truncado a límite de palabra (no corta "palabra" a media):
        self.assertNotIn("palab…", out)


if __name__ == "__main__":
    unittest.main()

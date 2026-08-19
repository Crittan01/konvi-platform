"""Regresión A11 — el bloque de catálogo del prompt incluye la DESCRIPCIÓN.

Bug (founder UAT conv +573125835649): el cliente preguntó "¿para qué sirven los
aceites esenciales?" y el bot respondió "la base de conocimiento no me da
detalles específicos de sus beneficios". Causa: products.description SÍ tiene los
beneficios ("antimicrobianas", "expectorante"...) pero _render_catalog_block solo
emitía título+variantes+precio → el LLM nunca veía los beneficios → consultaba la
KB (vacía de beneficios) → exponía la limitación al cliente.

Fix A: renderizar la descripción inline. Recorte por ORACIÓN completa (_clip_description), no a
media frase — el "…" a media oración confundía al cliente (reporte founder 2026-06-30).
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

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

    def test_description_tipica_se_emite_completa(self):
        # Una descripción típica (≤ presupuesto) se emite ÍNTEGRA, sin "…".
        full = ("Aceite esencial puro de árbol de té. Propiedades antimicrobianas y antisépticas. "
                "Ideal para imperfecciones de la piel.")
        out = _render_catalog_block([dict(_PROD, description=full)])
        self.assertIn(full, out)
        self.assertNotIn("…", out)

    def test_description_larga_se_recorta_por_oracion_no_a_media_frase(self):
        # Bug founder 2026-06-30: el bot terminaba a media frase con "…". Una descripción que excede
        # el presupuesto se recorta al último cierre de oración → termina en "." completo, sin "…".
        long_desc = ("El aceite es ideal para tu bienestar diario en el hogar y la oficina. "
                     "Reconocido en aromaterapia por sus múltiples usos cotidianos. ") * 8  # > 600
        out = _render_catalog_block([dict(_PROD, description=long_desc)])
        self.assertNotIn("cotidianos…", out)   # no corta a media frase
        self.assertNotIn("oficina…", out)
        self.assertIn("El aceite es ideal para tu bienestar diario", out)

    def test_safety_note_se_renderiza_con_marcador(self):
        prod = dict(_PROD, safety_note="Diluir antes de usar, no aplicar directo en la piel.")
        out = _render_catalog_block([prod])
        self.assertIn("⚠️", out)
        self.assertIn("Diluir antes de usar", out)

    def test_sin_safety_note_no_renderiza_marcador(self):
        out = _render_catalog_block([dict(_PROD, safety_note="")])
        self.assertNotIn("⚠️", out)


if __name__ == "__main__":
    unittest.main()

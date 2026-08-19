"""A11 2026-06-26 (palanca 4) — marcador AGOTADO en el catálogo del prompt.

El LLM debe ver qué variantes están agotadas (stock<=0) para NO ofrecerlas
(add_to_cart igual las bloquea, pero marcarlas evita ofrecer + backtrack).
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.system_prompt import _variant_line, _render_catalog_block  # noqa: E402


class VariantStockMarkerTests(unittest.TestCase):
    def test_stock_cero_marca_agotado(self):
        line = _variant_line({"label": "15ml", "price": 52000, "id": "v15", "stock": 0})
        self.assertIn("AGOTADO", line)
        self.assertIn("15ml", line)

    def test_stock_positivo_sin_marca(self):
        line = _variant_line({"label": "30ml", "price": 85000, "id": "v30", "stock": 6})
        self.assertNotIn("AGOTADO", line)

    def test_stock_ausente_no_marca(self):
        # Sin campo stock → NO asumir agotado (sin falso positivo).
        line = _variant_line({"label": "30ml", "price": 85000, "id": "v30"})
        self.assertNotIn("AGOTADO", line)

    def test_sin_label_o_precio_retorna_none(self):
        self.assertIsNone(_variant_line({"label": "", "price": 52000}))
        self.assertIsNone(_variant_line({"label": "15ml", "price": 0}))

    def test_render_catalog_marca_agotada(self):
        cat = [{
            "id": "p", "title": "Sérum de Vitamina C",
            "variants": [
                {"id": "v15", "label": "15ml", "price": 52000, "stock": 0},
                {"id": "v30", "label": "30ml", "price": 85000, "stock": 6},
            ],
        }]
        out = _render_catalog_block(cat)
        # La 15ml agotada marcada, la 30ml disponible sin marca.
        self.assertIn("15ml", out)
        self.assertIn("AGOTADO", out)
        # La línea de 30ml no debe llevar AGOTADO.
        line_30 = [ln for ln in out.splitlines() if "30ml" in ln][0]
        self.assertNotIn("AGOTADO", line_30)


if __name__ == "__main__":
    unittest.main()

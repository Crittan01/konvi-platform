"""ADR-0027 Pieza 2 — navegación de catálogo consciente de intención (decide_catalog_view).

Verifica que browse general → "index" (englobe) y específico/compra → "full" (detalle).
Conservador: ante la duda → "full" (nunca rompe compra). Multi-vertical.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.catalog_navigation import decide_catalog_view  # noqa: E402


def _p(pid, title, cat):
    return {"id": pid, "title": title, "category": cat,
            "variants": [{"id": f"v{pid}", "label": "u", "price": 1000}]}


# KAIU-like: 5 categorías (≥3 → englobe aplica).
_KAIU = (
    [_p(f"av{i}", f"Aceite de Cosa {i}", "Aceites Vegetales") for i in range(4)]
    + [_p(f"ae{i}", f"Aceite Esencial de Algo {i}", "Aceites Esenciales") for i in range(4)]
    + [_p(f"j{i}", f"Jabon Artesanal de Coco {i}", "Jabones Artesanales") for i in range(4)]
    + [_p(f"s{i}", f"Serum de Vitamina {i}", "Sérums") for i in range(3)]
    + [_p("k0", "Kit Inicio", "Kits")]
)
# Vertical distinta (moda): 3 categorías.
_MODA = (
    [_p(f"c{i}", f"Camisa Modelo {i}", "Camisas") for i in range(5)]
    + [_p(f"pa{i}", f"Pantalon {i}", "Pantalones") for i in range(5)]
    + [_p(f"z{i}", f"Zapato {i}", "Zapatos") for i in range(5)]
)
# Pocas categorías (2): nunca englobe.
_DOS = [_p("a", "Cosa A", "Alfa"), _p("b", "Cosa B", "Beta")]


class DecideCatalogViewTests(unittest.TestCase):
    def test_browse_general_to_index(self):
        for q in ("¿Qué productos tienen?", "que venden?", "qué manejan",
                  "muéstrame el catálogo", "qué hay?", "ver productos"):
            self.assertEqual(decide_catalog_view(q, _KAIU), "index", q)

    def test_pure_greeting_to_index(self):
        for q in ("Hola", "Buenos días", "buenas", "Hola!"):
            self.assertEqual(decide_catalog_view(q, _KAIU), "index", q)

    def test_purchase_to_full(self):
        for q in ("quiero 2 jabones de coco", "dame un sérum", "necesito aceite de coco",
                  "agrega el jabón de coco", "comprar 3 kits"):
            self.assertEqual(decide_catalog_view(q, _KAIU), "full", q)

    def test_specific_category_to_full(self):
        # Nombra una categoría → drilldown → full (el LLM la lista).
        self.assertEqual(decide_catalog_view("muéstrame los jabones", _KAIU), "full")
        self.assertEqual(decide_catalog_view("qué sérums tienen", _KAIU), "full")

    def test_specific_product_to_full(self):
        # Nombra un producto concreto → full (no englobar).
        self.assertEqual(decide_catalog_view("tienes coco?", _KAIU), "full")
        self.assertEqual(decide_catalog_view("info del serum de vitamina", _KAIU), "full")

    def test_greeting_with_purchase_to_full(self):
        self.assertEqual(decide_catalog_view("hola, quiero un jabón", _KAIU), "full")

    def test_few_categories_always_full(self):
        self.assertEqual(decide_catalog_view("¿qué productos tienen?", _DOS), "full")

    def test_empty_to_full(self):
        self.assertEqual(decide_catalog_view("", _KAIU), "full")
        self.assertEqual(decide_catalog_view("   ", _KAIU), "full")

    def test_multivertical_browse(self):
        # Funciona para moda (categorías reales distintas), no solo KAIU.
        self.assertEqual(decide_catalog_view("¿qué productos tienen?", _MODA), "index")
        self.assertEqual(decide_catalog_view("muéstrame las camisas", _MODA), "full")
        self.assertEqual(decide_catalog_view("quiero un pantalón", _MODA), "full")


if __name__ == "__main__":
    unittest.main()

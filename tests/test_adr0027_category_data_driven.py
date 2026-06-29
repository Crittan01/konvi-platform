"""ADR-0027 Fase 2 — categoría DATA-DRIVEN multi-vertical.

Prueba que el catálogo + CASE D usan la categoría REAL del tenant (products.category_id →
product_categories) y NO la heurística título-head ni el hardcode KAIU. La clave: un tenant de
OTRA vertical (moda) donde la categoría real ("Camisas") ≠ primera-palabra-del-título ("Polo").
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.catalog_tool import get_tenant_catalog, _fallback_category_from_title  # noqa: E402
from agentic.invariants.cart_render_coherence import (  # noqa: E402
    _detect_listed_category, _split_present_missing,
)


class _Chain:
    def __init__(self, data):
        self._data = data
    def __getattr__(self, _):
        return self
    def __call__(self, *a, **k):
        return self
    def execute(self):
        m = MagicMock(); m.data = self._data; return m


class _SB:
    """Mock que devuelve distinto según la tabla (products vs product_categories)."""
    def __init__(self, products, categories):
        self._products = products
        self._categories = categories
    def table(self, name):
        return _Chain(self._categories if name == "product_categories" else self._products)


# Tenant de MODA: categoría real "Camisas", título empieza por "Polo" (título-head = 'polo').
_FASHION_CAT_ID = "cat-camisas-uuid"
_FASHION_PRODUCTS = [{
    "id": "p1", "title": "Polo Ralph Lauren Clásico", "description": "", "safety_note": None,
    "category_id": _FASHION_CAT_ID,
    "product_variations": [{"id": "v1", "sku": "POLO-M", "attributes": {"talla": "M"},
                            "price": 120000, "stock_quantity": 5}],
}]
_FASHION_CATEGORIES = [{"id": _FASHION_CAT_ID, "name": "camisas", "display_label": "Camisas"}]


class GetCatalogRealCategoryTests(unittest.TestCase):
    def test_uses_real_category_not_title_head_fashion(self):
        # PRUEBA MULTI-VERTICAL: categoría real "Camisas", NO "Polo" (título-head).
        sb = _SB(_FASHION_PRODUCTS, _FASHION_CATEGORIES)
        cat = asyncio.run(get_tenant_catalog(sb, "t-fashion"))
        self.assertEqual(len(cat), 1)
        self.assertEqual(cat[0]["category"], "Camisas")        # real
        self.assertNotIn("polo", cat[0]["category"].lower())   # NO la heurística

    def test_fallback_to_title_head_when_category_id_null(self):
        # category_id NULL → fallback título-head (red temporal durante backfill).
        prods = [dict(_FASHION_PRODUCTS[0], category_id=None)]
        sb = _SB(prods, [])  # sin categorías → cat_map vacío
        cat = asyncio.run(get_tenant_catalog(sb, "t-fashion"))
        self.assertEqual(cat[0]["category"], "Polo")           # fallback título-head

    def test_fallback_helper(self):
        # Preserva el acento/caso del título original (display).
        self.assertEqual(_fallback_category_from_title("Jabón Artesanal de Coco"), "Jabón")
        self.assertEqual(_fallback_category_from_title("Vino Tinto Reserva"), "Vino")


class DetectListedCategoryTests(unittest.TestCase):
    def test_detects_any_vertical_category(self):
        # Categorías de verticales NO-KAIU se detectan (antes el hardcode solo conocía
        # sérum/jabón/aceite/kit).
        cats = ["Camisas", "Pantalones", "Vinos", "Laptops"]
        self.assertEqual(_detect_listed_category("Tenemos estas Camisas: ...", cats), "Camisas")
        self.assertEqual(_detect_listed_category("Estos son nuestros Vinos disponibles", cats), "Vinos")
        self.assertIsNone(_detect_listed_category("Hola buenas tardes", cats))

    def test_plural_and_accent_tolerant(self):
        self.assertEqual(_detect_listed_category("tenemos estos Sérums", ["Sérum"]), "Sérum")
        self.assertEqual(_detect_listed_category("nuestros Aceites", ["Aceite"]), "Aceite")

    def test_split_present_missing_by_category(self):
        prods = [{"title": "Polo Ralph Lauren"}, {"title": "Camisa Oxford Azul"}]
        text = "Tenemos el Polo Ralph Lauren disponible"
        present, missing = _split_present_missing(prods, text)
        self.assertEqual([p["title"] for p in present], ["Polo Ralph Lauren"])
        self.assertEqual([p["title"] for p in missing], ["Camisa Oxford Azul"])


if __name__ == "__main__":
    unittest.main()

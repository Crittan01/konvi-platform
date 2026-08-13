"""Tests del tool `list_catalog`.

ADR-0018 Sem 0 MVP — primer tool concreto.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.tools.base import ToolContext
from agentic.tools.catalog import ListCatalogTool, ListCatalogArgs


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_CATALOG_FIXTURE = [
    {
        "id": "p-jab-coco",
        "title": "Jabón Artesanal de Coco",
        "variants": [
            {"id": "v-60g", "label": "60g", "price": 18000},
            {"id": "v-100g", "label": "100g", "price": 24000},
            {"id": "v-150g", "label": "150g", "price": 32000},
        ],
    },
    {
        "id": "p-jab-lavanda",
        "title": "Jabón Artesanal de Lavanda",
        "variants": [
            {"id": "v-60g", "label": "60g", "price": 18000},
            {"id": "v-100g", "label": "100g", "price": 24000},
        ],
    },
    {
        "id": "p-ac-coco",
        "title": "Aceite de Coco Virgen",
        "variants": [
            {"id": "v-50ml", "label": "50ml", "price": 35000},
        ],
    },
    {
        "id": "p-ac-esencial-lavanda",
        "title": "Aceite Esencial de Lavanda",
        "variants": [
            {"id": "v-10ml", "label": "10ml", "price": 28000},
        ],
    },
    {
        "id": "p-serum-vit-c",
        "title": "Sérum de Vitamina C",
        "variants": [
            {"id": "v-30ml", "label": "30ml", "price": 85000},
        ],
    },
]


def _make_ctx() -> ToolContext:
    return ToolContext(
        tenant_id="tenant-test",
        conversation_id="conv-test",
        contact_id=None,
        catalog_cache=_CATALOG_FIXTURE,
    )


class ListCatalogToolTests(unittest.TestCase):

    def setUp(self):
        self.tool = ListCatalogTool()
        self.ctx = _make_ctx()

    def test_sin_categoria_retorna_catalog_completo(self):
        args = ListCatalogArgs()
        result = _run(self.tool.execute(args, self.ctx))
        self.assertTrue(result.success)
        self.assertEqual(result.data["count"], 5)
        titles = {p["title"] for p in result.data["products"]}
        self.assertIn("Jabón Artesanal de Coco", titles)
        self.assertIn("Aceite de Coco Virgen", titles)
        self.assertIn("Sérum de Vitamina C", titles)

    def test_filter_por_categoria_jabon(self):
        args = ListCatalogArgs(category="jabon")
        result = _run(self.tool.execute(args, self.ctx))
        self.assertTrue(result.success)
        titles = {p["title"] for p in result.data["products"]}
        self.assertEqual(len(titles), 2)
        self.assertIn("Jabón Artesanal de Coco", titles)
        self.assertIn("Jabón Artesanal de Lavanda", titles)
        self.assertNotIn("Aceite de Coco Virgen", titles)

    def test_filter_por_categoria_aceite_incluye_vegetal_y_esencial(self):
        args = ListCatalogArgs(category="aceite")
        result = _run(self.tool.execute(args, self.ctx))
        self.assertTrue(result.success)
        titles = {p["title"] for p in result.data["products"]}
        self.assertEqual(len(titles), 2)
        self.assertIn("Aceite de Coco Virgen", titles)
        self.assertIn("Aceite Esencial de Lavanda", titles)

    def test_filter_por_categoria_serum(self):
        args = ListCatalogArgs(category="serum")
        result = _run(self.tool.execute(args, self.ctx))
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["products"]), 1)
        self.assertEqual(result.data["products"][0]["title"], "Sérum de Vitamina C")

    def test_categoria_inexistente_retorna_lista_vacia_con_nota(self):
        args = ListCatalogArgs(category="cremas")
        result = _run(self.tool.execute(args, self.ctx))
        self.assertTrue(result.success)
        self.assertEqual(result.data["products"], [])
        self.assertIn("note", result.data)
        self.assertIn("cremas", result.data["category_requested"])

    def test_variantes_serializadas_correctamente(self):
        args = ListCatalogArgs(category="jabon")
        result = _run(self.tool.execute(args, self.ctx))
        coco = next(p for p in result.data["products"] if "Coco" in p["title"])
        self.assertEqual(len(coco["variants"]), 3)
        # Cada variant tiene los 3 fields esperados.
        for v in coco["variants"]:
            self.assertIn("variation_id", v)
            self.assertIn("label", v)
            self.assertIn("price_cop", v)
        # Verificar precios concretos.
        prices = {v["label"]: v["price_cop"] for v in coco["variants"]}
        self.assertEqual(prices["60g"], 18000)
        self.assertEqual(prices["100g"], 24000)
        self.assertEqual(prices["150g"], 32000)

    def test_catalog_vacio_retorna_lista_vacia(self):
        empty_ctx = ToolContext(
            tenant_id="t",
            conversation_id="c",
            catalog_cache=[],
        )
        args = ListCatalogArgs()
        result = _run(self.tool.execute(args, empty_ctx))
        self.assertTrue(result.success)
        self.assertEqual(result.data["products"], [])
        self.assertIn("vacío", result.data["note"].lower())

    def test_producto_sin_variantes_validas_se_excluye(self):
        """Producto sin variants con price>0 → se omite del output."""
        catalog = [
            {"id": "p-bad", "title": "Sin precio", "variants": [
                {"id": "v-x", "label": "X", "price": 0},
            ]},
            _CATALOG_FIXTURE[0],
        ]
        ctx = ToolContext(tenant_id="t", conversation_id="c", catalog_cache=catalog)
        args = ListCatalogArgs()
        result = _run(self.tool.execute(args, ctx))
        # Solo Jabón Coco debe aparecer.
        self.assertEqual(result.data["count"], 1)
        self.assertEqual(result.data["products"][0]["product_id"], "p-jab-coco")


class ListCatalogArgsValidationTests(unittest.TestCase):
    """Pydantic validation del schema."""

    def test_category_es_opcional(self):
        args = ListCatalogArgs()
        self.assertIsNone(args.category)

    def test_category_string_valido(self):
        args = ListCatalogArgs(category="jabon")
        self.assertEqual(args.category, "jabon")

    def test_category_max_length(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ListCatalogArgs(category="x" * 50)


if __name__ == "__main__":
    unittest.main()

"""Tests F8.B — image_send_tool.

Cubre:
- is_image_request_query positivos/negativos.
- handle_image_request_if_applicable:
    * intent ausente → handled=False.
    * producto con variation.image_url → image_link + caption con precio.
    * producto sin imagen → response_text honesto sin URL fake.
    * producto ambiguo (varias coincidencias) → response_text desambiguación.
    * cliente con tokens transaccionales fuertes (comprar/pagar) → handled=False
      (deja pasar al flujo de venta).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools.image_send_tool import (  # noqa: E402
    handle_image_request_if_applicable,
    is_image_request_query,
)


class _FakeQuery:
    def __init__(self, sb, table_name):
        self._sb = sb
        self._table = table_name

    def select(self, *a, **kw): return self
    def eq(self, *a, **kw): return self
    def limit(self, *a, **kw): return self

    def execute(self):
        m = MagicMock()
        m.data = self._sb.products if self._table == "products" else []
        return m


class _FakeSupabase:
    def __init__(self, products):
        self.products = products

    def table(self, name):
        return _FakeQuery(self, name)


class IsImageRequestQueryTests(unittest.TestCase):
    def test_positive_simple(self):
        for q in [
            "Mándame foto del aceite",
            "Tienes imagen del jabón",
            "Muéstrame el sérum",
            "¿Cómo se ve el aceite de coco?",
            "envíame una foto",
            "tienen foto?",
            "puedes enviarme la foto",
        ]:
            self.assertTrue(is_image_request_query(q), f"esperaba True para {q!r}")

    def test_negative_no_image_intent(self):
        for q in [
            "Hola, ¿qué tienen?",
            "¿Cuánto cuesta el aceite?",
            "Quiero pedir el jabón",
            "A Bogotá",
        ]:
            self.assertFalse(is_image_request_query(q), f"esperaba False para {q!r}")

    def test_priority_image_when_both_tokens_present(self):
        # Si hay AMBOS tokens (compra + foto), prioriza imagen — el cliente
        # explícitamente pidió ver antes de comprar.
        for q in [
            "Quiero comprar el aceite y mándame foto",
            "Ya pago, mándame la foto del jabón",
        ]:
            self.assertTrue(is_image_request_query(q), f"esperaba True para {q!r}")

    def test_empty_or_none(self):
        self.assertFalse(is_image_request_query(""))
        self.assertFalse(is_image_request_query(None))


class HandleImageRequestTests(unittest.TestCase):
    def _run(self, *, products, query):
        sb = _FakeSupabase(products)
        return asyncio.run(
            handle_image_request_if_applicable(
                supabase=sb, tenant_id="t1", conversation_id="c1",
                query_text=query, recent_messages=[],
            )
        )

    def test_no_intent_returns_handled_false(self):
        r = self._run(products=[], query="Hola, ¿cuánto cuesta?")
        self.assertFalse(r.handled)

    def test_product_with_variation_image_url(self):
        products = [{
            "id": "p1",
            "title": "Aceite de Argán",
            "cover_image_url": "https://cdn.example.com/cover-argan.jpg",
            "product_variations": [
                {"id": "v1", "sku": "ARG-30", "attributes": {"Volumen": "30ml"},
                 "stock_quantity": 5, "price": 48000,
                 "image_url": "https://cdn.example.com/argan-30.jpg"},
                {"id": "v2", "sku": "ARG-60", "attributes": {"Volumen": "60ml"},
                 "stock_quantity": 5, "price": 82000,
                 "image_url": "https://cdn.example.com/argan-60.jpg"},
            ],
        }]
        r = self._run(products=products, query="Mándame foto del aceite de argán de 60ml")
        self.assertTrue(r.handled)
        self.assertEqual(r.image_link, "https://cdn.example.com/argan-60.jpg")
        self.assertIn("Aceite de Argán", r.image_caption)
        self.assertIn("$82.000", r.image_caption)

    def test_product_without_image_returns_honest_text(self):
        products = [{
            "id": "p2",
            "title": "Jabón Artesanal de Lavanda",
            "cover_image_url": None,
            "product_variations": [
                {"id": "v3", "sku": "LAV-60", "attributes": {"Presentación": "60g"},
                 "stock_quantity": 5, "price": 18000, "image_url": None},
                {"id": "v4", "sku": "LAV-100", "attributes": {"Presentación": "100g"},
                 "stock_quantity": 5, "price": 24000, "image_url": None},
            ],
        }]
        r = self._run(products=products, query="¿Foto del jabón de lavanda?")
        self.assertTrue(r.handled)
        self.assertIsNone(r.image_link)
        self.assertIsNotNone(r.response_text)
        self.assertIn("no tengo foto", r.response_text.lower())
        # No debe inventar URLs
        self.assertNotIn("http", r.response_text)

    def test_product_ambiguous_asks_for_clarification(self):
        products = [
            {"id": "p1", "title": "Aceite de Coco Virgen", "cover_image_url": None,
             "product_variations": [{"id": "v1", "sku": "C-100", "attributes": {"Volumen": "100ml"},
                                     "stock_quantity": 5, "price": 22000, "image_url": None}]},
            {"id": "p2", "title": "Aceite de Argán", "cover_image_url": None,
             "product_variations": [{"id": "v2", "sku": "A-30", "attributes": {"Volumen": "30ml"},
                                     "stock_quantity": 5, "price": 48000, "image_url": None}]},
            {"id": "p3", "title": "Aceite de Almendras Dulces", "cover_image_url": None,
             "product_variations": [{"id": "v3", "sku": "AL-100", "attributes": {"Volumen": "100ml"},
                                     "stock_quantity": 5, "price": 28000, "image_url": None}]},
        ]
        r = self._run(products=products, query="Foto del aceite")
        # Producto ambiguo: o handled con response_text de desambiguación,
        # o handled con response_text genérico pidiendo cuál.
        self.assertTrue(r.handled)
        self.assertIsNone(r.image_link)
        self.assertIsNotNone(r.response_text)

    def test_no_products_returns_handled_false(self):
        r = self._run(products=[], query="Foto del aceite")
        self.assertFalse(r.handled)

    def test_product_uses_cover_image_when_no_variation_image(self):
        products = [{
            "id": "p1",
            "title": "Sérum de Vitamina C",
            "cover_image_url": "https://cdn.example.com/serum-cover.png",
            "product_variations": [
                {"id": "v1", "sku": "VTC-15", "attributes": {"Volumen": "15ml"},
                 "stock_quantity": 5, "price": 52000, "image_url": None},
            ],
        }]
        r = self._run(products=products, query="muéstrame el sérum de vitamina C")
        self.assertTrue(r.handled)
        self.assertEqual(r.image_link, "https://cdn.example.com/serum-cover.png")


if __name__ == "__main__":
    unittest.main()

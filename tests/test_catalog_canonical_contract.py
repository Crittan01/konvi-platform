"""ADR-0028 Pieza B — pacto del catálogo canónico cross-surface.

Fuerza que el endpoint GET /api/v1/catalog (servicio API) y el productor del bot
(get_tenant_catalog, servicio orchestrator) compartan la MISMA clave de variantes
(`variants`) — el literal divergente fue exactamente el bug A11 que bloqueó ventas.
Además valida la forma customer-facing (sin cost_price interno).
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from routers.catalog import shape_catalog_product, CATALOG_VARIATIONS_KEY as API_KEY  # noqa: E402
from tools.catalog_contract import CATALOG_VARIATIONS_KEY as BOT_KEY  # noqa: E402


class CatalogCanonicalContractTests(unittest.TestCase):
    def test_api_and_bot_share_variations_key(self):
        # El pacto: ambas capas exponen variantes bajo la misma clave canónica.
        self.assertEqual(API_KEY, BOT_KEY, "API y bot divergen en la clave de variantes")
        self.assertEqual(API_KEY, "variants")

    def test_shape_is_customer_facing(self):
        prod = {
            "id": "p1", "title": "Jabón de Coco", "description": "natural",
            "safety_note": "uso externo", "retracto_excluded": False,
            "category_id": "cat-jabones", "cover_image_url": "http://img",
            "product_variations": [
                {"id": "v1", "sku": "JAB-60", "price": 18000, "stock_quantity": 5,
                 "attributes": {"Presentación": "60g"}, "image_url": None,
                 "cost_price": 9000},  # cost_price NO debe filtrarse al contrato
            ],
        }
        shaped = shape_catalog_product(prod, "Jabones Artesanales")
        # Forma canónica + categoría operativa.
        self.assertEqual(shaped["category"], "Jabones Artesanales")
        self.assertEqual(shaped["safety_note"], "uso externo")
        self.assertIn(API_KEY, shaped)
        v = shaped[API_KEY][0]
        self.assertEqual(v["label"], "60g")          # label derivado de attributes
        self.assertEqual(v["price"], 18000)
        self.assertEqual(v["currency"], "COP")
        # CRÍTICO: cost_price (interno) NUNCA en el contrato cara-cliente.
        self.assertNotIn("cost_price", v)
        self.assertNotIn("cost_price", shaped)

    def test_empty_variations_safe(self):
        shaped = shape_catalog_product({"id": "p2", "title": "X", "product_variations": []}, None)
        self.assertEqual(shaped[API_KEY], [])
        self.assertIsNone(shaped["category"])


if __name__ == "__main__":
    unittest.main()

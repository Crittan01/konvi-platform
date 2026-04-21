import sys
import types
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools import catalog_tool


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _SupabaseStub:
    def __init__(self, data):
        self._data = data

    def table(self, name):
        if name != "products":
            raise AssertionError(f"Tabla inesperada: {name}")
        return _Query(self._data)


class CatalogToolVariantsTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_includes_variant_breakdown_and_range(self):
        supabase = _SupabaseStub(
            [
                {
                    "title": "Camiseta Tech",
                    "description": "Dry-fit",
                    "product_variations": [
                        {
                            "sku": "CT-M-BLK",
                            "attributes": {"talla": "M", "color": "Negro"},
                            "price": "50000.00",
                            "stock_quantity": 4,
                        },
                        {
                            "sku": "CT-L-BLK",
                            "attributes": {"talla": "L", "color": "Negro"},
                            "price": "55000.00",
                            "stock_quantity": 2,
                        },
                    ],
                }
            ]
        )

        catalog = await catalog_tool.get_tenant_catalog(supabase, "tenant-1")
        self.assertEqual(len(catalog), 1)
        item = catalog[0]

        self.assertEqual(item["title"], "Camiseta Tech")
        self.assertEqual(item["price_min"], 50000.0)
        self.assertEqual(item["price_max"], 55000.0)
        self.assertEqual(item["stock_total"], 6)
        self.assertEqual(item["price"], 50000.0)  # compat legacy
        self.assertEqual(item["stock"], 6)        # compat legacy
        self.assertEqual(len(item["variants"]), 2)
        self.assertEqual(item["variants"][0]["label"], "color: Negro, talla: M")
        self.assertEqual(item["variants"][1]["label"], "color: Negro, talla: L")
        self.assertEqual(item["variants"][0]["attributes"], {"talla": "M", "color": "Negro"})

    async def test_catalog_caps_variant_list_but_keeps_total_stock(self):
        variations = []
        for idx in range(1, catalog_tool.MAX_VARIANTS_PER_PRODUCT + 2):
            variations.append(
                {
                    "sku": f"SKU-{idx}",
                    "attributes": {"modelo": f"V{idx}"},
                    "price": 10000 + idx,
                    "stock_quantity": 1,
                }
            )
        supabase = _SupabaseStub(
            [
                {
                    "title": "Producto Multi",
                    "description": "",
                    "product_variations": variations,
                }
            ]
        )

        catalog = await catalog_tool.get_tenant_catalog(supabase, "tenant-1")
        item = catalog[0]

        self.assertEqual(len(item["variants"]), catalog_tool.MAX_VARIANTS_PER_PRODUCT)
        self.assertEqual(item["stock_total"], len(variations))


if __name__ == "__main__":
    unittest.main()

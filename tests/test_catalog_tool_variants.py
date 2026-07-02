import sys
import types
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools import catalog_tool


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def gt(self, *_args, **_kwargs):
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


class CatalogAvailableStockTests(unittest.IsolatedAsyncioTestCase):
    """F4 — el bot cita stock DISPONIBLE (bruto − reservas activas), no bruto."""

    def _stub(self, reservations):
        prods = [{
            "id": "p1", "title": "Aceite", "category_id": None,
            "product_variations": [
                {"id": "v1", "sku": "A-30", "attributes": {}, "price": "10000", "stock_quantity": 5},
                {"id": "v2", "sku": "A-50", "attributes": {}, "price": "15000", "stock_quantity": 3},
            ],
        }]

        class _Stub:
            def table(_self, name):
                if name == "products":
                    return _Query(prods)
                if name == "stock_reservations":
                    return _Query(reservations)
                raise AssertionError(f"tabla inesperada: {name}")
        return _Stub()

    async def test_subtracts_active_reservations(self):
        cat = await catalog_tool.get_tenant_catalog(
            self._stub([{"variation_id": "v1", "qty": 2}]), "t1")
        by_sku = {v["sku"]: v for v in cat[0][catalog_tool.CATALOG_VARIATIONS_KEY]}
        self.assertEqual(by_sku["A-30"]["stock"], 3)   # 5 − 2 reservado
        self.assertEqual(by_sku["A-50"]["stock"], 3)   # sin reserva → intacto
        self.assertEqual(cat[0]["stock_total"], 6)     # 3 + 3

    async def test_never_negative(self):
        cat = await catalog_tool.get_tenant_catalog(
            self._stub([{"variation_id": "v1", "qty": 9}]), "t1")   # reserva > bruto
        by_sku = {v["sku"]: v for v in cat[0][catalog_tool.CATALOG_VARIATIONS_KEY]}
        self.assertEqual(by_sku["A-30"]["stock"], 0)   # max(0, 5−9)

    async def test_no_reservations_equals_gross(self):
        cat = await catalog_tool.get_tenant_catalog(self._stub([]), "t1")
        self.assertEqual(cat[0]["stock_total"], 8)     # 5 + 3 bruto


if __name__ == "__main__":
    unittest.main()

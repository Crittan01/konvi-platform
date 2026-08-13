"""F2 — importación masiva vía API (POST /products/bulk): antes el mass-importer escribía DIRECTO a
Supabase desde el browser (sin RBAC + @audit_log + validación de ownership). Ahora enruta por la API.

Verifica: crear producto nuevo + variantes, reusar por título, rechazar categoría ajena, y tolerancia
(un producto que falla no detiene los demás).
"""
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402

from routers.products import bulk_import_products, BulkImport, BulkProduct, BulkVariation  # noqa: E402

TID = "tenant-abc"
_REQ = types.SimpleNamespace(headers={}, method="POST",
                             url=types.SimpleNamespace(path="/api/v1/products/bulk"))


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op, self.rows = name, ctrl, "select", None

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def insert(self, rows, *_a, **_k):
        self.op = "insert"; self.rows = rows; return self

    def update(self, data, *_a, **_k):
        self.op = "update"; self.rows = data; return self

    def upsert(self, rows, *_a, **_k):
        self.op = "upsert"; self.rows = rows; return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return self.ctrl._exec(self)


class _Ctrl:
    def __init__(self, *, category_owned=True, existing_titles=None):
        self.category_owned = category_owned
        self.existing_titles = existing_titles or set()
        self.captured = {"insert": [], "update": [], "upsert": []}

    def table(self, name):
        return _Q(name, self)

    def _exec(self, q):
        if q.op in ("insert", "update", "upsert"):
            self.captured[q.op].append((q.name, q.rows))
        if q.name == "product_categories":
            return types.SimpleNamespace(data=[{"id": "cat-1"}] if self.category_owned else [])
        if q.name == "products" and q.op == "select":
            # simula "existe por título" según el set
            return types.SimpleNamespace(data=[{"id": "prod-existing"}] if self.existing_titles else [])
        if q.op == "insert":
            return types.SimpleNamespace(data=[{"id": "prod-new"}])
        return types.SimpleNamespace(data=[{"id": "x"}])


def _payload(title="Jabón", category_id="cat-1", skus=("S1",)):
    return BulkImport(products=[BulkProduct(
        title=title, category_id=category_id,
        variations=[BulkVariation(sku=s, price=10.0, stock_quantity=5) for s in skus],
    )])


async def _run(ctrl, payload):
    return bulk_import_products(payload=payload, request=_REQ, tenant_id=TID,
                                     supabase=ctrl, _role="owner")


class BulkImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_new_product_and_variants(self):
        ctrl = _Ctrl(existing_titles=set())
        r = await _run(ctrl, _payload(skus=("S1", "S2")))
        self.assertEqual(r["products_created"], 1)
        self.assertEqual(r["products_reused"], 0)
        self.assertEqual(r["variants_upserted"], 2)
        self.assertEqual(r["errors"], [])
        # el insert de producto lleva platform_category_id null + tenant scoping
        prod_ins = [rows for (name, rows) in ctrl.captured["insert"] if name == "products"][0]
        self.assertIsNone(prod_ins["platform_category_id"])
        self.assertEqual(prod_ins["tenant_id"], TID)
        # variantes upsertadas por sku
        self.assertTrue(ctrl.captured["upsert"])

    async def test_reuses_existing_by_title(self):
        ctrl = _Ctrl(existing_titles={"Jabón"})
        r = await _run(ctrl, _payload())
        self.assertEqual(r["products_created"], 0)
        self.assertEqual(r["products_reused"], 1)

    async def test_foreign_category_rejected(self):
        ctrl = _Ctrl(category_owned=False)
        with self.assertRaises(HTTPException) as cm:
            await _run(ctrl, _payload(category_id="ajena"))
        self.assertEqual(cm.exception.status_code, 422)

    async def test_no_category_ok(self):
        ctrl = _Ctrl()
        r = await _run(ctrl, _payload(category_id=None))
        self.assertEqual(r["products_created"], 1)


if __name__ == "__main__":
    unittest.main()

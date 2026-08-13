"""ADR-0029 F3 — alta de producto vía API: hardening verificado en review adversarial.

Cubre las 3 conductas que la revisión adversarial confirmó como reales sobre POST /products:
1. Integridad multi-tenant: category_id ajeno al tenant se rechaza (no se persiste el producto).
2. Higiene de datos: si el bulk insert de variantes falla, el producto NO queda huérfano (se borra).
3. Error accionable: SKU duplicado (uc_tenant_sku) devuelve 409 claro, no un 500 opaco.
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

from routers.products import (  # noqa: E402
    create_product,
    ProductCreate,
    VariationCreate,
    _assert_category_owned,
)

TID = "tenant-abc"
_REQ = types.SimpleNamespace(
    headers={}, method="POST",
    url=types.SimpleNamespace(path="/api/v1/products/"),
)


class _Q:
    """Query builder chainable que registra la operación y los .eq() en el controller."""

    def __init__(self, name, ctrl):
        self.name, self.ctrl = name, ctrl
        self.op = "select"
        self.eq_calls = []
        self.rows = None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def insert(self, rows, *_a, **_k):
        self.op = "insert"
        self.rows = rows
        return self

    def update(self, data, *_a, **_k):
        self.op = "update"
        self.rows = data
        return self

    def delete(self, *_a, **_k):
        self.op = "delete"
        return self

    def single(self):
        return self

    def eq(self, k, v):
        self.eq_calls.append((k, v))
        return self

    def execute(self):
        return self.ctrl._execute(self)


class _Ctrl:
    """Fake supabase — respuestas por (tabla, op); una respuesta Exception se lanza."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []  # (name, op, eq_calls, rows)

    def table(self, name):
        return _Q(name, self)

    def _execute(self, q):
        self.calls.append((q.name, q.op, list(q.eq_calls), q.rows))
        r = self.responses.get((q.name, q.op), [])
        if isinstance(r, Exception):
            raise r
        return types.SimpleNamespace(data=r)

    def calls_for(self, name, op):
        return [c for c in self.calls if c[0] == name and c[1] == op]


async def _create(supabase, product):
    return create_product(
        product=product, request=_REQ, tenant_id=TID, supabase=supabase, _role="owner",
    )


class AssertCategoryOwnedTests(unittest.TestCase):
    def test_none_is_noop(self):
        ctrl = _Ctrl()
        _assert_category_owned(ctrl, TID, None)          # no debe consultar DB ni lanzar
        self.assertEqual(ctrl.calls, [])

    def test_owned_ok(self):
        ctrl = _Ctrl({("product_categories", "select"): [{"id": "cat-1"}]})
        _assert_category_owned(ctrl, TID, "cat-1")        # no lanza
        # la consulta se filtró por id Y tenant_id (aislamiento):
        eq = ctrl.calls_for("product_categories", "select")[0][2]
        self.assertIn(("id", "cat-1"), eq)
        self.assertIn(("tenant_id", TID), eq)

    def test_foreign_category_rejected(self):
        ctrl = _Ctrl({("product_categories", "select"): []})   # categoría de otro tenant → vacío
        with self.assertRaises(HTTPException) as cm:
            _assert_category_owned(ctrl, TID, "cat-de-otro")
        self.assertEqual(cm.exception.status_code, 422)


class CreateProductApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_category_blocks_product_insert(self):
        ctrl = _Ctrl({("product_categories", "select"): []})   # no pertenece al tenant
        product = ProductCreate(title="Jabón", category_id="cat-de-otro",
                                variations=[VariationCreate(sku="S1", price=10.0)])
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, product)
        self.assertEqual(cm.exception.status_code, 422)
        # el producto NUNCA se insertó (la validación va antes):
        self.assertEqual(ctrl.calls_for("products", "insert"), [])

    async def test_happy_path_inserts_scoped(self):
        ctrl = _Ctrl({
            ("product_categories", "select"): [{"id": "cat-1"}],
            ("products", "insert"): [{"id": "prod-1", "title": "Jabón"}],
            ("product_variations", "insert"): [{"id": "var-1", "sku": "S1"}],
        })
        product = ProductCreate(title="Jabón", category_id="cat-1",
                                variations=[VariationCreate(sku="S1", price=10.0),
                                            VariationCreate(sku="S2", price=12.0)])
        result = await _create(ctrl, product)
        self.assertEqual(result["id"], "prod-1")
        self.assertEqual(len(result["product_variations"]), 1)
        # las 2 variantes se insertaron en UN bulk (atómico), cada row con tenant_id del JWT:
        ins = ctrl.calls_for("product_variations", "insert")
        self.assertEqual(len(ins), 1)
        rows = ins[0][3]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["tenant_id"] == TID for r in rows))

    async def test_duplicate_sku_returns_409_and_deletes_orphan(self):
        ctrl = _Ctrl({
            ("products", "insert"): [{"id": "prod-1"}],
            ("product_variations", "insert"): Exception(
                'duplicate key value violates unique constraint "uc_tenant_sku"'),
        })
        product = ProductCreate(title="Jabón",
                                variations=[VariationCreate(sku="DUP", price=10.0)])
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, product)
        self.assertEqual(cm.exception.status_code, 409)
        # el producto huérfano se borró, scoping por id + tenant:
        dels = ctrl.calls_for("products", "delete")
        self.assertEqual(len(dels), 1)
        self.assertIn(("id", "prod-1"), dels[0][2])
        self.assertIn(("tenant_id", TID), dels[0][2])


if __name__ == "__main__":
    unittest.main()

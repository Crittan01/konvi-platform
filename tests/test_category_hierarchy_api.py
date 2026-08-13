"""F2 (roadmap producción) — jerarquía de categorías Categoría › Subcategoría en el router.

Verifica las reglas de negocio de 2 niveles que la API debe hacer cumplir (el frontend no es
seguridad):
1. create: el parent_id debe pertenecer al tenant y SER RAÍZ (no una subcategoría) → si no, 422.
2. create: el parent_id se persiste en el insert.
3. patch: no auto-referencia, el nuevo padre debe ser raíz del tenant, y una categoría que YA tiene
   subcategorías no puede volverse subcategoría de otra (evita un 3er nivel).
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

from routers.product_categories import (  # noqa: E402
    create_product_category,
    patch_product_category,
    ProductCategoryCreate,
    ProductCategoryPatch,
)

TID = "tenant-abc"
_REQ = types.SimpleNamespace(headers={}, method="POST",
                             url=types.SimpleNamespace(path="/api/v1/product-categories/"))


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl = name, ctrl
        self.op = "select"
        self.eq_calls = []
        self.rows = None

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def insert(self, rows, *_a, **_k):
        self.op = "insert"; self.rows = rows; return self

    def update(self, data, *_a, **_k):
        self.op = "update"; self.rows = data; return self

    def eq(self, k, v):
        self.eq_calls.append((k, v)); return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return self.ctrl._execute(self)


class _Ctrl:
    """Fake supabase. Rutea los SELECT sobre product_categories:
    - si filtra por parent_id → es el lookup de HIJOS → `children`.
    - si no → es el lookup del PADRE → `parent`.
    Captura inserts/updates para aserciones."""

    def __init__(self, *, parent=None, children=None, insert=None, update=None):
        self.parent = parent if parent is not None else []
        self.children = children if children is not None else []
        self.insert_resp = insert if insert is not None else [{"id": "new-cat"}]
        self.update_resp = update if update is not None else [{"id": "cat-x"}]
        self.calls = []

    def table(self, name):
        return _Q(name, self)

    def _execute(self, q):
        self.calls.append((q.name, q.op, list(q.eq_calls), q.rows))
        if q.op == "insert":
            return types.SimpleNamespace(data=self.insert_resp)
        if q.op == "update":
            return types.SimpleNamespace(data=self.update_resp)
        # select sobre product_categories: rutear por presencia de filtro parent_id
        if any(k == "parent_id" for k, _ in q.eq_calls):
            return types.SimpleNamespace(data=self.children)
        return types.SimpleNamespace(data=self.parent)

    def insert_rows(self):
        for name, op, _eq, rows in self.calls:
            if name == "product_categories" and op == "insert":
                return rows
        return None


async def _create(ctrl, **kw):
    return create_product_category(
        category=ProductCategoryCreate(**kw), request=_REQ, tenant_id=TID, supabase=ctrl, _role="owner")


async def _patch(ctrl, cid, **kw):
    return patch_product_category(
        category_id=cid, category=ProductCategoryPatch(**kw), request=_REQ,
        tenant_id=TID, supabase=ctrl, _role="owner")


class CreateHierarchyTests(unittest.IsolatedAsyncioTestCase):
    async def test_root_create_persists_null_parent(self):
        ctrl = _Ctrl(insert=[{"id": "v1", "display_label": "Salud y Belleza"}])
        await _create(ctrl, name="salud", display_label="Salud y Belleza")
        self.assertEqual(ctrl.insert_rows()["parent_id"], None)

    async def test_subcategory_under_root_ok(self):
        ctrl = _Ctrl(parent=[{"id": "v1", "parent_id": None}],   # el padre existe y es RAÍZ
                     insert=[{"id": "s1", "display_label": "Aceites"}])
        await _create(ctrl, name="aceites", display_label="Aceites", parent_id="v1")
        self.assertEqual(ctrl.insert_rows()["parent_id"], "v1")

    async def test_parent_not_owned_rejected(self):
        ctrl = _Ctrl(parent=[])   # padre ajeno/inexistente para el tenant
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, name="x", display_label="X", parent_id="ajeno")
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIsNone(ctrl.insert_rows())   # no se insertó

    async def test_parent_is_subcategory_rejected(self):
        ctrl = _Ctrl(parent=[{"id": "s1", "parent_id": "v1"}])   # el "padre" ya es subcategoría → 3er nivel
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, name="x", display_label="X", parent_id="s1")
        self.assertEqual(cm.exception.status_code, 422)


class PatchHierarchyTests(unittest.IsolatedAsyncioTestCase):
    async def test_self_parent_rejected(self):
        ctrl = _Ctrl()
        with self.assertRaises(HTTPException) as cm:
            await _patch(ctrl, "c1", parent_id="c1")
        self.assertEqual(cm.exception.status_code, 422)

    async def test_reassign_under_root_ok(self):
        # padre v1 es raíz; la categoría movida (c1) NO tiene hijos → permitido.
        ctrl = _Ctrl(parent=[{"id": "v1", "parent_id": None}], children=[])
        await _patch(ctrl, "c1", parent_id="v1")
        # el update se ejecutó con parent_id
        upd = [c for c in ctrl.calls if c[1] == "update"]
        self.assertTrue(upd and upd[0][3].get("parent_id") == "v1")

    async def test_nesting_a_parent_rejected(self):
        # c1 YA tiene subcategorías → no puede volverse subcategoría de v1 (crearía 3 niveles).
        ctrl = _Ctrl(parent=[{"id": "v1", "parent_id": None}], children=[{"id": "grandkid"}])
        with self.assertRaises(HTTPException) as cm:
            await _patch(ctrl, "c1", parent_id="v1")
        self.assertEqual(cm.exception.status_code, 422)

    async def test_new_parent_must_be_root(self):
        ctrl = _Ctrl(parent=[{"id": "s1", "parent_id": "v1"}])   # nuevo padre ya es subcategoría
        with self.assertRaises(HTTPException) as cm:
            await _patch(ctrl, "c1", parent_id="s1")
        self.assertEqual(cm.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

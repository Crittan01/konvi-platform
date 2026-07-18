"""F2/ADR-0029 D3 — CRUD del contrato de atributos (authoring). RBAC + tenant scoping + validación.

Verifica las reglas de negocio del router product_attribute_definitions:
- create: la categoría debe ser del tenant; el type debe ser válido; el code se deriva del label si falta;
  duplicado (23505) → 409.
- patch: exclude_unset; type inválido → 422; no encontrado → 404.
- delete: no encontrado → 404.
"""
import os
import sys
import types
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi import HTTPException  # noqa: E402

from routers.product_attribute_definitions import (  # noqa: E402
    create_attribute_definition,
    patch_attribute_definition,
    delete_attribute_definition,
    AttributeDefCreate,
    AttributeDefPatch,
    _slugify,
)

TID = "tenant-abc"
_REQ = types.SimpleNamespace(headers={}, method="POST",
                             url=types.SimpleNamespace(path="/api/v1/product-attribute-definitions/"))


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op, self.rows = name, ctrl, "select", None

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def insert(self, rows, *_a, **_k):
        self.op = "insert"; self.rows = rows; return self

    def update(self, data, *_a, **_k):
        self.op = "update"; self.rows = data; return self

    def delete(self, *_a, **_k):
        self.op = "delete"; return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        return self.ctrl._exec(self)


class _Ctrl:
    def __init__(self, responses=None, raise_on_insert=None):
        self.responses = responses or {}
        self.raise_on_insert = raise_on_insert
        self.captured = {}

    def table(self, name):
        return _Q(name, self)

    def _exec(self, q):
        if q.op == "insert":
            if self.raise_on_insert:
                raise self.raise_on_insert
            self.captured.setdefault(q.name, []).append(q.rows)
        return types.SimpleNamespace(data=self.responses.get((q.name, q.op), []))


async def _create(ctrl, **kw):
    return create_attribute_definition(
        definition=AttributeDefCreate(**kw), request=_REQ, tenant_id=TID, supabase=ctrl, _role="owner")


async def _patch(ctrl, did, **kw):
    return patch_attribute_definition(
        definition_id=did, definition=AttributeDefPatch(**kw), request=_REQ,
        tenant_id=TID, supabase=ctrl, _role="owner")


async def _delete(ctrl, did):
    return delete_attribute_definition(
        definition_id=did, request=_REQ, tenant_id=TID, supabase=ctrl, _role="owner")


class SlugifyTests(unittest.TestCase):
    def test_derives_ascii_snake(self):
        self.assertEqual(_slugify("Ingrediente Activo"), "ingrediente_activo")
        self.assertEqual(_slugify("100% puro"), "100_puro")
        self.assertEqual(_slugify("Cancelación de ruido"), "cancelacion_de_ruido")


class CreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_ok_derives_code(self):
        ctrl = _Ctrl({
            ("product_categories", "select"): [{"id": "cat-1"}],   # categoría del tenant
            ("product_attribute_definitions", "insert"): [{"id": "d1", "code": "fps"}],
        })
        await _create(ctrl, product_category_id="cat-1", label="FPS", type="number")
        ins = ctrl.captured["product_attribute_definitions"][0]
        self.assertEqual(ins["code"], "fps")          # derivado del label
        self.assertEqual(ins["tenant_id"], TID)

    async def test_unowned_category_rejected(self):
        ctrl = _Ctrl({("product_categories", "select"): []})       # categoría ajena
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, product_category_id="ajena", label="X", type="text")
        self.assertEqual(cm.exception.status_code, 422)
        self.assertNotIn("product_attribute_definitions", ctrl.captured)

    async def test_invalid_type_rejected(self):
        ctrl = _Ctrl({("product_categories", "select"): [{"id": "cat-1"}]})
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, product_category_id="cat-1", label="X", type="fecha")
        self.assertEqual(cm.exception.status_code, 422)

    async def test_duplicate_code_409(self):
        ctrl = _Ctrl(
            {("product_categories", "select"): [{"id": "cat-1"}]},
            raise_on_insert=Exception('duplicate key value violates unique constraint (23505)'),
        )
        with self.assertRaises(HTTPException) as cm:
            await _create(ctrl, product_category_id="cat-1", label="FPS", code="fps", type="number")
        self.assertEqual(cm.exception.status_code, 409)


class PatchDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_ok(self):
        ctrl = _Ctrl({("product_attribute_definitions", "update"): [{"id": "d1", "label": "FPS (SPF)"}]})
        r = await _patch(ctrl, "d1", label="FPS (SPF)")
        self.assertEqual(r["label"], "FPS (SPF)")

    async def test_patch_invalid_type_rejected(self):
        ctrl = _Ctrl({})
        with self.assertRaises(HTTPException) as cm:
            await _patch(ctrl, "d1", type="fecha")
        self.assertEqual(cm.exception.status_code, 422)

    async def test_patch_not_found_404(self):
        ctrl = _Ctrl({("product_attribute_definitions", "update"): []})
        with self.assertRaises(HTTPException) as cm:
            await _patch(ctrl, "missing", label="X")
        self.assertEqual(cm.exception.status_code, 404)

    async def test_patch_empty_422(self):
        ctrl = _Ctrl({})
        with self.assertRaises(HTTPException) as cm:
            await _patch(ctrl, "d1")
        self.assertEqual(cm.exception.status_code, 422)

    async def test_delete_not_found_404(self):
        ctrl = _Ctrl({("product_attribute_definitions", "delete"): []})
        with self.assertRaises(HTTPException) as cm:
            await _delete(ctrl, "missing")
        self.assertEqual(cm.exception.status_code, 404)

    async def test_delete_ok(self):
        ctrl = _Ctrl({("product_attribute_definitions", "delete"): [{"id": "d1"}]})
        r = await _delete(ctrl, "d1")
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()

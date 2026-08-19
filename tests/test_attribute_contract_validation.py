"""ADR-0029 D4 (roadmap producción F2) — validación HARD de products.attributes contra el contrato.

El bot cita los atributos product-level como HECHOS → deben estar gobernados (anti-alucinación, criterio
binario ADR-0024). Si la categoría tiene contrato: cada atributo debe tener NOMBRE definido y VALOR válido
(SET membership / numérico / booleano). Sin contrato = no-op (backward-compat; KAIU hasta el seed).
"""
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402

from routers.products import (  # noqa: E402
    _validate_attr_value,
    _validate_attributes_against_contract,
    create_product,
    ProductCreate,
    VariationCreate,
)

TID = "tenant-abc"
_REQ = types.SimpleNamespace(headers={}, method="POST",
                             url=types.SimpleNamespace(path="/api/v1/products/"))


def _d(label, type_="text", unit=None, allowed=None):
    return {"label": label, "type": type_, "unit": unit, "allowed_values": allowed}


class ValidateAttrValueTests(unittest.TestCase):
    def test_select_in_set_ok(self):
        _validate_attr_value(_d("Ingrediente activo", "select", allowed=["Bakuchiol", "Retinol"]),
                             "Ingrediente activo", "Bakuchiol")  # no lanza

    def test_select_out_of_set_rejected(self):
        with self.assertRaises(HTTPException) as cm:
            _validate_attr_value(_d("Ingrediente activo", "select", allowed=["Bakuchiol", "Retinol"]),
                                 "Ingrediente activo", "Banana")
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("fuera del contrato", cm.exception.detail)

    def test_select_case_space_insensitive(self):
        _validate_attr_value(_d("Aroma", "select", allowed=["Árbol de té", "Lavanda"]),
                             "Aroma", "árbol de té")  # match normalizado

    def test_metric_with_unit_set_membership(self):
        # 'Volumen' es metric con allowed_values y unidad → el gate es allowed_values (con/sin unidad).
        d = _d("Volumen", "metric", unit="ml", allowed=[5, 10, 30])
        _validate_attr_value(d, "Volumen", "30ml")   # con unidad OK
        _validate_attr_value(d, "Volumen", "30")     # sin unidad OK
        with self.assertRaises(HTTPException):
            _validate_attr_value(d, "Volumen", "7")  # no está en el set

    def test_number_numeric_ok_and_reject(self):
        d = _d("FPS", "number")
        _validate_attr_value(d, "FPS", "50")          # numérico OK
        with self.assertRaises(HTTPException):
            _validate_attr_value(d, "FPS", "altísimo")

    def test_boolean_ok_and_reject(self):
        d = _d("100% puro", "boolean")
        _validate_attr_value(d, "100% puro", "Sí")
        _validate_attr_value(d, "100% puro", "false")
        with self.assertRaises(HTTPException):
            _validate_attr_value(d, "100% puro", "quizás")

    def test_empty_value_is_noop(self):
        _validate_attr_value(_d("FPS", "number"), "FPS", "")  # opcional → no lanza


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op = name, ctrl, "select"

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.ctrl.responses.get((self.name, self.op), []))


class _Ctrl:
    def __init__(self, responses):
        self.responses = responses

    def table(self, name):
        return _Q(name, self)


class ValidateAgainstContractTests(unittest.TestCase):
    def test_no_contract_is_noop(self):
        ctrl = _Ctrl({("product_attribute_definitions", "select"): []})
        _validate_attributes_against_contract(ctrl, TID, "cat-1", {"Cualquiera": "valor"})  # no lanza

    def test_none_category_or_empty_attrs_noop(self):
        ctrl = _Ctrl({})
        _validate_attributes_against_contract(ctrl, TID, None, {"x": "y"})
        _validate_attributes_against_contract(ctrl, TID, "cat-1", {})

    def test_unknown_key_rejected(self):
        ctrl = _Ctrl({("product_attribute_definitions", "select"): [_d("FPS", "number")]})
        with self.assertRaises(HTTPException) as cm:
            _validate_attributes_against_contract(ctrl, TID, "cat-1", {"Marca": "X"})
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("no está en el contrato", cm.exception.detail)

    def test_known_key_bad_value_rejected(self):
        ctrl = _Ctrl({("product_attribute_definitions", "select"):
                      [_d("Ingrediente activo", "select", allowed=["Bakuchiol"])]})
        with self.assertRaises(HTTPException):
            _validate_attributes_against_contract(ctrl, TID, "cat-1", {"Ingrediente activo": "Plutonio"})

    def test_valid_attributes_pass(self):
        ctrl = _Ctrl({("product_attribute_definitions", "select"):
                      [_d("Ingrediente activo", "select", allowed=["Bakuchiol"]), _d("FPS", "number")]})
        _validate_attributes_against_contract(ctrl, TID, "cat-1",
                                              {"Ingrediente activo": "Bakuchiol", "FPS": "50"})  # no lanza


class _QFull:
    """Fake para create end-to-end: registra inserts, respuestas por (tabla, op)."""
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op, self.rows = name, ctrl, "select", None

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def insert(self, rows, *_a, **_k):
        self.op = "insert"; self.rows = rows; return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        if self.op == "insert":
            self.ctrl.inserts.setdefault(self.name, []).append(self.rows)
        return types.SimpleNamespace(data=self.ctrl.responses.get((self.name, self.op), []))


class _CtrlFull:
    def __init__(self, responses):
        self.responses, self.inserts = responses, {}

    def table(self, name):
        return _QFull(name, self)


class CreateProductContractE2ETests(unittest.IsolatedAsyncioTestCase):
    async def _create(self, ctrl, product):
        return create_product(product=product, request=_REQ, tenant_id=TID,
                                    supabase=ctrl, _role="owner")

    async def test_create_rejects_out_of_contract_attribute(self):
        ctrl = _CtrlFull({
            ("product_categories", "select"): [{"id": "cat-1"}],   # categoría del tenant
            ("product_attribute_definitions", "select"): [_d("FPS", "number")],
        })
        product = ProductCreate(title="Bloqueador", category_id="cat-1",
                                attributes={"FPS": "no-numérico"},
                                variations=[VariationCreate(sku="S1", price=10.0)])
        with self.assertRaises(HTTPException) as cm:
            await self._create(ctrl, product)
        self.assertEqual(cm.exception.status_code, 422)
        self.assertNotIn("products", ctrl.inserts)   # el producto NO se insertó

    async def test_create_ok_when_attributes_valid(self):
        ctrl = _CtrlFull({
            ("product_categories", "select"): [{"id": "cat-1"}],
            ("product_attribute_definitions", "select"): [_d("FPS", "number")],
            ("products", "insert"): [{"id": "prod-1", "title": "Bloqueador"}],
            ("product_variations", "insert"): [{"id": "var-1", "sku": "S1"}],
        })
        product = ProductCreate(title="Bloqueador", category_id="cat-1",
                                attributes={"FPS": "50"},
                                variations=[VariationCreate(sku="S1", price=10.0)])
        await self._create(ctrl, product)
        self.assertIn("products", ctrl.inserts)   # sí se insertó
        self.assertEqual(ctrl.inserts["products"][0]["attributes"], {"FPS": "50"})


if __name__ == "__main__":
    unittest.main()

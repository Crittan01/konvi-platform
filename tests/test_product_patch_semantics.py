"""F2.2 — semántica del PATCH de productos (build_patch_update).

Fija el contrato que permite migrar editProduct (web) a la API SIN perder la capacidad de limpiar
campos opcionales a null: 'campo ausente' = no se toca; 'campo=null' = se limpia; campos
`never_clear` (title/sku/price/stock) protegidos de quedar en null aunque lleguen como null.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from routers.products import (  # noqa: E402
    build_patch_update,
    ProductPatch,
    VariationCreate,
    VariationPatch,
    _PRODUCT_NEVER_CLEAR,
    _VARIATION_NEVER_CLEAR,
)


class ProductPatchSemanticsTests(unittest.TestCase):
    def test_explicit_null_clears_optional_fields(self):
        # editProduct envía estos campos como null cuando el operador los vacía → deben limpiarse.
        p = ProductPatch(title="Jabón", safety_note=None, category_id=None,
                         description=None, retracto_excluded_reason=None)
        data = build_patch_update(p, _PRODUCT_NEVER_CLEAR)
        self.assertEqual(data["title"], "Jabón")
        self.assertIsNone(data["safety_note"])               # se limpia
        self.assertIsNone(data["category_id"])
        self.assertIsNone(data["description"])
        self.assertIsNone(data["retracto_excluded_reason"])

    def test_absent_fields_are_not_touched(self):
        # Un PATCH parcial (solo title) NO debe arrastrar las demás columnas a null.
        p = ProductPatch(title="Solo título")
        data = build_patch_update(p, _PRODUCT_NEVER_CLEAR)
        self.assertEqual(data, {"title": "Solo título"})

    def test_title_protected_from_null(self):
        # title nunca debe quedar en null aunque llegue como null.
        p = ProductPatch(title=None, safety_note=None)
        data = build_patch_update(p, _PRODUCT_NEVER_CLEAR)
        self.assertNotIn("title", data)
        self.assertIsNone(data["safety_note"])               # el resto sí se limpia

    def test_retracto_false_is_applied(self):
        # false ≠ null → debe aplicarse (desmarcar el checkbox de retracto).
        p = ProductPatch(retracto_excluded=False)
        data = build_patch_update(p, _PRODUCT_NEVER_CLEAR)
        self.assertEqual(data["retracto_excluded"], False)

    def test_status_applied_and_protected(self):
        # restore/deactivate envían status; se aplica y nunca se limpia a null.
        self.assertEqual(build_patch_update(ProductPatch(status="active"), _PRODUCT_NEVER_CLEAR)["status"], "active")
        self.assertNotIn("status", build_patch_update(ProductPatch(status=None), _PRODUCT_NEVER_CLEAR))

    def test_variation_create_allows_null_sku_and_attributes(self):
        # Variante única: el web crea sin SKU ni atributos → el contrato debe aceptarlo (antes 422).
        v = VariationCreate(price=10.0, stock_quantity=5)
        self.assertIsNone(v.sku)
        self.assertIsNone(v.attributes)

    def test_variation_protects_price_and_stock(self):
        v = VariationPatch(price=None, stock_quantity=None, image_url=None, compare_at_price=None)
        data = build_patch_update(v, _VARIATION_NEVER_CLEAR)
        self.assertNotIn("price", data)
        self.assertNotIn("stock_quantity", data)
        self.assertIsNone(data["image_url"])                 # opcional → se limpia
        self.assertIsNone(data["compare_at_price"])


if __name__ == "__main__":
    unittest.main()

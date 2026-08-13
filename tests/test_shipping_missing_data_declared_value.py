"""Fundación de envíos (auditoría ecosistema 2026-07-01) — 2 fixes con impacto financiero:

ENVIO-1: un producto SIN weight_kg/dims ya NO se cotiza a ~0.05kg (que dispara el reajuste retroactivo
         de Aveonline que paga el tenant); se bloquea y se escala a un asesor.
ENVIO-2: el valorDeclarado del seguro = subtotal REAL de productos del cart (COP), no el 50.000 hardcoded.
"""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.cart_tool import compute_shipping_inputs  # noqa: E402
from tools.shipping_quote_tool import (  # noqa: E402
    _estimate_package_from_cart_if_available,
    _build_quote_payload,
    PackageEstimate,
)

_FULL_ITEM = {
    "variation_id": "v-ok", "product_id": "p-ok", "quantity": 1, "unit_price_cents": 3000000,
    "variation": {"label": "30ml", "weight_kg": 0.12, "length_cm": 8, "width_cm": 4, "height_cm": 4},
    "product": {"title": "Sérum Facial"},
}
_MISSING_ITEM = {
    "variation_id": "v-nopeso", "product_id": "p-x", "quantity": 1, "unit_price_cents": 5000000,
    "variation": {"label": "Único", "weight_kg": None, "length_cm": None, "width_cm": None, "height_cm": None},
    "product": {"title": "Audífonos Pro"},
}

CART_FULL = {"id": "c1", "subtotal_cents": 3000000, "items": [_FULL_ITEM]}
CART_MISSING = {"id": "c2", "subtotal_cents": 8000000, "items": [_FULL_ITEM, _MISSING_ITEM]}


class ComputeShippingInputsMissingTests(unittest.TestCase):
    def test_full_cart_has_no_missing(self):
        out = compute_shipping_inputs(CART_FULL)
        self.assertEqual(out["missing_shipping_data"], [])
        self.assertGreater(out["billable_weight_kg"], 0)

    def test_item_without_weight_is_flagged_by_title(self):
        out = compute_shipping_inputs(CART_MISSING)
        self.assertIn("Audífonos Pro", out["missing_shipping_data"])
        self.assertEqual(len(out["missing_shipping_data"]), 1)  # solo el que falta


class EstimatePackageTests(unittest.TestCase):
    def _run(self, cart):
        with patch("tools.cart_tool.get_cart_with_items", return_value=cart):
            return _estimate_package_from_cart_if_available(
                supabase=None, tenant_id="t1", conversation_id="conv1",
            )

    def test_missing_weight_blocks_quote(self):
        # ENVIO-1: NO se devuelve package (que se cotizaría a 0.05kg); se señala missing_shipping_data.
        dec = self._run(CART_MISSING)
        self.assertIsNotNone(dec)
        self.assertIsNone(dec.package)
        self.assertIn("Audífonos Pro", dec.missing_shipping_data)

    def test_full_cart_sets_declared_value_from_subtotal_cop(self):
        # ENVIO-2: subtotal_cents 3.000.000 (centavos) → declared_value 30.000 COP (no 50.000 hardcoded).
        dec = self._run(CART_FULL)
        self.assertIsNotNone(dec.package)
        self.assertEqual(dec.package.declared_value, 30000)
        self.assertEqual(dec.missing_shipping_data, [])


class BuildQuotePayloadTests(unittest.TestCase):
    """ENVIO-2 en el 2º path vivo (API /shipping/quote): el parcel DEBE llevar declaredValueCop,
    si no la API cae al 50k hardcoded (bug HIGH que la review adversarial cazó)."""

    def test_parcel_carries_declared_value(self):
        pkg = PackageEstimate(
            weight_kg=0.3, length_cm=10, width_cm=8, height_cm=5, quantity=1,
            product_title="Sérum", declared_value=82000, source="cart_db",
        )
        payload = _build_quote_payload({"city": "Bogota"}, {"city": "Medellin"}, pkg)
        self.assertEqual(payload["parcels"][0]["declaredValueCop"], 82000)


if __name__ == "__main__":
    unittest.main()

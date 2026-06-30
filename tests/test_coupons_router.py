"""F2.2 — validación del router de cupones (espeja validateCouponInput del web)."""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers.coupons import validate_coupon  # noqa: E402


class ValidateCouponTests(unittest.TestCase):
    def test_valid_create(self):
        self.assertIsNone(validate_coupon(
            {"code": "PROMO10", "discount_type": "percent", "discount_value": 10},
            require_code=True))

    def test_bad_code(self):
        self.assertIn("Código", validate_coupon(
            {"code": "ab", "discount_type": "percent", "discount_value": 10}, require_code=True))

    def test_invalid_discount_type(self):
        self.assertIn("Tipo", validate_coupon(
            {"code": "PROMO10", "discount_type": "bogus", "discount_value": 10}, require_code=True))

    def test_percent_over_100(self):
        self.assertIn("Porcentaje", validate_coupon(
            {"discount_type": "percent", "discount_value": 150}, require_code=False))

    def test_negative_value(self):
        self.assertIn("negativo", validate_coupon(
            {"discount_type": "fixed_amount", "discount_value": -5}, require_code=False))

    def test_max_redemptions_zero(self):
        self.assertIn("redenciones", validate_coupon(
            {"discount_type": "percent", "discount_value": 10, "max_redemptions": 0}, require_code=False))

    def test_dates_inverted(self):
        self.assertIn("posterior", validate_coupon(
            {"discount_type": "percent", "discount_value": 10,
             "valid_from": "2026-07-01T00:00", "valid_until": "2026-06-01T00:00"}, require_code=False))

    def test_patch_toggle_only_is_valid(self):
        # Un toggle (solo is_active) no envía campos de descuento → válido.
        self.assertIsNone(validate_coupon({}, require_code=False))

    def test_patch_does_not_require_code(self):
        # PATCH no manda code (inmutable) → no debe fallar por código.
        self.assertIsNone(validate_coupon(
            {"discount_type": "percent", "discount_value": 20}, require_code=False))


if __name__ == "__main__":
    unittest.main()

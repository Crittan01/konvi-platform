"""
Tests API /settings/tenant — certificación campos completos y validaciones.

Cubre:
- GET /tenant retorna los campos nuevos: nit, email_contacto, telefono_contacto, low_stock_threshold
- TenantPatch acepta y valida email_contacto (422 si inválido)
- TenantPatch acepta y valida telefono_contacto (422 si no empieza por 3 con 10 dígitos)
- TenantPatch acepta y valida low_stock_threshold (422 si fuera de rango 1-999)
- TenantPatch acepta nit sin restricción de formato
- store_type solo acepta valores válidos
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from pydantic import ValidationError
from routers.settings import TenantPatch


class TenantPatchValidationTests(unittest.TestCase):
    """Pruebas de validación del modelo TenantPatch."""

    def test_valid_email_contacto_accepted(self):
        p = TenantPatch(email_contacto="contacto@mitienda.com")
        self.assertEqual(p.email_contacto, "contacto@mitienda.com")

    def test_invalid_email_contacto_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(email_contacto="no-es-un-email")

    def test_invalid_email_no_domain_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(email_contacto="usuario@")

    def test_valid_telefono_colombiano_accepted(self):
        p = TenantPatch(telefono_contacto="3121234567")
        self.assertEqual(p.telefono_contacto, "3121234567")

    def test_telefono_with_plus_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(telefono_contacto="+573121234567")

    def test_telefono_not_starting_3_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(telefono_contacto="1234567890")

    def test_telefono_too_short_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(telefono_contacto="312123456")  # 9 digits

    def test_valid_low_stock_threshold(self):
        p = TenantPatch(low_stock_threshold=5)
        self.assertEqual(p.low_stock_threshold, 5)

    def test_low_stock_threshold_zero_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(low_stock_threshold=0)

    def test_low_stock_threshold_too_high_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(low_stock_threshold=1000)

    def test_low_stock_boundary_1_accepted(self):
        p = TenantPatch(low_stock_threshold=1)
        self.assertEqual(p.low_stock_threshold, 1)

    def test_low_stock_boundary_999_accepted(self):
        p = TenantPatch(low_stock_threshold=999)
        self.assertEqual(p.low_stock_threshold, 999)

    def test_nit_no_format_restriction(self):
        p = TenantPatch(nit="900.123.456-7")
        self.assertEqual(p.nit, "900.123.456-7")

    def test_valid_store_type(self):
        for st in ("fisica", "virtual", "fisica_virtual"):
            p = TenantPatch(store_type=st)  # type: ignore
            self.assertEqual(p.store_type, st)

    def test_invalid_store_type_rejected(self):
        with self.assertRaises(ValidationError):
            TenantPatch(store_type="otro")  # type: ignore

    def test_all_fields_none_allowed(self):
        p = TenantPatch()
        self.assertIsNone(p.nit)
        self.assertIsNone(p.email_contacto)
        self.assertIsNone(p.telefono_contacto)
        self.assertIsNone(p.low_stock_threshold)

    def test_multiple_fields_at_once(self):
        p = TenantPatch(
            name="Mi Tienda",
            nit="900.123.456-7",
            email_contacto="hola@mitienda.co",
            telefono_contacto="3001234567",
            low_stock_threshold=10,
        )
        self.assertEqual(p.name, "Mi Tienda")
        self.assertEqual(p.low_stock_threshold, 10)


class TenantGetSelectTests(unittest.TestCase):
    """Verifica que el select de GET /tenant incluye todos los campos necesarios."""

    def test_select_contains_identity_fields(self):
        import inspect
        import routers.settings as settings_module
        source = inspect.getsource(settings_module.get_tenant)
        for field in ("nit", "email_contacto", "telefono_contacto", "low_stock_threshold"):
            self.assertIn(field, source, f"'{field}' no está en el select de get_tenant")

    def test_patch_docstring_mentions_new_fields(self):
        import routers.settings as settings_module
        doc = settings_module.patch_tenant.__doc__ or ""
        for field in ("nit", "email_contacto", "telefono_contacto", "low_stock_threshold"):
            self.assertIn(field, doc, f"'{field}' no está documentado en patch_tenant")


if __name__ == "__main__":
    unittest.main()

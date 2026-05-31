"""Tests del builder de customer_data para Wompi (rev. 68).

Verifica que `_build_customer_data()` arma el bloque correcto según el
contacto provisto, respetando reglas oficiales de Wompi:
- legal_id y legal_id_type van juntos o ninguno.
- phone_number_prefix se separa del número (+57 prefijo + dígitos).
- Solo se incluyen campos no vacíos (Wompi rechaza campos null).
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from integrations.wompi_client import _build_customer_data  # noqa: E402


class CustomerDataBuilderTests(unittest.TestCase):
    def test_none_contact_returns_none(self):
        self.assertIsNone(_build_customer_data(None))
        self.assertIsNone(_build_customer_data({}))

    def test_complete_contact_full_payload(self):
        cd = _build_customer_data({
            "name": "Andrés Pérez",
            "email": "andres@test.com",
            "phone": "+573001234567",
            "document_type": "CC",
            "document_number": "1234567890",
        })
        self.assertEqual(cd["full_name"], "Andrés Pérez")
        self.assertEqual(cd["email"], "andres@test.com")
        self.assertEqual(cd["phone_number_prefix"], "+57")
        self.assertEqual(cd["phone_number"], "3001234567")
        self.assertEqual(cd["legal_id"], "1234567890")
        self.assertEqual(cd["legal_id_type"], "CC")

    def test_email_only_contact(self):
        cd = _build_customer_data({"email": "x@y.com"})
        self.assertEqual(cd, {"email": "x@y.com"})
        self.assertNotIn("full_name", cd)
        self.assertNotIn("legal_id", cd)

    def test_phone_without_57_prefix(self):
        # Rev. 104 (F0-4): canon helper INFIERE prefix CO cuando phone es cel
        # local de 10 dígitos empezando con '3' (3001234567 → 573001234567).
        # Para Wompi, esto produce prefix='+57' + number='3001234567'.
        cd = _build_customer_data({"phone": "3001234567"})
        self.assertEqual(cd.get("phone_number_prefix"), "+57")
        self.assertEqual(cd.get("phone_number"), "3001234567")

    def test_phone_with_plus(self):
        cd = _build_customer_data({"phone": "+573120000000"})
        self.assertEqual(cd["phone_number_prefix"], "+57")
        self.assertEqual(cd["phone_number"], "3120000000")

    def test_document_only_with_one_field_excluded(self):
        # Solo type sin number → no incluye legal_id (regla: van juntos)
        cd = _build_customer_data({"document_type": "CC"})
        self.assertNotIn("legal_id", (cd or {}))
        self.assertNotIn("legal_id_type", (cd or {}))

    def test_document_lowercase_type_normalized_to_upper(self):
        cd = _build_customer_data({
            "document_type": "cc",
            "document_number": "1234567890",
        })
        # El builder hace upper() del type
        self.assertEqual(cd["legal_id_type"], "CC")

    def test_empty_strings_excluded(self):
        # Si todos los campos del contact son vacíos, retorna None
        cd = _build_customer_data({
            "name": "",
            "email": "",
            "phone": "",
            "document_type": "",
            "document_number": "",
        })
        self.assertIsNone(cd)

    def test_only_required_fields_for_pse(self):
        # PSE en práctica requiere full_name + email + legal_id + legal_id_type.
        cd = _build_customer_data({
            "name": "Juan",
            "email": "juan@test.com",
            "document_type": "CC",
            "document_number": "1000000000",
        })
        self.assertIn("full_name", cd)
        self.assertIn("email", cd)
        self.assertIn("legal_id", cd)
        self.assertIn("legal_id_type", cd)


if __name__ == "__main__":
    unittest.main()

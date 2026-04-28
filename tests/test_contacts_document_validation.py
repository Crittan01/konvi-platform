"""Tests del validador de documentos de contacto (rev. 68).

Cubre las reglas de validación implementadas en
services/api/dependencies/contact_validators.py:
- Tipos aceptados (CC, CE, NIT, PP, TI, OTHER) y rechazo de inválidos.
- Reglas de longitud por tipo.
- Normalización (puntos, espacios).
- Address completa según building_type.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from dependencies.contact_validators import (  # noqa: E402
    validate_document,
    normalize_document_number,
    is_address_complete,
    address_required_fields,
    DOCUMENT_TYPES_CO,
)


class DocumentTypeTests(unittest.TestCase):
    def test_co_types_set(self):
        self.assertEqual(DOCUMENT_TYPES_CO, frozenset({"CC", "CE", "NIT", "PP", "TI", "OTHER"}))

    def test_normalize_strips_dots_and_spaces(self):
        self.assertEqual(normalize_document_number("1.234.567"), "1234567")
        self.assertEqual(normalize_document_number(" 12 34 56 "), "123456")
        self.assertEqual(normalize_document_number(None), None)
        self.assertEqual(normalize_document_number(""), None)

    def test_validate_both_none_ok(self):
        self.assertIsNone(validate_document(None, None))

    def test_validate_one_missing_fails(self):
        self.assertIsNotNone(validate_document("CC", None))
        self.assertIsNotNone(validate_document(None, "12345678"))

    def test_validate_invalid_type_rejected(self):
        err = validate_document("INVALID", "12345678")
        self.assertIsNotNone(err)
        self.assertIn("inválido", err)

    def test_validate_cc_accepts_8_digits(self):
        self.assertIsNone(validate_document("CC", "12345678"))

    def test_validate_cc_rejects_letters(self):
        err = validate_document("CC", "ABC12345")
        self.assertIsNotNone(err)
        self.assertIn("dígitos", err)

    def test_validate_cc_rejects_too_short(self):
        err = validate_document("CC", "12345")  # 5 dígitos < 6
        self.assertIsNotNone(err)
        self.assertIn("entre 6 y 12", err)

    def test_validate_nit_accepts_with_dv(self):
        self.assertIsNone(validate_document("NIT", "900123456-7"))

    def test_validate_nit_accepts_without_dv(self):
        self.assertIsNone(validate_document("NIT", "900123456"))

    def test_validate_ti_accepts(self):
        self.assertIsNone(validate_document("TI", "10234567890"))


class AddressCompleteTests(unittest.TestCase):
    def test_empty_address_incomplete(self):
        ok, missing = is_address_complete(None)
        self.assertFalse(ok)
        self.assertGreater(len(missing), 0)

    def test_casa_required_fields(self):
        self.assertEqual(
            address_required_fields("casa"),
            ["street", "neighborhood", "city", "state", "dane_code"],
        )

    def test_edificio_requires_apartment(self):
        self.assertIn("apartment", address_required_fields("edificio"))

    def test_conjunto_requires_tower_apartment(self):
        req = address_required_fields("conjunto")
        self.assertIn("tower", req)
        self.assertIn("apartment", req)

    def test_complete_casa_address(self):
        addr = {
            "street": "Calle 10 # 5-23",
            "neighborhood": "Chapinero",
            "city": "Bogotá",
            "state": "DC",
            "dane_code": "11001000",
            "building_type": "casa",
        }
        ok, missing = is_address_complete(addr)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_incomplete_edificio_missing_apartment(self):
        addr = {
            "street": "Calle 10",
            "neighborhood": "X",
            "city": "Bogotá",
            "state": "DC",
            "dane_code": "11001000",
            "building_type": "edificio",
            # falta apartment
        }
        ok, missing = is_address_complete(addr)
        self.assertFalse(ok)
        self.assertIn("apartment", missing)

    def test_invalid_building_type_returns_error(self):
        ok, errs = is_address_complete({"building_type": "carpa"})
        self.assertFalse(ok)
        self.assertTrue(any("building_type inv" in e for e in errs))


if __name__ == "__main__":
    unittest.main()

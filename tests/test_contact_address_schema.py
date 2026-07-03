"""Tests del schema canónico contacts.address rev. 110 — A2 finiquito 2026-06-23.

Single-source-of-truth Pydantic: `agentic.tools.contact.SaveAddressArgs`
+ migration `supabase/migrations/20260429000000_contacts_document_and_address.sql`.

Política A2: campos NUEVOS (state, country, dane_code, complex_name,
company_name) son OPCIONALES para NO romper contrato tool de Gemini.
state/dane_code se resuelven server-side via DIVIPOLA cuando no llegan.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from pydantic import ValidationError

from agentic.tools.contact import SaveAddressArgs, _build_address_dict


class TestContactAddressCanonical(unittest.TestCase):
    """Shape canónico — required minimal + opcionales completos."""

    def test_residencial_minima_required(self):
        """street + city + building_type bastan (mínimo canónico rev. 110)."""
        addr = SaveAddressArgs(
            street="Calle 10 #5-23",
            city="Bogotá",
            building_type="casa",
        )
        self.assertEqual(addr.street, "Calle 10 #5-23")
        self.assertEqual(addr.city, "Bogotá")
        self.assertEqual(addr.building_type, "casa")

    def test_residencial_completa_canonica(self):
        addr = SaveAddressArgs(
            street="Calle 10 #5-23",
            city="Bogotá",
            neighborhood="Chapinero",
            state="Cundinamarca",
            dane_code="11001000",
            building_type="casa",
            country="CO",
        )
        self.assertEqual(addr.state, "Cundinamarca")
        self.assertEqual(addr.dane_code, "11001000")

    def test_falta_street_falla(self):
        with self.assertRaises(ValidationError):
            SaveAddressArgs(
                city="Bogotá", neighborhood="Chapinero",
                state="DC", dane_code="11001000", building_type="casa",
            )

    def test_falta_city_falla(self):
        with self.assertRaises(ValidationError):
            SaveAddressArgs(
                street="Calle X", building_type="casa",
            )

    def test_falta_building_type_falla(self):
        with self.assertRaises(ValidationError):
            SaveAddressArgs(
                street="Calle X", city="Bogotá",
            )

    def test_building_type_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            SaveAddressArgs(
                street="Calle X", city="Bogotá", building_type="bunker",
            )


class TestBuildAddressDict(unittest.TestCase):
    """`_build_address_dict` persiste shape canónico, NUNCA `line1`."""

    def test_no_persiste_line1(self):
        args = SaveAddressArgs(
            street="Calle 10 #5-23", city="Bogotá", building_type="casa",
        )
        d = _build_address_dict(args)
        self.assertNotIn("line1", d)
        self.assertIn("street", d)
        self.assertEqual(d["street"], "Calle 10 #5-23")

    def test_street_persiste_verbatim_sin_dian(self):
        """F31: el street se persiste tal cual (case + '#' preservados), NUNCA
        uppercased/abreviado DIAN. Tras remover la normalización DIAN muerta del
        path legacy, ambos paths (agentic + legacy) almacenan el formato humano
        legible. Guarda contra reintroducir normalize-on-write."""
        args = SaveAddressArgs(
            street="Calle 36A # 6-87", city="Bogotá", building_type="casa",
        )
        d = _build_address_dict(args)
        self.assertEqual(d["street"], "Calle 36A # 6-87")
        self.assertNotEqual(d["street"], d["street"].upper())

    def test_persiste_opcionales_cuando_presentes(self):
        args = SaveAddressArgs(
            street="Calle 10", city="Bogotá", building_type="casa",
            state="Cundinamarca", country="CO",
            neighborhood="Chapinero",
        )
        d = _build_address_dict(args)
        self.assertEqual(d.get("state"), "Cundinamarca")
        self.assertEqual(d.get("country"), "CO")
        self.assertEqual(d.get("neighborhood"), "Chapinero")

    def test_dane_code_pasthrough_si_provee(self):
        args = SaveAddressArgs(
            street="Calle 10", city="Bogotá", building_type="casa",
            dane_code="11001000",
        )
        d = _build_address_dict(args)
        self.assertEqual(d.get("dane_code"), "11001000")

    def test_oficina_company_name_persistido(self):
        args = SaveAddressArgs(
            street="Av 1", city="Bogotá", building_type="oficina",
            apartment="501", company_name="Acme S.A.S.",
        )
        d = _build_address_dict(args)
        self.assertEqual(d.get("company_name"), "Acme S.A.S.")
        self.assertEqual(d.get("apartment"), "501")


if __name__ == "__main__":
    unittest.main()

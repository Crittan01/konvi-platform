"""Rev. 91 — Tests del extractor multi-slot.

Cubre el caso S6: cliente envía dump combinado tras consent question:
  "Soy Cristian Garzón, correo crittan01@gmail.com, CC 1032414179,
   dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá"

El extractor debe sacar email + name + (doc_type, doc_number) +
address.{city,street} en una sola pasada determinística.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from slot_extractors import (  # noqa: E402
    extract_email,
    extract_name,
    extract_document,
    extract_city,
    extract_street,
    extract_all_slots,
)


class EmailExtractorTests(unittest.TestCase):

    def test_simple_email(self):
        self.assertEqual(extract_email("mi correo es foo@bar.com"), "foo@bar.com")

    def test_email_in_dump(self):
        text = ("Soy Cristian Garzón, correo crittan01@gmail.com, "
                "CC 1032414179")
        self.assertEqual(extract_email(text), "crittan01@gmail.com")

    def test_no_email(self):
        self.assertIsNone(extract_email("Hola, soy Juan"))

    def test_lowercase_normalization(self):
        self.assertEqual(extract_email("Mi mail: User@DOMAIN.com"), "user@domain.com")


class NameExtractorTests(unittest.TestCase):

    def test_soy_pattern(self):
        self.assertEqual(extract_name("Soy Cristian Garzón"), "Cristian Garzón")

    def test_me_llamo(self):
        self.assertEqual(extract_name("Me llamo Juan Pérez"), "Juan Pérez")

    def test_mi_nombre_es(self):
        self.assertEqual(extract_name("Mi nombre es Ana María"), "Ana María")

    def test_in_dump(self):
        text = ("Soy Cristian Garzón, correo crittan01@gmail.com, "
                "CC 1032414179")
        self.assertEqual(extract_name(text), "Cristian Garzón")

    def test_no_match_when_no_preamble(self):
        # "Cristian Garzón" sin "soy" no se extrae — evita falsos positivos.
        self.assertIsNone(extract_name("Cristian Garzón aquí"))

    def test_yes_response_not_a_name(self):
        # "Sí, esa opción" NO debe extraerse como nombre.
        self.assertIsNone(extract_name("Sí, esa opción"))


class DocumentExtractorTests(unittest.TestCase):

    def test_cc_with_number(self):
        out = extract_document("CC 1032414179")
        self.assertEqual(out, ("CC", "1032414179"))

    def test_cc_with_dots_in_number(self):
        out = extract_document("CC 1.032.414.179")
        self.assertEqual(out, ("CC", "1032414179"))

    def test_ce_pattern(self):
        out = extract_document("CE 123456")
        self.assertEqual(out, ("CE", "123456"))

    def test_nit(self):
        self.assertEqual(extract_document("NIT 900123456"), ("NIT", "900123456"))

    def test_in_dump(self):
        text = ("Soy Cristian Garzón, correo crittan01@gmail.com, "
                "CC 1032414179, dirección Calle 3 sur 70-84")
        self.assertEqual(extract_document(text), ("CC", "1032414179"))

    def test_no_type_no_match(self):
        # Solo dígitos sin tipo → ambiguo, NO extraer.
        self.assertIsNone(extract_document("1032414179"))


class CityExtractorTests(unittest.TestCase):

    def test_bogota_with_accent(self):
        self.assertEqual(extract_city("envíalo a Bogotá"), "Bogotá")

    def test_bogota_no_accent(self):
        self.assertEqual(extract_city("envialo a bogota"), "Bogotá")

    def test_medellin(self):
        self.assertEqual(extract_city("para Medellín"), "Medellín")

    def test_in_dump(self):
        text = "dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá"
        self.assertEqual(extract_city(text), "Bogotá")

    def test_no_city(self):
        self.assertIsNone(extract_city("hola amigo"))


class StreetExtractorTests(unittest.TestCase):

    def test_calle_with_number(self):
        out = extract_street("Calle 3 sur 70-84, barrio Olaya")
        self.assertIsNotNone(out)
        self.assertIn("calle 3", out.lower())

    def test_carrera(self):
        out = extract_street("Carrera 70 # 12-34")
        self.assertIsNotNone(out)


class ExtractAllSlotsDumpTests(unittest.TestCase):
    """Caso S6 directo: el extractor debe sacar TODOS los campos del dump."""

    def test_full_dump_s6(self):
        text = (
            "Soy Cristian Garzón, correo crittan01@gmail.com, "
            "CC 1032414179, dirección Calle 3 sur 70-84, "
            "barrio Olaya, casa, Bogotá"
        )
        slots = extract_all_slots(text)
        self.assertEqual(slots.get("email"), "crittan01@gmail.com")
        self.assertEqual(slots.get("name"), "Cristian Garzón")
        self.assertEqual(slots.get("document_type"), "CC")
        self.assertEqual(slots.get("document_number"), "1032414179")
        addr = slots.get("address") or {}
        self.assertEqual(addr.get("city"), "Bogotá")
        self.assertIsNotNone(addr.get("street"))

    def test_partial_dump(self):
        # Solo email + nombre — los demás slots ausentes.
        text = "Hola, soy Juan, mi correo es juan@example.com"
        slots = extract_all_slots(text)
        self.assertEqual(slots.get("email"), "juan@example.com")
        self.assertEqual(slots.get("name"), "Juan")
        self.assertNotIn("document_type", slots)
        self.assertNotIn("address", slots)

    def test_empty_text(self):
        self.assertEqual(extract_all_slots(""), {})

    def test_yes_no_extracts_nothing(self):
        self.assertEqual(extract_all_slots("Sí"), {})
        self.assertEqual(extract_all_slots("Sigamos con la compra por favor"), {})


if __name__ == "__main__":
    unittest.main()

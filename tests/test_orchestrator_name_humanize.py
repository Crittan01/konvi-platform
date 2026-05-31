"""
Tests de humanización de nombre en respuestas del Orchestrator.

Cubre:
- Nombre completo reemplazado por primer nombre
- Variaciones de casing (title, upper, lower)
- Sin nombre de contacto → sin cambios
- extracted_name distinto a contact_name → ambos reemplazados
- Texto sin ocurrencias → sin cambios
- Solo primer nombre → sin cambios
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _humanize_name_in_text


class OrchestratorNameHumanizeTests(unittest.TestCase):
    def test_replaces_full_name_with_first_name(self):
        text = "Perfecto, Cristian Camilo Garzon Tamayo. Tu pedido está listo."
        result = _humanize_name_in_text(text, "Cristian Camilo Garzon Tamayo", None)
        self.assertEqual(result, "Perfecto, Cristian. Tu pedido está listo.")

    def test_replaces_title_case_variant(self):
        text = "Gracias, Cristian Camilo Garzon Tamayo"
        result = _humanize_name_in_text(text, "cristian camilo garzon tamayo", None)
        # Title case variant: "Cristian Camilo Garzon Tamayo" → reemplaza por primer nombre title-case
        self.assertEqual(result, "Gracias, Cristian")

    def test_replaces_upper_case_variant(self):
        text = "Hola, CRISTIAN CAMILO GARZON TAMAYO"
        result = _humanize_name_in_text(text, "Cristian Camilo Garzon Tamayo", None)
        self.assertEqual(result, "Hola, Cristian")

    def test_no_change_when_no_full_name(self):
        text = "Hola, ¿en qué puedo ayudarte?"
        result = _humanize_name_in_text(text, "Cristian Camilo Garzon Tamayo", None)
        self.assertEqual(result, text)

    def test_no_change_when_only_first_name(self):
        text = "Hola, Cristian"
        result = _humanize_name_in_text(text, "Cristian", None)
        self.assertEqual(result, text)

    def test_replaces_both_contact_and_extracted_name(self):
        text = "Cristian Camilo Garzon Tamayo y Juan Pablo Perez Garcia"
        result = _humanize_name_in_text(
            text,
            "Cristian Camilo Garzon Tamayo",
            "Juan Pablo Perez Garcia",
        )
        self.assertEqual(result, "Cristian y Juan")

    def test_none_names_no_crash(self):
        text = "Hola, ¿en qué puedo ayudarte?"
        result = _humanize_name_in_text(text, None, None)
        self.assertEqual(result, text)

    def test_empty_text_no_crash(self):
        result = _humanize_name_in_text("", "Cristian Camilo Garzon Tamayo", None)
        self.assertEqual(result, "")

    def test_extracted_name_replaced_when_contact_name_missing(self):
        text = "Perfecto, Maria Paula Rodriguez Lopez"
        result = _humanize_name_in_text(text, None, "Maria Paula Rodriguez Lopez")
        self.assertEqual(result, "Perfecto, Maria")

    def test_replaces_full_name_with_irregular_spaces(self):
        text = "Perfecto, Cristian   Camilo   Garzon   Tamayo. Seguimos?"
        result = _humanize_name_in_text(text, "Cristian Camilo Garzon Tamayo", None)
        self.assertEqual(result, "Perfecto, Cristian. Seguimos?")

    def test_replaces_full_name_with_line_breaks(self):
        text = "Hola Cristian\nCamilo Garzon Tamayo, confirmo tu pedido."
        result = _humanize_name_in_text(text, "Cristian Camilo Garzon Tamayo", None)
        self.assertEqual(result, "Hola Cristian, confirmo tu pedido.")


if __name__ == "__main__":
    unittest.main()

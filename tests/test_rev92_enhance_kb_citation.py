"""Rev. 92 — Tests del post-process de citas KB.

Convierte `_Fuente: TITLE_` (etiqueta colgada en cursiva) en
blockquote `> Fuente: TITLE` + agrega CTA invitacional, ya que el
schema de KB no tiene URL pública del documento.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from orchestrator import _enhance_kb_citation, _format_whatsapp_response_text  # noqa: E402


class EnhanceKbCitationTests(unittest.TestCase):

    def test_replaces_italic_cite_with_blockquote_plus_cta(self):
        text = (
            "Aceptamos devoluciones dentro de los 15 días calendario.\n\n"
            "_Fuente: Política de devoluciones y cambios_"
        )
        out = _enhance_kb_citation(text)
        self.assertIn("> Fuente: Política de devoluciones y cambios", out)
        self.assertIn("házmelo saber", out)
        self.assertNotIn("_Fuente:", out)

    def test_inserts_blank_line_before_cta_when_cite_glued_to_body(self):
        """LLM a veces pega `_Fuente:_` directo al cuerpo sin blank line.
        El post-process debe garantizar `\\n\\n` antes del CTA."""
        text = (
            "Aceptamos devoluciones dentro de los 15 días calendario.\n"
            "_Fuente: Política de devoluciones y cambios_"
        )
        out = _enhance_kb_citation(text)
        # Debe haber blank line entre el cuerpo y el CTA.
        self.assertIn("calendario.\n\nSi quieres", out)
        # Y blank line entre CTA y cite.
        self.assertIn("házmelo saber.\n\n> Fuente:", out)

    def test_no_triple_newlines(self):
        """No debe acumular saltos (\\n\\n\\n) en la sustitución."""
        text = (
            "Política aquí.\n\n\n\n"
            "_Fuente: Política X_"
        )
        out = _enhance_kb_citation(text)
        self.assertNotIn("\n\n\n", out)

    def test_no_modification_when_no_cite(self):
        text = "Aceptamos devoluciones dentro de los 15 días calendario."
        out = _enhance_kb_citation(text)
        self.assertEqual(out, text)

    def test_idempotent_when_blockquote_already_present(self):
        text = (
            "Política aquí.\n\n"
            "Si quieres que te amplíe algún punto, házmelo saber.\n\n"
            "> Fuente: Política X"
        )
        out = _enhance_kb_citation(text)
        self.assertEqual(out, text)

    def test_does_not_duplicate_cta_if_present(self):
        text = (
            "Política aquí.\n\n"
            "Si quieres que te amplíe algún punto, házmelo saber.\n\n"
            "_Fuente: Política X_"
        )
        out = _enhance_kb_citation(text)
        # El CTA ya existía → no se duplica, solo se transforma la cita.
        self.assertEqual(out.count("házmelo saber"), 1)
        self.assertIn("> Fuente: Política X", out)

    def test_preserves_title_with_special_chars(self):
        text = "Info.\n\n_Fuente: Política de envíos & devoluciones_"
        out = _enhance_kb_citation(text)
        self.assertIn("> Fuente: Política de envíos & devoluciones", out)

    def test_only_first_cite_transformed_when_multiple(self):
        # Caso defensivo: si por algún motivo hay dos citas, solo
        # transforma la primera (las múltiples son edge case raro).
        text = (
            "Info A.\n\n_Fuente: Doc A_\n\nInfo B.\n\n_Fuente: Doc B_"
        )
        out = _enhance_kb_citation(text)
        self.assertIn("> Fuente: Doc A", out)
        # La segunda queda intacta (rare edge — si se necesita transformar
        # múltiples, ampliar la implementación).


class FormatPipelineIntegrationTests(unittest.TestCase):

    def test_format_pipeline_enhances_kb_cite(self):
        text = (
            "Aceptamos devoluciones dentro de los 15 días.\n\n"
            "_Fuente: Política de devoluciones y cambios_"
        )
        out = _format_whatsapp_response_text(text)
        self.assertIn("> Fuente: Política de devoluciones y cambios", out)
        self.assertIn("házmelo saber", out)


if __name__ == "__main__":
    unittest.main()

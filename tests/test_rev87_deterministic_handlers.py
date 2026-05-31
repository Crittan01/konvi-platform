"""Rev. 87 — Tests de handlers determinísticos.

Filosofía: el LLM redacta, el código decide. Cada handler asegura una
ruta crítica que NO depende de la disciplina del LLM.

Tests:
  • _truncate_at_first_question — UX "1 pregunta por turno"
  • _detect_shipping_location_change — re-cotización tras cambio de
    ubicación post-quote
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _truncate_at_first_question,
    _detect_shipping_location_change,
)


class TruncateFirstQuestionTests(unittest.TestCase):

    def test_two_questions_truncates(self):
        text = ("Listo, *60g*. ¿A qué ciudad te enviamos? "
                "¿Y qué tipo de piel tienes?")
        out = _truncate_at_first_question(text)
        self.assertIn("¿A qué ciudad te enviamos?", out)
        self.assertNotIn("piel", out)

    def test_single_question_unchanged(self):
        text = "Perfecto. ¿Confirmas para generar el link de pago?"
        out = _truncate_at_first_question(text)
        self.assertEqual(out, text)

    def test_no_questions_unchanged(self):
        text = "Perfecto, tu pedido fue confirmado."
        out = _truncate_at_first_question(text)
        self.assertEqual(out, text)

    def test_three_questions_truncates_to_first(self):
        text = "Hola. ¿En qué ayudo? ¿Quieres catálogo? ¿O cotizar?"
        out = _truncate_at_first_question(text)
        # Debe conservar la primera pregunta y descartar las siguientes.
        self.assertIn("¿En qué ayudo?", out)
        self.assertNotIn("catálogo?", out)
        self.assertNotIn("cotizar?", out)

    def test_empty_text(self):
        self.assertEqual(_truncate_at_first_question(""), "")
        self.assertEqual(_truncate_at_first_question(None), None)


class ShippingLocationChangeTests(unittest.TestCase):

    def _quoted_outbound(self):
        return {
            "direction": "outbound",
            "content": ("Envío a Bogotá D.C.: *Económica* Servientrega "
                       "$6.740 entrega 1-2 días."),
        }

    def test_cambia_envio_a_medellin(self):
        history = [self._quoted_outbound()]
        out = _detect_shipping_location_change(
            "cambia el envío a Medellín", history,
        )
        self.assertEqual(out, "Medellin")

    def test_envialo_a_oficina_en_cali(self):
        history = [self._quoted_outbound()]
        out = _detect_shipping_location_change(
            "envíalo a la oficina en Cali", history,
        )
        self.assertEqual(out, "Cali")

    def test_mejor_a_bucaramanga(self):
        history = [self._quoted_outbound()]
        out = _detect_shipping_location_change(
            "mejor a Bucaramanga", history,
        )
        self.assertEqual(out, "Bucaramanga")

    def test_no_quote_history_no_detect(self):
        # Sin cotización previa, el detector NO debe gatillar.
        history = [{"direction": "outbound", "content": "Hola, soy Sara."}]
        out = _detect_shipping_location_change(
            "cambia el envío a Medellín", history,
        )
        self.assertIsNone(out)

    def test_no_change_phrase_no_detect(self):
        history = [self._quoted_outbound()]
        out = _detect_shipping_location_change(
            "Bogotá está bien", history,
        )
        self.assertIsNone(out)

    def test_cambia_la_ubicacion(self):
        # Frase que el usuario sugirió ("ubicación", no "ciudad")
        history = [self._quoted_outbound()]
        out = _detect_shipping_location_change(
            "cambia la ubicación a Manizales", history,
        )
        self.assertEqual(out, "Manizales")

    def test_change_to_pereira(self):
        history = [self._quoted_outbound()]
        out = _detect_shipping_location_change(
            "ya no a Bogotá, mándalo a Pereira", history,
        )
        self.assertEqual(out, "Pereira")


if __name__ == "__main__":
    unittest.main()

"""
Rev. 77 — Tests del formato canónico WhatsApp.

Canon definido tras consulta a FAQ oficial de WhatsApp:
  https://faq.whatsapp.com/539178204879377
  > "Listas con viñetas: Escribe un asterisco o guion seguido de espacio"

Por lo tanto el formato NATIVO es `* item`. Esta función normaliza variantes
(`•`, `-`, `·`, `+`) hacia `* ` para usar el render oficial de WhatsApp.

Valida `_format_whatsapp_response_text` aplica:
  1. Bullets variantes (`•`, `-`, `·`, `+`) → `* ` Unicode/canon WhatsApp.
  2. `* item` ya correcto se respeta (idempotente).
  3. Markdown `**bold**` → `*bold*` (WhatsApp usa un solo asterisco para negrita).
  4. Espaciado correcto entre secciones y antes de preguntas.
  5. Citas `> texto` se preservan intactas.
  6. Trim + colapsar saltos múltiples.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _format_whatsapp_response_text  # noqa: E402


class BulletNormalizationTests(unittest.TestCase):

    def test_unicode_bullet_normalized_to_asterisk(self):
        text = "Productos:\n• Item A\n• Item B"
        out = _format_whatsapp_response_text(text)
        self.assertIn("* Item A", out)
        self.assertIn("* Item B", out)
        self.assertNotIn("• Item", out)

    def test_dash_normalized_to_asterisk(self):
        text = "Productos:\n- Item A\n- Item B"
        out = _format_whatsapp_response_text(text)
        self.assertIn("* Item A", out)
        self.assertIn("* Item B", out)

    def test_middot_normalized(self):
        text = "Productos:\n· Item A"
        out = _format_whatsapp_response_text(text)
        self.assertIn("* Item A", out)

    def test_plus_normalized(self):
        text = "Productos:\n+ Item A"
        out = _format_whatsapp_response_text(text)
        self.assertIn("* Item A", out)

    def test_already_canonical_asterisk_idempotent(self):
        """`* item` ya está en formato canónico — no lo toca."""
        text = "Productos:\n* Item A\n* Item B"
        out = _format_whatsapp_response_text(text)
        self.assertEqual(out.count("* Item"), 2)

    def test_inline_bold_not_confused_with_bullet(self):
        """`*texto*` inline (negrita) NO debe convertirse en bullet."""
        text = "El total es *$24.740 COP*"
        out = _format_whatsapp_response_text(text)
        self.assertIn("*$24.740 COP*", out)
        # No debe haber un bullet falso
        self.assertNotIn("\n* $24.740", out)

    def test_indented_bullet_normalized(self):
        """Sub-bullet con sangría también se normaliza."""
        text = "Lista:\n  - Sub item"
        out = _format_whatsapp_response_text(text)
        self.assertIn("* Sub item", out)


class BoldNormalizationTests(unittest.TestCase):

    def test_double_asterisk_to_single(self):
        """Markdown estándar `**bold**` → WhatsApp `*bold*`."""
        text = "El **TOTAL** es **$24.740**"
        out = _format_whatsapp_response_text(text)
        self.assertIn("*TOTAL*", out)
        self.assertIn("*$24.740*", out)
        self.assertNotIn("**", out)

    def test_single_asterisk_unchanged(self):
        text = "El *TOTAL* es *$24.740*"
        out = _format_whatsapp_response_text(text)
        self.assertEqual(out.count("*"), 4)


class SpacingTests(unittest.TestCase):

    def test_bullet_after_colon_no_inline(self):
        """`Productos: * item` debe convertirse en `Productos:\\n* item`."""
        text = "Productos: * Coco"
        out = _format_whatsapp_response_text(text)
        self.assertIn("Productos:\n* Coco", out)

    def test_question_separated_from_bullet(self):
        # Rev. 104 — el `¿` se conserva durante separación de párrafos pero
        # se strip al final (estilo WhatsApp casual colombiano).
        text = "* Item A ¿Confirmas?"
        out = _format_whatsapp_response_text(text)
        self.assertIn("\n\nConfirmas?", out)
        self.assertNotIn("¿", out)

    def test_question_separated_from_sentence(self):
        text = "El total es $50.000. ¿Confirmas?"
        out = _format_whatsapp_response_text(text)
        self.assertIn(".\n\nConfirmas?", out)
        self.assertNotIn("¿", out)

    def test_collapse_excessive_newlines(self):
        text = "Línea 1\n\n\n\nLínea 2"
        out = _format_whatsapp_response_text(text)
        self.assertNotIn("\n\n\n", out)
        self.assertIn("\n\n", out)


class QuotePreservationTests(unittest.TestCase):
    """Citas `> texto` deben pasar intactas (formato oficial WhatsApp)."""

    def test_quote_preserved(self):
        text = "> Calle 3 sur # 70-84\n\nConfirmado, Cristian."
        out = _format_whatsapp_response_text(text)
        self.assertIn("> Calle 3 sur # 70-84", out)
        self.assertIn("Confirmado, Cristian.", out)

    def test_quote_with_question_after(self):
        # Rev. 104 — `¿` se strip al final.
        text = "> Pedido #123\n\nEstá en proceso. ¿Algo más?"
        out = _format_whatsapp_response_text(text)
        self.assertIn("> Pedido #123", out)
        self.assertIn(".\n\nAlgo más?", out)
        self.assertNotIn("¿", out)


class CanonicalSummaryFormatTests(unittest.TestCase):
    """Asegura que el patrón canónico se preserva tras post-process."""

    def test_canonical_summary_preserved(self):
        # Rev. 104 — el canónico oficial NO incluye opening `¿` (estilo
        # WhatsApp casual colombiano). El input ahora se construye sin `¿`
        # y el formato es idempotente.
        canonical = (
            "📋 *Resumen de tu pedido:*\n\n"
            "*Productos:*\n"
            "* 1x Jabón Artesanal de Coco (Presentación: 60g): $18.000 COP\n\n"
            "Subtotal: $18.000 COP\n"
            "Envío: $6.740 COP\n"
            "*TOTAL: $24.740 COP*\n\n"
            "*Datos de envío:*\n"
            "* Nombre: Cristian Garzon\n"
            "* Correo: crittan01@gmail.com\n"
            "* Celular: +57 312 583 5649\n"
            "* Documento: CC 1032414179\n"
            "* Dirección: Calle 3 sur 70-84 — Bogotá\n\n"
            "Confirmas que los datos están correctos para generar tu link de pago?"
        )
        out = _format_whatsapp_response_text(canonical)
        # Idempotente
        self.assertEqual(canonical, out)

    def test_llm_emits_markdown_with_unicode_bullets(self):
        """Caso real: LLM emite markdown con `**` y `•` mezclados.
        Post-process lleva todo al canónico WhatsApp."""
        markdown = (
            "**Resumen de tu pedido:**\n\n"
            "**Productos:**\n"
            "• 1x Coco (60g): $18.000\n"
            "• 2x Lavanda (150g): $64.000\n\n"
            "**TOTAL: $82.000**"
        )
        out = _format_whatsapp_response_text(markdown)
        # Negrita normalizada
        self.assertIn("*Resumen de tu pedido:*", out)
        self.assertIn("*Productos:*", out)
        self.assertIn("*TOTAL: $82.000*", out)
        self.assertNotIn("**", out)
        # Bullets canonizados
        self.assertIn("* 1x Coco", out)
        self.assertIn("* 2x Lavanda", out)
        self.assertNotIn("• ", out)


class CasualPunctuationStripTests(unittest.TestCase):
    """Rev. 104 — Estilo WhatsApp casual colombiano: los signos de apertura
    `¡` `¿` se remueven del outbound, solo se preservan los de cierre."""

    def test_strips_opening_exclamation(self):
        out = _format_whatsapp_response_text("¡Hola, Cristian!")
        self.assertEqual(out, "Hola, Cristian!")

    def test_strips_opening_question(self):
        out = _format_whatsapp_response_text("¿En qué te puedo ayudar?")
        self.assertEqual(out, "En qué te puedo ayudar?")

    def test_preserves_closing_punctuation(self):
        # `!` seguido de `?` → format separa en párrafos (regla pre-existente)
        # + post-process strip `¡` `¿`. Resultado: 2 líneas independientes.
        out = _format_whatsapp_response_text("¡Listo! ¿Algo más?")
        self.assertEqual(out, "Listo!\n\nAlgo más?")
        self.assertIn("!", out)
        self.assertIn("?", out)
        self.assertNotIn("¡", out)
        self.assertNotIn("¿", out)

    def test_strips_in_long_compound_sentence(self):
        text = (
            "¡Buenas tardes! Soy *Sara Camila* de *KAIU Living Natural*. "
            "¿En qué te puedo ayudar?"
        )
        out = _format_whatsapp_response_text(text)
        self.assertNotIn("¡", out)
        self.assertNotIn("¿", out)
        self.assertIn("Buenas tardes!", out)
        self.assertIn("En qué te puedo ayudar?", out)
        # Preserva markdown
        self.assertIn("*Sara Camila*", out)

    def test_strips_within_bullet_list(self):
        text = (
            "*Productos:*\n"
            "* 1x Coco — $18.000\n"
            "* 2x Lavanda — $36.000\n\n"
            "¿Te ayudo con el envío?"
        )
        out = _format_whatsapp_response_text(text)
        self.assertNotIn("¿", out)
        self.assertIn("Te ayudo con el envío?", out)
        # Bullets intactos
        self.assertIn("* 1x Coco", out)
        self.assertIn("* 2x Lavanda", out)

    def test_idempotent_on_already_clean_text(self):
        clean = "Hola! Cómo te ayudo?"
        out = _format_whatsapp_response_text(clean)
        self.assertEqual(out, clean)


if __name__ == "__main__":
    unittest.main()

"""Rev. 92 — Tests del post-process determinístico de listados de catálogo.

Garantiza UX consistente independiente de la obediencia del LLM al
prompt: por categoría, MÁXIMO 2 ítems + `* _Entre otros..._` cuando
hay ≥3, y cita marketing al final si al menos una categoría fue
truncada.

Skips: nunca toca resúmenes (`📋`, `*TOTAL:`, `*Resumen`), cotizaciones
(`Económica`, `transportadora`), ni textos sin categorías.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _truncate_category_listings  # noqa: E402


class TruncateCategoryListingsTests(unittest.TestCase):

    def test_category_with_4_items_truncated_to_2_plus_entre_otros(self):
        text = (
            "*Aceites vegetales:*\n"
            "* Aceite de Almendras Dulces\n"
            "* Aceite de Argán\n"
            "* Aceite de Coco Virgen\n"
            "* Aceite de Rosa Mosqueta"
        )
        out = _truncate_category_listings(text)
        self.assertIn("* Aceite de Almendras Dulces", out)
        self.assertIn("* Aceite de Argán", out)
        self.assertNotIn("Aceite de Coco Virgen", out)
        self.assertNotIn("Aceite de Rosa Mosqueta", out)
        self.assertIn("* _Entre otros..._", out)

    def test_appends_marketing_cite_when_truncation_happened(self):
        text = (
            "*Jabones artesanales:*\n"
            "* Avena y Miel\n"
            "* Coco\n"
            "* Lavanda\n"
            "* Menta y Eucalipto"
        )
        out = _truncate_category_listings(text)
        self.assertIn("> _Tenemos muchas más referencias para ti", out)

    def test_category_with_2_items_kept_intact(self):
        text = (
            "*Sérums faciales:*\n"
            "* Vitamina C\n"
            "* Ácido Hialurónico"
        )
        out = _truncate_category_listings(text)
        self.assertIn("* Vitamina C", out)
        self.assertIn("* Ácido Hialurónico", out)
        self.assertNotIn("Entre otros", out)
        # No marketing cite si nada fue truncado.
        self.assertNotIn("Tenemos muchas más referencias", out)

    def test_category_with_1_item_kept_intact(self):
        text = (
            "*Bálsamos:*\n"
            "* Bálsamo Reparador"
        )
        out = _truncate_category_listings(text)
        self.assertIn("* Bálsamo Reparador", out)
        self.assertNotIn("Entre otros", out)

    def test_multiple_categories_each_truncated(self):
        text = (
            "*Aceites vegetales:*\n"
            "* Almendras\n"
            "* Argán\n"
            "* Coco\n"
            "* Rosa Mosqueta\n"
            "\n"
            "*Aceites esenciales:*\n"
            "* Árbol de Té\n"
            "* Eucalipto\n"
            "* Lavanda\n"
            "* Menta"
        )
        out = _truncate_category_listings(text)
        # Ambas categorías cortadas a 2 + Entre otros.
        self.assertEqual(out.count("* _Entre otros..._"), 2)
        # Cita marketing UNA SOLA VEZ al final (no duplicada).
        self.assertEqual(out.count("Tenemos muchas más referencias"), 1)

    def test_skip_summary_message(self):
        text = (
            "📋 *Resumen de tu pedido:*\n\n"
            "*Productos:*\n"
            "* 1x Jabón A\n"
            "* 1x Jabón B\n"
            "* 1x Jabón C\n"
            "* 1x Jabón D\n\n"
            "Subtotal: $X\n*TOTAL: $Y*"
        )
        out = _truncate_category_listings(text)
        # Resumen NO debe ser truncado — todos los productos visibles.
        self.assertEqual(out, text)

    def test_skip_shipping_quote(self):
        text = (
            "*Envío de tu pedido (3 unidades) a Bogotá:*\n"
            "* 1x Producto A\n"
            "* 1x Producto B\n"
            "* 1x Producto C\n"
            "\n"
            "* *Económica*: FedEx | $5.000\n"
            "* *Rápida*: FedEx | $7.000"
        )
        out = _truncate_category_listings(text)
        self.assertEqual(out, text)

    def test_no_categories_kept_intact(self):
        text = "Hola, ¿en qué te puedo ayudar?"
        out = _truncate_category_listings(text)
        self.assertEqual(out, text)

    def test_idempotent_already_truncated(self):
        # Si el texto ya contiene "Entre otros", no se duplica.
        text = (
            "*Jabones:*\n"
            "* Coco\n"
            "* Lavanda\n"
            "* _Entre otros..._\n"
            "\n"
            "> _Tenemos muchas más referencias para ti — pregúntame por la "
            "que te interese._"
        )
        out = _truncate_category_listings(text)
        # Ya estaba truncado, no se modifica.
        self.assertEqual(out.count("* _Entre otros..._"), 1)
        self.assertEqual(out.count("Tenemos muchas más referencias"), 1)


class FormatPipelineIntegrationTests(unittest.TestCase):
    """Verifica que `_format_whatsapp_response_text` ahora aplique el
    truncado como paso 8 del pipeline."""

    def test_format_pipeline_truncates(self):
        from orchestrator import _format_whatsapp_response_text
        text = (
            "*Aceites:*\n"
            "* Almendras\n"
            "* Argán\n"
            "* Coco\n"
            "* Rosa Mosqueta"
        )
        out = _format_whatsapp_response_text(text)
        self.assertIn("* _Entre otros..._", out)
        self.assertIn("Tenemos muchas más referencias", out)


if __name__ == "__main__":
    unittest.main()

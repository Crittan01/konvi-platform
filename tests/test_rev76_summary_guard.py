"""
Rev. 76 — Test del guard que evita re-cotización tras resumen final.

Caso UAT real (conv c2043f98 turn 12, 2026-04-29):
- Bot envía resumen final con CTA "¿Confirmas... para generar tu link de pago?".
- Cliente dice "Ok, gracias".
- shipping_quote_tool ANTES interpretaba como followup afirmativo a oferta
  de envío y disparaba re-cotización (porque el resumen contiene la palabra
  "Envío:" y un costo).
- Resultado: bot pedía cotizar producto de nuevo, cliente desfasado.

Fix rev. 76: agregar `summary_markers` al guard previo de
`_is_shipping_followup_query` para no interceptar "ok/gracias"
cuando el último outbound ya fue resumen final con CTA de pago.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools.shipping_quote_tool import _is_shipping_followup_query  # noqa: E402


def _outbound(text: str) -> dict:
    return {"direction": "outbound", "content": text}


class Rev76SummaryGuardTests(unittest.TestCase):

    def _summary_outbound(self) -> str:
        return (
            "📋 *Resumen de tu pedido:*\n"
            "*Productos:*\n"
            "• 1x Jabón Artesanal de Coco (Presentación: 60g): $18.000 COP\n"
            "• 2x Jabón Artesanal de Lavanda (Presentación: 60g): $36.000 COP\n"
            "• 1x Sérum de Vitamina C (Volumen: 30ml): $85.000 COP\n"
            "Subtotal: $139.000 COP\n"
            "Envío: $12.150 COP\n"
            "*TOTAL: $151.150 COP*\n"
            "*Datos de envío:*\n"
            "• Nombre: Cristian Camilo Garzón Tamayo\n"
            "• Correo: crittan01@gmail.com\n"
            "• Dirección: Calle 3 sur # 70-84 — Bogotá\n"
            "¿Confirmas que los datos están correctos para generar tu link de pago?"
        )

    def test_ok_gracias_tras_resumen_no_dispara_shipping_followup(self):
        """Caso bug UAT 2026-04-29: cliente dice 'Ok, gracias' tras resumen.
        El detector NO debe activar followup de shipping."""
        history = [_outbound(self._summary_outbound())]
        result = _is_shipping_followup_query("Ok, gracias", history)
        self.assertFalse(result, "Tras resumen final, 'Ok, gracias' NO es followup de envío")

    def test_si_tras_resumen_no_dispara_shipping_followup(self):
        history = [_outbound(self._summary_outbound())]
        self.assertFalse(_is_shipping_followup_query("Sí", history))

    def test_dale_tras_resumen_no_dispara_shipping_followup(self):
        history = [_outbound(self._summary_outbound())]
        self.assertFalse(_is_shipping_followup_query("Dale", history))

    def test_minimal_summary_marker_blocks(self):
        """Aunque el outbound sea solo el CTA, el guard lo detecta."""
        history = [_outbound(
            "Para finalizar, ¿confirmas que los datos están correctos para generar tu link de pago?"
        )]
        self.assertFalse(_is_shipping_followup_query("Sí", history))

    def test_subtotal_marker_blocks(self):
        """Resúmenes con 'Subtotal:' deben bloquear el followup."""
        history = [_outbound(
            "Tu pedido:\n• 1x Coco — $18.000\nSubtotal: $18.000\nEnvío: $12.000"
        )]
        self.assertFalse(_is_shipping_followup_query("Ok", history))

    def test_followup_real_envio_sigue_funcionando(self):
        """Caso legítimo: bot ofrece cotizar, cliente dice 'sí'.
        El detector DEBE seguir activándose (no ser falso negativo)."""
        history = [_outbound(
            "¿Te gustaría cotizar el envío a tu ciudad?"
        )]
        self.assertTrue(_is_shipping_followup_query("Sí", history))


if __name__ == "__main__":
    unittest.main()

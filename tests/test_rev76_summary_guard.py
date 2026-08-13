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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

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

    def test_subtotal_solo_no_bloquea_followup(self):
        """Sem 7 F2 cierre 2026-05-20 — Bug founder UAT (conv 56ff85d8).

        ANTES: cualquier outbound con "Subtotal:" disparaba el guard y
        bloqueaba el followup. Eso era demasiado amplio — el mini-resumen
        pre-cotización (que el bot emite ANTES de pedir ciudad) también
        contiene "Subtotal:" pero NO es resumen FINAL.

        AHORA: "Subtotal:" solo NO basta. Necesita combinarse con markers
        ESPECÍFICOS del resumen final ("Resumen de tu pedido", "link de
        pago", "datos correctos"). Los outbounds tipo mini-resumen
        pre-cotización deben PASAR el guard para que el tool pueda
        procesar la ciudad que el cliente da inmediatamente después.
        """
        history = [_outbound(
            "Perfecto, vamos a cotizar el envío.\n"
            "*Productos en tu carrito:*\n"
            "* 1x Jabón Coco (100g): *$24.000*\n"
            "Subtotal: *$56.000 COP*\n"
            "Para qué ciudad es el envío?"
        )]
        # Cliente da ciudad → DEBE activar followup (no bloquear).
        result = _is_shipping_followup_query("Bogota", history)
        self.assertTrue(
            result,
            "Mini-resumen pre-cotización con 'Subtotal:' NO debe bloquear "
            "respuesta del cliente con ciudad — el bot acaba de preguntar 'Para qué ciudad'.",
        )

    def test_resumen_final_completo_si_bloquea(self):
        """Caso original rev. 76 preservado: el resumen FINAL completo
        (con TODOS los markers específicos) SÍ bloquea el followup."""
        history = [_outbound(self._summary_outbound())]
        self.assertFalse(_is_shipping_followup_query("Ok, gracias", history))

    def test_followup_real_envio_sigue_funcionando(self):
        """Caso legítimo: bot ofrece cotizar, cliente dice 'sí'.
        El detector DEBE seguir activándose (no ser falso negativo)."""
        history = [_outbound(
            "¿Te gustaría cotizar el envío a tu ciudad?"
        )]
        self.assertTrue(_is_shipping_followup_query("Sí", history))

    # ── Bug founder UAT 2026-05-21 (conv 56ff85d8) ────────────────────────

    def test_ciudad_tras_pregunta_para_que_ciudad_activa_followup(self):
        """Bug founder: el bot pregunta "Para qué ciudad es el envío?",
        cliente responde "Bogota". ANTES no había marker para esa frase
        → tool retornaba False → LLM tomaba control → respondía texto
        genérico de KB sin cotizar realmente.
        Ahora: el marker `'para que ciudad es el envio'` matchea."""
        history = [_outbound(
            "Perfecto, vamos a cotizar el envío.\n"
            "*Productos en tu carrito:*\n"
            "* 1x Jabón Coco (100g): *$24.000*\n"
            "Subtotal: *$56.000 COP*\n"
            "Para qué ciudad es el envío?"
        )]
        self.assertTrue(_is_shipping_followup_query("Bogota", history))

    def test_ciudad_tras_pregunta_a_que_ciudad_enviamos_activa_followup(self):
        """Variante: bot pregunta "¿A qué ciudad enviamos?" (frase canónica
        con verbo de envío + marker "a que ciudad enviamos")."""
        history = [_outbound(
            "Tienes 1x Coco + 1x Lavanda.\n"
            "A qué ciudad enviamos tu pedido?"
        )]
        self.assertTrue(_is_shipping_followup_query("Medellín", history))

    def test_ciudad_tras_pregunta_ciudad_de_entrega_activa_followup(self):
        """Variante: bot pregunta "Cuál es la ciudad de entrega?"."""
        history = [_outbound(
            "Listo, productos en carrito.\n"
            "Cuál es la ciudad de entrega?"
        )]
        self.assertTrue(_is_shipping_followup_query("Cali", history))


if __name__ == "__main__":
    unittest.main()

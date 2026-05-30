"""Tests del PostToolCoherenceInvariant.

Rev. 107 — bug runtime conducción KAIU turno A (conv 6b367d8f, 2026-05-23):
LLM emitió outbound con "¿Confirmas?" + "Listo, aquí está el link" en
mismo mensaje, tras ejecutar `generate_payment_link` con éxito. UX
confuso. Este invariant atrapa el patrón y limpia la pregunta redundante.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class PostToolCoherenceTests(unittest.TestCase):

    def setUp(self):
        from agentic.invariants.post_tool_coherence import PostToolCoherenceInvariant
        self.inv = PostToolCoherenceInvariant()
        self.base = {
            "tenant_id": "t", "conversation_id": "c", "contact_id": "ct",
            "supabase": MagicMock(),
        }

    def test_sin_write_tool_ok(self):
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="¿Confirmas tu pedido?",
            tool_call_log=[],  # ningún tool
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_write_tool_sin_pregunta_ok(self):
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="Listo, agregué el item al carrito.",
            tool_call_log=[{"tool": "add_to_cart", "result": {"added": True}}],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_payment_link_generado_con_pregunta_rewrite(self):
        """Caso runtime KAIU turno A: bot emitió pregunta + link."""
        from agentic.invariants.base import InvariantOutcome
        text_bug = (
            "📋 *Resumen de tu pedido:*\n\n"
            "* 1 Jabón 60g: $18.000\n"
            "* Total: $159.950\n\n"
            "¿Confirmas que los datos están correctos para generar tu link de pago?\n\n"
            "Listo, Cristian! Aquí tienes un nuevo link de pago:\n"
            "https://checkout.wompi.co/l/test_sj9wWb"
        )
        r = _run(self.inv.validate(
            candidate_text=text_bug,
            tool_call_log=[
                {"tool": "generate_payment_link",
                 "result": {"checkout_url": "https://checkout.wompi.co/l/test_sj9wWb"}},
            ],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        # Replacement no debe tener la pregunta redundante.
        self.assertNotIn("Confirmas que los datos", r.replacement_text)
        # Replacement debe conservar el link.
        self.assertIn("test_sj9wWb", r.replacement_text)

    def test_add_to_cart_con_pregunta_no_dispara_rev107(self):
        """Rev. 107: el invariant ya NO dispara con writes intermedios
        (add_to_cart, save_*, select_carrier). Esas son next-step
        preguntas legítimas, no redundancia post-acción terminal."""
        from agentic.invariants.base import InvariantOutcome
        text = (
            "Agregué 1 Coco 60g al pedido. ¿Procedemos con el envío?"
        )
        r = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[{"tool": "add_to_cart", "result": {"added": True}}],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_write_tool_fallo_no_rewrite(self):
        """Si el write tool FALLÓ, la pregunta puede ser legítima — OK."""
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="¿Confirmas que quieres reintentar?",
            tool_call_log=[
                {"tool": "generate_payment_link",
                 "result": {"error": "PAYMENT_API_ERROR", "code": "X"}},
            ],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_pregunta_no_es_confirmacion_ok(self):
        """Preguntas legítimas no-confirmación deben pasar."""
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="¡Listo! ¿Quieres algo más?",
            tool_call_log=[{"tool": "add_to_cart", "result": {"added": True}}],
            **self.base,
        ))
        # "¿Quieres algo más?" no match con nuestros patrones de confirmación.
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_save_email_seguido_de_confirmas_pedido_es_legitimo(self):
        """Tras save_email, "¿confirmas el pedido?" es legítimo next-step.
        El invariant rev. 107 ya NO dispara para save_* writes intermedios."""
        from agentic.invariants.base import InvariantOutcome
        text = (
            "Listo, guardé tu correo.\n\n📋 Resumen: ...\n"
            "Confirmas el pedido para generar el link de pago?"
        )
        r = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[{"tool": "save_email", "result": {"saved": True}}],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_confirmas_el_pedido_es_redundante_rewrite(self):
        """'Confirmas EL pedido' tras generate_payment_link → redundante."""
        from agentic.invariants.base import InvariantOutcome
        casos_redundantes = [
            "Listo, aquí tu link.\n\nConfirmas el pedido?",
            "Genial. Confirmas los datos correctos?",
            "Link generado. Confirmas la dirección registrada?",
        ]
        for text in casos_redundantes:
            r = _run(self.inv.validate(
                candidate_text=text,
                tool_call_log=[{"tool": "generate_payment_link",
                                "result": {"checkout_url": "x"}}],
                **self.base,
            ))
            self.assertEqual(
                r.outcome, InvariantOutcome.REWRITE,
                f"DEBE rewrite: {text!r}",
            )


if __name__ == "__main__":
    unittest.main()

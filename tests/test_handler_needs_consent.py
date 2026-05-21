"""Tests integración handler Sem 1.3 — NEEDS_CONSENT.

Verifica zero-regression del refactor:
  • Cliente en NEEDS_CONSENT → bot pide consent (template estándar).
  • Si cliente dijo "sigamos" sin elegir carrier explícitamente Y hay
    cotización en history → preápende ack del carrier auto-defaulteado.
  • Si cliente eligió carrier explícitamente ("Económica") → solo
    consent question, sin ack (cliente ya sabe qué eligió).
"""
import asyncio
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from fsm.handlers import dispatch, TurnInput
import fsm.handlers.needs_consent  # noqa: F401


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_OUTBOUND_QUOTE = (
    "Envío a Bogotá:\n"
    "* *Económica*: FedEx | $11.570 | entrega 22/05\n"
    "* *Rápida*: FedEx Express | $14.410 | entrega 20/05\n"
    "¿Con cuál continuamos?"
)


class NeedsConsentHandlerTests(unittest.TestCase):

    def test_consent_basico_sin_continue_intent(self):
        """Cliente nuevo dice "Económica" → handler emite consent template
        sin ack (cliente eligió explícitamente)."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="NEEDS_CONSENT",
            inbound_text="Económica",
            history=[
                {"direction": "outbound", "content": _OUTBOUND_QUOTE},
            ],
        )
        result = _run(dispatch(turn))
        self.assertIsNotNone(result)
        # Sin ack — cliente eligió explícitamente.
        self.assertNotIn("voy con la opción", result.outbound_text)
        # Sí debe contener el template consent.
        self.assertTrue(
            "acuerdo" in result.outbound_text.lower()
            or "consent" in result.outbound_text.lower()
            or "datos personales" in result.outbound_text.lower()
        )

    def test_continue_intent_sin_carrier_explicito_prepende_ack(self):
        """Cliente dice "sigamos" después de cotización multi-opción →
        handler preápende ack del carrier defaulteado."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="NEEDS_CONSENT",
            inbound_text="sigamos",
            history=[
                {"direction": "outbound", "content": _OUTBOUND_QUOTE},
            ],
        )
        result = _run(dispatch(turn))
        self.assertIsNotNone(result)
        # Ack del carrier al inicio.
        self.assertIn("voy con la opción", result.outbound_text)
        self.assertIn("Económica", result.outbound_text)
        # Y después el consent question.
        self.assertTrue(
            "acuerdo" in result.outbound_text.lower()
            or "consent" in result.outbound_text.lower()
            or "datos personales" in result.outbound_text.lower()
        )

    def test_estado_no_aplicable_retorna_none(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="hola",
        )
        result = _run(dispatch(turn))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

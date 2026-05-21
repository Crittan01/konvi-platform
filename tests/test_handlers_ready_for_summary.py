"""Tests integración handlers Sem 1 — READY_FOR_SUMMARY default + correction.

Verifica zero-regression del refactor:
  • ReadyForSummaryHandler (priority 100) emite resumen 📋 cuando cart
    tiene items + datos completos.
  • ReadyForSummaryCorrectionHandler (priority 50) corre ANTES y
    detecta intent "el email está mal" / "cambia el nombre", pide nuevo
    valor y limpia campo en DB (mock).
  • Guards: idempotencia summary, afirmativos, PII update, phone, add_item
    intent → ceder turn al LLM.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from fsm.handlers import dispatch, TurnInput
# Auto-registro al importar:
import fsm.handlers.ready_for_summary  # noqa: F401
import fsm.handlers.ready_for_summary_correction  # noqa: F401


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_COCO_100G_PRICE = 24000


_CART_WITH_ITEMS = {
    "id": "cart-x",
    "items": [{
        "variation_id": "v100",
        "product_id": "p-coco",
        "quantity": 1,
        "unit_price_cents": _COCO_100G_PRICE * 100,
        "subtotal_cents": _COCO_100G_PRICE * 100,
        "product": {"title": "Jabón Artesanal de Coco"},
    }],
    "subtotal_cents": _COCO_100G_PRICE * 100,
    "shipping_cents": 1157000,
    "total_cents": _COCO_100G_PRICE * 100 + 1157000,
    "shipping_meta": {
        "city": "Bogotá D.C.",
        "carrier": "FedEx",
        "service_level": "Económica",
    },
}


_CONTACT_COMPLETE = {
    "id": "contact-x",
    "consent_given": True,
    "name": "Cristian Camilo Garzon Tamayo",
    "email": "crittan01@gmail.com",
    "phone": "+573125835649",
    "document_type": "CC",
    "document_number": "1032414179",
    "address": {
        "street": "CL 36A 6-87",
        "city": "Bogotá D.C.",
        "state": "Bogotá D.C.",
        "country": "CO",
        "building_type": "oficina",
        "floor": "3",
        "apartment": "301",
        "company_name": "Banco de Bogota",
        "dane_code": "11001",
    },
}


class ReadyForSummaryHandlerTests(unittest.TestCase):

    def test_emite_resumen_determ_cuando_cart_y_datos_completos(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            # Inbound NEUTRO (no afirmativo, no PII update) — debe mostrar
            # resumen porque cliente preguntó qué pasa.
            inbound_text="qué viene ahora?",
            contact_record=_CONTACT_COMPLETE,
            cart=_CART_WITH_ITEMS,
            history=[
                {"direction": "outbound", "content": "Envío Económica: FedEx | $11.570"},
                {"direction": "inbound", "content": "Económica"},
            ],
        )
        result = _run(dispatch(turn))
        self.assertIsNotNone(result)
        self.assertIn("📋", result.outbound_text)
        self.assertIn("Resumen", result.outbound_text)
        self.assertIn("Coco", result.outbound_text)
        self.assertIn("TOTAL", result.outbound_text)
        self.assertEqual(result.handler_name, "ready_for_summary.deterministic_summary")

    def test_guard_idempotencia_summary_no_re_emite(self):
        """Si el último outbound ya fue resumen, NO re-emitir."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="hmm",
            contact_record=_CONTACT_COMPLETE,
            cart=_CART_WITH_ITEMS,
            history=[
                {"direction": "outbound",
                 "content": "📋 *Resumen de tu pedido:*\n* 1x Coco: $24.000\n*TOTAL: $35.570*"},
            ],
        )
        result = _run(dispatch(turn))
        # Idempotencia: handler retorna None → LLM compone (cliente puede
        # estar preguntando otra cosa).
        self.assertIsNone(result)

    def test_guard_afirmativo_cede_al_payment_link(self):
        """Cliente confirma → otro path (payment_link) lo maneja."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="sí confirmo",
            contact_record=_CONTACT_COMPLETE,
            cart=_CART_WITH_ITEMS,
            history=[],
        )
        result = _run(dispatch(turn))
        self.assertIsNone(result)

    def test_guard_10_digit_phone_cede_turn(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="3223840887",
            contact_record=_CONTACT_COMPLETE,
            cart=_CART_WITH_ITEMS,
            history=[],
        )
        result = _run(dispatch(turn))
        self.assertIsNone(result)

    def test_guard_add_item_intent_cede_turn(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="puedo adicionar 1 jabón de coco?",
            contact_record=_CONTACT_COMPLETE,
            cart=_CART_WITH_ITEMS,
            catalog=[{
                "id": "p-coco",
                "title": "Jabón Artesanal de Coco",
                "variants": [{"id": "v60", "label": "60g", "price": 18000}],
            }],
            history=[],
        )
        result = _run(dispatch(turn))
        self.assertIsNone(result)

    def test_cart_vacio_no_emite_resumen(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="qué te dije?",
            contact_record=_CONTACT_COMPLETE,
            cart={"items": []},
            history=[],
        )
        result = _run(dispatch(turn))
        self.assertIsNone(result)


class ReadyForSummaryCorrectionHandlerTests(unittest.TestCase):

    def test_correction_intent_dispara_antes_del_summary(self):
        """Cliente dice "el email está mal" en READY_FOR_SUMMARY →
        correction handler (priority 50) corre ANTES que summary (priority 100)."""
        # Mock supabase y orchestrator helpers.
        fake_sb = MagicMock()
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="cambia el email por favor",
            contact_record=_CONTACT_COMPLETE,
            cart=_CART_WITH_ITEMS,
            supabase=fake_sb,
            history=[],
        )
        # Patch _clear_contact_field para no tocar DB real.
        with patch("orchestrator._clear_contact_field") as mock_clear:
            result = _run(dispatch(turn))
        self.assertIsNotNone(result)
        self.assertEqual(result.handler_name, "ready_for_summary.correction")
        # Side-effect verificado.
        mock_clear.assert_called_once()
        # No emite resumen — el outbound es prompt de corrección.
        self.assertNotIn("📋", result.outbound_text)

    def test_sin_correction_intent_cede_al_summary(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            contact_id="contact-x",
            display_state="READY_FOR_SUMMARY",
            # Inbound neutro — sin tokens de afirmación ni de corrección.
            inbound_text="quiero ver mi resumen final",
            contact_record=_CONTACT_COMPLETE,
            cart=_CART_WITH_ITEMS,
            history=[],
        )
        result = _run(dispatch(turn))
        # No es correction; el summary default debe atrapar.
        self.assertIsNotNone(result)
        self.assertEqual(result.handler_name, "ready_for_summary.deterministic_summary")


if __name__ == "__main__":
    unittest.main()

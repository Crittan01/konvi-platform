"""Rev. 81 — Tests del model router."""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from llm_router import (  # noqa: E402
    classify_intent,
    model_pair_for,
    INTENT_SIMPLE,
    INTENT_TRANSACTIONAL,
    TRANSACTIONAL_FSM_STATES,
)


class FsmStateRoutingTests(unittest.TestCase):

    def test_needs_consent_is_transactional(self):
        self.assertEqual(
            classify_intent("ok", fsm_state="NEEDS_CONSENT"),
            INTENT_TRANSACTIONAL,
        )

    def test_needs_email_is_transactional(self):
        self.assertEqual(
            classify_intent("crittan01@gmail.com", fsm_state="NEEDS_EMAIL"),
            INTENT_TRANSACTIONAL,
        )

    def test_ready_for_summary_is_transactional(self):
        self.assertEqual(
            classify_intent("Sí", fsm_state="READY_FOR_SUMMARY"),
            INTENT_TRANSACTIONAL,
        )

    def test_awaiting_order_confirmation_is_transactional(self):
        self.assertEqual(
            classify_intent("Sí confirmo", fsm_state="AWAITING_ORDER_CONFIRMATION"),
            INTENT_TRANSACTIONAL,
        )


class KeywordRoutingTests(unittest.TestCase):

    def test_buy_intent_is_transactional(self):
        self.assertEqual(
            classify_intent("Quiero comprar un jabón de coco"),
            INTENT_TRANSACTIONAL,
        )

    def test_pay_intent_is_transactional(self):
        self.assertEqual(
            classify_intent("Cómo pago? Tarjeta o nequi"),
            INTENT_TRANSACTIONAL,
        )

    def test_quote_intent_is_transactional(self):
        self.assertEqual(
            classify_intent("Cotizar el envío a Bogotá"),
            INTENT_TRANSACTIONAL,
        )

    def test_simple_greeting(self):
        self.assertEqual(
            classify_intent("Hola buenos días"),
            INTENT_SIMPLE,
        )

    def test_simple_kb_query(self):
        self.assertEqual(
            classify_intent("¿Cuál es la política de devoluciones?"),
            INTENT_SIMPLE,
        )

    def test_simple_product_info(self):
        self.assertEqual(
            classify_intent("De qué está hecho el jabón?"),
            INTENT_SIMPLE,
        )


class HistoryRoutingTests(unittest.TestCase):
    """Si el cliente expresó intent transaccional en turnos previos,
    el siguiente turno (aunque sea simple) sigue siendo transactional —
    no podemos perder precisión a mitad de flujo."""

    def test_followup_after_buy_intent_stays_transactional(self):
        history = [
            {"direction": "inbound", "content": "Quiero comprar un jabón"},
            {"direction": "outbound", "content": "Claro, ¿cuál presentación?"},
        ]
        self.assertEqual(
            classify_intent("60g", history=history),
            INTENT_TRANSACTIONAL,
        )


class ModelPairTests(unittest.TestCase):

    def test_simple_pair(self):
        primary, fallback = model_pair_for(INTENT_SIMPLE)
        # Lite primario
        self.assertIn("lite", primary)
        # Flash fallback
        self.assertNotIn("lite", fallback)

    def test_transactional_pair(self):
        primary, fallback = model_pair_for(INTENT_TRANSACTIONAL)
        # Flash primario (no lite)
        self.assertNotIn("lite", primary)
        # Lite fallback
        self.assertIn("lite", fallback)

    def test_unknown_defaults_to_simple_pair(self):
        # Cualquier intent no transaccional cae en simple.
        primary, _ = model_pair_for("desconocido")
        self.assertIn("lite", primary)


class RoutingDefaultsTests(unittest.TestCase):
    """Defaults: ante duda, simple."""

    def test_unknown_text_defaults_to_simple(self):
        self.assertEqual(
            classify_intent("?"),
            INTENT_SIMPLE,
        )

    def test_empty_query_is_simple(self):
        self.assertEqual(classify_intent(""), INTENT_SIMPLE)

    def test_fsm_states_covered(self):
        # Sanidad: las 7 transitions de captura están en el set.
        self.assertEqual(len(TRANSACTIONAL_FSM_STATES), 7)


if __name__ == "__main__":
    unittest.main()

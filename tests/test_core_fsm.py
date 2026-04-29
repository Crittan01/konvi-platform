"""Tests de ``core/fsm.py``.

Cubre:
- determine_state en cada combinación de hechos.
- is_transition_allowed para todas las transiciones canónicas + bloqueadas.
- tools_for_state retorna conjuntos no vacíos para cada estado.
- transiciones correctivas (READY_FOR_SUMMARY → NEEDS_X) están permitidas.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from core.fsm import (  # noqa: E402
    ALLOWED_TOOLS_BY_STATE,
    FsmFacts,
    State,
    allowed_transitions,
    determine_state,
    is_transition_allowed,
    tools_for_state,
)


class DetermineStateTests(unittest.TestCase):
    def test_no_cart_returns_catalog_mode(self):
        s = determine_state(FsmFacts(has_cart_with_items=False))
        self.assertEqual(s, State.CATALOG_MODE)

    def test_cart_no_quote_returns_needs_shipping_city(self):
        s = determine_state(FsmFacts(has_cart_with_items=True))
        self.assertEqual(s, State.NEEDS_SHIPPING_CITY)

    def test_quoted_no_carrier_returns_awaiting_carrier(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
        ))
        self.assertEqual(s, State.AWAITING_CARRIER_SELECTION)

    def test_carrier_no_consent_returns_needs_consent(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
            carrier_selected=True,
        ))
        self.assertEqual(s, State.NEEDS_CONSENT)

    def test_consent_no_email_returns_needs_email(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
            carrier_selected=True, consent_given=True,
        ))
        self.assertEqual(s, State.NEEDS_EMAIL)

    def test_email_no_name_returns_needs_name(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
            carrier_selected=True, consent_given=True,
            has_email=True,
        ))
        self.assertEqual(s, State.NEEDS_NAME)

    def test_name_no_document_returns_needs_document(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
            carrier_selected=True, consent_given=True,
            has_email=True, has_name=True,
        ))
        self.assertEqual(s, State.NEEDS_DOCUMENT)

    def test_document_no_address_returns_needs_direction(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
            carrier_selected=True, consent_given=True,
            has_email=True, has_name=True, has_document=True,
        ))
        self.assertEqual(s, State.NEEDS_DIRECTION)

    def test_all_data_returns_ready_for_summary(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
            carrier_selected=True, consent_given=True,
            has_email=True, has_name=True, has_document=True,
            has_complete_address=True,
        ))
        self.assertEqual(s, State.READY_FOR_SUMMARY)

    def test_confirm_question_returns_awaiting_order_confirmation(self):
        s = determine_state(FsmFacts(
            has_cart_with_items=True, shipping_quoted=True,
            carrier_selected=True, consent_given=True,
            has_email=True, has_name=True, has_document=True,
            has_complete_address=True,
            last_outbound_was_order_confirm_question=True,
        ))
        self.assertEqual(s, State.AWAITING_ORDER_CONFIRMATION)


class TransitionTests(unittest.TestCase):
    def test_catalog_to_needs_shipping_city_allowed(self):
        self.assertTrue(is_transition_allowed(
            src=State.CATALOG_MODE, dst=State.NEEDS_SHIPPING_CITY,
        ))

    def test_skip_states_not_allowed(self):
        # No se puede saltar de NEEDS_NAME directo a READY_FOR_SUMMARY
        self.assertFalse(is_transition_allowed(
            src=State.NEEDS_NAME, dst=State.READY_FOR_SUMMARY,
        ))
        # Ni de NEEDS_CONSENT directo a NEEDS_DIRECTION
        self.assertFalse(is_transition_allowed(
            src=State.NEEDS_CONSENT, dst=State.NEEDS_DIRECTION,
        ))

    def test_correction_from_summary_to_needs_email(self):
        # Cliente en READY_FOR_SUMMARY pide corregir email → debe ser permitida
        self.assertTrue(is_transition_allowed(
            src=State.READY_FOR_SUMMARY, dst=State.NEEDS_EMAIL,
        ))
        self.assertTrue(is_transition_allowed(
            src=State.READY_FOR_SUMMARY, dst=State.NEEDS_DIRECTION,
        ))

    def test_abort_back_to_catalog_from_any_collection_state(self):
        for state in [
            State.NEEDS_SHIPPING_CITY,
            State.NEEDS_CONSENT,
            State.NEEDS_EMAIL,
            State.NEEDS_NAME,
            State.NEEDS_DOCUMENT,
            State.NEEDS_DIRECTION,
        ]:
            self.assertTrue(
                is_transition_allowed(src=state, dst=State.CATALOG_MODE),
                f"Falta transición {state} → CATALOG_MODE",
            )

    def test_awaiting_order_confirmation_back_to_catalog(self):
        self.assertTrue(is_transition_allowed(
            src=State.AWAITING_ORDER_CONFIRMATION, dst=State.CATALOG_MODE,
        ))

    def test_allowed_transitions_returns_frozenset(self):
        result = allowed_transitions(State.CATALOG_MODE)
        self.assertIsInstance(result, frozenset)


class ToolsByStateTests(unittest.TestCase):
    def test_every_state_has_tools(self):
        for state in State:
            self.assertGreater(
                len(tools_for_state(state)), 0,
                f"State {state} no tiene tools — el LLM no podría hacer nada",
            )

    def test_catalog_mode_has_search_and_image(self):
        tools = tools_for_state(State.CATALOG_MODE)
        self.assertIn("search_catalog", tools)
        self.assertIn("get_product_image", tools)
        self.assertIn("answer_kb", tools)

    def test_needs_consent_only_has_record_consent(self):
        tools = tools_for_state(State.NEEDS_CONSENT)
        self.assertEqual(tools, frozenset({"record_consent"}))

    def test_awaiting_order_confirmation_has_confirm_and_cancel(self):
        tools = tools_for_state(State.AWAITING_ORDER_CONFIRMATION)
        self.assertIn("confirm_order", tools)
        self.assertIn("cancel_order", tools)

    def test_no_state_allows_unknown_tool(self):
        for state, tools in ALLOWED_TOOLS_BY_STATE.items():
            self.assertNotIn(
                "delete_database",  # tool inventado, no debería aparecer nunca
                tools,
                f"State {state} permite tool peligroso",
            )


if __name__ == "__main__":
    unittest.main()

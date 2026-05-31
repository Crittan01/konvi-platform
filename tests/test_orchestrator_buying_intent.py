import os
import sys
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

import orchestrator


class BuyingIntentStateTests(unittest.TestCase):
    def test_inquiry_phrase_is_not_buying_intent(self):
        self.assertFalse(
            orchestrator._has_buying_intent(
                "Me gustaria averiguar por unos cargador rapido",
                [],
            )
        )

    def test_direct_purchase_phrase_is_buying_intent(self):
        self.assertTrue(orchestrator._has_buying_intent("Quiero comprar 2 unidades", []))

    def test_display_state_catalog_mode_when_not_buying(self):
        state = orchestrator._resolve_display_state(
            contact_record={"consent_given": False},
            history=[],
            buying_intent=False,
            shipping_quoted=False,
        )
        self.assertEqual(state, "CATALOG_MODE")

    def test_display_state_needs_shipping_city_first(self):
        state = orchestrator._resolve_display_state(
            contact_record={"consent_given": False},
            history=[],
            buying_intent=True,
            shipping_quoted=False,
        )
        self.assertEqual(state, "NEEDS_SHIPPING_CITY")

    def test_display_state_waits_carrier_after_quote(self):
        state = orchestrator._resolve_display_state(
            contact_record={"consent_given": False},
            history=[
                {"direction": "outbound", "content": "Envío de 1 unidad:\n• *Económica*: X\n• *Rápida*: Y"}
            ],
            buying_intent=True,
            shipping_quoted=True,
        )
        self.assertEqual(state, "AWAITING_CARRIER_SELECTION")


if __name__ == "__main__":
    unittest.main()

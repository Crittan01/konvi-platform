"""Tests del prompt builder per-state (rev. 109 Día 2).

Cubre:
  • Cada AgenticState produce un prompt no vacío.
  • Tamaños razonables (vs monolito 19KB).
  • Bloques incluidos coherentes con el estado.
  • Tools subset coherente con estado (3-7 tools por estado, no 15).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.state_machine import AgenticState
from agentic.prompt import build_prompt_for_state, tools_for_state
from agentic.prompt.tools_subset import all_known_tool_names


_FAKE_CATALOG = [
    {"id": "p1", "title": "Jabón de Coco",
     "variations": [{"id": "v1", "label": "100g", "price_cop": 24000}]},
    {"id": "p2", "title": "Sérum Vit C",
     "variations": [{"id": "v2", "label": "15ml", "price_cop": 52000}]},
]
_FAKE_CARRIERS = [
    {"carrier_name": "SERVIENTREGA", "supports_cod": True,
     "cod_min_recaudo_cop": 30000, "charges_return_fee": False,
     "max_weight_kg": 30},
]
_FAKE_PAYMENT_METHODS = {"cod_enabled": True, "online_wompi_enabled": True}
_FAKE_CONTACT = {
    "name": None, "email": None, "consent_given": False,
    "address": None, "phone": "+573125835649",
}


class PromptBuilderTests(unittest.TestCase):
    def _build(self, state: AgenticState) -> str:
        return build_prompt_for_state(
            state=state,
            tenant_name="KAIU Living Natural",
            tenant_pitch="cosmética artesanal natural",
            tenant_tone="cordial y profesional",
            catalog=_FAKE_CATALOG,
            contact_record=_FAKE_CONTACT,
            carriers=_FAKE_CARRIERS,
            payment_methods=_FAKE_PAYMENT_METHODS,
            server_greeting="Buenos días",
        )

    def test_all_states_produce_non_empty_prompt(self):
        for state in AgenticState:
            prompt = self._build(state)
            self.assertGreater(len(prompt), 500, f"{state.value} muy corto")

    def test_greeting_prompt_includes_tenant_name(self):
        prompt = self._build(AgenticState.GREETING)
        self.assertIn("KAIU Living Natural", prompt)
        # Saludo time-aware presente en GREETING.
        self.assertIn("Buenos días", prompt)

    def test_cart_building_includes_catalog(self):
        prompt = self._build(AgenticState.CART_BUILDING)
        self.assertIn("CATÁLOGO ACTUAL", prompt)
        self.assertIn("Jabón de Coco", prompt)

    def test_pii_collection_excludes_catalog(self):
        """PII no necesita catálogo — reduce prompt size."""
        prompt = self._build(AgenticState.PII_COLLECTION)
        self.assertNotIn("CATÁLOGO ACTUAL", prompt)
        self.assertIn("Habeas Data", prompt)

    def test_payment_includes_carriers_and_methods(self):
        prompt = self._build(AgenticState.PAYMENT)
        self.assertIn("CARRIERS", prompt)
        self.assertIn("MÉTODOS DE PAGO", prompt)

    def test_shipping_quote_includes_carriers(self):
        prompt = self._build(AgenticState.SHIPPING_QUOTE)
        self.assertIn("CARRIERS", prompt)

    def test_human_handoff_minimal(self):
        prompt = self._build(AgenticState.HUMAN_HANDOFF)
        self.assertIn("HUMAN_HANDOFF", prompt)
        # Sin catálogo ni carriers en handoff.
        self.assertNotIn("CATÁLOGO ACTUAL", prompt)

    def test_all_prompts_include_safety(self):
        for state in AgenticState:
            prompt = self._build(state)
            self.assertIn("REGLAS UNIVERSALES", prompt, f"{state.value}")

    def test_prompt_sizes_are_reasonable(self):
        """Per-state prompts deberían ser < 15KB cada uno (vs 19KB monolito).

        Estados livianos < 8KB; pesados (con catálogo) < 15KB.
        """
        for state in AgenticState:
            prompt = self._build(state)
            self.assertLess(
                len(prompt), 15000,
                f"{state.value} prompt={len(prompt)} > 15KB",
            )


class ToolsSubsetTests(unittest.TestCase):
    def test_all_states_have_at_least_one_tool(self):
        for state in AgenticState:
            tools = tools_for_state(state)
            self.assertGreaterEqual(
                len(tools), 1,
                f"{state.value} sin tools — bot mudo",
            )

    def test_escalate_present_in_all_states(self):
        for state in AgenticState:
            self.assertIn("escalate_to_human", tools_for_state(state))

    def test_cart_building_has_add_to_cart(self):
        tools = tools_for_state(AgenticState.CART_BUILDING)
        self.assertIn("add_to_cart", tools)
        self.assertIn("update_cart_item_quantity", tools)

    def test_pii_collection_has_consent_tools(self):
        tools = tools_for_state(AgenticState.PII_COLLECTION)
        self.assertIn("record_consent", tools)
        self.assertIn("save_contact_field", tools)
        # Rev. 109 UAT live BUG 15: PII_COLLECTION incluye cart mods
        # (cliente puede modificar items antes de dar PII).
        self.assertIn("update_cart_item_quantity", tools)
        self.assertIn("remove_cart_item", tools)
        # NO debe tener tools de pago/envío en PII (eso es estado posterior).
        self.assertNotIn("generate_payment_link", tools)
        self.assertNotIn("quote_shipping", tools)

    def test_payment_has_link_tool(self):
        tools = tools_for_state(AgenticState.PAYMENT)
        self.assertIn("generate_payment_link", tools)
        # Rev. 109 UAT live BUG 15: PAYMENT incluye add_to_cart porque
        # cliente puede agregar item last-minute antes de generar link.
        # El cart sigue mutable hasta orden creada.
        self.assertIn("add_to_cart", tools)

    def test_post_payment_has_recent_orders(self):
        tools = tools_for_state(AgenticState.POST_PAYMENT)
        self.assertIn("get_recent_orders", tools)

    def test_human_handoff_has_only_escalate(self):
        tools = tools_for_state(AgenticState.HUMAN_HANDOFF)
        self.assertEqual(tools, frozenset({"escalate_to_human"}))

    def test_none_state_returns_all_tools(self):
        """Fallback compat — sin state, exponer todos los tools."""
        all_tools = tools_for_state(None)
        self.assertGreaterEqual(len(all_tools), 10)
        # Contiene tools de varios estados.
        self.assertIn("add_to_cart", all_tools)
        self.assertIn("generate_payment_link", all_tools)
        self.assertIn("record_consent", all_tools)

    def test_subsets_are_all_drawn_from_known_set(self):
        """Defensive: tools subset no nombran tools fantasma."""
        known = all_known_tool_names()
        for state in AgenticState:
            subset = tools_for_state(state)
            for tool in subset:
                self.assertIn(tool, known, f"{state.value}: {tool} fantasma")


if __name__ == "__main__":
    unittest.main()

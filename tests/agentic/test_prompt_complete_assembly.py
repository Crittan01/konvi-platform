"""Capstone integration tests — build_prompt_for_state full assembly (Fase 0/4 finiquito).

Cierra testing pyramid inversion identificada en root-cause analysis wujbdgrhk:
los tests existentes cubrían blocks individuales OK pero NUNCA assertaron que
el prompt FINAL ensamblado por `build_prompt_for_state` contenga los literales
esperados del business_ops_block en cada estado donde debe aparecer.

Previene regresión del bug verificado 2026-06-23: V3 per-state no recibía los
6 kwargs business_ops → prompt incompleto → bot improvisaba horarios y
shipping_origin (causa raíz P1 documentada en synthesis).

Adversarial coverage:
  • shipping_origin/store_locations/support_schedule/social_links presentes
    → block aparece literal en estados conversacionales.
  • shipping_origin null + todos null → block NO aparece (no inyecta header
    vacío que confunda al LLM).
  • Estados transaccionales (PII/SHIPPING/CARRIER/PAYMENT/HANDOFF) →
    block NO aparece (decisión Q3 ADR-0024: solo conversacionales).
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.prompt.builder import build_prompt_for_state, _BUSINESS_OPS_STATES
from agentic.state_machine.states import AgenticState


KAIU_FULL = {
    "tenant_name": "KAIU Living Natural",
    "shipping_origin": {
        "city": "Bogotá D.C.",
        "state": "Bogotá D.C.",
        "street": "Calle 3 sur # 70-84",
        "country": "Colombia",
    },
    "store_locations": [],
    "store_type": "virtual",
    "support_schedule": {
        "days": [1, 2, 3, 4, 5, 6],
        "open": "08:00",
        "close": "18:00",
    },
    "social_links": {
        "facebook": "https://www.facebook.com/kaiuoficial/",
        "instagram": "https://www.instagram.com/kaiu.oficial",
    },
    "after_hours_message": "Atendemos de lunes a sábado de 8 a 6.",
}

CONTACT_CRISTIAN = {
    "id": "cb69830b-1111-2222-3333-444444444444",
    "name": "Cristian García",
    "phone": "573125835649",
    "shipping_phone": "573125835649",
    "email": "crittan01@gmail.com",
    "document_type": "CC",
    "document_number": "1023456789",
    "consent_given": True,
    "address": {
        "street": "Calle 50 #20-30",
        "city": "Medellín",
        "neighborhood": "Laureles",
        "building_type": "casa",
    },
}


def _build(state: AgenticState, **kwargs):
    """Helper — build_prompt_for_state con KAIU defaults + overrides."""
    merged = {**KAIU_FULL, **kwargs}
    return build_prompt_for_state(
        state=state,
        tenant_name=merged["tenant_name"],
        catalog=[],
        contact_record=CONTACT_CRISTIAN,
        carriers=[],
        payment_methods={},
        active_coupons=[],
        shipping_origin=merged.get("shipping_origin"),
        store_locations=merged.get("store_locations"),
        store_type=merged.get("store_type"),
        support_schedule=merged.get("support_schedule"),
        social_links=merged.get("social_links"),
        after_hours_message=merged.get("after_hours_message"),
    )


class BusinessOpsInProperStatesTests(unittest.TestCase):
    """Fase 0 gate — business_ops_block aparece SOLO en estados conversacionales."""

    def test_greeting_includes_business_ops(self):
        p = _build(AgenticState.GREETING)
        self.assertIn("SOBRE LA TIENDA", p)
        self.assertIn("Bogotá D.C.", p)  # shipping_origin.city literal
        self.assertIn("08:00", p)  # support_schedule.open literal
        self.assertIn("18:00", p)  # support_schedule.close literal
        self.assertIn("Lun a Sáb", p)  # rendered days

    def test_exploring_includes_business_ops(self):
        p = _build(AgenticState.EXPLORING)
        self.assertIn("SOBRE LA TIENDA", p)
        self.assertIn("Bogotá D.C.", p)
        self.assertIn("Lun a Sáb de 08:00 a 18:00", p)

    def test_cart_building_includes_business_ops(self):
        p = _build(AgenticState.CART_BUILDING)
        self.assertIn("SOBRE LA TIENDA", p)
        self.assertIn("Bogotá D.C.", p)

    def test_post_payment_includes_business_ops(self):
        p = _build(AgenticState.POST_PAYMENT)
        self.assertIn("SOBRE LA TIENDA", p)
        self.assertIn("Bogotá D.C.", p)

    def test_pii_collection_excludes_business_ops(self):
        p = _build(AgenticState.PII_COLLECTION)
        self.assertNotIn("SOBRE LA TIENDA", p)
        # Transactional state — no noise from business_ops

    def test_shipping_quote_excludes_business_ops(self):
        p = _build(AgenticState.SHIPPING_QUOTE)
        self.assertNotIn("SOBRE LA TIENDA", p)

    def test_carrier_selection_excludes_business_ops(self):
        p = _build(AgenticState.CARRIER_SELECTION)
        self.assertNotIn("SOBRE LA TIENDA", p)

    def test_payment_excludes_business_ops(self):
        p = _build(AgenticState.PAYMENT)
        self.assertNotIn("SOBRE LA TIENDA", p)

    def test_human_handoff_excludes_business_ops(self):
        p = _build(AgenticState.HUMAN_HANDOFF)
        self.assertNotIn("SOBRE LA TIENDA", p)


class BusinessOpsCornerCasesTests(unittest.TestCase):
    """Adversarial — null/empty data NO inyecta header vacío."""

    def test_all_null_omits_block(self):
        """Sin shipping_origin/store/schedule/social → no header SOBRE LA TIENDA."""
        p = _build(
            AgenticState.EXPLORING,
            shipping_origin=None,
            store_locations=None,
            store_type=None,
            support_schedule=None,
            social_links=None,
            after_hours_message=None,
        )
        self.assertNotIn("SOBRE LA TIENDA", p)

    def test_empty_lists_omits_block(self):
        """Empty list/empty dict no inyecta block (any() filtra falsy)."""
        p = _build(
            AgenticState.EXPLORING,
            shipping_origin={},  # empty dict
            store_locations=[],  # empty list
            store_type="",
            support_schedule={},
            social_links={},
            after_hours_message=None,
        )
        self.assertNotIn("SOBRE LA TIENDA", p)

    def test_partial_data_renders_what_present(self):
        """Solo shipping_origin → block aparece pero sin support_schedule line."""
        p = _build(
            AgenticState.EXPLORING,
            shipping_origin={"city": "Bogotá D.C."},
            store_locations=None,
            store_type=None,
            support_schedule=None,
            social_links=None,
            after_hours_message=None,
        )
        self.assertIn("SOBRE LA TIENDA", p)
        self.assertIn("Bogotá D.C.", p)
        # No schedule rendered → no "08:00"
        self.assertNotIn("08:00", p)

    def test_contact_canonical_address_appears(self):
        """Smoke — el contact_record canonical (street) llega al prompt."""
        p = _build(AgenticState.GREETING)
        self.assertIn("Calle 50", p)  # contact.address.street
        self.assertIn("Medellín", p)  # contact.address.city
        # contact.address NO usa line1 (canon rev. 110)
        self.assertNotIn("'line1':", p)


class BusinessOpsStatesAlignmentTests(unittest.TestCase):
    """_BUSINESS_OPS_STATES debe contener EXACTAMENTE los 4 estados conversacionales
    decididos en Q3 ADR-0024 (root-cause analysis wujbdgrhk)."""

    def test_business_ops_states_q3_decision(self):
        expected = {
            AgenticState.GREETING,
            AgenticState.EXPLORING,
            AgenticState.CART_BUILDING,
            AgenticState.POST_PAYMENT,
        }
        self.assertEqual(_BUSINESS_OPS_STATES, expected)


if __name__ == "__main__":
    unittest.main()

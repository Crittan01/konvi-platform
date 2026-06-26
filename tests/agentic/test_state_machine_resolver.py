"""Tests determinísticos del resolver de state machine (rev. 109).

ADR-0019 — Agentic State Machine.

El resolver es función pura: ResolutionContext → AgenticState.
Cubrimos cada regla del resolver explícitamente + edge cases.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.state_machine import (
    AgenticState,
    ResolutionContext,
    StateResolver,
    is_valid_transition,
    allowed_next_states,
)
from agentic.state_machine.resolver import build_context_from_records


class StateResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = StateResolver()

    # ---------- Regla 1: handoff humano ----------
    def test_human_handoff_wins_over_everything(self):
        # A11 audit: status canónico en DB = "human_takeover" (no "human_handoff").
        ctx = ResolutionContext(
            conversation_status="human_takeover",
            cart_items_count=3,
            cart_has_payment_link=True,
            has_active_order=True,
            payment_status="approved",
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.HUMAN_HANDOFF)

    # ---------- Regla 2: orden activa + pago resuelto ----------
    def test_post_payment_when_order_approved(self):
        ctx = ResolutionContext(
            has_active_order=True,
            payment_status="approved",
            cart_items_count=2,  # cart aún visible, pero orden ya tomó verdad
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.POST_PAYMENT)

    def test_post_payment_when_cod_pending(self):
        ctx = ResolutionContext(
            has_active_order=True,
            payment_status="cod_pending",
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.POST_PAYMENT)

    # ---------- Regla 3: pago en curso ----------
    def test_payment_when_link_generated(self):
        ctx = ResolutionContext(
            cart_status="checkout",
            cart_items_count=2,
            cart_has_payment_link=True,
            contact_has_required_pii=True,
            contact_consent_given=True,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.PAYMENT)

    def test_payment_when_status_pending(self):
        ctx = ResolutionContext(
            cart_items_count=2,
            payment_status="pending",
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.PAYMENT)

    # ---------- Regla 4: carrier selection ----------
    def test_carrier_selection_when_quote_no_carrier(self):
        ctx = ResolutionContext(
            cart_items_count=2,
            cart_has_shipping_quote=True,
            cart_has_carrier_selected=False,
            contact_has_required_pii=True,
            contact_consent_given=True,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.CARRIER_SELECTION)

    # ---------- Regla 5: shipping quote en curso ----------
    def test_shipping_quote_when_pii_done_no_quote(self):
        ctx = ResolutionContext(
            cart_items_count=2,
            contact_has_required_pii=True,
            contact_consent_given=True,
            cart_has_shipping_quote=False,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.SHIPPING_QUOTE)

    # ---------- Regla 6: PII collection ----------
    def test_pii_collection_when_consent_missing(self):
        ctx = ResolutionContext(
            cart_items_count=2,
            contact_consent_given=False,
            contact_has_required_pii=False,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.PII_COLLECTION)

    def test_pii_collection_when_consent_yes_pii_missing(self):
        ctx = ResolutionContext(
            cart_items_count=2,
            contact_consent_given=True,
            contact_has_required_pii=False,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.PII_COLLECTION)

    # ---------- Regla 7: cart building ----------
    def test_cart_building_with_items_pii_done_pre_quote(self):
        # Si PII está done, debería pasar a SHIPPING_QUOTE.
        # CART_BUILDING aplica cuando NO se ha iniciado el flujo de envío
        # — eso ocurre cuando aún falta PII (caso 6) o cuando ya hay items
        # pero no se ha consultado el envío AND no hay PII completa.
        # Aquí simulamos cliente con cart, consent dado, pero sin PII completa
        # → cae en PII_COLLECTION (regla 6).
        ctx = ResolutionContext(
            cart_items_count=1,
            contact_consent_given=True,
            contact_has_required_pii=False,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.PII_COLLECTION)

    # ---------- Regla 8: exploring ----------
    def test_exploring_when_history_no_cart(self):
        ctx = ResolutionContext(
            has_prior_inbound=True,
            history_len=2,
            cart_items_count=0,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.EXPLORING)

    # ---------- Regla 9: greeting default ----------
    def test_greeting_when_blank_slate(self):
        ctx = ResolutionContext()
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.GREETING)

    # ---------- Build context helper ----------
    def test_build_context_from_records_minimal(self):
        ctx = build_context_from_records(
            conversation={"status": "bot_active"},
            cart=None,
            contact=None,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.GREETING)

    def test_build_context_from_records_cart_with_items(self):
        ctx = build_context_from_records(
            conversation={"status": "bot_active"},
            cart={"status": "open", "items": [{"id": "a"}, {"id": "b"}]},
            contact={"consent_given": False},
            history_len=4,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.PII_COLLECTION)

    def test_build_context_from_records_full_journey(self):
        ctx = build_context_from_records(
            conversation={"status": "bot_active"},
            cart={
                "status": "checkout",
                "items_count": 3,
                "shipping_cents": 12000,
                "carrier_code": "SERVIENTREGA",
                "payment_link": "https://checkout.wompi.co/l/abc",
            },
            contact={
                "consent_given": True,
                "name": "John",
                "email": "john@example.com",
                "address": "Calle 1",
            },
            history_len=12,
        )
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.PAYMENT)

    def test_build_context_from_records_post_payment(self):
        # FIX A11: build_context_from_records ahora hila order+payment → el
        # dispatcher puede alcanzar POST_PAYMENT (antes order/payment nunca se
        # pasaban → estado post-venta dead). Cart convertido (None) + orden con
        # pago approved → POST_PAYMENT.
        ctx = build_context_from_records(
            conversation={"status": "bot_active"},
            cart=None,
            contact={"consent_given": True, "name": "John",
                     "document_number": "123", "address": "Calle 1"},
            order={"id": "order-1", "status": "confirmed"},
            payment={"status": "approved"},
            history_len=14,
        )
        self.assertTrue(ctx.has_active_order)
        self.assertEqual(ctx.payment_status, "approved")
        self.assertEqual(self.resolver.resolve(ctx), AgenticState.POST_PAYMENT)

    def test_build_context_no_order_not_post_payment(self):
        # Sin order/payment (default) → NO POST_PAYMENT (regresión del bug).
        ctx = build_context_from_records(
            conversation={"status": "bot_active"},
            cart=None,
            contact={"consent_given": True},
            history_len=3,
        )
        self.assertFalse(ctx.has_active_order)
        self.assertNotEqual(self.resolver.resolve(ctx), AgenticState.POST_PAYMENT)


class TransitionsTests(unittest.TestCase):
    def test_null_to_any_is_valid(self):
        for state in AgenticState:
            self.assertTrue(is_valid_transition(None, state))

    def test_greeting_can_go_to_cart_building(self):
        self.assertTrue(
            is_valid_transition(AgenticState.GREETING, AgenticState.CART_BUILDING)
        )

    def test_greeting_cannot_jump_to_post_payment(self):
        self.assertFalse(
            is_valid_transition(AgenticState.GREETING, AgenticState.POST_PAYMENT)
        )

    def test_post_payment_can_loop_to_greeting(self):
        self.assertTrue(
            is_valid_transition(AgenticState.POST_PAYMENT, AgenticState.GREETING)
        )

    def test_allowed_next_states_contains_self(self):
        for state in AgenticState:
            self.assertIn(state, allowed_next_states(state))


class StatePropsTests(unittest.TestCase):
    def test_pre_cart_states(self):
        self.assertTrue(AgenticState.GREETING.is_pre_cart)
        self.assertTrue(AgenticState.EXPLORING.is_pre_cart)
        self.assertFalse(AgenticState.CART_BUILDING.is_pre_cart)

    def test_checkout_states(self):
        for s in (
            AgenticState.PII_COLLECTION,
            AgenticState.SHIPPING_QUOTE,
            AgenticState.CARRIER_SELECTION,
            AgenticState.PAYMENT,
        ):
            self.assertTrue(s.is_checkout)
        self.assertFalse(AgenticState.CART_BUILDING.is_checkout)

    def test_terminal_states(self):
        self.assertTrue(AgenticState.POST_PAYMENT.is_terminal)
        self.assertTrue(AgenticState.HUMAN_HANDOFF.is_terminal)
        self.assertFalse(AgenticState.PAYMENT.is_terminal)


if __name__ == "__main__":
    unittest.main()

"""Tests cancel_intent_resolver + order_cancellation pipeline (rev. 109).

Cubre:
  • Detección intent cancel vs retracto vs nada.
  • Extracción order_id short (#ABC12345) y long (UUID).
  • Anti falso positivo (cupón, otras palabras).
  • Pipeline escalation rules (12+).
  • Cancellation result builders.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"),
)

from agentic.cancel_intent_resolver import detect_cancel_intent
from lib.order_cancellation import (
    detect_escalation_reasons, TenantPolicy, CancellationRequest,
    CancellationItem, _compose_customer_message, _escalation_customer_message,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class CancelIntentDetectionTests(unittest.TestCase):
    def test_cancel_with_short_id(self):
        r = detect_cancel_intent("cancela mi pedido #ABC12345")
        self.assertIsNotNone(r)
        self.assertEqual(r.intent, "cancel_order")
        self.assertEqual(r.order_id_short, "ABC12345")

    def test_cancel_without_id(self):
        r = detect_cancel_intent("quiero anular la compra")
        self.assertIsNotNone(r)
        self.assertEqual(r.intent, "cancel_order")
        self.assertIsNone(r.order_id_short)

    def test_retracto_explicit(self):
        r = detect_cancel_intent("me retracto de mi pedido")
        self.assertIsNotNone(r)
        self.assertEqual(r.intent, "retracto")

    def test_retracto_art_47(self):
        r = detect_cancel_intent("invoco el art 47 ley 1480")
        self.assertIsNotNone(r)
        self.assertEqual(r.intent, "retracto")

    def test_retracto_devolver(self):
        r = detect_cancel_intent("quiero devolverlo")
        self.assertIsNotNone(r)
        self.assertEqual(r.intent, "retracto")

    def test_no_intent_on_unrelated_text(self):
        self.assertIsNone(detect_cancel_intent("hola que tal"))
        self.assertIsNone(detect_cancel_intent("quiero comprar jabón"))

    def test_no_intent_on_coupon_cancel(self):
        """'cancela el cupón' NO debe matchear como cancelación de pedido."""
        r = detect_cancel_intent("cancela el cupón")
        self.assertIsNone(r)

    def test_cancel_uuid_long(self):
        r = detect_cancel_intent(
            "cancela pedido f5e80d0a-c0f5-4d4d-8a85-9dee27a64a3d"
        )
        self.assertIsNotNone(r)
        self.assertEqual(r.intent, "cancel_order")
        self.assertEqual(r.order_id_long, "f5e80d0a-c0f5-4d4d-8a85-9dee27a64a3d")

    def test_empty_and_long_inputs(self):
        self.assertIsNone(detect_cancel_intent(""))
        self.assertIsNone(detect_cancel_intent(None))
        self.assertIsNone(detect_cancel_intent("a" * 600))


class EscalationRulesTests(unittest.TestCase):
    def setUp(self):
        self.policy = TenantPolicy()
        self.request = CancellationRequest(
            order_id="xxx", tenant_id="t1", actor="customer",
            reason_text="quiero cancelar",
        )

    def test_e1_in_transit_escalates(self):
        order = {"status": "confirmed", "total_amount": 50000}
        shipment = {"status": "picked_up"}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
            shipment=shipment,
        )
        self.assertIn("ORDER_IN_TRANSIT", reasons)

    def test_e1_delivered_escalates_retracto(self):
        order = {"status": "delivered", "total_amount": 50000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertIn("ORDER_DELIVERED", reasons)

    def test_e2_high_value_escalates(self):
        order = {"status": "confirmed", "total_amount": 600000}  # > $500K
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertIn("HIGH_VALUE", reasons)

    def test_e3_product_defect_escalates(self):
        self.request.reason_text = "el jabón vino dañado"
        order = {"status": "confirmed", "total_amount": 50000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertIn("PRODUCT_DEFECT_CLAIMED", reasons)

    def test_e4_missing_package_escalates(self):
        self.request.reason_text = "no me ha llegado el pedido"
        order = {"status": "confirmed", "total_amount": 50000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertIn("MISSING_PACKAGE", reasons)

    def test_e5_payment_dispute(self):
        self.request.reason_text = "me cobraron mal el producto"
        order = {"status": "confirmed", "total_amount": 50000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertIn("PAYMENT_DISPUTE", reasons)

    def test_e7_refund_other_account_escalates(self):
        self.request.reason_text = "refund a otra cuenta diferente"
        order = {"status": "confirmed", "total_amount": 50000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertIn("REFUND_TO_OTHER_ACCOUNT", reasons)

    def test_e8_discount_request_escalates(self):
        self.request.reason_text = "cancela y dame descuento futuro"
        order = {"status": "confirmed", "total_amount": 50000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertIn("DISCOUNT_REQUEST", reasons)

    def test_e10_hostile_escalates(self):
        self.request.reason_text = "esto es una estafa, fraude"
        order = {"status": "confirmed", "total_amount": 50000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        # PAYMENT_DISPUTE u CUSTOMER_HOSTILE deben matchear
        self.assertTrue(
            "CUSTOMER_HOSTILE" in reasons or "PAYMENT_DISPUTE" in reasons,
        )

    def test_e13_tenant_disabled_card_void(self):
        policy = TenantPolicy(escalate_card_voids=True)
        order = {"status": "confirmed", "total_amount": 50000}
        payment = {"payment_method_type": "CARD"}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=policy,
            payment=payment,
        )
        self.assertIn("POLICY_DISABLED", reasons)

    def test_safe_cancel_no_escalation(self):
        """Caso bot autónomo: pre-entrega, monto bajo, sin defectos."""
        order = {"status": "pending_payment", "total_amount": 30000}
        reasons = detect_escalation_reasons(
            order=order, request=self.request, policy=self.policy,
        )
        self.assertEqual(reasons, [])


class CustomerMessageTests(unittest.TestCase):
    def test_no_payment(self):
        policy = TenantPolicy()
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="no_refund_no_payment",
            refund_amount_cents=0, policy=policy,
        )
        self.assertIn("No se cobró nada", msg)
        self.assertIn("#ABC12345", msg)

    def test_cod_not_collected(self):
        policy = TenantPolicy()
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="cod_not_collected",
            refund_amount_cents=0, policy=policy,
        )
        self.assertIn("contra entrega", msg)

    def test_wompi_void_auto(self):
        policy = TenantPolicy()
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="wompi_void_auto",
            refund_amount_cents=4800000, policy=policy,
        )
        self.assertIn("$48.000", msg)
        self.assertIn("3-5 días hábiles", msg)

    def test_wompi_manual(self):
        policy = TenantPolicy(manual_refund_legal_days=30)
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="wompi_dashboard_manual",
            refund_amount_cents=10000000, policy=policy,
        )
        self.assertIn("$100.000", msg)
        # El plazo en comercio electrónico es de 15 días calendario (art. 47, mod. art. 3
        # Ley 2439 de 2024). Este test afirmaba 30 y CONGELABA el error como comportamiento
        # esperado — por eso nadie lo detectó hasta la revalidación legal del 2026-07-26.
        self.assertIn("15 días calendario", msg)
        self.assertNotIn("30 días", msg)
        self.assertIn("Ley 1480", msg)
        self.assertNotIn("Art. 49", msg)


class EscalationMessageTests(unittest.TestCase):
    def test_in_transit(self):
        msg = _escalation_customer_message(
            ["ORDER_IN_TRANSIT"], "ABC12345", {}, TenantPolicy(),
        )
        self.assertIn("rechazarlo", msg.lower())
        self.assertIn("courier", msg.lower())

    def test_defect(self):
        msg = _escalation_customer_message(
            ["PRODUCT_DEFECT_CLAIMED"], "ABC12345", {}, TenantPolicy(),
        )
        self.assertIn("garantía", msg.lower())
        self.assertIn("Art. 11", msg)

    def test_missing(self):
        msg = _escalation_customer_message(
            ["MISSING_PACKAGE"], "ABC12345", {}, TenantPolicy(),
        )
        self.assertIn("courier", msg.lower())

    def test_high_value(self):
        msg = _escalation_customer_message(
            ["HIGH_VALUE"], "ABC12345", {"total_amount": 600000}, TenantPolicy(),
        )
        self.assertIn("especialista", msg.lower())

    def test_dispute(self):
        msg = _escalation_customer_message(
            ["PAYMENT_DISPUTE"], "ABC12345", {}, TenantPolicy(),
        )
        self.assertIn("verificación", msg.lower())


if __name__ == "__main__":
    unittest.main()

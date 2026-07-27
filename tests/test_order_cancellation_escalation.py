"""Tests de la política de escalación de cancelaciones (money-path, Ley 1480).

`detect_escalation_reasons` decide cuándo el bot escala una cancelación a un humano
(orden en tránsito/entregada, alto monto, defecto, paquete no recibido, disputa de
pago, cliente hostil, etc.) vs manejarla autónomo. `_escalation_customer_message`
compone el mensaje legal correcto al cliente. Ambas puras → testeables sin DB.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from lib.order_cancellation import (  # noqa: E402
    CancellationRequest,
    TenantPolicy,
    _escalation_customer_message,
    detect_escalation_reasons,
)


def _req(reason_text: str = "") -> CancellationRequest:
    return CancellationRequest(
        order_id="o1", tenant_id="t1", actor="customer", reason_text=reason_text,
    )


_LOW = {"status": "pending_payment", "total_amount": 20000}  # $20K, bajo el umbral


class DetectEscalationReasonsTests(unittest.TestCase):
    def test_no_reasons_bot_autonomous(self):
        r = detect_escalation_reasons(order=_LOW, request=_req("quiero cancelar"), policy=TenantPolicy())
        self.assertEqual(r, [])

    def test_order_delivered(self):
        r = detect_escalation_reasons(
            order={"status": "delivered", "total_amount": 20000},
            request=_req(), policy=TenantPolicy(),
        )
        self.assertIn("ORDER_DELIVERED", r)

    def test_order_shipped_escalates(self):
        r = detect_escalation_reasons(
            order={"status": "shipped", "total_amount": 20000},
            request=_req(), policy=TenantPolicy(),
        )
        self.assertIn("ORDER_DELIVERED", r)

    def test_in_transit_escalates_when_policy_disallows(self):
        r = detect_escalation_reasons(
            order=_LOW, request=_req(), policy=TenantPolicy(allow_cancel_after_picked_up=False),
            shipment={"status": "in_transit"},
        )
        self.assertIn("ORDER_IN_TRANSIT", r)

    def test_in_transit_ok_when_policy_allows(self):
        r = detect_escalation_reasons(
            order=_LOW, request=_req(), policy=TenantPolicy(allow_cancel_after_picked_up=True),
            shipment={"status": "in_transit"},
        )
        self.assertNotIn("ORDER_IN_TRANSIT", r)

    def test_high_value(self):
        # total_amount*100 > 50.000.000 cents → $600K supera el umbral default.
        r = detect_escalation_reasons(
            order={"status": "pending_payment", "total_amount": 600000},
            request=_req(), policy=TenantPolicy(),
        )
        self.assertIn("HIGH_VALUE", r)

    def test_product_defect_claimed(self):
        r = detect_escalation_reasons(order=_LOW, request=_req("el producto vino defectuoso"), policy=TenantPolicy())
        self.assertIn("PRODUCT_DEFECT_CLAIMED", r)

    def test_missing_package(self):
        r = detect_escalation_reasons(order=_LOW, request=_req("no me llegó el pedido"), policy=TenantPolicy())
        self.assertIn("MISSING_PACKAGE", r)

    def test_payment_dispute(self):
        r = detect_escalation_reasons(order=_LOW, request=_req("esto es un fraude, no autoricé"), policy=TenantPolicy())
        self.assertIn("PAYMENT_DISPUTE", r)

    def test_refund_to_other_account(self):
        r = detect_escalation_reasons(order=_LOW, request=_req("devuélvanme a otra cuenta"), policy=TenantPolicy())
        self.assertIn("REFUND_TO_OTHER_ACCOUNT", r)

    def test_discount_request(self):
        r = detect_escalation_reasons(order=_LOW, request=_req("me dan un descuento y no cancelo"), policy=TenantPolicy())
        self.assertIn("DISCOUNT_REQUEST", r)

    def test_customer_hostile(self):
        r = detect_escalation_reasons(order=_LOW, request=_req("esto es una estafa, los voy a demandar"), policy=TenantPolicy())
        self.assertIn("CUSTOMER_HOSTILE", r)

    def test_card_void_policy_disabled(self):
        r = detect_escalation_reasons(
            order=_LOW, request=_req(), policy=TenantPolicy(escalate_card_voids=True),
            payment={"payment_method_type": "CARD"},
        )
        self.assertIn("POLICY_DISABLED", r)

    def test_card_void_not_escalated_when_policy_allows(self):
        r = detect_escalation_reasons(
            order=_LOW, request=_req(), policy=TenantPolicy(escalate_card_voids=False),
            payment={"payment_method_type": "CARD"},
        )
        self.assertNotIn("POLICY_DISABLED", r)

    def test_multiple_reasons_accumulate(self):
        r = detect_escalation_reasons(
            order={"status": "delivered", "total_amount": 600000},
            request=_req("vino defectuoso"), policy=TenantPolicy(),
        )
        self.assertIn("ORDER_DELIVERED", r)
        self.assertIn("HIGH_VALUE", r)
        self.assertIn("PRODUCT_DEFECT_CLAIMED", r)


class EscalationCustomerMessageTests(unittest.TestCase):
    def test_in_transit_message(self):
        msg = _escalation_customer_message(["ORDER_IN_TRANSIT"], "ABC123", {}, TenantPolicy())
        self.assertIn("en ruta", msg.lower())
        self.assertIn("ABC123", msg)

    def test_delivered_message_cites_retracto(self):
        msg = _escalation_customer_message(["ORDER_DELIVERED"], "ABC123", {}, TenantPolicy())
        self.assertIn("retracto", msg.lower())
        self.assertIn("1480", msg)

    def test_defect_message_cites_garantia(self):
        msg = _escalation_customer_message(["PRODUCT_DEFECT_CLAIMED"], "ABC123", {}, TenantPolicy())
        self.assertIn("garantía", msg.lower())

    def test_missing_package_message(self):
        msg = _escalation_customer_message(["MISSING_PACKAGE"], "ABC123", {}, TenantPolicy())
        self.assertIn("courier", msg.lower())

    def test_uses_primary_reason_first(self):
        # El primer reason es el primario → mensaje de ORDER_DELIVERED, no de HIGH_VALUE.
        msg = _escalation_customer_message(["ORDER_DELIVERED", "HIGH_VALUE"], "X", {}, TenantPolicy())
        self.assertIn("retracto", msg.lower())


if __name__ == "__main__":
    unittest.main()

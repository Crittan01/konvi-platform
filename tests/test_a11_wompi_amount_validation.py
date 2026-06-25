"""Regresión A11 audit (2026-06-25) — webhook Wompi valida monto/moneda.

Hallazgo: `_process_wompi_event` confirmaba la orden ante un evento APPROVED sin
comparar el monto cobrado contra el total de la orden. Defensa payment-integrity
fail-closed: un mismatch (link mal correlacionado, tampering, cobro parcial) NO
debe confirmar la orden.

`total_amount` está en pesos; `amount_in_cents` en cents → esperado = total*100
(verificado contra orden real del UAT: total_amount=66100.0 → 6.610.000 cents).
"""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/tests")

from routers import wompi_webhook  # noqa: E402
from helpers.wompi_payload_builder import WompiPayloadBuilder, TEST_EVENTS_KEY  # noqa: E402
from test_wompi_webhook import _make_supabase_mock  # noqa: E402  (reusa harness por-tabla)


class WompiAmountValidationTests(unittest.TestCase):
    def setUp(self):
        # get_tenant_wompi_creds → events_key del tenant para que la firma valide.
        self._p = patch(
            "routers.wompi_webhook.get_tenant_wompi_creds",
            return_value=(None, TEST_EVENTS_KEY, "sandbox"),
        )
        self._p.start()
        self.addCleanup(self._p.stop)

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_amount_mismatch_does_not_confirm(self, mock_get_client, mock_decrement):
        # total_amount=1350.0 → esperado 135.000 cents; pago reporta 999.999 → mismatch.
        payload = WompiPayloadBuilder().with_approved_txn(
            payment_link_id="plink-mm", txn_id="txn-mm", amount_in_cents=999_999,
        ).build()
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-mm": "order-mm"},
            "payments_by_txn": {"txn-mm": {"id": "pay-mm", "tenant_id": "tenant-1"}},
            "orders": {
                "order-mm": {
                    "id": "order-mm", "tenant_id": "tenant-1",
                    "status": "pending_payment", "conversation_id": "conv-1",
                    "total_amount": 1350.0,
                },
            },
        })
        mock_get_client.return_value = supabase

        with self.assertLogs("routers.wompi_webhook", level="ERROR") as cm:
            wompi_webhook._process_wompi_event(payload)

        self.assertIn("monto_mismatch", "\n".join(cm.output))
        mock_decrement.assert_not_called()  # orden NO confirmada

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_amount_match_confirms(self, mock_get_client, mock_decrement):
        # total_amount=1350.0 → esperado 135.000 cents; pago reporta 135.000 → match.
        payload = WompiPayloadBuilder().with_approved_txn(
            payment_link_id="plink-ok", txn_id="txn-ok", amount_in_cents=135_000,
        ).build()
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-ok": "order-ok"},
            "payments_by_txn": {"txn-ok": {"id": "pay-ok", "tenant_id": "tenant-1"}},
            "orders": {
                "order-ok": {
                    "id": "order-ok", "tenant_id": "tenant-1",
                    "status": "pending_payment", "conversation_id": "conv-1",
                    "total_amount": 1350.0,
                },
            },
        })
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        mock_decrement.assert_called()  # confirm procedió (happy path no se rompe)


if __name__ == "__main__":
    unittest.main()

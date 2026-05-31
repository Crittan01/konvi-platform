"""
Tests F1: Wompi DECLINED/ERROR → retry de pago.

Cubre:
- DECLINED en orden pending_payment → genera nuevo link + encola outbound
- DECLINED en orden confirmed → skip (idempotente)
- DECLINED en orden cancelled → skip
- ERROR en pending_payment → retry igual que DECLINED
- Sin WOMPI_PRIVATE_KEY → encola mensaje de fallo sin nuevo link
- APPROVED → no activa retry (control negativo)
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/tests")

from helpers.wompi_payload_builder import WompiPayloadBuilder


def _make_supabase_mock(*, order_status="pending_payment", has_conversation=True):
    """Construye un mock de Supabase con las respuestas esperadas."""
    supabase = MagicMock()

    # Respuesta de _get_order_by_id en _maybe_offer_payment_retry
    order_data = {
        "id": "order-uuid-123",
        "tenant_id": "tenant-uuid-456",
        "status": order_status,
        "total_amount": 135_000.0,
        "notes": "Pedido de prueba",
        "conversation_id": "conv-uuid-789" if has_conversation else None,
    }

    # Respuesta de _get_order_id_by_link (payments → order_id)
    mock_payments = MagicMock()
    mock_payments.data = [{"order_id": "order-uuid-123"}]

    # Respuesta de _get_order_by_id (orders)
    mock_order_by_id = MagicMock()
    mock_order_by_id.data = [order_data]

    # Respuesta de contacts join para nombre
    mock_contacts_join = MagicMock()
    mock_contacts_join.data = [{"contacts": {"name": "Test Cliente"}}]

    # Respuesta de insert en payments
    mock_payments_insert = MagicMock()
    mock_payments_insert.data = [{"id": "payment-new-uuid"}]

    # Respuesta de insert en messages
    mock_msg_insert = MagicMock()
    mock_msg_insert.data = [{"id": "msg-new-uuid"}]

    # Respuesta de conversations (customer_phone)
    mock_conv = MagicMock()
    mock_conv.data = [{"customer_phone": "+573001234567"}]

    # Respuesta de rpc enqueue
    mock_rpc = MagicMock()
    mock_rpc.execute.return_value = MagicMock()

    def _table_side_effect(table_name):
        mock_table = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])

        if table_name == "payments":
            select_chain = MagicMock()
            select_chain.execute.return_value = mock_payments
            mock_table.select.return_value = select_chain

            insert_chain = MagicMock()
            insert_chain.execute.return_value = mock_payments_insert
            mock_table.insert.return_value = insert_chain

        elif table_name == "orders":
            select_chain = MagicMock()
            # Soporta dos tipos de select: con "id,tenant_id,status..." y con "contacts(name)"
            def _order_select(*args, **kwargs):
                eq1 = MagicMock()
                eq2 = MagicMock()
                limit1 = MagicMock()

                if "contacts" in str(args):
                    limit1.execute.return_value = mock_contacts_join
                else:
                    limit1.execute.return_value = mock_order_by_id

                eq2.limit.return_value = limit1
                eq1.eq.return_value = eq2
                return eq1

            mock_table.select.side_effect = _order_select

        elif table_name == "messages":
            insert_chain = MagicMock()
            insert_chain.execute.return_value = mock_msg_insert
            mock_table.insert.return_value = insert_chain

        elif table_name == "conversations":
            select_chain = MagicMock()
            eq1 = MagicMock()
            eq2 = MagicMock()
            limit1 = MagicMock()
            limit1.execute.return_value = mock_conv
            eq2.limit.return_value = limit1
            eq1.eq.return_value = eq2
            select_chain.eq.return_value = eq1
            mock_table.select.return_value = select_chain

        return mock_table

    supabase.table.side_effect = _table_side_effect
    supabase.rpc.return_value = mock_rpc
    return supabase


class WompiRetryTests(unittest.TestCase):

    def _load_webhook_module(self):
        """Import fresco del módulo en cada test para evitar estado global."""
        import importlib
        import routers.wompi_webhook as wh
        importlib.reload(wh)
        return wh

    @patch("routers.wompi_webhook._get_service_client")
    @patch("routers.wompi_webhook.verify_event_signature", return_value=True)
    @patch("routers.wompi_webhook.get_tenant_wompi_creds", return_value=("prv_test_key", "events_key", "sandbox"))
    @patch("routers.wompi_webhook.create_payment_link_sync")
    def test_declined_pending_payment_triggers_retry(self, mock_create_link, _mock_creds, mock_sig, mock_supabase_client):
        """DECLINED en pending_payment → genera nuevo link y encola outbound."""
        mock_create_link.return_value = {
            "link_id": "new-link-id",
            "checkout_url": "https://checkout.wompi.co/l/new-link-id",
            "active": True,
            "amount_in_cents": 13_500_000,
            "expires_at": "2026-04-25T12:00:00.000Z",
        }
        supabase = _make_supabase_mock(order_status="pending_payment")
        mock_supabase_client.return_value = supabase

        from routers.wompi_webhook import _maybe_offer_payment_retry
        _maybe_offer_payment_retry(supabase, order_id="order-uuid-123", txn_status="DECLINED")

        mock_create_link.assert_called_once()
        supabase.rpc.assert_called_once()

    @patch("routers.wompi_webhook.verify_event_signature", return_value=True)
    def test_declined_confirmed_order_no_retry(self, _mock_sig):
        """DECLINED en orden ya confirmada → skip completo."""
        supabase = _make_supabase_mock(order_status="confirmed")
        from routers.wompi_webhook import _maybe_offer_payment_retry
        with patch("integrations.wompi_client.create_payment_link_sync") as mock_create:
            _maybe_offer_payment_retry(supabase, order_id="order-uuid-123", txn_status="DECLINED")
            mock_create.assert_not_called()

    @patch("routers.wompi_webhook.verify_event_signature", return_value=True)
    def test_declined_cancelled_order_no_retry(self, _mock_sig):
        """DECLINED en orden cancelada (TTL expirado) → skip completo."""
        supabase = _make_supabase_mock(order_status="cancelled")
        from routers.wompi_webhook import _maybe_offer_payment_retry
        with patch("integrations.wompi_client.create_payment_link_sync") as mock_create:
            _maybe_offer_payment_retry(supabase, order_id="order-uuid-123", txn_status="DECLINED")
            mock_create.assert_not_called()

    @patch("routers.wompi_webhook._get_service_client")
    @patch("routers.wompi_webhook.verify_event_signature", return_value=True)
    @patch("routers.wompi_webhook.get_tenant_wompi_creds", return_value=("prv_test_key", "events_key", "sandbox"))
    @patch("routers.wompi_webhook.create_payment_link_sync")
    def test_error_status_triggers_retry(self, mock_create_link, _mock_creds, mock_sig, mock_supabase_client):
        """ERROR en pending_payment también activa retry."""
        mock_create_link.return_value = {
            "link_id": "error-retry-link",
            "checkout_url": "https://checkout.wompi.co/l/error-retry-link",
            "active": True,
            "amount_in_cents": 13_500_000,
            "expires_at": "2026-04-25T12:00:00.000Z",
        }
        supabase = _make_supabase_mock(order_status="pending_payment")
        mock_supabase_client.return_value = supabase

        from routers.wompi_webhook import _maybe_offer_payment_retry
        _maybe_offer_payment_retry(supabase, order_id="order-uuid-123", txn_status="ERROR")
        mock_create_link.assert_called_once()

    @patch("routers.wompi_webhook.verify_event_signature", return_value=True)
    @patch("routers.wompi_webhook.get_tenant_wompi_creds", return_value=(None, None, "sandbox"))
    def test_no_wompi_key_enqueues_failure_msg(self, _mock_creds, _mock_sig):
        """Wompi no configurado para el tenant → encola mensaje de fallo sin generar link."""
        supabase = _make_supabase_mock(order_status="pending_payment")
        from routers.wompi_webhook import _maybe_offer_payment_retry
        with patch("integrations.wompi_client.create_payment_link_sync") as mock_create, \
             patch("routers.wompi_webhook._enqueue_outbound_text") as mock_enqueue:
            _maybe_offer_payment_retry(supabase, order_id="order-uuid-123", txn_status="DECLINED")
            mock_create.assert_not_called()
            mock_enqueue.assert_called_once()

    @patch("routers.wompi_webhook._get_service_client")
    @patch("routers.wompi_webhook.get_tenant_wompi_creds", return_value=(None, None, "sandbox"))
    @patch("routers.wompi_webhook.verify_event_signature", return_value=True)
    def test_approved_does_not_trigger_retry(self, _mock_sig, _mock_creds, mock_supabase_client):
        """APPROVED nunca activa retry — lo maneja el flujo de confirmación."""
        supabase = _make_supabase_mock(order_status="pending_payment")
        mock_supabase_client.return_value = supabase

        payload = WompiPayloadBuilder().with_approved_txn(
            txn_id="txn-ok", payment_link_id="plink-ok", amount_in_cents=13_500_000
        ).build()

        # Simular el proceso completo pero sin order found (payments vacío)
        supabase.table("payments").select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        with patch("routers.wompi_webhook._maybe_offer_payment_retry") as mock_retry:
            from routers.wompi_webhook import _process_wompi_event
            _process_wompi_event(payload)
            mock_retry.assert_not_called()


if __name__ == "__main__":
    unittest.main()

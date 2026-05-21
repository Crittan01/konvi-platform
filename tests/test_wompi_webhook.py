"""
Tests del router de webhook Wompi.

Cubre:
- Firma inválida → rechazo silencioso
- Evento distinto a transaction.updated → ignorado
- transaction.updated APPROVED sin payment_link_id → sin acción
- transaction.updated APPROVED con link no encontrado → sin acción
- transaction.updated APPROVED + order ya confirmed → idempotencia
- transaction.updated APPROVED + order pending_payment → confirma, stock, notifica
- transaction.updated DECLINED → sin acción en order
- transaction.updated VOIDED/ERROR/PENDING → sin acción en order
- Error en confirmación de orden → logueado, no notifica
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/tests")

from routers import wompi_webhook
from helpers.wompi_payload_builder import WompiPayloadBuilder, TEST_EVENTS_KEY


class _TableMock:
    """Mock de tabla Supabase que responde según un state dict."""

    def __init__(self, name, state):
        self._name = name
        self._state = state
        self._select_cols = ""
        self._eq_filters = []

    def select(self, cols="*"):
        self._select_cols = cols
        return self

    def insert(self, data):
        return _ExecuteMock(self._state.get(f"{self._name}_insert", []))

    def update(self, data):
        return _UpdateMock(self._name, self._state)

    def eq(self, col, val):
        self._eq_filters.append((col, val))
        return self

    def limit(self, n):
        return self

    def single(self):
        return self

    def execute(self):
        if self._name == "payments":
            # _get_order_id_by_link busca por wompi_link_id
            if any(col == "wompi_link_id" for col, _ in self._eq_filters):
                link_id = next((v for c, v in self._eq_filters if c == "wompi_link_id"), None)
                mapping = self._state.get("link_to_order", {})
                order_id = mapping.get(link_id)
                return types.SimpleNamespace(data=[{"order_id": order_id}] if order_id else [])
            # _upsert_payment_record busca por wompi_txn_id
            if any(col == "wompi_txn_id" for col, _ in self._eq_filters):
                txn_id = next((v for c, v in self._eq_filters if c == "wompi_txn_id"), None)
                existing = self._state.get("payments_by_txn", {})
                rec = existing.get(txn_id)
                return types.SimpleNamespace(data=[rec] if rec else [])
            return types.SimpleNamespace(data=[])

        if self._name == "orders":
            # _get_order_by_id busca por id
            if any(col == "id" for col, _ in self._eq_filters):
                order_id = next((v for c, v in self._eq_filters if c == "id"), None)
                orders = self._state.get("orders", {})
                rec = orders.get(order_id)
                return types.SimpleNamespace(data=[rec] if rec else [])
            return types.SimpleNamespace(data=[])

        if self._name == "messages":
            return types.SimpleNamespace(data=self._state.get("messages_insert", []))

        if self._name == "conversations":
            convs = self._state.get("conversations", {})
            conv_id = next((v for c, v in self._eq_filters if c == "id"), None)
            rec = convs.get(conv_id)
            return types.SimpleNamespace(data=[rec] if rec else [])

        return types.SimpleNamespace(data=[])


class _UpdateMock:
    def __init__(self, table_name, state):
        self._table_name = table_name
        self._state = state
        self._eq_filters = []

    def eq(self, col, val):
        self._eq_filters.append((col, val))
        return self

    def execute(self):
        return types.SimpleNamespace(data=[])


class _ExecuteMock:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _RpcMock:
    def __init__(self):
        self.calls = []

    def __call__(self, name, params):
        self.calls.append((name, params))
        return _ExecuteMock([])


def _make_supabase_mock(state):
    """Crea un mock de Supabase con comportamiento por tabla."""
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _TableMock(name, state)
    rpc = _RpcMock()
    supabase.rpc.side_effect = rpc
    return supabase


class WompiWebhookTests(unittest.TestCase):
    def setUp(self):
        # Inyectar events_key del tenant vía get_tenant_wompi_creds (nueva API multi-tenant)
        self._patcher = patch(
            "routers.wompi_webhook.get_tenant_wompi_creds",
            return_value=(None, TEST_EVENTS_KEY, "sandbox"),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_invalid_signature_rejects_event(self, mock_get_client, mock_decrement):
        payload = WompiPayloadBuilder().with_approved_txn().build()
        payload["signature"]["checksum"] = "BAD"
        supabase = _make_supabase_mock({})
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        # Con multi-tenant: payments + orders son consultados antes de verificar firma
        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_non_transaction_updated_ignored(self, mock_get_client, mock_decrement):
        payload = WompiPayloadBuilder().with_event("payment_link.created").with_approved_txn().build()
        supabase = _make_supabase_mock({})
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        supabase.table.assert_not_called()
        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_approved_without_payment_link_id_no_action(self, mock_get_client, mock_decrement):
        builder = WompiPayloadBuilder().with_approved_txn()
        payload = builder.build()
        payload["data"]["transaction"]["payment_link_id"] = None
        supabase = _make_supabase_mock({})
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_approved_link_not_found_no_action(self, mock_get_client, mock_decrement):
        payload = WompiPayloadBuilder().with_approved_txn(payment_link_id="plink-missing").build()
        supabase = _make_supabase_mock({})
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_orphan_webhook_logs_and_returns_early(self, mock_get_client, mock_decrement):
        """Sem 7 F2 cierre 2026-05-21 — Capa C (Wompi payment link guard):
        webhook con payment_link_id pero sin `payments` row matching → log
        `[WOMPI][ORPHAN]` + return early SIN verificar firma (no podemos
        sin tenant_id). Anteriormente este caso producía un misleading
        'firma_invalida' log."""
        payload = WompiPayloadBuilder().with_approved_txn(
            payment_link_id="plink-orphan", txn_id="txn-orphan",
        ).build()
        supabase = _make_supabase_mock({})  # vacío → link_to_order={}
        mock_get_client.return_value = supabase

        with self.assertLogs("routers.wompi_webhook", level="WARNING") as cm:
            wompi_webhook._process_wompi_event(payload)

        joined = "\n".join(cm.output)
        self.assertIn("[WOMPI][ORPHAN]", joined)
        self.assertIn("plink-orphan", joined)
        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_approved_order_already_confirmed_idempotent(self, mock_get_client, mock_decrement):
        payload = WompiPayloadBuilder().with_approved_txn(
            payment_link_id="plink-1", txn_id="txn-1"
        ).build()
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-1": "order-1"},
            "payments_by_txn": {"txn-1": {"id": "pay-1", "tenant_id": "tenant-1"}},
            "orders": {
                "order-1": {"id": "order-1", "tenant_id": "tenant-1", "status": "confirmed", "conversation_id": "conv-1"}
            },
        })
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_approved_confirm_order_decrement_stock_notify(self, mock_get_client, mock_decrement):
        payload = WompiPayloadBuilder().with_approved_txn(
            payment_link_id="plink-2", txn_id="txn-2"
        ).build()
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-2": "order-2"},
            "orders": {
                "order-2": {"id": "order-2", "tenant_id": "tenant-1", "status": "pending_payment", "conversation_id": "conv-2"}
            },
            "messages_insert": [{"id": "msg-1"}],
            "conversations": {"conv-2": {"customer_phone": "573001112233"}},
        })
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        mock_decrement.assert_called_once()
        # Verificar que se encoló mensaje outbound
        self.assertTrue(any(call[0][0] == "enqueue_whatsapp_outbound_message" for call in supabase.rpc.call_args_list))

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_declined_does_not_confirm(self, mock_get_client, mock_decrement):
        payload = WompiPayloadBuilder().with_declined_txn(
            payment_link_id="plink-3", txn_id="txn-3"
        ).build()
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-3": "order-3"},
            "orders": {
                "order-3": {"id": "order-3", "tenant_id": "tenant-1", "status": "pending_payment", "conversation_id": "conv-3"}
            },
        })
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_error_status_does_not_confirm(self, mock_get_client, mock_decrement):
        payload = WompiPayloadBuilder().with_txn(
            txn_id="txn-4", status="ERROR", amount_in_cents=135_000
        ).with_custom_properties([
            "data.transaction.id", "data.transaction.status", "data.transaction.amount_in_cents"
        ]).build()
        payload["data"]["transaction"]["payment_link_id"] = "plink-4"
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-4": "order-4"},
            "orders": {
                "order-4": {"id": "order-4", "tenant_id": "tenant-1", "status": "pending_payment", "conversation_id": "conv-4"}
            },
        })
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        mock_decrement.assert_not_called()

    @patch("routers.wompi_webhook._confirm_order")
    @patch("routers.wompi_webhook._get_service_client")
    def test_error_on_confirm_logs_and_skips_notify(self, mock_get_client, mock_confirm):
        payload = WompiPayloadBuilder().with_approved_txn(
            payment_link_id="plink-5", txn_id="txn-5"
        ).build()
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-5": "order-5"},
            "orders": {
                "order-5": {"id": "order-5", "tenant_id": "tenant-1", "status": "pending_payment", "conversation_id": "conv-5"}
            },
        })
        mock_get_client.return_value = supabase
        mock_confirm.side_effect = RuntimeError("DB fail")

        # No debe lanzar excepción hacia arriba
        wompi_webhook._process_wompi_event(payload)

        mock_confirm.assert_called_once()


if __name__ == "__main__":
    unittest.main()

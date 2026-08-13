"""
Rev. 79 — Tests de concurrencia stock_reservation_release vs consume.

Race scenarios cubiertos:
  R1. Doble DECLINED (Wompi reintento del webhook): release_by_conversation
      es idempotente — segundo call no afecta filas que ya están 'released'.
  R2. APPROVED tras DECLINED (caso reverso/race): el webhook idempotency
      guard sobre `orders.status` debe bloquear consume cuando la orden
      ya pasó por DECLINED.

No simulamos race real (requeriría dos conexiones Postgres concurrentes).
Validamos la lógica de idempotencia y guards en el código de la app.
"""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from test_wompi_webhook import (  # noqa: E402
    WompiPayloadBuilder,
    _make_supabase_mock,
    TEST_EVENTS_KEY,
)
from routers import wompi_webhook  # noqa: E402


def _count_release_calls(supabase) -> int:
    return sum(
        1 for c in supabase.rpc.call_args_list
        if c[0][0] == "rpc_stock_reservation_release_by_conversation"
    )


class Rev79DoubleDeclinedTests(unittest.TestCase):
    """R1 — Wompi puede reintentar webhook con mismo status DECLINED.
    Cada reintento llama release pero el RPC es idempotente (UPDATE WHERE
    status='active' afecta 0 filas la segunda vez)."""

    def setUp(self):
        self._patcher = patch(
            "routers.wompi_webhook.get_tenant_wompi_creds",
            return_value=(None, TEST_EVENTS_KEY, "sandbox"),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_two_declined_events_both_call_release(self, mock_get_client, mock_decrement):
        """Cada DECLINED dispara release. La idempotencia vive en el RPC,
        no en el handler — es lo correcto, porque el handler no sabe si
        es retry o evento legítimo."""
        payload = (
            WompiPayloadBuilder()
            .with_declined_txn(payment_link_id="plink-rc1", txn_id="txn-rc1")
            .build()
        )
        # Cambiar event_id en el segundo payload para evitar dedup-checksum.
        payload2 = (
            WompiPayloadBuilder()
            .with_declined_txn(payment_link_id="plink-rc1", txn_id="txn-rc1-retry")
            .build()
        )
        for p in (payload, payload2):
            supabase = _make_supabase_mock({
                "link_to_order": {"plink-rc1": "order-rc1"},
                "orders": {
                    "order-rc1": {
                        "id": "order-rc1",
                        "tenant_id": "tenant-1",
                        "status": "pending_payment",
                        "conversation_id": "conv-rc1",
                    }
                },
            })
            mock_get_client.return_value = supabase
            wompi_webhook._process_wompi_event(p)
            self.assertEqual(
                _count_release_calls(supabase), 1,
                "Cada evento DECLINED debe disparar exactamente 1 release",
            )
        mock_decrement.assert_not_called()


class Rev79ApprovedAfterDeclinedTests(unittest.TestCase):
    """R2 — Si llega APPROVED tras una orden ya cancelada/abandonada,
    el guard de orders.status debe bloquear el consume.

    Aquí el mock simula que la orden quedó en `cancelled` (porque el flow
    DECLINED + cliente que dijo cancelar la marcó así), y verifica que el
    webhook NO confirma — preserva integridad del estado terminal."""

    def setUp(self):
        self._patcher = patch(
            "routers.wompi_webhook.get_tenant_wompi_creds",
            return_value=(None, TEST_EVENTS_KEY, "sandbox"),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._confirm_order")
    @patch("routers.wompi_webhook._get_service_client")
    def test_approved_on_already_cancelled_order_does_not_confirm(
        self, mock_get_client, mock_confirm, mock_decrement
    ):
        payload = (
            WompiPayloadBuilder()
            .with_approved_txn(payment_link_id="plink-rc2", txn_id="txn-rc2")
            .build()
        )
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-rc2": "order-rc2"},
            "orders": {
                "order-rc2": {
                    "id": "order-rc2",
                    "tenant_id": "tenant-1",
                    "status": "cancelled",  # estado terminal previo
                    "conversation_id": "conv-rc2",
                }
            },
        })
        mock_get_client.return_value = supabase
        wompi_webhook._process_wompi_event(payload)

        # Rev. 79 — el guard idempotente ahora incluye 'cancelled' como
        # estado terminal. APPROVED tardío sobre orden cancelada NO debe
        # reabrirla.
        mock_confirm.assert_not_called()
        mock_decrement.assert_not_called()


class Rev79ReleaseIdempotencyTests(unittest.TestCase):
    """R3 — release_by_conversation puede invocarse N veces sobre la misma
    conversación; el RPC en DB usa WHERE status='active' por lo que el
    segundo call afecta 0 filas. Validamos que el código del handler no
    haga side-effects extra."""

    def setUp(self):
        self._patcher = patch(
            "routers.wompi_webhook.get_tenant_wompi_creds",
            return_value=(None, TEST_EVENTS_KEY, "sandbox"),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_release_called_with_correct_conversation_id(
        self, mock_get_client, mock_decrement
    ):
        payload = (
            WompiPayloadBuilder()
            .with_declined_txn(payment_link_id="plink-rc3", txn_id="txn-rc3")
            .build()
        )
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-rc3": "order-rc3"},
            "orders": {
                "order-rc3": {
                    "id": "order-rc3",
                    "tenant_id": "tenant-1",
                    "status": "pending_payment",
                    "conversation_id": "conv-rc3",
                }
            },
        })
        mock_get_client.return_value = supabase
        wompi_webhook._process_wompi_event(payload)

        release_call = next(
            c for c in supabase.rpc.call_args_list
            if c[0][0] == "rpc_stock_reservation_release_by_conversation"
        )
        params = release_call[0][1]
        self.assertEqual(params.get("p_conversation_id"), "conv-rc3")


if __name__ == "__main__":
    unittest.main()

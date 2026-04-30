"""
Rev. 78 — Tests de los fixes de certificación E2E.

Cobertura:
  F1: DECLINED/VOIDED/ERROR libera reservas vía
      `rpc_stock_reservation_release_by_conversation`.
  F2: `_send_outbound_text` bloquea ghost messages (texto vacío/whitespace).
  F3: `format_kb_for_prompt` inyecta instrucción de cita de fuentes
      cuando hay docs reales (no markers sintéticos).
"""
import sys
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/tests")

from test_wompi_webhook import (  # noqa: E402
    WompiPayloadBuilder,
    _make_supabase_mock,
    TEST_EVENTS_KEY,
)
from routers import wompi_webhook  # noqa: E402
from tools.kb_tool import format_kb_for_prompt  # noqa: E402


class Rev78F1ReleaseReservationsTests(unittest.TestCase):
    """F1 — branch DECLINED debe llamar al RPC de liberación de reservas."""

    def setUp(self):
        self._patcher = patch(
            "routers.wompi_webhook.get_tenant_wompi_creds",
            return_value=(None, TEST_EVENTS_KEY, "sandbox"),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_declined_releases_reservations(self, mock_get_client, mock_decrement):
        payload = (
            WompiPayloadBuilder()
            .with_declined_txn(payment_link_id="plink-r1", txn_id="txn-r1")
            .build()
        )
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-r1": "order-r1"},
            "orders": {
                "order-r1": {
                    "id": "order-r1",
                    "tenant_id": "tenant-1",
                    "status": "pending_payment",
                    "conversation_id": "conv-r1",
                }
            },
        })
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        rpc_calls = [c[0] for c in supabase.rpc.call_args_list]
        self.assertIn(
            "rpc_stock_reservation_release_by_conversation",
            [name for name, _ in rpc_calls],
            f"DECLINED debe llamar el RPC de liberación. Calls vistas: {rpc_calls}",
        )
        # Validar que recibe el conversation_id de la orden.
        release_call = next(
            params for name, params in rpc_calls
            if name == "rpc_stock_reservation_release_by_conversation"
        )
        self.assertEqual(release_call.get("p_conversation_id"), "conv-r1")
        mock_decrement.assert_not_called()

    @patch("routers.orders._decrement_stock_on_confirm")
    @patch("routers.wompi_webhook._get_service_client")
    def test_voided_releases_reservations(self, mock_get_client, mock_decrement):
        payload = (
            WompiPayloadBuilder()
            .with_txn(txn_id="txn-r2", status="VOIDED", amount_in_cents=50_000)
            .with_custom_properties([
                "data.transaction.id",
                "data.transaction.status",
                "data.transaction.amount_in_cents",
            ])
            .build()
        )
        payload["data"]["transaction"]["payment_link_id"] = "plink-r2"
        supabase = _make_supabase_mock({
            "link_to_order": {"plink-r2": "order-r2"},
            "orders": {
                "order-r2": {
                    "id": "order-r2",
                    "tenant_id": "tenant-1",
                    "status": "pending_payment",
                    "conversation_id": "conv-r2",
                }
            },
        })
        mock_get_client.return_value = supabase

        wompi_webhook._process_wompi_event(payload)

        rpc_names = [c[0][0] for c in supabase.rpc.call_args_list]
        self.assertIn("rpc_stock_reservation_release_by_conversation", rpc_names)


class Rev78F2GhostMessageGuardTests(unittest.IsolatedAsyncioTestCase):
    """F2 — _send_outbound_text bloquea texto vacío/whitespace tras formato."""

    async def test_empty_string_blocked(self):
        from orchestrator import _send_outbound_text
        result = await _send_outbound_text(
            supabase=object(),
            conversation_id="conv-empty",
            tenant_id="tenant-1",
            text="",
        )
        self.assertFalse(result)

    async def test_whitespace_only_blocked(self):
        from orchestrator import _send_outbound_text
        result = await _send_outbound_text(
            supabase=object(),
            conversation_id="conv-ws",
            tenant_id="tenant-1",
            text="   \n\n   ",
        )
        self.assertFalse(result)


class Rev78F3KbCitationTests(unittest.TestCase):
    """F3 — format_kb_for_prompt agrega instrucción de cita cuando hay docs reales."""

    def test_real_docs_include_citation_instruction(self):
        docs = [{
            "title": "Política de envíos",
            "content": "Envíos a todo el país por Servientrega.",
            "category": "envios",
        }]
        out = format_kb_for_prompt(docs)
        self.assertIn("INSTRUCCIÓN DE CITA", out)
        self.assertIn("_Fuente:", out)
        self.assertIn("Política de envíos", out)

    def test_only_synthetic_markers_no_citation(self):
        docs = [{
            "title": "Envíos y tarifas — sin información configurada",
            "content": "El tenant aún no ha cargado información…",
            "category": "envios",
            "_synthetic_missing": True,
        }]
        out = format_kb_for_prompt(docs)
        self.assertNotIn("INSTRUCCIÓN DE CITA", out)

    def test_mixed_docs_include_citation(self):
        docs = [
            {
                "title": "FAQ general",
                "content": "Horarios L-V 8-6.",
                "category": "faq",
            },
            {
                "title": "Pagos — sin información configurada",
                "content": "El tenant aún no ha cargado…",
                "category": "pagos",
                "_synthetic_missing": True,
            },
        ]
        out = format_kb_for_prompt(docs)
        self.assertIn("INSTRUCCIÓN DE CITA", out)

    def test_empty_documents_returns_empty(self):
        self.assertEqual(format_kb_for_prompt([]), "")


if __name__ == "__main__":
    unittest.main()

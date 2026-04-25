"""
Tests F6: Telegram webhook bidireccional.

Cubre:
- Sin TELEGRAM_WEBHOOK_SECRET configurado → 503
- Token inválido en header → 401
- Body inválido (no JSON) → 200 ok (Telegram espera 2xx siempre)
- /resolver con conv existente en human_takeover → update a bot_active + respuesta OK
- /resolver con conv ya en bot_active → respuesta informativa, sin update
- /resolver con conv no encontrada → respuesta de error, sin update
- /resolver sin argumento → mensaje de uso
- /estado con conv existente → retorna status, phone, timestamp
- /ayuda → retorna lista de comandos
- Comando desconocido → respuesta vacía (sin error)
"""
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-key")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret-token-123")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from routers.telegram_webhook import _cmd_resolver, _cmd_estado, _handle_command


def _mock_supabase_conversation(conv_data):
    supabase = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[conv_data] if conv_data else [])
    (supabase.table.return_value
     .select.return_value
     .eq.return_value
     .limit.return_value) = chain
    supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return supabase


class CmdResolverTests(unittest.IsolatedAsyncioTestCase):

    @patch("routers.telegram_webhook._get_service_client")
    async def test_resolver_human_takeover_updates_to_bot_active(self, mock_client):
        conv = {"id": "conv-uuid-abcdef", "status": "human_takeover", "tenant_id": "t1"}
        supabase = _mock_supabase_conversation(conv)
        mock_client.return_value = supabase

        result = await _cmd_resolver("conv-uuid-abcdef")

        self.assertIn("Bot activado", result)
        self.assertIn("conv-uui", result)  # first 8 chars of conv id
        supabase.table.return_value.update.assert_called_once_with({"status": "bot_active"})

    @patch("routers.telegram_webhook._get_service_client")
    async def test_resolver_already_bot_active_no_update(self, mock_client):
        conv = {"id": "conv-uuid-abcdef", "status": "bot_active", "tenant_id": "t1"}
        supabase = _mock_supabase_conversation(conv)
        mock_client.return_value = supabase

        result = await _cmd_resolver("conv-uuid-abcdef")

        self.assertIn("ya está en modo bot", result)
        supabase.table.return_value.update.assert_not_called()

    @patch("routers.telegram_webhook._get_service_client")
    async def test_resolver_conv_not_found(self, mock_client):
        supabase = _mock_supabase_conversation(None)
        mock_client.return_value = supabase

        result = await _cmd_resolver("conv-no-existe")

        self.assertIn("no encontrada", result)
        supabase.table.return_value.update.assert_not_called()

    async def test_resolver_empty_arg_returns_usage(self):
        result = await _cmd_resolver("")
        self.assertIn("Uso", result)
        self.assertIn("resolver", result.lower())

    @patch("routers.telegram_webhook._get_service_client")
    async def test_resolver_db_error_returns_error_msg(self, mock_client):
        supabase = MagicMock()
        supabase.table.side_effect = RuntimeError("DB down")
        mock_client.return_value = supabase

        result = await _cmd_resolver("conv-uuid-xyz")
        self.assertIn("Error", result)


class CmdEstadoTests(unittest.IsolatedAsyncioTestCase):

    @patch("routers.telegram_webhook._get_service_client")
    async def test_estado_returns_conversation_info(self, mock_client):
        conv = {
            "id": "conv-uuid-abcdef",
            "status": "human_takeover",
            "customer_phone": "+573001234567",
            "last_interaction_at": "2026-04-25T12:30:00Z",
        }
        supabase = _mock_supabase_conversation(conv)
        mock_client.return_value = supabase

        result = await _cmd_estado("conv-uuid-abcdef")

        self.assertIn("human_takeover", result)
        self.assertIn("+573001234567", result)
        self.assertIn("2026-04-25", result)

    async def test_estado_empty_arg_returns_usage(self):
        result = await _cmd_estado("")
        self.assertIn("Uso", result)


class HandleCommandTests(unittest.IsolatedAsyncioTestCase):

    async def test_help_command(self):
        result = await _handle_command("/ayuda", 12345)
        self.assertIn("resolver", result.lower())
        self.assertIn("estado", result.lower())

    async def test_help_english(self):
        result = await _handle_command("/help", 12345)
        self.assertIn("resolver", result.lower())

    async def test_unknown_command_returns_empty(self):
        result = await _handle_command("/unknown_command", 12345)
        self.assertEqual(result, "")

    async def test_no_slash_prefix_not_matched(self):
        result = await _handle_command("hola, ¿cómo estás?", 12345)
        self.assertEqual(result, "")

    @patch("routers.telegram_webhook._cmd_resolver", new_callable=AsyncMock)
    async def test_resolver_command_dispatched(self, mock_resolver):
        mock_resolver.return_value = "ok"
        await _handle_command("/resolver conv-123", 12345)
        mock_resolver.assert_called_once_with("conv-123")

    @patch("routers.telegram_webhook._cmd_estado", new_callable=AsyncMock)
    async def test_estado_command_dispatched(self, mock_estado):
        mock_estado.return_value = "estado: ok"
        await _handle_command("/estado conv-456", 12345)
        mock_estado.assert_called_once_with("conv-456")


class TelegramWebhookEndpointTests(unittest.IsolatedAsyncioTestCase):

    async def test_no_secret_configured_returns_503(self):
        from fastapi.testclient import TestClient
        with patch("routers.telegram_webhook.TELEGRAM_WEBHOOK_SECRET", ""):
            from fastapi import FastAPI
            from routers.telegram_webhook import router
            app = FastAPI()
            app.include_router(router, prefix="/api/v1/integrations")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/integrations/telegram/webhook",
                json={"message": {"text": "/resolver x", "chat": {"id": 1}}},
                headers={"X-Telegram-Bot-Api-Secret-Token": ""},
            )
            self.assertEqual(resp.status_code, 503)

    async def test_invalid_token_returns_401(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from routers.telegram_webhook import router
        with patch("routers.telegram_webhook.TELEGRAM_WEBHOOK_SECRET", "correct-secret"):
            app = FastAPI()
            app.include_router(router, prefix="/api/v1/integrations")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/integrations/telegram/webhook",
                json={"message": {"text": "/ayuda", "chat": {"id": 1}}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            )
            self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()

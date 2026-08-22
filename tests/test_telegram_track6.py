"""Track 6 — Tests de la evolución Telegram (2026-08-22).

Cobertura:
  • parse_mode HTML: _build_takeover_text escapa contenido dinámico;
    notify_escalation_async escapa el reason; los senders fijan parse_mode=HTML.
  • Inline keyboard de la alerta de takeover: reply_markup con callback_data
    resolve:{conv_id} (≤64 bytes, límite oficial) + persistencia del message_id
    en telegram_alert_messages (dedup por UNIQUE chat_id+message_id).
  • callback_query: handler resolve → _cmd_resolver + answerCallbackQuery
    (obligatorio, ≤200 chars) + cierre de alertas; chat no autorizado → nada.
  • resolve_takeover_alerts: editMessageReplyMarkup (sin reply_markup = quita
    el teclado) + marca resolved_at; sin filas → 0.
  • /telegram/setup (M17): gates (rol, secret, token) + cadena
    getMe→setWebhook→setMyCommands→getWebhookInfo.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-key")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret-token-123")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import notifications  # noqa: E402
from routers import telegram_webhook  # noqa: E402
from routers.telegram_webhook import (  # noqa: E402
    _cmd_resolver,
    _handle_callback_query,
)
from lib import operator_alerts  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _tg_http_ok(message_id=777):
    """Mock de httpx.AsyncClient que responde ok=true con message_id."""
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"ok": True, "result": {"message_id": message_id}}
    mock_post = AsyncMock(return_value=resp)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_post


class TakeoverTextHtmlTests(unittest.TestCase):

    def test_takeover_text_escapes_dynamic_values(self):
        payload = {
            "conversation_id": "abc-<script>-123",
            "customer_phone": "+57 300 <b>123</b>",
        }
        text = notifications._build_takeover_text(payload)
        self.assertIn("<b>Escalamiento humano requerido</b>", text)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("&lt;b&gt;", text)  # el "bold" del cliente NO formatea

    def test_reply_markup_callback_data_within_64_bytes(self):
        conv = "123e4567-e89b-12d3-a456-426614174000"
        markup = notifications._takeover_reply_markup(conv)
        button = markup["inline_keyboard"][0][0]
        self.assertEqual(button["callback_data"], f"resolve:{conv}")
        self.assertLessEqual(len(button["callback_data"].encode()), 64)

    def test_reply_markup_none_without_conversation(self):
        self.assertIsNone(notifications._takeover_reply_markup(""))


class SendTelegramNotificationTests(unittest.TestCase):

    def test_sends_html_parse_mode_and_persists_message_id(self):
        mock_ctx, mock_post = _tg_http_ok(message_id=4242)
        supabase = MagicMock()
        config = {"bot_token": "tok", "chat_id": "-100"}
        with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
            ok = _run(notifications._send_telegram_notification(
                config, "<b>alerta</b>",
                reply_markup={"inline_keyboard": [[{"text": "✅ Resolver", "callback_data": "resolve:c1"}]]},
                alert_context={"supabase": supabase, "tenant_id": "t1", "conversation_id": "c1"},
            ))
        self.assertTrue(ok)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("reply_markup", payload)
        # Persistió (tenant, conv, chat, message_id) — clave del edit posterior.
        supabase.table.assert_called_with("telegram_alert_messages")
        row = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(row["message_id"], 4242)
        self.assertEqual(row["chat_id"], "-100")
        self.assertEqual(row["conversation_id"], "c1")

    def test_persist_failure_does_not_break_send(self):
        mock_ctx, _ = _tg_http_ok()
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("DB down")
        with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
            ok = _run(notifications._send_telegram_notification(
                {"bot_token": "tok", "chat_id": "-100"}, "texto",
                alert_context={"supabase": supabase, "tenant_id": "t1", "conversation_id": "c1"},
            ))
        self.assertTrue(ok)  # la alerta se entregó; persistir es best-effort

    def test_no_plain_text_fallback_remains(self):
        """El fallback 'can't parse entities' se eliminó: un 400 de parse es
        permanente (True, no re-encolar) SIN reintento en texto plano."""
        resp = MagicMock(status_code=400)
        resp.json.return_value = {
            "ok": False, "error_code": 400,
            "description": "Bad Request: can't parse entities",
        }
        resp.text = "can't parse entities"
        mock_post = AsyncMock(return_value=resp)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
            ok = _run(notifications._send_telegram_notification(
                {"bot_token": "tok", "chat_id": "-100"}, "texto <b>roto",
            ))
        self.assertTrue(ok)  # permanente
        self.assertEqual(mock_post.await_count, 1)  # UNA sola llamada, sin retry


class EscalationHtmlTests(unittest.TestCase):

    def test_escalation_escapes_reason(self):
        import telegram_notifications
        import vault_helper
        reason = "Cliente escribió <b>groserías</b> & más"
        supabase = MagicMock()
        supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"config": {"chat_id": "-100", "bot_token": "plain-token"}}],
        )
        # resolve_secret se importa dentro de la función DESDE vault_helper —
        # el patch debe caer sobre vault_helper.resolve_secret, no sobre el módulo.
        with patch("notifications._send_telegram_notification", new=AsyncMock(return_value=True)) as mock_send, \
             patch.object(vault_helper, "resolve_secret", return_value="tok"), \
             patch.object(vault_helper, "VaultHelper", MagicMock()):
            ok = _run(telegram_notifications.notify_escalation_async(
                supabase, tenant_id="t1", conversation_id="c123456789",
                reason=reason, severity="critical",
            ))
        self.assertTrue(ok)
        mock_send.assert_awaited_once()
        text = mock_send.await_args.args[1]
        self.assertIn("&lt;b&gt;groserías&lt;/b&gt;", text)
        self.assertIn("&amp;", text)
        self.assertIn("<b>Escalación</b>", text)
        self.assertIn("<i>Conv: c1234567</i>", text)


class CallbackQueryTests(unittest.TestCase):

    def _base_cq(self, data="resolve:conv-uuid-abcdef"):
        return {
            "id": "cq-1",
            "from": {"id": 55, "username": "oper"},
            "data": data,
            "message": {"message_id": 900, "chat": {"id": -5381900925}},
        }

    def test_resolve_callback_runs_resolver_and_answers(self):
        with patch("routers.telegram_webhook._get_service_client") as mock_client, \
             patch("lib.identity_registry.resolve_tenant_id", return_value="t1"), \
             patch("routers.telegram_webhook._resolve_bot_token", return_value="tok"), \
             patch("routers.telegram_webhook._cmd_resolver", new=AsyncMock(return_value="Bot activado en conversación conv-uui.")) as mock_resolver, \
             patch("routers.telegram_webhook._telegram_api_post") as mock_api:
            _run(_handle_callback_query(self._base_cq()))
            mock_resolver.assert_awaited_once_with("conv-uuid-abcdef", "t1")
            # answerCallbackQuery obligatorio con el resultado (≤200 chars).
            mock_api.assert_called_once()
            method = mock_api.call_args.args[1]
            payload = mock_api.call_args.args[2]
            self.assertEqual(method, "answerCallbackQuery")
            self.assertEqual(payload["callback_query_id"], "cq-1")
            self.assertLessEqual(len(payload["text"]), 200)

    def test_callback_from_unmapped_chat_does_nothing(self):
        with patch("routers.telegram_webhook._get_service_client"), \
             patch("lib.identity_registry.resolve_tenant_id", return_value=""), \
             patch("routers.telegram_webhook._resolve_and_link_via_notification_settings", return_value=""), \
             patch("routers.telegram_webhook._cmd_resolver", new=AsyncMock()) as mock_resolver, \
             patch("routers.telegram_webhook._telegram_api_post") as mock_api:
            _run(_handle_callback_query(self._base_cq()))
            mock_resolver.assert_not_awaited()
            mock_api.assert_not_called()  # sin tenant no hay token con qué responder

    def test_unknown_callback_data_answers_generic(self):
        with patch("routers.telegram_webhook._get_service_client"), \
             patch("lib.identity_registry.resolve_tenant_id", return_value="t1"), \
             patch("routers.telegram_webhook._resolve_bot_token", return_value="tok"), \
             patch("routers.telegram_webhook._telegram_api_post") as mock_api:
            _run(_handle_callback_query(self._base_cq(data="otra_accion:x")))
            payload = mock_api.call_args.args[2]
            self.assertIn("no reconocida", payload["text"])

    def test_webhook_routes_callback_query_update(self):
        """End-to-end del update: callback_query va al handler y responde 200."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        with patch.object(telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "s3cr3t"):
            with patch("routers.telegram_webhook._handle_callback_query", new=AsyncMock()) as mock_handler:
                app = FastAPI()
                app.include_router(telegram_webhook.router, prefix="/api/v1/integrations")
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/v1/integrations/telegram/webhook",
                    json={"callback_query": {"id": "cq-9", "data": "resolve:c1"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "s3cr3t"},
                )
                self.assertEqual(resp.status_code, 200)
                mock_handler.assert_awaited_once()


class CmdResolverClosesAlertsTests(unittest.TestCase):

    def test_resolver_cierra_alertas_abiertas(self):
        supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[{"id": "conv-1", "status": "human_takeover", "tenant_id": "t1"}])
        (supabase.table.return_value
         .select.return_value
         .eq.return_value
         .eq.return_value
         .limit.return_value) = chain
        with patch("routers.telegram_webhook._get_service_client", return_value=supabase), \
             patch("lib.operator_alerts.resolve_takeover_alerts") as mock_close:
            result = _run(_cmd_resolver("conv-1", "t1"))
            self.assertIn("Bot activado", result)
            mock_close.assert_called_once()
            kwargs = mock_close.call_args.kwargs
            self.assertEqual(kwargs["conversation_id"], "conv-1")
            self.assertEqual(kwargs["resolved_via"], "telegram_command")


class ResolveTakeoverAlertsTests(unittest.TestCase):

    def _supabase_with_alerts(self, rows):
        supabase = MagicMock()
        # Cadena exacta del código: select → eq(tenant) → eq(conv) → is_ → execute
        sel = supabase.table.return_value.select.return_value
        (sel.eq.return_value.eq.return_value
         .is_.return_value.execute.return_value) = MagicMock(data=rows)
        return supabase

    def test_edits_markup_and_marks_resolved(self):
        rows = [{"id": "a1", "chat_id": "-100", "message_id": 42}]
        supabase = self._supabase_with_alerts(rows)
        with patch("lib.operator_alerts._resolve_telegram_config", return_value=("tok", "-100")), \
             patch("lib.operator_alerts.httpx.Client") as mock_client_cls:
            closed = operator_alerts.resolve_takeover_alerts(
                supabase, tenant_id="t1", conversation_id="c1", resolved_via="test",
            )
        self.assertEqual(closed, 1)
        # editMessageReplyMarkup SIN reply_markup → quita el teclado (doc oficial).
        post = mock_client_cls.return_value.__enter__.return_value.post
        edit_payload = post.call_args.kwargs["json"]
        self.assertNotIn("reply_markup", edit_payload)
        self.assertEqual(edit_payload["message_id"], 42)
        # Marcada resuelta en la tabla.
        supabase.table.return_value.update.assert_called_once()

    def test_no_open_alerts_returns_zero(self):
        supabase = self._supabase_with_alerts([])
        closed = operator_alerts.resolve_takeover_alerts(
            supabase, tenant_id="t1", conversation_id="c1",
        )
        self.assertEqual(closed, 0)

    def test_lookup_error_returns_zero_no_raise(self):
        supabase = MagicMock()
        supabase.table.side_effect = RuntimeError("DB down")
        closed = operator_alerts.resolve_takeover_alerts(
            supabase, tenant_id="t1", conversation_id="c1",
        )
        self.assertEqual(closed, 0)


class OperatorAlertsHtmlTests(unittest.TestCase):

    def test_notify_operator_telegram_uses_html(self):
        with patch("lib.operator_alerts._resolve_telegram_config", return_value=("tok", "-100")), \
             patch("lib.operator_alerts.httpx.Client") as mock_client_cls:
            resp = MagicMock(status_code=200)
            mock_client_cls.return_value.__enter__.return_value.post.return_value = resp
            ok = operator_alerts.notify_operator_telegram(MagicMock(), tenant_id="t1", text="<b>x</b>")
        self.assertTrue(ok)
        payload = mock_client_cls.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["parse_mode"], "HTML")


class TelegramSetupTests(unittest.TestCase):
    """POST /telegram/setup (M17) — cadena getMe→setWebhook→setMyCommands→getWebhookInfo."""

    def _setup_env(self, mock_client_cls, calls):
        """httpx.AsyncClient mock que responde según el método llamado."""
        def _make_resp(method):
            ok_body = {
                "getMe": {"ok": True, "result": {"username": "konvi_stg_bot"}},
                "setWebhook": {"ok": True, "result": True},
                "setMyCommands": {"ok": True, "result": True},
                "getWebhookInfo": {"ok": True, "result": {
                    "url": "https://api.test/api/v1/integrations/telegram/webhook",
                    "pending_update_count": 0,
                }},
            }[method]
            resp = MagicMock(status_code=200, content=b"x")
            resp.json.return_value = ok_body
            resp.text = str(ok_body)
            return resp

        async def _post(url, json=None):
            method = url.rsplit("/", 1)[-1]
            calls.append((method, json))
            return _make_resp(method)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return mock_ctx

    def _supabase_with_token(self):
        supabase = MagicMock()
        supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"config": {"chat_id": "-100", "bot_token": "plain-tok"}}],
        )
        return supabase

    def test_role_gate_forbids_operator(self):
        from routers.integrations import telegram_setup
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            _run(telegram_setup(tenant_id="t1", supabase=MagicMock(), role="operator"))
        self.assertEqual(cm.exception.status_code, 403)

    def test_missing_webhook_secret_returns_503(self):
        from routers.integrations import telegram_setup
        from fastapi import HTTPException
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": ""}):
            with self.assertRaises(HTTPException) as cm:
                _run(telegram_setup(tenant_id="t1", supabase=MagicMock(), role="owner"))
        self.assertEqual(cm.exception.status_code, 503)

    def test_happy_path_full_chain(self):
        from routers import integrations
        calls: list = []
        mock_ctx = self._setup_env(None, calls)
        with patch.dict(os.environ, {
            "TELEGRAM_WEBHOOK_SECRET": "s3cr3t",
            "PUBLIC_WEBHOOK_URL": "https://api.test",
        }):
            with patch("routers.integrations.httpx.AsyncClient", return_value=mock_ctx), \
                 patch("routers.integrations.resolve_secret", return_value="tok", create=True), \
                 patch("vault_helper.VaultHelper"):
                # resolve_secret se importa dentro de la función desde vault_helper
                import vault_helper
                with patch.object(vault_helper, "resolve_secret", return_value="tok"):
                    result = _run(integrations.telegram_setup(
                        tenant_id="t1", supabase=self._supabase_with_token(), role="owner",
                    ))
        self.assertTrue(result["ok"])
        self.assertEqual(result["bot_username"], "konvi_stg_bot")
        methods = [m for m, _ in calls]
        self.assertEqual(methods, ["getMe", "setWebhook", "setMyCommands", "getWebhookInfo"])
        # setWebhook con secret_token + allowed_updates de Track 6.
        sw = dict(calls[1][1])
        self.assertEqual(sw["secret_token"], "s3cr3t")
        self.assertEqual(sw["allowed_updates"], ["message", "callback_query"])
        self.assertTrue(sw["drop_pending_updates"])
        self.assertEqual(
            sw["url"], "https://api.test/api/v1/integrations/telegram/webhook",
        )


if __name__ == "__main__":
    unittest.main()

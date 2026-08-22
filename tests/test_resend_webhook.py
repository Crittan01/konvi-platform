"""Track 6 — Tests del webhook de eventos Resend (routers/resend_webhook.py).

Cobertura:
  • Sin RESEND_WEBHOOK_SECRET configurado → 503
  • Firma svix inválida → 401 (y NADA se persiste)
  • Firma válida → 200 + evento persistido con routing desde tags
    (tenant_id/order_id, recipient normalizado, email_id)
  • Re-entrega (mismo svix_id) → 200 duplicate, sin doble procesamiento
  • email.bounced/complained/failed/suppressed → alerta Telegram al operador
  • suppression.added → persistido (con recipient=data.email), SIN alerta
  • Evento sin tags → tenant NULL, solo persistido (sin alerta)
  • is_email_suppressed: último evento added → True, removed → False

La firma se genera con la MISMA lib oficial (svix) — el esquema es
HMAC-SHA256 sobre "{svix-id}.{svix-timestamp}.{body}" con secret whsec_...
Tests aislados con mocks (sin red, sin Supabase real).
"""
import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-key")
os.environ.setdefault("RESEND_WEBHOOK_SECRET", "whsec_dGVzdC1zZWNyZXQta29udmktdHJhY2s2")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from svix.webhooks import Webhook  # noqa: E402

from routers import resend_webhook  # noqa: E402
from routers.resend_webhook import (  # noqa: E402
    _build_row,
    _persist_event,
    _process_resend_event,
)

TEST_SECRET = "whsec_dGVzdC1zZWNyZXQta29udmktdHJhY2s2"
TENANT_A = "11111111-1111-1111-1111-111111111111"
ORDER_A = "22222222-2222-2222-2222-222222222222"


def _signed_headers(body: bytes, msg_id: str = "msg_test_1", secret: str = TEST_SECRET) -> dict:
    """Headers svix con firma VÁLIDA generada por la lib oficial.

    Un ÚNICO timestamp para firmar y para el header (la firma cubre el
    timestamp — usar dos llamadas a time.time() puede diferir en 1s y la
    verificación fallaría intermitentemente).
    """
    ts_int = int(time.time())
    ts = datetime.fromtimestamp(ts_int, tz=timezone.utc)
    sig = Webhook(secret).sign(msg_id=msg_id, timestamp=ts, data=body.decode())
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(ts_int),
        "svix-signature": sig,
        "content-type": "application/json",
    }


def _payload(event_type: str, **data_overrides) -> bytes:
    data = {
        "email_id": "email-uuid-123",
        "from": "Konvi STG <onboarding@resend.dev>",
        "to": ["Cliente@Example.com"],
        "subject": "Pago recibido — Pedido #ABCD1234",
        "created_at": "2026-08-22T10:00:00.000Z",
        "tags": {"tenant_id": TENANT_A, "order_id": ORDER_A, "template": "payment_confirmed"},
    }
    data.update(data_overrides)
    return json.dumps({"type": event_type, "created_at": "2026-08-22T10:00:01.000Z", "data": data}).encode()


def _make_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(resend_webhook.router, prefix="/api/v1/webhooks")
    return TestClient(app, raise_server_exceptions=False)


def _mock_supabase_insert_ok():
    """Supabase mock: insert OK + cadena completa del lookup de correlación."""
    supabase = MagicMock()
    supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "1"}])
    return supabase


class ResendWebhookEndpointTests(unittest.TestCase):

    def test_no_secret_returns_503(self):
        with patch.object(resend_webhook, "RESEND_WEBHOOK_SECRET", ""):
            client = _make_client()
            resp = client.post("/api/v1/webhooks/resend", content=b"{}")
            self.assertEqual(resp.status_code, 503)

    def test_invalid_signature_returns_401_and_persists_nothing(self):
        with patch.object(resend_webhook, "RESEND_WEBHOOK_SECRET", TEST_SECRET):
            with patch("routers.resend_webhook._get_service_client") as mock_client:
                mock_client.return_value = _mock_supabase_insert_ok()
                client = _make_client()
                body = _payload("email.bounced")
                resp = client.post(
                    "/api/v1/webhooks/resend",
                    content=body,
                    headers={
                        "svix-id": "msg_x",
                        "svix-timestamp": str(int(time.time())),
                        "svix-signature": "v1,firmaadulterada==",
                    },
                )
                self.assertEqual(resp.status_code, 401)
                # Nada se persistió: la firma gobierna antes que cualquier otra lógica.
                mock_client.return_value.table.assert_not_called()

    def test_valid_signature_persists_event_with_routing(self):
        with patch.object(resend_webhook, "RESEND_WEBHOOK_SECRET", TEST_SECRET):
            with patch("routers.resend_webhook._get_service_client") as mock_client, \
                 patch("routers.resend_webhook._process_resend_event") as mock_proc:
                supabase = _mock_supabase_insert_ok()
                mock_client.return_value = supabase
                client = _make_client()
                body = _payload("email.delivered")
                resp = client.post(
                    "/api/v1/webhooks/resend",
                    content=body,
                    headers=_signed_headers(body, "msg_delivered_1"),
                )
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json()["received"])
                # Persistió con routing: tenant/order desde tags, recipient
                # normalizado a minúsculas, svix_id del header.
                supabase.table.assert_called_with("email_events")
                row = supabase.table.return_value.insert.call_args.args[0]
                self.assertEqual(row["svix_id"], "msg_delivered_1")
                self.assertEqual(row["tenant_id"], TENANT_A)
                self.assertEqual(row["order_id"], ORDER_A)
                self.assertEqual(row["event_type"], "email.delivered")
                self.assertEqual(row["recipient"], "cliente@example.com")
                self.assertEqual(row["email_id"], "email-uuid-123")
                # delivered NO alerta (no está en _ALERT_EVENT_TYPES) pero sí se
                # evalúa en background.
                mock_proc.assert_called_once()

    def test_duplicate_svix_id_returns_duplicate_without_processing(self):
        with patch.object(resend_webhook, "RESEND_WEBHOOK_SECRET", TEST_SECRET):
            with patch("routers.resend_webhook._get_service_client") as mock_client, \
                 patch("routers.resend_webhook._process_resend_event") as mock_proc:
                supabase = MagicMock()
                supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
                    'duplicate key value violates unique constraint "email_events_svix_id_key" (23505)'
                )
                mock_client.return_value = supabase
                client = _make_client()
                body = _payload("email.bounced")
                resp = client.post(
                    "/api/v1/webhooks/resend",
                    content=body,
                    headers=_signed_headers(body, "msg_dup_1"),
                )
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json().get("duplicate"))
                mock_proc.assert_not_called()

    def test_bounced_triggers_telegram_alert(self):
        row = _build_row("msg_b1", "email.bounced", json.loads(_payload("email.bounced", bounce={
            "message": "smtp; 550 5.1.1 mailbox unavailable", "type": "Permanent", "subType": "General",
        })))
        with patch("routers.resend_webhook._get_service_client") as mock_client, \
             patch("routers.resend_webhook.notify_operator_telegram") as mock_alert:
            mock_alert.return_value = True
            _process_resend_event("email.bounced", row)
            mock_alert.assert_called_once()
            kwargs = mock_alert.call_args.kwargs
            self.assertEqual(kwargs["tenant_id"], TENANT_A)
            self.assertIn("cliente@example.com", kwargs["text"])
            self.assertIn("rebotado", kwargs["text"])
            self.assertIn("mailbox unavailable", kwargs["text"])
            self.assertIn("#22222222", kwargs["text"])  # order corto en mayúsculas

    def test_complained_failed_suppressed_also_alert(self):
        for event_type in ("email.complained", "email.failed", "email.suppressed"):
            row = _build_row("msg_x", event_type, json.loads(_payload(event_type)))
            with patch("routers.resend_webhook._get_service_client"), \
                 patch("routers.resend_webhook.notify_operator_telegram") as mock_alert:
                _process_resend_event(event_type, row)
                mock_alert.assert_called_once(), f"{event_type} debió alertar"

    def test_suppression_added_persists_without_alert(self):
        body = _payload("suppression.added", **{
            "id": "supp-1", "email": "Cliente@Example.com", "origin": "bounce",
            "source_id": "email-uuid-123",
        })
        # suppression.*: recipient desde data.email (no hay data.to) y
        # email_id desde source_id (correlación).
        payload = json.loads(body)
        # quitar los campos de email.* que no vienen en suppression.*
        payload["data"].pop("to", None)
        payload["data"].pop("tags", None)
        row = _build_row("msg_supp_1", "suppression.added", payload)
        self.assertEqual(row["recipient"], "cliente@example.com")
        self.assertEqual(row["email_id"], "email-uuid-123")
        self.assertIsNone(row["tenant_id"])  # suppression.* no trae tags
        with patch("routers.resend_webhook._get_service_client"), \
             patch("routers.resend_webhook.notify_operator_telegram") as mock_alert:
            _process_resend_event("suppression.added", row)
            mock_alert.assert_not_called()

    def test_event_without_tags_persists_with_null_tenant_no_alert(self):
        body = _payload("email.bounced", tags={})
        row = _build_row("msg_notags", "email.bounced", json.loads(body))
        self.assertIsNone(row["tenant_id"])
        self.assertIsNone(row["order_id"])
        with patch("routers.resend_webhook._get_service_client"), \
             patch("routers.resend_webhook.notify_operator_telegram") as mock_alert:
            _process_resend_event("email.bounced", row)
            mock_alert.assert_not_called()

    def test_suppression_tenant_correlation_via_source_id(self):
        """suppression.added sin tags → tenant por correlación source_id → email_id."""
        supabase = MagicMock()
        # El lookup de correlación devuelve un evento previo con tenant.
        # OJO: `.not_` es acceso de atributo (no llamada) → sin .return_value.
        corr_chain = supabase.table.return_value.select.return_value
        corr_chain.eq.return_value.not_.is_.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"tenant_id": TENANT_A}],
        )
        row = {
            "svix_id": "msg_corr", "tenant_id": None, "order_id": None,
            "email_id": "email-uuid-123", "event_type": "suppression.added",
            "recipient": "a@b.com", "payload": {}, "occurred_at": None,
        }
        result = _persist_event(supabase, row)
        self.assertTrue(result)
        self.assertEqual(row["tenant_id"], TENANT_A)


class EmailSuppressionTests(unittest.TestCase):
    """lib/email_suppression.py — exclusión de direcciones en senders."""

    def _supabase_with_rows(self, rows):
        from lib.email_suppression import is_email_suppressed  # noqa: F401
        supabase = MagicMock()
        chain = supabase.table.return_value.select.return_value.eq.return_value.in_.return_value
        chain.order.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=rows)
        return supabase

    def test_last_event_added_is_suppressed(self):
        from lib.email_suppression import is_email_suppressed
        supabase = self._supabase_with_rows([{"event_type": "suppression.added"}])
        self.assertTrue(is_email_suppressed(supabase, "Cliente@Example.com"))

    def test_last_event_removed_is_not_suppressed(self):
        from lib.email_suppression import is_email_suppressed
        supabase = self._supabase_with_rows([{"event_type": "suppression.removed"}])
        self.assertFalse(is_email_suppressed(supabase, "a@b.com"))

    def test_no_events_is_not_suppressed(self):
        from lib.email_suppression import is_email_suppressed
        supabase = self._supabase_with_rows([])
        self.assertFalse(is_email_suppressed(supabase, "a@b.com"))

    def test_db_error_fails_open(self):
        from lib.email_suppression import is_email_suppressed
        supabase = MagicMock()
        supabase.table.side_effect = RuntimeError("DB down")
        self.assertFalse(is_email_suppressed(supabase, "a@b.com"))

    def test_empty_email_is_not_suppressed(self):
        from lib.email_suppression import is_email_suppressed
        self.assertFalse(is_email_suppressed(MagicMock(), ""))


class SenderSuppressionTests(unittest.TestCase):
    """_send_email_via_resend (orchestrator): skip de destinatarios suprimidos."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))
        import notifications  # noqa: F401
        self.notifications = notifications

    def test_suppressed_recipient_returns_false_without_http(self):
        import asyncio
        with patch.object(self.notifications, "RESEND_API_KEY", "re_test"):
            with patch.object(self.notifications, "_is_suppressed", return_value=True):
                with patch("notifications.httpx.AsyncClient") as mock_client:
                    ok = asyncio.new_event_loop().run_until_complete(
                        self.notifications._send_email_via_resend(
                            to="suprimido@example.com", subject="S", html="<p>h</p>",
                            supabase=MagicMock(),
                        )
                    )
        self.assertFalse(ok)
        mock_client.assert_not_called()

    def test_not_suppressed_sends_normally(self):
        import asyncio
        from unittest.mock import AsyncMock
        mock_post = AsyncMock(return_value=MagicMock(status_code=200, text='{"id":"x"}', headers={}))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch.object(self.notifications, "RESEND_API_KEY", "re_test"):
            with patch.object(self.notifications, "_is_suppressed", return_value=False):
                with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
                    ok = asyncio.new_event_loop().run_until_complete(
                        self.notifications._send_email_via_resend(
                            to="sano@example.com", subject="S", html="<p>h</p>",
                            supabase=MagicMock(),
                        )
                    )
        self.assertTrue(ok)
        mock_post.assert_called_once()


if __name__ == "__main__":
    unittest.main()

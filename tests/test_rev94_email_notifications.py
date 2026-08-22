"""Rev. 94 — Tests del módulo de notificaciones email vía Resend.

Cobertura:
  • _send_email_via_resend: payload shape, headers, fallback sin API key,
    manejo de 4xx vs 5xx.
  • notify_consent_revoked: arma subject + body, llama dispatcher.
  • notify_sar_received: arma subject según sar_type.
  • _notify_tenant_event: filtra notification_settings por
    channel='email' + enabled=True.

Tests aislados con mocks (sin red, sin Supabase real).
"""
import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import notifications  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class SendEmailViaResendTests(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_no_api_key_returns_true_no_call(self):
        # Sin RESEND_API_KEY: log-only, no http.
        with patch.object(notifications, "RESEND_API_KEY", ""):
            with patch("notifications.httpx.AsyncClient") as mock_client:
                ok = self.loop.run_until_complete(
                    notifications._send_email_via_resend(
                        to="t@x.com", subject="Test", html="<p>x</p>",
                    )
                )
        self.assertTrue(ok)
        mock_client.assert_not_called()

    def test_with_key_posts_to_resend_endpoint(self):
        mock_post = AsyncMock(return_value=MagicMock(
            status_code=200, text='{"id":"abc"}',
        ))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(notifications, "RESEND_API_KEY", "re_test_key"):
            with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
                ok = self.loop.run_until_complete(
                    notifications._send_email_via_resend(
                        to="t@x.com", subject="S", html="<p>h</p>",
                    )
                )
        self.assertTrue(ok)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(
            mock_post.call_args.args[0], "https://api.resend.com/emails"
        )
        self.assertIn("Authorization", call_kwargs["headers"])
        self.assertTrue(
            call_kwargs["headers"]["Authorization"].startswith("Bearer ")
        )
        body = call_kwargs["json"]
        self.assertEqual(body["to"], ["t@x.com"])
        self.assertEqual(body["subject"], "S")
        self.assertEqual(body["html"], "<p>h</p>")

    def test_4xx_returns_false_not_delivered(self):
        # BLOQUE H (review Fable HIGH): el bool es "¿entregado (2xx)?", no
        # "¿reintentar?". Un 4xx (incl. 429 rate-limit) = NO entregado → False.
        # Antes devolvía True en 4xx, lo que en el path donde el email gobierna
        # (refund sin conversación) marcaba 'cliente notificado' en falso.
        mock_post = AsyncMock(return_value=MagicMock(
            status_code=400, text='{"error":"bad_request"}',
        ))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(notifications, "RESEND_API_KEY", "re_x"):
            with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
                ok = self.loop.run_until_complete(
                    notifications._send_email_via_resend(
                        to="t@x.com", subject="S", html="<p>h</p>",
                    )
                )
        self.assertFalse(ok)

    def test_429_rate_limit_returns_false(self):
        # 429 (cuota free tier 100/día) es transitorio → NO entregado → False,
        # para que el caller (cron refund) reintente el próximo ciclo.
        mock_post = AsyncMock(return_value=MagicMock(
            status_code=429, text='{"error":"rate_limit"}',
        ))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(notifications, "RESEND_API_KEY", "re_x"):
            with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
                ok = self.loop.run_until_complete(
                    notifications._send_email_via_resend(
                        to="t@x.com", subject="S", html="<p>h</p>",
                    )
                )
        self.assertFalse(ok)

    def test_5xx_returns_false_for_retry(self):
        mock_post = AsyncMock(return_value=MagicMock(
            status_code=503, text="upstream",
        ))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(notifications, "RESEND_API_KEY", "re_x"):
            with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
                ok = self.loop.run_until_complete(
                    notifications._send_email_via_resend(
                        to="t@x.com", subject="S", html="<p>h</p>",
                    )
                )
        self.assertFalse(ok)

    def test_unreachable_returns_false(self):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("DNS down"))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(notifications, "RESEND_API_KEY", "re_x"):
            with patch("notifications.httpx.AsyncClient", return_value=mock_ctx):
                ok = self.loop.run_until_complete(
                    notifications._send_email_via_resend(
                        to="t@x.com", subject="S", html="<p>h</p>",
                    )
                )
        self.assertFalse(ok)


class NotifyConsentRevokedTests(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.sb = MagicMock()
        # notification_settings con un email row.
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[
            {"channel": "email", "enabled": True,
             "config": {"to_email": "ops@kaiu.co"}}
        ])

    def tearDown(self):
        self.loop.close()

    def test_dispatches_email_to_recipient(self):
        sent = []

        async def fake_send(*, to, subject, html, text=None, tags=None, reply_to=None, idempotency_key=None, supabase=None):
            sent.append({"to": to, "subject": subject, "html": html})
            return True

        with patch.object(notifications, "_send_email_via_resend", side_effect=fake_send):
            ok = self.loop.run_until_complete(
                notifications.notify_consent_revoked(
                    self.sb,
                    tenant_id="t-1",
                    contact_phone_hash="abc123def456" * 5 + "9999",
                    occurred_at="2026-05-01T12:00:00Z",
                    source="whatsapp",
                )
            )
        self.assertTrue(ok)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["to"], "ops@kaiu.co")
        self.assertIn("revoc", sent[0]["subject"].lower())
        self.assertIn("Habeas", sent[0]["subject"])
        self.assertIn("whatsapp", sent[0]["html"])

    def test_no_recipients_returns_true(self):
        # Sin email rows configurados — OK (no-op).
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[])
        ok = self.loop.run_until_complete(
            notifications.notify_consent_revoked(
                self.sb, tenant_id="t-1",
                contact_phone_hash="x", occurred_at="2026-05-01", source="whatsapp",
            )
        )
        self.assertTrue(ok)

    def test_empty_tenant_id_returns_true(self):
        ok = self.loop.run_until_complete(
            notifications.notify_consent_revoked(
                self.sb, tenant_id="",
                contact_phone_hash="x", occurred_at="2026-05-01", source="whatsapp",
            )
        )
        self.assertTrue(ok)


class NotifySarReceivedTests(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.sb = MagicMock()
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[
            {"channel": "email", "enabled": True,
             "config": {"to_email": "legal@kaiu.co"}}
        ])

    def tearDown(self):
        self.loop.close()

    def test_export_sar_subject_mentions_export(self):
        sent = []

        async def fake_send(*, to, subject, html, text=None, tags=None, reply_to=None, idempotency_key=None, supabase=None):
            sent.append({"subject": subject, "html": html})
            return True

        with patch.object(notifications, "_send_email_via_resend", side_effect=fake_send):
            self.loop.run_until_complete(
                notifications.notify_sar_received(
                    self.sb, tenant_id="t-1",
                    contact_id="contact-uuid-12345678",
                    sar_type="export",
                )
            )
        self.assertEqual(len(sent), 1)
        self.assertIn("export", sent[0]["subject"].lower())
        self.assertIn("Habeas", sent[0]["subject"])

    def test_erase_sar_includes_reason(self):
        sent = []

        async def fake_send(*, to, subject, html, text=None, tags=None, reply_to=None, idempotency_key=None, supabase=None):
            sent.append({"html": html})
            return True

        with patch.object(notifications, "_send_email_via_resend", side_effect=fake_send):
            self.loop.run_until_complete(
                notifications.notify_sar_received(
                    self.sb, tenant_id="t-1",
                    contact_id="c-1", sar_type="erase",
                    reason="Cliente solicitó borrado total",
                )
            )
        self.assertIn("Cliente solicitó borrado total", sent[0]["html"])


class NotifyTenantEventTests(unittest.TestCase):
    """Test del dispatcher genérico — filtros y multi-recipient."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.sb = MagicMock()

    def tearDown(self):
        self.loop.close()

    def test_filters_only_email_channel(self):
        # Verificar que el query incluye .eq("channel", "email").
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[])

        self.loop.run_until_complete(
            notifications._notify_tenant_event(
                self.sb, tenant_id="t-1",
                event_type="test_event", subject="S", html_body="<p>h</p>",
            )
        )
        # Verificar las llamadas .eq que se hicieron en el chain.
        eq_calls = self.sb.table.return_value.select.return_value.eq.call_args_list
        # Primera .eq debe ser tenant_id.
        self.assertEqual(eq_calls[0].args, ("tenant_id", "t-1"))

    def test_multi_recipient_dispatch(self):
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[
            {"channel": "email", "enabled": True,
             "config": {"to_email": "ops@x.com"}},
            {"channel": "email", "enabled": True,
             "config": {"to_email": "legal@x.com"}},
        ])
        sent_to = []

        async def fake_send(*, to, subject, html, text=None, tags=None, reply_to=None, idempotency_key=None, supabase=None):
            sent_to.append(to)
            return True

        with patch.object(notifications, "_send_email_via_resend", side_effect=fake_send):
            ok = self.loop.run_until_complete(
                notifications._notify_tenant_event(
                    self.sb, tenant_id="t-1", event_type="x",
                    subject="S", html_body="h",
                )
            )
        self.assertTrue(ok)
        self.assertEqual(set(sent_to), {"ops@x.com", "legal@x.com"})

    def test_skips_rows_without_recipient(self):
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[
            {"channel": "email", "enabled": True, "config": {}},  # sin to_email
        ])
        sent_count = [0]

        async def fake_send(*, to, subject, html, text=None, tags=None, reply_to=None, idempotency_key=None, supabase=None):
            sent_count[0] += 1
            return True

        with patch.object(notifications, "_send_email_via_resend", side_effect=fake_send):
            self.loop.run_until_complete(
                notifications._notify_tenant_event(
                    self.sb, tenant_id="t-1", event_type="x",
                    subject="S", html_body="h",
                )
            )
        self.assertEqual(sent_count[0], 0)


if __name__ == "__main__":
    unittest.main()

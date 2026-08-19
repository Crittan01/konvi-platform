"""F6 — ejercicio de derechos Habeas Data en el path agéntico (decisión founder Opción A).

- Art. 14 (acceso): el bot responde SELF-SERVICE con el resumen ENMASCARADO → NO escala.
- Art. 16 (rectificación) y supresión: ESCALAN a humano (el bot no auto-edita ni auto-borra PII).
- Todo con paper-trail en consent_audit_log.
"""
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.dispatcher import _handle_data_rights_if_intent  # noqa: E402
from lib.habeas_data_request import classify_data_rights_request  # noqa: E402


class ClassifierTests(unittest.TestCase):
    def test_classification(self):
        cases = {
            "¿qué datos tienen de mí?": "access",
            "quiero ver mis datos personales": "access",
            "por favor borren mis datos": "suppression",
            "retiro mi consentimiento": "suppression",
            "corrijan mis datos por favor": "rectification",
            "actualicen mi dirección": "rectification",
            "mis datos están mal": "rectification",
            "quiero comprar 2 unidades": None,
        }
        for txt, expected in cases.items():
            self.assertEqual(classify_data_rights_request(txt), expected, txt)


class _FakeSb:
    def __init__(self, contact_id="contact-1"):
        self.contact_id = contact_id
        self.updates = []       # (table, data) de los UPDATE
        self.audit_events = []  # events insertados en consent_audit_log
        self._tbl = None
        self._pending = None

    def table(self, name):
        self._tbl = name
        self._pending = None
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def limit(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def update(self, data, *a, **k):
        self._pending = ("update", self._tbl, data)
        return self

    def insert(self, data, *a, **k):
        self._pending = ("insert", self._tbl, data)
        return self

    def execute(self):
        if self._pending:
            op, tbl, data = self._pending
            if op == "update":
                self.updates.append((tbl, data))
                return types.SimpleNamespace(data=[{"id": "x"}])
            if op == "insert":
                if tbl == "consent_audit_log":
                    self.audit_events.append(data.get("event"))
                return types.SimpleNamespace(data=[{}])
        # F2: _resolve_contact_id consulta conversations.customer_phone → contacts.phone.
        if self._tbl == "conversations":
            return types.SimpleNamespace(data=[{"customer_phone": "573001112222"}])
        if self._tbl == "contacts":
            return types.SimpleNamespace(
                data=[{"id": self.contact_id}] if self.contact_id else []
            )
        return types.SimpleNamespace(data=[])

    def _escalated(self):
        return any(t == "conversations" and d.get("status") == "human_takeover"
                   for (t, d) in self.updates)


class AccessSelfServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_access_sends_masked_summary_without_escalating(self):
        sb = _FakeSb()
        with patch("orchestrator._send_outbound_text", new=AsyncMock()) as send, \
             patch("orchestrator._mark_message_processing", new=MagicMock()), \
             patch("orchestrator._build_customer_data_summary", new=MagicMock(return_value="RESUMEN ENMASCARADO")):
            r = await _handle_data_rights_if_intent(
                sb, message_id="m", tenant_id="t", conversation_id="c",
                content="¿qué datos tienen de mí?", content_type="text")
        self.assertTrue(r)
        send.assert_awaited()
        self.assertIn("RESUMEN ENMASCARADO", send.await_args.kwargs.get("text", ""))
        self.assertFalse(sb._escalated(), "acceso Art.14 es self-service: NO debe escalar")
        self.assertIn("export_request", sb.audit_events)


class SuppressionRectificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletion_escalates(self):
        sb = _FakeSb()
        with patch("orchestrator._send_outbound_text", new=AsyncMock()), \
             patch("orchestrator._mark_message_processing", new=MagicMock()), \
             patch("telegram_notifications.notify_escalation_async", new=AsyncMock()) as notify:
            r = await _handle_data_rights_if_intent(
                sb, message_id="m", tenant_id="t", conversation_id="c",
                content="borren mis datos ya", content_type="text")
        self.assertTrue(r)
        self.assertTrue(sb._escalated(), "supresión debe escalar a humano")
        self.assertIn("data_rights_request", sb.audit_events)
        notify.assert_awaited()

    async def test_rectification_escalates_not_autoedits(self):
        sb = _FakeSb()
        with patch("orchestrator._send_outbound_text", new=AsyncMock()), \
             patch("orchestrator._mark_message_processing", new=MagicMock()), \
             patch("telegram_notifications.notify_escalation_async", new=AsyncMock()):
            r = await _handle_data_rights_if_intent(
                sb, message_id="m", tenant_id="t", conversation_id="c",
                content="corrijan mis datos por favor", content_type="text")
        self.assertTrue(r)
        self.assertTrue(sb._escalated(), "rectificación escala (no auto-edita PII)")


if __name__ == "__main__":
    unittest.main()

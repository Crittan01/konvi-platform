"""F6 — gate de menores en el path AGENTIC (Decreto 1377/2013 Art. 7).

Portado del legacy (orchestrator.py:7758) que en el agentic no corría → un menor autodeclarado seguía
siendo atendido por el bot. El gate: detecta menor → responde pidiendo representante → escala a
human_takeover → notifica. Aquí: guardas (no-texto / no-menor → no procesa) + caso positivo (escala).
"""
import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.dispatcher import _handle_minor_intent_if_applicable  # noqa: E402


class _Cap:
    """Fake supabase que captura los UPDATE a conversations."""
    def __init__(self):
        self.updates = []
        self._t = None
        self._op = None

    def table(self, name):
        self._t = name; self._op = None; return self

    def update(self, data, *_a, **_k):
        self._op = ("update", self._t, data); return self

    def select(self, *_a, **_k):
        self._op = ("select", self._t); return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._op and self._op[0] == "update":
            self.updates.append(self._op)
        return types.SimpleNamespace(data=[])


class MinorGateGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_text_returns_false(self):
        # content_type != text → guarda temprana, ni siquiera evalúa detección.
        r = await _handle_minor_intent_if_applicable(
            _Cap(), message_id="m", tenant_id="t", conversation_id="c",
            content="tengo 15 años", content_type="image")
        self.assertFalse(r)

    async def test_non_minor_returns_false(self):
        sb = _Cap()
        r = await _handle_minor_intent_if_applicable(
            sb, message_id="m", tenant_id="t", conversation_id="c",
            content="quiero comprar un jabón de lavanda", content_type="text")
        self.assertFalse(r)
        self.assertEqual(sb.updates, [])   # no escala si no es menor


class MinorGateEscalationTests(unittest.IsolatedAsyncioTestCase):
    async def test_minor_detected_escalates_and_returns_true(self):
        sb = _Cap()
        with patch("orchestrator._send_outbound_text", new=AsyncMock()), \
             patch("orchestrator._mark_message_processing", new=MagicMock()), \
             patch("telegram_notifications.notify_escalation_async", new=AsyncMock()) as notify:
            r = await _handle_minor_intent_if_applicable(
                sb, message_id="m1", tenant_id="t1", conversation_id="c1",
                content="hola, tengo 15 años, quiero comprar", content_type="text")
        self.assertTrue(r)   # procesó → el caller NO avanza al LLM
        # escaló a human_takeover
        self.assertTrue(any(
            op == "update" and tbl == "conversations" and data.get("status") == "human_takeover"
            for (op, tbl, data) in sb.updates
        ))
        notify.assert_awaited()   # notificó al operador


if __name__ == "__main__":
    unittest.main()

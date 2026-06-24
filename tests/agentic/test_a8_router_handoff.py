"""A8 finiquito — Handoff sintético del agent_router con consumer REAL.

Audit §1 #8 + §6: cuando el agent_router clasifica un inbound para un rol que
NINGÚN agente del tenant cubre, devuelve _HANDOFF_SYNTHETIC_AGENT con
_needs_human_handoff=True. Antes el dispatcher IGNORABA el flag: el bot respondía
"te contacto con un asesor" pero NADIE era notificado y la conv NO se marcaba
human_takeover → promesa rota.

Fix: _consume_router_handoff materializa el side-effect (status=human_takeover +
audit append-only + notificar operador), igual que escalate_to_human.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic import dispatcher as disp  # noqa: E402


class _FakeTable:
    def __init__(self, name, sink, *, update_raises=False):
        self.name = name
        self.sink = sink
        self._update_raises = update_raises
        self._mode = None
        self._payload = None

    def update(self, payload):
        self._mode, self._payload = "update", payload
        return self

    def insert(self, payload):
        self.sink.append((self.name, "insert", payload))
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        if self._mode == "update":
            if self._update_raises and self.name == "conversations":
                raise RuntimeError("db down")
            self.sink.append((self.name, "update", self._payload))
        return SimpleNamespace(data=[{"id": "x"}])


class _FakeSupabase:
    def __init__(self, *, update_raises=False):
        self.ops = []
        self._update_raises = update_raises

    def table(self, name):
        return _FakeTable(name, self.ops, update_raises=self._update_raises)


class RouterHandoffConsumerTests(unittest.TestCase):
    def test_handoff_marks_human_takeover_and_notifies(self):
        sb = _FakeSupabase()
        with patch("telegram_notifications.notify_escalation_async",
                   new_callable=AsyncMock) as mock_notify:
            ok = asyncio.run(disp._consume_router_handoff(sb, "tenant-A", "conv-1"))
        self.assertTrue(ok)
        # status=human_takeover marcado
        updates = [d for (n, op, d) in sb.ops if n == "conversations" and op == "update"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["status"], "human_takeover")
        # audit append-only en messages
        audits = [d for (n, op, d) in sb.ops
                  if n == "messages" and op == "insert"
                  and d.get("content_type") == "escalation_audit"]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["payload"]["source"], "agent_router_handoff")
        # operador notificado
        mock_notify.assert_awaited_once()

    def test_handoff_returns_false_if_status_update_fails(self):
        sb = _FakeSupabase(update_raises=True)
        with patch("telegram_notifications.notify_escalation_async",
                   new_callable=AsyncMock) as mock_notify:
            ok = asyncio.run(disp._consume_router_handoff(sb, "tenant-A", "conv-1"))
        self.assertFalse(ok)
        # Sin status no notifica (no puede garantizar takeover sin marcarlo).
        mock_notify.assert_not_awaited()

    def test_synthetic_agent_has_handoff_flag(self):
        # Contrato: el agente sintético del router lleva el flag que dispara
        # el consumer.
        from agentic.agent_router import _HANDOFF_SYNTHETIC_AGENT
        self.assertTrue(_HANDOFF_SYNTHETIC_AGENT.get("_needs_human_handoff"))
        self.assertEqual(_HANDOFF_SYNTHETIC_AGENT.get("tools_allowed"), [])


if __name__ == "__main__":
    unittest.main()

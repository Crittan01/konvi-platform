"""A5 finiquito — Habeas Data Ley 1581: audit de TODA escritura de PII.

Antes los 6 SaveTool (email/name/document/address/shipping_phone/contact_field)
mutaban PII vía `_write_contact_update` SIN escribir a `pii_access_log`. Solo
get_contact_info (reads) y record_consent auditaban → ante auditoría SIC no había
trazabilidad de WRITES (Art. 17 lit. e + Art. 21).

Fix: `_write_contact_update` (chokepoint único de los 6) inserta en pii_access_log
con accessed_by='agentic_tool:save_pii:<field>', fields_accessed=<keys>,
purpose='pii_update'. Best-effort (no rompe el flujo) pero con logger.warning.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.tools.base import ToolContext  # noqa: E402
from agentic.tools import contact as contact_mod  # noqa: E402
from agentic.tools.contact import _write_contact_update, SaveEmailTool, SaveEmailArgs  # noqa: E402


class _FakeTable:
    def __init__(self, name, sink, *, update_raises=False):
        self.name = name
        self.sink = sink
        self._update_raises = update_raises

    def update(self, data):
        self._pending = ("update", data)
        return self

    def insert(self, data):
        self.sink.append((self.name, "insert", data))
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        if getattr(self, "_pending", (None,))[0] == "update":
            if self._update_raises and self.name == "contacts":
                raise RuntimeError("db down")
            self.sink.append((self.name, "update", self._pending[1]))
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self, *, contacts_update_raises=False):
        self.ops = []
        self._contacts_update_raises = contacts_update_raises

    def table(self, name):
        return _FakeTable(
            name, self.ops,
            update_raises=self._contacts_update_raises,
        )


def _ctx(sb):
    return ToolContext(
        tenant_id="tenant-A", conversation_id="conv-1",
        contact_id="contact-1", supabase=sb,
    )


def _audit_inserts(sb):
    return [d for (n, op, d) in sb.ops if n == "pii_access_log" and op == "insert"]


class WriteAuditTests(unittest.TestCase):
    def test_single_field_write_audits(self):
        sb = _FakeSupabase()
        res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "a@b.com"}, "email"))
        self.assertTrue(res.success)
        audits = _audit_inserts(sb)
        self.assertEqual(len(audits), 1)
        a = audits[0]
        self.assertEqual(a["accessed_by"], "agentic_tool:save_pii:email")
        self.assertEqual(a["fields_accessed"], ["email"])
        self.assertEqual(a["purpose"], "pii_update")
        self.assertEqual(a["tenant_id"], "tenant-A")
        self.assertEqual(a["contact_id"], "contact-1")

    def test_multi_field_write_audits_sorted_keys(self):
        sb = _FakeSupabase()
        res = asyncio.run(_write_contact_update(
            _ctx(sb),
            {"document_number": "123", "document_type": "CC"},
            "document",
        ))
        self.assertTrue(res.success)
        audits = _audit_inserts(sb)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["fields_accessed"], ["document_number", "document_type"])
        self.assertEqual(audits[0]["accessed_by"], "agentic_tool:save_pii:document")

    def test_contacts_update_failure_no_audit(self):
        # Si el UPDATE de contacts falla, NO se audita (no hubo escritura real).
        sb = _FakeSupabase(contacts_update_raises=True)
        res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "a@b.com"}, "email"))
        self.assertFalse(res.success)
        self.assertEqual(len(_audit_inserts(sb)), 0)

    def test_audit_failure_is_best_effort(self):
        # Si el insert de audit falla, el WRITE de PII NO se revierte (best-effort)
        # pero se loggea warning (no pass silencioso).
        class _AuditFailSupabase(_FakeSupabase):
            def table(self, name):
                t = super().table(name)
                if name == "pii_access_log":
                    orig = t.insert
                    def _boom(_data):
                        raise RuntimeError("audit table down")
                    t.insert = _boom
                return t

        sb = _AuditFailSupabase()
        with patch.object(contact_mod.logger, "warning") as mock_warn:
            res = asyncio.run(_write_contact_update(_ctx(sb), {"name": "Ana"}, "name"))
        self.assertTrue(res.success)  # el WRITE no se rompe
        mock_warn.assert_called_once()  # pero el fallo de audit es observable


class SaveToolEndToEndTests(unittest.TestCase):
    def test_save_email_tool_routes_to_audit(self):
        # Prueba que un SaveTool real (con consent OK) genera el audit WRITE.
        sb = _FakeSupabase()

        async def _run():
            with patch.object(contact_mod, "_verify_consent_or_fail", return_value=None):
                return await SaveEmailTool().execute(
                    SaveEmailArgs(value="cliente@ejemplo.com"), _ctx(sb),
                )
        res = asyncio.run(_run())
        self.assertTrue(res.success)
        audits = _audit_inserts(sb)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["accessed_by"], "agentic_tool:save_pii:email")


if __name__ == "__main__":
    unittest.main()

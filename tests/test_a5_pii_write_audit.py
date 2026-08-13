"""A5 finiquito — Habeas Data Ley 1581: audit de TODA escritura de PII.

Antes los 6 SaveTool (email/name/document/address/shipping_phone/contact_field)
mutaban PII vía `_write_contact_update` SIN escribir a `pii_access_log`. Solo
get_contact_info (reads) y record_consent auditaban → ante auditoría SIC no había
trazabilidad de WRITES (Art. 17 lit. e + Art. 21).

Fix: `_write_contact_update` (chokepoint único de los 6) inserta en pii_access_log
(purpose='pii_update'). Best-effort + logger.warning.

Extensión (decisión founder): si el WRITE CORRIGE un valor existente (no colección
inicial), además emite consent_audit_log event='rectified' (Art. 8 lit. c, aparece
en sic_report). Se lee el valor previo para distinguir corrección vs colección.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.tools.base import ToolContext  # noqa: E402
from agentic.tools import contact as contact_mod  # noqa: E402
from agentic.tools.contact import _write_contact_update, SaveEmailTool, SaveEmailArgs  # noqa: E402


class _FakeTable:
    def __init__(self, name, sink, prior_contacts, *, update_raises=False, insert_raises_for=None):
        self.name = name
        self.sink = sink
        self.prior = prior_contacts
        self._update_raises = update_raises
        self._insert_raises_for = insert_raises_for or set()
        self._mode = None
        self._payload = None

    def select(self, *a, **k):
        self._mode = "select"
        return self

    def update(self, data):
        self._mode = "update"
        self._payload = data
        return self

    def insert(self, data):
        if self.name in self._insert_raises_for:
            raise RuntimeError(f"{self.name} insert down")
        self.sink.append((self.name, "insert", data))
        self._mode = "insert"
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self._mode == "select":
            if self.name == "contacts" and self.prior is not None:
                return SimpleNamespace(data=[self.prior])
            return SimpleNamespace(data=[])
        if self._mode == "update":
            if self._update_raises and self.name == "contacts":
                raise RuntimeError("db down")
            self.sink.append((self.name, "update", self._payload))
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self, *, prior_contacts=None, contacts_update_raises=False, insert_raises_for=None):
        self.ops = []
        self._prior = prior_contacts
        self._contacts_update_raises = contacts_update_raises
        self._insert_raises_for = insert_raises_for or set()

    def table(self, name):
        return _FakeTable(
            name, self.ops, self._prior,
            update_raises=self._contacts_update_raises,
            insert_raises_for=self._insert_raises_for,
        )


def _ctx(sb):
    return ToolContext(
        tenant_id="tenant-A", conversation_id="conv-1",
        contact_id="contact-1", supabase=sb,
    )


def _inserts(sb, table):
    return [d for (n, op, d) in sb.ops if n == table and op == "insert"]


class PiiAccessAuditTests(unittest.TestCase):
    def test_single_field_write_audits(self):
        sb = _FakeSupabase()
        res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "a@b.com"}, "email"))
        self.assertTrue(res.success)
        audits = _inserts(sb, "pii_access_log")
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
            _ctx(sb), {"document_number": "123", "document_type": "CC"}, "document",
        ))
        self.assertTrue(res.success)
        audits = _inserts(sb, "pii_access_log")
        self.assertEqual(audits[0]["fields_accessed"], ["document_number", "document_type"])

    def test_contacts_update_failure_no_audit(self):
        sb = _FakeSupabase(contacts_update_raises=True)
        res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "a@b.com"}, "email"))
        self.assertFalse(res.success)
        self.assertEqual(len(_inserts(sb, "pii_access_log")), 0)

    def test_audit_failure_is_best_effort(self):
        sb = _FakeSupabase(insert_raises_for={"pii_access_log"})
        with patch.object(contact_mod.logger, "warning") as mock_warn:
            res = asyncio.run(_write_contact_update(_ctx(sb), {"name": "Ana"}, "name"))
        self.assertTrue(res.success)
        mock_warn.assert_called_once()


class RectifiedAuditTests(unittest.TestCase):
    def test_initial_collection_no_rectified(self):
        # Sin valor previo (colección inicial) → pii_access_log sí, rectified NO.
        sb = _FakeSupabase(prior_contacts={"email": None})
        res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "a@b.com"}, "email"))
        self.assertTrue(res.success)
        self.assertEqual(len(_inserts(sb, "pii_access_log")), 1)
        self.assertEqual(len(_inserts(sb, "consent_audit_log")), 0)

    def test_correction_emits_rectified(self):
        # Valor previo distinto (corrección) → pii_access_log + rectified.
        sb = _FakeSupabase(prior_contacts={"email": "old@b.com"})
        res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "new@b.com"}, "email"))
        self.assertTrue(res.success)
        self.assertEqual(len(_inserts(sb, "pii_access_log")), 1)
        rect = _inserts(sb, "consent_audit_log")
        self.assertEqual(len(rect), 1)
        self.assertEqual(rect[0]["event"], "rectified")
        self.assertEqual(rect[0]["source"], "whatsapp")
        self.assertEqual(rect[0]["tenant_id"], "tenant-A")
        self.assertEqual(rect[0]["conversation_id"], "conv-1")
        self.assertEqual(rect[0]["evidence"]["fields_rectified"], ["email"])

    def test_same_value_resave_no_rectified(self):
        # Re-guardar el MISMO valor → no es rectificación.
        sb = _FakeSupabase(prior_contacts={"email": "a@b.com"})
        res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "a@b.com"}, "email"))
        self.assertTrue(res.success)
        self.assertEqual(len(_inserts(sb, "consent_audit_log")), 0)

    def test_multifield_only_changed_in_rectified(self):
        # 2 campos: uno nuevo (doc_type colección), otro corregido (doc_number).
        sb = _FakeSupabase(prior_contacts={"document_number": "111", "document_type": None})
        res = asyncio.run(_write_contact_update(
            _ctx(sb), {"document_number": "222", "document_type": "CC"}, "document",
        ))
        self.assertTrue(res.success)
        rect = _inserts(sb, "consent_audit_log")
        self.assertEqual(len(rect), 1)
        # Solo document_number era corrección (document_type era colección inicial).
        self.assertEqual(rect[0]["evidence"]["fields_rectified"], ["document_number"])

    def test_rectified_audit_failure_best_effort(self):
        sb = _FakeSupabase(
            prior_contacts={"email": "old@b.com"},
            insert_raises_for={"consent_audit_log"},
        )
        with patch.object(contact_mod.logger, "warning") as mock_warn:
            res = asyncio.run(_write_contact_update(_ctx(sb), {"email": "new@b.com"}, "email"))
        self.assertTrue(res.success)  # el WRITE no se rompe
        mock_warn.assert_called_once()


class SaveToolEndToEndTests(unittest.TestCase):
    def test_save_email_tool_routes_to_audit(self):
        sb = _FakeSupabase()

        async def _run():
            with patch.object(contact_mod, "_verify_consent_or_fail", return_value=None):
                return await SaveEmailTool().execute(
                    SaveEmailArgs(value="cliente@ejemplo.com"), _ctx(sb),
                )
        res = asyncio.run(_run())
        self.assertTrue(res.success)
        self.assertEqual(len(_inserts(sb, "pii_access_log")), 1)


if __name__ == "__main__":
    unittest.main()

"""Tests del tool escalate_to_human + record_consent (Habeas Data).

ADR-0018 production-grade.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from agentic.tools.base import ToolContext
from agentic.tools.escalation import EscalateToHumanTool, EscalateToHumanArgs
from agentic.tools.contact import (
    RecordConsentTool, RecordConsentArgs,
    SavePIITool, SavePIIArgs,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeQuery:
    def __init__(self, returns=None, raises=None):
        self._returns = returns or []
        self._raises = raises
        self.calls = []

    def select(self, *a, **k): self.calls.append(("select", a, k)); return self
    def insert(self, data): self.calls.append(("insert", data)); return self
    def update(self, data): self.calls.append(("update", data)); return self
    def delete(self): self.calls.append(("delete",)); return self
    def eq(self, c, v): self.calls.append(("eq", c, v)); return self
    def single(self): self.calls.append(("single",)); return self
    def limit(self, n): self.calls.append(("limit", n)); return self

    def execute(self):
        if self._raises:
            raise self._raises
        return MagicMock(data=self._returns)


class _FakeSupabase:
    def __init__(self):
        self.tables = {}
    def set_table(self, name, returns=None, raises=None):
        self.tables[name] = _FakeQuery(returns=returns, raises=raises)
    def table(self, name):
        return self.tables.setdefault(name, _FakeQuery())


class RecordConsentToolTests(unittest.TestCase):

    def test_registra_consent_yes_actualiza_db_y_audit_log(self):
        sb = _FakeSupabase()
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb,
        )
        tool = RecordConsentTool()
        result = _run(tool.execute(
            RecordConsentArgs(given=True, consent_text="ok"),
            ctx,
        ))
        self.assertTrue(result.success)
        self.assertTrue(result.data["consent_given"])
        # Verificar que escribió en contacts + consent_audit_log.
        self.assertIn("contacts", sb.tables)
        self.assertIn("consent_audit_log", sb.tables)

    def test_falla_si_no_hay_contact_id(self):
        sb = _FakeSupabase()
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id=None,
            supabase=sb,
        )
        tool = RecordConsentTool()
        result = _run(tool.execute(RecordConsentArgs(given=True), ctx))
        self.assertFalse(result.success)
        self.assertEqual(result.data["code"], "NO_CONTACT")


class SavePIIToolTests(unittest.TestCase):

    def test_falla_si_consent_no_dado(self):
        """Habeas Data: save_pii REQUIERE consent_given=True en DB."""
        sb = _FakeSupabase()
        sb.set_table("contacts", returns={"consent_given": False})
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb,
        )
        tool = SavePIITool()
        result = _run(tool.execute(
            SavePIIArgs(field="email", value="x@y.com"),
            ctx,
        ))
        self.assertFalse(result.success)
        self.assertEqual(result.data["code"], "CONSENT_REQUIRED")

    def test_guarda_email_con_consent(self):
        sb = _FakeSupabase()
        sb.set_table("contacts", returns={"consent_given": True})
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb,
        )
        tool = SavePIITool()
        result = _run(tool.execute(
            SavePIIArgs(field="email", value="cliente@ejemplo.com"),
            ctx,
        ))
        self.assertTrue(result.success)
        self.assertEqual(result.data["field"], "email")

    def test_validation_email_mal_formado_rechaza(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SavePIIArgs(field="email", value="no-es-email")

    def test_validation_document_requiere_type_number(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SavePIIArgs(field="document", value="solo string")

    def test_document_valido_estructura_dict(self):
        args = SavePIIArgs(
            field="document",
            value={"type": "CC", "number": "1032414179"},
        )
        self.assertEqual(args.value["type"], "CC")

    def test_document_type_invalido_rechaza(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SavePIIArgs(field="document", value={"type": "INVALID", "number": "123"})


class EscalateToHumanToolTests(unittest.TestCase):

    def test_marca_conversation_como_human_takeover(self):
        sb = _FakeSupabase()
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb,
        )
        tool = EscalateToHumanTool()
        result = _run(tool.execute(
            EscalateToHumanArgs(reason="cliente pide hablar con asesor humano"),
            ctx,
        ))
        self.assertTrue(result.success)
        self.assertEqual(result.data["conversation_status"], "human_takeover")

    def test_validation_reason_min_length(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            EscalateToHumanArgs(reason="x")  # < 10 chars


if __name__ == "__main__":
    unittest.main()

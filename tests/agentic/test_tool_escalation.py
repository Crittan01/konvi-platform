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
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.tools.base import ToolContext
from agentic.tools.escalation import EscalateToHumanTool, EscalateToHumanArgs
from agentic.tools.contact import (
    RecordConsentTool, RecordConsentArgs,
    SaveEmailTool, SaveEmailArgs,
    SaveNameTool, SaveNameArgs,
    SaveDocumentTool, SaveDocumentArgs,
    SaveAddressTool, SaveAddressArgs,
    SaveShippingPhoneTool, SaveShippingPhoneArgs,
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


class SavePIIToolsTests(unittest.TestCase):
    """Tests de los 5 save_* tools (1 por campo PII)."""

    def _ctx(self, consent: bool):
        sb = _FakeSupabase()
        sb.set_table("contacts", returns={"consent_given": consent})
        return ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb,
        )

    def test_save_email_falla_si_consent_no_dado(self):
        result = _run(SaveEmailTool().execute(
            SaveEmailArgs(value="cliente@ejemplo.com"),
            self._ctx(consent=False),
        ))
        self.assertFalse(result.success)
        self.assertEqual(result.data["code"], "CONSENT_REQUIRED")

    def test_save_email_guarda_con_consent(self):
        result = _run(SaveEmailTool().execute(
            SaveEmailArgs(value="cliente@ejemplo.com"),
            self._ctx(consent=True),
        ))
        self.assertTrue(result.success)
        self.assertEqual(result.data["field"], "email")

    def test_save_email_validation_rechaza_invalido(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SaveEmailArgs(value="no-es-email")

    def test_save_document_requiere_type_y_number(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SaveDocumentArgs(doc_type="CC")  # falta doc_number
        with self.assertRaises(ValidationError):
            SaveDocumentArgs(doc_type="INVALID", doc_number="123456")

    def test_save_document_guarda_con_consent(self):
        result = _run(SaveDocumentTool().execute(
            SaveDocumentArgs(doc_type="CC", doc_number="1032414179"),
            self._ctx(consent=True),
        ))
        self.assertTrue(result.success)
        self.assertEqual(result.data["field"], "document")

    def test_save_address_requiere_building_type(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SaveAddressArgs(
                street="Cl 36",
                city="Bogotá",
                building_type="INVALID",
            )

    def test_save_address_guarda_con_consent(self):
        result = _run(SaveAddressTool().execute(
            SaveAddressArgs(
                street="Cl 36A # 6-87",
                city="Bogotá",
                building_type="oficina",
                apartment="301",
                floor="3",
            ),
            self._ctx(consent=True),
        ))
        self.assertTrue(result.success)

    def test_save_shipping_phone_validation(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SaveShippingPhoneArgs(value="123")  # < 10 chars

    def test_save_name_guarda_con_consent(self):
        result = _run(SaveNameTool().execute(
            SaveNameArgs(value="Cristian Camilo Garzon"),
            self._ctx(consent=True),
        ))
        self.assertTrue(result.success)


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

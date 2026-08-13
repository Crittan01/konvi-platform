"""Regresión A11 UAT — al otorgar consent vía bot, se setean los timestamps
denormalizados (consent_date + consent_given_at), no solo el flag.

Bug (founder UAT): el contacto quedaba con consent_given=True pero
consent_date=NULL. La UI Tenant Console muestra "consent desde {consent_date}"
y el export SAR Habeas Data muestra "Otorgado en {consent_given_at}" — ambos
quedaban en blanco para consents otorgados por el bot. El consent_audit_log
canónico SÍ tenía el timestamp, pero estas columnas denormalizadas no.

Fix: record_consent tool (GRANTED) + resolver pre-LLM del dispatcher setean
consent_date + consent_given_at + limpian consent_revoked_at.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))


class _CaptureSb:
    """Mock supabase mínimo: captura .update()/.insert() por tabla."""

    def __init__(self):
        self.updates = {}
        self.inserts = {}
        self._tbl = None

    def table(self, name):
        self._tbl = name
        return self

    def update(self, data):
        self.updates.setdefault(self._tbl, []).append(data)
        return self

    def insert(self, data):
        self.inserts.setdefault(self._tbl, []).append(data)
        return self

    def eq(self, *a, **kw):
        return self

    def execute(self):
        return MagicMock(data=[])


class ConsentDateSetTests(unittest.TestCase):
    def _run_grant(self, given: bool):
        import agentic.tools.contact  # noqa: F401 — registra el tool
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext

        tool = get_tool("record_consent")
        sb = _CaptureSb()
        ctx = ToolContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            contact_id="00000000-0000-0000-0000-000000000003",
            supabase=sb, extras={}, logger=MagicMock(),
        )
        args = tool.args_schema(given=given, consent_text="Sí, autorizo")
        asyncio.new_event_loop().run_until_complete(tool.execute(args, ctx))
        return sb

    def test_granted_sets_both_timestamps(self):
        sb = self._run_grant(given=True)
        updates = sb.updates.get("contacts", [])
        self.assertTrue(updates, "record_consent no escribió contacts.update")
        upd = updates[0]
        self.assertTrue(upd.get("consent_given"))
        self.assertIn("consent_date", upd)
        self.assertIn("consent_given_at", upd)
        self.assertIsNotNone(upd["consent_date"])
        self.assertIsNotNone(upd["consent_given_at"])
        # Re-grant limpia revocación previa:
        self.assertIsNone(upd.get("consent_revoked_at"))

    def test_revoked_does_not_set_grant_date(self):
        sb = self._run_grant(given=False)
        updates = sb.updates.get("contacts", [])
        self.assertTrue(updates)
        upd = updates[0]
        self.assertFalse(upd.get("consent_given"))
        # En revocación NO se setea consent_date (no es un otorgamiento):
        self.assertNotIn("consent_date", upd)


if __name__ == "__main__":
    unittest.main()

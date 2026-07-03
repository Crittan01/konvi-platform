"""F33 — Consolidación de los formateadores de teléfono display CO.

Había 2 copias inline divergentes (summary_coherence._format_phone y el bloque
inline de contact.GetContactInfoTool) que solo manejaban 12 dígitos (57+10) y caían
a str(raw) crudo para 10 dígitos locales. Ahora ambas delegan en la fuente única
lib.phone_format.format_phone_co, que sí formatea 10 dígitos.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from lib.phone_format import format_phone_co  # noqa: E402


class FormatPhoneCoTests(unittest.TestCase):
    def test_10_digit_local_se_formatea(self):
        """El caso que las copias inline perdían: 10 dígitos → '+57 312 583 5649'."""
        self.assertEqual(format_phone_co("3125835649"), "+57 312 583 5649")

    def test_12_digit_con_prefijo(self):
        self.assertEqual(format_phone_co("573125835649"), "+57 312 583 5649")

    def test_ya_formateado_passthrough(self):
        # No matchea 10/12 dígitos crudos → passthrough.
        self.assertEqual(format_phone_co("+57 312 583 5649"), "+57 312 583 5649")

    def test_vacio_o_none(self):
        self.assertEqual(format_phone_co(""), "")
        self.assertEqual(format_phone_co(None), "")

    def test_robustez_no_string(self):
        """F33 hardening: input no-string (int) se coacciona sin crashear."""
        self.assertEqual(format_phone_co(3125835649), "+57 312 583 5649")


class DelegationTests(unittest.TestCase):
    def test_summary_coherence_delega_a_fuente_unica(self):
        from agentic.invariants import summary_coherence
        # El alias _format_phone ES format_phone_co (misma función).
        self.assertIs(summary_coherence._format_phone, format_phone_co)

    def test_contact_tool_formatea_10_digitos(self):
        """GetContactInfoTool devuelve phone_formatted con 10 dígitos bien formateados."""
        import asyncio
        import agentic.tools.contact  # noqa: F401
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext

        tool = get_tool("get_contact_info")
        sb = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.insert.return_value = chain
        chain.execute.return_value = MagicMock(data={
            "id": "ct-1", "consent_given": True, "name": "Ana", "email": None,
            "phone": "3125835649", "shipping_phone": None,
            "document_type": None, "document_number": None, "address": {},
        })
        sb.table.return_value = chain
        ctx = ToolContext(
            tenant_id="t-1", conversation_id="c-1", contact_id="ct-1",
            supabase=sb, extras={}, logger=MagicMock(),
        )
        r = asyncio.new_event_loop().run_until_complete(tool.execute(tool.args_schema(), ctx))
        self.assertTrue(r.success)
        self.assertEqual(r.data["phone_formatted"], "+57 312 583 5649")


if __name__ == "__main__":
    unittest.main()

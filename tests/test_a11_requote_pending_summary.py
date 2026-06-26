"""A11 2026-06-26 — RequotePendingSummaryInvariant.

Conversación +573125835649: el cliente agregó un Sérum a mitad del checkout, el
envío se invalidó (requires_requote=True) pero el bot presentó un resumen con
Total=Subtotal SIN envío. El invariant reescribe a recotizar.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.invariants.requote_pending_summary import (  # noqa: E402
    RequotePendingSummaryInvariant,
)
from agentic.invariants.base import InvariantOutcome  # noqa: E402


def _sb(cart):
    sb = MagicMock()
    q = MagicMock()
    q.eq.return_value = q       # chain-agnóstico (varios .eq())
    q.neq.return_value = q
    q.order.return_value = q
    q.limit.return_value = q
    q.execute.return_value = MagicMock(data=([cart] if cart else []))
    sb.table.return_value.select.return_value = q
    return sb


_SUMMARY = (
    "📋 *Resumen de tu pedido:*\n* 1 Sérum de Vitamina C: $85.000 COP\n"
    "* Subtotal: $214.000 COP\n* *Total: $214.000 COP*"
)


def _run(text, cart):
    inv = RequotePendingSummaryInvariant()
    return asyncio.new_event_loop().run_until_complete(inv.validate(
        candidate_text=text, tenant_id="t", conversation_id="c", contact_id=None,
        supabase=_sb(cart), tool_call_log=[], inbound_text=""))


class RequotePendingSummaryTests(unittest.TestCase):
    def test_resumen_con_requote_pendiente_reescribe(self):
        r = _run(_SUMMARY, {"requires_requote": True, "shipping_cents": 0, "status": "open"})
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("recalcular", r.replacement_text.lower())
        self.assertIn("envío", r.replacement_text)

    def test_resumen_normal_no_dispara(self):
        # Envío vigente (requires_requote=False) → resumen OK.
        r = _run(_SUMMARY, {"requires_requote": False, "shipping_cents": 16500, "status": "open"})
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_sin_total_no_toca_db(self):
        # Sin marcador de resumen/total → OK sin consultar carrito.
        sb = MagicMock()
        inv = RequotePendingSummaryInvariant()
        r = asyncio.new_event_loop().run_until_complete(inv.validate(
            candidate_text="¿Qué presentación prefieres?", tenant_id="t",
            conversation_id="c", contact_id=None, supabase=sb, tool_call_log=[]))
        self.assertEqual(r.outcome, InvariantOutcome.OK)
        sb.table.assert_not_called()  # pre-check evitó la DB

    def test_sin_carrito_no_dispara(self):
        r = _run(_SUMMARY, None)
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_link_de_pago_con_requote_reescribe(self):
        r = _run("Genero el link de pago por $214.000.",
                 {"requires_requote": True, "shipping_cents": 0, "status": "open"})
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)


if __name__ == "__main__":
    unittest.main()

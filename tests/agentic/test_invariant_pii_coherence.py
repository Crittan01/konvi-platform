"""Tests del PIICoherenceInvariant.

Rev. 107 — bug runtime KAIU 7b45bfc6: bot heredó document_number de
contact previo (Pedro) y NO pidió cédula a María. Resumen pudo haber
mostrado cédula incorrecta. Este invariant detecta mismatch outbound
vs contact real (name/email) y reescribe a prompt de verificación.

Validar coherencia datos en TODA LA SOLUCIÓN (founder feedback) —
no solo cart, también contact, name, email, etc.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_sb_contact(name=None, email=None, document_number=None, recipient_name=None):
    """Mock multi-tabla: contacts.single() retorna contact data,
    conversation_carts.execute() retorna shipping_meta.recipient.

    Rev. 109 BUG 42b — PIICoherenceInvariant lee recipient del cart para
    detectar envío a tercero (no es mismatch del titular).
    """
    sb = MagicMock()

    def _table_router(table_name):
        chain = MagicMock()
        # contacts: chain.select().eq().single().execute() → contact data
        # conversation_carts: chain.select().eq().eq().in_().order().limit().execute() → list
        if table_name == "contacts":
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.single.return_value = chain
            chain.execute.return_value = MagicMock(data={
                "name": name,
                "email": email,
                "document_number": document_number,
            })
        elif table_name == "conversation_carts":
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.in_.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            recipient_data = {}
            if recipient_name:
                recipient_data = {
                    "shipping_meta": {"recipient": {"name": recipient_name}},
                }
            chain.execute.return_value = MagicMock(
                data=[recipient_data] if recipient_data else [],
            )
        return chain

    sb.table.side_effect = _table_router
    return sb


class PIICoherenceTests(unittest.TestCase):

    def setUp(self):
        from agentic.invariants.pii_coherence import PIICoherenceInvariant
        self.inv = PIICoherenceInvariant()
        self.base = {
            "tenant_id": "t", "conversation_id": "c", "contact_id": "ct-1",
            "supabase": _make_sb_contact(name="María López", email="maria@ejemplo.com"),
        }

    def test_sin_contact_id_ok(self):
        from agentic.invariants.base import InvariantOutcome
        b = dict(self.base, contact_id=None)
        r = _run(self.inv.validate(
            candidate_text="Datos de envío:\nNombre: Pedro",
            tool_call_log=[],
            **b,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_outbound_sin_pii_block_ok(self):
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="Te muestro nuestros jabones.",
            tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_name_coherente_ok(self):
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="Datos de envío:\n*Nombre:* María López\n*Email:* maria@ejemplo.com",
            tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_name_mismatch_rewrite(self):
        """Caso runtime KAIU: contact.name='María López' pero outbound
        contiene 'Nombre: Pedro Pérez' (heredado/inventado)."""
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="Datos de envío:\n*Nombre:* Pedro Pérez",
            tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("verificar", r.replacement_text.lower())

    def test_email_mismatch_rewrite(self):
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="Datos de envío:\n*Email:* otra@email.com",
            tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_tildes_match_flexible(self):
        """'maria lopez' (sin tildes) debe match con 'María López'."""
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="Datos de envío:\n*Nombre:* maria lopez",
            tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_db_unreadable_ok_best_effort(self):
        from agentic.invariants.base import InvariantOutcome
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = Exception("db down")
        b = dict(self.base, supabase=sb)
        r = _run(self.inv.validate(
            candidate_text="Datos de envío:\n*Nombre:* X",
            tool_call_log=[], **b,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)


if __name__ == "__main__":
    unittest.main()

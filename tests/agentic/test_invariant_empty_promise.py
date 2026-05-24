"""Tests EmptyPromiseInvariant — bug runtime KAIU 2026-05-24 conv eb21c1fc.

Bot dice "Un momento, estoy calculando" sin haber corrido quote_shipping
→ cliente queda esperando indefinidamente. REWRITE forzado a CTA.
"""
import asyncio
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from agentic.invariants import EmptyPromiseInvariant, InvariantOutcome


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class EmptyPromiseInvariantTests(unittest.TestCase):

    def setUp(self):
        self.inv = EmptyPromiseInvariant()
        self.base = {
            "tenant_id": "t",
            "conversation_id": "c",
            "contact_id": "ct",
            "supabase": None,
        }

    def test_un_momento_sin_tool_rewrite(self):
        """Bug runtime KAIU 2026-05-24: 'Un momento, estoy calculando'
        con tools=0 → REWRITE a CTA de cotización."""
        text = (
            "Claro, Cristian. Un momento por favor, estoy calculando el "
            "costo de envío a Medellín."
        )
        r = _run(self.inv.validate(
            candidate_text=text, tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("Medellín", r.replacement_text)
        self.assertIn("cotizar", r.replacement_text.lower())

    def test_estoy_calculando_con_quote_shipping_ok(self):
        """Si corrió quote_shipping, la 'promesa' es coherente → OK."""
        text = "Listo, estoy calculando opciones — aquí van:"
        r = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[
                {"tool": "quote_shipping",
                 "result": {"options": [{"rate_id": "x"}]}},
            ],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_dejame_revisar_sin_tool_rewrite(self):
        """'Déjame revisar tus pedidos anteriores' sin get_recent_orders
        → REWRITE."""
        text = "Déjame revisar tus pedidos anteriores y te confirmo."
        r = _run(self.inv.validate(
            candidate_text=text, tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("pedidos", r.replacement_text.lower())

    def test_permiteme_consultar_sin_tool_rewrite(self):
        text = "Permíteme consultar el catálogo y te muestro las opciones."
        r = _run(self.inv.validate(
            candidate_text=text, tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_un_momento_pero_con_list_catalog_ok(self):
        """'Un momento, consulto catálogo' con list_catalog ejecutado → OK."""
        text = "Un momento por favor — aquí están las presentaciones:"
        r = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[
                {"tool": "list_catalog", "result": {"products": []}},
            ],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_outbound_sin_promesa_ok(self):
        """Outbound normal sin promesa de acción → OK."""
        text = "Listo, Cristian. Ya agregué el sérum a tu carrito."
        r = _run(self.inv.validate(
            candidate_text=text, tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_voy_a_cotizar_sin_tool_rewrite(self):
        text = "Voy a cotizar el envío para ti."
        r = _run(self.inv.validate(
            candidate_text=text, tool_call_log=[], **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)


if __name__ == "__main__":
    unittest.main()

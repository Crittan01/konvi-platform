"""BLOQUE 0 · Regresión del P0 — get_claim_status debe scopear por cliente.

Antes: get_claim_status filtraba solo por (tenant_id, ticket_number). Como
ticket_number es un secuencial per-tenant, un cliente podía leer por WhatsApp el
reclamo de OTRO cliente del mismo tenant (reason/resolution_notes = PII enumerable).
Fix: filtro por customer_id == ctx.contact_id + fail-closed si no hay contact_id.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))

from agentic.tools.base import ToolContext
from agentic.tools.claims import (
    CreateClaimArgs,
    CreateClaimTool,
    GetClaimStatusArgs,
    GetClaimStatusTool,
)


class _RecordingQuery:
    def __init__(self, rows):
        self._rows = rows
        self.eqs = []

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.eqs.append((col, val))
        return self

    def limit(self, *_):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _RecordingSupabase:
    def __init__(self, rows):
        self.query = _RecordingQuery(rows)
        self.table_called = False

    def table(self, _name):
        self.table_called = True
        return self.query


class ClaimCustomerScopingTests(unittest.TestCase):
    def test_fail_closed_sin_contact_id_no_consulta(self):
        """Sin contact_id resuelto → tool_failure y NUNCA se corre el query."""
        sb = _RecordingSupabase(rows=[{"ticket_number": 42, "status": "open"}])
        ctx = ToolContext(tenant_id="t1", conversation_id="c1", contact_id=None, supabase=sb)
        res = asyncio.run(GetClaimStatusTool().execute(GetClaimStatusArgs(ticket_number=42), ctx))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "CLAIM_LOOKUP_NO_CONTACT")
        self.assertFalse(sb.table_called, "fail-closed: no debe tocar la DB sin contact_id")

    def test_query_scopea_por_customer_id(self):
        """El query incluye .eq('customer_id', ctx.contact_id) además de tenant+ticket."""
        sb = _RecordingSupabase(rows=[{
            "ticket_number": 42, "status": "open", "reason": "producto dañado",
            "resolution_notes": None, "created_at": "x", "updated_at": "y",
        }])
        ctx = ToolContext(tenant_id="t1", conversation_id="c1", contact_id="ct-owner", supabase=sb)
        res = asyncio.run(GetClaimStatusTool().execute(GetClaimStatusArgs(ticket_number=42), ctx))
        self.assertTrue(res.success)
        self.assertIn(("customer_id", "ct-owner"), sb.query.eqs)
        self.assertIn(("tenant_id", "t1"), sb.query.eqs)
        self.assertIn(("ticket_number", 42), sb.query.eqs)

    def test_ticket_de_otro_cliente_no_se_filtra(self):
        """Ticket de otro cliente (query no matchea por customer_id) → NOT_FOUND, no leak."""
        sb = _RecordingSupabase(rows=[])  # el filtro por customer_id no devuelve nada
        ctx = ToolContext(tenant_id="t1", conversation_id="c1", contact_id="ct-attacker", supabase=sb)
        res = asyncio.run(GetClaimStatusTool().execute(GetClaimStatusArgs(ticket_number=5), ctx))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "CLAIM_NOT_FOUND")
        # confirma que el aislamiento vino del filtro por cliente
        self.assertIn(("customer_id", "ct-attacker"), sb.query.eqs)


class CreateClaimOrderOwnershipTests(unittest.TestCase):
    """BLOQUE 0 (review) — create_claim debe scopear el pedido por contact_id.

    Antes: el lookup del pedido filtraba solo (id, tenant_id) → un cliente podía radicar
    un reclamo sobre el pedido de OTRO cliente del mismo tenant conociendo su UUID, y
    customer_id quedaba mal atribuido. Fix: fail-closed sin contacto + .eq('contact_id').
    """

    def test_fail_closed_sin_contact_id_no_consulta(self):
        sb = _RecordingSupabase(rows=[{"id": "o1", "contact_id": "ct-b"}])
        ctx = ToolContext(tenant_id="t1", conversation_id="c1", contact_id=None, supabase=sb)
        res = asyncio.run(
            CreateClaimTool().execute(CreateClaimArgs(order_id="o1", reason="dañado"), ctx)
        )
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "CLAIM_CREATE_NO_CONTACT")
        self.assertFalse(sb.table_called, "fail-closed: no debe tocar la DB sin contact_id")

    def test_pedido_ajeno_no_matchea_y_no_inserta(self):
        """UUID de un pedido de otro cliente: el filtro por contact_id no matchea → NOT_FOUND,
        y el query prueba que el aislamiento vino del scope por cliente (no solo tenant)."""
        sb = _RecordingSupabase(rows=[])  # el filtro por contact_id no devuelve el pedido ajeno
        ctx = ToolContext(tenant_id="t1", conversation_id="c1", contact_id="ct-attacker", supabase=sb)
        res = asyncio.run(
            CreateClaimTool().execute(CreateClaimArgs(order_id="o-de-victima", reason="dañado"), ctx)
        )
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "CLAIM_ORDER_NOT_FOUND")
        self.assertIn(("contact_id", "ct-attacker"), sb.query.eqs)
        self.assertIn(("tenant_id", "t1"), sb.query.eqs)


if __name__ == "__main__":
    unittest.main()

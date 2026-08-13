"""OLA 0 — create_claim idempotente.

El LLM puede invocar create_claim otra vez si el cliente repite el reclamo en el
mismo flujo → antes se creaban reclamos DUPLICADOS + doble notificación al operador.
Fix: SELECT de reclamo ABIERTO por (tenant_id, order_id, customer_id) antes del
INSERT; si existe, se devuelve (idempotente) y NO se inserta.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.tools.base import ToolContext  # noqa: E402
from agentic.tools.claims import CreateClaimArgs, CreateClaimTool  # noqa: E402

_ORDER = {"id": "order-1", "tenant_id": "t1", "contact_id": "cust-1",
          "status": "delivered", "total_amount": 120000.0}
_OPEN_CLAIM = {"id": "claim-existing", "ticket_number": 7}


class _Query:
    def __init__(self, table, sb):
        self.table = table
        self.sb = sb

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def in_(self, *_):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if self.table == "orders":
            return type("R", (), {"data": [_ORDER]})()
        if self.table == "claims":
            # el SELECT de idempotencia devuelve un reclamo abierto existente
            return type("R", (), {"data": [_OPEN_CLAIM]})()
        return type("R", (), {"data": []})()

    def insert(self, _payload):
        if self.table == "claims":
            self.sb.claims_inserted = True  # marca — NO debería ocurrir si idempotente
        return self

    def update(self, *_):
        return self


class _Supabase:
    def __init__(self):
        self.claims_inserted = False

    def table(self, name):
        return _Query(name, self)


class CreateClaimIdempotencyTests(unittest.TestCase):

    def test_reclamo_abierto_existente_no_duplica(self):
        sb = _Supabase()
        ctx = ToolContext(tenant_id="t1", conversation_id="c1", contact_id="cust-1", supabase=sb)
        res = asyncio.run(CreateClaimTool().execute(
            CreateClaimArgs(order_id="order-1", reason="mi pedido llegó dañado"), ctx))
        self.assertTrue(res.success)
        # devuelve el reclamo EXISTENTE, no uno nuevo
        self.assertEqual(res.data["claim_id"], "claim-existing")
        self.assertEqual(res.data["ticket_number"], 7)
        # y NO insertó un duplicado
        self.assertFalse(sb.claims_inserted, "create_claim insertó un reclamo duplicado")


if __name__ == "__main__":
    unittest.main()

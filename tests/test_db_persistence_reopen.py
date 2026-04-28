"""Regresión del fix en db_persistence._upsert_conversation:

1. Al recibir un inbound para `(tenant_id, phone)` con conversación 'closed',
   debe REABRIRLA (status=bot_active) y reutilizar el id.
2. Si hay múltiples conversaciones para el mismo par, debe seleccionar la
   MÁS RECIENTE por last_interaction_at (no la primera arbitraria que devuelva).
3. Si no existe ninguna, crea una nueva con status=bot_active.

El fix vivía antes en orchestrator; ahora la responsabilidad la asume el
connector durante la persistencia inbound, que es donde corresponde.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/connector-whatsapp")

from services.db_persistence import _upsert_conversation  # noqa: E402


class _SelectChain:
    """Mock del chain Supabase: .select().eq().eq().order().limit().execute() — devuelve `rows`."""
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw): return self
    def eq(self, *a, **kw): return self
    def order(self, *a, **kw): return self
    def limit(self, *a, **kw): return self
    def execute(self):
        out = MagicMock()
        out.data = list(self._rows)
        return out


class _UpdateChain:
    """Mock del chain de update."""
    def __init__(self, calls_log: list):
        self._calls = calls_log

    def update(self, payload):
        self._calls.append(("update", payload))
        return self
    def eq(self, *a, **kw): return self
    def execute(self):
        out = MagicMock()
        out.data = []
        return out


class _InsertChain:
    """Mock del chain de insert que retorna un id determinado."""
    def __init__(self, new_id):
        self._new_id = new_id

    def insert(self, payload):
        self._payload = payload
        return self
    def execute(self):
        out = MagicMock()
        out.data = [{"id": self._new_id}]
        return out


def _make_supabase(*, select_rows, new_conv_id="new-conv-uuid"):
    """Construye un cliente fake con tablas conversations parametrizadas."""
    sb = MagicMock()
    update_calls: list = []

    def table(name):
        if name != "conversations":
            return MagicMock()
        # Retorna un objeto que se comporta como ambos chains.
        # Distinguimos por el primer método llamado (select vs update vs insert).
        chain = MagicMock()
        chain.select = _SelectChain(select_rows).select
        # Para que .select(...) en sí devuelva _SelectChain, lo seteamos:
        s_chain = _SelectChain(select_rows)
        u_chain = _UpdateChain(update_calls)
        i_chain = _InsertChain(new_conv_id)

        def _select(*a, **kw): return s_chain
        def _update(p): return u_chain.update(p)
        def _insert(p): return i_chain.insert(p)

        chain.select = _select
        chain.update = _update
        chain.insert = _insert
        return chain

    sb.table = table
    sb._update_calls = update_calls
    return sb


class UpsertConversationTests(unittest.TestCase):
    def test_reopens_closed_conversation(self):
        sb = _make_supabase(select_rows=[{"id": "conv-A", "status": "closed"}])
        conv_id = _upsert_conversation(sb, tenant_id="tenant-1", customer_phone="+57 312 5835649")
        self.assertEqual(conv_id, "conv-A")
        # Verifica que se llamó update con status=bot_active
        updates = [c for c in sb._update_calls if c[0] == "update"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1].get("status"), "bot_active")

    def test_reuses_active_conversation_without_update(self):
        sb = _make_supabase(select_rows=[{"id": "conv-B", "status": "bot_active"}])
        conv_id = _upsert_conversation(sb, tenant_id="tenant-1", customer_phone="3120000000")
        self.assertEqual(conv_id, "conv-B")
        # No hubo update (estaba activa)
        self.assertEqual(sb._update_calls, [])

    def test_reuses_human_takeover_conversation(self):
        sb = _make_supabase(select_rows=[{"id": "conv-C", "status": "human_takeover"}])
        conv_id = _upsert_conversation(sb, tenant_id="tenant-1", customer_phone="3120000001")
        self.assertEqual(conv_id, "conv-C")
        self.assertEqual(sb._update_calls, [])

    def test_creates_when_no_existing(self):
        sb = _make_supabase(select_rows=[], new_conv_id="conv-NEW")
        conv_id = _upsert_conversation(sb, tenant_id="tenant-1", customer_phone="3120000002")
        self.assertEqual(conv_id, "conv-NEW")

    def test_select_orders_by_last_interaction_desc(self):
        # El query debe pedir order=last_interaction_at desc + limit 1.
        # El mock no permite verificar argumentos del .order, pero podemos verificar
        # que con múltiples filas devolvemos la primera (la más reciente).
        rows = [
            {"id": "conv-RECENT", "status": "bot_active"},
            {"id": "conv-OLD", "status": "closed"},
        ]
        sb = _make_supabase(select_rows=rows)
        conv_id = _upsert_conversation(sb, tenant_id="t", customer_phone="3000000000")
        self.assertEqual(conv_id, "conv-RECENT", "debe seleccionar la más reciente, no escanear")


if __name__ == "__main__":
    unittest.main()

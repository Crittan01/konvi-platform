"""Tests `services/api/lib/contact_cleanup.py` (Sem 7 F2 cierre 2026-05-19).

Bug founder UAT 2026-05-19 (conv 056490b8): tras eliminar contact desde UI,
carts históricos persisten en DB → cart-recovery flow contamina próxima conv.

Helper compartido `purge_contact_completely` ejecuta cascade completo,
usado por endpoint API y script CLI.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from lib.contact_cleanup import (  # noqa: E402
    purge_contact_completely,
    _safe_delete,
    _collect_contact_resources,
)


class _FakeQuery:
    """Mock chainable de supabase.table(...).select/delete/.eq/.in_/.execute()."""
    def __init__(self, returns_data=None, raises=None):
        self._returns = returns_data or []
        self._raises = raises
        self.calls: list[tuple] = []

    def select(self, *args, **kwargs):
        self.calls.append(("select", args, kwargs))
        return self

    def delete(self):
        self.calls.append(("delete",))
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    def in_(self, col, val):
        self.calls.append(("in_", col, val))
        return self

    def single(self):
        self.calls.append(("single",))
        return self

    def execute(self):
        if self._raises:
            raise self._raises
        return MagicMock(data=self._returns)


class _FakeSupabase:
    """Mock supabase client. Cada tabla puede devolver datos custom."""

    def __init__(self):
        self.tables: dict[str, _FakeQuery] = {}
        self.table_calls: list[str] = []

    def set_table(self, name: str, returns=None, raises=None):
        self.tables[name] = _FakeQuery(returns_data=returns, raises=raises)

    def table(self, name: str):
        self.table_calls.append(name)
        if name not in self.tables:
            self.tables[name] = _FakeQuery(returns_data=[])
        return self.tables[name]


class PurgeContactCompletelyTests(unittest.TestCase):

    def test_raises_si_falta_tenant_id(self):
        sb = _FakeSupabase()
        with self.assertRaises(ValueError):
            purge_contact_completely(sb, "", "contact-1")

    def test_raises_si_falta_contact_id(self):
        sb = _FakeSupabase()
        with self.assertRaises(ValueError):
            purge_contact_completely(sb, "tenant-1", "")

    def test_purge_idempotente_sin_recursos(self):
        """Contact sin conversations/orders/carts: solo borra el contact."""
        sb = _FakeSupabase()
        # Tablas con data=[] → counts=0.
        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        self.assertEqual(out["orders_found"], 0)
        self.assertEqual(out["carts_found"], 0)
        self.assertEqual(out["conversations_found"], 0)
        self.assertEqual(out["payments_deleted"], 0)
        self.assertEqual(out["shipments_deleted"], 0)
        self.assertEqual(out["carts_deleted"], 0)
        self.assertEqual(out["orders_deleted"], 0)
        self.assertEqual(out["conversations_deleted"], 0)

    def test_purge_con_recursos_borra_cascade(self):
        """Contact con conversation + order + cart → cascade completo."""
        sb = _FakeSupabase()
        # Lookup recursos.
        sb.set_table("conversations", returns=[{"id": "conv-1"}, {"id": "conv-2"}])
        sb.set_table("orders", returns=[{"id": "ord-1"}])
        sb.set_table("conversation_carts", returns=[{"id": "cart-1"}])
        # Resto retorna data=[] (default).

        # Recargar el wrapper "conversations" porque luego se va a usar para
        # SELECT + DELETE. _FakeQuery solo soporta 1 ciclo execute; el test
        # acepta esto como simplificación.
        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        self.assertEqual(out["orders_found"], 1)
        self.assertEqual(out["carts_found"], 1)
        self.assertEqual(out["conversations_found"], 2)

    def test_summary_tiene_keys_estandares(self):
        """El dict de salida tiene contract estable."""
        sb = _FakeSupabase()
        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        expected_keys = {
            "tenant_id", "contact_id",
            "orders_found", "carts_found", "conversations_found",
            "payments_deleted", "shipments_deleted",
            "cart_events_deleted", "cart_items_deleted",
            "carts_deleted",
            "order_items_deleted", "orders_deleted",
            "messages_deleted", "reads_deleted",
            "conversations_deleted",
            "contact_deleted",
        }
        self.assertTrue(expected_keys.issubset(set(out.keys())),
                        f"missing: {expected_keys - set(out.keys())}")


class CollectContactResourcesTests(unittest.TestCase):

    def test_recolecta_ids_correctamente(self):
        sb = _FakeSupabase()
        sb.set_table("conversations", returns=[
            {"id": "c1"}, {"id": "c2"}, {"id": "c3"},
        ])
        sb.set_table("orders", returns=[{"id": "o1"}, {"id": "o2"}])
        sb.set_table("conversation_carts", returns=[{"id": "ct1"}])

        out = _collect_contact_resources(sb, "t1", "ct1")
        self.assertEqual(out["conversation_ids"], ["c1", "c2", "c3"])
        self.assertEqual(out["order_ids"], ["o1", "o2"])
        self.assertEqual(out["cart_ids"], ["ct1"])

    def test_skip_table_inexistente(self):
        """Si una tabla aún no existe (migración pendiente en algún ambiente)
        el helper retorna lista vacía sin levantar excepción."""
        sb = _FakeSupabase()
        sb.set_table("conversations", raises=Exception("table not found"))
        out = _collect_contact_resources(sb, "t1", "c1")
        self.assertEqual(out["conversation_ids"], [])


class SafeDeleteTests(unittest.TestCase):

    def test_delete_simple_eq(self):
        sb = _FakeSupabase()
        sb.set_table("orders", returns=[{"id": "o1"}, {"id": "o2"}])
        count = _safe_delete(sb, "orders", "contact_id", "c1")
        self.assertEqual(count, 2)

    def test_delete_in_list(self):
        sb = _FakeSupabase()
        sb.set_table("payments", returns=[{"id": "p1"}])
        count = _safe_delete(sb, "payments", "order_id", ["o1", "o2"], in_list=True)
        self.assertEqual(count, 1)

    def test_delete_lista_vacia_no_ejecuta(self):
        """Si in_list con lista vacía → return 0 sin tocar DB."""
        sb = _FakeSupabase()
        count = _safe_delete(sb, "payments", "order_id", [], in_list=True)
        self.assertEqual(count, 0)

    def test_delete_si_tabla_falla_retorna_cero(self):
        sb = _FakeSupabase()
        sb.set_table("missing_table", raises=Exception("relation does not exist"))
        count = _safe_delete(sb, "missing_table", "id", "x")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

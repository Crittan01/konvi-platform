"""Tests AST audit tenant_filter — Fase A6.1 finiquito NIVEL 2.

Validates que el lint script detecta correctamente:
  • Queries `.table(X).select(...)` sin `.eq("tenant_id", ...)` → gap
  • Queries `.table(X).select(...).eq("tenant_id", ...)` → OK
  • Queries `.table(X).insert(dict_with_tenant_id)` → OK
  • Queries `.table(X).update(dict_no_tenant_id)` → gap kind=missing_payload_key
  • Exemption marker `# tenant_filter:exempt:<reason>` → skip
  • Tables no-críticas (e.g. 'public_categories') → no analizadas
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_tenant_filter import (  # noqa: E402
    FileVisitor,
    TENANT_SCOPED_TABLES_EXTENDED,
)


def _analyze(source: str, file_path: str = "test.py") -> list:
    return FileVisitor.analyze(file_path, source)


class DetectMissingEqTests(unittest.TestCase):
    def test_simple_select_without_tenant_id_is_gap(self):
        src = '''
def fn():
    supabase.table("contacts").select("*").execute()
'''
        gaps = _analyze(src)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].table, "contacts")
        self.assertEqual(gaps[0].kind, "missing_eq")

    def test_select_with_tenant_id_eq_is_ok(self):
        src = '''
def fn():
    supabase.table("contacts").select("*").eq("tenant_id", tenant_id).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])

    def test_select_with_tenant_id_in_middle_of_chain_is_ok(self):
        src = '''
def fn():
    (supabase.table("orders")
        .select("id, amount")
        .eq("tenant_id", tid)
        .eq("status", "paid")
        .order("created_at", desc=True)
        .execute())
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])

    def test_select_with_other_eq_but_no_tenant_id_is_gap(self):
        src = '''
def fn():
    supabase.table("orders").select("*").eq("id", order_id).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].table, "orders")
        self.assertEqual(gaps[0].kind, "missing_eq")


class DetectWritePayloadTests(unittest.TestCase):
    def test_insert_with_tenant_id_in_payload_is_ok(self):
        src = '''
def fn():
    supabase.table("payments").insert({"tenant_id": tid, "amount": 100}).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])

    def test_insert_without_tenant_id_in_payload_is_gap(self):
        src = '''
def fn():
    supabase.table("payments").insert({"amount": 100, "status": "pending"}).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].kind, "missing_payload_key_insert")

    def test_update_with_eq_tenant_id_is_ok(self):
        src = '''
def fn():
    supabase.table("orders").update({"status": "shipped"}).eq("tenant_id", tid).eq("id", oid).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])

    def test_update_without_tenant_id_in_payload_or_eq_is_gap(self):
        src = '''
def fn():
    supabase.table("orders").update({"status": "shipped"}).eq("id", oid).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].kind, "missing_payload_key_update")

    def test_upsert_with_tenant_id_is_ok(self):
        src = '''
def fn():
    supabase.table("tenant_integrations").upsert(
        {"tenant_id": tid, "provider": "whatsapp"},
        on_conflict="tenant_id,provider",
    ).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])


class ExemptionMarkerTests(unittest.TestCase):
    def test_exempt_marker_same_line_skips_gap(self):
        src = '''
def fn():
    supabase.table("orders").select("*").execute()  # tenant_filter:exempt: cross-tenant admin
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])

    def test_exempt_marker_previous_line_skips_gap(self):
        src = '''
def fn():
    # tenant_filter:exempt: webhook tenant resolution
    supabase.table("orders").select("*").eq("payment_link_id", link_id).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])


class ScopeFilterTests(unittest.TestCase):
    def test_non_critical_table_not_analyzed(self):
        """Tablas NO en TENANT_SCOPED_TABLES_EXTENDED se ignoran."""
        # Asumir que 'public_categories' NO está en la lista
        self.assertNotIn("public_categories", TENANT_SCOPED_TABLES_EXTENDED)
        src = '''
def fn():
    supabase.table("public_categories").select("*").execute()
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])

    def test_all_critical_tables_in_set(self):
        """Sanity check — set tiene tablas críticas conocidas."""
        critical_minimum = {
            "contacts", "conversations", "messages", "orders",
            "payments", "conversation_carts", "consent_audit_log",
        }
        self.assertTrue(critical_minimum.issubset(TENANT_SCOPED_TABLES_EXTENDED))


class MultipleGapsInFileTests(unittest.TestCase):
    def test_multiple_gaps_all_detected(self):
        src = '''
def fn1():
    supabase.table("orders").select("*").execute()

def fn2():
    supabase.table("messages").update({"status": "read"}).eq("id", mid).execute()

def fn3():
    supabase.table("payments").select("*").eq("tenant_id", tid).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(len(gaps), 2)
        kinds = {g.kind for g in gaps}
        self.assertIn("missing_eq", kinds)
        self.assertIn("missing_payload_key_update", kinds)


class FalsePositiveProtectionTests(unittest.TestCase):
    def test_rpc_call_not_analyzed(self):
        """`.rpc()` calls fuera de scope (RPCs gobiernan su auth via SQL)."""
        src = '''
def fn():
    supabase.rpc("pgsec_read_secret", {"p_id": secret_id}).execute()
'''
        gaps = _analyze(src)
        self.assertEqual(gaps, [])

    def test_variable_table_name_skipped(self):
        """`.table(variable)` no analizable estáticamente."""
        src = '''
def fn():
    table_name = "orders"
    supabase.table(table_name).select("*").execute()
'''
        gaps = _analyze(src)
        # No analizable porque table_name no es Constant
        self.assertEqual(gaps, [])


if __name__ == "__main__":
    unittest.main()

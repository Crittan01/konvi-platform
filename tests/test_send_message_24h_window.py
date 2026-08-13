"""Tests del helper _check_24h_window_or_raise en routers/conversations.py.

Verifica que la política de ventana 24h Meta se aplica antes del envío:
- last_inbound_at < 24h → permite (no levanta).
- last_inbound_at > 24h → 422 con código WINDOW_EXPIRED.
- sin inbound previo → 422 con código WINDOW_NO_INBOUND.
- borde 23h59m → permite.
"""
import os
import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402
from routers import conversations  # noqa: E402


def _chain_with_data(data):
    q = MagicMock()
    q.select.return_value = q
    q.eq.return_value = q
    q.order.return_value = q
    q.limit.return_value = q
    q.execute.return_value = types.SimpleNamespace(data=data)
    return q


def _supabase_with_inbound_at(iso_ts: str | None):
    sb = MagicMock()
    rows = [{"created_at": iso_ts}] if iso_ts else []
    sb.table.return_value = _chain_with_data(rows)
    return sb


class WindowCheckTests(unittest.TestCase):
    def test_within_window_allows(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        sb = _supabase_with_inbound_at(recent)
        # No debe levantar
        self.assertIsNone(conversations._check_24h_window_or_raise(sb, "tenant-1", "conv-1"))

    def test_just_before_24h_allows(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=23, minutes=59)).isoformat()
        sb = _supabase_with_inbound_at(recent)
        self.assertIsNone(conversations._check_24h_window_or_raise(sb, "tenant-1", "conv-1"))

    def test_outside_window_raises_window_expired(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        sb = _supabase_with_inbound_at(old)
        with self.assertRaises(HTTPException) as ctx:
            conversations._check_24h_window_or_raise(sb, "tenant-1", "conv-1")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail.get("code"), "WINDOW_EXPIRED")
        self.assertGreaterEqual(ctx.exception.detail.get("hours_since_last_inbound", 0), 24)

    def test_no_inbound_raises_window_no_inbound(self):
        sb = _supabase_with_inbound_at(None)
        with self.assertRaises(HTTPException) as ctx:
            conversations._check_24h_window_or_raise(sb, "tenant-1", "conv-1")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail.get("code"), "WINDOW_NO_INBOUND")

    def test_iso_with_z_suffix_parses(self):
        # Supabase suele devolver con sufijo Z. Aseguramos parseo correcto.
        recent_z = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        sb = _supabase_with_inbound_at(recent_z)
        self.assertIsNone(conversations._check_24h_window_or_raise(sb, "tenant-1", "conv-1"))

    def test_query_filters_by_tenant_and_conversation(self):
        # Verifica multi-tenant: la query filtra por tenant_id Y conversation_id.
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        sb = MagicMock()
        chain = _chain_with_data([{"created_at": recent}])
        sb.table.return_value = chain
        conversations._check_24h_window_or_raise(sb, "tenant-A", "conv-X")
        # Verifica que se aplicaron 3 filtros eq: tenant_id, conversation_id, direction='inbound'
        eq_calls = chain.eq.call_args_list
        eq_kv = {c.args[0]: c.args[1] for c in eq_calls}
        self.assertEqual(eq_kv.get("tenant_id"), "tenant-A")
        self.assertEqual(eq_kv.get("conversation_id"), "conv-X")
        self.assertEqual(eq_kv.get("direction"), "inbound")


if __name__ == "__main__":
    unittest.main()

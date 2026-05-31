"""
R-04: Auditoría de aislamiento multi-tenant.

Verifica que:
1. El helper scoped_table aplica tenant_id obligatoriamente.
2. Las rutas críticas de la API no tienen queries a tablas sensibles
   que falten el filtro .eq("tenant_id", ...).

Este test es un guard de regresión: falla cuando se agrega código nuevo
que bypassea el aislamiento.
"""
import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from dependencies.tenant_scope import scoped_table, TENANT_SCOPED_TABLES


class ScopedTableHelperTests(unittest.TestCase):

    def test_raises_on_empty_tenant_id(self):
        """scoped_table debe rechazar tenant_id vacío."""
        supabase = MagicMock()
        with self.assertRaises(ValueError):
            scoped_table(supabase, "orders", "")

    def test_raises_on_none_tenant_id(self):
        """scoped_table debe rechazar tenant_id None."""
        supabase = MagicMock()
        with self.assertRaises(ValueError):
            scoped_table(supabase, "orders", None)

    def test_applies_tenant_id_filter_on_critical_table(self):
        """Para tabla crítica, aplica .eq('tenant_id', ...) automáticamente."""
        supabase = MagicMock()
        mock_table = MagicMock()
        supabase.table.return_value = mock_table
        mock_table.eq.return_value = mock_table

        scoped_table(supabase, "orders", "tenant-123")

        supabase.table.assert_called_with("orders")
        mock_table.eq.assert_called_with("tenant_id", "tenant-123")

    def test_all_critical_tables_defined(self):
        """Las tablas críticas del negocio están en TENANT_SCOPED_TABLES."""
        required = {"orders", "contacts", "conversations", "messages", "payments", "products"}
        missing = required - TENANT_SCOPED_TABLES
        self.assertEqual(missing, set(), f"Tablas faltantes en TENANT_SCOPED_TABLES: {missing}")

    def test_select_is_proxied(self):
        """La llamada .select() se delega al query subyacente."""
        supabase = MagicMock()
        mock_table = MagicMock()
        supabase.table.return_value = mock_table
        mock_table.eq.return_value = mock_table

        q = scoped_table(supabase, "orders", "t-1")
        q.select("id, status")

        mock_table.select.assert_called_with("id, status")

    def test_update_is_proxied(self):
        """La llamada .update() se delega al query subyacente."""
        supabase = MagicMock()
        mock_table = MagicMock()
        supabase.table.return_value = mock_table
        mock_table.eq.return_value = mock_table

        q = scoped_table(supabase, "orders", "t-1")
        q.update({"status": "confirmed"})

        mock_table.update.assert_called_with({"status": "confirmed"})


class TenantIsolationAuditTests(unittest.TestCase):
    """
    Análisis estático: busca patrones de queries sin tenant_id en
    los routers críticos del API.

    El patrón peligroso es:
        supabase.table("orders").select(...)  # sin .eq("tenant_id", ...)
        supabase.table("contacts").update(...)  # sin filtro de tenant

    El patrón seguro es:
        .eq("tenant_id", tenant_id)  # antes o después de la query
    """

    ROUTERS_PATH = Path("/home/ansible/workspaces/konvi-platform/services/api/routers")
    CRITICAL_TABLES = {"orders", "order_items", "contacts", "conversations", "messages", "payments"}

    def _get_router_files(self):
        return list(self.ROUTERS_PATH.glob("*.py"))

    def test_router_files_exist(self):
        """Al menos los routers críticos deben existir."""
        files = {f.name for f in self._get_router_files()}
        for expected in {"orders.py", "contacts.py", "conversations.py"}:
            self.assertIn(expected, files, f"Router crítico no encontrado: {expected}")

    def test_critical_routers_have_tenant_filter(self):
        """
        Heurística: en routers con queries a tablas críticas,
        el string 'tenant_id' debe aparecer en el mismo archivo.
        Si no está, hay riesgo de cross-tenant leak.
        """
        missing_tenant_filter = []
        for router_file in self._get_router_files():
            content = router_file.read_text(encoding="utf-8")
            for table in self.CRITICAL_TABLES:
                if f'table("{table}")' in content or f"table('{table}')" in content:
                    if "tenant_id" not in content:
                        missing_tenant_filter.append(
                            f"{router_file.name}: queries a '{table}' sin 'tenant_id'"
                        )

        self.assertEqual(
            missing_tenant_filter, [],
            f"Routers con posible leak cross-tenant:\n" + "\n".join(missing_tenant_filter),
        )

    def test_wompi_webhook_uses_tenant_from_order(self):
        """wompi_webhook.py resuelve tenant_id desde la orden, no desde JWT."""
        wompi_file = self.ROUTERS_PATH / "wompi_webhook.py"
        content = wompi_file.read_text(encoding="utf-8")
        # Verifica que obtiene tenant_id del order dict (no hardcodeado)
        self.assertIn('order["tenant_id"]', content,
                      "wompi_webhook debe extraer tenant_id desde la orden DB")


if __name__ == "__main__":
    unittest.main()

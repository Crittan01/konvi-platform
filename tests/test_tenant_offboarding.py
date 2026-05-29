"""Tests `services/api/lib/tenant_offboarding.py` (rev. 109 J.2.4.4).

Cubre invariantes críticos del módulo offboarding:
  1. export_tenant_data 404 si tenant no existe.
  2. export_tenant_data tolera tablas faltantes (loguea warning, sigue).
  3. export_tenant_data incluye los 4 grupos de tablas + summary.
  4. export_tenant_data marca tabla truncated si filas >= MAX_ROWS.
  5. request_tenant_deletion invoca RPC fn_request_tenant_deletion.
  6. request_tenant_deletion rechaza razón vacía.
  7. request_tenant_deletion traduce SQLSTATE 40000 → TenantOffboardingError.
  8. cancel_tenant_deletion retorna True si había offboarding, False si no.
  9. get_offboarding_status retorna state enum + is_recoverable.
  10. hard_delete_tenant levanta NotImplementedError (Fase 2 stub).

NO requiere DB real — fake Supabase client con stub de tablas + RPCs.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "tenant_offboarding.py"


def _load_lib():
    spec = importlib.util.spec_from_file_location("_tenant_offboarding", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_tenant_offboarding"] = mod
    spec.loader.exec_module(mod)
    return mod


toff = _load_lib()


# ─── Fake Supabase con suficiente fidelidad para los tests ───────────────────


class _FakeTableQuery:
    """Mock chained table().select(...).eq(...).limit(...).execute()."""

    def __init__(self, rows: list[dict[str, Any]], raise_on_execute: bool = False):
        self._rows = rows
        self._raise = raise_on_execute
        self._limit: int | None = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def execute(self):
        if self._raise:
            raise Exception("Simulated DB error")
        rows = self._rows
        if self._limit is not None:
            rows = rows[: self._limit]
        return SimpleNamespace(data=rows)


class _FakeRpcCall:
    def __init__(self, fn_name: str, args, registry: list[dict], result: Any,
                 raise_with: str | None = None):
        self._fn_name = fn_name
        self._args = args
        self._registry = registry
        self._result = result
        self._raise_with = raise_with

    def execute(self):
        self._registry.append({"fn": self._fn_name, "args": self._args})
        if self._raise_with is not None:
            raise Exception(self._raise_with)
        return SimpleNamespace(data=self._result)


class _FakeSupabase:
    def __init__(self, *, tables: dict[str, list[dict[str, Any]]] | None = None,
                 table_error: set[str] | None = None,
                 rpc_results: dict[str, Any] | None = None,
                 rpc_errors: dict[str, str] | None = None):
        self._tables = tables or {}
        self._table_error = table_error or set()
        self._rpc_results = rpc_results or {}
        self._rpc_errors = rpc_errors or {}
        self.rpc_calls: list[dict] = []

    def table(self, name: str):
        return _FakeTableQuery(
            rows=self._tables.get(name, []),
            raise_on_execute=(name in self._table_error),
        )

    def rpc(self, fn_name: str, args=None):
        return _FakeRpcCall(
            fn_name, args, self.rpc_calls,
            result=self._rpc_results.get(fn_name),
            raise_with=self._rpc_errors.get(fn_name),
        )


# ─── Tests ───────────────────────────────────────────────────────────────────


class ExportTenantDataTests(unittest.TestCase):
    def test_404_si_tenant_no_existe(self):
        sb = _FakeSupabase(tables={"tenants": []})
        with self.assertRaises(toff.TenantOffboardingError) as ctx:
            toff.export_tenant_data(sb, "missing-uuid")
        self.assertIn("no encontrado", str(ctx.exception))

    def test_503_si_tabla_tenants_falla(self):
        sb = _FakeSupabase(table_error={"tenants"})
        with self.assertRaises(toff.TenantOffboardingError) as ctx:
            toff.export_tenant_data(sb, "any-uuid")
        self.assertIn("DB no disponible", str(ctx.exception))

    def test_export_tolera_tablas_faltantes(self):
        """Una tabla con error NO debe romper el export entero."""
        sb = _FakeSupabase(
            tables={
                "tenants": [{"id": "T1", "name": "Test", "slug": "test"}],
                "contacts": [{"id": "C1", "tenant_id": "T1"}],
            },
            # Simulamos que 5 tablas fallan (migrations no aplicadas locales).
            table_error={"ai_agents", "rma_requests", "stock_movements"},
        )
        payload = toff.export_tenant_data(sb, "T1", requester_email="owner@test.com")
        self.assertEqual(payload["tenant"]["id"], "T1")
        self.assertEqual(payload["requested_by"], "owner@test.com")
        # contacts incluida.
        self.assertEqual(len(payload["data"]["customers_and_pii"]["contacts"]), 1)
        # Las que fallaron salen vacías, no rompen.
        self.assertEqual(payload["data"]["core_config"]["ai_agents"], [])

    def test_export_incluye_4_grupos(self):
        sb = _FakeSupabase(
            tables={"tenants": [{"id": "T1", "name": "Test"}]},
        )
        payload = toff.export_tenant_data(sb, "T1")
        self.assertIn("core_config", payload["data"])
        self.assertIn("operation", payload["data"])
        self.assertIn("customers_and_pii", payload["data"])
        self.assertIn("audit_trail", payload["data"])
        # Cabecera completa.
        self.assertEqual(payload["format_version"], "1.0")
        self.assertIn("Ley 1581", payload["legal_basis"]["law"])

    def test_truncated_si_tabla_alcanza_max(self):
        """Si una tabla devuelve >= MAX_ROWS, debe marcarse como truncada."""
        big_table = [{"id": str(i), "tenant_id": "T1"} for i in range(toff.MAX_ROWS_PER_TABLE)]
        sb = _FakeSupabase(
            tables={
                "tenants": [{"id": "T1"}],
                "messages": big_table,
            }
        )
        payload = toff.export_tenant_data(sb, "T1")
        self.assertIn("messages", payload["summary"]["truncated_tables"])
        self.assertIsNotNone(payload["summary"]["note"])


class RequestTenantDeletionTests(unittest.TestCase):
    def test_razon_vacia_rechazada(self):
        sb = _FakeSupabase()
        with self.assertRaises(toff.TenantOffboardingError) as ctx:
            toff.request_tenant_deletion(
                sb, "T1", "user-uuid", "owner@test.com", "1.2.3.4", reason="   ",
            )
        self.assertIn("obligatoria", str(ctx.exception))

    def test_happy_path_invoca_rpc(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        sb = _FakeSupabase(rpc_results={"fn_request_tenant_deletion": future})
        result = toff.request_tenant_deletion(
            sb, "T1", "user-uuid", "owner@test.com", "1.2.3.4",
            reason="Cierre por inactividad",
        )
        self.assertIsInstance(result, datetime)
        # Verificar que la RPC fue invocada con los args correctos.
        rpc_call = sb.rpc_calls[0]
        self.assertEqual(rpc_call["fn"], "fn_request_tenant_deletion")
        self.assertEqual(rpc_call["args"]["p_tenant_id"], "T1")
        self.assertEqual(rpc_call["args"]["p_reason"], "Cierre por inactividad")

    def test_offboarding_ya_en_curso_levanta(self):
        sb = _FakeSupabase(
            rpc_errors={
                "fn_request_tenant_deletion":
                    "ERROR: Tenant X ya tiene offboarding en curso desde 2026-05-29",
            }
        )
        with self.assertRaises(toff.TenantOffboardingError) as ctx:
            toff.request_tenant_deletion(
                sb, "T1", "uid", "e@test.com", None, reason="x" * 20,
            )
        self.assertIn("ya tiene una solicitud", str(ctx.exception))


class CancelTenantDeletionTests(unittest.TestCase):
    def test_cancel_exitoso(self):
        sb = _FakeSupabase(rpc_results={"fn_cancel_tenant_deletion": True})
        result = toff.cancel_tenant_deletion(
            sb, "T1", "uid", "e@test.com", "1.2.3.4",
        )
        self.assertTrue(result)
        self.assertEqual(sb.rpc_calls[0]["fn"], "fn_cancel_tenant_deletion")

    def test_no_offboarding_pendiente_retorna_false(self):
        sb = _FakeSupabase(rpc_results={"fn_cancel_tenant_deletion": False})
        result = toff.cancel_tenant_deletion(
            sb, "T1", "uid", "e@test.com", None,
        )
        self.assertFalse(result)

    def test_ya_hard_deleted_levanta(self):
        sb = _FakeSupabase(
            rpc_errors={
                "fn_cancel_tenant_deletion":
                    "ERROR: Tenant T1 ya fue hard-deleted, no es cancelable",
            }
        )
        with self.assertRaises(toff.TenantOffboardingError) as ctx:
            toff.cancel_tenant_deletion(sb, "T1", "uid", "e@test.com", None)
        self.assertIn("eliminado permanentemente", str(ctx.exception))


class GetOffboardingStatusTests(unittest.TestCase):
    def test_state_active_si_no_hay_deletion(self):
        sb = _FakeSupabase(
            tables={
                "tenants": [{
                    "id": "T1",
                    "deletion_requested_at": None,
                    "deletion_scheduled_for": None,
                    "deleted_at": None,
                }]
            }
        )
        result = toff.get_offboarding_status(sb, "T1")
        self.assertEqual(result["state"], "active")
        self.assertFalse(result["is_recoverable"])

    def test_state_soft_deleted_si_requested(self):
        sb = _FakeSupabase(
            tables={
                "tenants": [{
                    "id": "T1",
                    "deletion_requested_at": "2026-05-29T00:00:00+00:00",
                    "deletion_scheduled_for": "2026-06-28T00:00:00+00:00",
                    "deletion_reason": "Cierre operativo",
                    "deleted_at": None,
                }]
            }
        )
        result = toff.get_offboarding_status(sb, "T1")
        self.assertEqual(result["state"], "soft_deleted_grace_period")
        self.assertTrue(result["is_recoverable"])

    def test_state_hard_deleted(self):
        sb = _FakeSupabase(
            tables={
                "tenants": [{
                    "id": "T1",
                    "deletion_requested_at": "2026-05-29T00:00:00+00:00",
                    "deletion_scheduled_for": "2026-06-28T00:00:00+00:00",
                    "deleted_at": "2026-06-28T01:00:00+00:00",
                }]
            }
        )
        result = toff.get_offboarding_status(sb, "T1")
        self.assertEqual(result["state"], "hard_deleted")
        self.assertFalse(result["is_recoverable"])


class HardDeleteTests(unittest.TestCase):
    """Fase 2 — implementación real del hard-delete."""

    def _supabase_with_storage(self, rpc_result=True, archive_fail=False):
        """FakeSupabase con .storage.from_().upload() mockeado."""
        sb = _FakeSupabase(
            tables={
                "audit_log": [{"id": "a1", "tenant_id": "T1"}],
                "consent_audit_log": [{"id": "c1", "tenant_id": "T1"}],
            },
            rpc_results={"fn_hard_delete_tenant": rpc_result},
        )

        class _StorageBucket:
            def __init__(self, fail):
                self._fail = fail
                self.uploads = []

            def upload(self, path, content, *args, **kwargs):
                if self._fail:
                    raise Exception("Storage timeout")
                self.uploads.append({"path": path, "size": len(content)})
                return SimpleNamespace(error=None)

        class _Storage:
            def __init__(self, fail):
                self._bucket = _StorageBucket(fail)

            def from_(self, name):
                assert name == "offboarding-archive"
                return self._bucket

        sb.storage = _Storage(archive_fail)
        return sb

    def test_hard_delete_happy_path(self):
        sb = self._supabase_with_storage(rpc_result=True)
        result = toff.hard_delete_tenant(sb, "T1")
        self.assertEqual(result["tenant_id"], "T1")
        self.assertTrue(result["rpc_result"])
        self.assertIn("archive_path", result)
        # Verificar RPC invocada con archive_path como param.
        rpc_call = next(c for c in sb.rpc_calls if c["fn"] == "fn_hard_delete_tenant")
        self.assertEqual(rpc_call["args"]["p_tenant_id"], "T1")
        self.assertIn("p_archive_path", rpc_call["args"])

    def test_hard_delete_idempotente_si_ya_deleted(self):
        """RPC retorna False si tenant ya fue hard-deleted antes (race condition cron)."""
        sb = self._supabase_with_storage(rpc_result=False)
        result = toff.hard_delete_tenant(sb, "T1")
        self.assertFalse(result["rpc_result"])

    def test_hard_delete_levanta_si_no_elegible(self):
        class _Storage:
            def from_(self, name):
                class _B:
                    uploads = []
                    def upload(self, *a, **kw):
                        return None
                return _B()
        sb = _FakeSupabase(
            rpc_errors={
                "fn_hard_delete_tenant":
                    "ERROR: Tenant T1 todavía en grace period (scheduled_for=...)",
            },
            tables={"audit_log": []},
        )
        sb.storage = _Storage()

        with self.assertRaises(toff.TenantOffboardingError) as ctx:
            toff.hard_delete_tenant(sb, "T1")
        self.assertIn("grace period", str(ctx.exception).lower())

    def test_hard_delete_tolera_storage_failure(self):
        """Si upload a archive falla, NO debe bloquear el delete (degraded mode).
        Compliance Art. 16 derecho eliminación > Art. 22 custodia (preferimos
        eliminar con audit log degradado a no eliminar)."""
        sb = self._supabase_with_storage(rpc_result=True, archive_fail=True)
        # No debe levantar — solo loguea warning.
        result = toff.hard_delete_tenant(sb, "T1")
        self.assertEqual(result["tenant_id"], "T1")


class ListPendingHardDeleteTests(unittest.TestCase):
    def test_retorna_lista_vacia_si_rpc_no_existe(self):
        """Migration Fase 2 no aplicada → silenciosamente retorna []."""
        sb = _FakeSupabase(
            rpc_errors={
                "fn_list_tenants_pending_hard_delete":
                    "function fn_list_tenants_pending_hard_delete does not exist",
            },
        )
        result = toff.list_tenants_pending_hard_delete(sb)
        self.assertEqual(result, [])

    def test_retorna_filas_si_rpc_OK(self):
        future = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        sb = _FakeSupabase(
            rpc_results={
                "fn_list_tenants_pending_hard_delete": [
                    {
                        "tenant_id": "T1",
                        "deletion_scheduled_for": future,
                        "grace_period_days": 30,
                    },
                ],
            },
        )
        result = toff.list_tenants_pending_hard_delete(sb)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tenant_id"], "T1")


if __name__ == "__main__":
    unittest.main()

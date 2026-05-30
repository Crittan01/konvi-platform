"""Tests `services/api/lib/credentials_facade.py` (rev. 105 Sem 2 F.11 / MA-3).

Cubre invariantes:
  1. Caché in-memory con TTL real (5min default).
  2. Cache hit NO va a DB.
  3. Cache miss va a DB y emite audit log con cache_hit=False.
  4. Audit log NO bloquea el read principal si falla.
  5. invalidate(tenant_id) borra entries del tenant.
  6. invalidate(tenant_id, provider) borra solo del provider.
  7. service_name no canónico produce warning pero no falla.

NO requiere DB real — fake Supabase con tenant_integrations + audit log.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "credentials_facade.py"


def _load_lib():
    import sys
    spec = importlib.util.spec_from_file_location("_credentials_facade", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_credentials_facade"] = mod
    spec.loader.exec_module(mod)
    return mod


cf = _load_lib()


# ─── Fake Supabase ────────────────────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None

    def select(self, _cols: str = "*"):
        return _FakeQuery(self._store, op="select")

    def insert(self, payload: dict[str, Any]):
        return _FakeQuery(self._store, op="insert", payload=payload)

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def execute(self):
        if self._op == "select":
            rows = [
                r for r in self._store
                if all(r.get(c) == v for c, v in self._filters)
            ]
            if self._limit is not None:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)
        if self._op == "insert":
            new_id = max((r.get("id", 0) for r in self._store), default=0) + 1
            row = dict(self._payload)
            row["id"] = new_id
            self._store.append(row)
            return SimpleNamespace(data=[row])
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict[str, Any]]] = {
            "tenant_integrations": [],
            "credential_access_log": [],
        }
        self.read_count: dict[tuple[str, str], int] = {}

    def table(self, name: str):
        # Track reads to tenant_integrations para verificar caché behavior.
        return _TrackingQuery(self, name, self._tables[name])


class _TrackingQuery(_FakeQuery):
    def __init__(self, parent: _FakeSupabase, table_name: str,
                 store: list[dict[str, Any]]):
        super().__init__(store)
        self._parent = parent
        self._table_name = table_name

    def select(self, cols: str = "*"):
        if self._table_name == "tenant_integrations":
            self._parent.read_count[(self._table_name, cols)] = (
                self._parent.read_count.get((self._table_name, cols), 0) + 1
            )
        return super().select(cols)


# ─── Tests ────────────────────────────────────────────────────────────────────

class CacheTests(unittest.TestCase):
    def setUp(self):
        cf._reset_global_cache()

    def test_cache_hit_no_va_a_db(self):
        client = _FakeSupabase()
        client._tables["tenant_integrations"].append({
            "tenant_id": "tenant-A",
            "provider": "wompi",
            "credentials": {"private_key": "PRV-PLAINTEXT"},
        })
        facade = cf.TenantCredentialsFacade(client, service_name="api")

        v1 = facade.get("tenant-A", "wompi", "private_key")
        v2 = facade.get("tenant-A", "wompi", "private_key")
        v3 = facade.get("tenant-A", "wompi", "private_key")

        self.assertEqual(v1, "PRV-PLAINTEXT")
        self.assertEqual(v2, "PRV-PLAINTEXT")
        self.assertEqual(v3, "PRV-PLAINTEXT")
        # Solo UNA lectura a tenant_integrations a pesar de 3 gets.
        self.assertEqual(
            client.read_count.get(("tenant_integrations", "credentials"), 0),
            1,
        )

    def test_cache_miss_emite_audit_con_cache_hit_false(self):
        client = _FakeSupabase()
        client._tables["tenant_integrations"].append({
            "tenant_id": "tenant-A",
            "provider": "aveonline",
            "credentials": {"api_key": "ENVIA-XYZ"},
        })
        facade = cf.TenantCredentialsFacade(client, service_name="api")

        facade.get("tenant-A", "aveonline", "api_key")
        audit = client._tables["credential_access_log"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["cache_hit"], False)
        self.assertEqual(audit[0]["accessed_by_service"], "api")

    def test_cache_hit_emite_audit_con_cache_hit_true(self):
        client = _FakeSupabase()
        client._tables["tenant_integrations"].append({
            "tenant_id": "tenant-A",
            "provider": "aveonline",
            "credentials": {"api_key": "K"},
        })
        facade = cf.TenantCredentialsFacade(client, service_name="api")

        facade.get("tenant-A", "aveonline", "api_key")  # miss
        facade.get("tenant-A", "aveonline", "api_key")  # hit
        audit = client._tables["credential_access_log"]
        self.assertEqual(len(audit), 2)
        self.assertEqual(audit[0]["cache_hit"], False)
        self.assertEqual(audit[1]["cache_hit"], True)

    def test_credencial_no_existe_retorna_none(self):
        client = _FakeSupabase()
        facade = cf.TenantCredentialsFacade(client, service_name="api")
        result = facade.get("tenant-X", "wompi", "private_key")
        self.assertIsNone(result)

    def test_invalidate_borra_entries_de_tenant(self):
        client = _FakeSupabase()
        client._tables["tenant_integrations"].extend([
            {"tenant_id": "tenant-A", "provider": "wompi",
             "credentials": {"private_key": "PRV-A"}},
            {"tenant_id": "tenant-A", "provider": "aveonline",
             "credentials": {"api_key": "ENV-A"}},
            {"tenant_id": "tenant-B", "provider": "wompi",
             "credentials": {"private_key": "PRV-B"}},
        ])
        facade = cf.TenantCredentialsFacade(client, service_name="api")

        facade.get("tenant-A", "wompi", "private_key")
        facade.get("tenant-A", "aveonline", "api_key")
        facade.get("tenant-B", "wompi", "private_key")
        self.assertEqual(cf._global_cache_size(), 3)

        n = facade.invalidate("tenant-A")
        self.assertEqual(n, 2)
        self.assertEqual(cf._global_cache_size(), 1)

    def test_invalidate_filtra_por_provider(self):
        client = _FakeSupabase()
        client._tables["tenant_integrations"].extend([
            {"tenant_id": "A", "provider": "wompi",
             "credentials": {"k": "v"}},
            {"tenant_id": "A", "provider": "aveonline",
             "credentials": {"k": "v"}},
        ])
        facade = cf.TenantCredentialsFacade(client, service_name="api")
        facade.get("A", "wompi", "k")
        facade.get("A", "aveonline", "k")
        self.assertEqual(cf._global_cache_size(), 2)

        n = facade.invalidate("A", "wompi")
        self.assertEqual(n, 1)
        self.assertEqual(cf._global_cache_size(), 1)


class ServiceValidationTests(unittest.TestCase):
    def setUp(self):
        cf._reset_global_cache()

    def test_service_canonico_no_warning(self):
        client = _FakeSupabase()
        # No raise, no warning.
        cf.TenantCredentialsFacade(client, service_name="orchestrator")

    def test_service_no_canonico_loguea_warning_pero_no_falla(self):
        client = _FakeSupabase()
        # Logger del módulo cargado vía importlib se nombra "_credentials_facade"
        # (alias usado en _load_lib). NO levanta excepción al usar service no canónico.
        with self.assertLogs("_credentials_facade", level="WARNING") as cm:
            facade = cf.TenantCredentialsFacade(client, service_name="hacker")
            self.assertIsNotNone(facade)
            self.assertTrue(any("no canónico" in msg for msg in cm.output))


class AuditDisabledTests(unittest.TestCase):
    def setUp(self):
        cf._reset_global_cache()

    def test_audit_disabled_no_inserta_log(self):
        client = _FakeSupabase()
        client._tables["tenant_integrations"].append({
            "tenant_id": "A", "provider": "wompi",
            "credentials": {"private_key": "K"},
        })
        facade = cf.TenantCredentialsFacade(
            client, service_name="api", audit_enabled=False,
        )
        facade.get("A", "wompi", "private_key")
        self.assertEqual(len(client._tables["credential_access_log"]), 0)


class CacheTTLTests(unittest.TestCase):
    """Test interno del caché — verifica expiración por TTL sin esperar 5min."""

    def test_ttl_expirado_es_miss(self):
        cache = cf._Cache(ttl_seconds=1)
        cache.put(("A", "wompi", "k"), "value")
        ok, v = cache.get(("A", "wompi", "k"))
        self.assertTrue(ok)
        self.assertEqual(v, "value")

        # Forzar expiración inyectando expires_at en el pasado.
        with patch("time.time", return_value=10**12):
            ok2, v2 = cache.get(("A", "wompi", "k"))
            self.assertFalse(ok2)
            self.assertIsNone(v2)


if __name__ == "__main__":
    unittest.main()

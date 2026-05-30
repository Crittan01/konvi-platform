"""Tests para `services/api/lib/identity_registry.py` (rev. 105 Sem 2 F.12 / MA-10).

Cubre los invariantes críticos del registry:
  1. Validación provider canónico (snake_case) — rechaza no-soportados.
  2. Normalización provider_internal_id (str obligatorio).
  3. resolve_tenant_id retorna None si no existe (no levanta).
  4. register_identity rechaza colisión cross-tenant (clase de bugs MA-10).
  5. register_identity es idempotente sobre el mismo tenant.
  6. revoke_identity elimina y retorna bool.

NO requiere DB real — usa un fake Supabase client con almacenamiento en
memoria que reproduce el contrato de la API supabase-py (table().select()
.eq().execute() → SimpleNamespace(data=...)).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "identity_registry.py"


def _load_lib():
    import sys
    spec = importlib.util.spec_from_file_location("_identity_registry", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registrar en sys.modules antes de exec — necesario para que dataclass
    # con `from __future__ import annotations` resuelva tipos.
    sys.modules["_identity_registry"] = mod
    spec.loader.exec_module(mod)
    return mod


registry = _load_lib()


# ─── Fake Supabase client en memoria ─────────────────────────────────────────

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

    def update(self, payload: dict[str, Any]):
        q = _FakeQuery(self._store, op="update", payload=payload)
        return q

    def delete(self):
        return _FakeQuery(self._store, op="delete")

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        return all(row.get(col) == val for col, val in self._filters)

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            if self._limit is not None:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)
        if self._op == "insert":
            new_id = max((r["id"] for r in self._store), default=0) + 1
            row = dict(self._payload)
            row["id"] = new_id
            row.setdefault("metadata", row.get("metadata") or {})
            # Resolver "now()" sentinel a un timestamp string fake.
            for ts_col in ("verified_at", "created_at", "updated_at"):
                if row.get(ts_col) == "now()" or ts_col not in row:
                    row[ts_col] = "2026-05-14T10:00:00Z" if ts_col != "verified_at" or row.get("verified_at") == "now()" else row.get("verified_at")
            self._store.append(row)
            return SimpleNamespace(data=[row])
        if self._op == "update":
            updated = []
            for row in self._store:
                if self._matches(row):
                    for k, v in self._payload.items():
                        row[k] = "2026-05-14T10:00:00Z" if v == "now()" else v
                    row["updated_at"] = "2026-05-14T10:00:00Z"
                    updated.append(row)
            return SimpleNamespace(data=updated)
        if self._op == "delete":
            keep = [r for r in self._store if not self._matches(r)]
            removed = [r for r in self._store if self._matches(r)]
            self._store.clear()
            self._store.extend(keep)
            return SimpleNamespace(data=removed)
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict[str, Any]]] = {
            "tenant_provider_identity": []
        }

    def table(self, name: str):
        return _FakeQuery(self._tables[name])


# ─── Tests ────────────────────────────────────────────────────────────────────

class ProviderValidationTests(unittest.TestCase):
    def test_provider_invalid_levanta(self):
        with self.assertRaises(registry.IdentityRegistryError):
            registry._validate_provider("FACEBOOK")
        with self.assertRaises(registry.IdentityRegistryError):
            registry._validate_provider("")

    def test_provider_canonico_se_normaliza_lowercase(self):
        self.assertEqual(registry._validate_provider("WHATSAPP"), "whatsapp")
        self.assertEqual(registry._validate_provider(" Telegram "), "telegram")

    def test_supported_providers_set_estable(self):
        # Garantiza que los 6 providers canónicos están presentes.
        for p in ("whatsapp", "wompi", "aveonline", "meli", "telegram", "resend"):
            self.assertIn(p, registry.SUPPORTED_PROVIDERS)

    def test_internal_id_none_levanta(self):
        with self.assertRaises(registry.IdentityRegistryError):
            registry._normalize_internal_id(None)

    def test_internal_id_vacio_levanta(self):
        with self.assertRaises(registry.IdentityRegistryError):
            registry._normalize_internal_id("   ")

    def test_internal_id_int_se_stringifica(self):
        self.assertEqual(registry._normalize_internal_id(123456789), "123456789")
        self.assertEqual(registry._normalize_internal_id("WABA-abc"), "WABA-abc")


class ResolveTenantIdTests(unittest.TestCase):
    def test_resolve_no_existe_retorna_none(self):
        client = _FakeSupabase()
        result = registry.resolve_tenant_id(client, "telegram", 999)
        self.assertIsNone(result)

    def test_resolve_existe_retorna_tenant_id(self):
        client = _FakeSupabase()
        registry.register_identity(
            client, "tenant-A", "telegram", "12345", metadata={"role": "operator"}
        )
        self.assertEqual(
            registry.resolve_tenant_id(client, "telegram", "12345"),
            "tenant-A",
        )

    def test_resolve_acepta_int_y_str(self):
        client = _FakeSupabase()
        registry.register_identity(client, "tenant-A", "telegram", 12345)
        # Búsqueda con int debe encontrar identidad almacenada como str.
        self.assertEqual(registry.resolve_tenant_id(client, "telegram", 12345), "tenant-A")
        self.assertEqual(registry.resolve_tenant_id(client, "telegram", "12345"), "tenant-A")


class RegisterIdentityCollisionTests(unittest.TestCase):
    """Tests centrales del bug MA-10. Cualquier regresión aquí reabre el
    bug Telegram cross-talk silencioso."""

    def test_cross_tenant_collision_levanta(self):
        client = _FakeSupabase()
        registry.register_identity(client, "tenant-A", "whatsapp", "PHONE-123")
        with self.assertRaises(registry.IdentityRegistryError) as ctx:
            registry.register_identity(client, "tenant-B", "whatsapp", "PHONE-123")
        self.assertIn("Cross-tenant identity collision", str(ctx.exception))
        self.assertIn("tenant-A", str(ctx.exception))

    def test_mismo_tenant_es_idempotente(self):
        client = _FakeSupabase()
        first = registry.register_identity(
            client, "tenant-A", "telegram", "55555", metadata={"v": 1}
        )
        # Re-registrar misma identidad para mismo tenant: no levanta, retorna fila.
        second = registry.register_identity(
            client, "tenant-A", "telegram", "55555", metadata={"v": 2}
        )
        self.assertEqual(first.id, second.id)

    def test_provider_distinto_mismo_internal_id_ok(self):
        # WhatsApp WABA "ABC" y Wompi merchant "ABC" son entidades distintas
        # — la UNIQUE es (provider, internal_id), no solo internal_id.
        client = _FakeSupabase()
        registry.register_identity(client, "tenant-A", "whatsapp", "ABC")
        registry.register_identity(client, "tenant-B", "wompi", "ABC")
        # Ambos coexisten sin colisión.
        self.assertEqual(registry.resolve_tenant_id(client, "whatsapp", "ABC"), "tenant-A")
        self.assertEqual(registry.resolve_tenant_id(client, "wompi", "ABC"), "tenant-B")


class ListAndRevokeTests(unittest.TestCase):
    def test_list_identities_para_tenant(self):
        client = _FakeSupabase()
        registry.register_identity(client, "tenant-A", "whatsapp", "WP-1")
        registry.register_identity(client, "tenant-A", "telegram", "TG-1")
        registry.register_identity(client, "tenant-B", "whatsapp", "WP-2")

        ids_a = registry.list_identities_for_tenant(client, "tenant-A")
        self.assertEqual(len(ids_a), 2)

        ids_a_wa = registry.list_identities_for_tenant(client, "tenant-A", "whatsapp")
        self.assertEqual(len(ids_a_wa), 1)
        self.assertEqual(ids_a_wa[0].provider_internal_id, "WP-1")

    def test_revoke_existente_retorna_true(self):
        client = _FakeSupabase()
        registry.register_identity(client, "tenant-A", "aveonline", "ACCT-1")
        self.assertTrue(registry.revoke_identity(client, "aveonline", "ACCT-1"))
        # Tras revoke, el slot queda libre para otro tenant.
        registry.register_identity(client, "tenant-B", "aveonline", "ACCT-1")
        self.assertEqual(
            registry.resolve_tenant_id(client, "aveonline", "ACCT-1"),
            "tenant-B",
        )

    def test_revoke_inexistente_retorna_false(self):
        client = _FakeSupabase()
        self.assertFalse(registry.revoke_identity(client, "aveonline", "NO-EXISTE"))


if __name__ == "__main__":
    unittest.main()

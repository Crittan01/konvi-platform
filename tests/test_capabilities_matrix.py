"""Tests `services/api/lib/capabilities_matrix.py` (rev. 105 Sem 2 F.3).

Cubre invariantes:
  1. Validación provider + capability canónicos.
  2. is_capability_enabled retorna default False si fila no existe.
  3. get_capability_config retorna {} si capability disabled.
  4. upsert_capability es idempotente (UNIQUE en DB).
  5. list_capabilities_for_tenant filtra por provider.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "capabilities_matrix.py"


def _load_lib():
    import sys
    spec = importlib.util.spec_from_file_location("_capabilities_matrix", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_capabilities_matrix"] = mod
    spec.loader.exec_module(mod)
    return mod


cm = _load_lib()


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
        return _FakeQuery(self._store, op="update", payload=payload)

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
            row.setdefault("created_at", "2026-05-14T10:00:00+00:00")
            row.setdefault("updated_at", "2026-05-14T10:00:00+00:00")
            self._store.append(row)
            return SimpleNamespace(data=[row])
        if self._op == "update":
            updated = []
            for row in self._store:
                if all(row.get(c) == v for c, v in self._filters):
                    for k, v in self._payload.items():
                        row[k] = v
                    row["updated_at"] = "2026-05-14T10:00:00+00:00"
                    updated.append(row)
            return SimpleNamespace(data=updated)
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict[str, Any]]] = {
            "tenant_provider_capabilities": []
        }

    def table(self, name: str):
        return _FakeQuery(self._tables[name])


class ValidationTests(unittest.TestCase):
    def test_provider_invalido_levanta(self):
        with self.assertRaises(cm.CapabilityError):
            cm._validate("FACEBOOK", "cod")

    def test_capability_no_canonica_levanta(self):
        with self.assertRaises(cm.CapabilityError):
            cm._validate("envia", "feature_inventada")

    def test_capability_canonica_lowercase(self):
        p, c = cm._validate("ENVIA", "COD")
        self.assertEqual(p, "envia")
        self.assertEqual(c, "cod")

    def test_capabilities_per_provider_completas(self):
        # Garantiza que las 6 providers canónicas tienen capabilities.
        self.assertEqual(
            set(cm.CAPABILITIES_BY_PROVIDER.keys()),
            {"envia", "wompi", "meta", "meli", "telegram", "resend"},
        )
        # Algunas capabilities críticas presentes.
        self.assertIn("cod", cm.CAPABILITIES_BY_PROVIDER["envia"])
        self.assertIn("hsm_templates", cm.CAPABILITIES_BY_PROVIDER["meta"])
        self.assertIn("payment_method_card", cm.CAPABILITIES_BY_PROVIDER["wompi"])
        self.assertIn("qna_reply", cm.CAPABILITIES_BY_PROVIDER["meli"])


class IsEnabledTests(unittest.TestCase):
    def test_no_existe_retorna_default_false(self):
        client = _FakeSupabase()
        result = cm.is_capability_enabled(client, "tenant-A", "envia", "cod")
        self.assertFalse(result)

    def test_no_existe_default_personalizado(self):
        client = _FakeSupabase()
        result = cm.is_capability_enabled(
            client, "tenant-A", "envia", "cod", default=True
        )
        self.assertTrue(result)

    def test_enabled_true_retorna_true(self):
        client = _FakeSupabase()
        cm.upsert_capability(
            client, "tenant-A", "envia", "cod",
            enabled=True, config={"carriers": ["servientrega"]}
        )
        self.assertTrue(
            cm.is_capability_enabled(client, "tenant-A", "envia", "cod")
        )

    def test_enabled_false_retorna_false(self):
        client = _FakeSupabase()
        cm.upsert_capability(
            client, "tenant-A", "envia", "cod", enabled=False
        )
        self.assertFalse(
            cm.is_capability_enabled(client, "tenant-A", "envia", "cod")
        )


class GetConfigTests(unittest.TestCase):
    def test_disabled_retorna_dict_vacio(self):
        client = _FakeSupabase()
        cm.upsert_capability(
            client, "tenant-A", "envia", "cod",
            enabled=False, config={"carriers": ["x"]}
        )
        cfg = cm.get_capability_config(client, "tenant-A", "envia", "cod")
        self.assertEqual(cfg, {})

    def test_enabled_retorna_config(self):
        client = _FakeSupabase()
        cm.upsert_capability(
            client, "tenant-A", "envia", "cod",
            enabled=True, config={"carriers": ["servientrega"], "fee": 2.5}
        )
        cfg = cm.get_capability_config(client, "tenant-A", "envia", "cod")
        self.assertEqual(cfg["carriers"], ["servientrega"])
        self.assertEqual(cfg["fee"], 2.5)


class UpsertTests(unittest.TestCase):
    def test_upsert_crea_si_no_existe(self):
        client = _FakeSupabase()
        rec = cm.upsert_capability(
            client, "tenant-A", "meta", "hsm_templates", enabled=True,
            config={"approved": ["welcome_v1"]}, notes="onboarding 2026-05",
        )
        self.assertTrue(rec.enabled)
        self.assertEqual(rec.config["approved"], ["welcome_v1"])
        self.assertEqual(rec.notes, "onboarding 2026-05")

    def test_upsert_actualiza_si_existe(self):
        client = _FakeSupabase()
        cm.upsert_capability(
            client, "tenant-A", "envia", "cod",
            enabled=False, config={"v": 1}
        )
        rec2 = cm.upsert_capability(
            client, "tenant-A", "envia", "cod",
            enabled=True, config={"v": 2}
        )
        self.assertTrue(rec2.enabled)
        self.assertEqual(rec2.config["v"], 2)
        # Solo una fila (UNIQUE constraint).
        self.assertEqual(
            len(client._tables["tenant_provider_capabilities"]),
            1,
        )


class ListTests(unittest.TestCase):
    def test_list_todas_de_un_tenant(self):
        client = _FakeSupabase()
        cm.upsert_capability(client, "A", "envia", "cod", True)
        cm.upsert_capability(client, "A", "wompi", "payment_method_card", True)
        cm.upsert_capability(client, "B", "envia", "cod", True)

        ids_a = cm.list_capabilities_for_tenant(client, "A")
        self.assertEqual(len(ids_a), 2)

    def test_list_filtra_por_provider(self):
        client = _FakeSupabase()
        cm.upsert_capability(client, "A", "envia", "cod", True)
        cm.upsert_capability(client, "A", "envia", "insurance", False)
        cm.upsert_capability(client, "A", "wompi", "payment_method_card", True)

        ids_envia = cm.list_capabilities_for_tenant(client, "A", "envia")
        self.assertEqual(len(ids_envia), 2)

    def test_list_provider_invalido_levanta(self):
        client = _FakeSupabase()
        with self.assertRaises(cm.CapabilityError):
            cm.list_capabilities_for_tenant(client, "A", "FACEBOOK")


if __name__ == "__main__":
    unittest.main()

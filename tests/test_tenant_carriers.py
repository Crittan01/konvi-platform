"""Tests tenant_carriers helper (rev. 105 Sem 5 H.2.7).

Cubre:
  1. validate_provider — provider inválido raise
  2. list_preferences — orden por priority + filtra por tenant
  3. filter_enabled_carriers — backward compat (vacío → todos)
  4. filter_enabled_carriers — case-insensitive matching
  5. filter_enabled_carriers — preserva orden candidates
  6. filter_enabled_carriers — todos disabled → lista vacía
  7. upsert_preference — idempotencia + retorna CarrierPreference
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    if "_tenant_carriers" in sys.modules:
        return sys.modules["_tenant_carriers"]
    spec = importlib.util.spec_from_file_location(
        "_tenant_carriers",
        REPO_ROOT / "services" / "api" / "lib" / "tenant_carriers.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_tenant_carriers"] = mod
    spec.loader.exec_module(mod)
    return mod


tc = _load()


class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None, conflict_keys: tuple = ()):
        self._store = store
        self._op = op
        self._payload = payload
        self._conflict_keys = conflict_keys
        self._filters: list[tuple[str, str, Any]] = []
        self._order: list[tuple[str, bool]] = []

    def select(self, _cols: str = "*"):
        return _FakeQuery(self._store, op="select")

    def insert(self, _payload):
        return _FakeQuery(self._store, op="insert", payload=_payload)

    def upsert(self, payload, on_conflict: str = ""):
        return _FakeQuery(
            self._store, op="upsert", payload=payload,
            conflict_keys=tuple(on_conflict.split(",")),
        )

    def delete(self):
        return _FakeQuery(self._store, op="delete")

    def eq(self, col: str, val: Any):
        self._filters.append((col, "eq", val))
        return self

    def order(self, col: str, desc: bool = False):
        self._order.append((col, desc))
        return self

    def _matches(self, row):
        for col, op, val in self._filters:
            if op == "eq" and row.get(col) != val:
                return False
        return True

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            for col, desc in reversed(self._order):
                rows = sorted(rows, key=lambda r: r.get(col) or 0, reverse=desc)
            return SimpleNamespace(data=rows)
        if self._op == "upsert":
            payload = self._payload
            # Buscar por conflict keys.
            for r in self._store:
                if all(
                    r.get(k.strip()) == payload.get(k.strip())
                    for k in self._conflict_keys
                ):
                    r.update(payload)
                    return SimpleNamespace(data=[r])
            new_row = {**payload, "id": len(self._store) + 1}
            self._store.append(new_row)
            return SimpleNamespace(data=[new_row])
        if self._op == "delete":
            initial = len(self._store)
            self._store[:] = [r for r in self._store if not self._matches(r)]
            return SimpleNamespace(data=[], count=initial - len(self._store))
        raise AssertionError(f"op {self._op} no soportado")


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict]] = {"tenant_carriers": []}

    def table(self, name: str):
        return _FakeQuery(self._tables[name])


class ValidateProviderTests(unittest.TestCase):
    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            tc._validate_provider("wompi")  # no en VALID_PROVIDERS

    def test_envia_ok(self):
        self.assertEqual(tc._validate_provider("envia"), "envia")
        self.assertEqual(tc._validate_provider("ENVIA"), "envia")
        self.assertEqual(tc._validate_provider("  envia  "), "envia")


class ListPreferencesTests(unittest.TestCase):
    def test_empty(self):
        sb = _FakeSupabase()
        result = tc.list_preferences(sb, "tenant-A", "envia")
        self.assertEqual(result, [])

    def test_orders_by_priority(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].extend([
            {"tenant_id": "tenant-A", "provider": "envia",
             "carrier_code": "fedex", "enabled": True, "priority": 50,
             "supports_cod": False, "supports_insurance": False},
            {"tenant_id": "tenant-A", "provider": "envia",
             "carrier_code": "servientrega", "enabled": True, "priority": 10,
             "supports_cod": True, "supports_insurance": False},
            {"tenant_id": "tenant-B", "provider": "envia",
             "carrier_code": "dhl", "enabled": True, "priority": 1,
             "supports_cod": False, "supports_insurance": False},
        ])
        result = tc.list_preferences(sb, "tenant-A", "envia")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].carrier_code, "servientrega")  # priority 10
        self.assertEqual(result[1].carrier_code, "fedex")  # priority 50
        self.assertTrue(result[0].supports_cod)
        self.assertFalse(result[1].supports_cod)


class FilterEnabledCarriersTests(unittest.TestCase):
    def test_no_preferences_returns_all_default_open(self):
        sb = _FakeSupabase()
        candidates = ["fedex", "servientrega", "dhl"]
        result = tc.filter_enabled_carriers(sb, "tenant-A", "envia", candidates)
        self.assertEqual(result, candidates)

    def test_with_preferences_filters_only_enabled(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].extend([
            {"tenant_id": "tenant-A", "provider": "envia",
             "carrier_code": "servientrega", "enabled": True, "priority": 100,
             "supports_cod": False, "supports_insurance": False},
            {"tenant_id": "tenant-A", "provider": "envia",
             "carrier_code": "fedex", "enabled": False, "priority": 100,
             "supports_cod": False, "supports_insurance": False},
        ])
        candidates = ["fedex", "servientrega", "dhl"]
        result = tc.filter_enabled_carriers(sb, "tenant-A", "envia", candidates)
        # Solo servientrega tiene enabled=true.
        # dhl no está en preferences (no en enabled set).
        # fedex está pero enabled=false.
        self.assertEqual(result, ["servientrega"])

    def test_case_insensitive_matching(self):
        # Envia mezcla camelCase y snake_case.
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].append({
            "tenant_id": "tenant-A", "provider": "envia",
            "carrier_code": "interrapidisimo",
            "enabled": True, "priority": 100,
            "supports_cod": False, "supports_insurance": False,
        })
        candidates = ["FedEx", "interRapidisimo", "DHL"]
        result = tc.filter_enabled_carriers(sb, "tenant-A", "envia", candidates)
        self.assertEqual(result, ["interRapidisimo"])  # preserva casing original

    def test_preserves_order_of_candidates(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].extend([
            {"tenant_id": "tenant-A", "provider": "envia",
             "carrier_code": "fedex", "enabled": True, "priority": 100,
             "supports_cod": False, "supports_insurance": False},
            {"tenant_id": "tenant-A", "provider": "envia",
             "carrier_code": "servientrega", "enabled": True, "priority": 100,
             "supports_cod": False, "supports_insurance": False},
        ])
        candidates = ["servientrega", "fedex"]
        result = tc.filter_enabled_carriers(sb, "tenant-A", "envia", candidates)
        self.assertEqual(result, ["servientrega", "fedex"])  # order preserved

    def test_all_disabled_returns_empty(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].append({
            "tenant_id": "tenant-A", "provider": "envia",
            "carrier_code": "fedex", "enabled": False, "priority": 100,
            "supports_cod": False, "supports_insurance": False,
        })
        candidates = ["fedex", "dhl"]
        result = tc.filter_enabled_carriers(sb, "tenant-A", "envia", candidates)
        # Tenant configuró pero deshabilitó todos. Caller debe alertar.
        self.assertEqual(result, [])

    def test_empty_candidates_returns_empty(self):
        sb = _FakeSupabase()
        result = tc.filter_enabled_carriers(sb, "tenant-A", "envia", [])
        self.assertEqual(result, [])


class UpsertPreferenceTests(unittest.TestCase):
    def test_insert_new(self):
        sb = _FakeSupabase()
        pref = tc.upsert_preference(
            sb, "tenant-A", "envia",
            carrier_code="servientrega",
            enabled=True, priority=10,
        )
        self.assertEqual(pref.carrier_code, "servientrega")
        self.assertTrue(pref.enabled)
        self.assertEqual(pref.priority, 10)
        self.assertEqual(len(sb._tables["tenant_carriers"]), 1)

    def test_update_existing_idempotent(self):
        sb = _FakeSupabase()
        # Insert primero.
        tc.upsert_preference(
            sb, "tenant-A", "envia", carrier_code="fedex", enabled=True,
        )
        # Update mismo carrier — UNIQUE conflict resuelto via on_conflict.
        pref = tc.upsert_preference(
            sb, "tenant-A", "envia", carrier_code="fedex",
            enabled=False, priority=50,
        )
        self.assertFalse(pref.enabled)
        self.assertEqual(pref.priority, 50)
        # Sigue habiendo 1 fila — no duplicó.
        self.assertEqual(len(sb._tables["tenant_carriers"]), 1)

    def test_empty_carrier_code_raises(self):
        sb = _FakeSupabase()
        with self.assertRaises(ValueError):
            tc.upsert_preference(sb, "tenant-A", "envia", carrier_code="")
        with self.assertRaises(ValueError):
            tc.upsert_preference(sb, "tenant-A", "envia", carrier_code="   ")


if __name__ == "__main__":
    unittest.main()

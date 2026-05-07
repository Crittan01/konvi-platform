"""Tests insurance helper (rev. 105 Sem 5 H.2.5).

Cubre:
  1. should_apply_insurance — sin tenant/carrier → False
  2. should_apply_insurance — sin row tenant_carriers → False (opt-in)
  3. should_apply_insurance — supports_insurance=true → True
  4. should_apply_insurance — supports_insurance=false → False
  5. should_apply_insurance — case-insensitive matching
  6. apply_insurance_to_packages — empty → empty
  7. apply_insurance_to_packages — single package
  8. apply_insurance_to_packages — multi packages distribuye valor
  9. apply_insurance_to_packages — declared_value=0 → no muta
 10. apply_insurance_to_packages — preserva additional_services existentes
 11. apply_insurance_to_packages — NO muta input original (deepcopy)
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    if "_insurance" in sys.modules:
        return sys.modules["_insurance"]
    spec = importlib.util.spec_from_file_location(
        "_insurance",
        REPO_ROOT / "services" / "api" / "lib" / "insurance.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_insurance"] = mod
    spec.loader.exec_module(mod)
    return mod


ins = _load()


class _FakeQuery:
    def __init__(self, store):
        self._store = store
        self._filters = []

    def select(self, _cols=""):
        return self

    def eq(self, col, val):
        self._filters.append((col, "eq", val))
        return self

    def ilike(self, col, pattern):
        self._filters.append((col, "ilike", pattern.lower()))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        rows = []
        for r in self._store:
            ok = True
            for col, op, val in self._filters:
                if op == "eq" and r.get(col) != val:
                    ok = False; break
                if op == "ilike" and (r.get(col) or "").lower() != val:
                    ok = False; break
            if ok:
                rows.append(r)
        return SimpleNamespace(data=rows)


class _FakeSupabase:
    def __init__(self):
        self._tables = {"tenant_carriers": []}

    def table(self, name):
        return _FakeQuery(self._tables[name])


# ─── should_apply_insurance ──────────────────────────────────────────────────

class ShouldApplyInsuranceTests(unittest.TestCase):
    def test_empty_tenant_returns_false(self):
        sb = _FakeSupabase()
        self.assertFalse(ins.should_apply_insurance(sb, "", "fedex"))
        self.assertFalse(ins.should_apply_insurance(sb, None, "fedex"))

    def test_empty_carrier_returns_false(self):
        sb = _FakeSupabase()
        self.assertFalse(ins.should_apply_insurance(sb, "tenant-A", ""))
        self.assertFalse(ins.should_apply_insurance(sb, "tenant-A", "  "))

    def test_no_row_returns_false_optin(self):
        # Default: insurance es opt-in. Sin fila explícita → False.
        sb = _FakeSupabase()
        self.assertFalse(ins.should_apply_insurance(sb, "tenant-A", "fedex"))

    def test_supports_insurance_true(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].append({
            "tenant_id": "tenant-A", "provider": "envia",
            "carrier_code": "coordinadora", "supports_insurance": True,
        })
        self.assertTrue(ins.should_apply_insurance(sb, "tenant-A", "coordinadora"))

    def test_supports_insurance_false(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].append({
            "tenant_id": "tenant-A", "provider": "envia",
            "carrier_code": "fedex", "supports_insurance": False,
        })
        self.assertFalse(ins.should_apply_insurance(sb, "tenant-A", "fedex"))

    def test_case_insensitive(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].append({
            "tenant_id": "tenant-A", "provider": "envia",
            "carrier_code": "interrapidisimo", "supports_insurance": True,
        })
        # Envia API mezcla camelCase y lowercase — lookup case-insensitive.
        self.assertTrue(
            ins.should_apply_insurance(sb, "tenant-A", "interRapidisimo"),
        )

    def test_tenant_isolation(self):
        sb = _FakeSupabase()
        sb._tables["tenant_carriers"].append({
            "tenant_id": "tenant-A", "provider": "envia",
            "carrier_code": "coordinadora", "supports_insurance": True,
        })
        # Otro tenant pregunta por mismo carrier → False.
        self.assertFalse(
            ins.should_apply_insurance(sb, "tenant-B", "coordinadora"),
        )


# ─── apply_insurance_to_packages ─────────────────────────────────────────────

class ApplyInsuranceToPackagesTests(unittest.TestCase):
    def test_empty_packages(self):
        self.assertEqual(ins.apply_insurance_to_packages([], declared_value_cop=10000), [])

    def test_zero_declared_value_no_change(self):
        pkgs = [{"weight": 1, "content": "test"}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=0)
        self.assertEqual(result, pkgs)
        self.assertNotIn("declaredValue", result[0])
        self.assertNotIn("additional_services", result[0])

    def test_negative_declared_value_no_change(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=-100)
        self.assertEqual(result, pkgs)

    def test_single_package_full_value(self):
        pkgs = [{"weight": 1, "content": "test"}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=100000)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["declaredValue"], 100000)
        self.assertEqual(result[0]["additional_services"], ["envia_insurance"])

    def test_multi_packages_distribuye_valor(self):
        pkgs = [{"weight": 1}, {"weight": 2}, {"weight": 3}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=99000)
        # 99000 / 3 = 33000, sin remainder.
        self.assertEqual(result[0]["declaredValue"], 33000)
        self.assertEqual(result[1]["declaredValue"], 33000)
        self.assertEqual(result[2]["declaredValue"], 33000)
        # Suma == valor total.
        self.assertEqual(
            sum(r["declaredValue"] for r in result), 99000,
        )

    def test_remainder_va_al_primer_package(self):
        pkgs = [{"weight": 1}, {"weight": 1}, {"weight": 1}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=100000)
        # 100000 / 3 = 33333, remainder = 1.
        self.assertEqual(result[0]["declaredValue"], 33334)  # base + remainder
        self.assertEqual(result[1]["declaredValue"], 33333)
        self.assertEqual(result[2]["declaredValue"], 33333)
        self.assertEqual(
            sum(r["declaredValue"] for r in result), 100000,
        )

    def test_preserva_additional_services_existentes(self):
        # Caso futuro: package ya tiene additional_services con
        # cash_on_delivery (H.2.4 futuro) — insurance debe AGREGARSE,
        # no reemplazar.
        pkgs = [{
            "weight": 1,
            "additional_services": ["cash_on_delivery"],
        }]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=50000)
        self.assertEqual(
            result[0]["additional_services"],
            ["cash_on_delivery", "envia_insurance"],
        )

    def test_no_muta_input(self):
        original = [{"weight": 1, "content": "test"}]
        snapshot = deepcopy(original)
        result = ins.apply_insurance_to_packages(original, declared_value_cop=10000)
        # Original NO debe haber cambiado.
        self.assertEqual(original, snapshot)
        # Result SÍ tiene declaredValue.
        self.assertEqual(result[0]["declaredValue"], 10000)
        # NO son la misma referencia.
        self.assertIsNot(result[0], original[0])

    def test_no_duplicates_si_ya_tiene_envia_insurance(self):
        pkgs = [{
            "weight": 1,
            "additional_services": ["envia_insurance"],
        }]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=10000)
        # NO duplicar el service.
        self.assertEqual(
            result[0]["additional_services"],
            ["envia_insurance"],
        )


if __name__ == "__main__":
    unittest.main()

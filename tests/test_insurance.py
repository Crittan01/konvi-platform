"""Tests insurance / declaredValue helper — provider-agnostic post-rev. 109.

Aveonline (provider único activo, ADR-0019) usa `declared_value_cop` como
base para cálculo de `valuation_percent` interno per carrier. Sin
`additional_services` Envia-específicos.

Tests:
  - Edge cases (empty, zero, negative declared_value).
  - Distribución floor + remainder en N packages.
  - Immutability (no mutar input).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


def _load_insurance_module():
    """Carga lib.insurance directo sin depender del paquete `lib`."""
    if "_insurance" in sys.modules:
        return sys.modules["_insurance"]
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    path = repo_root / "services" / "api" / "lib" / "insurance.py"
    spec = importlib.util.spec_from_file_location("_insurance", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_insurance"] = mod
    spec.loader.exec_module(mod)
    return mod


ins = _load_insurance_module()


# ─── Edge cases — early return sin tocar packages ───────────────────────────


class TestInsuranceEdgeCases(unittest.TestCase):

    def test_empty_packages_returns_empty(self):
        self.assertEqual(
            ins.apply_insurance_to_packages([], declared_value_cop=10000), [],
        )

    def test_zero_declared_value_returns_unchanged(self):
        pkgs = [{"weight": 1.0}]
        self.assertEqual(
            ins.apply_insurance_to_packages(pkgs, declared_value_cop=0),
            pkgs,
        )

    def test_negative_declared_value_returns_unchanged(self):
        pkgs = [{"weight": 1.0}]
        self.assertEqual(
            ins.apply_insurance_to_packages(pkgs, declared_value_cop=-100),
            pkgs,
        )

    def test_immutable_input(self):
        """apply_insurance_to_packages NO debe mutar la lista original."""
        original = [{"weight": 1.0, "content": "Test"}]
        ins.apply_insurance_to_packages(original, declared_value_cop=10000)
        self.assertNotIn("declaredValue", original[0])


# ─── Distribución valor declarado entre N packages ──────────────────────────


class TestDeclaredValueDistribution(unittest.TestCase):

    def test_single_package_gets_full_value(self):
        pkgs = [{"weight": 1.0}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=100000)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["declaredValue"], 100000)

    def test_two_packages_split_evenly(self):
        pkgs = [{"weight": 1.0}, {"weight": 2.0}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=100000)
        self.assertEqual(result[0]["declaredValue"], 50000)
        self.assertEqual(result[1]["declaredValue"], 50000)

    def test_three_packages_with_remainder_in_first(self):
        pkgs = [{"weight": 1.0}, {"weight": 2.0}, {"weight": 3.0}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=100)
        # 100 // 3 = 33, remainder 1 → first absorbe 34, otros 33
        self.assertEqual(result[0]["declaredValue"], 34)
        self.assertEqual(result[1]["declaredValue"], 33)
        self.assertEqual(result[2]["declaredValue"], 33)
        total = sum(r["declaredValue"] for r in result)
        self.assertEqual(total, 100)

    def test_preserves_other_package_fields(self):
        pkgs = [{"weight": 1.0, "content": "Producto X", "amount": 2}]
        result = ins.apply_insurance_to_packages(pkgs, declared_value_cop=50000)
        self.assertEqual(result[0]["weight"], 1.0)
        self.assertEqual(result[0]["content"], "Producto X")
        self.assertEqual(result[0]["amount"], 2)
        self.assertEqual(result[0]["declaredValue"], 50000)


if __name__ == "__main__":
    unittest.main()

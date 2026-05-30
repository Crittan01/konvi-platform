"""Tests insurance helper (rev. 105 Sem 5 H.2.5 v2 — 2026-05-08).

Cubre `apply_insurance_to_packages(packages, *, declared_value_cop, carrier)`:

  Reglas (basadas en docs Envia + evidencia empírica prod 2026-05-07):
    - declaredValue se setea SIEMPRE en cada package.
    - additional_services:["envia_insurance"] se agrega SOLO si carrier="envia".
    - Otros carriers (Coordinadora, FedEx, DHL, etc.) reciben solo declaredValue.
    - Coordinadora rompe con Bad Gateway si recibe envia_insurance (validado prod).
    - El input NO se muta (deepcopy interno).
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from copy import deepcopy
from pathlib import Path

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


# ─── apply_insurance_to_packages — base ──────────────────────────────────────

class ApplyInsuranceBaseTests(unittest.TestCase):
    def test_empty_packages(self):
        self.assertEqual(
            ins.apply_insurance_to_packages([], declared_value_cop=10000, carrier="envia"), [],
        )

    def test_zero_declared_value_no_change(self):
        pkgs = [{"weight": 1, "content": "test"}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=0, carrier="envia",
        )
        self.assertEqual(result, pkgs)
        self.assertNotIn("declaredValue", result[0])
        self.assertNotIn("additional_services", result[0])

    def test_negative_declared_value_no_change(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=-100, carrier="envia",
        )
        self.assertEqual(result, pkgs)

    def test_no_muta_input(self):
        original = [{"weight": 1, "content": "test"}]
        snapshot = deepcopy(original)
        result = ins.apply_insurance_to_packages(
            original, declared_value_cop=10000, carrier="envia",
        )
        self.assertEqual(original, snapshot)
        self.assertEqual(result[0]["declaredValue"], 10000)
        self.assertIsNot(result[0], original[0])


# ─── carrier="envia" — único que recibe envia_insurance additional_service ──

class EnviaOwnCarrierTests(unittest.TestCase):
    def test_single_package_full_value(self):
        pkgs = [{"weight": 1, "content": "test"}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=100000, carrier="envia",
        )
        self.assertEqual(result[0]["declaredValue"], 100000)
        self.assertEqual(result[0]["additional_services"], ["envia_insurance"])

    def test_carrier_envia_case_insensitive(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=50000, carrier="ENVIA",
        )
        self.assertEqual(result[0]["additional_services"], ["envia_insurance"])

    def test_carrier_envia_with_whitespace(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=50000, carrier="  envia  ",
        )
        self.assertEqual(result[0]["additional_services"], ["envia_insurance"])

    def test_multi_packages_distribuye_valor(self):
        pkgs = [{"weight": 1}, {"weight": 2}, {"weight": 3}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=99000, carrier="envia",
        )
        self.assertEqual(result[0]["declaredValue"], 33000)
        self.assertEqual(result[1]["declaredValue"], 33000)
        self.assertEqual(result[2]["declaredValue"], 33000)
        self.assertEqual(sum(r["declaredValue"] for r in result), 99000)

    def test_remainder_va_al_primer_package(self):
        pkgs = [{"weight": 1}, {"weight": 1}, {"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=100000, carrier="envia",
        )
        self.assertEqual(result[0]["declaredValue"], 33334)
        self.assertEqual(result[1]["declaredValue"], 33333)
        self.assertEqual(result[2]["declaredValue"], 33333)
        self.assertEqual(sum(r["declaredValue"] for r in result), 100000)

    def test_preserva_additional_services_existentes(self):
        pkgs = [{"weight": 1, "additional_services": ["electronic_signature"]}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=50000, carrier="envia",
        )
        self.assertEqual(
            result[0]["additional_services"],
            ["electronic_signature", "envia_insurance"],
        )

    def test_no_duplicates_si_ya_tiene_envia_insurance(self):
        pkgs = [{"weight": 1, "additional_services": ["envia_insurance"]}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=10000, carrier="envia",
        )
        self.assertEqual(result[0]["additional_services"], ["envia_insurance"])


# ─── Carriers no-envia — declaredValue solo, NO additional_service ───────────

class OtherCarriersTests(unittest.TestCase):
    def test_coordinadora_solo_declared_value(self):
        """Coordinadora rompe con envia_insurance — solo declaredValue.
        Validado prod 2026-05-07: Bad Gateway con additional_service envia_insurance."""
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=3_000_000, carrier="coordinadora",
        )
        self.assertEqual(result[0]["declaredValue"], 3_000_000)
        self.assertNotIn("additional_services", result[0])

    def test_fedex_solo_declared_value(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=100000, carrier="fedex",
        )
        self.assertEqual(result[0]["declaredValue"], 100000)
        self.assertNotIn("additional_services", result[0])

    def test_servientrega_solo_declared_value(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=50000, carrier="servientrega",
        )
        self.assertEqual(result[0]["declaredValue"], 50000)
        self.assertNotIn("additional_services", result[0])

    def test_dhl_solo_declared_value(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=200000, carrier="dhl",
        )
        self.assertEqual(result[0]["declaredValue"], 200000)
        self.assertNotIn("additional_services", result[0])

    def test_interrapidisimo_camelcase(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=50000, carrier="interRapidisimo",
        )
        self.assertEqual(result[0]["declaredValue"], 50000)
        self.assertNotIn("additional_services", result[0])

    def test_carrier_no_envia_preserva_additional_services_existentes(self):
        """Si caller pasó additional_services para Coordinadora (ej.
        electronic_signature), NO debemos tocarlos."""
        pkgs = [{"weight": 1, "additional_services": ["electronic_signature"]}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=50000, carrier="coordinadora",
        )
        self.assertEqual(
            result[0]["additional_services"], ["electronic_signature"],
        )
        self.assertEqual(result[0]["declaredValue"], 50000)

    def test_carrier_none_no_agrega_envia_insurance(self):
        pkgs = [{"weight": 1}]
        result = ins.apply_insurance_to_packages(
            pkgs, declared_value_cop=50000, carrier=None,
        )
        self.assertEqual(result[0]["declaredValue"], 50000)
        self.assertNotIn("additional_services", result[0])


# ─── Helper interno ──────────────────────────────────────────────────────────

class IsEnviaOwnCarrierTests(unittest.TestCase):
    def test_envia_lowercase(self):
        self.assertTrue(ins._is_envia_own_carrier("envia"))

    def test_envia_uppercase(self):
        self.assertTrue(ins._is_envia_own_carrier("ENVIA"))

    def test_envia_with_spaces(self):
        self.assertTrue(ins._is_envia_own_carrier("  envia  "))

    def test_other_carriers_false(self):
        for c in ("coordinadora", "fedex", "dhl", "servientrega",
                  "interRapidisimo", "tcc", "deprisa"):
            self.assertFalse(
                ins._is_envia_own_carrier(c),
                f"Esperado False para {c!r}",
            )

    def test_empty_or_none(self):
        self.assertFalse(ins._is_envia_own_carrier(""))
        self.assertFalse(ins._is_envia_own_carrier(None))


if __name__ == "__main__":
    unittest.main()

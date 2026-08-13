"""Sem 7 F2 cierre 2026-05-20 — Punto A founder UAT.

Matriz de validación para los 5 escenarios de building_type:
  1. Casa
  2. Edificio / Apartamento
  3. Conjunto torres
  4. Conjunto casas (con manzana opcional D4)
  5. Oficina / Lugar de trabajo

Por cada escenario valida:
  - validator API (`address_required_fields` + `is_address_complete`)
  - FSM Python (`missing_address_fields` + `has_real_address_data`)
  - Render summary (`_format_address_for_summary`)
  - Render known_customer (`_format_address`)

Garantiza coherencia 1:N (1 schema, N consumidores) — si cambia el
contrato en un lugar, este matriz lo cazará.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

# Validator API
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
from dependencies.contact_validators import (  # noqa: E402
    address_required_fields,
    is_address_complete,
)

# FSM + orchestrator render
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))
from fsm.address import (  # noqa: E402
    missing_address_fields,
    has_real_address_data,
)
import orchestrator  # noqa: E402
from tools.known_customer_tool import _format_address  # noqa: E402


# ── Fixtures por building_type (mínima address completa) ──────────────────

CASA = {
    "street": "Calle 10 # 5-23",
    "city": "Bogotá D.C.",
    "state": "Bogotá D.C.",
    "neighborhood": "Chapinero",
    "dane_code": "11001",
    "building_type": "casa",
}

EDIFICIO = {
    "street": "Carrera 7 # 32-18",
    "city": "Bogotá D.C.",
    "state": "Bogotá D.C.",
    "neighborhood": "Centro",
    "dane_code": "11001",
    "building_type": "edificio",
    "apartment": "501",
}

CONJUNTO_TORRES = {
    "street": "Calle 80 # 11-30",
    "city": "Bogotá D.C.",
    "state": "Bogotá D.C.",
    "neighborhood": "Chicó",
    "dane_code": "11001",
    "building_type": "conjunto",
    "conjunto_type": "torres",
    "tower": "3",
    "apartment": "401",
}

CONJUNTO_CASAS = {
    "street": "Diagonal 5 # 50-12",
    "city": "Cali",
    "state": "Valle del Cauca",
    "neighborhood": "Ciudad Jardín",
    "dane_code": "76001",
    "building_type": "conjunto",
    "conjunto_type": "casas",
    "apartment": "12",  # "Casa #12"
}

OFICINA = {
    "street": "Carrera 7 # 80-50",
    "city": "Bogotá D.C.",
    "state": "Bogotá D.C.",
    "dane_code": "11001",
    "building_type": "oficina",
    "apartment": "501",
    # neighborhood OPCIONAL en oficina (P6 opción C).
    # floor + company_name OPCIONALES (D1 + D2).
}


# ── 1. Casa ───────────────────────────────────────────────────────────────

class CasaMatrixTests(unittest.TestCase):

    def test_validator_api_required_fields(self):
        self.assertEqual(
            address_required_fields("casa"),
            ["street", "neighborhood", "city", "state", "dane_code"],
        )

    def test_validator_api_complete(self):
        ok, missing = is_address_complete(CASA)
        self.assertTrue(ok, f"missing={missing}")

    def test_validator_api_sin_barrio_falla(self):
        addr = {**CASA}
        del addr["neighborhood"]
        ok, missing = is_address_complete(addr)
        self.assertFalse(ok)
        self.assertIn("neighborhood", missing)

    def test_fsm_complete(self):
        self.assertEqual(missing_address_fields(CASA), [])
        self.assertTrue(has_real_address_data(CASA))

    def test_fsm_sin_barrio_falla(self):
        addr = {**CASA}
        del addr["neighborhood"]
        missing = missing_address_fields(addr)
        self.assertIn("Barrio", missing)
        self.assertFalse(has_real_address_data(addr))

    def test_render_summary_includes_street_and_neighborhood(self):
        out = orchestrator._format_address_for_summary(CASA)
        self.assertIn("Calle 10 # 5-23", out)
        self.assertIn("Chapinero", out)
        self.assertIn("Bogotá", out)
        # Casa NO debe renderizar "Apto", "Torre", "Casa #", "Oficina".
        self.assertNotIn("Apto", out)
        self.assertNotIn("Torre", out)
        self.assertNotIn("Oficina", out)


# ── 2. Edificio / Apartamento ─────────────────────────────────────────────

class EdificioMatrixTests(unittest.TestCase):

    def test_validator_required_fields(self):
        self.assertIn("apartment", address_required_fields("edificio"))
        self.assertIn("neighborhood", address_required_fields("edificio"))

    def test_validator_complete(self):
        ok, missing = is_address_complete(EDIFICIO)
        self.assertTrue(ok, f"missing={missing}")

    def test_validator_sin_apartment_falla(self):
        addr = {**EDIFICIO}
        del addr["apartment"]
        ok, missing = is_address_complete(addr)
        self.assertFalse(ok)
        self.assertIn("apartment", missing)

    def test_fsm_complete(self):
        self.assertEqual(missing_address_fields(EDIFICIO), [])

    def test_render_summary(self):
        out = orchestrator._format_address_for_summary(EDIFICIO)
        self.assertIn("Apto 501", out)
        self.assertIn("Centro", out)

    def test_render_summary_with_floor(self):
        addr = {**EDIFICIO, "floor": "5"}
        out = orchestrator._format_address_for_summary(addr)
        self.assertIn("Piso 5", out)
        self.assertIn("Apto 501", out)


# ── 3. Conjunto torres ────────────────────────────────────────────────────

class ConjuntoTorresMatrixTests(unittest.TestCase):

    def test_validator_required_fields(self):
        req = address_required_fields("conjunto", "torres")
        self.assertIn("tower", req)
        self.assertIn("apartment", req)
        self.assertIn("neighborhood", req)

    def test_validator_complete(self):
        ok, missing = is_address_complete(CONJUNTO_TORRES)
        self.assertTrue(ok, f"missing={missing}")

    def test_fsm_complete(self):
        self.assertEqual(missing_address_fields(CONJUNTO_TORRES), [])

    def test_fsm_sin_tower_falla(self):
        addr = {**CONJUNTO_TORRES}
        del addr["tower"]
        missing = missing_address_fields(addr)
        self.assertIn("Torre", missing)

    def test_render_summary(self):
        out = orchestrator._format_address_for_summary(CONJUNTO_TORRES)
        self.assertIn("Torre 3", out)
        self.assertIn("Apto 401", out)
        self.assertNotIn("Casa #", out)


# ── 4. Conjunto casas (D4 manzana opcional) ───────────────────────────────

class ConjuntoCasasMatrixTests(unittest.TestCase):

    def test_validator_required_fields_no_tower(self):
        req = address_required_fields("conjunto", "casas")
        self.assertIn("apartment", req)
        self.assertNotIn("tower", req)  # tower es opcional (D4).

    def test_validator_complete_sin_manzana(self):
        ok, missing = is_address_complete(CONJUNTO_CASAS)
        self.assertTrue(ok, f"missing={missing}")

    def test_fsm_complete_sin_manzana(self):
        self.assertEqual(missing_address_fields(CONJUNTO_CASAS), [])

    def test_render_summary_sin_manzana(self):
        out = orchestrator._format_address_for_summary(CONJUNTO_CASAS)
        self.assertIn("Casa #12", out)
        self.assertNotIn("Manzana", out)
        self.assertNotIn("Torre", out)

    def test_render_summary_con_manzana(self):
        addr = {**CONJUNTO_CASAS, "tower": "A"}
        out = orchestrator._format_address_for_summary(addr)
        self.assertIn("Manzana A", out)
        self.assertIn("Casa #12", out)
        self.assertNotIn("Torre", out)  # NO debe decir "Torre" en casas.


# ── 5. Oficina / Lugar de trabajo ─────────────────────────────────────────

class OficinaMatrixTests(unittest.TestCase):

    def test_validator_required_fields_sin_barrio(self):
        """P6 opción C — barrio opcional en oficina."""
        req = address_required_fields("oficina")
        self.assertIn("apartment", req)
        self.assertNotIn("neighborhood", req)  # OPCIONAL en oficina.

    def test_validator_complete_sin_barrio(self):
        ok, missing = is_address_complete(OFICINA)
        self.assertTrue(ok, f"missing={missing}")

    def test_fsm_complete_sin_barrio(self):
        self.assertEqual(missing_address_fields(OFICINA), [])

    def test_fsm_no_pide_barrio(self):
        """Oficina sin barrio NO debe estar en missing fields."""
        missing = missing_address_fields(OFICINA)
        self.assertNotIn("Barrio", missing)

    def test_render_summary(self):
        out = orchestrator._format_address_for_summary(OFICINA)
        self.assertIn("Oficina 501", out)
        self.assertNotIn("Apto", out)
        self.assertNotIn("Casa #", out)

    def test_render_summary_con_floor(self):
        addr = {**OFICINA, "floor": "5"}
        out = orchestrator._format_address_for_summary(addr)
        self.assertIn("Piso 5", out)
        self.assertIn("Oficina 501", out)

    def test_render_summary_con_company(self):
        addr = {**OFICINA, "floor": "3", "company_name": "Banco de Bogotá"}
        out = orchestrator._format_address_for_summary(addr)
        self.assertIn("Banco de Bogotá", out)
        self.assertIn("Piso 3", out)
        self.assertIn("Oficina 501", out)


# ── Coherencia cross-validator (1 schema, N consumidores) ─────────────────

class CoherenceCrossValidatorTests(unittest.TestCase):
    """Garantiza que validator API y FSM Python coincidan en todos los
    escenarios. Una desincronía silenciosa (caso del bug founder UAT)
    aquí se caza inmediatamente."""

    SCENARIOS = [
        ("casa", CASA),
        ("edificio", EDIFICIO),
        ("conjunto_torres", CONJUNTO_TORRES),
        ("conjunto_casas", CONJUNTO_CASAS),
        ("oficina", OFICINA),
    ]

    def test_all_complete_addresses_pass_both(self):
        for name, addr in self.SCENARIOS:
            with self.subTest(scenario=name):
                ok_api, _ = is_address_complete(addr)
                ok_fsm = has_real_address_data(addr)
                self.assertEqual(
                    ok_api, ok_fsm,
                    f"desincronía API vs FSM en {name}: "
                    f"api={ok_api} fsm={ok_fsm} addr={addr}",
                )

    def test_known_customer_render_no_crashes(self):
        """Render `_format_address` debe completar sin excepción en los 5."""
        for name, addr in self.SCENARIOS:
            with self.subTest(scenario=name):
                out = _format_address(addr)
                # Mínimo: contiene street.
                self.assertIn(addr["street"], out)


if __name__ == "__main__":
    unittest.main()

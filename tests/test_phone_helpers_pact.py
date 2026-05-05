"""Pact test — `services/api/lib/phone.py` ≡ `services/ai-orchestrator/lib/phone.py`
≡ `services/connector-whatsapp/lib/phone.py`.

Garantiza que los TRES servicios usen el MISMO canonicalizador. Cualquier cambio
en uno DEBE replicarse en los otros dos o este test falla.

Implementación: usamos `importlib.util.spec_from_file_location` para cargar
cada archivo bajo nombre único (`_phone_api`, `_phone_orch`, `_phone_conn`)
sin mutar sys.path ni shadowear el namespace `lib` de otros tests.
"""
from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
API_PHONE = REPO_ROOT / "services" / "api" / "lib" / "phone.py"
ORCH_PHONE = REPO_ROOT / "services" / "ai-orchestrator" / "lib" / "phone.py"
CONN_PHONE = REPO_ROOT / "services" / "connector-whatsapp" / "lib" / "phone.py"


def _file_hash(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _load_isolated(label: str, path: Path) -> ModuleType:
    """Carga un módulo desde un path absoluto sin mutar sys.path ni sys.modules['lib']."""
    spec = importlib.util.spec_from_file_location(f"_phone_pact_{label}", str(path))
    assert spec and spec.loader, f"no spec for {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PhoneHelpersPactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load_isolated("api", API_PHONE)
        cls.orch = _load_isolated("orch", ORCH_PHONE)
        cls.conn = _load_isolated("conn", CONN_PHONE)

    def test_phone_files_byte_identical(self):
        for f in (API_PHONE, ORCH_PHONE, CONN_PHONE):
            self.assertTrue(f.exists(), f"missing {f}")
        h_api = _file_hash(API_PHONE)
        h_orch = _file_hash(ORCH_PHONE)
        h_conn = _file_hash(CONN_PHONE)
        self.assertTrue(h_api == h_orch == h_conn, (
            f"phone.py difiere entre servicios. "
            f"api={h_api[:8]} orch={h_orch[:8]} conn={h_conn[:8]}"
        ))

    def test_to_canonical_contract(self):
        p = self.api
        cases = [
            ("+57 312 583 5649", "573125835649"),
            ("3125835649",       "573125835649"),
            ("57 3125835649",    "573125835649"),
            ("+573125835649",    "573125835649"),
            ("",                  None),
            (None,                None),
            ("abc",               None),
            ("123",               None),
            ("57573125835649",    "573125835649"),  # legacy doble prefix
            ("12015551234",       "12015551234"),    # extranjero (preservar)
        ]
        for raw, expected in cases:
            self.assertEqual(p.to_canonical(raw), expected,
                             f"to_canonical({raw!r}) != {expected!r}")

    def test_to_e164_idempotent(self):
        p = self.api
        self.assertEqual(p.to_e164("573125835649"), "+573125835649")
        self.assertEqual(p.to_e164("+573125835649"), "+573125835649")
        self.assertIsNone(p.to_e164(None))
        self.assertIsNone(p.to_e164(""))

    def test_hash_phone_invariante_a_formato(self):
        p = self.api
        h1 = p.hash_phone("+57 312 583 5649")
        h2 = p.hash_phone("3125835649")
        h3 = p.hash_phone("573125835649")
        h4 = p.hash_phone("+573125835649")
        self.assertEqual(h1, h2)
        self.assertEqual(h2, h3)
        self.assertEqual(h3, h4)
        self.assertEqual(len(h1), 64)
        self.assertEqual(p.hash_phone(None), "")
        self.assertEqual(p.hash_phone(""), "")

    def test_is_valid_co(self):
        p = self.api
        self.assertTrue(p.is_valid_co("573125835649"))
        self.assertFalse(p.is_valid_co("523125835649"))
        self.assertFalse(p.is_valid_co("57312583564"))
        self.assertFalse(p.is_valid_co("5731258356499"))
        self.assertFalse(p.is_valid_co(None))
        self.assertFalse(p.is_valid_co(""))

    def test_aliases_consistentes(self):
        p = self.api
        raw = "+57 312 583 5649"
        canon = p.to_canonical(raw)
        self.assertEqual(p.to_db_format(raw), canon)
        self.assertEqual(p.to_meta_wa_format(raw), canon)
        self.assertEqual(p.to_wompi_format(raw), "+573125835649")
        self.assertEqual(p.to_display_format(raw), "+57 312 583 5649")

    def test_orchestrator_y_connector_funcionalmente_equivalentes(self):
        """Los TRES módulos producen el mismo output ante el mismo input."""
        raw = "+57 312 583 5649"
        api_canon = self.api.to_canonical(raw)
        api_hash = self.api.hash_phone(raw)
        api_e164 = self.api.to_e164(api_canon)
        for label, mod in (("orch", self.orch), ("conn", self.conn)):
            self.assertEqual(mod.to_canonical(raw), api_canon, f"{label} to_canonical")
            self.assertEqual(mod.hash_phone(raw), api_hash, f"{label} hash_phone")
            self.assertEqual(mod.to_e164(mod.to_canonical(raw)), api_e164,
                             f"{label} to_e164")


if __name__ == "__main__":
    unittest.main()

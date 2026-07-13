"""BLOQUE K-3 (auditoría 2026-07-12) — paridad de las copias legacy de _hash_phone.

El helper `_hash_phone` (sha256 con strip de espacios/+/-) está DUPLICADO en 3 sitios
por aislamiento de deploy (cada servicio mantiene su lib mínima sin cross-imports):
  · services/ai-orchestrator/orchestrator.py
  · services/api/routers/meli_webhook.py
  · services/api/routers/data_subject_request.py

Alimenta `consent_audit_log.phone_hash` (Habeas Data Ley 1581) para lookup
post-anonimización. Si una copia DRIFTEA (o alguien cambia el algoritmo en una sola),
los hashes dejan de coincidir → lookups rotos + registros de consent inconsistentes
(la clase de bug que el audit señaló). NO se migran a un helper compartido porque
cambiar el algoritmo rompería los hashes YA almacenados; en su lugar este test:
  (1) asegura que las 3 copias producen output IDÉNTICO (previene drift entre ellas);
  (2) fija el hash de un input conocido (golden) → un cambio de ALGORITMO en las 3 a
      la vez (que rompería los lookups de hashes viejos) también se caza.
"""
import hashlib
import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_LEGACY_HASH_PHONE_FILES = {
    "orchestrator": _REPO / "services/ai-orchestrator/orchestrator.py",
    "meli_webhook": _REPO / "services/api/routers/meli_webhook.py",
    "data_subject_request": _REPO / "services/api/routers/data_subject_request.py",
}

_INPUTS = [
    "+573125835649",
    "573125835649",
    "+57 312 583 5649",
    "+57-312-583-5649",
    "  573125835649  ",
    "",
    None,
]


def _load_hash_phone(path: Path):
    """Extrae y compila SOLO la función _hash_phone del archivo (sin importar el
    módulo entero, que arrastra deps pesadas)."""
    src = path.read_text()
    m = re.search(r"(def _hash_phone\(.*?(?=\n(?:def |async def |class |@)))", src, re.S)
    if not m:
        raise AssertionError(f"_hash_phone no encontrado en {path}")
    ns: dict = {}
    exec("import hashlib, re\nfrom typing import Optional\n" + m.group(1), ns)
    return ns["_hash_phone"]


class HashPhoneParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.impls = {n: _load_hash_phone(p) for n, p in _LEGACY_HASH_PHONE_FILES.items()}

    def test_all_three_copies_present(self):
        self.assertEqual(len(self.impls), 3)

    def test_copies_produce_identical_output(self):
        # El corazón del test: las 3 copias deben coincidir para CADA input; si una
        # driftea, este assert falla nombrando el input divergente.
        for inp in _INPUTS:
            outs = {n: fn(inp) for n, fn in self.impls.items()}
            distinct = set(outs.values())
            self.assertEqual(
                len(distinct), 1,
                f"DRIFT en _hash_phone para input={inp!r}: {outs}",
            )

    def test_golden_hash_stable(self):
        # Fija el algoritmo: un input conocido → hash conocido. Si alguien cambia el
        # algoritmo en las 3 copias a la vez (rompiendo lookups de hashes ya
        # almacenados en consent_audit_log), este golden lo caza.
        expected = hashlib.sha256("573125835649".encode()).hexdigest()
        for name, fn in self.impls.items():
            self.assertEqual(fn("+57 312 583 5649"), expected, f"{name} cambió el algoritmo")
            self.assertEqual(fn("573125835649"), expected, f"{name} cambió el algoritmo")

    def test_none_and_empty_return_none(self):
        for name, fn in self.impls.items():
            self.assertIsNone(fn(None), name)
            self.assertIsNone(fn(""), name)


if __name__ == "__main__":
    unittest.main()

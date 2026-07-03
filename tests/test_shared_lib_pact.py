"""Pact test — libs compartidas byte-idénticas entre `services/api/lib/` y
`services/ai-orchestrator/lib/`.

Estos módulos son COPIAS COMPLETAS (no wrappers sys.path como coupons.py). No
hay mecanismo de import que garantice que ambas copias coincidan, así que este
test falla si divergen. Cualquier edición a una copia DEBE replicarse en la otra.

F35 (audit fullstack-review-2026-07-03): carrier_capabilities.py y
tenant_payment_methods.py habían drifteado textualmente (orden de import + línea
en blanco) sin ningún test que lo detectara. Este pact cierra ese gap.

Patrón calcado de tests/test_phone_helpers_pact.py (hash byte-a-byte).
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_LIB = REPO_ROOT / "services" / "api" / "lib"
ORCH_LIB = REPO_ROOT / "services" / "ai-orchestrator" / "lib"

# Archivos que DEBEN ser byte-idénticos entre ambos servicios.
# NO incluir coupons.py (orch es wrapper sys.path, no copia) ni phone.py
# (ya cubierto por test_phone_helpers_pact.py, e incluye connector-whatsapp).
SHARED = [
    "carrier_capabilities.py",
    "tenant_payment_methods.py",
    "dane_resolver.py",
    "tenant_carriers.py",
]


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class SharedLibPactTests(unittest.TestCase):
    def test_shared_libs_byte_identical(self):
        for fname in SHARED:
            with self.subTest(lib=fname):
                api_f = API_LIB / fname
                orch_f = ORCH_LIB / fname
                self.assertTrue(api_f.exists(), f"falta {api_f}")
                self.assertTrue(orch_f.exists(), f"falta {orch_f}")
                h_api = _sha256(api_f)
                h_orch = _sha256(orch_f)
                self.assertEqual(
                    h_api, h_orch,
                    f"{fname} difiere entre api y orchestrator "
                    f"(api={h_api[:8]} orch={h_orch[:8]}). "
                    f"Toda edición a una copia debe replicarse en la otra.",
                )


if __name__ == "__main__":
    unittest.main()

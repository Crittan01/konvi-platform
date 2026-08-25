"""Pact test — `konvi_domain` es la única fuente del motor de cupones (M2.0).

Tras la extracción a `packages/shared-py/`, los módulos `lib/coupons.py` de
`services/api` y `services/ai-orchestrator` son SHIMS que re-exportan la API
pública del paquete. Este test falla si:
  1. Un shim deja de re-exportar un símbolo público del paquete (drift).
  2. Reaparece el sys.path hack en el orchestrator (la deuda que M2.0 cerró).
  3. El paquete deja de ser importable / cambia su API pública de cupones.

Patrón calcado de tests/test_shared_lib_pact.py.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import konvi_domain.coupons as pkg

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIMS = [
    REPO_ROOT / "services" / "api" / "lib" / "coupons.py",
    REPO_ROOT / "services" / "ai-orchestrator" / "lib" / "coupons.py",
]

# API pública canónica del motor ADR-0015 (la que consumen orders.py,
# cart_tool.py y dispatcher.py).
PUBLIC_API = [
    "DISCOUNT_TYPE_PERCENT",
    "DISCOUNT_TYPE_FIXED",
    "DISCOUNT_TYPE_FREE_SHIPPING",
    "VALID_DISCOUNT_TYPES",
    "REDEMPTION_STATUS_APPLIED",
    "REDEMPTION_STATUS_CONSUMED",
    "REDEMPTION_STATUS_REVOKED",
    "ValidationResult",
    "ApplyResult",
    "validate_coupon_applicable",
    "compute_discount",
    "apply_coupon",
    "revoke_coupon",
    "consume_redemption",
]


def _load_shim(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class KonviDomainPactTests(unittest.TestCase):
    def test_package_exposes_canonical_api(self):
        for symbol in PUBLIC_API:
            with self.subTest(symbol=symbol):
                self.assertTrue(
                    hasattr(pkg, symbol),
                    f"konvi_domain.coupons ya no expone {symbol} — rompe los shims",
                )

    def test_shims_reexport_package_identity(self):
        """Cada shim re-exporta los MISMOS objetos del paquete (no copias)."""
        for shim_path in SHIMS:
            # str(): xdist no puede serializar PosixPath en parámetros de subTest.
            with self.subTest(shim=str(shim_path)):
                self.assertTrue(shim_path.exists(), f"falta {shim_path}")
                mod = _load_shim(shim_path, f"_shim_{shim_path.parts[-3]}")
                for symbol in PUBLIC_API:
                    self.assertTrue(
                        hasattr(mod, symbol),
                        f"{shim_path} no re-exporta {symbol}",
                    )
                    self.assertIs(
                        getattr(mod, symbol),
                        getattr(pkg, symbol),
                        f"{shim_path}:{symbol} no es el objeto del paquete (drift)",
                    )

    def test_no_syspath_hack_remains(self):
        """El sys.path hack que M2.0 cerró no reaparece en ningún shim (guarda
        sobre CÓDIGO — el docstring puede mencionar `sys.path` históricamente)."""
        for shim_path in SHIMS:
            with self.subTest(shim=str(shim_path)):
                src = shim_path.read_text()
                for hack in ("sys.path.insert", "sys.path.append", "sys.path.remove"):
                    self.assertNotIn(
                        hack,
                        src,
                        f"{shim_path} reintrodujo manipulación de sys.path ({hack}) — "
                        f"la deuda cerrada en M2.0 (usar el paquete instalado)",
                    )

    def test_package_import_is_side_effect_free(self):
        """Importar el paquete raíz no levanta clientes pesados (M3 lo importa
        para leer contratos sin efectos colaterales). En intérprete LIMPIO —
        en este proceso la suite ya pudo importar supabase/httpx por otros tests."""
        import subprocess

        code = (
            "import sys; import konvi_domain; "
            "heavy = [m for m in ('supabase', 'httpx', 'fastapi', 'google.genai') "
            "if m in sys.modules]; "
            "sys.exit(1 if heavy else 0)"
        )
        rc = subprocess.run([sys.executable, "-c", code], check=False).returncode
        self.assertEqual(rc, 0, "import konvi_domain cargó un cliente pesado — debe ser liviano")


if __name__ == "__main__":
    unittest.main()

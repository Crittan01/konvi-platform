"""Test estructural del contrato de domain services (Track 5 M2 — D2).

Verifica que TODO contrato registrado en `konvi_domain` cumple las reglas
declarativas (criterio de aceptación §7.4 de
docs/architecture/domain-services-contract.md):

  1. Nombres `{dominio}.{verbo}` únicos.
  2. Escritura (idempotency != read_only) exige: rbac no vacío + estrategia de
     idempotencia canónica + ≥1 evento + ≥1 error tipado.
  3. `implemented=True` exige que `service_fn` exista en el service module real.
  4. `customer_facing=True` exige audience con "customer".
  5. Los contratos se importan sin efectos colaterales (subproceso limpio).

Se registra un contrato por dominio aquí (lista CONTRACTS) a medida que los
dominios entran al backlog M2+.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import unittest

from konvi_domain.contract import IDEMPOTENCY_STRATEGIES, DomainContract
from konvi_domain.orders.contract import ORDERS_CONTRACT

CONTRACTS: list[DomainContract] = [ORDERS_CONTRACT]

# dominio → módulo de servicio donde deben vivir los service_fn.
SERVICE_MODULES = {
    "orders": "konvi_domain.orders.service",
}


class DomainContractStructuralTests(unittest.TestCase):
    def test_nombres_unicos_y_prefijados_por_dominio(self):
        for contract in CONTRACTS:
            names = [op.name for op in contract.operations]
            with self.subTest(domain=contract.domain):
                self.assertEqual(len(names), len(set(names)), f"duplicados en {names}")
                for name in names:
                    self.assertTrue(
                        name.startswith(f"{contract.domain}.") or name.startswith("payments."),
                        f"{name} no lleva el prefijo de su dominio",
                    )

    def test_escritura_exige_rbac_idempotencia_eventos_errores(self):
        for contract in CONTRACTS:
            for op in contract.operations:
                with self.subTest(op=op.name):
                    if op.idempotency == "read_only":
                        continue
                    self.assertIn(
                        op.idempotency, IDEMPOTENCY_STRATEGIES,
                        f"{op.name}: estrategia desconocida {op.idempotency}",
                    )
                    self.assertTrue(op.rbac, f"{op.name}: escritura sin rbac declarado")
                    self.assertTrue(
                        op.events, f"{op.name}: escritura sin eventos — contrato inválido",
                    )
                    self.assertTrue(op.errors, f"{op.name}: sin catálogo de errores")

    def test_implemented_exige_service_fn_real(self):
        for contract in CONTRACTS:
            module = importlib.import_module(SERVICE_MODULES[contract.domain])
            for op in contract.operations:
                if not op.implemented:
                    continue
                with self.subTest(op=op.name):
                    self.assertTrue(
                        callable(getattr(module, op.service_fn, None)),
                        f"{op.name}: implemented=True pero {op.service_fn} no existe en {SERVICE_MODULES[contract.domain]}",
                    )

    def test_customer_facing_exige_audience_customer(self):
        for contract in CONTRACTS:
            for op in contract.operations:
                if op.customer_facing:
                    with self.subTest(op=op.name):
                        self.assertIn("customer", op.audience)

    def test_contratos_se_importan_sin_efectos_colaterales(self):
        """Leer contratos (M3) no levanta clientes de DB ni HTTP."""
        code = (
            "import sys; from konvi_domain.orders.contract import ORDERS_CONTRACT; "
            "heavy = [m for m in ('supabase', 'httpx', 'fastapi') if m in sys.modules]; "
            "sys.exit(1 if heavy else 0)"
        )
        rc = subprocess.run([sys.executable, "-c", code], check=False).returncode
        self.assertEqual(rc, 0, "importar el contrato cargó un cliente pesado")


if __name__ == "__main__":
    unittest.main()

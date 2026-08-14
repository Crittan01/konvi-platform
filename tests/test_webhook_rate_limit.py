"""Tests del TokenBucket rate-limiter — la parte VIVA de lib/webhook_framework.

G14 (2026-08-13): la ABC WebhookHandler + signature.py + idempotency.py se
retiraron por 0 adopción (los 4 webhooks vivos son ad-hoc con hardening propio
verificado). Lo que queda con adopción real es rate_limit.py + errors.py,
consumidos por lib/integration_client/base.py — estos tests cubren eso.
(Hereda las clases TokenBucket* del retirado test_webhook_framework.py.)
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FW_PATH = REPO_ROOT / "services" / "api" / "lib" / "webhook_framework"


def _load_module(name: str, file_path: Path):
    """Carga un módulo aislado del paquete (patrón importlib del repo)."""
    pkg_name = "_test_webhook_framework"
    if pkg_name not in sys.modules:
        pkg_init = FW_PATH / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            pkg_name,
            pkg_init,
            submodule_search_locations=[str(FW_PATH)],
        )
        pkg_mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = pkg_mod
        # NO ejecutar __init__ aún para evitar imports relativos.

    full_name = f"{pkg_name}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


errors = _load_module("errors", FW_PATH / "errors.py")
rate_limit = _load_module("rate_limit", FW_PATH / "rate_limit.py")


class TokenBucketRuleTests(unittest.TestCase):
    def test_capacity_no_positiva_levanta(self):
        with self.assertRaises(ValueError):
            rate_limit.TokenBucketRule(capacity=0, refill_per_sec=1)

    def test_refill_no_positivo_levanta(self):
        with self.assertRaises(ValueError):
            rate_limit.TokenBucketRule(capacity=10, refill_per_sec=0)


class TokenBucketLimiterTests(unittest.TestCase):
    def setUp(self):
        self.limiter = rate_limit.TokenBucketLimiter()
        self.rule = rate_limit.TokenBucketRule(
            capacity=5, refill_per_sec=2.0
        )

    def test_consume_dentro_de_capacidad_ok(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        # 5to consumo OK (capacity=5).

    def test_consume_excediendo_levanta(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        with self.assertRaises(errors.RateLimitExceededError) as ctx:
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        self.assertGreaterEqual(ctx.exception.retry_after_seconds, 1)

    def test_buckets_independientes_per_tenant(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        # Tenant B no debe verse afectado.
        self.limiter.consume(
            tenant_id="B", integration="aveonline", rule=self.rule
        )

    def test_buckets_independientes_per_integration(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        # Mismo tenant otra integración → bucket separado.
        self.limiter.consume(
            tenant_id="A", integration="meta", rule=self.rule
        )

    def test_get_remaining_lee_sin_consumir(self):
        for _ in range(3):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        remaining = self.limiter.get_remaining(
            tenant_id="A", integration="aveonline", rule=self.rule
        )
        self.assertLessEqual(remaining, 2.5)
        self.assertGreaterEqual(remaining, 1.5)

    def test_reset_borra_buckets(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        self.limiter.reset(tenant_id="A")
        # Tras reset, A vuelve a tener capacidad full.
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )


if __name__ == "__main__":
    unittest.main()

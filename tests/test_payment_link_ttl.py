"""Divergencia TTL payment link (auditoría 2026-08-02) — una sola fuente.

Antes: `orders.py:76` hardcodeaba `WOMPI_PAYMENT_LINK_TTL_MINUTES = 30`
(creación del link) mientras `wompi_webhook.py:40` leía el env
`WOMPI_PAYMENT_LINK_TTL_MINUTES` (regeneración post-pago fallido) → un override
del env solo aplicaba a la mitad de los links generados.

Fix: helper único `integrations.wompi_client.payment_link_ttl_minutes()` que lee
el env en cada llamada (default 30, fail-safe ante valores inválidos). Ambos
routers lo usan en el punto de uso.

Cubiertas: default sin env, override válido, inválido/<1 → default con warning,
y el cableado de AMBOS routers al helper (regresión anti-divergencia).
"""
import inspect
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from integrations.wompi_client import (  # noqa: E402
    DEFAULT_PAYMENT_LINK_TTL_MINUTES,
    payment_link_ttl_minutes,
)


class PaymentLinkTtlHelperTests(unittest.TestCase):
    def test_default_sin_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WOMPI_PAYMENT_LINK_TTL_MINUTES", None)
            self.assertEqual(payment_link_ttl_minutes(), 30)
            self.assertEqual(DEFAULT_PAYMENT_LINK_TTL_MINUTES, 30)

    def test_override_env_valido(self):
        with patch.dict(os.environ, {"WOMPI_PAYMENT_LINK_TTL_MINUTES": "45"}):
            self.assertEqual(payment_link_ttl_minutes(), 45)

    def test_env_invalido_cae_al_default(self):
        with patch.dict(os.environ, {"WOMPI_PAYMENT_LINK_TTL_MINUTES": "abc"}):
            self.assertEqual(payment_link_ttl_minutes(), 30)

    def test_env_menor_que_1_cae_al_default(self):
        for bad in ("0", "-5"):
            with self.subTest(bad=bad), \
                 patch.dict(os.environ, {"WOMPI_PAYMENT_LINK_TTL_MINUTES": bad}):
                self.assertEqual(payment_link_ttl_minutes(), 30)


class PaymentLinkTtlWiringTests(unittest.TestCase):
    """Anti-divergencia: creación (orders) y regeneración (wompi_webhook) deben
    resolver el TTL via el MISMO helper en el punto de uso."""

    def test_orders_usa_el_helper(self):
        from routers import orders
        src = inspect.getsource(orders.create_payment_link)
        self.assertIn("payment_link_ttl_minutes()", src)

    def test_wompi_webhook_usa_el_helper(self):
        from routers import wompi_webhook
        src = inspect.getsource(wompi_webhook._maybe_offer_payment_retry)
        self.assertIn("payment_link_ttl_minutes()", src)

    def test_orders_ya_no_hardcodea_el_ttl(self):
        from routers import orders
        src = inspect.getsource(orders)
        self.assertNotIn("WOMPI_PAYMENT_LINK_TTL_MINUTES = 30", src)
        self.assertNotIn("WOMPI_PAYMENT_LINK_TTL_MINUTES = int(", src)


if __name__ == "__main__":
    unittest.main()

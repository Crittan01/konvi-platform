"""TTL del payment link — UNA fuente en el paquete compartido (Track 5 M2.3).

Historia: `orders.py:76` hardcodeaba `WOMPI_PAYMENT_LINK_TTL_MINUTES = 30`
(creación del link) mientras `wompi_webhook.py:40` leía el env
`WOMPI_PAYMENT_LINK_TTL_MINUTES` (regeneración post-pago fallido) → un override
del env solo aplicaba a la mitad de los links generados (auditoría 2026-08-02).

Fix 2026-08-02: helper único. Fix M2.3 (2026-08-25): la política migra al
paquete `konvi_domain.orders.payments` (colapsa el espejo router↔bot de M1
§3.3); `integrations/wompi_client` queda como SHIM que re-exporta los símbolos
para sus consumidores (wompi_webhook.py:29, este test).

Cubiertas: default sin env, override válido, inválido/<1 → default con warning,
identidad shim↔paquete, cableado del webhook al helper y alarma de drift
bot↔paquete (la constante congelada del bot debe seguir igualando el TTL
vigente con env limpio — si alguien setea el env en un ambiente, revienta aquí).
"""
import inspect
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import konvi_domain.orders.payments as pkg_payments  # noqa: E402
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
    """Anti-divergencia: el shim del API es el paquete (misma identidad), la
    regeneración (wompi_webhook) resuelve el TTL via el helper en el punto de
    uso, y la constante congelada del bot sigue igualando la política vigente."""

    def test_shim_reexporta_el_paquete(self):
        """(a) identidad shim↔paquete — la única fuente es konvi_domain."""
        self.assertIs(payment_link_ttl_minutes, pkg_payments.payment_link_ttl_minutes)
        self.assertIs(
            DEFAULT_PAYMENT_LINK_TTL_MINUTES,
            pkg_payments.DEFAULT_PAYMENT_LINK_TTL_MINUTES,
        )

    def test_wompi_webhook_usa_el_helper(self):
        """(b) la regeneración post-pago fallido sigue cableada al helper."""
        from routers import wompi_webhook
        src = inspect.getsource(wompi_webhook._maybe_offer_payment_retry)
        self.assertIn("payment_link_ttl_minutes()", src)

    def test_ttl_bot_espeja_al_paquete_con_env_limpio(self):
        """(c) alarma de drift bot↔paquete: el env NO está seteado en
        render.yaml ni .env.local — ambos canales deben operar con 30. Si
        alguien setea WOMPI_PAYMENT_LINK_TTL_MINUTES en un ambiente, el bucket
        guard del bot (constante congelada) diverge del expires_at real."""
        from tools.payment_link_tool import WOMPI_LINK_TTL_MINUTES
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WOMPI_PAYMENT_LINK_TTL_MINUTES", None)
            self.assertEqual(WOMPI_LINK_TTL_MINUTES, payment_link_ttl_minutes())

    def test_orders_ya_no_hardcodea_el_ttl(self):
        from routers import orders
        src = inspect.getsource(orders)
        self.assertNotIn("WOMPI_PAYMENT_LINK_TTL_MINUTES = 30", src)
        self.assertNotIn("WOMPI_PAYMENT_LINK_TTL_MINUTES = int(", src)


if __name__ == "__main__":
    unittest.main()

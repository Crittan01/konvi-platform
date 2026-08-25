"""Paridad de POLÍTICA payment-link bot↔paquete (Track 5 M2.3 — contrato §6.3).

El bot conserva su espejo CONGELADO (`services/ai-orchestrator/tools/
payment_link_tool.py`) hasta el bloque bot (B-2/M3 lo adopta del paquete).
Mientras tanto la duplicación time-boxed tiene ALARMA: este test falla si la
política del paquete (`konvi_domain.orders.payments`) diverge de la del bot.

  • TTL: `WOMPI_LINK_TTL_MINUTES` (bot) == `payment_link_ttl_minutes()`
    (paquete) con env limpio — hoy ambos 30; el env NO está seteado en
    render.yaml ni .env.local → drift real si alguien lo setea.
  • Reuso: mismas filas staged → la decisión `active_link` del bot
    (`_find_pending_order`) == `find_reusable_payment_link` (paquete):
    link vigente / expirado / sin checkout_url / sin filas.
  • La query de payments del paquete produce los mismos filtros
    (eq tenant/order/status + gte created_at) que la del bot.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from konvi_domain.orders.payments import (  # noqa: E402
    find_reusable_payment_link,
    payment_link_ttl_minutes,
)

# Espejo congelado del BOT (baseline de la paridad — NO se toca hasta B-2/M3).
from tools.payment_link_tool import (  # noqa: E402
    WOMPI_LINK_TTL_MINUTES,
    _find_pending_order,
)


# ─── Supabase falso con filtros eq + gte aplicados de verdad ─────────────────
# (el caso "link expirado" se ejerce por el filtro, no por staging vacío).


class _Q:
    def __init__(self, sb, table):
        self._sb, self._table, self._filters = sb, table, []

    def select(self, *a, **k):
        return self

    def eq(self, c, v):
        self._filters.append(("eq", c, v))
        return self

    def gte(self, c, v):
        self._filters.append(("gte", c, v))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        rows = [dict(r) for r in self._sb.tables.get(self._table, [])]
        for op, c, v in self._filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            elif op == "gte":
                # ISO 8601 con el mismo offset compara lexicográficamente.
                rows = [r for r in rows if str(r.get(c) or "") >= str(v)]
        self._sb.queries.append((self._table, list(self._filters)))
        return SimpleNamespace(data=rows)


class _Sb:
    def __init__(self, tables):
        self.tables = tables
        self.queries = []

    def table(self, name):
        return _Q(self, name)


def _stage(payment_rows):
    """DB staged: una orden pending_payment de la conversación + los payments
    del escenario."""
    return _Sb({
        "orders": [{
            "id": "order-1",
            "tenant_id": "t1",
            "conversation_id": "conv-1",
            "status": "pending_payment",
            "total_amount": 2000.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }],
        "payments": payment_rows,
    })


def _payment_row(*, minutes_old, checkout_url="https://checkout.wompi.co/l/x"):
    return {
        "tenant_id": "t1",
        "order_id": "order-1",
        "status": "pending",
        "checkout_url": checkout_url,
        "wompi_link_id": "plink-x",
        "amount_in_cents": 200_000,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
        ).isoformat(),
    }


class TtlParityTests(unittest.TestCase):
    def test_ttl_bot_espeja_paquete_con_env_limpio(self):
        """La constante congelada del bot (bucket guard a/b) debe seguir
        igualando el TTL vigente de la política (expires_at real)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WOMPI_PAYMENT_LINK_TTL_MINUTES", None)
            self.assertEqual(WOMPI_LINK_TTL_MINUTES, payment_link_ttl_minutes())


class ReuseParityTests(unittest.TestCase):
    """Misma DB staged → la decisión de reuso del bot == la del paquete."""

    def _decisions(self, sb):
        bot = _find_pending_order(sb, tenant_id="t1", conversation_id="conv-1")
        pkg = find_reusable_payment_link(sb, tenant_id="t1", order_id="order-1")
        return bot, pkg

    def test_link_vigente_ambos_reusan_el_mismo(self):
        sb = _stage([_payment_row(minutes_old=5)])
        bot, pkg = self._decisions(sb)
        self.assertIsNotNone(bot)
        self.assertIsNotNone(bot["active_link"])
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg["checkout_url"], bot["active_link"]["checkout_url"])
        self.assertEqual(
            int(pkg.get("amount_in_cents") or 0),
            bot["active_link"]["amount_in_cents"],
        )

    def test_link_expirado_ambos_descartan(self):
        """45 min > TTL 30: el filtro gte(cutoff) la excluye en AMBOS."""
        sb = _stage([_payment_row(minutes_old=45)])
        bot, pkg = self._decisions(sb)
        self.assertIsNotNone(bot)  # la orden existe; lo que no hay es link
        self.assertIsNone(bot["active_link"])
        self.assertIsNone(pkg)

    def test_link_sin_checkout_url_ambos_descartan(self):
        sb = _stage([_payment_row(minutes_old=5, checkout_url="")])
        bot, pkg = self._decisions(sb)
        self.assertIsNone(bot["active_link"])
        self.assertIsNone(pkg)

    def test_sin_filas_ambos_descartan(self):
        sb = _stage([])
        bot, pkg = self._decisions(sb)
        self.assertIsNone(bot["active_link"])
        self.assertIsNone(pkg)

    def test_query_payments_mismos_filtros(self):
        """La query del paquete es la del bot: eq tenant/order/status=pending
        + exactamente un gte sobre created_at (el cutoff del TTL)."""
        sb = _stage([_payment_row(minutes_old=5)])
        self._decisions(sb)
        payments_queries = [f for t, f in sb.queries if t == "payments"]
        self.assertEqual(len(payments_queries), 2)  # bot + paquete
        eq_sets = [
            {(c, v) for op, c, v in filters if op == "eq"}
            for filters in payments_queries
        ]
        self.assertEqual(eq_sets[0], eq_sets[1])
        self.assertEqual(
            eq_sets[0],
            {("tenant_id", "t1"), ("order_id", "order-1"), ("status", "pending")},
        )
        for filters in payments_queries:
            gtes = [(c,) for op, c, _v in filters if op == "gte"]
            self.assertEqual(gtes, [("created_at",)])


if __name__ == "__main__":
    unittest.main()

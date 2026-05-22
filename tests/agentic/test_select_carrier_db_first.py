"""Tests SelectCarrierTool — DB-first resolution de rate_id.

Rev. 106 — fix bug `RATE_ID_NOT_CACHED` (conv 2eb3bb48, 2026-05-22):
las quoted_options ahora viven en `cart.shipping_meta.quoted_options`
(DB-first, Plan A.0.2). El tool resuelve rate_id:
  1. DB primero (cross-path legacy↔agentic + sobrevive turns).
  2. ctx.extras fallback (cache del mismo turn).
  3. Si no resuelve, tool_failure con código RATE_ID_NOT_FOUND + lista
     de opciones reales disponibles (LLM no debe inventar).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

# Registrar tools (necesario antes de importar shipping tools).
import agentic.tools.cart  # noqa: F401
import agentic.tools.shipping  # noqa: F401

from agentic.tools.registry import get_tool
from agentic.tools.base import ToolContext


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_supabase_with_quoted_options(options: list[dict]):
    """Mock supabase que retorna shipping_meta.quoted_options."""
    sb = MagicMock()
    cart_data = {
        "shipping_meta": {"quoted_options": options},
    }

    def table_side(name):
        chain = MagicMock()
        if name == "conversation_carts":
            chain.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=cart_data)
        return chain

    sb.table.side_effect = table_side
    return sb


class SelectCarrierDBFirstTests(unittest.TestCase):

    def setUp(self):
        self.tool = get_tool("select_carrier")
        self.assertIsNotNone(self.tool, "select_carrier tool no registrado")

    def test_db_options_resuelven_rate_id_sin_ctx_extras(self):
        """Caso runtime conv 2eb3bb48: legacy cotizó (DB tiene options),
        agentic turn siguiente selecciona. ctx.extras está vacío (turn nuevo).
        """
        options_in_db = [
            {
                "rate_id": "envia-coordinadora-eco",
                "carrier": "Coordinadora",
                "service_level": "Económica",
                "price_cents": 1641000,
                "eta_date": "2026-06-01",
                "currency": "COP",
            },
            {
                "rate_id": "envia-tcc-rapida",
                "carrier": "TCC",
                "service_level": "Rápida",
                "price_cents": 7115000,
                "eta_date": "2026-05-23",
                "currency": "COP",
            },
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)

        # Simular select_carrier_for_cart legacy adapter retornando éxito.
        import agentic.legacy_adapters as la
        original = la.select_carrier_for_cart

        async def fake_select_carrier_for_cart(supabase, **kw):
            return {
                "ok": True,
                "carrier": kw["rate_data"]["carrier"],
                "service_level": kw["rate_data"]["service_level"],
                "shipping_cents": kw["rate_data"]["price_cents"],
                "total_cents": kw["rate_data"]["price_cents"] + 100000,
            }

        la.select_carrier_for_cart = fake_select_carrier_for_cart
        try:
            ctx = ToolContext(
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=sb, extras={},  # ← EXTRAS VACÍO (turn nuevo).
            )
            args = self.tool.args_schema(rate_id="envia-coordinadora-eco")
            result = _run(self.tool.execute(args, ctx))
        finally:
            la.select_carrier_for_cart = original

        self.assertTrue(result.success, f"Falló: {result.data}")
        self.assertEqual(result.data["carrier"], "Coordinadora")
        self.assertEqual(result.data["service_level"], "Económica")

    def test_rate_id_inventado_no_encuentra_devuelve_opciones_reales(self):
        """LLM inventó 'fedex-ground' (caso real). Tool retorna
        RATE_ID_NOT_FOUND + lista de rate_ids reales para que el LLM
        recomponga sin inventar otra vez."""
        options_in_db = [
            {
                "rate_id": "envia-coordinadora-eco",
                "carrier": "Coordinadora",
                "service_level": "Económica",
                "price_cents": 1641000,
            },
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)

        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb, extras={},
        )
        args = self.tool.args_schema(rate_id="fedex-ground")
        result = _run(self.tool.execute(args, ctx))

        self.assertFalse(result.success)
        self.assertEqual(result.data["code"], "RATE_ID_NOT_FOUND")
        # available_options está en data para que el LLM no invente.
        self.assertIn("available_options", result.data)
        self.assertEqual(len(result.data["available_options"]), 1)
        self.assertEqual(
            result.data["available_options"][0]["rate_id"],
            "envia-coordinadora-eco",
        )

    def test_no_options_en_db_ni_ctx_devuelve_not_found(self):
        """Sin options en DB ni ctx → error con lista vacía."""
        sb = _mock_supabase_with_quoted_options([])
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb, extras={},
        )
        args = self.tool.args_schema(rate_id="any")
        result = _run(self.tool.execute(args, ctx))

        self.assertFalse(result.success)
        self.assertEqual(result.data["code"], "RATE_ID_NOT_FOUND")

    def test_ctx_extras_fallback_si_db_no_disponible(self):
        """Si DB read falla, ctx.extras debe servir como cache de respaldo."""
        sb = MagicMock()
        sb.table.side_effect = Exception("DB unreachable")

        ctx_options = [
            {
                "rate_id": "envia-coordinadora-eco",
                "carrier": "Coordinadora",
                "service_level": "Económica",
                "price_cents": 1641000,
            },
        ]

        import agentic.legacy_adapters as la
        original = la.select_carrier_for_cart

        async def fake_select(supabase, **kw):
            return {
                "ok": True, "carrier": "Coordinadora",
                "service_level": "Económica",
                "shipping_cents": 1641000, "total_cents": 1741000,
            }

        la.select_carrier_for_cart = fake_select
        try:
            ctx = ToolContext(
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=sb, extras={"_last_quote_options": ctx_options},
            )
            args = self.tool.args_schema(rate_id="envia-coordinadora-eco")
            result = _run(self.tool.execute(args, ctx))
        finally:
            la.select_carrier_for_cart = original

        self.assertTrue(result.success, f"Falló: {result.data}")


if __name__ == "__main__":
    unittest.main()

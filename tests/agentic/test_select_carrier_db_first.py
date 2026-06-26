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
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
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


def _mock_supabase_with_selected_carrier(*, carrier, rate_id,
                                         shipping_cents=900000, total_cents=4800000):
    """Mock supabase con un carrier YA SELECCIONADO persistido en shipping_meta."""
    sb = MagicMock()
    cart_data = {
        "shipping_meta": {
            "carrier": carrier,
            "rate_id": rate_id,
            "service_level": "Estándar",
            "quoted_options": [{"rate_id": rate_id, "carrier": carrier}],
        },
        "shipping_cents": shipping_cents,
        "total_cents": total_cents,
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
        agentic turn siguiente selecciona.

        Rev. 108 update — guardrail anti-auto-select: con >1 opción,
        cliente DEBE haber mencionado el carrier en últimos inbounds.
        Test pasa 'Coordinadora' en recent_inbound_texts.
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
                supabase=sb,
                extras={
                    # Rev. 108 — cliente mencionó "Coordinadora" en inbound previo.
                    "recent_inbound_texts": ["Coordinadora me parece bien"],
                },
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

    def test_fuzzy_match_carrier_name_resuelve_rate_id_inventado(self):
        """Caso runtime founder (conv 73e26cbe): LLM inventó rate_id
        'd02fca25-e7cc-4214-b006-214376b63cfe' (UUID random) cuando el
        cliente dijo 'Por transportadora Envia'. Fuzzy match por carrier
        name debe resolverlo a rate_id='29' (ENVIA real)."""
        options_in_db = [
            {"rate_id": "1009", "carrier": "COORDINADORA MERCANTIL",
             "service_level": "Mensajeria", "price_cents": 1593000},
            {"rate_id": "29", "carrier": "ENVIA",
             "service_level": "Mensajeria", "price_cents": 1650000},
            {"rate_id": "33", "carrier": "SERVIENTREGA",
             "service_level": "Mensajeria", "price_cents": 1795000},
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)

        import agentic.legacy_adapters as la
        original = la.select_carrier_for_cart
        captured = {}

        async def fake_select(supabase, **kw):
            captured["rate_id"] = kw["rate_id"]
            captured["carrier"] = kw["rate_data"]["carrier"]
            return {
                "ok": True, "carrier": kw["rate_data"]["carrier"],
                "service_level": kw["rate_data"]["service_level"],
                "shipping_cents": kw["rate_data"]["price_cents"],
                "total_cents": kw["rate_data"]["price_cents"] + 100000,
            }

        la.select_carrier_for_cart = fake_select
        try:
            from unittest.mock import MagicMock
            ctx = ToolContext(
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=sb,
                extras={
                    # Rev. 108 — cliente mencionó "Envia" explícitamente.
                    "recent_inbound_texts": ["Por transportadora Envia"],
                },
                logger=MagicMock(),
            )
            # LLM inventó nombre que contiene 'envia'.
            args = self.tool.args_schema(rate_id="envia_medellin_rate_id")
            result = _run(self.tool.execute(args, ctx))
        finally:
            la.select_carrier_for_cart = original

        self.assertTrue(result.success,
                        f"Fuzzy match debe resolver: {result.data}")
        # Match correcto: ENVIA con rate_id real '29'.
        self.assertEqual(captured["carrier"], "ENVIA")
        self.assertEqual(captured["rate_id"], "29")

    def test_fuzzy_match_no_matchea_si_carrier_distinto(self):
        """Si LLM inventa rate_id sin match por carrier (e.g. 'fedex-ground'
        y solo hay Coordinadora) → seguir devolviendo RATE_ID_NOT_FOUND."""
        options_in_db = [
            {"rate_id": "1009", "carrier": "COORDINADORA MERCANTIL",
             "service_level": "Mensajeria", "price_cents": 1593000},
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)
        from unittest.mock import MagicMock
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb, extras={}, logger=MagicMock(),
        )
        args = self.tool.args_schema(rate_id="fedex-ground")
        result = _run(self.tool.execute(args, ctx))

        self.assertFalse(result.success)
        self.assertEqual(result.data["code"], "RATE_ID_NOT_FOUND")

    def test_fuzzy_match_normaliza_separadores_underscore_vs_espacio(self):
        """Caso runtime founder (conv 146fe9ec, 2026-05-22 23:26):
        LLM pasó 'rate_coordinadora_mercantil' (con underscores) pero
        carrier real es 'COORDINADORA MERCANTIL' (con espacio). Mi fuzzy
        match v1 falló por mismatch de separadores. Fix v2: normalizar
        ambos lados (colapsar espacios/guiones/underscores) antes de
        comparar substring.
        """
        options_in_db = [
            {"rate_id": "1009", "carrier": "COORDINADORA MERCANTIL",
             "service_level": "Mensajeria", "price_cents": 1593000},
            {"rate_id": "29", "carrier": "ENVIA",
             "service_level": "Mensajeria", "price_cents": 1650000},
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)

        import agentic.legacy_adapters as la
        original = la.select_carrier_for_cart
        captured = {}

        async def fake_select(supabase, **kw):
            captured["rate_id"] = kw["rate_id"]
            captured["carrier"] = kw["rate_data"]["carrier"]
            return {"ok": True, "carrier": kw["rate_data"]["carrier"],
                    "service_level": "M", "shipping_cents": 1593000,
                    "total_cents": 1593000}

        la.select_carrier_for_cart = fake_select
        try:
            from unittest.mock import MagicMock
            ctx = ToolContext(
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=sb,
                extras={
                    # Rev. 108 — cliente mencionó "Coordinadora" explícitamente.
                    "recent_inbound_texts": ["Coordinadora por favor"],
                },
                logger=MagicMock(),
            )
            args = self.tool.args_schema(rate_id="rate_coordinadora_mercantil")
            result = _run(self.tool.execute(args, ctx))
        finally:
            la.select_carrier_for_cart = original

        self.assertTrue(result.success,
                        f"Fuzzy con separadores normalizados debe matchear: {result.data}")
        self.assertEqual(captured["carrier"], "COORDINADORA MERCANTIL")
        self.assertEqual(captured["rate_id"], "1009")

    def test_fuzzy_match_normaliza_guiones(self):
        """Variante: 'rate-tcc-sa' debe matchear 'TCC SA'."""
        options_in_db = [
            {"rate_id": "1010", "carrier": "TCC SA",
             "service_level": "Mensajeria", "price_cents": 1860000},
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)

        import agentic.legacy_adapters as la
        original = la.select_carrier_for_cart

        async def fake_select(supabase, **kw):
            return {"ok": True, "carrier": "TCC SA", "service_level": "M",
                    "shipping_cents": 1860000, "total_cents": 1860000}

        la.select_carrier_for_cart = fake_select
        try:
            from unittest.mock import MagicMock
            ctx = ToolContext(
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=sb, extras={}, logger=MagicMock(),
            )
            args = self.tool.args_schema(rate_id="rate-tcc-sa")
            result = _run(self.tool.execute(args, ctx))
        finally:
            la.select_carrier_for_cart = original

        self.assertTrue(result.success)

    def test_fuzzy_match_case_insensitive(self):
        """Match debe ser case-insensitive: rate_id='ENVIA' y carrier='envia'."""
        options_in_db = [
            {"rate_id": "29", "carrier": "envia",  # lowercase carrier
             "service_level": "Mensajeria", "price_cents": 1650000},
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)

        import agentic.legacy_adapters as la
        original = la.select_carrier_for_cart

        async def fake_select(supabase, **kw):
            return {"ok": True, "carrier": "envia", "service_level": "M",
                    "shipping_cents": 1650000, "total_cents": 1650000}

        la.select_carrier_for_cart = fake_select
        try:
            from unittest.mock import MagicMock
            ctx = ToolContext(
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=sb, extras={}, logger=MagicMock(),
            )
            args = self.tool.args_schema(rate_id="ENVIA")  # uppercase rate_id
            result = _run(self.tool.execute(args, ctx))
        finally:
            la.select_carrier_for_cart = original

        self.assertTrue(result.success)

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

    def test_carrier_name_only_resuelve_sin_rate_id_rev107(self):
        """Rev. 107: el LLM puede pasar SOLO `carrier_name` cuando no
        recuerda el rate_id exacto. Caso runtime KAIU 2026-05-23:
        cliente 'Coordinadora me parece bien' → LLM mandó rate_id='12345'
        (placeholder inventado). Con carrier_name explícito, el fuzzy
        matcher resuelve sin error."""
        options_in_db = [
            {
                "rate_id": "1009",
                "carrier": "COORDINADORA MERCANTIL",
                "service_level": "Mensajeria",
                "price_cents": 753000,
            },
            {
                "rate_id": "29",
                "carrier": "ENVIA",
                "service_level": "Mensajeria",
                "price_cents": 900000,
            },
        ]
        sb = _mock_supabase_with_quoted_options(options_in_db)

        from agentic import legacy_adapters as la
        original = la.select_carrier_for_cart

        async def fake_select(supabase, **kw):
            return {
                "ok": True, "carrier": "Coordinadora Mercantil",
                "service_level": "Mensajeria",
                "shipping_cents": 753000, "total_cents": 853000,
            }

        la.select_carrier_for_cart = fake_select
        try:
            ctx = ToolContext(
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=sb,
                extras={
                    # Rev. 108 — cliente mencionó "Coordinadora" (KAIU 2026-05-23).
                    "recent_inbound_texts": ["Coordinadora me parece bien"],
                },
            )
            # rate_id vacío + carrier_name → debe resolver por fuzzy.
            args = self.tool.args_schema(rate_id="", carrier_name="Coordinadora")
            result = _run(self.tool.execute(args, ctx))
        finally:
            la.select_carrier_for_cart = original

        self.assertTrue(result.success, f"Falló: {result.data}")
        self.assertIn("Coordinadora", result.data["carrier"])

    def test_missing_both_rate_id_y_carrier_name_falla(self):
        """Si LLM no pasa ni rate_id ni carrier_name → error explícito."""
        sb = _mock_supabase_with_quoted_options([
            {"rate_id": "1009", "carrier": "COORDINADORA", "price_cents": 753000},
        ])
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb, extras={},
        )
        args = self.tool.args_schema(rate_id="", carrier_name="")
        result = _run(self.tool.execute(args, ctx))
        self.assertFalse(result.success)
        self.assertEqual(result.data["code"], "MISSING_CARRIER_ARG")

    def test_empty_args_idempotent_when_carrier_already_selected(self):
        """A11 FIX: si el carrier YA está persistido (shipping_meta.carrier +
        rate_id) y el LLM re-llama sin args (doble-manejo resolver+LLM), el
        tool devuelve éxito NO-OP en vez de MISSING_CARRIER_ARG ('error al
        seleccionar' visible al cliente)."""
        sb = _mock_supabase_with_selected_carrier(
            carrier="INTERRAPIDISIMO", rate_id="1016",
            shipping_cents=1810000, total_cents=6610000,
        )
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb, extras={},
        )
        args = self.tool.args_schema(rate_id="", carrier_name="")
        result = _run(self.tool.execute(args, ctx))
        self.assertTrue(result.success, f"Esperaba no-op éxito: {result.data}")
        self.assertEqual(result.data["carrier"], "INTERRAPIDISIMO")
        self.assertTrue(result.data.get("idempotent_noop"))
        self.assertEqual(result.data["total_cop"], 66100)


if __name__ == "__main__":
    unittest.main()

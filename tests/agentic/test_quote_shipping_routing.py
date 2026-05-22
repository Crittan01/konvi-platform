"""Tests routing por active_provider en QuoteShippingTool.

Rev. 107 M.5 — verifica que el tool lee tenant_shipping_provider_config
y invoca el adapter correcto (Envia o Aveonline) sin fallback automático.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

# Registrar tools.
import agentic.tools.cart  # noqa: F401
import agentic.tools.shipping  # noqa: F401

from agentic.tools.registry import get_tool
from agentic.tools.base import ToolContext


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_supabase_with_provider(active_provider: str | None):
    """Mock supabase que retorna config con active_provider."""
    sb = MagicMock()
    cfg_data = (
        {"active_provider": active_provider}
        if active_provider is not None else None
    )

    def table_side(name):
        chain = MagicMock()
        if name == "tenant_shipping_provider_config":
            chain.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=cfg_data)
        return chain

    sb.table.side_effect = table_side
    return sb


class QuoteShippingRoutingTests(unittest.TestCase):

    def setUp(self):
        self.tool = get_tool("quote_shipping")
        self.assertIsNotNone(self.tool, "quote_shipping tool no registrado")

    def _make_ctx(self, sb):
        return ToolContext(
            tenant_id="t-1", conversation_id="c-1", contact_id="ct-1",
            supabase=sb, extras={}, logger=MagicMock(),
        )

    def test_active_provider_envia_invoca_adapter_envia(self):
        """active_provider='envia' → quote_shipping_for_cart (legacy)."""
        sb = _mock_supabase_with_provider("envia")
        import agentic.legacy_adapters as la

        # Stub ambos adapters; verificar cuál se llama.
        called = {"envia": False, "aveonline": False}

        async def fake_envia(sb, **kw):
            called["envia"] = True
            return {"ok": True, "options": [{"rate_id": "envia-1", "carrier": "Envia", "service_level": "estandar", "price_cents": 15000, "eta_date": "3d"}], "city_normalized": "Bogotá"}

        async def fake_aveonline(sb, **kw):
            called["aveonline"] = True
            return {"ok": True, "options": []}

        with patch.object(la, "quote_shipping_for_cart", fake_envia), \
             patch.object(la, "quote_shipping_for_cart_aveonline", fake_aveonline):
            args = self.tool.args_schema(city="Bogotá")
            result = _run(self.tool.execute(args, self._make_ctx(sb)))

        self.assertTrue(called["envia"])
        self.assertFalse(called["aveonline"])
        self.assertTrue(result.success)

    def test_active_provider_aveonline_invoca_adapter_aveonline(self):
        """active_provider='aveonline' → quote_shipping_for_cart_aveonline."""
        sb = _mock_supabase_with_provider("aveonline")
        import agentic.legacy_adapters as la

        called = {"envia": False, "aveonline": False}

        async def fake_envia(sb, **kw):
            called["envia"] = True
            return {"ok": True, "options": []}

        async def fake_aveonline(sb, **kw):
            called["aveonline"] = True
            return {
                "ok": True,
                "options": [{
                    "rate_id": "ave-coord-1", "carrier": "COORDINADORA",
                    "service_level": "Mensajeria",
                    "price_cents": 1593000, "eta_date": "3d",
                }],
                "city_normalized": "Medellín",
                "destination": {"city": "Medellín"},
                "provider": "aveonline",
            }

        with patch.object(la, "quote_shipping_for_cart", fake_envia), \
             patch.object(la, "quote_shipping_for_cart_aveonline", fake_aveonline):
            args = self.tool.args_schema(city="Medellín")
            result = _run(self.tool.execute(args, self._make_ctx(sb)))

        self.assertTrue(called["aveonline"])
        self.assertFalse(called["envia"])
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["options"]), 1)
        self.assertEqual(result.data["options"][0]["carrier"], "COORDINADORA")

    def test_sin_config_default_envia(self):
        """Sin row en tenant_shipping_provider_config → default 'envia'."""
        sb = _mock_supabase_with_provider(None)  # No row.
        import agentic.legacy_adapters as la

        called = {"envia": False, "aveonline": False}

        async def fake_envia(sb, **kw):
            called["envia"] = True
            return {"ok": True, "options": [{"rate_id": "x", "carrier": "Envia", "service_level": "estandar", "price_cents": 15000, "eta_date": "3d"}], "city_normalized": "Bogotá"}

        async def fake_aveonline(sb, **kw):
            called["aveonline"] = True
            return {"ok": True, "options": []}

        with patch.object(la, "quote_shipping_for_cart", fake_envia), \
             patch.object(la, "quote_shipping_for_cart_aveonline", fake_aveonline):
            args = self.tool.args_schema(city="Bogotá")
            _run(self.tool.execute(args, self._make_ctx(sb)))

        self.assertTrue(called["envia"])
        self.assertFalse(called["aveonline"])

    def test_db_falla_default_envia(self):
        """Si DB query falla, defaultea a 'envia' sin propagar excepción."""
        sb = MagicMock()
        sb.table.side_effect = Exception("DB unreachable")
        import agentic.legacy_adapters as la

        called = {"envia": False, "aveonline": False}

        async def fake_envia(sb, **kw):
            called["envia"] = True
            return {"ok": True, "options": [{"rate_id": "x", "carrier": "Envia", "service_level": "estandar", "price_cents": 15000, "eta_date": "3d"}], "city_normalized": "Bogotá"}

        async def fake_aveonline(sb, **kw):
            called["aveonline"] = True
            return {"ok": True, "options": []}

        with patch.object(la, "quote_shipping_for_cart", fake_envia), \
             patch.object(la, "quote_shipping_for_cart_aveonline", fake_aveonline):
            args = self.tool.args_schema(city="Bogotá")
            _run(self.tool.execute(args, self._make_ctx(sb)))

        # Fallback graceful: Envia, no propaga la excepción de DB.
        self.assertTrue(called["envia"])
        self.assertFalse(called["aveonline"])


class CityFormatHelperTests(unittest.TestCase):
    """Helper _to_aveonline_city_format — uppercase + sin tildes + sin D.C."""

    def test_bogota_dc_normalizado(self):
        from agentic.legacy_adapters import _to_aveonline_city_format
        self.assertEqual(
            _to_aveonline_city_format("Bogotá D.C.", "Cundinamarca"),
            "BOGOTA(CUNDINAMARCA)",
        )

    def test_bogota_state_es_bogota_dc_se_remap_cundinamarca(self):
        """Caso edge: state='Bogotá D.C.' → remap a CUNDINAMARCA."""
        from agentic.legacy_adapters import _to_aveonline_city_format
        self.assertEqual(
            _to_aveonline_city_format("Bogotá D.C.", "Bogotá D.C."),
            "BOGOTA(CUNDINAMARCA)",
        )

    def test_medellin_antioquia(self):
        from agentic.legacy_adapters import _to_aveonline_city_format
        self.assertEqual(
            _to_aveonline_city_format("Medellín", "Antioquia"),
            "MEDELLIN(ANTIOQUIA)",
        )

    def test_input_vacio_retorna_vacio(self):
        from agentic.legacy_adapters import _to_aveonline_city_format
        self.assertEqual(_to_aveonline_city_format("", "Antioquia"), "")
        self.assertEqual(_to_aveonline_city_format("Medellín", ""), "")


if __name__ == "__main__":
    unittest.main()

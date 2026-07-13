"""
Tests R-02: variation_id real en pedido conversacional.
Verifica que _build_verified_order_context retorna product_id y variation_id,
y que payment_link_tool usa los IDs reales cuando están disponibles.
"""
import os
import sys
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("INTERNAL_SERVICE_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

import orchestrator
from tools.payment_link_tool import handle_payment_link_if_applicable


@patch("tools.payment_link_tool.INTERNAL_SERVICE_SECRET", "test-secret")
class PaymentLinkToolWithVerifiedCtxTests(unittest.IsolatedAsyncioTestCase):

    def _make_verified_ctx(self):
        return {
            "product_id": "prod-uuid-123",
            "variation_id": "var-uuid-rojo",
            "product_name": "Camiseta Polo Testing",
            "variant_label": "Color: Rojo",
            "unit_price_cents": 6000000,
            "quantity": 1,
            "subtotal_cents": 6000000,
            "shipping_cost_cents": 1314000,
            "total_cents": 7314000,
        }

    def _make_http_mock(self, captured_payload: dict):
        """Helper: construye mock httpx que captura el payload de /orders/."""
        async def _post(url, *, headers=None, json=None, **kw):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "payment-link" not in str(url):
                captured_payload.update(json or {})
                resp.status_code = 201
                resp.json.return_value = {"id": "order-abc-123"}
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "checkout_url": "https://checkout.wompi.co/l/test_abc",
                    "expires_at": "2026-04-25T23:00:00Z",
                }
            return resp

        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=_post)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)
        return client_mock

    async def test_uses_real_variation_id_in_order_items(self):
        """Con verified_ctx, el payload de la orden incluye variation_id y product_id reales."""
        captured = {}
        http_mock = self._make_http_mock(captured)

        with patch("tools.payment_link_tool.httpx.AsyncClient", return_value=http_mock):
            result = await handle_payment_link_if_applicable(
                tenant_id="tenant-1",
                contact_id="contact-1",
                conversation_id="conv-1",
                contact_name="Cristian Camilo Garzon Tamayo",
                total_in_cents=7314000,
                shipping_cost_cents=1314000,
                notes=None,
                supabase=MagicMock(),
                verified_ctx=self._make_verified_ctx(),
            )

        self.assertIsNotNone(result)
        self.assertIn("items", captured)
        item = captured["items"][0]
        self.assertEqual(item.get("variation_id"), "var-uuid-rojo")
        self.assertEqual(item.get("product_id"), "prod-uuid-123")
        self.assertEqual(item.get("quantity"), 1)
        self.assertIn("Camiseta Polo Testing", item.get("title", ""))
        self.assertIn("Color: Rojo", item.get("title", ""))

    async def test_fallback_to_generic_item_without_verified_ctx(self):
        """Sin verified_ctx, usa ítem genérico (comportamiento anterior)."""
        captured = {}
        http_mock = self._make_http_mock(captured)

        with patch("tools.payment_link_tool.httpx.AsyncClient", return_value=http_mock):
            await handle_payment_link_if_applicable(
                tenant_id="tenant-1",
                contact_id=None,
                conversation_id="conv-1",
                contact_name=None,
                total_in_cents=6000000,
                shipping_cost_cents=0,
                notes=None,
                supabase=MagicMock(),
                verified_ctx=None,
            )

        item = captured["items"][0]
        self.assertIsNone(item.get("variation_id"))
        # Sem 7 F2 cierre — fallback title cambió de "Pedido conversacional"
        # a "Pedido vía WhatsApp" para mejor UX (suena menos técnico al
        # cliente en checkout Wompi).
        self.assertEqual(item.get("title"), "Pedido vía WhatsApp")


if __name__ == "__main__":
    unittest.main()

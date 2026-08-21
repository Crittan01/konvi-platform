"""Test: el adapter agentic `generate_payment_link_for_cart` construye
`verified_ctx['items']` desde el cart real y lo pasa a la función legacy.

Rev. 107 — bug runtime KAIU: order_items quedaba con row genérico
"Pedido vía WhatsApp" porque el adapter NO pasaba verified_ctx → la
función legacy caía al fallback. Sin items reales en order_items, la
respuesta de `get_recent_orders` mostraba placeholder.

Este test no toca DB ni Wompi — mockea ambos para validar que el
adapter compone el payload correcto.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class PaymentAdapterVerifiedCtxTests(unittest.TestCase):

    def test_adapter_pasa_items_detallados_a_handle_payment_link(self):
        from agentic.legacy_adapters.payment import generate_payment_link_for_cart

        fake_cart = {
            "id": "cart-1", "status": "open",
            "subtotal_cents": 16000000, "shipping_cents": 1795000,
            "total_cents": 17795000,
            "items": [
                {
                    "product_id": "p-coco",
                    "variation_id": "v-coco-60",
                    "quantity": 1,
                    "unit_price_cents": 1800000,
                    "product": {"title": "Jabón Artesanal de Coco"},
                    "variation": {"attributes": {"Presentación": "60g"}},
                },
                {
                    "product_id": "p-serum",
                    "variation_id": "v-serum-30",
                    "quantity": 1,
                    "unit_price_cents": 9200000,
                    "product": {"title": "Sérum de Ácido Hialurónico"},
                    "variation": {"attributes": {"Volumen": "30ml"}},
                },
            ],
        }
        fake_contact = {
            "consent_given": True, "email": "x@y.com", "name": "Cristian",
            "document_type": "CC", "document_number": "123", "address": "X",
        }

        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            MagicMock(data=fake_contact)
        )
        # FIX 5 (2026-08-21): el adapter ahora exige una confirmación afirmativa
        # del cliente POSTERIOR al último resumen del bot antes de crear la
        # orden. El historial mockeado incluye ese "sí" tras el resumen.
        _messages_chain = MagicMock()
        _messages_chain.execute.return_value = MagicMock(data=[
            {"direction": "inbound", "content": "sí, confirmo"},
            {"direction": "outbound", "content": "📋 *Resumen del pedido*\n*TOTAL: $177.950*"},
        ])
        for _m in ("select", "eq", "order", "limit"):
            getattr(_messages_chain, _m).return_value = _messages_chain

        def _table_route(name):
            if name == "messages":
                return _messages_chain
            return sb.table.return_value

        sb.table.side_effect = _table_route

        captured = {}

        async def fake_handler(**kw):
            captured.update(kw)
            class _R:
                checkout_url = "https://checkout.wompi.co/l/test_XYZ"
                order_id = "ord-1"
                amount_in_cents = 17795000
                expires_at = "2026-05-23T15:00:00Z"
                response_text = "Listo"
            return _R()

        with patch("tools.cart_tool.get_cart_with_items", return_value=fake_cart):
            with patch(
                "tools.payment_link_tool.handle_payment_link_if_applicable",
                fake_handler,
            ):
                result = _run(generate_payment_link_for_cart(
                    sb,
                    conversation_id="conv-1",
                    tenant_id="t-1",
                    contact_id="ct-1",
                ))

        self.assertTrue(result["ok"])
        # Verificar que pasó verified_ctx poblado con items reales.
        ctx = captured.get("verified_ctx")
        self.assertIsNotNone(ctx, "verified_ctx NO fue pasado al handler")
        items = ctx.get("items") or []
        self.assertEqual(len(items), 2)

        # Item 1: Jabón Coco 60g
        coco = next(i for i in items if "Coco" in i["title"])
        self.assertEqual(coco["variant_label"], "60g")
        self.assertEqual(coco["quantity"], 1)
        self.assertEqual(coco["unit_price_cents"], 1800000)
        self.assertEqual(coco["variation_id"], "v-coco-60")

        # Item 2: Sérum Hialurónico 30ml
        serum = next(i for i in items if "Sérum" in i["title"])
        self.assertEqual(serum["variant_label"], "30ml")
        self.assertEqual(serum["variation_id"], "v-serum-30")


if __name__ == "__main__":
    unittest.main()

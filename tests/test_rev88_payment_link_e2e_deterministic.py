"""Rev. 88 — Test E2E determinístico del payment_link flow completo.

Pregunta del usuario: "¿Tienes contemplado pruebas para generar link de pago?"

Tests existentes (test_payment_link_tool.py) cubren edge cases (total
inválido, JWT ausente). Este archivo cubre el HAPPY PATH MULTI-PRODUCTO
end-to-end SIN depender del LLM — mockeo del Core API y Wompi.

Lo que asegura:
  • Multi-producto se persiste como N order_items separados.
  • verified_ctx se traduce correctamente al payload Wompi.
  • Customer_data prepoblado (rev. 78 F4).
  • Pre-validación de stock previene oversell.
  • Response_text final es humanizado con primer nombre.
"""
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("API_URL", "http://localhost:8001")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools import payment_link_tool  # noqa: E402


# ─── Fixture realista ────────────────────────────────────────────────────────

CART_BUG_LOG_VERIFIED_CTX = {
    # Reproducción del log conv 132f0dac
    "items": [
        {
            "title": "Jabón Artesanal de Coco",
            "variant_label": "60g",
            "quantity": 1,
            "unit_price_cents": 1800000,  # $18.000
            "product_id": "p-coco",
            "variation_id": "v-coco-60g",
        },
        {
            "title": "Jabón Artesanal de Lavanda",
            "variant_label": "150g",
            "quantity": 2,
            "unit_price_cents": 3200000,  # $32.000 c/u
            "product_id": "p-lavanda",
            "variation_id": "v-lavanda-150g",
        },
    ],
    "subtotal_cents": 8200000,    # 18k + 64k
    "shipping_cost_cents": 1100000,
    "total_cents": 9300000,
}


def _supabase_with_stock(stock_per_variation: dict) -> MagicMock:
    """Mock supabase que retorna stock_quantity per variation_id."""
    sb = MagicMock()
    def _table(name):
        t = MagicMock()
        if name == "product_variations":
            def _select(*args, **kwargs):
                s = MagicMock()
                def _eq(field, value):
                    e = MagicMock()
                    def _single():
                        single = MagicMock()
                        def _execute():
                            res = MagicMock()
                            res.data = (
                                {"sku": f"sku-{value[:6]}",
                                 "stock_quantity": stock_per_variation.get(value, 100)}
                                if value in stock_per_variation
                                else {"sku": f"sku-{value[:6]}", "stock_quantity": 100}
                            )
                            return res
                        single.execute = _execute
                        return single
                    e.single = _single
                    return e
                s.eq = _eq
                return s
            t.select = _select
        return t
    sb.table.side_effect = _table
    return sb


# ─── Tests ───────────────────────────────────────────────────────────────────

class PaymentLinkHappyPathTests(unittest.IsolatedAsyncioTestCase):
    """Happy path: cart con 2 productos + datos completos → link Wompi
    generado, items persistidos, response humanizado."""

    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_multi_product_creates_order_and_link(self, mock_client):
        """Reproducción del bug del log: 1 Coco + 2 Lavanda = $93.000.
        Ahora con cart-as-SoT (rev. 80) + payment_link tool → order completa.

        El tool hace 2 POST consecutivos:
          1. POST /api/v1/orders/ → returns order_id
          2. POST /api/v1/orders/{id}/payment-link → returns checkout_url
        """
        # Track de llamadas para asserts posteriores
        captured_calls = []

        async def _post(url, headers=None, json=None, **kw):
            captured_calls.append({"url": url, "json": json})
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            if "/payment-link" in url:
                resp.json = MagicMock(return_value={
                    "checkout_url": "https://checkout.wompi.co/l/plink-9300000",
                    "expires_at": "2026-05-01T16:00:00Z",
                    "amount_in_cents": 9300000,
                })
            else:
                resp.json = MagicMock(return_value={
                    "id": "order-bug-log",
                    "status": "pending_payment",
                })
            return resp

        async_ctx = AsyncMock()
        async_ctx.__aenter__.return_value = MagicMock(post=_post)
        mock_client.return_value = async_ctx

        sb = _supabase_with_stock({
            "v-coco-60g": 50,
            "v-lavanda-150g": 30,
        })

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-kaiu",
            contact_id="contact-cristian",
            conversation_id="conv-bug-log",
            contact_name="Cristian Camilo Garzón Tamayo",
            total_in_cents=9300000,
            shipping_cost_cents=1100000,
            notes=None,
            supabase=sb,
            verified_ctx=CART_BUG_LOG_VERIFIED_CTX,
        )

        # Resultado válido
        self.assertIsNotNone(result)
        self.assertEqual(result.checkout_url, "https://checkout.wompi.co/l/plink-9300000")
        self.assertEqual(result.amount_in_cents, 9300000)
        self.assertEqual(result.order_id, "order-bug-log")

        # 2 llamadas (orders + payment-link)
        self.assertEqual(len(captured_calls), 2)
        # Primera: POST /orders/ con TODOS los items multi-producto
        order_call = captured_calls[0]
        self.assertIn("/orders", order_call["url"])
        order_payload = order_call["json"]
        self.assertEqual(len(order_payload["items"]), 2)
        titles = [i["title"] for i in order_payload["items"]]
        self.assertIn("Jabón Artesanal de Coco — 60g", titles)
        self.assertIn("Jabón Artesanal de Lavanda — 150g", titles)
        # Cantidades correctas (1 Coco, 2 Lavanda)
        qtys = sorted([i["quantity"] for i in order_payload["items"]])
        self.assertEqual(qtys, [1, 2])
        # variation_ids presentes (necesario para decremento de stock al APPROVED)
        for item in order_payload["items"]:
            self.assertIn("variation_id", item)
        # contact_id va en payload (rev. 78 F4: customer_data prepoblado)
        self.assertEqual(order_payload["contact_id"], "contact-cristian")

        # Segunda llamada: POST payment-link
        link_call = captured_calls[1]
        self.assertIn("/payment-link", link_call["url"])
        self.assertIn("order-bug-log", link_call["url"])

        # Response_text humanizado con primer nombre
        self.assertIn("Cristian", result.response_text)
        # Mensaje incluye URL para que el cliente pueda hacer clic
        self.assertIn("checkout.wompi.co/l/plink-9300000", result.response_text)


class PaymentLinkStockGuardTests(unittest.IsolatedAsyncioTestCase):
    """Pre-validación de stock previene oversell."""

    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_insufficient_stock_blocks_link_and_offers_alternative(self, mock_client):
        # Stock insuficiente: pide 2 Lavanda pero solo hay 1
        sb = _supabase_with_stock({
            "v-coco-60g": 50,
            "v-lavanda-150g": 1,   # pediste 2, hay 1
        })

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-kaiu",
            contact_id="contact-cristian",
            conversation_id="conv-stock-issue",
            contact_name="Cristian",
            total_in_cents=9300000,
            shipping_cost_cents=1100000,
            notes=None,
            supabase=sb,
            verified_ctx=CART_BUG_LOG_VERIFIED_CTX,
        )

        # Resultado existe pero con mensaje de stock insuficiente
        self.assertIsNotNone(result)
        self.assertIn("sin stock suficiente", result.response_text.lower())
        self.assertIn("ajustar", result.response_text.lower())
        # Sin URL Wompi (el link NO se generó)
        self.assertEqual(result.checkout_url, "")

        # NO se llamó al Core API (ahorra latencia + previene order spurious)
        mock_client.assert_not_called()


class PaymentLinkWompiCustomerDataTests(unittest.IsolatedAsyncioTestCase):
    """Validación rev. 78 F4: customer_data prepoblado."""

    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_order_payload_includes_contact_id(self, mock_client):
        """contact_id va en el payload para que el endpoint API resuelva
        customer_data y lo pase a Wompi."""
        captured_calls = []

        async def _post(url, headers=None, json=None, **kw):
            captured_calls.append({"url": url, "json": json})
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            if "/payment-link" in url:
                resp.json = MagicMock(return_value={
                    "checkout_url": "https://checkout.wompi.co/l/plink-1",
                    "expires_at": "2026-05-01T16:00:00Z",
                    "amount_in_cents": 1800000,
                })
            else:
                resp.json = MagicMock(return_value={
                    "id": "order-1",
                    "status": "pending_payment",
                })
            return resp

        async_ctx = AsyncMock()
        async_ctx.__aenter__.return_value = MagicMock(post=_post)
        mock_client.return_value = async_ctx

        sb = _supabase_with_stock({"v-coco-60g": 50})

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-kaiu",
            contact_id="contact-cristian",
            conversation_id="conv-1",
            contact_name="Cristian",
            total_in_cents=1800000,
            shipping_cost_cents=0,
            notes=None,
            supabase=sb,
            verified_ctx={
                "items": [{
                    "title": "Jabón Artesanal de Coco",
                    "variant_label": "60g",
                    "quantity": 1,
                    "unit_price_cents": 1800000,
                    "product_id": "p-coco",
                    "variation_id": "v-coco-60g",
                }],
                "subtotal_cents": 1800000,
                "shipping_cost_cents": 0,
                "total_cents": 1800000,
            },
        )
        self.assertIsNotNone(result)
        order_payload = captured_calls[0]["json"]
        # contact_id presente para que el API resuelva y pase customer_data a Wompi
        self.assertEqual(order_payload["contact_id"], "contact-cristian")
        self.assertEqual(order_payload["conversation_id"], "conv-1")
        # Flag payment_link → status=pending_payment + creación de plink
        self.assertTrue(order_payload["payment_link"])


if __name__ == "__main__":
    unittest.main()

"""
Tests del tool payment_link_tool del Orchestrator.

Cubre:
- total_in_cents menor a mínimo → None
- total_in_cents mayor a cap de sanidad → None
- SUPABASE_JWT_SECRET ausente → None
- Error 503 de Core API (Wompi no configurado) → None
- Happy path: crea orden, genera link, retorna PaymentLinkResult
- Verificación del response_text humanizado (primer nombre)
"""
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("API_URL", "http://localhost:8001")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools import payment_link_tool


class PaymentLinkToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_total_below_minimum_returns_none(self):
        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Garzon",
            total_in_cents=1000,  # $10 COP
            shipping_cost_cents=0,
            notes=None,
            supabase=MagicMock(),
        )
        self.assertIsNone(result)

    async def test_total_above_sanity_cap_returns_none(self):
        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Garzon",
            total_in_cents=20_000_000_000,  # $200M COP
            shipping_cost_cents=0,
            notes=None,
            supabase=MagicMock(),
        )
        self.assertIsNone(result)

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "")
    async def test_missing_jwt_secret_returns_none(self):
        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Garzon",
            total_in_cents=200_000,
            shipping_cost_cents=0,
            notes=None,
            supabase=MagicMock(),
        )
        self.assertIsNone(result)

    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_core_api_503_returns_none(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Primera llamada (crear orden) OK
        # Segunda llamada (payment-link) 503
        order_resp = MagicMock()
        order_resp.status_code = 201
        order_resp.json.return_value = {"id": "order-123"}
        order_resp.raise_for_status = MagicMock()

        link_resp = MagicMock()
        link_resp.status_code = 503
        link_resp.raise_for_status = MagicMock(side_effect=Exception("503"))

        mock_client.post = AsyncMock(side_effect=[order_resp, link_resp])
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Garzon",
            total_in_cents=200_000,
            shipping_cost_cents=0,
            notes=None,
            supabase=MagicMock(),
        )
        self.assertIsNone(result)

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_happy_path_returns_result(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        order_resp = MagicMock()
        order_resp.status_code = 201
        order_resp.json.return_value = {"id": "order-123"}
        order_resp.raise_for_status = MagicMock()

        link_resp = MagicMock()
        link_resp.status_code = 200
        link_resp.json.return_value = {
            "checkout_url": "https://checkout.wompi.co/l/plink-123",
            "expires_at": "2026-04-24T20:00:00.000Z",
            "wompi_link_id": "plink-123",
        }
        link_resp.raise_for_status = MagicMock()

        mock_client.post = AsyncMock(side_effect=[order_resp, link_resp])
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Camilo Garzon Tamayo",
            total_in_cents=200_000,
            shipping_cost_cents=10_000,
            notes=None,
            supabase=MagicMock(),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.checkout_url, "https://checkout.wompi.co/l/plink-123")
        self.assertEqual(result.order_id, "order-123")
        self.assertEqual(result.amount_in_cents, 200_000)
        # Verificar humanización: usa primer nombre
        self.assertIn("Cristian", result.response_text)
        self.assertNotIn("Cristian Camilo Garzon Tamayo", result.response_text)

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_response_text_uses_first_name_only(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        order_resp = MagicMock()
        order_resp.status_code = 201
        order_resp.json.return_value = {"id": "order-abc"}
        order_resp.raise_for_status = MagicMock()

        link_resp = MagicMock()
        link_resp.status_code = 200
        link_resp.json.return_value = {
            "checkout_url": "https://checkout.wompi.co/l/plink-abc",
            "expires_at": "2026-04-24T20:00:00.000Z",
            "wompi_link_id": "plink-abc",
        }
        link_resp.raise_for_status = MagicMock()

        mock_client.post = AsyncMock(side_effect=[order_resp, link_resp])
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Maria Paula Rodriguez Lopez",
            total_in_cents=300_000,
            shipping_cost_cents=0,
            notes=None,
            supabase=MagicMock(),
        )

        self.assertIsNotNone(result)
        self.assertIn("Maria", result.response_text)
        self.assertNotIn("Maria Paula Rodriguez Lopez", result.response_text)

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_response_text_handles_whitespace_contact_name(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        order_resp = MagicMock()
        order_resp.status_code = 201
        order_resp.json.return_value = {"id": "order-whitespace"}
        order_resp.raise_for_status = MagicMock()

        link_resp = MagicMock()
        link_resp.status_code = 200
        link_resp.json.return_value = {
            "checkout_url": "https://checkout.wompi.co/l/plink-whitespace",
            "expires_at": "2026-04-24T20:00:00.000Z",
            "wompi_link_id": "plink-whitespace",
        }
        link_resp.raise_for_status = MagicMock()

        mock_client.post = AsyncMock(side_effect=[order_resp, link_resp])
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="   ",
            total_in_cents=300_000,
            shipping_cost_cents=0,
            notes=None,
            supabase=MagicMock(),
        )

        self.assertIsNotNone(result)
        self.assertNotIn("*   *", result.response_text)


if __name__ == "__main__":
    unittest.main()

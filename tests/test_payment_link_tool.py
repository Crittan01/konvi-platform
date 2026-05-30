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


class PaymentLinkIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    """Guards de idempotencia transaccional (rev. 104).

    Caso runtime motivador (S06[new] 2026-05-04):
      Cliente recibe link Wompi #1 → "Sigamos con la compra por favor" →
      bypass AWAITING_ORDER_CONFIRMATION+afirmativo dispara payment_link
      otra vez → SIN guard, orden #2 + link #2 (duplicado).

    Plan A.0.1: una conversación + cart abierto = una orden activa.
    """

    def _build_supabase_with_existing_link(
        self, *, order_id: str, checkout_url: str, amount_cents: int,
    ):
        """Mock supabase chain: orders.select... → 1 fila pending_payment;
        payments.select... → 1 fila pending vigente."""
        from datetime import datetime, timezone
        recent_iso = datetime.now(timezone.utc).isoformat()

        orders_exec_result = MagicMock()
        orders_exec_result.data = [
            {"id": order_id, "total_amount": amount_cents / 100,
             "status": "pending_payment", "created_at": recent_iso},
        ]
        payments_exec_result = MagicMock()
        payments_exec_result.data = [
            {"checkout_url": checkout_url, "wompi_link_id": "plink-existing",
             "status": "pending", "created_at": recent_iso,
             "amount_in_cents": amount_cents},
        ]

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.gte.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            if name == "orders":
                chain.execute.return_value = orders_exec_result
            elif name == "payments":
                chain.execute.return_value = payments_exec_result
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        sb = MagicMock()
        sb.table.side_effect = _table
        return sb

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_reuses_existing_link_when_pending_payment_active(self, mock_client_cls):
        sb = self._build_supabase_with_existing_link(
            order_id="order-existing-12345678",
            checkout_url="https://checkout.wompi.co/l/plink-existing",
            amount_cents=200_000,
        )

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Garzon",
            total_in_cents=200_000,
            shipping_cost_cents=10_000,
            notes=None,
            supabase=sb,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.order_id, "order-existing-12345678")
        self.assertEqual(result.checkout_url, "https://checkout.wompi.co/l/plink-existing")
        # No debió llamar al Core API (ni crear orden ni generar link)
        mock_client_cls.assert_not_called()
        # Mensaje recordatorio reconocible
        self.assertIn("ya tiene link de pago activo", result.response_text)
        self.assertIn("https://checkout.wompi.co/l/plink-existing", result.response_text)
        # Short id (primeros 8 chars en mayúscula)
        self.assertIn("ORDER-EX", result.response_text)

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_creates_new_order_when_no_active_pending_payment(self, mock_client_cls):
        # Sin orden pending_payment activa → flujo normal
        orders_exec_result = MagicMock()
        orders_exec_result.data = []

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.gte.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = orders_exec_result
            return chain

        sb = MagicMock()
        sb.table.side_effect = _table

        # Mock httpx para flujo normal de creación
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        order_resp = MagicMock()
        order_resp.status_code = 201
        order_resp.json.return_value = {"id": "order-new-123"}
        order_resp.raise_for_status = MagicMock()
        link_resp = MagicMock()
        link_resp.status_code = 200
        link_resp.json.return_value = {
            "checkout_url": "https://checkout.wompi.co/l/plink-new",
            "expires_at": "2026-04-24T20:00:00.000Z",
            "wompi_link_id": "plink-new",
        }
        link_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(side_effect=[order_resp, link_resp])
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian",
            total_in_cents=200_000,
            shipping_cost_cents=0,
            notes=None,
            supabase=sb,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.order_id, "order-new-123")
        self.assertEqual(result.checkout_url, "https://checkout.wompi.co/l/plink-new")

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_supabase_lookup_failure_degrades_to_create(self, mock_client_cls):
        # Lookup explota → guard degrada y procede a crear (best-effort)
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("DB conn lost")

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        order_resp = MagicMock()
        order_resp.status_code = 201
        order_resp.json.return_value = {"id": "order-fallback-123"}
        order_resp.raise_for_status = MagicMock()
        link_resp = MagicMock()
        link_resp.status_code = 200
        link_resp.json.return_value = {
            "checkout_url": "https://checkout.wompi.co/l/plink-fallback",
            "expires_at": "",
            "wompi_link_id": "plink-fallback",
        }
        link_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(side_effect=[order_resp, link_resp])
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian",
            total_in_cents=200_000,
            shipping_cost_cents=0,
            notes=None,
            supabase=sb,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.order_id, "order-fallback-123")

    def _build_supabase_with_expired_link(
        self, *, order_id: str, total_amount: float,
    ):
        """Mock supabase chain donde:
          orders.select... → 1 fila pending_payment
          payments.select.gte(cutoff)... → vacío (link >TTL ya filtrado)
        Simula el caso (b): orden viva pero el link expiró.
        """
        orders_exec_result = MagicMock()
        orders_exec_result.data = [{
            "id": order_id, "total_amount": total_amount,
            "status": "pending_payment", "created_at": "2026-05-04T20:00:00+00:00",
        }]
        payments_exec_result = MagicMock()
        payments_exec_result.data = []  # gte(cutoff) filtra link expirado

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.gte.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            if name == "orders":
                chain.execute.return_value = orders_exec_result
            elif name == "payments":
                chain.execute.return_value = payments_exec_result
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        sb = MagicMock()
        sb.table.side_effect = _table
        return sb

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_regenerates_link_on_existing_order_when_link_expired(self, mock_client_cls):
        # Caso (b): orden pending_payment vive, link >TTL → regenerar sobre
        # MISMA orden, NO crear orden nueva.
        sb = self._build_supabase_with_expired_link(
            order_id="order-stale-12345678", total_amount=2531.0,
        )

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        # Sólo UN POST esperado: regenerar link (no creación de orden)
        regen_resp = MagicMock()
        regen_resp.status_code = 200
        regen_resp.json.return_value = {
            "checkout_url": "https://checkout.wompi.co/l/plink-regen",
            "expires_at": "2026-05-04T22:30:00.000Z",
            "wompi_link_id": "plink-regen",
        }
        regen_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=regen_resp)
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Garzon",
            total_in_cents=253_100,
            shipping_cost_cents=7_310,
            notes=None,
            supabase=sb,
        )

        self.assertIsNotNone(result)
        # Misma orden, NUEVO link
        self.assertEqual(result.order_id, "order-stale-12345678")
        self.assertEqual(result.checkout_url, "https://checkout.wompi.co/l/plink-regen")
        # Una sola llamada al Core API (regenerar) — no se creó orden
        self.assertEqual(mock_client.post.await_count, 1)
        called_url = mock_client.post.await_args.args[0]
        self.assertIn("/api/v1/orders/order-stale-12345678/payment-link", called_url)
        # Mensaje informa expiración del link anterior
        self.assertIn("link anterior expiró", result.response_text.lower())
        self.assertIn("https://checkout.wompi.co/l/plink-regen", result.response_text)
        # amount_in_cents derivado de orders.total_amount (2531.0 → 253_100)
        self.assertEqual(result.amount_in_cents, 253_100)

    @patch("tools.payment_link_tool.SUPABASE_JWT_SECRET", "jwt-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_regenerate_failure_returns_none_no_duplicate(self, mock_client_cls):
        # Si regenerar falla (Wompi 503 o transient), NO crear orden nueva
        # — degrada a None (caller decide handoff). Plan A.0.1 prima sobre
        # disponibilidad: preferimos un fallback explícito a basura tx.
        sb = self._build_supabase_with_expired_link(
            order_id="order-stale-failregen", total_amount=2531.0,
        )

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        regen_resp = MagicMock()
        regen_resp.status_code = 503
        regen_resp.raise_for_status = MagicMock(side_effect=Exception("503"))
        mock_client.post = AsyncMock(return_value=regen_resp)
        mock_client_cls.return_value = mock_client

        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian",
            total_in_cents=253_100,
            shipping_cost_cents=7_310,
            notes=None,
            supabase=sb,
        )

        self.assertIsNone(result)
        # NO debe haber intento de crear orden nueva tras fallar la regeneración
        self.assertEqual(mock_client.post.await_count, 1)


if __name__ == "__main__":
    unittest.main()

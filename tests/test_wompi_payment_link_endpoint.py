"""
Tests del endpoint POST /api/v1/orders/{id}/payment-link.

Cubre:
- WOMPI_PRIVATE_KEY ausente → 503
- Pedido no encontrado → 404
- Estado inválido → 409
- Monto menor a $1.500 COP → 422
- Happy path: genera link, persiste en payments, actualiza orden
"""
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("WOMPI_PRIVATE_KEY_SANDBOX", "test-private-key")
os.environ.setdefault("WOMPI_ENV", "sandbox")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from fastapi import HTTPException
from routers import orders
import integrations.wompi_client as wompi_client_module


def _make_supabase_mock(state):
    supabase = MagicMock()

    def table_side_effect(name):
        query = MagicMock()
        if name == "orders":
            single_mock = MagicMock()
            single_mock.execute.return_value = types.SimpleNamespace(data=state.get("orders_single", None))
            eq_mock = MagicMock()
            eq_mock.single.return_value = single_mock
            eq_mock.eq.return_value = eq_mock  # chain multiple eq()
            select_mock = MagicMock()
            select_mock.eq.return_value = eq_mock
            query.select.return_value = select_mock
            query.update.return_value.eq.return_value.eq.return_value.execute.return_value = types.SimpleNamespace(
                data=state.get("orders_update", [])
            )
        elif name == "payments":
            query.insert.return_value.execute.return_value = types.SimpleNamespace(
                data=state.get("payments_insert", [])
            )
        else:
            raise AssertionError(f"Tabla inesperada: {name}")
        return query

    supabase.table.side_effect = table_side_effect
    return supabase


class WompiPaymentLinkEndpointTests(unittest.IsolatedAsyncioTestCase):
    @patch.object(wompi_client_module, "WOMPI_PRIVATE_KEY", "test-private-key")
    @patch.object(wompi_client_module, "create_payment_link", new_callable=AsyncMock)
    async def test_happy_path_generates_link_and_persists(self, mock_wompi_create):
        mock_wompi_create.return_value = {
            "link_id": "plink-123",
            "checkout_url": "https://checkout.wompi.co/l/plink-123",
            "active": True,
            "amount_in_cents": 200_000,
            "expires_at": "2026-04-24T20:00:00.000Z",
        }
        supabase = _make_supabase_mock({
            "orders_single": {
                "id": "order-123",
                "status": "pending",
                "total_amount": 2000.0,
                "shipping_cost": 0.0,
                "notes": "Test order",
                "contact_id": "contact-1",
                "contacts": {"name": "Cristian Garzon", "phone": "573001112233"},
            },
        })

        result = await orders.create_payment_link(
            order_id="order-123",
            tenant_id="tenant-1",
            supabase=supabase,
            _role="owner",
        )

        self.assertEqual(result["checkout_url"], "https://checkout.wompi.co/l/plink-123")
        self.assertEqual(result["order_id"], "order-123")
        mock_wompi_create.assert_awaited_once()
        # Verificar que se insertó en payments
        supabase.table.assert_any_call("payments")

    @patch.object(wompi_client_module, "WOMPI_PRIVATE_KEY", "test-private-key")
    @patch.object(wompi_client_module, "create_payment_link", new_callable=AsyncMock)
    async def test_order_not_found_raises_404(self, mock_wompi_create):
        supabase = _make_supabase_mock({"orders_single": None})

        with self.assertRaises(HTTPException) as ctx:
            await orders.create_payment_link(
                order_id="order-missing",
                tenant_id="tenant-1",
                supabase=supabase,
                _role="owner",
            )
        self.assertEqual(ctx.exception.status_code, 404)
        mock_wompi_create.assert_not_awaited()

    @patch.object(wompi_client_module, "WOMPI_PRIVATE_KEY", "test-private-key")
    @patch.object(wompi_client_module, "create_payment_link", new_callable=AsyncMock)
    async def test_invalid_status_raises_409(self, mock_wompi_create):
        supabase = _make_supabase_mock({
            "orders_single": {
                "id": "order-123",
                "status": "confirmed",
                "total_amount": 2000.0,
                "contacts": {"name": "Cristian"},
            },
        })

        with self.assertRaises(HTTPException) as ctx:
            await orders.create_payment_link(
                order_id="order-123",
                tenant_id="tenant-1",
                supabase=supabase,
                _role="owner",
            )
        self.assertEqual(ctx.exception.status_code, 409)
        mock_wompi_create.assert_not_awaited()

    @patch.object(wompi_client_module, "WOMPI_PRIVATE_KEY", "test-private-key")
    @patch.object(wompi_client_module, "create_payment_link", new_callable=AsyncMock)
    async def test_amount_below_minimum_raises_422(self, mock_wompi_create):
        supabase = _make_supabase_mock({
            "orders_single": {
                "id": "order-123",
                "status": "pending",
                "total_amount": 10.0,  # $10 COP
                "contacts": {"name": "Cristian"},
            },
        })

        with self.assertRaises(HTTPException) as ctx:
            await orders.create_payment_link(
                order_id="order-123",
                tenant_id="tenant-1",
                supabase=supabase,
                _role="owner",
            )
        self.assertEqual(ctx.exception.status_code, 422)
        mock_wompi_create.assert_not_awaited()

    @patch.object(wompi_client_module, "WOMPI_PRIVATE_KEY", "")
    async def test_missing_private_key_raises_503(self):
        supabase = _make_supabase_mock({
            "orders_single": {
                "id": "order-123",
                "status": "pending",
                "total_amount": 2000.0,
                "contacts": {"name": "Cristian"},
            },
        })

        with self.assertRaises(HTTPException) as ctx:
            await orders.create_payment_link(
                order_id="order-123",
                tenant_id="tenant-1",
                supabase=supabase,
                _role="owner",
            )
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()

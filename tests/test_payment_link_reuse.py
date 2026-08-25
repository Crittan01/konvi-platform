"""
Tests G3 — reuso de link de pago vigente en POST /api/v1/orders/{id}/payment-link.

El endpoint (services/api/routers/orders.py:create_payment_link) antes creaba
SIEMPRE link Wompi nuevo + fila payments nueva por llamada. Ahora espeja el
criterio de reuso del bot
(services/ai-orchestrator/tools/payment_link_tool.py:_find_pending_order):
payments de la orden con status='pending', created_at >= now - TTL
(payment_link_ttl_minutes(), default 30 min), más reciente primero, con
checkout_url no vacío → reusar SIN llamar a Wompi ni insertar fila.

Cubre:
(a) link pending vigente → reuso: 200 con el link existente, 0 llamadas a
    Wompi, 0 inserts en payments, 0 update de la orden.
(b) sin link vigente → creación normal (Wompi + insert payments).
(c) link expirado → la query gte(created_at, cutoff) lo excluye en DB →
    creación. Verifica que el filtro de cutoff usa el TTL correcto (~30 min).
(d) wiring: el endpoint declara Depends(RL_WRITE_DEFAULT) (rate-limit G3).

Patrón de mocks: `tests/helpers/supabase_mocks.py` (compartido; antes copia
local calcada de tests/test_wompi_payment_link_endpoint.py).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from routers import orders  # noqa: E402
from dependencies.security import RL_WRITE_DEFAULT  # noqa: E402
import integrations.wompi_client as wompi_client_module  # noqa: E402
from helpers.supabase_mocks import (  # noqa: E402
    make_orders_payments_supabase_mock as _make_supabase_mock,
)

_FAKE_CREDS = ("prv_test_fake_key", "test_events_fake_key", "sandbox")

_ORDER_PENDING = {
    "id": "order-123",
    "status": "pending",
    "total_amount": 2000.0,
    "shipping_cost": 0.0,
    "notes": "Test order",
    "contact_id": "contact-1",
    "contacts": {"name": "Cristian Garzon", "phone": "573001112233"},
}


class PaymentLinkReuseTests(unittest.IsolatedAsyncioTestCase):

    @patch.object(wompi_client_module, "get_tenant_wompi_creds", return_value=_FAKE_CREDS)
    @patch.object(
        wompi_client_module, "create_payment_link_with_resilience", new_callable=AsyncMock
    )
    async def test_a_reusa_link_vigente_sin_wompi_ni_insert(self, mock_wompi, _mock_creds):
        """(a) payments pending dentro del TTL con checkout_url → reuso.

        Responde el link existente (mismo shape que creación) y NO llama a
        Wompi, NO inserta fila payments y NO toca la orden."""
        created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        vigente = {
            "checkout_url": "https://checkout.wompi.co/l/plink-vigente",
            "wompi_link_id": "plink-vigente",
            "status": "pending",
            "created_at": created_at.isoformat(),
            "amount_in_cents": 200_000,
        }
        supabase, probes = _make_supabase_mock({
            "orders_single": dict(_ORDER_PENDING),
            "payments_select": [vigente],
        })

        result = await orders.create_payment_link(
            request=MagicMock(headers={}),
            order_id="order-123",
            tenant_id="tenant-1",
            supabase=supabase,
            _role="owner",
        )

        self.assertEqual(result["checkout_url"], "https://checkout.wompi.co/l/plink-vigente")
        self.assertEqual(result["wompi_link_id"], "plink-vigente")
        self.assertEqual(result["order_id"], "order-123")
        self.assertEqual(result["amount_in_cents"], 200_000)
        # expires_at derivado: created_at + TTL (mismo formato que la creación)
        expected_exp = (created_at + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.assertEqual(result["expires_at"], expected_exp)
        # La regla de dinero: ni Wompi ni fila nueva ni update de la orden
        mock_wompi.assert_not_awaited()
        probes["payments_insert"].assert_not_called()
        probes["orders_update"].assert_not_called()
        # El lookup de reuso sí consultó payments con los filtros del bot
        probes["payments_select"].execute.assert_called_once()
        probes["payments_select"].eq.assert_any_call("status", "pending")
        probes["payments_select"].eq.assert_any_call("order_id", "order-123")
        probes["payments_select"].eq.assert_any_call("tenant_id", "tenant-1")

    @patch.object(wompi_client_module, "get_tenant_wompi_creds", return_value=_FAKE_CREDS)
    @patch.object(
        wompi_client_module, "create_payment_link_with_resilience", new_callable=AsyncMock
    )
    async def test_b_sin_link_vigente_crea_normal(self, mock_wompi, _mock_creds):
        """(b) sin payments pending vigente → flujo de creación intacto."""
        mock_wompi.return_value = {
            "link_id": "plink-new",
            "checkout_url": "https://checkout.wompi.co/l/plink-new",
            "active": True,
            "amount_in_cents": 200_000,
            "expires_at": "2026-08-13T20:00:00.000Z",
        }
        supabase, probes = _make_supabase_mock({
            "orders_single": dict(_ORDER_PENDING),
            "payments_select": [],  # DB no devuelve link vigente
        })

        result = await orders.create_payment_link(
            request=MagicMock(headers={}),
            order_id="order-123",
            tenant_id="tenant-1",
            supabase=supabase,
            _role="owner",
        )

        self.assertEqual(result["checkout_url"], "https://checkout.wompi.co/l/plink-new")
        self.assertEqual(result["wompi_link_id"], "plink-new")
        mock_wompi.assert_awaited_once()
        # Se persistió la fila payments nueva (status pending, provider wompi)
        probes["payments_insert"].assert_called_once()
        inserted = probes["payments_insert"].call_args.args[0]
        self.assertEqual(inserted["status"], "pending")
        self.assertEqual(inserted["provider"], "wompi")
        self.assertEqual(inserted["order_id"], "order-123")
        self.assertEqual(inserted["wompi_link_id"], "plink-new")
        # Orden pending → se mueve a pending_payment (comportamiento existente)
        probes["orders_update"].assert_called()

    @patch.object(wompi_client_module, "get_tenant_wompi_creds", return_value=_FAKE_CREDS)
    @patch.object(
        wompi_client_module, "create_payment_link_with_resilience", new_callable=AsyncMock
    )
    async def test_c_link_expirado_crea_nuevo(self, mock_wompi, _mock_creds):
        """(c) link expirado → el filtro gte(created_at, cutoff) lo excluye en
        DB (la query devuelve vacío) → creación. Verifica que el cutoff es
        now - TTL (~30 min), la misma regla del bot."""
        mock_wompi.return_value = {
            "link_id": "plink-fresh",
            "checkout_url": "https://checkout.wompi.co/l/plink-fresh",
            "active": True,
            "amount_in_cents": 200_000,
            "expires_at": "2026-08-13T20:00:00.000Z",
        }
        # Hay una fila payments pero con created_at de hace 45 min (> TTL 30):
        # Postgres la filtra con el gte(cutoff) → data vacío.
        supabase, probes = _make_supabase_mock({
            "orders_single": dict(_ORDER_PENDING),
            "payments_select": [],
        })
        before = datetime.now(timezone.utc)

        result = await orders.create_payment_link(
            request=MagicMock(headers={}),
            order_id="order-123",
            tenant_id="tenant-1",
            supabase=supabase,
            _role="owner",
        )

        after = datetime.now(timezone.utc)
        self.assertEqual(result["checkout_url"], "https://checkout.wompi.co/l/plink-fresh")
        mock_wompi.assert_awaited_once()
        probes["payments_insert"].assert_called_once()
        # El filtro de expiración existe y usa el TTL: cutoff ∈ [antes-30m, después-30m]
        probes["payments_select"].gte.assert_called_once()
        field, cutoff_raw = probes["payments_select"].gte.call_args.args
        self.assertEqual(field, "created_at")
        cutoff = datetime.fromisoformat(cutoff_raw)
        self.assertLessEqual(cutoff, after - timedelta(minutes=29))
        self.assertGreaterEqual(cutoff, before - timedelta(minutes=31))


class PaymentLinkRateLimitWiringTests(unittest.TestCase):
    """(d) G3 — create_payment_link declara Depends(RL_WRITE_DEFAULT) como
    parámetro (patrón de este archivo; create_order/patch_order lo hacen igual)."""

    def test_endpoint_tiene_rl_write_default(self):
        import inspect

        from fastapi.params import Depends as DependsParam

        sig = inspect.signature(orders.create_payment_link)
        deps = [
            p.default.dependency
            for p in sig.parameters.values()
            if isinstance(p.default, DependsParam)
        ]
        self.assertIn(
            RL_WRITE_DEFAULT, deps,
            "create_payment_link sin Depends(RL_WRITE_DEFAULT) — rate-limit G3 ausente",
        )


class PaymentLinkIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    """G3 follow-up — Idempotency-Key en payment-link (patrón de create_order).

    Se parchean begin/finalize/abort en el namespace del router (allí se
    importaron) para verificar el CABLEADO sin tocar la tabla idempotency_keys.
    """

    @patch("routers.orders.begin_idempotency")
    async def test_replay_responde_sin_efectos(self, mock_begin):
        """Con key + replay registrado → JSONResponse del replay, sin Wompi ni DB."""
        mock_begin.return_value = (
            MagicMock(),  # sesión viva
            {"status_code": 200, "body": {"order_id": "order-123", "checkout_url": "https://replay"}},
        )
        req = MagicMock(headers={"Idempotency-Key": "k-replay"})
        result = await orders.create_payment_link(
            request=req,
            order_id="order-123",
            tenant_id="tenant-1",
            supabase=MagicMock(),
            _role="owner",
        )
        # JSONResponse con el body del replay
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers.get("Idempotency-Replayed"), "true")
        mock_begin.assert_called_once()

    @patch("routers.orders.finalize_idempotency")
    @patch("routers.orders.begin_idempotency")
    @patch.object(wompi_client_module, "get_tenant_wompi_creds", return_value=_FAKE_CREDS)
    @patch.object(
        wompi_client_module, "create_payment_link_with_resilience", new_callable=AsyncMock
    )
    async def test_sin_replay_crea_y_finaliza(self, mock_wompi, _creds, mock_begin, mock_finalize):
        """Con key pero sin replay → flujo normal; finalize con 200 al crear."""
        mock_begin.return_value = (MagicMock(), None)  # sesión nueva, sin replay
        mock_wompi.return_value = {
            "link_id": "plink-new",
            "checkout_url": "https://checkout.wompi.co/l/plink-new",
        }
        supabase, _probes = _make_supabase_mock({
            "orders_single": dict(_ORDER_PENDING),
            "payments_select": [],
        })
        req = MagicMock(headers={"Idempotency-Key": "k-new"})
        result = await orders.create_payment_link(
            request=req,
            order_id="order-123",
            tenant_id="tenant-1",
            supabase=supabase,
            _role="owner",
        )
        self.assertEqual(result["wompi_link_id"], "plink-new")
        mock_finalize.assert_called_once()
        kwargs = mock_finalize.call_args.kwargs
        self.assertEqual(kwargs["status_code"], 200)
        self.assertEqual(kwargs["body"]["wompi_link_id"], "plink-new")

    @patch("routers.orders.abort_idempotency")
    @patch("routers.orders.begin_idempotency")
    async def test_error_aborta_sesion(self, mock_begin, mock_abort):
        """Fallo del handler (404 orden inexistente) → abort de la sesión."""
        mock_begin.return_value = (MagicMock(), None)
        supabase, _probes = _make_supabase_mock({
            "orders_single": None,  # orden no encontrada
            "payments_select": [],
        })
        req = MagicMock(headers={"Idempotency-Key": "k-404"})
        with self.assertRaises(Exception):  # HTTPException 404
            await orders.create_payment_link(
                request=req,
                order_id="order-inexistente",
                tenant_id="tenant-1",
                supabase=supabase,
                _role="owner",
            )
        mock_abort.assert_called_once()


if __name__ == "__main__":
    unittest.main()

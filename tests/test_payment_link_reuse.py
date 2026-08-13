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

Patrón de mocks: mismo que tests/test_wompi_payment_link_endpoint.py.
"""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from routers import orders  # noqa: E402
from dependencies.security import RL_WRITE_DEFAULT  # noqa: E402
import integrations.wompi_client as wompi_client_module  # noqa: E402

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


def _make_supabase_mock(state):
    """Mock de supabase con cadenas explícitas inspeccionables.

    Devuelve (supabase, probes) donde probes expone:
      - payments_select: cadena select().eq().eq().eq().gte().order().limit().execute()
      - payments_insert: método insert de la tabla payments
      - orders_update:   método update de la tabla orders
    """
    supabase = MagicMock()

    orders_q = MagicMock(name="orders_table")
    single = MagicMock()
    single.execute.return_value = types.SimpleNamespace(data=state.get("orders_single"))
    eq_chain = MagicMock()
    eq_chain.maybe_single.return_value = single
    eq_chain.single.return_value = single
    eq_chain.eq.return_value = eq_chain
    select_chain = MagicMock()
    select_chain.eq.return_value = eq_chain
    orders_q.select.return_value = select_chain
    upd = MagicMock()
    upd.eq.return_value = upd
    upd.execute.return_value = types.SimpleNamespace(data=state.get("orders_update", []))
    orders_q.update.return_value = upd

    payments_q = MagicMock(name="payments_table")
    sel = MagicMock(name="payments_select_chain")
    sel.eq.return_value = sel
    sel.gte.return_value = sel
    sel.order.return_value = sel
    sel.limit.return_value = sel
    sel.execute.return_value = types.SimpleNamespace(
        data=state.get("payments_select", [])
    )
    payments_q.select.return_value = sel
    ins_execute = MagicMock()
    ins_execute.execute.return_value = types.SimpleNamespace(
        data=state.get("payments_insert", [])
    )
    payments_q.insert.return_value = ins_execute

    def table_side_effect(name):
        if name == "orders":
            return orders_q
        if name == "payments":
            return payments_q
        raise AssertionError(f"Tabla inesperada: {name}")

    supabase.table.side_effect = table_side_effect
    probes = {
        "payments_select": sel,
        "payments_insert": payments_q.insert,
        "orders_update": orders_q.update,
    }
    return supabase, probes


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
            request=MagicMock(),
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
            request=MagicMock(),
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
            request=MagicMock(),
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


if __name__ == "__main__":
    unittest.main()

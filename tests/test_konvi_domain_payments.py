"""Tests unitarios de konvi_domain.orders.payments (Track 5 M2.3).

Verifican la política de payment link extraída intacta del router
(services/api/routers/orders.py:create_payment_link histórico):

  1. TTL helper — default/override/fail-safe (fuente única de la política).
  2. payment_link_expires_at — derivación created_at + TTL, degradación a ''.
  3. validate_link_amount — round NO int (BLOQUE A) + mínimo $1.500 exacto.
  4. find_reusable_payment_link — criterio de reuso + degradación a crear.
  5. get_or_create_payment_link — orden de pasos heredado (creds→orden→status→
     reuso→monto→crear→insert→flip) con puertos falsos; reuso sin efectos;
     eventos y errores tipados (503/404/409/422 vía http_status/code).

Mocks: `make_orders_payments_supabase_mock` de tests/helpers/supabase_mocks.py
(las factories compartidas viven en helpers — un import test→test de un módulo
con side effects de colección dejó bindings huérfanos de sys.modules bajo
xdist; lección M2.3).
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from konvi_domain import Actor, Channel, DomainError, ErrorCode, Role  # noqa: E402
from konvi_domain.orders import payments as svc  # noqa: E402
from konvi_domain.orders.payments import PaymentLinkPorts  # noqa: E402
from helpers.supabase_mocks import (  # noqa: E402
    make_orders_payments_supabase_mock as _make_supabase_mock,
)

_ACTOR = Actor(channel=Channel.CONSOLE, tenant_id="tenant-1", role=Role.OWNER)

_ORDER_PENDING = {
    "id": "order-123",
    "status": "pending",
    "total_amount": 2000.0,
    "shipping_cost": 0.0,
    "notes": "Test order",
    "contact_id": "contact-1",
    "contacts": {"name": "Cristian Garzon", "phone": "573001112233"},
}

_LINK_DATA = {
    "link_id": "plink-new",
    "checkout_url": "https://checkout.wompi.co/l/plink-new",
    "active": True,
    "amount_in_cents": 200_000,
    "expires_at": "2026-08-25T20:00:00.000Z",
}


def _ports(creds=("prv_test", "sandbox"), create_mock=None):
    return PaymentLinkPorts(
        wompi_credentials=lambda _tid: creds,
        create_link=create_mock or AsyncMock(return_value=dict(_LINK_DATA)),
    )


class TtlHelperTests(unittest.TestCase):
    def test_default_sin_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WOMPI_PAYMENT_LINK_TTL_MINUTES", None)
            self.assertEqual(svc.payment_link_ttl_minutes(), 30)
            self.assertEqual(svc.DEFAULT_PAYMENT_LINK_TTL_MINUTES, 30)

    def test_override_y_failsafe(self):
        with patch.dict(os.environ, {"WOMPI_PAYMENT_LINK_TTL_MINUTES": "45"}):
            self.assertEqual(svc.payment_link_ttl_minutes(), 45)
        for bad in ("abc", "0", "-5"):
            with self.subTest(bad=bad), \
                 patch.dict(os.environ, {"WOMPI_PAYMENT_LINK_TTL_MINUTES": bad}):
                self.assertEqual(svc.payment_link_ttl_minutes(), 30)


class ExpiresAtTests(unittest.TestCase):
    def test_created_at_mas_ttl_formato_creacion(self):
        created = datetime(2026, 8, 25, 15, 0, 0, tzinfo=timezone.utc)
        out = svc.payment_link_expires_at(created.isoformat())
        self.assertEqual(out, "2026-08-25T15:30:00.000Z")

    def test_no_parseable_degrada_a_vacio(self):
        for bad in ("", None, "no-es-fecha", 123):
            with self.subTest(bad=str(bad)):
                self.assertEqual(svc.payment_link_expires_at(bad), "")


class AmountTests(unittest.TestCase):
    def test_round_no_trunca(self):
        # BLOQUE A: 20004.10*100 == 2000409.9999999998 → int trunca 1 cent.
        self.assertEqual(svc.amount_to_cents(20004.10), 2_000_410)

    def test_minimo_exacto(self):
        self.assertEqual(svc.validate_link_amount(1500.0), 150_000)
        with self.assertRaises(DomainError) as ctx:
            svc.validate_link_amount(10.0)
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)
        self.assertEqual(
            ctx.exception.message,
            "Monto mínimo Wompi es $1.500 COP. Monto actual: $10",
        )


class FindReusableTests(unittest.TestCase):
    def test_filtros_exactos_del_criterio(self):
        supabase, probes = _make_supabase_mock({"payments_select": []})
        svc.find_reusable_payment_link(supabase, tenant_id="tenant-1", order_id="order-123")
        probes["payments_select"].eq.assert_any_call("tenant_id", "tenant-1")
        probes["payments_select"].eq.assert_any_call("order_id", "order-123")
        probes["payments_select"].eq.assert_any_call("status", "pending")
        probes["payments_select"].gte.assert_called_once()
        field, _cutoff = probes["payments_select"].gte.call_args.args
        self.assertEqual(field, "created_at")

    def test_solo_reusa_con_checkout_url(self):
        row = {"checkout_url": "", "wompi_link_id": "x", "status": "pending"}
        supabase, _ = _make_supabase_mock({"payments_select": [row]})
        self.assertIsNone(
            svc.find_reusable_payment_link(supabase, tenant_id="t", order_id="o")
        )

    def test_lookup_fallido_degrada_a_none(self):
        supabase, probes = _make_supabase_mock({"payments_select": []})
        probes["payments_select"].execute.side_effect = Exception("db down")
        self.assertIsNone(
            svc.find_reusable_payment_link(supabase, tenant_id="t", order_id="o")
        )


class GetOrCreateLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_sin_credenciales_503_tipado(self):
        supabase, _ = _make_supabase_mock({})
        with self.assertRaises(DomainError) as ctx:
            await svc.get_or_create_payment_link(
                supabase, tenant_id="tenant-1", order_id="order-123",
                actor=_ACTOR, ports=_ports(creds=None),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.UPSTREAM)
        self.assertEqual(ctx.exception.http_status, 503)
        self.assertEqual(
            ctx.exception.message,
            "Integración Wompi no configurada. Conéctala en Ajustes → Integraciones.",
        )

    async def test_pedido_no_encontrado_404(self):
        supabase, _ = _make_supabase_mock({"orders_single": None})
        with self.assertRaises(DomainError) as ctx:
            await svc.get_or_create_payment_link(
                supabase, tenant_id="tenant-1", order_id="order-x",
                actor=_ACTOR, ports=_ports(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)
        self.assertEqual(ctx.exception.message, "Pedido no encontrado")

    async def test_estado_invalido_409(self):
        supabase, _ = _make_supabase_mock({
            "orders_single": {**_ORDER_PENDING, "status": "confirmed"},
        })
        with self.assertRaises(DomainError) as ctx:
            await svc.get_or_create_payment_link(
                supabase, tenant_id="tenant-1", order_id="order-123",
                actor=_ACTOR, ports=_ports(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.PRECONDITION)
        self.assertEqual(
            ctx.exception.message,
            "El pedido está en estado 'confirmed' — solo se puede generar link "
            "para pedidos pending o pending_payment",
        )

    async def test_reuso_sin_efectos(self):
        """Link vigente → reused=True: sin Wompi, sin insert, sin update, y el
        expires_at se deriva created_at + TTL. El guard de monto NO aplica."""
        created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        vigente = {
            "checkout_url": "https://checkout.wompi.co/l/plink-vigente",
            "wompi_link_id": "plink-vigente",
            "status": "pending",
            "created_at": created_at.isoformat(),
            "amount_in_cents": 200_000,
        }
        create_mock = AsyncMock(return_value=dict(_LINK_DATA))
        # total_amount por DEBAJO del mínimo: la rama de reuso lo salta.
        supabase, probes = _make_supabase_mock({
            "orders_single": {**_ORDER_PENDING, "total_amount": 10.0},
            "payments_select": [vigente],
        })

        outcome = await svc.get_or_create_payment_link(
            supabase, tenant_id="tenant-1", order_id="order-123",
            actor=_ACTOR, ports=_ports(create_mock=create_mock),
        )

        self.assertTrue(outcome.reused)
        self.assertEqual(outcome.checkout_url, "https://checkout.wompi.co/l/plink-vigente")
        self.assertEqual(outcome.amount_in_cents, 200_000)
        expected_exp = (created_at + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.assertEqual(outcome.expires_at, expected_exp)
        self.assertEqual(outcome.events, ())
        create_mock.assert_not_awaited()
        probes["payments_insert"].assert_not_called()
        probes["orders_update"].assert_not_called()
        # body() conserva el shape REST heredado
        self.assertEqual(
            set(outcome.body().keys()),
            {"order_id", "checkout_url", "amount_in_cents", "expires_at", "wompi_link_id"},
        )

    async def test_creacion_happy_path(self):
        """Sin link vigente → crea en Wompi con los kwargs exactos heredados,
        inserta payments (pending/ACTIVE), flipea la orden y emite el evento."""
        create_mock = AsyncMock(return_value=dict(_LINK_DATA))
        supabase, probes = _make_supabase_mock({
            "orders_single": dict(_ORDER_PENDING),
            "payments_select": [],
        })

        outcome = await svc.get_or_create_payment_link(
            supabase, tenant_id="tenant-1", order_id="order-123",
            actor=_ACTOR, ports=_ports(create_mock=create_mock),
        )

        self.assertFalse(outcome.reused)
        kwargs = create_mock.await_args.kwargs
        self.assertEqual(kwargs["private_key"], "prv_test")
        self.assertEqual(kwargs["environment"], "sandbox")
        self.assertEqual(kwargs["order_id"], "order-123")
        self.assertEqual(kwargs["name"], "Pedido #ORDER-12 — Cristian Garzon")
        self.assertEqual(kwargs["description"], "Test order")
        self.assertEqual(kwargs["amount_in_cents"], 200_000)
        self.assertRegex(kwargs["expires_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$")
        self.assertEqual(kwargs["contact"], _ORDER_PENDING["contacts"])

        inserted = probes["payments_insert"].call_args.args[0]
        self.assertEqual(inserted["provider"], "wompi")
        self.assertEqual(inserted["status"], "pending")
        self.assertEqual(inserted["wompi_status"], "ACTIVE")
        self.assertEqual(inserted["currency"], "COP")
        self.assertEqual(inserted["wompi_link_id"], "plink-new")
        self.assertEqual(inserted["amount_in_cents"], 200_000)
        # orden pending → flip a pending_payment
        probes["orders_update"].assert_called()
        # evento de dominio obligatorio en escritura
        self.assertEqual(len(outcome.events), 1)
        self.assertEqual(outcome.events[0].name, "payment.link_created")
        self.assertEqual(outcome.events[0].payload["order_id"], "order-123")
        self.assertEqual(outcome.events[0].payload["channel"], "console")

    async def test_creacion_en_pending_payment_no_duplica_flip(self):
        create_mock = AsyncMock(return_value=dict(_LINK_DATA))
        supabase, probes = _make_supabase_mock({
            "orders_single": {**_ORDER_PENDING, "status": "pending_payment", "notes": None},
            "payments_select": [],
        })

        await svc.get_or_create_payment_link(
            supabase, tenant_id="tenant-1", order_id="order-123",
            actor=_ACTOR, ports=_ports(create_mock=create_mock),
        )

        probes["orders_update"].assert_not_called()
        # description cae al fallback "Pedido #<short>" cuando notes es None
        self.assertEqual(
            create_mock.await_args.kwargs["description"], "Pedido #ORDER-12"
        )


if __name__ == "__main__":
    unittest.main()

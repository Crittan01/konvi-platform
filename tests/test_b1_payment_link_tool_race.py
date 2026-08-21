"""B1 (auditoría money-path 2026-08-21) — payment_link_tool: adopt-winner del lado
del orquestador + Idempotency-Key determinístico hacia el API.

Cubre (services/ai-orchestrator/tools/payment_link_tool.py):
  • Create POST falla (409 idempotency in-flight / carrera) y YA existe una
    orden pending_payment (la ganadora de otro turno) → se adopta: se reusa su
    link vigente o se regenera sobre ella. NUNCA se reintenta el insert.
  • Ganadora con monto stale (cart cambió) → se invalida y se degrada (None).
  • Create POST lleva Idempotency-Key determinístico por conversación+versión
    de cart (misma versión → misma key; versión distinta → key distinta).
  • Payment-link POST lleva Idempotency-Key plink:{order_id}:b<bucket>.
"""
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("INTERNAL_SERVICE_SECRET", "internal-secret")
os.environ.setdefault("API_URL", "http://localhost:8001")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools import payment_link_tool  # noqa: E402

_WINNER = {
    "id": "99999999-8888-7777-6666-555555555555",
    "total_amount": 2000.0,
    "status": "pending_payment",
    "created_at": "2026-08-21T10:00:00+00:00",
}
_CART = {"id": "cart-1", "updated_at": "2026-08-21T10:00:00+00:00"}


class _Chain:
    def __init__(self, ctrl, table):
        self.ctrl, self.table, self.cols, self._single = ctrl, table, "", False

    def select(self, cols="*", *a, **k):
        self.cols = cols
        return self

    def update(self, data, *a, **k):
        self.ctrl.updates.append((self.table, data))
        return self

    def insert(self, rows, *a, **k):
        return self

    def delete(self):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.ctrl._exec(self.table, self.cols, self._single))


class _Ctrl:
    """Supabase falso para el tool: secuencia de respuestas de `orders` (cada
    llamada a _find_pending_order consume una), cart fijo, payments configurable."""

    def __init__(self, *, cart=_CART, orders_sequence=None, payments_rows=None,
                 cart_payment="credit"):
        self.cart = cart
        self.orders_sequence = list(orders_sequence or [])
        self.payments_rows = payments_rows or []
        self.cart_payment = cart_payment
        self.updates = []  # (tabla, data) — invalidaciones capturadas

    def table(self, name):
        return _Chain(self, name)

    def rpc(self, *a, **k):
        return MagicMock(execute=MagicMock(return_value=types.SimpleNamespace(data=[])))

    def _exec(self, table, cols, single):
        if table == "orders" and "id, total_amount, status, created_at" in cols:
            rows = self.orders_sequence.pop(0) if self.orders_sequence else []
            return rows
        if table == "payments" and "checkout_url" in cols:
            return self.payments_rows
        if table == "conversation_carts":
            if "requires_requote" in cols:
                return []
            if "updated_at" in cols:
                return [self.cart] if self.cart else []
            if "payment_method" in cols:
                return {"payment_method": self.cart_payment}
            if "shipping_meta" in cols:
                return {"shipping_meta": {}}
            return []  # get_cart_with_items u otros selects → sin cart
        return []


def _http_stack(post_side_effects):
    """Mock de httpx.AsyncClient con una secuencia de respuestas POST."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=post_side_effects)
    factory = MagicMock(return_value=mock_client)
    return mock_client, factory


def _resp(status, body=None, *, raise_error=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    if raise_error:
        r.raise_for_status = MagicMock(side_effect=raise_error)
    else:
        r.raise_for_status = MagicMock()
    return r


_BASE_KW = dict(
    tenant_id="tenant-1",
    contact_id="contact-1",
    conversation_id="conv-1",
    contact_name="Cristian Garzon",
    total_in_cents=200_000,
    shipping_cost_cents=10_000,
    notes=None,
)


class AdoptWinnerToolTests(unittest.IsolatedAsyncioTestCase):
    """La creación choca con la orden ganadora → se adopta, nunca se duplica."""

    @patch("tools.payment_link_tool.INTERNAL_SERVICE_SECRET", "internal-secret")
    async def test_create_conflict_adopts_winner_reusing_active_link(self):
        recent = datetime.now(timezone.utc).isoformat()
        sb = _Ctrl(
            orders_sequence=[
                [],        # lookup inicial: aún no hay orden (la carrera)
                [_WINNER],  # lookup post-fallo: la ganadora ya existe
            ],
            payments_rows=[{
                "checkout_url": "https://checkout.wompi.co/l/plink-winner",
                "wompi_link_id": "plink-winner", "status": "pending",
                "created_at": recent, "amount_in_cents": 200_000,
            }],
        )
        create_resp = _resp(409, raise_error=Exception(
            "409 Ya existe una solicitud en proceso con este Idempotency-Key"))
        mock_client, factory = _http_stack([create_resp])
        with patch("tools.payment_link_tool.httpx.AsyncClient", factory):
            result = await payment_link_tool.handle_payment_link_if_applicable(
                supabase=sb, **_BASE_KW,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result.order_id, _WINNER["id"])
        self.assertEqual(
            result.checkout_url, "https://checkout.wompi.co/l/plink-winner",
        )
        # UN solo POST HTTP (el create fallido): NO hubo segundo insert ni
        # llamada a payment-link (el link vigente se reusó).
        self.assertEqual(mock_client.post.await_count, 1)

    @patch("tools.payment_link_tool.INTERNAL_SERVICE_SECRET", "internal-secret")
    async def test_create_conflict_adopts_winner_regenerating_expired_link(self):
        sb = _Ctrl(
            orders_sequence=[[], [_WINNER]],
            payments_rows=[],  # ganadora sin link vigente (>TTL)
        )
        create_resp = _resp(500, raise_error=Exception("500 tras insert remoto"))
        regen_resp = _resp(200, {
            "checkout_url": "https://checkout.wompi.co/l/plink-regen",
            "expires_at": "2026-08-21T11:00:00.000Z",
        })
        mock_client, factory = _http_stack([create_resp, regen_resp])
        with patch("tools.payment_link_tool.httpx.AsyncClient", factory):
            result = await payment_link_tool.handle_payment_link_if_applicable(
                supabase=sb, **_BASE_KW,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result.order_id, _WINNER["id"])
        self.assertEqual(
            result.checkout_url, "https://checkout.wompi.co/l/plink-regen",
        )
        # 2 POSTs: create fallido + regen sobre la orden GANADORA (no nueva).
        self.assertEqual(mock_client.post.await_count, 2)
        regen_url = mock_client.post.await_args.args[0]
        self.assertIn(f"/api/v1/orders/{_WINNER['id']}/payment-link", regen_url)

    @patch("tools.payment_link_tool.INTERNAL_SERVICE_SECRET", "internal-secret")
    async def test_create_conflict_winner_stale_amount_invalidates_and_degrades(self):
        stale_winner = {**_WINNER, "total_amount": 1500.0}  # ≠ cart actual
        sb = _Ctrl(
            orders_sequence=[[], [stale_winner]],
            payments_rows=[],  # sin link → monto se lee de total_amount
        )
        create_resp = _resp(409, raise_error=Exception("409 in-flight"))
        mock_client, factory = _http_stack([create_resp])
        with patch("tools.payment_link_tool.httpx.AsyncClient", factory):
            result = await payment_link_tool.handle_payment_link_if_applicable(
                supabase=sb, **_BASE_KW,
            )
        self.assertIsNone(result)
        # La ganadora stale quedó cancelada + sus payments voided.
        order_updates = [u for u in sb.updates if u[0] == "orders"]
        payment_updates = [u for u in sb.updates if u[0] == "payments"]
        self.assertTrue(order_updates and order_updates[0][1]["status"] == "cancelled")
        self.assertTrue(payment_updates and payment_updates[0][1]["status"] == "voided")

    @patch("tools.payment_link_tool.INTERNAL_SERVICE_SECRET", "internal-secret")
    async def test_create_fails_without_winner_returns_none(self):
        """Sin ganadora visible (fallo real del API) → None, como antes."""
        sb = _Ctrl(orders_sequence=[[], []])
        create_resp = _resp(500, raise_error=Exception("500"))
        mock_client, factory = _http_stack([create_resp])
        with patch("tools.payment_link_tool.httpx.AsyncClient", factory):
            result = await payment_link_tool.handle_payment_link_if_applicable(
                supabase=sb, **_BASE_KW,
            )
        self.assertIsNone(result)
        self.assertEqual(mock_client.post.await_count, 1)


class IdempotencyKeyToolTests(unittest.IsolatedAsyncioTestCase):
    """Idempotency-Key determinístico por conversación + versión de cart."""

    async def _run_happy_path(self, cart):
        sb = _Ctrl(cart=cart, orders_sequence=[[]])
        create_resp = _resp(201, {"id": "order-new-123"})
        link_resp = _resp(200, {
            "checkout_url": "https://checkout.wompi.co/l/plink-new",
            "expires_at": "",
        })
        mock_client, factory = _http_stack([create_resp, link_resp])
        with patch("tools.payment_link_tool.INTERNAL_SERVICE_SECRET", "internal-secret"), \
             patch("tools.payment_link_tool.httpx.AsyncClient", factory):
            result = await payment_link_tool.handle_payment_link_if_applicable(
                supabase=sb, **_BASE_KW,
            )
        self.assertIsNotNone(result)
        return [c.kwargs.get("headers", {}) for c in mock_client.post.await_args_list]

    async def test_create_y_link_llevan_idempotency_key(self):
        headers_list = await self._run_happy_path(_CART)
        self.assertEqual(len(headers_list), 2)
        create_key = headers_list[0].get("Idempotency-Key", "")
        link_key = headers_list[1].get("Idempotency-Key", "")
        self.assertTrue(create_key.startswith("ordc:conv-1:"), create_key)
        self.assertTrue(link_key.startswith("plink:order-new-123:b"), link_key)
        # Charset del contrato dependencies/idempotency.py: [A-Za-z0-9:_-]{8,128}
        import re
        self.assertRegex(create_key, r"^[A-Za-z0-9:_-]{8,128}$")
        self.assertRegex(link_key, r"^[A-Za-z0-9:_-]{8,128}$")

    async def test_misma_version_de_cart_misma_key(self):
        k1 = (await self._run_happy_path(_CART))[0]["Idempotency-Key"]
        k2 = (await self._run_happy_path(_CART))[0]["Idempotency-Key"]
        self.assertEqual(k1, k2, "misma versión de cart → retry replaya")

    async def test_cart_mutado_genera_key_nueva(self):
        k1 = (await self._run_happy_path(_CART))[0]["Idempotency-Key"]
        cart_v2 = {**_CART, "updated_at": "2026-08-21T10:05:00+00:00"}
        k2 = (await self._run_happy_path(cart_v2))[0]["Idempotency-Key"]
        self.assertNotEqual(k1, k2, "cart mutado → operación nueva, no replay")


if __name__ == "__main__":
    unittest.main()

"""Tests del adaptador consola → pipeline unificado de cancelación (M2.2).

patch_order con status=cancelled ahora ejecuta el pipeline legal completo
(`konvi_domain.orders.cancellation`) con los puertos del servicio API:
  • RBAC heredado: operator no cancela (403) — la guarda es del adaptador.
  • Cancelación de una orden confirmed: audit order_cancellations + orders
    cancelled + restock + respuesta con resumen de la cancelación.
  • Notificaciones: WhatsApp al cliente (si hay conversación) + Telegram al
    operador cuando el refund queda manual.
  • Idempotencia: cancelar una orden ya cancelada no duplica efectos.

Fake `_Sb` stateful reutilizado de tests/test_order_cancellation_pipeline.py.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")

_API = Path(__file__).resolve().parents[1] / "services" / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))
_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from fastapi import HTTPException  # noqa: E402
from routers import orders as orders_mod  # noqa: E402
from routers.orders import OrderPatch  # noqa: E402
from test_order_cancellation_pipeline import ORDER, _Sb  # noqa: E402


class _SbLive(_Sb):
    """_Sb + updates que SÍ mutan las filas staged (PostgREST devuelve la fila
    actualizada en producción; el fake base solo las registra)."""

    def _exec(self, q):
        res = super()._exec(q)
        if q._op == "update":
            for r in self._tables.get(q._table, []):
                if all(str(r.get(c)) == str(v) for op, c, v in q._filters if op == "eq"):
                    r.update(q._payload)
        return res

_REQ = types.SimpleNamespace(
    headers={}, method="PATCH",
    url=types.SimpleNamespace(path="/api/v1/orders/order-1"),
    client=types.SimpleNamespace(host="127.0.0.1"),
)


def _patch_cancel(**kw):
    base = dict(
        order_id="order-1", patch=OrderPatch(status="cancelled"), request=_REQ,
        tenant_id="t1", role="owner", _mfa=None, _rl=None, _user_id="u-1",
    )
    base.update(kw)
    return orders_mod.patch_order(**base)


class CancelAdapterRbacTests(unittest.TestCase):
    def test_operator_no_puede_cancelar(self):
        """La guarda RBAC del adaptador sigue: operator → 403 antes del pipeline."""
        sb = _Sb({"orders": [dict(ORDER)]})
        with self.assertRaises(HTTPException) as ctx:
            _patch_cancel(supabase=sb, role="operator")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("owner o manager", ctx.exception.detail)
        # Nada se tocó: sin updates ni inserts.
        self.assertEqual(sb.updates, [])
        self.assertEqual(sb.inserts, [])

    def test_rol_desconocido_403(self):
        sb = _Sb({"orders": [dict(ORDER)]})
        with self.assertRaises(HTTPException) as ctx:
            _patch_cancel(supabase=sb, role="viewer")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_pedido_inexistente_404(self):
        sb = _Sb({"orders": []})
        with self.assertRaises(HTTPException) as ctx:
            _patch_cancel(supabase=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_transicion_invalida_409(self):
        """delivered es terminal: ni el pipeline ni la consola reabren."""
        sb = _Sb({"orders": [dict(ORDER, status="delivered")]})
        with self.assertRaises(HTTPException) as ctx:
            _patch_cancel(supabase=sb)
        self.assertEqual(ctx.exception.status_code, 409)


class CancelAdapterPipelineTests(unittest.TestCase):
    """El adaptador ejecuta el pipeline completo con puertos API (void/guía
    no disparan en estos escenarios — sin pago CARD ni guía real)."""

    def test_cancel_confirmed_pipeline_completo(self):
        sb = _SbLive({
            "orders": [dict(ORDER)],
            "conversations": [{"id": "conv-1", "tenant_id": "t1", "customer_phone": "+573001234567"}],
            "stock_movements": [{
                "variation_id": "v1", "delta": -2, "tenant_id": "t1",
                "order_id": "order-1", "reason": "sale",
            }],
        })
        with patch("lib.order_cancel_ports.notify_operator_telegram") as tg:
            resp = _patch_cancel(supabase=sb)

        # Auditoría SIC creada con actor staff + user_id.
        audit = [p for t, p in sb.inserts if t == "order_cancellations"]
        self.assertEqual(len(audit), 1)
        # Enum DB order_cancellation_actor: staff de consola = 'operator'
        # (la granularidad owner/manager vive en cancelled_by_user_id).
        self.assertEqual(audit[0]["cancelled_by_actor"], "operator")
        self.assertEqual(audit[0]["cancelled_by_user_id"], "u-1")
        self.assertEqual(audit[0]["reason_code"], "operator_console")
        self.assertEqual(audit[0]["legal_basis"], "ley_1480_estatuto_consumidor")
        # Orden cancelada por el pipeline (no por un flip del adaptador).
        upd_orders = [p for t, p, _f in sb.updates if t == "orders"]
        self.assertTrue(any(p.get("status") == "cancelled" for p in upd_orders))
        self.assertTrue(any("cancellation_id" in p for p in upd_orders))
        # Restock vía RPC idempotente (reason canónica).
        self.assertIn(
            ("rpc_stock_restore", {
                "p_tenant_id": "t1", "p_variation_id": "v1", "p_qty": 2,
                "p_order_id": "order-1", "p_reason": "cancellation_refund",
            }),
            sb.rpc_calls,
        )
        # Respuesta: fila + resumen de la cancelación para la UI.
        self.assertEqual(resp["status"], "cancelled")
        self.assertIn("cancellation", resp)
        self.assertEqual(resp["cancellation"]["status"], "completed")
        # Sin pago → sin refund → sin Telegram de refund manual.
        tg.assert_not_called()
        # Cliente notificado por WhatsApp (la orden tiene conversation_id).
        wa_msgs = [p for t, p in sb.inserts if t == "messages"]
        self.assertEqual(len(wa_msgs), 1)
        self.assertIn("cancelé tu pedido", wa_msgs[0]["content"])
        self.assertTrue(
            any(name == "enqueue_whatsapp_outbound_message" for name, _ in sb.rpc_calls),
        )

    def test_cancel_idempotente_orden_ya_cancelada(self):
        sb = _SbLive({"orders": [dict(ORDER, status="cancelled")]})
        with patch("lib.order_cancel_ports.notify_operator_telegram") as tg:
            resp = _patch_cancel(supabase=sb)
        # Sin nueva fila de auditoría ni re-efectos.
        self.assertEqual([p for t, p in sb.inserts if t == "order_cancellations"], [])
        self.assertEqual(sb.rpc_calls, [])
        tg.assert_not_called()
        self.assertEqual(resp["status"], "cancelled")
        self.assertEqual(resp["cancellation"]["status"], "completed")

    def test_triage_de_staff_se_registra_pero_no_bloquea(self):
        """Un owner cancelando un pedido de ALTO MONTO: el pipeline procede (el
        humano decide) y la señal de riesgo queda en la auditoría."""
        sb = _SbLive({"orders": [dict(ORDER, total_amount=900000)]})  # $900K > $500K
        with patch("lib.order_cancel_ports.notify_operator_telegram"):
            resp = _patch_cancel(supabase=sb)
        audit = [p for t, p in sb.inserts if t == "order_cancellations"]
        self.assertEqual(audit[0]["escalated_to_operator"], False)
        self.assertEqual(audit[0]["escalation_reason"], "HIGH_VALUE")
        self.assertEqual(resp["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()

"""Tests del pipeline completo de cancelación de pedidos (Ley 1480).

Complementa test_order_cancellation_escalation.py (triage puro) y
test_cancel_intent_and_pipeline.py (intent + mensajes). Acá se prueba el
pipeline `cancel_order` de punta a punta sobre un Supabase falso:

  • Orden no encontrada / ya cancelada (idempotencia).
  • Escalación: persiste audit con escalated=True y NO toca la orden.
  • Cancelación total feliz: reversa stock (RPC atómica), marca orders.cancelled,
    completa la fila de auditoría.
  • Reembolso: sin pago, COD, CARD void auto (éxito / no elegible / fallo /
    sin credenciales), manual con plazo legal.
  • Cancelación de guía Aveonline: simulated, API ok, API fallo, en tránsito.
  • Cancelación parcial: solo repone las variaciones listadas.

Los clientes Wompi/Aveonline se inyectan como módulos falsos en sys.modules
(los imports son lazy dentro de las funciones) — nunca se pega a la red.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from lib.order_cancellation import (  # noqa: E402
    CancellationItem,
    CancellationRequest,
    TenantPolicy,
    _cancel_shipping,
    _compose_customer_message,
    _hydrate_payment_from_webhook,
    _load_policy,
    _process_refund,
    _restore_stock,
    cancel_order,
)
from lib.legal_texts import REEMBOLSO_DIAS_CALENDARIO_MAX  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Supabase falso (mismo diseño que test_meli_webhook_processing) ──────────


class _Q:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table
        self._filters = []
        self._op = "select"
        self._payload = None
        self._single = False
        self._maybe = False

    def select(self, *a, **k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, c, v):
        self._filters.append(("eq", c, v))
        return self

    def in_(self, c, vals):
        self._filters.append(("in", c, vals))
        return self

    def like(self, c, p):
        self._filters.append(("like", c, p))
        return self

    def limit(self, n):
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._maybe = True
        return self

    def execute(self):
        return self._sb._exec(self)


class _Sb:
    def __init__(self, tables=None, rpc_handler=None):
        self._tables = tables or {}
        self._rpc_handler = rpc_handler
        self.inserts = []
        self.updates = []
        self.upserts = []
        self.rpc_calls = []
        self.fail = {}

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params=None):
        self.rpc_calls.append((name, params))
        data = None
        if self._rpc_handler:
            data = self._rpc_handler(name, params)

        class _Exec:
            def execute(self_inner):
                if isinstance(data, Exception):
                    raise data
                return SimpleNamespace(data=data)

        return _Exec()

    def _exec(self, q):
        exc = self.fail.get((q._table, q._op))
        if exc:
            raise exc
        rows = [dict(r) for r in self._tables.get(q._table, [])]
        if q._op == "select":
            for op, c, v in q._filters:
                if op == "eq":
                    rows = [r for r in rows if str(r.get(c)) == str(v)]
                elif op == "in":
                    rows = [r for r in rows if r.get(c) in v]
            if q._single or q._maybe:
                return SimpleNamespace(data=rows[0] if rows else None)
            return SimpleNamespace(data=rows)
        if q._op == "insert":
            self.inserts.append((q._table, q._payload))
            n = sum(1 for t, _ in self.inserts if t == q._table)
            payload = q._payload
            if isinstance(payload, list):
                data = [dict(p, id=p.get("id", f"{q._table}-{n}-{i}"))
                        for i, p in enumerate(payload)]
            else:
                data = [dict(payload, id=payload.get("id", f"{q._table}-{n}"))]
            return SimpleNamespace(data=data)
        if q._op == "upsert":
            self.upserts.append((q._table, q._payload))
            return SimpleNamespace(data=[dict(q._payload, id=q._payload.get("id", f"{q._table}-u1"))])
        if q._op == "update":
            self.updates.append((q._table, q._payload, q._filters))
            return SimpleNamespace(data=[])
        raise AssertionError(f"op desconocida {q._op}")


def _updates_for(sb, table):
    return [p for t, p, _ in sb.updates if t == table]


def _inserts_for(sb, table):
    return [p for t, p in sb.inserts if t == table]


# ─── Fixtures de dominio ─────────────────────────────────────────────────────

ORDER = {
    "id": "order-1", "tenant_id": "t1", "status": "confirmed",
    "total_amount": 50000, "conversation_id": "conv-1",
    "contact_id": "c1", "payment_method": "credit",
}

PAYMENT_CARD = {
    "order_id": "order-1", "tenant_id": "t1",
    "status": "approved", "wompi_status": "APPROVED", "wompi_txn_id": "txn-1",
    "amount_in_cents": 5_000_000,
    "raw_webhook": {"data": {"transaction": {
        "payment_method_type": "CARD", "finalized_at": "2026-08-01T00:00:00Z",
    }}},
}


def _card_payment(**over):
    """Payment CARD ya hidratado (como lo deja el pipeline tras leer raw_webhook)."""
    p = dict(PAYMENT_CARD)
    p.update(over)
    _hydrate_payment_from_webhook(p)
    return p


def _req(**over):
    base = dict(order_id="order-1", tenant_id="t1", actor="customer",
                reason_text="quiero cancelar", conversation_id="conv-1")
    base.update(over)
    return CancellationRequest(**base)


def _fake_wompi_module(void_result=None, void_exc=None, eligible=True, creds=("PRIV", "EK", "sandbox")):
    """Módulo falso integrations.wompi_client para los imports lazy del pipeline."""
    mod = types.ModuleType("integrations.wompi_client")
    calls = {"void": []}
    mod.is_void_eligible = lambda method, paid_at: eligible
    mod.get_tenant_wompi_creds = lambda sb, tenant_id=None: creds

    def _void(**kwargs):
        calls["void"].append(kwargs)
        if void_exc:
            raise void_exc
        return void_result

    mod.void_transaction_sync = _void
    mod._calls = calls
    return mod


def _fake_ave_module(cancel_result=None, cancel_exc=None):
    mod = types.ModuleType("integrations.aveonline_client")
    client = SimpleNamespace()
    client.cancel_guide = AsyncMock(
        side_effect=cancel_exc if cancel_exc else None,
        return_value=cancel_result,
    ) if cancel_exc else AsyncMock(return_value=cancel_result)
    mod.AveonlineClient = lambda supabase=None, tenant_id=None: client
    mod._client = client
    return mod


# ─── Pipeline: lookups e idempotencia ────────────────────────────────────────


class PipelineLookupTests(unittest.TestCase):
    def test_orden_no_encontrada_excepcion(self):
        sb = _Sb()
        sb.fail[("orders", "select")] = RuntimeError("db down")
        r = _run(cancel_order(sb, _req()))
        self.assertFalse(r.success)
        self.assertEqual(r.status, "failed")
        self.assertIn("orden no encontrada", r.error)
        self.assertIn("No encuentro ese pedido", r.customer_message)

    def test_orden_inexistente(self):
        sb = _Sb()  # single() → None
        r = _run(cancel_order(sb, _req()))
        self.assertFalse(r.success)
        self.assertEqual(r.error, "orden no existe")

    def test_orden_ya_cancelada_es_idempotente(self):
        sb = _Sb({"orders": [dict(ORDER, status="cancelled")]})
        r = _run(cancel_order(sb, _req()))
        self.assertTrue(r.success)
        self.assertEqual(r.status, "completed")
        self.assertIn("ya estaba cancelado", r.customer_message)
        self.assertEqual(_updates_for(sb, "orders"), [], "no re-escribe una orden ya cancelada")
        self.assertEqual(_inserts_for(sb, "order_cancellations"), [], "no duplica audit")


# ─── Pipeline: escalación ────────────────────────────────────────────────────


class PipelineEscalationTests(unittest.TestCase):
    def test_escalacion_persiste_audit_y_no_toca_orden(self):
        sb = _Sb({"orders": [dict(ORDER, status="delivered")]})
        r = _run(cancel_order(sb, _req(reason_text="quiero cancelar")))

        self.assertFalse(r.success)
        self.assertTrue(r.requires_escalation)
        self.assertIn("ORDER_DELIVERED", r.escalation_reasons)
        self.assertIn("retracto", r.customer_message.lower())
        self.assertIn("🚨", r.operator_notification)

        audit = _inserts_for(sb, "order_cancellations")
        self.assertEqual(len(audit), 1)
        self.assertTrue(audit[0]["escalated_to_operator"])
        self.assertIn("ORDER_DELIVERED", audit[0]["escalation_reason"])
        self.assertEqual(audit[0]["legal_basis"], "ley_1480_estatuto_consumidor")
        self.assertEqual(_updates_for(sb, "orders"), [], "escalado → la orden NO se cancela sola")

    def test_escalacion_alto_monto(self):
        sb = _Sb({"orders": [dict(ORDER, total_amount=600000)]})  # $600K > umbral $500K
        r = _run(cancel_order(sb, _req()))
        self.assertTrue(r.requires_escalation)
        self.assertIn("HIGH_VALUE", r.escalation_reasons)


# ─── Pipeline: cancelación feliz ─────────────────────────────────────────────


class PipelineHappyPathTests(unittest.TestCase):
    def test_cancel_total_sin_pago_reversa_stock_y_cierra(self):
        sb = _Sb({
            "orders": [dict(ORDER, status="confirmed")],
            "stock_movements": [
                {"order_id": "order-1", "tenant_id": "t1", "variation_id": "v1",
                 "delta": -2, "reason": "reservation_consumed"},
                {"order_id": "order-1", "tenant_id": "t1", "variation_id": "v1",
                 "delta": -1, "reason": "sale"},
            ],
        }, rpc_handler=lambda name, params: 3)

        r = _run(cancel_order(sb, _req()))

        self.assertTrue(r.success)
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.refund_method, "no_refund_no_payment")
        self.assertIn("No se cobró nada", r.customer_message)

        # Stock: una sola RPC con el total agregado (2+1).
        restore = [p for n, p in sb.rpc_calls if n == "rpc_stock_restore"]
        self.assertEqual(len(restore), 1)
        self.assertEqual(restore[0]["p_variation_id"], "v1")
        self.assertEqual(restore[0]["p_qty"], 3)
        self.assertEqual(restore[0]["p_reason"], "cancellation_refund")

        # Orden marcada cancelled con trazabilidad del actor.
        upd = _updates_for(sb, "orders")
        self.assertEqual(upd[0]["status"], "cancelled")
        self.assertEqual(upd[0]["cancelled_by_actor"], "customer")
        self.assertIn("cancellation_id", upd[0])

        # Fila de audit cerrada como completed.
        cxl = _updates_for(sb, "order_cancellations")
        self.assertEqual(cxl[0]["status"], "completed")
        self.assertTrue(cxl[0]["stock_restored"])
        self.assertEqual(cxl[0]["stock_restore_method"], "stock_movements_reversed")

    def test_cancel_parcial_solo_repone_variaciones_listadas(self):
        sb = _Sb({
            "orders": [dict(ORDER)],
            "stock_movements": [
                {"order_id": "order-1", "tenant_id": "t1", "variation_id": "v1",
                 "delta": -2, "reason": "sale"},
                {"order_id": "order-1", "tenant_id": "t1", "variation_id": "v2",
                 "delta": -1, "reason": "sale"},
            ],
        }, rpc_handler=lambda name, params: 1)
        items = [CancellationItem(
            cart_item_id="ci1", product_id="p1", variation_id="v1",
            qty=2, unit_price_cents=2_500_000,
        )]
        r = _run(cancel_order(sb, _req(items=items)))

        self.assertEqual(r.status, "completed")
        restore = [p for n, p in sb.rpc_calls if n == "rpc_stock_restore"]
        self.assertEqual(len(restore), 1)
        self.assertEqual(restore[0]["p_variation_id"], "v1", "v2 NO se repone en cancelación parcial")
        # items_cancelled_json persistido en el audit.
        audit = _inserts_for(sb, "order_cancellations")
        self.assertEqual(audit[0]["items_cancelled_json"][0]["variation_id"], "v1")

    def test_fallo_reversa_stock_marca_partial_failure(self):
        sb = _Sb({"orders": [dict(ORDER)]})
        sb.fail[("stock_movements", "select")] = RuntimeError("db down")
        r = _run(cancel_order(sb, _req()))
        self.assertEqual(r.status, "partial_failure")
        cxl = _updates_for(sb, "order_cancellations")
        self.assertFalse(cxl[0]["stock_restored"])

    def test_libera_reservas_activas_del_cart(self):
        sb = _Sb({
            "orders": [dict(ORDER)],
            "conversation_carts": [{"id": "cart-1", "converted_order_id": "order-1", "tenant_id": "t1"}],
        })
        with patch("lib.stock_reservation.release_by_cart") as rel:
            _run(cancel_order(sb, _req()))
        rel.assert_called_once()
        self.assertEqual(rel.call_args.kwargs["cart_id"], "cart-1")


# ─── Reembolso (unit sobre _process_refund + pipeline CARD) ──────────────────


class ProcessRefundTests(unittest.TestCase):
    def test_sin_payment_no_refund(self):
        method, status, amount = _process_refund(_Sb(), order=ORDER, payment=None, policy=TenantPolicy())
        self.assertEqual((method, status, amount), ("no_refund_no_payment", "not_applicable", 0))

    def test_payment_pending_no_refund(self):
        p = {"status": "pending", "payment_method_type": "CARD", "amount_in_cents": 100}
        method, status, _ = _process_refund(_Sb(), order=ORDER, payment=p, policy=TenantPolicy())
        self.assertEqual((method, status), ("no_refund_no_payment", "not_applicable"))

    def test_cod_confirmado_no_hay_dinero_que_devolver(self):
        p = _card_payment()
        method, status, _ = _process_refund(
            _Sb(), order=dict(ORDER, payment_method="cod"), payment=p, policy=TenantPolicy(),
        )
        self.assertEqual((method, status), ("cod_not_collected", "not_applicable"))

    def test_policy_escalate_card_voids_siempre_manual(self):
        p = _card_payment(payment_method_type="NEQUI", paid_at="2026-08-01")
        method, status, amount = _process_refund(
            _Sb(), order=ORDER, payment=p, policy=TenantPolicy(escalate_card_voids=True),
        )
        self.assertEqual((method, status), ("wompi_dashboard_manual", "pending_manual"))
        self.assertEqual(amount, 5_000_000)

    def test_card_elegible_void_auto(self):
        sb = _Sb({"payments": [_card_payment(id="pay-1")]})
        fake = _fake_wompi_module(void_result={"status": "VOIDED"})
        with patch.dict(sys.modules, {"integrations.wompi_client": fake}):
            method, status, amount = _process_refund(
                sb, order=ORDER, payment=_card_payment(), policy=TenantPolicy(),
            )
        self.assertEqual((method, status), ("wompi_void_auto", "completed"))
        self.assertEqual(amount, 5_000_000)
        self.assertEqual(fake._calls["void"][0]["transaction_id"], "txn-1")
        # payments marcado VOIDED localmente (el webhook posterior es idempotente).
        upd = _updates_for(sb, "payments")
        self.assertEqual(upd[0]["wompi_status"], "VOIDED")

    def test_card_no_elegible_manual(self):
        fake = _fake_wompi_module(eligible=False)
        with patch.dict(sys.modules, {"integrations.wompi_client": fake}):
            method, status, _ = _process_refund(
                _Sb(), order=ORDER, payment=_card_payment(), policy=TenantPolicy(),
            )
        self.assertEqual((method, status), ("wompi_dashboard_manual", "pending_manual"))
        self.assertEqual(fake._calls["void"], [], "fuera de ventana → ni intenta el void")

    def test_sin_private_key_manual(self):
        fake = _fake_wompi_module(creds=(None, None, "sandbox"))
        with patch.dict(sys.modules, {"integrations.wompi_client": fake}):
            method, status, _ = _process_refund(
                _Sb(), order=ORDER, payment=_card_payment(), policy=TenantPolicy(),
            )
        self.assertEqual((method, status), ("wompi_dashboard_manual", "pending_manual"))

    def test_sin_txn_id_manual(self):
        fake = _fake_wompi_module()
        p = _card_payment(wompi_txn_id=None)
        with patch.dict(sys.modules, {"integrations.wompi_client": fake}):
            method, status, _ = _process_refund(
                _Sb(), order=ORDER, payment=p, policy=TenantPolicy(),
            )
        self.assertEqual((method, status), ("wompi_dashboard_manual", "pending_manual"))

    def test_void_falla_escala_a_manual(self):
        fake = _fake_wompi_module(void_exc=RuntimeError("wompi 500"))
        with patch.dict(sys.modules, {"integrations.wompi_client": fake}):
            method, status, _ = _process_refund(
                _Sb(), order=ORDER, payment=_card_payment(), policy=TenantPolicy(),
            )
        self.assertEqual((method, status), ("wompi_dashboard_manual", "pending_manual"))

    def test_metodo_no_card_va_a_manual(self):
        p = _card_payment(payment_method_type="NEQUI")
        method, status, _ = _process_refund(
            _Sb(), order=ORDER, payment=p, policy=TenantPolicy(),
        )
        self.assertEqual((method, status), ("wompi_dashboard_manual", "pending_manual"))


class PipelineRefundIntegrationTests(unittest.TestCase):
    def test_pipeline_card_void_completo(self):
        sb = _Sb({
            "orders": [dict(ORDER)],
            "payments": [dict(PAYMENT_CARD, id="pay-1")],
        }, rpc_handler=lambda name, params: 0)
        fake = _fake_wompi_module(void_result={"status": "VOIDED"})
        with patch.dict(sys.modules, {"integrations.wompi_client": fake}):
            r = _run(cancel_order(sb, _req()))

        self.assertEqual(r.status, "completed")
        self.assertEqual(r.refund_method, "wompi_void_auto")
        self.assertEqual(r.refund_amount_cents, 5_000_000)
        self.assertIn("Reembolso", r.customer_message)
        cxl = _updates_for(sb, "order_cancellations")
        self.assertEqual(cxl[0]["refund_status"], "completed")
        self.assertIsNotNone(cxl[0]["refund_completed_at"])

    def test_pipeline_refund_manual_notifica_operador(self):
        sb = _Sb({
            "orders": [dict(ORDER)],
            "payments": [dict(PAYMENT_CARD, id="pay-1")],
        }, rpc_handler=lambda name, params: 0)
        fake = _fake_wompi_module(eligible=False)
        with patch.dict(sys.modules, {"integrations.wompi_client": fake}):
            r = _run(cancel_order(sb, _req()))

        self.assertEqual(r.refund_status, "pending_manual")
        self.assertIn("Refund manual requerido", r.operator_notification)
        self.assertIn("días calendario", r.operator_notification)
        # El cliente recibe el plazo legal, no una promesa vacía.
        self.assertIn(str(REEMBOLSO_DIAS_CALENDARIO_MAX), r.customer_message)
        # partial_failure porque el refund quedó pendiente.
        self.assertEqual(r.status, "partial_failure")


# ─── Cancelación de guía Aveonline ───────────────────────────────────────────


class CancelShippingTests(unittest.TestCase):
    def test_sin_shipment_no_aplica(self):
        ok, method = _run(_cancel_shipping(_Sb(), tenant_id="t1", shipment=None))
        self.assertEqual((ok, method), (False, "not_applicable"))

    def test_en_transito_es_manual(self):
        for st in ("picked_up", "in_transit", "out_for_delivery", "delivered"):
            with self.subTest(status=st):
                ok, method = _run(_cancel_shipping(
                    _Sb(), tenant_id="t1",
                    shipment={"status": st, "tracking_number": "GU1"},
                ))
                self.assertEqual((ok, method), (False, "manual_operator_call"))

    def test_sin_tracking_no_aplica(self):
        ok, method = _run(_cancel_shipping(
            _Sb(), tenant_id="t1", shipment={"status": "labeled", "tracking_number": None},
        ))
        self.assertEqual((ok, method), (False, "not_applicable"))

    def test_guia_simulada_solo_marca_db(self):
        sb = _Sb({"shipments": [{"status": "simulated", "tracking_number": "GU1", "tenant_id": "t1"}]})
        ok, method = _run(_cancel_shipping(
            sb, tenant_id="t1", shipment={"status": "simulated", "tracking_number": "GU1"},
        ))
        self.assertEqual((ok, method), (True, "simulated_no_api_call"))
        self.assertEqual(_updates_for(sb, "shipments")[0]["status"], "cancelled")

    def test_aveonline_api_ok(self):
        sb = _Sb({"shipments": [{"status": "labeled", "tracking_number": "GU1", "tenant_id": "t1"}]})
        fake = _fake_ave_module(cancel_result={"ok": True})
        with patch.dict(sys.modules, {"integrations.aveonline_client": fake}):
            ok, method = _run(_cancel_shipping(
                sb, tenant_id="t1", shipment={"status": "labeled", "tracking_number": "GU1"},
            ))
        self.assertEqual((ok, method), (True, "aveonline_api"))
        fake._client.cancel_guide.assert_awaited_once_with(tracking_number="GU1")
        self.assertEqual(_updates_for(sb, "shipments")[0]["status"], "cancelled")

    def test_aveonline_rechaza_escala_manual(self):
        fake = _fake_ave_module(cancel_result={"ok": False, "message": "ya recogida"})
        with patch.dict(sys.modules, {"integrations.aveonline_client": fake}):
            ok, method = _run(_cancel_shipping(
                _Sb(), tenant_id="t1", shipment={"status": "labeled", "tracking_number": "GU1"},
            ))
        self.assertEqual((ok, method), (False, "manual_operator_call"))

    def test_aveonline_excepcion_escala_manual(self):
        fake = _fake_ave_module(cancel_exc=RuntimeError("http down"))
        with patch.dict(sys.modules, {"integrations.aveonline_client": fake}):
            ok, method = _run(_cancel_shipping(
                _Sb(), tenant_id="t1", shipment={"status": "labeled", "tracking_number": "GU1"},
            ))
        self.assertEqual((ok, method), (False, "manual_operator_call"))


# ─── Stock restore (unit) ────────────────────────────────────────────────────


class RestoreStockTests(unittest.TestCase):
    def test_sin_movimientos_reservation_released(self):
        ok, method = _restore_stock(_Sb(), order_id="o1", tenant_id="t1", items=None)
        self.assertEqual((ok, method), (True, "reservation_released"))

    def test_rpc_falla_no_explota_y_reporta_released(self):
        def handler(name, params):
            raise RuntimeError("rpc down")
        sb = _Sb(
            {"stock_movements": [
                {"order_id": "o1", "tenant_id": "t1", "variation_id": "v1",
                 "delta": -1, "reason": "sale"},
            ]},
            rpc_handler=handler,
        )
        ok, method = _restore_stock(sb, order_id="o1", tenant_id="t1", items=None)
        self.assertEqual((ok, method), (True, "reservation_released"),
                         "el RPC idempotente falló pero la reserva sí se liberó")

    def test_excepcion_global_marca_failed(self):
        sb = _Sb()
        sb.fail[("stock_movements", "select")] = RuntimeError("db down")
        ok, method = _restore_stock(sb, order_id="o1", tenant_id="t1", items=None)
        self.assertEqual((ok, method), (False, "failed"))


# ─── Policy + helpers puros ──────────────────────────────────────────────────


class LoadPolicyTests(unittest.TestCase):
    def test_sin_fila_defaults(self):
        sb = _Sb()
        sb.fail[("tenant_cancellation_policy", "select")] = RuntimeError("sin tabla")
        p = _load_policy(sb, "t1")
        self.assertEqual(p.auto_void_card_window_hours, 23)
        self.assertFalse(p.allow_cancel_after_picked_up)
        self.assertEqual(p.high_value_escalation_threshold_cents, 50_000_000)

    def test_fila_honra_valores(self):
        sb = _Sb({"tenant_cancellation_policy": [{
            "tenant_id": "t1", "allow_cancel_after_picked_up": True,
            "auto_void_card_window_hours": 5,
            "retracto_window_business_days": 10,
        }]})
        p = _load_policy(sb, "t1")
        self.assertTrue(p.allow_cancel_after_picked_up)
        self.assertEqual(p.auto_void_card_window_hours, 5)
        self.assertEqual(p.retracto_window_business_days, 10)

    def test_techo_legal_se_impone_siempre(self):
        # 30 días era el default viejo (plazo presencial) — la ley da 15 calendario.
        self.assertEqual(
            TenantPolicy(manual_refund_legal_days=30).manual_refund_legal_days,
            REEMBOLSO_DIAS_CALENDARIO_MAX,
        )
        self.assertEqual(
            TenantPolicy(manual_refund_legal_days=0).manual_refund_legal_days,
            REEMBOLSO_DIAS_CALENDARIO_MAX,
        )


class HydratePaymentTests(unittest.TestCase):
    def test_extrae_metodo_y_fecha_del_webhook(self):
        p = {"raw_webhook": {"data": {"transaction": {
            "payment_method_type": "CARD", "finalized_at": "2026-08-01T10:00:00Z",
        }}}}
        _hydrate_payment_from_webhook(p)
        self.assertEqual(p["payment_method_type"], "CARD")
        self.assertEqual(p["paid_at"], "2026-08-01T10:00:00Z")

    def test_no_pisa_valores_existentes(self):
        p = {"payment_method_type": "NEQUI", "paid_at": "ayer", "raw_webhook": {}}
        _hydrate_payment_from_webhook(p)
        self.assertEqual(p["payment_method_type"], "NEQUI")
        self.assertEqual(p["paid_at"], "ayer")

    def test_webhook_malformado_no_explota(self):
        p = {"raw_webhook": {"data": "no-es-dict"}}
        _hydrate_payment_from_webhook(p)
        self.assertEqual(p["payment_method_type"], "")


class ComposeCustomerMessageTests(unittest.TestCase):
    def test_sin_cobro(self):
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="no_refund_no_payment",
            refund_amount_cents=0, policy=TenantPolicy(),
        )
        self.assertIn("No se cobró nada", msg)

    def test_cod(self):
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="cod_not_collected",
            refund_amount_cents=0, policy=TenantPolicy(),
        )
        self.assertIn("pago contra entrega", msg)

    def test_void_auto_monto_formateado(self):
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="wompi_void_auto",
            refund_amount_cents=5_000_000, policy=TenantPolicy(),
        )
        self.assertIn("$50.000", msg)
        self.assertIn("3-5 días hábiles", msg)

    def test_manual_cita_plazo_legal(self):
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method="wompi_dashboard_manual",
            refund_amount_cents=5_000_000, policy=TenantPolicy(),
        )
        self.assertIn(str(REEMBOLSO_DIAS_CALENDARIO_MAX), msg)
        self.assertIn("días", msg)

    def test_metodo_desconocido_mensaje_base(self):
        msg = _compose_customer_message(
            short_id="ABC12345", refund_method=None,
            refund_amount_cents=0, policy=TenantPolicy(),
        )
        self.assertIn("cancelé tu pedido", msg)
        self.assertIn("ABC12345", msg)


if __name__ == "__main__":
    unittest.main()

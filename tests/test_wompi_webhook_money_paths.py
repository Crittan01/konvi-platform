"""Tests de money-paths del webhook Wompi no cubiertos por test_wompi_webhook.py.

Complementa la suite existente (firma, confirmación básica, reconciliación
system_auto) con los paths de dinero que la auditoría 2026-08-01 marcó sin
cobertura:

  • Pago huérfano sobre orden terminal: void automático CARD / reembolso manual.
  • Guard de monto/moneda (fail-closed) y orden sin total.
  • Dedup por checksum processed-aware: replay, crash-recovery, propagación.
  • Ledger de payments: nunca degradar approved, nunca aprobar con monto distinto.
  • VOIDED post-cancelación (confirmación bancaria del refund) + notificación.
  • Re-quote post-DECLINED: nuevo link, monto mínimo, sin clave.
  • Generación de guía Aveonline post-pago (simulate vs real, claim idempotente,
    COD, pending_generation ante fallo, ambigüedad money-safe).
  • Emails del ciclo de vida (modos, Resend 4xx/429/5xx/red).
  • Endpoint: rate-limit 429, fail-open, inbox durable.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from routers import wompi_webhook  # noqa: E402
import lib.shipping_guides as shipping_guides  # noqa: E402
from helpers.wompi_payload_builder import WompiPayloadBuilder, TEST_EVENTS_KEY  # noqa: E402

mw = wompi_webhook


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Supabase falso genérico ──────────────────────────────────────────────────


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
        self.queries = []
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
        self.queries.append((q._table, q._op))
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
                elif op == "like":
                    pat = str(v)
                    if pat.endswith("%"):
                        rows = [r for r in rows if str(r.get(c) or "").startswith(pat[:-1])]
                    else:
                        rows = [r for r in rows if pat in str(r.get(c) or "")]
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


# ─── Base para tests que corren _process_wompi_event ─────────────────────────


class _EventDrivenTest(unittest.TestCase):
    """setUp común: firma válida, service client falso, decremento observado."""

    def setUp(self):
        p_creds = patch.object(
            mw, "get_tenant_wompi_creds",
            return_value=(None, TEST_EVENTS_KEY, "sandbox"),
        )
        self.creds = p_creds.start()
        self.addCleanup(p_creds.stop)

        p_client = patch.object(mw, "_get_service_client")
        self.get_client = p_client.start()
        self.addCleanup(p_client.stop)

        p_dec = patch("routers.orders._decrement_stock_on_confirm")
        self.decrement = p_dec.start()
        self.addCleanup(p_dec.stop)

        p_guide = patch.object(mw, "_generate_shipping_guide", return_value=False)
        self.guide = p_guide.start()
        self.addCleanup(p_guide.stop)

        p_env = patch.dict(os.environ, {"RESEND_API_KEY": ""})
        p_env.start()
        self.addCleanup(p_env.stop)

    def _drive(self, payload, sb):
        self.get_client.return_value = sb
        mw._process_wompi_event(payload)
        return sb


def _approved_payload(link="plink-1", txn="txn-1", amount=135_000, **txn_over):
    payload = WompiPayloadBuilder().with_approved_txn(
        payment_link_id=link, txn_id=txn, amount_in_cents=amount,
    ).build()
    payload["data"]["transaction"].update(txn_over)
    return payload


def _state_con_orden(order, link="plink-1", payments=None):
    """State mínimo: link → orden + filas payments preexistentes opcionales."""
    tables = {
        "payments": [dict({"id": "pay-1", "wompi_link_id": link, "order_id": order["id"],
                           "tenant_id": order["tenant_id"]},
                          **(payments or {}))],
        "orders": [order],
        "messages": [],
        "conversations": [{"id": order.get("conversation_id"), "tenant_id": order["tenant_id"],
                           "customer_phone": "573001112233"}] if order.get("conversation_id") else [],
    }
    return tables


# ─── Pago huérfano (void automático / reembolso manual) ──────────────────────


class OrphanPaymentTests(_EventDrivenTest):
    ORDER_CANCELADA = {
        "id": "order-1", "tenant_id": "t1", "status": "cancelled",
        "cancelled_by_actor": "operator", "conversation_id": "conv-1",
        "total_amount": 1350.0,
    }

    def _handle(self, *, method="CARD", eligible=True, void_result=None,
                void_exc=None, private_key="PRIV"):
        order = dict(self.ORDER_CANCELADA)
        payload = _approved_payload(
            payment_method_type=method, finalized_at="2026-08-01T00:00:00Z",
        )
        sb = _Sb(_state_con_orden(order))
        self.get_client.return_value = sb
        with patch.object(mw, "is_void_eligible", return_value=eligible), \
             patch.object(mw, "get_tenant_wompi_creds",
                          return_value=(private_key, TEST_EVENTS_KEY, "sandbox")), \
             patch.object(mw, "void_transaction_sync",
                          side_effect=void_exc if void_exc else None,
                          return_value=void_result) as void:
            mw._handle_orphan_payment(
                supabase=sb, order=order, txn_id="txn-1",
                amount_in_cents=135_000, payload=payload,
                current_status="cancelled",
            )
        return sb, void

    def test_void_ok_marca_orphan_voided(self):
        sb, void = self._handle(void_result={"status": "VOIDED"})
        self.assertTrue(void.called)
        upd = _updates_for(sb, "payments")
        self.assertEqual(upd[0]["status"], "orphan_voided")

    def test_void_rechazado_marca_refund_pending(self):
        sb, _ = self._handle(void_result={"status": "PENDING"})
        self.assertEqual(_updates_for(sb, "payments")[0]["status"], "orphan_refund_pending")

    def test_void_falla_marca_refund_pending_sin_propagar(self):
        sb, _ = self._handle(void_exc=RuntimeError("wompi 500"))
        self.assertEqual(_updates_for(sb, "payments")[0]["status"], "orphan_refund_pending")

    def test_sin_private_key_no_intenta_void(self):
        sb, void = self._handle(private_key=None)
        void.assert_not_called()
        self.assertEqual(_updates_for(sb, "payments")[0]["status"], "orphan_refund_pending")

    def test_metodo_no_elegible_requiere_reembolso_manual(self):
        """NEQUI/PSE/Bancolombia ya transfirieron — no hay void posible."""
        sb, void = self._handle(method="NEQUI", eligible=False)
        void.assert_not_called()
        self.assertEqual(_updates_for(sb, "payments")[0]["status"], "orphan_refund_pending")

    def test_approved_sobre_cancelada_de_operador_invoca_orphan_handler(self):
        sb = _Sb(_state_con_orden(dict(self.ORDER_CANCELADA)))
        with patch.object(mw, "_handle_orphan_payment") as orphan:
            self._drive(_approved_payload(), sb)
        orphan.assert_called_once()
        self.decrement.assert_not_called()

    def test_replay_mismo_txn_sobre_confirmada_es_idempotente(self):
        """Mismo txn ya en el ledger + orden confirmada → skip silencioso (ni orphan ni confirm)."""
        order = dict(self.ORDER_CANCELADA, status="confirmed", cancelled_by_actor=None)
        sb = _Sb(_state_con_orden(
            order,
            payments={"wompi_txn_id": "txn-1", "status": "approved", "amount_in_cents": 135_000},
        ))
        with patch.object(mw, "_handle_orphan_payment") as orphan:
            self._drive(_approved_payload(), sb)
        orphan.assert_not_called()
        self.decrement.assert_not_called()

    def test_txn_distinto_mismo_link_sobre_confirmada_es_replay(self):
        """Un 2º txn sobre el MISMO link en una orden confirmada: el fallback de
        lookup por (order_id, link) — rev. 104 BUG-3 — lo resuelve contra la fila
        preexistente → was_duplicate=True → skip idempotente. El orphan por doble
        cobro (c) queda para la carrera defensiva sin fila que matchee."""
        order = dict(self.ORDER_CANCELADA, status="confirmed", cancelled_by_actor=None)
        sb = _Sb(_state_con_orden(order))  # payments sin wompi_txn_id → match solo por link
        with patch.object(mw, "_handle_orphan_payment") as orphan:
            self._drive(_approved_payload(txn="txn-otro-distinto"), sb)
        orphan.assert_not_called()
        self.decrement.assert_not_called()
        # La fila preexistente quedó completada con el nuevo txn (trazabilidad).
        upd = _updates_for(sb, "payments")
        self.assertEqual(upd[0]["wompi_txn_id"], "txn-otro-distinto")


# ─── Guards de monto / moneda / total (fail-closed) ──────────────────────────


class AmountCurrencyGuardTests(_EventDrivenTest):
    def _order(self, **over):
        base = {
            "id": "order-1", "tenant_id": "t1", "status": "pending_payment",
            "conversation_id": "conv-1", "total_amount": 1350.0,
        }
        base.update(over)
        return base

    def test_orden_sin_total_no_se_confirma(self):
        order = self._order()
        del order["total_amount"]
        sb = _Sb(_state_con_orden(order))
        with self.assertLogs("routers.wompi_webhook", level="ERROR") as cm:
            self._drive(_approved_payload(), sb)
        self.assertIn("sin total_amount", "\n".join(cm.output))
        self.decrement.assert_not_called()

    def test_monto_mismatch_no_se_confirma(self):
        sb = _Sb(_state_con_orden(self._order(total_amount=999.0)))
        with self.assertLogs("routers.wompi_webhook", level="ERROR") as cm:
            self._drive(_approved_payload(), sb)
        self.assertIn("monto_mismatch", "\n".join(cm.output))
        self.decrement.assert_not_called()

    def test_moneda_distinta_de_cop_no_se_confirma(self):
        sb = _Sb(_state_con_orden(self._order()))
        payload = _approved_payload(currency="USD")
        with self.assertLogs("routers.wompi_webhook", level="ERROR") as cm:
            self._drive(payload, sb)
        self.assertIn("moneda_invalida", "\n".join(cm.output))
        self.decrement.assert_not_called()

    def test_monto_y_moneda_correctos_confirma(self):
        sb = _Sb(_state_con_orden(self._order()))
        self._drive(_approved_payload(currency="COP"), sb)
        self.decrement.assert_called_once()
        upd = _updates_for(sb, "orders")
        self.assertEqual(upd[0]["status"], "confirmed")


# ─── Dedup processed-aware ────────────────────────────────────────────────────


class DedupTests(_EventDrivenTest):
    ORDER = {
        "id": "order-1", "tenant_id": "t1", "status": "pending_payment",
        "conversation_id": "conv-1", "total_amount": 1350.0,
    }
    DUP = Exception('duplicate key value violates unique constraint "wompi_events_seen_pkey" (23505)')

    def test_ya_procesado_se_descarta(self):
        payload = _approved_payload()
        sb = _Sb({
            **_state_con_orden(dict(self.ORDER)),
            "wompi_events_seen": [{
                "event_id": payload["signature"]["checksum"],
                "processed_at": "2026-08-01T00:00:00Z",
            }],
        })
        sb.fail[("wompi_events_seen", "insert")] = self.DUP
        self._drive(payload, sb)
        self.decrement.assert_not_called()
        self.assertEqual(sb.updates, [], "ni siquiera el ledger se toca en un replay procesado")

    def test_recibido_sin_procesar_se_reprocesa(self):
        """Crash entre INSERT y confirmación: el reintento DEBE completar el pago."""
        payload = _approved_payload()
        sb = _Sb({
            **_state_con_orden(dict(self.ORDER)),
            "wompi_events_seen": [{
                "event_id": payload["signature"]["checksum"], "processed_at": None,
            }],
        })
        sb.fail[("wompi_events_seen", "insert")] = self.DUP
        self._drive(payload, sb)
        self.decrement.assert_called_once()

    def test_error_no_duplicado_no_bloquea(self):
        """Un error de red/schema en el dedup NO frena el procesamiento (el guard
        de estado terminal protege del doble decremento)."""
        sb = _Sb(_state_con_orden(dict(self.ORDER)))
        sb.fail[("wompi_events_seen", "insert")] = RuntimeError("connection reset")
        self._drive(_approved_payload(), sb)
        self.decrement.assert_called_once()

    def test_fallo_en_processed_check_propaga(self):
        """W3-F2: flake transitorio del check PROPAGA → inbox queda para reconciliar."""
        sb = _Sb(_state_con_orden(dict(self.ORDER)))
        sb.fail[("wompi_events_seen", "insert")] = self.DUP
        sb.fail[("wompi_events_seen", "select")] = RuntimeError("db flake")
        self.get_client.return_value = sb
        with self.assertRaises(RuntimeError):
            mw._process_wompi_event(_approved_payload())


# ─── Ledger de payments (_upsert_payment_record) ──────────────────────────────


class UpsertPaymentRecordTests(_EventDrivenTest):
    def _call(self, sb, **over):
        kwargs = dict(
            supabase=sb, wompi_txn_id="txn-1", wompi_link_id="plink-1",
            order_id="order-1", amount_in_cents=135_000,
            wompi_status="APPROVED", raw_webhook={"event": "transaction.updated"},
        )
        kwargs.update(over)
        return mw._upsert_payment_record(**kwargs)

    def test_replay_por_txn_actualiza_y_retorna_true(self):
        sb = _Sb({"payments": [{
            "id": "pay-1", "tenant_id": "t1", "wompi_txn_id": "txn-1",
            "status": "pending", "amount_in_cents": 135_000,
        }]})
        dup = self._call(sb)
        self.assertTrue(dup)
        upd = _updates_for(sb, "payments")
        self.assertEqual(upd[0]["status"], "approved")

    def test_nunca_degrada_un_pago_aprobado(self):
        """DECLINED tardío sobre pago APPROVED → status/wompi_status congelados."""
        sb = _Sb({"payments": [{
            "id": "pay-1", "tenant_id": "t1", "wompi_txn_id": "txn-1",
            "status": "approved", "amount_in_cents": 135_000,
        }]})
        with self.assertLogs("routers.wompi_webhook", level="WARNING") as cm:
            dup = self._call(sb, wompi_status="DECLINED")
        self.assertTrue(dup)
        self.assertIn("ledger_no_degrada", "\n".join(cm.output))
        upd = _updates_for(sb, "payments")
        self.assertNotIn("status", upd[0])
        self.assertNotIn("wompi_status", upd[0])
        self.assertIn("raw_webhook", upd[0], "auditoría íntegra se conserva")

    def test_nunca_aprueba_con_monto_distinto(self):
        sb = _Sb({"payments": [{
            "id": "pay-1", "tenant_id": "t1", "wompi_txn_id": "txn-1",
            "status": "pending", "amount_in_cents": 100_000,
        }]})
        with self.assertLogs("routers.wompi_webhook", level="ERROR") as cm:
            dup = self._call(sb, amount_in_cents=135_000)
        self.assertTrue(dup)
        self.assertIn("ledger_monto_mismatch", "\n".join(cm.output))
        upd = _updates_for(sb, "payments")
        self.assertNotIn("status", upd[0])

    def test_completa_fila_preexistente_por_link(self):
        """payment_link_tool creó la fila con txn NULL; el 1er webhook la completa."""
        sb = _Sb({"payments": [{
            "id": "pay-1", "tenant_id": "t1", "wompi_txn_id": None,
            "wompi_link_id": "plink-1", "order_id": "order-1",
            "status": "pending", "amount_in_cents": 135_000,
        }]})
        dup = self._call(sb)
        self.assertTrue(dup)
        upd = _updates_for(sb, "payments")
        self.assertEqual(upd[0]["wompi_txn_id"], "txn-1")

    def test_sin_order_id_no_inserta(self):
        sb = _Sb()
        dup = self._call(sb, order_id=None)
        self.assertFalse(dup)
        self.assertEqual(_inserts_for(sb, "payments"), [])

    def test_insert_nuevo_descubriendo_tenant(self):
        sb = _Sb({"orders": [{"id": "order-1", "tenant_id": "t1"}]})
        dup = self._call(sb)
        self.assertFalse(dup)
        ins = _inserts_for(sb, "payments")
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0]["tenant_id"], "t1")
        self.assertEqual(ins[0]["status"], "approved")


# ─── VOIDED post-cancelación (confirmación bancaria del refund) ───────────────


class PostCancelVoidTests(_EventDrivenTest):
    def _voided_payload(self):
        payload = WompiPayloadBuilder().with_txn(
            txn_id="txn-1", status="VOIDED", amount_in_cents=135_000,
        ).with_custom_properties([
            "data.transaction.id", "data.transaction.status", "data.transaction.amount_in_cents",
        ]).build()
        # El checksum se computa sobre id/status/amount → cambiar el link no lo invalida.
        payload["data"]["transaction"]["payment_link_id"] = "plink-1"
        return payload

    def _state(self, refund_status="pending_manual", refund_method="wompi_void_auto"):
        order = {
            "id": "order-1", "tenant_id": "t1", "status": "cancelled",
            "cancellation_id": "cxl-1", "conversation_id": "conv-1",
            "total_amount": 1350.0,
        }
        tables = _state_con_orden(order, payments={
            "wompi_txn_id": "txn-1", "status": "approved", "amount_in_cents": 135_000,
        })
        tables["order_cancellations"] = [{
            "id": "cxl-1", "refund_method": refund_method, "refund_status": refund_status,
        }]
        return tables

    def test_is_post_cancel_void(self):
        sb = _Sb(self._state())
        self.assertTrue(mw._is_post_cancel_void(sb, order_id="order-1"))

    def test_is_post_cancel_void_orden_no_cancelada(self):
        tables = self._state()
        tables["orders"][0]["status"] = "confirmed"
        self.assertFalse(mw._is_post_cancel_void(_Sb(tables), order_id="order-1"))

    def test_is_post_cancel_void_sin_cancellation_id(self):
        tables = self._state()
        tables["orders"][0]["cancellation_id"] = None
        self.assertFalse(mw._is_post_cancel_void(_Sb(tables), order_id="order-1"))

    def test_is_post_cancel_void_metodo_manual(self):
        self.assertFalse(mw._is_post_cancel_void(
            _Sb(self._state(refund_method="wompi_dashboard_manual")), order_id="order-1",
        ))

    def test_is_post_cancel_void_error_degrada_a_false(self):
        sb = _Sb()
        sb.fail[("orders", "select")] = RuntimeError("db down")
        self.assertFalse(mw._is_post_cancel_void(sb, order_id="order-1"))

    def test_voided_post_cancel_notifica_reembolso_completado(self):
        sb = _Sb(self._state())
        with patch.object(mw, "_maybe_offer_payment_retry") as retry:
            self._drive(self._voided_payload(), sb)
        retry.assert_not_called()
        # WhatsApp al cliente con la confirmación del reembolso.
        enqueue = [p for n, p in sb.rpc_calls if n == "enqueue_whatsapp_outbound_message"]
        self.assertEqual(len(enqueue), 1)
        self.assertIn("Reembolso confirmado", enqueue[0]["p_message"]["text"])
        # Audit: refund_completed_at marcado.
        cxl = _updates_for(sb, "order_cancellations")
        self.assertEqual(cxl[0]["refund_status"], "completed")

    def test_voided_ya_notificado_no_duplica_whatsapp(self):
        """Idempotencia cross-path con el cron backup del orchestrator."""
        sb = _Sb(self._state(refund_status="completed"))
        self._drive(self._voided_payload(), sb)
        self.assertEqual([n for n, _ in sb.rpc_calls if n == "enqueue_whatsapp_outbound_message"], [])

    def test_voided_no_post_cancel_cae_a_release_y_retry(self):
        order = {
            "id": "order-1", "tenant_id": "t1", "status": "pending_payment",
            "conversation_id": "conv-1", "total_amount": 1350.0,
        }
        sb = _Sb(_state_con_orden(order))
        with patch.object(mw, "_release_stock_reservations_for_order") as rel, \
             patch.object(mw, "_maybe_offer_payment_retry") as retry:
            self._drive(self._voided_payload(), sb)
        rel.assert_called_once()
        retry.assert_called_once()

    def test_declined_libera_reservas_y_ofrece_retry(self):
        payload = WompiPayloadBuilder().with_declined_txn(
            payment_link_id="plink-1", txn_id="txn-d",
        ).build()
        order = {
            "id": "order-1", "tenant_id": "t1", "status": "pending_payment",
            "conversation_id": "conv-1", "total_amount": 1350.0,
        }
        sb = _Sb(_state_con_orden(order))
        with patch.object(mw, "_maybe_offer_payment_retry") as retry:
            self._drive(payload, sb)
        retry.assert_called_once()
        release = [p for n, p in sb.rpc_calls if n == "rpc_stock_reservation_release_by_conversation"]
        self.assertEqual(len(release), 1)
        self.assertEqual(release[0]["p_conversation_id"], "conv-1")


# ─── Re-quote post-DECLINED ───────────────────────────────────────────────────


class RetryOfferTests(_EventDrivenTest):
    ORDER = {
        "id": "order-1", "tenant_id": "t1", "status": "pending_payment",
        "conversation_id": "conv-1", "total_amount": 2000.0,
    }

    def _retry(self, sb, order_id="order-1"):
        mw._maybe_offer_payment_retry(sb, order_id=order_id, txn_status="DECLINED")

    def test_orden_no_pending_no_hace_nada(self):
        sb = _Sb(_state_con_orden(dict(self.ORDER, status="confirmed")))
        self._retry(sb)
        self.assertEqual(sb.rpc_calls, [])

    def test_sin_private_key_notifica_fallo_sin_link(self):
        sb = _Sb(_state_con_orden(dict(self.ORDER)))
        with patch.object(mw, "get_tenant_wompi_creds", return_value=(None, "EK", "sandbox")):
            self._retry(sb)
        enqueue = [p for n, p in sb.rpc_calls if n == "enqueue_whatsapp_outbound_message"]
        self.assertEqual(len(enqueue), 1)
        self.assertNotIn("http", enqueue[0]["p_message"]["text"], "sin clave no hay link nuevo")
        self.assertEqual(_inserts_for(sb, "payments"), [])

    def test_monto_bajo_no_genera_link(self):
        """Wompi exige mínimo $1.500 — menos que eso sería un link inválido."""
        sb = _Sb(_state_con_orden(dict(self.ORDER, total_amount=1000.0)))
        with patch.object(mw, "create_payment_link_sync") as create:
            self._retry(sb)
        create.assert_not_called()
        enqueue = [n for n, _ in sb.rpc_calls if n == "enqueue_whatsapp_outbound_message"]
        self.assertEqual(len(enqueue), 1)

    def test_retry_feliz_genera_link_y_lo_envia(self):
        tables = _state_con_orden(dict(self.ORDER))
        tables["orders"][0]["contacts"] = {"name": "Ana", "phone": "573001112233"}
        sb = _Sb(tables)
        with patch.object(mw, "get_tenant_wompi_creds",
                          return_value=("PRIV", "EK", "sandbox")), \
             patch.object(mw, "create_payment_link_sync",
                          return_value={"link_id": "L-2", "checkout_url": "https://checkout.wompi.co/L-2"}) as create:
            self._retry(sb)
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["amount_in_cents"], 200_000)
        ins = _inserts_for(sb, "payments")
        self.assertEqual(ins[0]["wompi_link_id"], "L-2")
        enqueue = [p for n, p in sb.rpc_calls if n == "enqueue_whatsapp_outbound_message"]
        self.assertIn("https://checkout.wompi.co/L-2", enqueue[0]["p_message"]["text"])

    def test_create_link_falla_notifica_sin_link(self):
        tables = _state_con_orden(dict(self.ORDER))
        sb = _Sb(tables)
        with patch.object(mw, "get_tenant_wompi_creds",
                          return_value=("PRIV", "EK", "sandbox")), \
             patch.object(mw, "create_payment_link_sync", side_effect=RuntimeError("wompi down")):
            self._retry(sb)
        enqueue = [p for n, p in sb.rpc_calls if n == "enqueue_whatsapp_outbound_message"]
        self.assertEqual(len(enqueue), 1)
        self.assertNotIn("http", enqueue[0]["p_message"]["text"])


# ─── Liberación de reservas ───────────────────────────────────────────────────


class ReleaseReservationsTests(_EventDrivenTest):
    def test_sin_conversacion_no_hay_reservas(self):
        sb = _Sb({"orders": [{"id": "order-1", "tenant_id": "t1", "conversation_id": None}]})
        mw._release_stock_reservations_for_order(sb, order_id="order-1", txn_status="DECLINED")
        self.assertEqual(sb.rpc_calls, [])

    def test_con_conversacion_llama_rpc(self):
        sb = _Sb({"orders": [{"id": "order-1", "tenant_id": "t1", "conversation_id": "conv-1"}]})
        mw._release_stock_reservations_for_order(sb, order_id="order-1", txn_status="DECLINED")
        self.assertEqual(sb.rpc_calls[0][0], "rpc_stock_reservation_release_by_conversation")

    def test_rpc_falla_no_propaga(self):
        sb = _Sb({"orders": [{"id": "order-1", "tenant_id": "t1", "conversation_id": "conv-1"}]},
                 rpc_handler=lambda n, p: RuntimeError("rpc down"))
        mw._release_stock_reservations_for_order(sb, order_id="order-1", txn_status="DECLINED")


# ─── Etapa 2 post-guía (email + WhatsApp con tracking) ────────────────────────


class PostGuideFlowTests(_EventDrivenTest):
    def test_guia_ok_dispara_notificacion_con_tracking(self):
        order = {
            "id": "order-1", "tenant_id": "t1", "status": "pending_payment",
            "conversation_id": "conv-1", "total_amount": 1350.0,
        }
        tables = _state_con_orden(order)
        tables["shipments"] = [{
            "order_id": "order-1", "tenant_id": "t1", "carrier": "SERVIENTREGA",
            "tracking_number": "GU-1", "tracking_url": "http://track/GU-1",
        }]
        sb = _Sb(tables)
        self.guide.return_value = True
        self._drive(_approved_payload(), sb)

        enqueue = [p for n, p in sb.rpc_calls if n == "enqueue_whatsapp_outbound_message"]
        texts = [p["p_message"]["text"] for p in enqueue]
        self.assertTrue(any("Guía asignada" in t and "GU-1" in t for t in texts),
                        "etapa 2 avisa la guía con su tracking (sin prometer 'en camino')")

    def test_error_en_notificacion_no_rompe_el_flujo(self):
        order = {
            "id": "order-1", "tenant_id": "t1", "status": "pending_payment",
            "conversation_id": "conv-1", "total_amount": 1350.0,
        }
        sb = _Sb(_state_con_orden(order))
        with patch.object(mw, "_notify_client_payment_approved", side_effect=RuntimeError("pgmq down")):
            self._drive(_approved_payload(), sb)
        self.decrement.assert_called_once()
        # El evento igual se marca procesado (la notif se recupera por otro canal).
        self.assertTrue(_updates_for(sb, "wompi_events_seen"))


# ─── Generación de guía Aveonline ────────────────────────────────────────────


def _fake_ave_module(guide_result=None, guide_exc=None):
    mod = types.ModuleType("integrations.aveonline_client")
    client = SimpleNamespace()
    client.calls = []

    async def _gen(**kwargs):
        client.calls.append(kwargs)
        if guide_exc:
            raise guide_exc
        return guide_result

    client.generate_guide = _gen
    mod.AveonlineClient = lambda tenant_id, supabase: client
    mod.to_aveonline_city_format = lambda city, state: (
        f"{city}-{state}".replace(" ", "").upper() if city else ""
    )
    mod._client = client
    return mod


_GUIDE_OK = {
    "ok": True, "tracking_number": "GU-1", "label_url": "http://label/GU-1",
    "tracking_url": "http://track/GU-1", "carrier_name": "SERVIENTREGA",
    "simulated": True, "raw": {},
}


def _guide_tables(**over):
    tables = {
        "tenant_shipping_provider_config": [{
            "tenant_id": "t1", "active_provider": "aveonline", "real_guides_enabled": False,
        }],
        "orders": [{
            "id": "order-1", "tenant_id": "t1", "total_amount": 50000,
            "shipping_cost": 8000, "payment_method": "credit",
            "contacts": {
                "name": "Ana Ruiz", "phone": "573001112233", "email": "ana@x.co",
                # dsnit válido según la regla real del server (live 2026-08-22:
                # numérico, ≥5 dígitos, >10000 — "" y "00000" son rechazados).
                "document_number": "1020304050",
                "address": {
                    "city": "Medellín", "state": "Antioquia",
                    "street": "Cra 10 # 20-30", "dane_code": "05001",
                    "neighborhood": "Laureles",
                },
            },
        }],
        "tenants": [{
            "id": "t1", "name": "Shop", "nit": "900123",
            "telefono_contacto": "3001112233", "email_contacto": "shop@x.co",
            "shipping_origin": {
                "city": "Bogotá", "state": "Cundinamarca", "street": "Cra 1 # 1-1",
                "dane_code": "11001", "name": "Bodega", "phone": "3001112233",
            },
        }],
        "conversation_carts": [{
            "tenant_id": "t1", "converted_order_id": "order-1",
            "shipping_meta": {
                "rate_id": "T1", "carrier": "SERVIENTREGA", "dane_code": "05001",
                "weight_inputs": {"weight_kg": 0.7, "length_cm": 20, "width_cm": 12, "height_cm": 6},
            },
        }],
        "order_items": [{"order_id": "order-1", "tenant_id": "t1", "title": "Jabón avena", "quantity": 2}],
        "shipments": [],
    }
    for key, val in over.items():
        if val is None:
            tables[key] = []
        else:
            tables[key] = val
    return tables


class GenerateGuideTests(unittest.TestCase):
    def setUp(self):
        p_env = patch.dict(os.environ, {
            "AVEONLINE_GENERATE_REAL_GUIDES": "false",
            "RESEND_API_KEY": "",
        })
        p_env.start()
        self.addCleanup(p_env.stop)

    def _run_guide(self, sb, fake_ave):
        with patch.dict(sys.modules, {"integrations.aveonline_client": fake_ave}):
            return _run(mw._generate_shipping_guide_async(
                sb, order_id="order-1", tenant_id="t1", delay_seconds=0.0,
            ))

    def test_provider_no_aveonline_skip(self):
        sb = _Sb(_guide_tables(
            tenant_shipping_provider_config=[{"tenant_id": "t1", "active_provider": "envia"}],
        ))
        ok = self._run_guide(sb, _fake_ave_module(_GUIDE_OK))
        self.assertFalse(ok)
        self.assertEqual(_inserts_for(sb, "shipments"), [])

    def test_contact_incompleto_skip(self):
        tables = _guide_tables()
        tables["orders"][0]["contacts"] = {"name": "Ana"}  # sin phone
        sb = _Sb(tables)
        self.assertFalse(self._run_guide(sb, _fake_ave_module(_GUIDE_OK)))

    def test_sin_direccion_skip(self):
        tables = _guide_tables()
        tables["orders"][0]["contacts"]["address"] = {}
        sb = _Sb(tables)
        self.assertFalse(self._run_guide(sb, _fake_ave_module(_GUIDE_OK)))

    def test_documento_destinatario_invalido_skip_antes_del_claim(self):
        """dsnit es OBLIGATORIO server-side (live 2026-08-22: "" y "00000" son
        rechazados aunque la doc lo exija solo para COD). Sin documento válido
        → skip ANTES del claim (operador completa el dato del contacto)."""
        for doc_malo in (None, "", "00000", "1000", "1234"):
            with self.subTest(document_number=doc_malo):
                tables = _guide_tables()
                tables["orders"][0]["contacts"]["document_number"] = doc_malo
                sb = _Sb(tables)
                fake = _fake_ave_module(dict(_GUIDE_OK))
                self.assertFalse(self._run_guide(sb, fake))
                self.assertEqual(fake._client.calls, [],
                                 "skip antes de llamar a Aveonline")
                self.assertEqual(_inserts_for(sb, "shipments"), [],
                                 "skip antes del claim-before-bill")

    def test_documento_con_formato_se_sanea_a_digitos(self):
        """'CC 1.020.304.050' → dsnit '1020304050' (solo dígitos)."""
        tables = _guide_tables()
        tables["orders"][0]["contacts"]["document_number"] = "CC 1.020.304.050"
        sb = _Sb(tables)
        fake = _fake_ave_module(dict(_GUIDE_OK))
        self.assertTrue(self._run_guide(sb, fake))
        self.assertEqual(fake._client.calls[0]["recipient"]["doc"], "1020304050")

    def test_tenant_sin_shipping_origin_skip(self):
        tables = _guide_tables()
        tables["tenants"][0]["shipping_origin"] = {}
        sb = _Sb(tables)
        self.assertFalse(self._run_guide(sb, _fake_ave_module(_GUIDE_OK)))

    def test_sin_carrier_rate_id_skip(self):
        tables = _guide_tables()
        tables["conversation_carts"][0]["shipping_meta"] = {}
        sb = _Sb(tables)
        self.assertFalse(self._run_guide(sb, _fake_ave_module(_GUIDE_OK)))

    def test_claim_duplicado_es_idempotente_no_factura(self):
        """Un 2º webhook/retry choca con el índice único → NO llama a Aveonline."""
        sb = _Sb(_guide_tables())
        sb.fail[("shipments", "insert")] = Exception("duplicate key (23505)")
        fake = _fake_ave_module(_GUIDE_OK)
        ok = self._run_guide(sb, fake)
        self.assertFalse(ok)
        self.assertEqual(fake._client.calls, [])

    def test_happy_simulado_persiste_tracking_y_valor_mercancia(self):
        sb = _Sb(_guide_tables())
        fake = _fake_ave_module(dict(_GUIDE_OK))
        ok = self._run_guide(sb, fake)

        self.assertTrue(ok)
        call = fake._client.calls[0]
        self.assertTrue(call["simulate"], "default fail-safe: guía SIMULADA")
        # valorDeclarado = mercancía (total - envío), NO el total con flete.
        self.assertEqual(call["package"]["declared_value_cop"], 42000)
        self.assertFalse(call["package"]["cod_enabled"])
        self.assertEqual(call["package"]["weight_kg"], 0.7, "reusa peso cotizado (F5)")
        # Claim insertado ANTES de facturar + contenido derivado de los items reales.
        claim = _inserts_for(sb, "shipments")[0]
        self.assertEqual(claim["status"], "generating")
        self.assertIn("2x Jabón avena", claim["parcels"][0]["content"])
        # Claim actualizado a simulated con tracking.
        upd = _updates_for(sb, "shipments")[-1]
        self.assertEqual(upd["status"], "simulated")
        self.assertEqual(upd["tracking_number"], "GU-1")

    def test_happy_cod_pasa_contraentrega_y_recaudo_total(self):
        tables = _guide_tables()
        tables["orders"][0]["payment_method"] = "cod"
        sb = _Sb(tables)
        fake = _fake_ave_module(dict(_GUIDE_OK))
        self.assertTrue(self._run_guide(sb, fake))
        package = fake._client.calls[0]["package"]
        self.assertTrue(package["cod_enabled"])
        self.assertEqual(package["valorrecaudo"], 50000, "el courier recauda productos + envío")

    def test_guias_reales_requieren_master_y_tenant(self):
        # Master OFF + tenant ON → simulado.
        tables = _guide_tables()
        tables["tenant_shipping_provider_config"][0]["real_guides_enabled"] = True
        sb = _Sb(tables)
        fake = _fake_ave_module(dict(_GUIDE_OK))
        self.assertTrue(self._run_guide(sb, fake))
        self.assertTrue(fake._client.calls[0]["simulate"], "kill-switch global OFF manda")

    def test_guias_reales_con_ambos_flags(self):
        tables = _guide_tables()
        tables["tenant_shipping_provider_config"][0]["real_guides_enabled"] = True
        sb = _Sb(tables)
        fake = _fake_ave_module(dict(_GUIDE_OK))
        with patch.dict(os.environ, {"AVEONLINE_GENERATE_REAL_GUIDES": "true"}):
            self.assertTrue(self._run_guide(sb, fake))
        self.assertFalse(fake._client.calls[0]["simulate"])
        self.assertEqual(_updates_for(sb, "shipments")[-1]["status"], "labeled")

    def test_aveonline_rechaza_deja_pending_generation_reintentable(self):
        sb = _Sb(_guide_tables())
        fake = _fake_ave_module({"ok": False, "error": "sin cobertura", "code": "AVEONLINE_GUIDE_ERROR"})
        ok = self._run_guide(sb, fake)
        self.assertFalse(ok)
        upd = _updates_for(sb, "shipments")[-1]
        self.assertEqual(upd["status"], "pending_generation",
                         "no facturó → fuera del índice único → reintento seguro")

    def test_excepcion_simulada_deja_pending_generation(self):
        sb = _Sb(_guide_tables())
        fake = _fake_ave_module(guide_exc=RuntimeError("timeout"))
        self.assertFalse(self._run_guide(sb, fake))
        upd = _updates_for(sb, "shipments")[-1]
        self.assertEqual(upd["status"], "pending_generation")
        self.assertFalse(upd["quote_response"]["ambiguous_bill"])

    def test_excepcion_real_queda_generating_money_safe(self):
        """Timeout facturando guía REAL: puede haber cobro → bloquear auto-retry."""
        tables = _guide_tables()
        tables["tenant_shipping_provider_config"][0]["real_guides_enabled"] = True
        sb = _Sb(tables)
        fake = _fake_ave_module(guide_exc=RuntimeError("timeout"))
        with patch.dict(os.environ, {"AVEONLINE_GENERATE_REAL_GUIDES": "true"}):
            self.assertFalse(self._run_guide(sb, fake))
        upd = _updates_for(sb, "shipments")[-1]
        self.assertEqual(upd["status"], "generating")
        self.assertTrue(upd["quote_response"]["ambiguous_bill"])

    def test_wrapper_sync_respeta_delay_env(self):
        sb = _Sb(_guide_tables(
            tenant_shipping_provider_config=[{"tenant_id": "t1", "active_provider": "envia"}],
        ))
        with patch.dict(os.environ, {"GUIDE_GENERATION_DELAY_SECONDS": "0"}), \
             patch.dict(sys.modules, {"integrations.aveonline_client": _fake_ave_module(_GUIDE_OK)}):
            self.assertFalse(mw._generate_shipping_guide(sb, order_id="order-1", tenant_id="t1"))

    def test_delay_invalido_cae_al_default(self):
        sb = _Sb(_guide_tables(
            tenant_shipping_provider_config=[{"tenant_id": "t1", "active_provider": "envia"}],
        ))
        with patch.dict(os.environ, {"GUIDE_GENERATION_DELAY_SECONDS": "no-numero"}), \
             patch.object(shipping_guides.asyncio, "sleep", new=AsyncMock()) as sleep, \
             patch.dict(sys.modules, {"integrations.aveonline_client": _fake_ave_module(_GUIDE_OK)}):
            mw._generate_shipping_guide(sb, order_id="order-1", tenant_id="t1")
        sleep.assert_awaited_once_with(60.0)


# ─── Emails del ciclo de vida ────────────────────────────────────────────────


class _FakeSyncClient:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.calls = []

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self._exc:
            raise self._exc
        return self._resp


def _resp(status=200, payload=None, text=""):
    r = SimpleNamespace()
    r.status_code = status
    r.json = lambda: (payload or {"id": "re_1"})
    r.text = text
    return r


def _email_tables():
    return {
        "orders": [{
            "id": "order-1", "tenant_id": "t1", "total_amount": 50000,
            "shipping_cost": 8000, "contact_id": "c1",
            "contacts": {"name": "Ana", "email": "ana@x.co"},
        }],
        "order_items": [{"order_id": "order-1", "tenant_id": "t1",
                         "title": "Jabón", "quantity": 2, "unit_price": 21000}],
        "tenants": [{"id": "t1", "name": "Shop"}],
        "shipments": [{
            "order_id": "order-1", "tenant_id": "t1", "carrier": "SERVIENTREGA",
            "tracking_number": "GU-1", "tracking_url": "http://track/GU-1",
            "label_url": "http://label/GU-1", "status": "labeled",
        }],
    }


class SendEmailTests(unittest.TestCase):
    def _send(self, sb, mode="payment_confirmed"):
        mw._send_payment_confirmation_email(
            sb, order_id="order-1", tenant_id="t1", template_mode=mode,
        )

    def test_sin_api_key_no_hace_nada(self):
        sb = _Sb(_email_tables())
        with patch.dict(os.environ, {"RESEND_API_KEY": ""}):
            self._send(sb)
        self.assertEqual(sb.queries, [], "sin RESEND_API_KEY sale antes de leer la DB")

    def test_contact_sin_email_skip(self):
        tables = _email_tables()
        tables["orders"][0]["contacts"] = {"name": "Ana"}
        sb = _Sb(tables)
        client = _FakeSyncClient(_resp())
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
             patch("httpx.Client", client):
            self._send(sb)
        self.assertEqual(client.calls, [])

    def test_error_leyendo_orden_sale_quieto(self):
        sb = _Sb()
        sb.fail[("orders", "select")] = RuntimeError("db down")
        client = _FakeSyncClient(_resp())
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
             patch("httpx.Client", client):
            self._send(sb)
        self.assertEqual(client.calls, [])

    def test_payment_confirmed_envia_con_idempotency_key(self):
        sb = _Sb(_email_tables())
        client = _FakeSyncClient(_resp())
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
             patch("httpx.Client", client):
            self._send(sb)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["json"]["to"], ["ana@x.co"])
        self.assertIn("Pago recibido", call["json"]["subject"])
        self.assertIn("42.000", call["json"]["html"], "desglose subtotal = total - envío")
        self.assertTrue(call["json"]["text"], "parte text/plain anti-spam")
        self.assertEqual(
            call["headers"]["Idempotency-Key"], "t1:order-1:payment_confirmed",
        )

    def test_modos_mapean_subject(self):
        casos = [
            ("payment_failed", "Pago no procesado"),
            ("shipment_label_ready", "Guía generada"),
            ("shipment_in_transit", "en ruta"),
            ("shipment_delivered", "entregado"),
            ("shipment_exception", "Novedad"),
            ("refund_completed", "Reembolso confirmado"),
            ("modo_desconocido", "Confirmación pedido"),
        ]
        for mode, fragmento in casos:
            with self.subTest(mode=mode):
                sb = _Sb(_email_tables())
                client = _FakeSyncClient(_resp())
                with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
                     patch("httpx.Client", client):
                    self._send(sb, mode=mode)
                self.assertIn(fragmento, client.calls[0]["json"]["subject"])

    def test_429_loguea_quota_como_error(self):
        sb = _Sb(_email_tables())
        client = _FakeSyncClient(_resp(429, text="rate limited"))
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
             patch("httpx.Client", client), \
             self.assertLogs("lib.client_notifications", level="ERROR") as cap:
            self._send(sb)
        self.assertTrue(any("RATE/QUOTA 429" in line for line in cap.output))

    def test_4xx_loguea_config_como_error(self):
        sb = _Sb(_email_tables())
        client = _FakeSyncClient(_resp(403, text="invalid key"))
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
             patch("httpx.Client", client), \
             self.assertLogs("lib.client_notifications", level="ERROR") as cap:
            self._send(sb)
        self.assertTrue(any("resend 4xx status=403" in line for line in cap.output))

    def test_5xx_loguea_transitorio_como_error(self):
        sb = _Sb(_email_tables())
        client = _FakeSyncClient(_resp(500, text="resend down"))
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
             patch("httpx.Client", client), \
             self.assertLogs("lib.client_notifications", level="ERROR") as cap:
            self._send(sb)
        self.assertTrue(any("resend 5xx status=500" in line for line in cap.output))

    def test_error_de_red_loguea_transport_exception(self):
        sb = _Sb(_email_tables())
        client = _FakeSyncClient(exc=RuntimeError("dns"))
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_x"}), \
             patch("httpx.Client", client), \
             self.assertLogs("lib.client_notifications", level="WARNING") as cap:
            self._send(sb)
        self.assertTrue(any("httpx err" in line for line in cap.output))


class ComposerTests(unittest.TestCase):
    BASE = dict(customer_name="Ana", order_short="ABC123", subtotal=42000,
                shipping=8000, total=50000, carrier="SERVIENTREGA", tenant_name="Shop")

    def test_payment_email_con_tracking(self):
        html = mw._compose_payment_email_html(
            **self.BASE, items=[{"title": "Jabón", "quantity": 2, "unit_price": 21000}],
            tracking_number="GU-1", tracking_url="http://track/GU-1",
            label_url="http://label/GU-1", shipment_status="labeled",
        )
        self.assertIn("GU-1", html)
        self.assertIn("Jabón", html)
        self.assertIn("$50.000", html)

    def test_payment_failed_email(self):
        html = mw._compose_payment_failed_email_html(
            **self.BASE, items=[{"title": "Jabón", "quantity": 1, "unit_price": 42000}],
        )
        self.assertIn("ABC123", html)
        self.assertIn("Ana", html)

    def test_label_ready_email(self):
        html = mw._compose_shipment_label_ready_email_html(
            **self.BASE, items=[], tracking_number="GU-1",
            tracking_url="http://track/GU-1", label_url="http://label/GU-1",
            shipment_status="labeled",
        )
        self.assertIn("GU-1", html)
        self.assertIn("http://track/GU-1", html)

    def test_in_transit_email(self):
        html = mw._compose_shipment_in_transit_email_html(
            customer_name="Ana", order_short="ABC123", carrier="SERVIENTREGA",
            tenant_name="Shop", tracking_number="GU-1",
            tracking_url="http://track/GU-1", raw_status="En camino",
        )
        self.assertIn("GU-1", html)
        self.assertIn("En camino", html)

    def test_delivered_email(self):
        html = mw._compose_shipment_delivered_email_html(
            customer_name="Ana", order_short="ABC123", carrier="SERVIENTREGA",
            tenant_name="Shop", tracking_number="GU-1",
        )
        self.assertIn("entregado", html.lower())

    def test_exception_email(self):
        html = mw._compose_shipment_exception_email_html(
            customer_name="Ana", order_short="ABC123", carrier="SERVIENTREGA",
            tenant_name="Shop", tracking_number="GU-1", raw_status="Cliente ausente",
        )
        self.assertIn("Cliente ausente", html)

    def test_refund_completed_email(self):
        html = mw._compose_refund_completed_email_html(
            customer_name="Ana", order_short="ABC123", total=50000, tenant_name="Shop",
        )
        self.assertIn("$50.000", html)
        self.assertIn("ABC123", html)


class TextHelpersTests(unittest.TestCase):
    def test_fmt_cop(self):
        self.assertEqual(mw._fmt_cop(50000), "$50.000")
        self.assertEqual(mw._fmt_cop(1350), "$1.350")

    def test_mask_email(self):
        self.assertEqual(mw._mask_email("juan@x.co"), "ju**@x.co")
        self.assertEqual(mw._mask_email("sin-arroba"), "***")
        self.assertEqual(mw._mask_email(""), "***")

    def test_html_to_text(self):
        text = mw._html_to_text("<p>Hola<br>mundo</p><script>x()</script>")
        self.assertIn("Hola", text)
        self.assertIn("mundo", text)
        self.assertNotIn("<p>", text)
        self.assertNotIn("x()", text)

    def test_humanize_shipment_status(self):
        self.assertEqual(mw._humanize_shipment_status("EN RUTA", ""), "En ruta")
        self.assertEqual(mw._humanize_shipment_status("Cliente ausente", ""), "Cliente ausente")
        self.assertEqual(mw._humanize_shipment_status("", "in_transit"), "En camino")
        self.assertEqual(mw._humanize_shipment_status("", ""), "")


# ─── Notificaciones WhatsApp del ciclo de envío ───────────────────────────────


class NotifyHelpersTests(unittest.TestCase):
    def _sb(self, phone="573001112233"):
        return _Sb({"conversations": [{
            "id": "conv-1", "tenant_id": "t1", "customer_phone": phone,
        }]})

    def _enqueue_texts(self, sb):
        return [p["p_message"]["text"] for n, p in sb.rpc_calls
                if n == "enqueue_whatsapp_outbound_message"]

    def test_label_ready(self):
        sb = self._sb()
        mw._notify_client_shipment_label_ready(
            sb, conversation_id="conv-1", tenant_id="t1", order_id="order-1234",
            carrier="SERVIENTREGA", tracking_number="GU-1", tracking_url="http://track/GU-1",
        )
        text = self._enqueue_texts(sb)[0]
        self.assertIn("Guía asignada", text)
        self.assertIn("GU-1", text)
        self.assertNotIn("en camino", text.lower(), "la guía no promete despacho físico")

    def test_in_transit(self):
        sb = self._sb()
        mw._notify_client_shipment_in_transit(
            sb, conversation_id="conv-1", tenant_id="t1", order_id="order-1234",
            carrier="SERVIENTREGA", tracking_number="GU-1",
            tracking_url="http://track/GU-1", raw_status="EN RUTA",
        )
        text = self._enqueue_texts(sb)[0]
        self.assertIn("en ruta", text.lower())
        self.assertIn("EN RUTA", text)

    def test_delivered(self):
        sb = self._sb()
        mw._notify_client_shipment_delivered(
            sb, conversation_id="conv-1", tenant_id="t1", order_id="order-1234",
            carrier="SERVIENTREGA", tracking_number="GU-1",
        )
        self.assertIn("entregado", self._enqueue_texts(sb)[0].lower())

    def test_exception(self):
        sb = self._sb()
        mw._notify_client_shipment_exception(
            sb, conversation_id="conv-1", tenant_id="t1", order_id="order-1234",
            carrier="SERVIENTREGA", tracking_number="GU-1", raw_status="Dirección errada",
        )
        text = self._enqueue_texts(sb)[0]
        self.assertIn("Novedad", text)
        self.assertIn("Dirección errada", text)

    def test_sin_phone_no_encola(self):
        sb = self._sb(phone="")
        mw._notify_client_shipment_delivered(
            sb, conversation_id="conv-1", tenant_id="t1", order_id="order-1234",
            carrier="SERVIENTREGA", tracking_number="GU-1",
        )
        self.assertEqual(self._enqueue_texts(sb), [])


class EscalationRoleTests(unittest.TestCase):
    def test_role_configurado(self):
        sb = _Sb({"tenants": [{"id": "t1", "escalation_role": "Especialista"}]})
        self.assertEqual(mw._get_tenant_escalation_role(sb, "t1"), "especialista")

    def test_role_default_y_error(self):
        self.assertEqual(mw._get_tenant_escalation_role(_Sb(), "t1"), "asesor")
        sb = _Sb()
        sb.fail[("tenants", "select")] = RuntimeError("db down")
        self.assertEqual(mw._get_tenant_escalation_role(sb, "t1"), "asesor")


# ─── Endpoint + inbox durable ─────────────────────────────────────────────────


class EndpointTests(unittest.TestCase):
    def setUp(self):
        p_client = patch.object(mw, "_get_service_client")
        self.get_client = p_client.start()
        self.addCleanup(p_client.stop)
        p_ip = patch.object(mw, "_client_ip", return_value="1.2.3.4")
        p_ip.start()
        self.addCleanup(p_ip.stop)

    def _request(self, body=None, raises=False):
        req = MagicMock()
        if raises:
            req.json = AsyncMock(side_effect=ValueError("no json"))
        else:
            req.json = AsyncMock(return_value=body)
        return req

    def _bt(self):
        from fastapi import BackgroundTasks
        return BackgroundTasks()

    def test_rate_limited_429(self):
        with patch.object(mw, "webhook_rate_limit_check", return_value=(False, 30)):
            resp = _run(mw.wompi_webhook(self._request({}), self._bt()))
        self.assertEqual(resp.status_code, 429)

    def test_rate_limiter_caido_es_fail_open(self):
        """Un error del limiter NUNCA dropea un webhook de pago legítimo."""
        with patch.object(mw, "webhook_rate_limit_check", side_effect=RuntimeError("redis down")):
            resp = _run(mw.wompi_webhook(self._request({"event": "other"}), self._bt()))
        self.assertEqual(resp.status_code, 200)

    def test_body_invalido_200_sin_inbox(self):
        sb = _Sb()
        self.get_client.return_value = sb
        resp = _run(mw.wompi_webhook(self._request(raises=True), self._bt()))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sb.queries, [])

    def test_transaction_updated_persiste_inbox_antes_del_ack(self):
        sb = _Sb()
        self.get_client.return_value = sb
        payload = WompiPayloadBuilder().with_approved_txn().build()
        bt = self._bt()
        with patch.object(mw, "webhook_rate_limit_check", return_value=(True, 0)):
            resp = _run(mw.wompi_webhook(self._request(payload), bt))
        self.assertEqual(resp.status_code, 200)
        inbox = _inserts_for(sb, "wompi_webhook_inbox")
        self.assertEqual(len(inbox), 1, "el payload crudo queda durable ANTES del 200")
        self.assertEqual(inbox[0]["checksum"], payload["signature"]["checksum"])
        self.assertEqual(len(bt.tasks), 1)
        self.assertEqual(bt.tasks[0].func, mw._process_wompi_event_durable)

    def test_evento_no_transaction_no_ensucia_inbox(self):
        sb = _Sb()
        self.get_client.return_value = sb
        bt = self._bt()
        with patch.object(mw, "webhook_rate_limit_check", return_value=(True, 0)):
            _run(mw.wompi_webhook(self._request({"event": "payment_link.created"}), bt))
        self.assertEqual(_inserts_for(sb, "wompi_webhook_inbox"), [])

    def test_inbox_sin_checksum_no_persiste(self):
        sb = _Sb()
        self.get_client.return_value = sb
        payload = WompiPayloadBuilder().with_approved_txn().build()
        payload["signature"]["checksum"] = ""
        with patch.object(mw, "webhook_rate_limit_check", return_value=(True, 0)):
            _run(mw.wompi_webhook(self._request(payload), self._bt()))
        self.assertEqual(_inserts_for(sb, "wompi_webhook_inbox"), [])


class InboxHelpersTests(unittest.TestCase):
    def test_persist_inbox_duplicado_se_traga(self):
        sb = _Sb()
        sb.fail[("wompi_webhook_inbox", "insert")] = Exception("duplicate key (23505)")
        mw._persist_inbox(sb, "chk", {})  # no lanza

    def test_persist_inbox_otro_error_propaga(self):
        sb = _Sb()
        sb.fail[("wompi_webhook_inbox", "insert")] = RuntimeError("db down")
        with self.assertRaises(RuntimeError):
            mw._persist_inbox(sb, "chk", {})

    def test_mark_processed_error_se_traga(self):
        sb = _Sb()
        sb.fail[("wompi_webhook_inbox", "update")] = RuntimeError("db down")
        mw._mark_inbox_processed(sb, "chk")

    def test_record_error_se_traga(self):
        sb = _Sb()
        sb.fail[("wompi_webhook_inbox", "update")] = RuntimeError("db down")
        mw._record_inbox_error(sb, "chk", "boom")


class DurableWrapperTests(unittest.TestCase):
    def setUp(self):
        p_client = patch.object(mw, "_get_service_client")
        self.get_client = p_client.start()
        self.addCleanup(p_client.stop)

    def test_exito_marca_procesado(self):
        sb = _Sb()
        self.get_client.return_value = sb
        payload = WompiPayloadBuilder().with_approved_txn().build()
        with patch.object(mw, "_process_wompi_event"):
            mw._process_wompi_event_durable(payload)
        upd = _updates_for(sb, "wompi_webhook_inbox")
        self.assertEqual(len(upd), 1)
        self.assertIn("processed_at", upd[0])

    def test_fallo_registra_error_y_no_marca(self):
        sb = _Sb()
        self.get_client.return_value = sb
        payload = WompiPayloadBuilder().with_approved_txn().build()
        with patch.object(mw, "_process_wompi_event", side_effect=RuntimeError("crash")):
            mw._process_wompi_event_durable(payload)
        upd = _updates_for(sb, "wompi_webhook_inbox")
        self.assertEqual(len(upd), 1)
        self.assertIn("last_error", upd[0])
        self.assertNotIn("processed_at", upd[0], "queda para reconciliación del worker")


if __name__ == "__main__":
    unittest.main()

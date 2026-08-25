"""Paridad de OUTCOME del pipeline de cancelación (Track 5 M2.2 — criterio §7.2
extendido a la operación que mueve dinero).

El bot conserva su pipeline congelado (`services/ai-orchestrator/lib/
order_cancellation.py`) hasta el bloque bot (B-2). Mientras tanto, este test
certifica que el pipeline unificado del paquete (`konvi_domain.orders.
cancellation`) produce EXACTAMENTE el mismo outcome para el mismo input:

  • mismos campos del CancellationResult (success/status/refund_*/escalación/
    mensajes),
  • mismas escrituras de dominio en DB (inserts/updates en order_cancellations,
    orders, payments, shipments + mismas llamadas RPC con mismos parámetros).

Se excluyen los valores inherentemente distintos por corrida (uuid de la fila de
auditoría, timestamps cancelled_at/completed_at). Si el paquete y el bot
divergen en el futuro, este test falla — la duplicación time-boxed tiene alarma.

Fake `_Sb` (stateful, filtra por eq/in) reutilizado de
tests/test_order_cancellation_pipeline.py (patrón test→test ya establecido en
el repo: test_wompi_webhook).
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

# Pipeline del BOT (copia congelada — baseline de outcome).
from lib.order_cancellation import cancel_order as bot_cancel_order  # noqa: E402
from test_order_cancellation_pipeline import (  # noqa: E402
    ORDER, PAYMENT_CARD, _Sb, _fake_ave_module, _fake_wompi_module,
)

# Pipeline del PAQUETE (única fuente futura).
from konvi_domain.orders.cancellation import (  # noqa: E402
    CancellationPorts,
    CancellationRequest as PkgReq,
)
from konvi_domain.orders.cancellation import cancel_order as pkg_cancel_order  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _bot_request(**over):
    from lib.order_cancellation import CancellationRequest as BotReq
    base = dict(order_id="order-1", tenant_id="t1", actor="customer",
                reason_text="quiero cancelar", conversation_id="conv-1")
    base.update(over)
    return BotReq(**base)


def _pkg_request(**over):
    base = dict(order_id="order-1", tenant_id="t1", actor="customer",
                reason_text="quiero cancelar", conversation_id="conv-1")
    base.update(over)
    return PkgReq(**base)


def _pkg_ports(*, void_creds=("PRIV", "sandbox"), void_exc=None, void_calls=None,
               guide_result=None, guide_exc=None):
    """Puertos equivalentes a los módulos falsos del harness del bot."""
    def _void_credentials(tenant_id):
        return void_creds

    def _void_payment(private_key, environment, txn_id):
        if void_calls is not None:
            void_calls.append({"private_key": private_key, "environment": environment,
                               "transaction_id": txn_id})
        if void_exc:
            raise void_exc

    async def _cancel_guide(tenant_id, tracking):
        if guide_exc:
            raise guide_exc
        return guide_result if guide_result is not None else {"ok": True, "method": "aveonline_api"}

    return CancellationPorts(
        void_credentials=_void_credentials,
        void_payment=_void_payment,
        cancel_shipping_guide=_cancel_guide,
    )


# Campos volátiles por corrida (uuid de auditoría + timestamps).
_VOLATILE_INSERT = {"id"}
_VOLATILE_UPDATE = {"cancelled_at", "completed_at", "cancellation_id", "refund_completed_at"}


def _trace(sb: _Sb) -> dict:
    """Huella de dominio comparable: inserts/updates/rpc sin volátiles."""
    ins = [
        (t, {k: v for k, v in p.items() if k not in _VOLATILE_INSERT})
        for t, p in sb.inserts
    ]
    upd = [
        (t, {k: v for k, v in p.items() if k not in _VOLATILE_UPDATE})
        for t, p, _f in sb.updates
    ]
    rpc = [(name, params) for name, params in sb.rpc_calls]
    return {"inserts": ins, "updates": upd, "rpc": rpc}


def _result_tuple(r) -> tuple:
    return (
        r.success, r.status, r.requires_escalation, tuple(r.escalation_reasons),
        r.refund_method, r.refund_status, r.refund_amount_cents,
        r.customer_message, r.operator_notification,
    )


class CancellationOutcomeParityTests(unittest.TestCase):
    """Cada escenario corre el MISMO input por el pipeline del bot (con los
    módulos falsos de su harness) y por el del paquete (con puertos
    equivalentes) sobre dos _Sb idénticos, y compara resultado + huella DB."""

    def _run_both(self, *, tables, request_over=None, void_exc=None,
                  void_eligible=True, guide_result=None, guide_exc=None):
        request_over = request_over or {}

        # — Canal bot (congelado): sus imports lazy resueltos a módulos falsos.
        sb_bot = _Sb(tables)
        fake_wompi = _fake_wompi_module(void_exc=void_exc, eligible=void_eligible)
        fake_ave = _fake_ave_module(
            cancel_result=({"ok": True} if guide_result is None else guide_result),
            cancel_exc=guide_exc,
        )
        # El método de auditoría del bot es "aveonline_api" fijo en su copia.
        bot_void_calls = fake_wompi._calls["void"]
        with _patched_modules(fake_wompi, fake_ave):
            r_bot = _run(bot_cancel_order(sb_bot, _bot_request(**request_over)))

        # — Canal paquete: puertos equivalentes.
        sb_pkg = _Sb(tables)
        pkg_void_calls: list = []
        r_pkg = _run(pkg_cancel_order(
            sb_pkg, _pkg_request(**request_over),
            ports=_pkg_ports(void_exc=void_exc, void_calls=pkg_void_calls,
                             guide_result=(
                                {"ok": guide_result.get("ok", True),
                                 "method": "aveonline_api"}
                                if guide_result is not None else None
                             ), guide_exc=guide_exc),
        ))
        return r_bot, r_pkg, sb_bot, sb_pkg, bot_void_calls, pkg_void_calls

    def test_happy_path_cancel_total_sin_pago(self):
        tables = {"orders": [ORDER], "stock_movements": [
            {"variation_id": "v1", "delta": -2, "tenant_id": "t1",
             "order_id": "order-1", "reason": "sale"},
        ]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))
        self.assertEqual(r_pkg.status, "completed")
        self.assertEqual(r_pkg.refund_method, "no_refund_no_payment")

    def test_escalacion_customer_por_entregado(self):
        tables = {"orders": [dict(ORDER, status="delivered")]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertTrue(r_pkg.requires_escalation)
        self.assertIn("ORDER_DELIVERED", r_pkg.escalation_reasons)
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))
        # La orden NO se tocó en ninguno de los dos caminos.
        self.assertFalse([u for u in sb_pkg.updates if u[0] == "orders"])

    def test_card_void_auto_completo(self):
        # Pago CARD reciente (ventana de void <23h) → la regla real del paquete
        # dice elegible y el fake del bot (eligible=True) también: ambos voidean.
        from datetime import datetime, timedelta, timezone
        pago_reciente = dict(PAYMENT_CARD)
        pago_reciente["raw_webhook"] = {"data": {"transaction": {
            "payment_method_type": "CARD",
            "finalized_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }}}
        tables = {"orders": [ORDER], "payments": [pago_reciente]}
        r_bot, r_pkg, sb_bot, sb_pkg, bot_void, pkg_void = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(r_pkg.refund_method, "wompi_void_auto")
        self.assertEqual(r_pkg.refund_status, "completed")
        # El void se ejecutó en ambos caminos sobre la misma txn.
        self.assertEqual(len(bot_void), 1)
        self.assertEqual(len(pkg_void), 1)
        self.assertEqual(pkg_void[0]["transaction_id"], "txn-1")
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))

    def test_card_void_no_elegible_va_a_manual(self):
        pago_viejo = dict(PAYMENT_CARD)
        pago_viejo["raw_webhook"] = {"data": {"transaction": {
            "payment_method_type": "CARD", "finalized_at": "2020-01-01T00:00:00Z",
        }}}
        tables = {"orders": [ORDER], "payments": [pago_viejo]}
        # Bot: su fake declara NO elegible; paquete: la regla real (ventana 23h)
        # dice lo mismo por el timestamp viejo. Ambos → manual.
        r_bot, r_pkg, sb_bot, sb_pkg, bot_void, pkg_void = self._run_both(
            tables=tables, void_eligible=False,
        )
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(r_pkg.refund_status, "pending_manual")
        self.assertEqual(bot_void, [])
        self.assertEqual(pkg_void, [])
        self.assertIn("Refund manual requerido", r_pkg.operator_notification)
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))

    def test_void_falla_escala_a_manual_en_ambos(self):
        tables = {"orders": [ORDER], "payments": [PAYMENT_CARD]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(
            tables=tables, void_exc=RuntimeError("wompi down"),
        )
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(r_pkg.refund_status, "pending_manual")
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))

    def test_shipment_simulado_se_cancela_sin_api(self):
        tables = {"orders": [ORDER], "shipments": [{
            "order_id": "order-1", "tenant_id": "t1", "status": "simulated",
            "tracking_number": "KAIU123", "carrier": "COORDINADORA", "service": None,
        }]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))
        upd_ship = [u for u in sb_pkg.updates if u[0] == "shipments"]
        self.assertEqual(upd_ship[0][1], {"status": "cancelled"})

    def test_guia_real_cancelada_via_api(self):
        tables = {"orders": [ORDER], "shipments": [{
            "order_id": "order-1", "tenant_id": "t1", "status": "labeled",
            "tracking_number": "KAIU999", "carrier": "COORDINADORA", "service": None,
        }]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        # El método de auditoría es el del proveedor real en ambos caminos.
        upd_cancel = [u for u in sb_pkg.updates if u[0] == "order_cancellations"]
        self.assertEqual(upd_cancel[-1][1]["shipping_cancel_method"], "aveonline_api")
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))

    def test_cod_no_hay_dinero_que_devolver(self):
        # Orden COD con pago APROVED → branch cod_not_collected (sin devolución).
        tables = {"orders": [dict(ORDER, payment_method="cod")],
                  "payments": [dict(PAYMENT_CARD, status="approved")]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(r_pkg.refund_method, "cod_not_collected")
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))

    def test_payment_cod_pending_sin_reembolso_en_ambos(self):
        # COD aún no cobrado → no_refund_no_payment (paridad de la guarda temprana).
        tables = {"orders": [dict(ORDER, payment_method="cod")],
                  "payments": [dict(PAYMENT_CARD, status="cod_pending")]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(r_pkg.refund_method, "no_refund_no_payment")
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))

    def test_fallo_restock_marca_partial_failure_en_ambos(self):
        # Mismo mecanismo que el test del bot: el SELECT de stock_movements
        # revienta → _restore_stock retorna (False, "failed") → partial_failure.
        tables = {"orders": [ORDER], "stock_movements": [
            {"variation_id": "v1", "delta": -1, "tenant_id": "t1",
             "order_id": "order-1", "reason": "sale"},
        ]}

        sb_bot = _Sb(tables)
        sb_bot.fail[("stock_movements", "select")] = RuntimeError("db down")
        with _patched_modules(_fake_wompi_module(), _fake_ave_module()):
            r_bot = _run(bot_cancel_order(sb_bot, _bot_request()))
        sb_pkg = _Sb(tables)
        sb_pkg.fail[("stock_movements", "select")] = RuntimeError("db down")
        r_pkg = _run(pkg_cancel_order(sb_pkg, _pkg_request(), ports=_pkg_ports()))

        self.assertEqual(r_bot.status, r_pkg.status)
        self.assertEqual(r_pkg.status, "partial_failure")
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))

    def test_orden_ya_cancelada_es_idempotente_en_ambos(self):
        tables = {"orders": [dict(ORDER, status="cancelled")]}
        r_bot, r_pkg, sb_bot, sb_pkg, *_ = self._run_both(tables=tables)
        self.assertEqual(_result_tuple(r_bot), _result_tuple(r_pkg))
        self.assertEqual(r_pkg.status, "completed")
        self.assertEqual(_trace(sb_bot), _trace(sb_pkg))


class _patched_modules:
    """Contexto: sys.modules falsos para los imports lazy del pipeline del bot
    (mismo patrón que tests/test_order_cancellation_pipeline.py)."""

    def __init__(self, wompi_mod, ave_mod):
        self._mods = {
            "integrations.wompi_client": wompi_mod,
            "integrations.aveonline_client": ave_mod,
        }
        self._saved = {}

    def __enter__(self):
        for name, mod in self._mods.items():
            self._saved[name] = sys.modules.get(name)
            sys.modules[name] = mod

    def __exit__(self, *exc):
        for name, old in self._saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


if __name__ == "__main__":
    unittest.main()

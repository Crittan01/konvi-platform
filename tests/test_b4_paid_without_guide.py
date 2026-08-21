"""B4 (auditoría money-path 2026-08-21) — pagado-sin-guía deja de ser silencioso.

Cubre:
  • Reconciliador del worker `_reconcile_paid_without_guide_if_due`
    (services/ai-orchestrator/worker.py): órdenes confirmed >15 min sin guía →
    alerta Telegram UNA vez por orden (marca paid_no_guide_alerted_at).
  • Alerta inmediata del webhook `_alert_paid_without_guide_operator`
    (services/api/routers/wompi_webhook.py): solo tenants Aveonline.
  • Helper api-side `notify_operator_telegram`
    (services/api/lib/operator_alerts.py): settings/vault/HTTP best-effort.
"""
import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "ai-orchestrator"))
sys.path.insert(0, str(ROOT / "services" / "api"))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Reconciliador del worker ────────────────────────────────────────────────

class _Chain:
    def __init__(self, ctrl, table):
        self.ctrl, self.table = ctrl, table

    def select(self, *a, **k):
        return self

    def update(self, data, *a, **k):
        self.ctrl.updates.append((self.table, data))
        return self

    def eq(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.ctrl.data_for(self.table))


class _WorkerSb:
    def __init__(self, *, orders=None, shipments=None):
        self._orders = orders or []
        self._shipments = shipments or []
        self.updates = []
        self.queries = []

    def data_for(self, table):
        if table == "orders":
            return self._orders
        if table == "shipments":
            return self._shipments
        return []

    def table(self, name):
        self.queries.append(name)
        return _Chain(self, name)


class _WorkerSbRaises(_WorkerSb):
    def table(self, name):
        self.queries.append(name)
        chain = _Chain(self, name)
        if name == "orders":
            chain.execute = MagicMock(side_effect=Exception(
                'column "paid_no_guide_alerted_at" does not exist'))
        return chain


_CANDIDATE = {
    "id": "aaaaaaa1-0000-0000-0000-000000000001",
    "tenant_id": "tenant-1",
    "total_amount": 2100.0,
    "payment_method": "credit",
    "created_at": "2026-08-21T10:00:00+00:00",
}


def _worker_stub(sb, *, enabled=True, last_at=0.0):
    """Stub spec'd del worker (patrón tests/test_meli_token_refresh_worker.py)."""
    from worker import OrchestratorWorker
    stub = MagicMock(spec=OrchestratorWorker)
    stub.supabase = sb
    stub._paid_no_guide_enabled = enabled
    stub._last_paid_no_guide_at = last_at
    stub._metrics = {"paid_no_guide_alerts_sent": 0, "paid_no_guide_errors": 0}
    return stub


def _run_reconciler(stub, *, telegram_ok=True):
    from worker import OrchestratorWorker
    with patch("telegram_notifications.notify_escalation_async",
               new=AsyncMock(return_value=telegram_ok)) as mock_tg:
        _run(OrchestratorWorker._reconcile_paid_without_guide_if_due(stub))
    return mock_tg


class PaidNoGuideReconcilerTests(unittest.TestCase):
    def test_disabled_no_consulta(self):
        sb = _WorkerSb(orders=[_CANDIDATE])
        stub = _worker_stub(sb, enabled=False)
        mock_tg = _run_reconciler(stub)
        self.assertEqual(sb.queries, [])
        mock_tg.assert_not_called()

    def test_throttled_no_consulta(self):
        import time
        sb = _WorkerSb(orders=[_CANDIDATE])
        stub = _worker_stub(sb, last_at=time.time())
        mock_tg = _run_reconciler(stub)
        self.assertEqual(sb.queries, [])
        mock_tg.assert_not_called()

    def test_orden_sin_guia_alerta_y_marca_una_vez(self):
        sb = _WorkerSb(orders=[_CANDIDATE], shipments=[])
        stub = _worker_stub(sb)
        mock_tg = _run_reconciler(stub)
        mock_tg.assert_awaited_once()
        kwargs = mock_tg.await_args.kwargs
        self.assertEqual(kwargs["tenant_id"], "tenant-1")
        self.assertIn("AAAAAAA1", kwargs["reason"])
        self.assertEqual(kwargs["severity"], "critical")
        marks = [u for u in sb.updates
                 if u[0] == "orders" and "paid_no_guide_alerted_at" in u[1]]
        self.assertEqual(len(marks), 1, "una sola marca por orden (no spam)")
        self.assertEqual(stub._metrics["paid_no_guide_alerts_sent"], 1)

    def test_orden_con_guia_labeled_no_alerta(self):
        sb = _WorkerSb(
            orders=[_CANDIDATE],
            shipments=[{"id": "sh1", "status": "labeled", "tracking_number": "T1"}],
        )
        stub = _worker_stub(sb)
        mock_tg = _run_reconciler(stub)
        mock_tg.assert_not_called()
        self.assertEqual(sb.updates, [])

    def test_shipment_pending_generation_si_alerta(self):
        """Shipment existe pero sin guía (pending_generation tras rechazo) → alerta."""
        sb = _WorkerSb(
            orders=[_CANDIDATE],
            shipments=[{"id": "sh1", "status": "pending_generation",
                        "tracking_number": None}],
        )
        stub = _worker_stub(sb)
        mock_tg = _run_reconciler(stub)
        mock_tg.assert_awaited_once()

    def test_telegram_falla_no_marca_y_reintenta_proximo_ciclo(self):
        sb = _WorkerSb(orders=[_CANDIDATE], shipments=[])
        stub = _worker_stub(sb)
        mock_tg = _run_reconciler(stub, telegram_ok=False)
        mock_tg.assert_awaited_once()
        self.assertEqual(sb.updates, [], "sin marca → reintento próximo ciclo")
        self.assertEqual(stub._metrics["paid_no_guide_errors"], 1)

    def test_columna_ausente_degrada_sin_romper_el_loop(self):
        """Migración 20260821120200 pendiente → skip con warning, nunca crash."""
        sb = _WorkerSbRaises(orders=[_CANDIDATE])
        stub = _worker_stub(sb)
        mock_tg = _run_reconciler(stub)  # no debe lanzar
        mock_tg.assert_not_called()


# ─── Alerta inmediata del webhook (api) ──────────────────────────────────────

class _ApiChain:
    def __init__(self, ctrl, table):
        self.ctrl, self.table = ctrl, table

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.ctrl.responses.get(self.table))


class _ApiSb:
    def __init__(self, responses):
        self.responses = responses

    def table(self, name):
        return _ApiChain(self, name)


def _load_webhook_module():
    """Import fresco (patrón tests/test_wompi_retry_payment.py)."""
    import importlib
    import routers.wompi_webhook as wh
    importlib.reload(wh)
    return wh


class WebhookGuideFailureAlertTests(unittest.TestCase):
    def test_provider_no_aveonline_no_alerta(self):
        wh = _load_webhook_module()
        sb = _ApiSb({
            "tenant_shipping_provider_config": {"active_provider": "envia"},
        })
        with patch("lib.operator_alerts.notify_operator_telegram") as mock_tg:
            sent = wh._alert_paid_without_guide_operator(
                sb, order_id="order-12345678", tenant_id="tenant-1", detail="boom",
            )
        self.assertFalse(sent)
        mock_tg.assert_not_called()

    def test_aveonline_alerta_con_contexto_del_pedido(self):
        wh = _load_webhook_module()
        sb = _ApiSb({
            "tenant_shipping_provider_config": {"active_provider": "aveonline"},
            "orders": {"total_amount": 2100.0},
        })
        with patch("lib.operator_alerts.notify_operator_telegram",
                   return_value=True) as mock_tg:
            sent = wh._alert_paid_without_guide_operator(
                sb, order_id="order-12345678-abcd", tenant_id="tenant-1",
                detail="timeout Aveonline",
            )
        self.assertTrue(sent)
        mock_tg.assert_called_once()
        text = mock_tg.call_args.kwargs["text"]
        self.assertIn("#ORDER-12", text)
        self.assertIn("$2.100", text)
        self.assertIn("timeout Aveonline", text)

    def test_lookup_falla_degrada_sin_lanzar(self):
        wh = _load_webhook_module()

        class _BrokenSb:
            def table(self, name):
                raise Exception("db down")

        sent = wh._alert_paid_without_guide_operator(
            _BrokenSb(), order_id="order-1", tenant_id="tenant-1",
        )
        self.assertFalse(sent)


# ─── Helper operator_alerts (api) ────────────────────────────────────────────

class OperatorAlertsTests(unittest.TestCase):
    def test_sin_settings_no_envia(self):
        from lib import operator_alerts
        sb = _ApiSb({"notification_settings": []})
        self.assertFalse(operator_alerts.notify_operator_telegram(
            sb, tenant_id="tenant-1", text="hola",
        ))

    def test_settings_sin_chat_id_no_envia(self):
        from lib import operator_alerts
        sb = _ApiSb({
            "notification_settings": [{"config": {"bot_token": "x"}}],
        })
        self.assertFalse(operator_alerts.notify_operator_telegram(
            sb, tenant_id="tenant-1", text="hola",
        ))

    def test_envio_ok_post_a_telegram(self):
        from lib import operator_alerts
        sb = _ApiSb({
            "notification_settings": [{
                "config": {"chat_id": 123, "bot_token": "vault:x"},
            }],
        })
        resp = MagicMock()
        resp.status_code = 200
        client = MagicMock()
        client.post.return_value = resp
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=client)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch("vault_helper.resolve_secret", return_value="tok-1"), \
             patch("httpx.Client", MagicMock(return_value=cm)) as mock_client_cls:
            ok = operator_alerts.notify_operator_telegram(
                sb, tenant_id="tenant-1", text="🚨 alerta",
            )
        self.assertTrue(ok)
        mock_client_cls.assert_called_once()
        post_kwargs = client.post.call_args.kwargs
        self.assertEqual(post_kwargs["json"]["chat_id"], 123)
        self.assertIn("bottok-1", client.post.call_args.args[0])

    def test_http_error_retorna_false(self):
        from lib import operator_alerts
        sb = _ApiSb({
            "notification_settings": [{
                "config": {"chat_id": 123, "bot_token": "vault:x"},
            }],
        })
        resp = MagicMock()
        resp.status_code = 500
        client = MagicMock()
        client.post.return_value = resp
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=client)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch("vault_helper.resolve_secret", return_value="tok-1"), \
             patch("httpx.Client", MagicMock(return_value=cm)):
            ok = operator_alerts.notify_operator_telegram(
                sb, tenant_id="tenant-1", text="alerta",
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

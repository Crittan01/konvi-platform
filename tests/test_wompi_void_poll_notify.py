"""BLOQUE H P0-1 (auditoría 2026-07-12 + review Fable) — cron backup Wompi VOIDED.

Bug: el cron `_poll_wompi_pending_voids_if_due` importaba
`wompi_webhook._notify_client_refund_completed` con un lazy import que NUNCA
resuelve en el proceso del orchestrator → notif silenciosa siempre fallida →
cliente jamás informado + wompi_status nunca sincronizado.

Fix + endurecimiento por revisión adversarial (Fable):
  · Réplica local `refund_notifications.notify_client_refund_completed` (bool:
    entrega gobierna; email 2xx-only; Idempotency-Key).
  · phone-empty NO inserta fantasma → False (#4).
  · RPC de cola falla → rollback del row huérfano (#3).
  · idempotencia cross-path por refund_status (#5/#13/#22).
  · tenant_id scoped por el caller (#10/#11).
  · monto correcto en el mensaje (#18).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

import refund_notifications  # noqa: E402
from refund_notifications import (  # noqa: E402
    _enqueue_whatsapp_outbound,
    notify_client_refund_completed,
)

TENANT = "11111111-1111-1111-1111-111111111111"
ORDER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CONV = "22222222-2222-2222-2222-222222222222"
CANCEL = "33333333-3333-3333-3333-333333333333"


class _FakeQuery:
    """Query-builder mock que registra tabla, operación, payload y filtros .eq."""

    def __init__(self, table, result, rec):
        self._table = table
        self._result = result
        self._rec = rec
        self._op = "select"
        self._payload = None
        self._filters = {}

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, k=None, v=None):
        if k is not None:
            self._filters[k] = v
        return self

    def or_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        # Registrar la operación (writes + filtros) para asserts.
        if self._op in ("insert", "update", "delete"):
            self._rec.append({
                "table": self._table, "op": self._op,
                "payload": self._payload, "filters": dict(self._filters),
            })
        # Resolver el resultado (callable para poder lanzar excepción).
        result = self._result
        if callable(result):
            result = result(self)
        return MagicMock(data=result)


class _FakeSupabase:
    """Supabase mock configurable por tabla. `results[table]` puede ser un
    valor o un callable(query)->valor (para lanzar excepciones o variar)."""

    def __init__(self, results, rec, rpc_raises=False):
        self._results = results
        self._rec = rec
        self._rpc_raises = rpc_raises
        self.rpc_calls = []

    def table(self, name):
        return _FakeQuery(name, self._results.get(name), self._rec)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        m = MagicMock()
        if self._rpc_raises:
            m.execute.side_effect = RuntimeError("pgmq down")
        return m


def _base_results(*, conv=True, email="ana@x.com", phone="573001112233",
                  refund_status="pending", msg_insert=None):
    return {
        "orders": {
            "tenant_id": TENANT,
            "conversation_id": CONV if conv else None,
            "cancellation_id": CANCEL,
            "total_amount": 56000,
            "contacts": {"name": "Ana", "email": email},
        },
        "order_cancellations": {"refund_status": refund_status},
        "conversations": [{"customer_phone": phone}] if conv else [],
        "tenants": {"name": "KAIU"},
        "messages": [{"id": "msg-1"}] if msg_insert is None else msg_insert,
    }


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class NotifyRefundCompletedTest(unittest.TestCase):
    def _call(self, results, *, rpc_raises=False, email_ret=True, amount=5600000):
        rec = []
        sb = _FakeSupabase(results, rec, rpc_raises=rpc_raises)
        with patch.object(
            refund_notifications, "_send_email_via_resend",
            new=AsyncMock(return_value=email_ret),
        ) as sender:
            ok = _run(notify_client_refund_completed(
                sb, order_id=ORDER, tenant_id=TENANT, amount_in_cents=amount,
            ))
        return ok, rec, sb, sender

    def test_whatsapp_delivered_syncs_and_audits(self):
        ok, rec, sb, _ = self._call(_base_results())
        self.assertTrue(ok)
        tables = [r["table"] for r in rec]
        self.assertIn("messages", tables)          # WA encolado
        self.assertIn("order_cancellations", tables)  # audit completed
        audit = next(r for r in rec if r["table"] == "order_cancellations" and r["op"] == "update")
        self.assertEqual(audit["payload"]["refund_status"], "completed")
        self.assertEqual(len(sb.rpc_calls), 1)      # cola

    def test_whatsapp_message_carries_correct_amount(self):
        # #18 (HIGH): una mutación que quite el /100 (100x) DEBE romper el test.
        _, rec, _, _ = self._call(_base_results(), amount=5600000)
        msg = next(r for r in rec if r["table"] == "messages" and r["op"] == "insert")
        self.assertIn("$56.000 COP", msg["payload"]["content"])
        self.assertNotIn("5.600.000", msg["payload"]["content"])

    def test_order_read_scoped_by_tenant(self):
        # #10/#11: la query de order va scoped por tenant_id (ADR-0025).
        rec = []
        # order como callable que registra filtros al ejecutar select.
        seen = {}

        def _order_result(q):
            seen.update(q._filters)
            return _base_results()["orders"]

        results = _base_results()
        results["orders"] = _order_result
        sb = _FakeSupabase(results, rec)
        with patch.object(refund_notifications, "_send_email_via_resend",
                          new=AsyncMock(return_value=True)):
            _run(notify_client_refund_completed(
                sb, order_id=ORDER, tenant_id=TENANT, amount_in_cents=5600000,
            ))
        self.assertEqual(seen.get("tenant_id"), TENANT)
        self.assertEqual(seen.get("id"), ORDER)

    def test_rpc_failure_rolls_back_orphan_row(self):
        # #3/#19: si el RPC de cola falla, el row 'pending' insertado se BORRA
        # (no fantasma) y se devuelve False (sigue elegible).
        ok, rec, sb, _ = self._call(_base_results(), rpc_raises=True, email_ret=False)
        self.assertFalse(ok)
        ops = [(r["table"], r["op"]) for r in rec]
        self.assertIn(("messages", "insert"), ops)
        self.assertIn(("messages", "delete"), ops)   # rollback
        self.assertNotIn(("order_cancellations", "update"), ops)  # sin audit falso

    def test_insert_no_data_returns_false(self):
        # #20: insert messages sin data → canal WA falla → si email también
        # falla, success=False (no sync).
        ok, rec, _, _ = self._call(
            _base_results(msg_insert=[]), email_ret=False,
        )
        self.assertFalse(ok)

    def test_phone_empty_no_orphan_no_false_success(self):
        # #4: sin teléfono NO se inserta fantasma; si email tampoco gobierna
        # (falla) → False.
        ok, rec, _, _ = self._call(
            _base_results(phone=""), email_ret=False,
        )
        self.assertFalse(ok)
        self.assertNotIn("messages", [r["table"] for r in rec])

    def test_idempotent_shortcircuit_when_already_completed(self):
        # #5/#13/#22: refund ya 'completed' → NO re-notificar (True, sin WA).
        ok, rec, sb, sender = self._call(
            _base_results(refund_status="completed"),
        )
        self.assertTrue(ok)
        self.assertNotIn("messages", [r["table"] for r in rec])
        sender.assert_not_awaited()
        self.assertEqual(len(sb.rpc_calls), 0)

    def test_email_governs_when_no_conversation(self):
        ok, _, _, _ = self._call(
            _base_results(conv=False), email_ret=False,
        )
        self.assertFalse(ok)  # email único canal y falló → no sync

    def test_email_delivered_governs_success_no_conversation(self):
        ok, rec, _, _ = self._call(
            _base_results(conv=False), email_ret=True,
        )
        self.assertTrue(ok)
        self.assertIn("order_cancellations", [r["table"] for r in rec])

    def test_whatsapp_ok_email_fail_still_success(self):
        ok, _, _, _ = self._call(_base_results(), email_ret=False)
        self.assertTrue(ok)  # WA entregó; email best-effort

    def test_no_channels_vacuous_success(self):
        ok, _, _, _ = self._call(
            _base_results(conv=False, email=""),
        )
        self.assertTrue(ok)

    def test_order_read_failure_returns_false(self):
        rec = []
        sb = _FakeSupabase({"orders": lambda q: (_ for _ in ()).throw(RuntimeError("db down"))}, rec)
        ok = _run(notify_client_refund_completed(
            sb, order_id=ORDER, tenant_id=TENANT, amount_in_cents=5600000,
        ))
        self.assertFalse(ok)

    def test_email_idempotency_key_passed(self):
        _, _, _, sender = self._call(_base_results(conv=False))
        kwargs = sender.call_args.kwargs
        self.assertEqual(kwargs["idempotency_key"], f"{TENANT}:{ORDER}:refund_completed")


class EnqueueHelperTest(unittest.TestCase):
    def test_no_phone_returns_false_no_insert(self):
        rec = []
        sb = _FakeSupabase({"conversations": []}, rec)
        ok = _enqueue_whatsapp_outbound(
            sb, conversation_id=CONV, tenant_id=TENANT, text="x", log_tag="T",
        )
        self.assertFalse(ok)
        self.assertNotIn("messages", [r["table"] for r in rec])

    def test_conversation_lookup_scoped_by_tenant(self):
        # #11: la verificación de conversación va scoped por tenant.
        seen = {}
        rec = []

        def _conv(q):
            seen.update(q._filters)
            return [{"customer_phone": "573001112233"}]

        sb = _FakeSupabase({"conversations": _conv, "messages": [{"id": "m1"}]}, rec)
        _enqueue_whatsapp_outbound(
            sb, conversation_id=CONV, tenant_id=TENANT, text="x", log_tag="T",
        )
        self.assertEqual(seen.get("tenant_id"), TENANT)
        self.assertEqual(seen.get("id"), CONV)


class WorkerVoidPollCycleTest(unittest.TestCase):
    """Ciclo del cron con mock VOIDED + candidatos negativos (#24)."""

    def _run_cycle(self, *, notify_ok=True, wompi_status="VOIDED",
                   candidate_overrides=None, updated_at="2026-07-12T03:00:00+00:00"):
        from worker import OrchestratorWorker

        payments_updates = []

        class _PaymentsQ:
            def __init__(self, op_result):
                self._op_result = op_result

            def __getattr__(self, name):
                def _chain(*args, **kwargs):
                    if name == "update":
                        payments_updates.append(args[0])
                    if name == "execute":
                        return MagicMock(data=self._op_result)
                    return self
                return _chain

        candidate = {
            "id": "pay-1", "tenant_id": TENANT, "order_id": ORDER,
            "wompi_txn_id": "txn-1", "amount_in_cents": 5600000,
            "wompi_status": "APPROVED", "updated_at": updated_at,
            "orders": {
                "status": "cancelled", "cancellation_id": CANCEL,
                "order_cancellations": [
                    {"refund_method": "wompi_void_auto", "refund_status": "pending"},
                ],
            },
        }
        if candidate_overrides:
            candidate = {**candidate, **candidate_overrides}
        sb = MagicMock()
        sb.table.side_effect = lambda name: _PaymentsQ(
            [candidate] if name == "payments" else [],
        )

        stub = MagicMock(spec=OrchestratorWorker)
        stub.supabase = sb
        stub._wompi_void_poll_enabled = True
        stub._last_wompi_void_poll_at = 0.0
        stub._metrics = {"wompi_void_notify_failed": 0}
        stub.last_heartbeat_ts = 0.0

        wompi_response = MagicMock(status_code=200)
        wompi_response.json.return_value = {"data": {"status": wompi_status}}
        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=False)
        async_client.get = AsyncMock(return_value=wompi_response)

        with patch("integrations.wompi_client.get_tenant_wompi_creds",
                   return_value=("pub_test_x", None, "sandbox")), \
             patch("integrations.wompi_client.wompi_base_url",
                   return_value="https://sandbox.wompi.co/v1"), \
             patch("httpx.AsyncClient", return_value=async_client), \
             patch("worker.notify_client_refund_completed",
                   new=AsyncMock(return_value=notify_ok)) as notify_mock:
            _run(OrchestratorWorker._poll_wompi_pending_voids_if_due(stub))
        return payments_updates, notify_mock, stub

    def test_voided_and_notified_syncs_local(self):
        updates, notify_mock, stub = self._run_cycle(notify_ok=True)
        notify_mock.assert_awaited_once()
        # El caller pasa tenant_id (scoping ADR-0025).
        self.assertEqual(notify_mock.call_args.kwargs["tenant_id"], TENANT)
        self.assertEqual(updates, [{"wompi_status": "VOIDED"}])
        self.assertEqual(stub._metrics["wompi_void_notify_failed"], 0)

    def test_voided_notify_fails_keeps_candidate(self):
        updates, notify_mock, stub = self._run_cycle(notify_ok=False)
        notify_mock.assert_awaited_once()
        self.assertEqual(updates, [])
        self.assertEqual(stub._metrics["wompi_void_notify_failed"], 1)

    def test_not_voided_no_notify(self):
        updates, notify_mock, _ = self._run_cycle(wompi_status="APPROVED")
        notify_mock.assert_not_awaited()
        self.assertEqual(updates, [])

    def test_order_not_cancelled_excluded(self):
        # #24: candidato con order NO cancelled → no elegible → no notify.
        updates, notify_mock, _ = self._run_cycle(
            candidate_overrides={"orders": {
                "status": "shipped", "cancellation_id": CANCEL,
                "order_cancellations": [{"refund_method": "wompi_void_auto"}],
            }},
        )
        notify_mock.assert_not_awaited()

    def test_wrong_refund_method_excluded(self):
        # #24: refund_method distinto → no elegible.
        updates, notify_mock, _ = self._run_cycle(
            candidate_overrides={"orders": {
                "status": "cancelled", "cancellation_id": CANCEL,
                "order_cancellations": [{"refund_method": "manual_transfer"}],
            }},
        )
        notify_mock.assert_not_awaited()

    def test_stale_candidate_logs_alert(self):
        # #2: candidato viejo (updated_at antiguo) → log de STUCK antes del age-out.
        with self.assertLogs("orchestrator.worker", level="ERROR") as cm:
            self._run_cycle(notify_ok=True, updated_at="2020-01-01T00:00:00+00:00")
        self.assertTrue(any("STUCK refund void" in m for m in cm.output))


class ImportRegressionTest(unittest.TestCase):
    def test_worker_no_longer_lazy_imports_api_router(self):
        import inspect
        import worker
        src = inspect.getsource(worker.OrchestratorWorker._poll_wompi_pending_voids_if_due)
        self.assertNotIn("from wompi_webhook import", src)
        self.assertIn("notify_client_refund_completed", src)

    def test_helper_is_top_level_import_in_worker(self):
        # Regresión del bug raíz: el símbolo se resuelve al importar worker
        # (falla al boot si falta, no en runtime silencioso).
        import worker
        self.assertTrue(hasattr(worker, "notify_client_refund_completed"))


if __name__ == "__main__":
    unittest.main()

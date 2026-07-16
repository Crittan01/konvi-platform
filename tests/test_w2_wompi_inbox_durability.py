"""W2 (auditoría 2026-07-13) — durabilidad del webhook Wompi (inbox transaccional).

Gap: la API ACK-ea 200 y procesa en background → un crash pierde el evento de pago
(Wompi no reintenta un 200 ni ofrece pull por reference). Fix: persistir el payload
crudo en `wompi_webhook_inbox` ANTES del ACK; el worker reconcilia lo no procesado
re-POSTeando al webhook (reusa el flujo verificado; idempotencia por wompi_events_seen).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://x.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

import routers.wompi_webhook as wh  # noqa: E402


def _captured_table(store):
    """Devuelve un supabase-mock que registra insert/update por tabla en `store`."""
    sb = MagicMock()

    def _table(name):
        t = MagicMock()

        def _insert(row):
            store.setdefault(name, {"insert": [], "update": []})["insert"].append(row)
            ex = MagicMock()
            ex.execute.return_value = MagicMock(data=[row])
            return ex

        def _update(row):
            store.setdefault(name, {"insert": [], "update": []})["update"].append(row)
            chain = MagicMock()
            chain.eq.return_value = chain
            chain.execute.return_value = MagicMock(data=[])
            return chain

        t.insert.side_effect = _insert
        t.update.side_effect = _update
        return t

    sb.table.side_effect = _table
    return sb


class PersistInboxTests(unittest.TestCase):
    def test_inserta_payload_crudo(self):
        store = {}
        sb = _captured_table(store)
        payload = {"event": "transaction.updated", "signature": {"checksum": "abc"}}
        wh._persist_inbox(sb, "abc", payload)
        ins = store["wompi_webhook_inbox"]["insert"]
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0]["checksum"], "abc")
        self.assertEqual(ins[0]["raw_payload"], payload)

    def test_sin_checksum_no_inserta(self):
        store = {}
        sb = _captured_table(store)
        wh._persist_inbox(sb, "", {"event": "x"})
        self.assertNotIn("wompi_webhook_inbox", store)

    def test_duplicado_no_relanza(self):
        sb = MagicMock()
        t = MagicMock()
        t.insert.return_value.execute.side_effect = Exception("duplicate key value 23505")
        sb.table.return_value = t
        # no debe propagar (ya capturado por un ACK/re-drive previo)
        wh._persist_inbox(sb, "dup", {"a": 1})

    def test_otro_error_si_propaga(self):
        sb = MagicMock()
        t = MagicMock()
        t.insert.return_value.execute.side_effect = Exception("connection refused")
        sb.table.return_value = t
        with self.assertRaises(Exception):
            wh._persist_inbox(sb, "x", {"a": 1})


class DurableWrapperTests(unittest.TestCase):
    def test_marca_processed_en_retorno_normal(self):
        store = {}
        sb = _captured_table(store)
        payload = {"signature": {"checksum": "ok1"}}
        with patch.object(wh, "_get_service_client", return_value=sb), \
             patch.object(wh, "_process_wompi_event", return_value=None) as proc:
            wh._process_wompi_event_durable(payload)
        proc.assert_called_once_with(payload)
        upd = store["wompi_webhook_inbox"]["update"]
        self.assertTrue(any("processed_at" in u for u in upd), "no marcó processed_at")

    def test_no_marca_processed_si_lanza(self):
        store = {}
        sb = _captured_table(store)
        payload = {"signature": {"checksum": "boom"}}
        with patch.object(wh, "_get_service_client", return_value=sb), \
             patch.object(wh, "_process_wompi_event", side_effect=RuntimeError("crash")):
            wh._process_wompi_event_durable(payload)  # no debe propagar
        updates = store.get("wompi_webhook_inbox", {}).get("update", [])
        # registró last_error pero NUNCA processed_at → queda para reconciliación
        self.assertFalse(any("processed_at" in u for u in updates), "no debía marcar processed")
        self.assertTrue(any("last_error" in u for u in updates), "debía registrar last_error")


class WorkerReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def test_redrive_repostea_filas_no_procesadas(self):
        sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")
        import worker as wk
        from unittest.mock import AsyncMock

        w = wk.OrchestratorWorker.__new__(wk.OrchestratorWorker)  # sin __init__ pesado
        w._wompi_inbox_reconcile_enabled = True
        w._last_wompi_inbox_reconcile_at = 0.0
        claimed = [
            {"checksum": "c1", "raw_payload": {"signature": {"checksum": "c1"}}, "attempts": 1},
            {"checksum": "c2", "raw_payload": {"signature": {"checksum": "c2"}}, "attempts": 2},
        ]
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value = MagicMock(data=claimed)
        w.supabase = sb

        posted = []
        resp = MagicMock(status_code=200)
        client = MagicMock()
        client.post = AsyncMock(side_effect=lambda url, json: posted.append((url, json)) or resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=cm):
            await w._reconcile_wompi_inbox_if_due()

        self.assertEqual(len(posted), 2)
        self.assertTrue(posted[0][0].endswith("/api/v1/webhooks/wompi"))
        self.assertEqual(posted[0][1], claimed[0]["raw_payload"])
        # llamó al claim RPC con los límites
        sb.rpc.assert_called_once()
        self.assertEqual(sb.rpc.call_args[0][0], "claim_wompi_inbox_batch")

    async def test_deshabilitado_no_hace_nada(self):
        sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")
        import worker as wk
        w = wk.OrchestratorWorker.__new__(wk.OrchestratorWorker)
        w._wompi_inbox_reconcile_enabled = False
        w._last_wompi_inbox_reconcile_at = 0.0
        w.supabase = MagicMock()
        await w._reconcile_wompi_inbox_if_due()
        w.supabase.rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()

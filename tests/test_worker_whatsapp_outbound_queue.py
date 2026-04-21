import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("MAX_PROCESSING_ATTEMPTS", "3")
os.environ.setdefault("WHATSAPP_OUTBOUND_MAX_ATTEMPTS", "3")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

import worker


class _MessagesUpdateQuery:
    def __init__(self, parent):
        self.parent = parent
        self._payload = None

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        self.parent.updated_payloads.append(self._payload or {})
        return types.SimpleNamespace(data=[{"id": "m-out-1"}])


class _FakeSupabase:
    def __init__(self, event_read_ct=1):
        self.event_read_ct = event_read_ct
        self.rpc_calls = []
        self.updated_payloads = []

    def table(self, name):
        if name != "messages":
            raise AssertionError(f"Tabla inesperada: {name}")
        return _MessagesUpdateQuery(self)

    def rpc(self, fn, payload):
        self.rpc_calls.append((fn, payload))
        if fn == "dequeue_whatsapp_outbound_messages":
            return types.SimpleNamespace(
                execute=lambda: types.SimpleNamespace(
                    data=[
                        {
                            "msg_id": 9001,
                            "read_ct": self.event_read_ct,
                            "message": {
                                "tenant_id": "t-1",
                                "conversation_id": "c-1",
                                "message_id": "m-out-1",
                                "customer_phone": "573001112233",
                                "text": "hola",
                            },
                        }
                    ]
                )
            )
        if fn == "ack_whatsapp_outbound_message":
            return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=True))
        if fn == "dequeue_human_takeover_notifications":
            return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=[]))
        raise AssertionError(f"RPC inesperado: {fn}")


class WorkerWhatsAppOutboundQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_outbound_processed_on_success(self):
        fake_supabase = _FakeSupabase(event_read_ct=1)
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=AsyncMock(return_value="wamid.123")),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))
        self.assertTrue(any(p.get("processing_status") == "processed" for p in fake_supabase.updated_payloads))
        self.assertTrue(any(p.get("meta_message_id") == "wamid.123" for p in fake_supabase.updated_payloads))

    async def test_marks_failed_and_ack_on_max_attempts(self):
        fake_supabase = _FakeSupabase(event_read_ct=max(1, worker.WHATSAPP_OUTBOUND_MAX_ATTEMPTS))
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=AsyncMock(return_value=None)),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))
        self.assertTrue(any(p.get("processing_status") == "failed" for p in fake_supabase.updated_payloads))
        self.assertTrue(
            any(p.get("last_error") == "outbound_send_failed_max_attempts" for p in fake_supabase.updated_payloads)
        )


if __name__ == "__main__":
    unittest.main()

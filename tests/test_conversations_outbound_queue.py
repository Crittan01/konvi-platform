import os
import sys
import types
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from routers import conversations


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def single(self, *_args, **_kwargs):
        return self

    def insert(self, *_args, **_kwargs):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _SupabaseStub:
    def __init__(self):
        self.rpc_calls = []

    def table(self, name):
        if name == "conversations":
            return _Query({"id": "c-1", "customer_phone": "573001112233", "status": "human_takeover"})
        if name == "messages":
            return _Query(
                [
                    {
                        "id": "m-out-1",
                        "tenant_id": "t-1",
                        "conversation_id": "c-1",
                        "direction": "outbound",
                        "content": "hola",
                        "processing_status": "pending",
                    }
                ]
            )
        raise AssertionError(f"Tabla inesperada: {name}")

    def rpc(self, fn, payload):
        self.rpc_calls.append((fn, payload))
        return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=101))


class ConversationsOutboundQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_agent_message_enqueues_outbound(self):
        supabase = _SupabaseStub()
        request = types.SimpleNamespace(headers={})

        result = await conversations.send_agent_message(
            conversation_id="c-1",
            body=conversations.AgentMessageRequest(text="hola"),
            request=request,
            tenant_id="t-1",
            supabase=supabase,
        )

        self.assertTrue(result["queued"])
        self.assertEqual(result["queue_message_id"], 101)
        self.assertEqual(result["message"]["processing_status"], "pending")
        self.assertEqual(len(supabase.rpc_calls), 1)
        self.assertEqual(supabase.rpc_calls[0][0], "enqueue_whatsapp_outbound_message")


if __name__ == "__main__":
    unittest.main()

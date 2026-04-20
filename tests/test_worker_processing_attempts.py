import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("MAX_PROCESSING_ATTEMPTS", "3")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

import worker


class _MessagesQuery:
    def __init__(self, parent):
        self.parent = parent
        self._mode = "select"
        self._update_payload = None

    def select(self, *_args, **_kwargs):
        self._mode = "select"
        return self

    def update(self, payload):
        self._mode = "update"
        self._update_payload = payload
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self._mode == "select":
            return types.SimpleNamespace(
                data=[
                    {
                        "id": "m-1",
                        "tenant_id": "t-1",
                        "conversation_id": "c-1",
                        "content": "hola",
                        "content_type": "text",
                        "processing_attempts": 3,
                    }
                ]
            )

        self.parent.last_update_payload = self._update_payload
        return types.SimpleNamespace(data=[{"id": "m-1"}])


class _FakeSupabase:
    def __init__(self):
        self.last_update_payload = None

    def table(self, name):
        if name != "messages":
            raise AssertionError(f"Tabla inesperada en test: {name}")
        return _MessagesQuery(self)


class WorkerProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_failed_after_max_attempts(self):
        fake_supabase = _FakeSupabase()

        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "build_and_run_orchestration", new=AsyncMock()) as build,
        ):
            w = worker.OrchestratorWorker()
            await w._poll_cycle()

        build.assert_not_awaited()
        self.assertIsNotNone(fake_supabase.last_update_payload)
        self.assertEqual(fake_supabase.last_update_payload["processing_status"], "failed")
        self.assertEqual(fake_supabase.last_update_payload["last_error"], "max_attempts_exceeded")


if __name__ == "__main__":
    unittest.main()

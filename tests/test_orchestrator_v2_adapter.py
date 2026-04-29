"""Tests del v2 adapter — feature flag y fallback al monolito.

Cubre:
- is_v2_enabled lee env var dinámicamente.
- run_orchestration con flag off → llama al monolito.
- run_orchestration con flag on + coordinator falla → fallback a monolito.

NO invoca LLM real ni DB real — todo mockeado.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

import orchestrator_v2_adapter as adapter  # noqa: E402


class FlagTests(unittest.TestCase):
    def test_default_is_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USE_NEW_ORCHESTRATOR", None)
            self.assertFalse(adapter.is_v2_enabled())

    def test_truthy_values_enable(self):
        for v in ["1", "true", "TRUE", "yes", "on"]:
            with patch.dict(os.environ, {"USE_NEW_ORCHESTRATOR": v}):
                self.assertTrue(adapter.is_v2_enabled(), f"valor {v!r} debería habilitar")

    def test_falsy_values_disable(self):
        for v in ["0", "false", "no", "off", ""]:
            with patch.dict(os.environ, {"USE_NEW_ORCHESTRATOR": v}):
                self.assertFalse(adapter.is_v2_enabled())


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_flag_off_calls_monolith(self):
        os.environ.pop("USE_NEW_ORCHESTRATOR", None)
        with patch.object(
            adapter,
            "_run_v2",
            new_callable=AsyncMock,
        ) as run_v2_mock, patch(
            "orchestrator.build_and_run_orchestration",
            new_callable=AsyncMock,
        ) as monolith_mock:
            await adapter.run_orchestration(
                supabase=MagicMock(),
                message_id="m1",
                tenant_id="t1",
                conversation_id="c1",
                content="hola",
                content_type="text",
            )
            run_v2_mock.assert_not_awaited()
            monolith_mock.assert_awaited_once()

    async def test_flag_on_calls_v2(self):
        with patch.dict(os.environ, {"USE_NEW_ORCHESTRATOR": "true"}):
            with patch.object(
                adapter,
                "_run_v2",
                new_callable=AsyncMock,
            ) as run_v2_mock, patch(
                "orchestrator.build_and_run_orchestration",
                new_callable=AsyncMock,
            ) as monolith_mock:
                await adapter.run_orchestration(
                    supabase=MagicMock(),
                    message_id="m1",
                    tenant_id="t1",
                    conversation_id="c1",
                    content="hola",
                    content_type="text",
                )
                run_v2_mock.assert_awaited_once()
                monolith_mock.assert_not_awaited()

    async def test_flag_on_v2_failure_falls_back_to_monolith(self):
        with patch.dict(os.environ, {"USE_NEW_ORCHESTRATOR": "true"}):
            with patch.object(
                adapter,
                "_run_v2",
                new_callable=AsyncMock,
                side_effect=RuntimeError("v2 explotó"),
            ) as run_v2_mock, patch(
                "orchestrator.build_and_run_orchestration",
                new_callable=AsyncMock,
            ) as monolith_mock:
                await adapter.run_orchestration(
                    supabase=MagicMock(),
                    message_id="m1",
                    tenant_id="t1",
                    conversation_id="c1",
                    content="hola",
                    content_type="text",
                )
                run_v2_mock.assert_awaited_once()
                monolith_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

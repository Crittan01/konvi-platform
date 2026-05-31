"""
Tests: _get_tenant_ai_agent — default fallback y custom agent
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("API_URL", "http://localhost:8001")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _get_tenant_ai_agent

TENANT_ID = "tenant-abc"

DEFAULT_FIELDS = {"name", "role_description", "strict_guardrails"}


def _mock_supabase_agent(agent_row: dict | None) -> MagicMock:
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
        [agent_row] if agent_row else []
    )
    return sb


class TestGetTenantAiAgent(unittest.IsolatedAsyncioTestCase):

    async def test_returns_default_when_no_agent_configured(self):
        sb = _mock_supabase_agent(None)
        agent = await _get_tenant_ai_agent(sb, TENANT_ID)
        for field in DEFAULT_FIELDS:
            self.assertIn(field, agent, f"Campo '{field}' ausente en agente por defecto")
        self.assertTrue(agent["strict_guardrails"], "Guardrails debe estar activo por defecto")

    async def test_returns_custom_agent_when_configured(self):
        custom = {
            "tenant_id": TENANT_ID,
            "name": "Sofia",
            "role_description": "Soy Sofia, especialista en ventas.",
            "strict_guardrails": False,
        }
        sb = _mock_supabase_agent(custom)
        agent = await _get_tenant_ai_agent(sb, TENANT_ID)
        self.assertEqual(agent["name"], "Sofia")
        self.assertEqual(agent["role_description"], "Soy Sofia, especialista en ventas.")
        self.assertFalse(agent["strict_guardrails"])

    async def test_default_name_is_non_empty_string(self):
        sb = _mock_supabase_agent(None)
        agent = await _get_tenant_ai_agent(sb, TENANT_ID)
        self.assertIsInstance(agent["name"], str)
        self.assertTrue(len(agent["name"]) > 0)

    async def test_default_role_description_is_non_empty_string(self):
        sb = _mock_supabase_agent(None)
        agent = await _get_tenant_ai_agent(sb, TENANT_ID)
        self.assertIsInstance(agent["role_description"], str)
        self.assertTrue(len(agent["role_description"]) > 0)

    async def test_queries_correct_tenant(self):
        sb = _mock_supabase_agent(None)
        await _get_tenant_ai_agent(sb, TENANT_ID)
        sb.table.return_value.select.return_value.eq.assert_called_once_with("tenant_id", TENANT_ID)

    async def test_strict_guardrails_defaults_to_true(self):
        sb = _mock_supabase_agent(None)
        agent = await _get_tenant_ai_agent(sb, TENANT_ID)
        self.assertIs(agent["strict_guardrails"], True)


if __name__ == "__main__":
    unittest.main()

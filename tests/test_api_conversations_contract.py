import os
import sys
import types
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from fastapi import HTTPException
from routers import conversations


def _chain_with_data(data):
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.single.return_value = query
    query.update.return_value = query
    query.execute.return_value = types.SimpleNamespace(data=data)
    return query


class ConversationContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_uses_canonical_status_keys(self):
        supabase = MagicMock()
        query = _chain_with_data([
            {"status": "bot_active"},
            {"status": "human_takeover"},
            {"status": "closed"},
            {"status": "bot_active"},
        ])
        supabase.table.return_value = query

        stats = await conversations.get_inbox_stats(tenant_id="t-1", supabase=supabase)

        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["bot_active"], 2)
        self.assertEqual(stats["human_takeover"], 1)
        self.assertEqual(stats["closed"], 1)
        self.assertNotIn("active", stats)
        self.assertNotIn("resolved", stats)

    async def test_update_status_rejects_legacy_values(self):
        with self.assertRaises(HTTPException) as ctx:
            await conversations.update_conversation_status(
                conversation_id="c-1",
                body=conversations.ConversationStatusUpdate(status="resolved"),
                tenant_id="t-1",
                supabase=MagicMock(),
            )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_update_status_accepts_canonical_values(self):
        supabase = MagicMock()
        query = _chain_with_data([{"id": "c-1", "status": "closed"}])
        supabase.table.return_value = query

        result = await conversations.update_conversation_status(
            conversation_id="c-1",
            body=conversations.ConversationStatusUpdate(status="closed"),
            tenant_id="t-1",
            supabase=supabase,
        )

        self.assertEqual(result, {"id": "c-1", "status": "closed"})


if __name__ == "__main__":
    unittest.main()

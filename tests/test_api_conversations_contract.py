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
    async def test_list_conversations_uses_last_interaction_sort(self):
        supabase = MagicMock()
        query = _chain_with_data(
            [
                {
                    "id": "c-1",
                    "customer_phone": "573001112233",
                    "status": "bot_active",
                    "created_at": "2026-04-22T10:00:00Z",
                    "last_interaction_at": "2026-04-22T11:00:00Z",
                    "messages": [{"content": "hola", "direction": "inbound", "created_at": "2026-04-22T11:00:00Z"}],
                }
            ]
        )
        supabase.table.return_value = query

        result = await conversations.list_conversations(
            tenant_id="t-1",
            supabase=supabase,
            status=None,
            limit=30,
            offset=0,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "c-1")
        query.order.assert_called_with("last_interaction_at", desc=True)

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

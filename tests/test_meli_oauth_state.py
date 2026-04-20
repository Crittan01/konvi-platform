import importlib
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ["MELI_CLIENT_ID"] = "client-id"
os.environ["MELI_CLIENT_SECRET"] = "client-secret"
os.environ["MELI_REDIRECT_URI"] = "https://example.com/callback"
os.environ["MELI_AUTH_URL"] = "https://auth.mercadolibre.com.co/authorization"
os.environ["MELI_OAUTH_STATE_SECRET"] = "test-super-secret"
os.environ["MELI_OAUTH_STATE_TTL_SECONDS"] = "600"

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from integrations import meli_client as _meli_client
from routers import integrations as integrations_router

meli_client = importlib.reload(_meli_client)


class _StateQuery:
    def __init__(self, store):
        self.store = store
        self._op = None
        self._payload = None
        self._filters = []
        self._maybe_single = False

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def select(self, *_args, **_kwargs):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, key, value):
        self._filters.append(("eq", key, value))
        return self

    def is_(self, key, value):
        self._filters.append(("is", key, value))
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def _match(self, row):
        for op, key, value in self._filters:
            current = row.get(key)
            if op == "eq" and current != value:
                return False
            if op == "is" and value == "null" and current is not None:
                return False
        return True

    def execute(self):
        if self._op == "insert":
            row = {
                "id": f"state-{len(self.store) + 1}",
                "tenant_id": self._payload["tenant_id"],
                "provider": self._payload["provider"],
                "nonce_hash": self._payload["nonce_hash"],
                "expires_at": self._payload["expires_at"],
                "consumed_at": None,
            }
            self.store.append(row)
            return types.SimpleNamespace(data=[row])

        rows = [row for row in self.store if self._match(row)]

        if self._op == "select":
            if self._maybe_single:
                return types.SimpleNamespace(data=rows[0] if rows else None)
            return types.SimpleNamespace(data=rows)

        if self._op == "update":
            updated = []
            for row in rows:
                row.update(self._payload)
                updated.append(dict(row))
            return types.SimpleNamespace(data=updated)

        return types.SimpleNamespace(data=[])


class InMemoryOAuthStateSupabase:
    def __init__(self):
        self.rows = []

    def table(self, name):
        if name != "integration_oauth_states":
            raise AssertionError(f"Tabla no soportada en test: {name}")
        return _StateQuery(self.rows)


class MeLiOAuthStateTests(unittest.TestCase):
    def test_valid_state_then_replay_is_rejected(self):
        supabase = InMemoryOAuthStateSupabase()

        state = meli_client.issue_oauth_state(supabase, tenant_id="tenant-1")
        tenant_id = meli_client.validate_and_consume_oauth_state(supabase, state)
        replay = meli_client.validate_and_consume_oauth_state(supabase, state)

        self.assertEqual(tenant_id, "tenant-1")
        self.assertIsNone(replay)

    def test_tampered_state_is_rejected(self):
        supabase = InMemoryOAuthStateSupabase()
        state = meli_client.issue_oauth_state(supabase, tenant_id="tenant-1")
        tampered = state[:-1] + ("A" if state[-1] != "A" else "B")

        self.assertIsNone(meli_client.validate_and_consume_oauth_state(supabase, tampered))

    def test_expired_state_is_rejected(self):
        supabase = InMemoryOAuthStateSupabase()
        state = meli_client.issue_oauth_state(supabase, tenant_id="tenant-1")
        supabase.rows[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

        self.assertIsNone(meli_client.validate_and_consume_oauth_state(supabase, state))


class MeLiOAuthCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_missing_state_is_rejected(self):
        response = await integrations_router.meli_oauth_callback(code="abc", state=None)
        self.assertEqual(response.status_code, 307)
        self.assertIn("error=missing_state", response.headers["location"])

    async def test_callback_invalid_state_does_not_persist_tokens(self):
        fake_sb = MagicMock()
        table_query = MagicMock()
        table_query.upsert.return_value = table_query
        table_query.execute.return_value = types.SimpleNamespace(data=[{}])
        fake_sb.table.return_value = table_query

        with (
            patch.object(integrations_router, "_get_service_client", return_value=fake_sb),
            patch.object(integrations_router.meli_client, "validate_and_consume_oauth_state", return_value=None),
        ):
            response = await integrations_router.meli_oauth_callback(
                code="abc",
                state="bad-state",
            )

        self.assertEqual(response.status_code, 307)
        self.assertIn("error=invalid_state", response.headers["location"])
        fake_sb.table.assert_not_called()

    async def test_callback_valid_state_persists_tokens(self):
        fake_sb = MagicMock()
        table_query = MagicMock()
        table_query.upsert.return_value = table_query
        table_query.execute.return_value = types.SimpleNamespace(data=[{"id": "ok"}])
        fake_sb.table.return_value = table_query

        with (
            patch.object(integrations_router, "_get_service_client", return_value=fake_sb),
            patch.object(integrations_router.meli_client, "validate_and_consume_oauth_state", return_value="tenant-1"),
            patch.object(
                integrations_router.meli_client,
                "exchange_code",
                new=AsyncMock(
                    return_value={
                        "access_token": "at",
                        "refresh_token": "rt",
                        "expires_in": 100,
                        "user_id": 123,
                        "scope": "read write",
                        "token_type": "Bearer",
                    }
                ),
            ),
        ):
            response = await integrations_router.meli_oauth_callback(
                code="good-code",
                state="good-state",
            )

        self.assertEqual(response.status_code, 307)
        self.assertIn("connected=mercadolibre", response.headers["location"])
        fake_sb.table.assert_called_with("tenant_integrations")
        table_query.upsert.assert_called_once()


if __name__ == "__main__":
    unittest.main()

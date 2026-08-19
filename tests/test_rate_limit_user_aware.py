"""Tests del rate limiter user-aware (rev. 69 C1).

Verifica que `build_rate_limit_dependency(include_user_id=True)` compone la
key incluyendo el user_id extraído del JWT, y que `_get_optional_user_id`
retorna 'anon' cuando JWT ausente o sin sub.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from dependencies.security import _get_optional_user_id  # noqa: E402


def _make_request(headers: dict | None = None):
    req = MagicMock()
    req.headers = headers or {}
    req.client = MagicMock()
    req.client.host = "1.2.3.4"
    return req


class GetOptionalUserIdTests(unittest.TestCase):
    def test_no_authorization_header_returns_anon(self):
        req = _make_request()
        self.assertEqual(_get_optional_user_id(req), "anon")

    def test_invalid_bearer_returns_anon(self):
        req = _make_request({"Authorization": "Bearer invalid.jwt.token"})
        self.assertEqual(_get_optional_user_id(req), "anon")

    def test_jwt_with_sub_returns_user_id(self):
        # Mock a payload with sub claim.
        req = _make_request({"Authorization": "Bearer xxx"})
        with patch("dependencies.auth._extract_jwt_payload", return_value={"sub": "user-123"}):
            self.assertEqual(_get_optional_user_id(req), "user-123")

    def test_jwt_without_sub_returns_anon(self):
        req = _make_request({"Authorization": "Bearer xxx"})
        with patch("dependencies.auth._extract_jwt_payload", return_value={"app_metadata": {}}):
            self.assertEqual(_get_optional_user_id(req), "anon")


class RateLimitKeyCompositionTests(unittest.TestCase):
    """Verifica que el rate limiter compone la key con user_id cuando include_user_id=True.

    Test indirecto: ejecutamos el helper que construye la key a través del
    distributed_hit RPC mock y confirmamos el formato.
    """

    def test_key_includes_user_id_when_enabled(self):
        from dependencies.security import build_rate_limit_dependency, RateLimitRule

        captured_keys = []

        def fake_rpc(name, params):
            captured_keys.append(params.get("p_key"))
            mock = MagicMock()
            mock.execute.return_value = MagicMock(data=[{"allowed": True, "remaining": 9, "reset_in": 60}])
            return mock

        sb = MagicMock()
        sb.rpc.side_effect = fake_rpc

        rule = RateLimitRule(bucket="test.bucket", limit=10, window_seconds=60)
        dep = build_rate_limit_dependency(rule, include_user_id=True)

        req = _make_request({"Authorization": "Bearer xxx"})
        resp = MagicMock()
        resp.headers = {}

        # Ejecutar la dependency simulando los Depends.
        import asyncio
        with patch("dependencies.auth._extract_jwt_payload", return_value={"sub": "user-abc"}):
            asyncio.run(dep(req, resp, tenant_id="tenant-1", supabase=sb))

        self.assertEqual(len(captured_keys), 1)
        # Key esperada: bucket:tenant_id:user_id:ip
        self.assertIn("test.bucket:tenant-1:user-abc:1.2.3.4", captured_keys[0])

    def test_key_excludes_user_id_when_disabled(self):
        from dependencies.security import build_rate_limit_dependency, RateLimitRule

        captured_keys = []

        def fake_rpc(name, params):
            captured_keys.append(params.get("p_key"))
            mock = MagicMock()
            mock.execute.return_value = MagicMock(data=[{"allowed": True, "remaining": 9, "reset_in": 60}])
            return mock

        sb = MagicMock()
        sb.rpc.side_effect = fake_rpc

        rule = RateLimitRule(bucket="test.bucket", limit=10, window_seconds=60)
        dep = build_rate_limit_dependency(rule, include_user_id=False)

        req = _make_request({"Authorization": "Bearer xxx"})
        resp = MagicMock()
        resp.headers = {}

        import asyncio
        with patch("dependencies.auth._extract_jwt_payload", return_value={"sub": "user-abc"}):
            asyncio.run(dep(req, resp, tenant_id="tenant-1", supabase=sb))

        # Key esperada SIN user_id: bucket:tenant_id:ip
        self.assertEqual(captured_keys[0], "test.bucket:tenant-1:1.2.3.4")


if __name__ == "__main__":
    unittest.main()

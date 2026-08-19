import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException
from dependencies import auth
from routers import settings


class RBACTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_defaults_to_operator(self):
        with patch.object(auth, "_extract_jwt_payload", return_value={"app_metadata": {}}):
            role = await auth.get_current_role(request=object())
        self.assertEqual(role, "operator")

    async def test_invalid_role_falls_back_to_operator(self):
        with patch.object(auth, "_extract_jwt_payload", return_value={"app_metadata": {"role": "legacy_role"}}):
            role = await auth.get_current_role(request=object())
        self.assertEqual(role, "operator")

    async def test_require_write_role_rejects_operator(self):
        with self.assertRaises(HTTPException) as ctx:
            await auth.require_write_role(role="operator")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_settings_runtime_roles_exclude_agent(self):
        self.assertEqual(settings.VALID_ROLES, {"owner", "manager", "operator"})


if __name__ == "__main__":
    unittest.main()

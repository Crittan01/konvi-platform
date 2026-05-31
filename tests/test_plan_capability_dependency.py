import os
import sys
import types
import unittest

from fastapi import HTTPException
from starlette.responses import Response

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("PLAN_ENFORCEMENT_ENABLED", "true")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from dependencies import plans


class _SupabaseStub:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def rpc(self, fn, args):
        self.calls.append((fn, args))
        return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=self.payload))


class PlanCapabilityDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_allows_when_capability_enabled(self):
        dep = plans.build_plan_capability_dependency("orders.create", units=1)
        supabase = _SupabaseStub(
            [
                {
                    "allowed": True,
                    "plan_code": "pro",
                    "enabled": True,
                    "limit_value": 3000,
                    "period": "month",
                    "used": 10,
                    "remaining": 2990,
                    "reset_at": "2099-01-01T00:00:00+00:00",
                    "reason": None,
                }
            ]
        )
        response = Response()

        result = await dep(response=response, tenant_id="tenant-1", supabase=supabase)

        self.assertTrue(result.allowed)
        self.assertEqual(result.plan_code, "pro")
        self.assertEqual(response.headers.get("X-Plan-Code"), "pro")
        self.assertEqual(supabase.calls[0][0], "consume_tenant_capability")

    async def test_denies_when_feature_disabled(self):
        dep = plans.build_plan_capability_dependency("integrations.mercadolibre", units=1)
        supabase = _SupabaseStub(
            [
                {
                    "allowed": False,
                    "plan_code": "basic",
                    "enabled": False,
                    "limit_value": None,
                    "period": "none",
                    "used": 0,
                    "remaining": 0,
                    "reset_at": None,
                    "reason": "feature_disabled",
                }
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            await dep(response=Response(), tenant_id="tenant-1", supabase=supabase)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_denies_when_quota_exceeded(self):
        dep = plans.build_plan_capability_dependency("orders.create", units=1)
        supabase = _SupabaseStub(
            [
                {
                    "allowed": False,
                    "plan_code": "basic",
                    "enabled": True,
                    "limit_value": 500,
                    "period": "month",
                    "used": 500,
                    "remaining": 0,
                    "reset_at": "2099-01-01T00:00:00+00:00",
                    "reason": "quota_exceeded",
                }
            ]
        )

        with self.assertRaises(HTTPException) as ctx:
            await dep(response=Response(), tenant_id="tenant-1", supabase=supabase)
        self.assertEqual(ctx.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()

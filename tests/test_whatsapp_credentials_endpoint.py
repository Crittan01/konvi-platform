"""F3 activación — captura self-service de credenciales WhatsApp (ADR-0023 Model B).

Verifica: app_secret + access_token → Vault; el resto + secret_ids → tenant_integrations.credentials
(shape que el connector lee); status=connected + integration_type=direct_provider; RBAC (403 no owner);
idempotencia (reusa secret_id existente → update, no create).
"""
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi import HTTPException  # noqa: E402

import routers.integrations as integ  # noqa: E402
from routers.integrations import upsert_whatsapp_credentials, WhatsAppCredentialsInput  # noqa: E402

TID = "tenant-abc"
_REQ = types.SimpleNamespace(headers={}, method="POST",
                             url=types.SimpleNamespace(path="/api/v1/integrations/whatsapp/credentials"))


class _Q:
    def __init__(self, name, ctrl):
        self.name, self.ctrl, self.op, self.rows = name, ctrl, "select", None

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def upsert(self, rows, *_a, **_k):
        self.op = "upsert"; self.rows = rows; return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self.op == "upsert":
            self.ctrl.upserts.append(self.rows)
        return types.SimpleNamespace(data=self.ctrl.existing if self.op == "select" else [{}])


class _Ctrl:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.upserts = []

    def table(self, name):
        return _Q(name, self)


def _payload():
    return WhatsAppCredentialsInput(
        app_id="123456789", app_secret="s3cr3t-app-secret", verify_token="my-verify-token",
        phone_number_id="990364080831295", waba_id="2159052118202272",
        access_token="EAAG-long-system-user-token-xyz123456",
    )


async def _run(ctrl, role="owner"):
    return upsert_whatsapp_credentials(
        payload=_payload(), request=_REQ, tenant_id=TID, supabase=ctrl, role=role)


class WhatsAppCredentialsTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_vault_secrets_and_upserts_shape(self):
        ctrl = _Ctrl(existing=[])  # sin credenciales previas → create_secret
        fake_vault = MagicMock()
        fake_vault.create_secret.side_effect = ["sid-appsecret", "sid-token"]
        with patch.object(integ, "VaultHelper", return_value=fake_vault):
            r = await _run(ctrl)
        self.assertEqual(r["status"], "connected")
        self.assertIn(TID, r["webhook_url"])
        self.assertTrue(r["webhook_url"].endswith(f"/api/v1/whatsapp/webhook/{TID}"))
        # el app_secret y access_token fueron al Vault (create, no update)
        self.assertEqual(fake_vault.create_secret.call_count, 2)
        # el upsert lleva el shape EXACTO que el connector lee
        creds = ctrl.upserts[0]["credentials"]
        self.assertEqual(creds["app_secret_secret_id"], "sid-appsecret")
        self.assertEqual(creds["access_token_secret_id"], "sid-token")
        self.assertEqual(creds["verify_token"], "my-verify-token")
        self.assertEqual(creds["phone_number_id"], "990364080831295")
        self.assertEqual(creds["waba_id"], "2159052118202272")
        self.assertEqual(ctrl.upserts[0]["status"], "connected")
        self.assertEqual(ctrl.upserts[0]["meta"]["integration_type"], "direct_provider")
        self.assertEqual(ctrl.upserts[0]["tenant_id"], TID)

    async def test_idempotent_reuses_existing_secret_ids(self):
        ctrl = _Ctrl(existing=[{"credentials": {
            "app_secret_secret_id": "old-appsecret", "access_token_secret_id": "old-token"}}])
        fake_vault = MagicMock()
        with patch.object(integ, "VaultHelper", return_value=fake_vault):
            await _run(ctrl)
        # reusó los secret_id existentes (update, NO create → sin secretos huérfanos)
        self.assertEqual(fake_vault.update_secret.call_count, 2)
        fake_vault.create_secret.assert_not_called()

    async def test_non_owner_rejected(self):
        ctrl = _Ctrl()
        with patch.object(integ, "VaultHelper", return_value=MagicMock()):
            with self.assertRaises(HTTPException) as cm:
                await _run(ctrl, role="agent")
        self.assertEqual(cm.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

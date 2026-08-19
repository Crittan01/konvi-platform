"""Regresión A11 audit (WH-01) — persist_whatsapp_message usa el tenant
HMAC-verificado del path, NO re-resuelve por el meta_waba_id del payload.

Antes: `persist_whatsapp_message` SIEMPRE re-resolvía el tenant por
`meta_waba_id` (campo del body, attacker-influenciable) ignorando el tenant
criptográficamente establecido por la firma HMAC (Model B ADR-0023) → riesgo de
persistir bajo el tenant equivocado si el waba del body divergiera.

Fix: el handler pasa `tenant_id_verified` (el tenant del path ya HMAC-verificado);
persist lo usa como autoridad. Re-resolución por waba solo como fallback.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/connector-whatsapp"))

from services import db_persistence  # noqa: E402

_DATA = {
    "meta_waba_id": "WABA_DE_OTRO_TENANT",   # waba del payload (NO debe usarse)
    "customer_phone": "573001112233",
    "content": "hola",
    "content_type": "text",
    "meta_message_id": "wamid.test1",
}


class WH01VerifiedTenantTests(unittest.TestCase):
    def test_verified_tenant_used_and_no_reresolution(self):
        with patch.object(db_persistence, "get_supabase", return_value=MagicMock()), \
             patch.object(db_persistence, "_resolve_tenant_by_waba") as mock_resolve, \
             patch.object(db_persistence, "_upsert_conversation", return_value="conv-1") as mock_conv:
            db_persistence.persist_whatsapp_message(dict(_DATA), tenant_id_verified="tenant-A-verified")

        # NO re-resuelve por el waba del payload:
        mock_resolve.assert_not_called()
        # Persiste bajo el tenant VERIFICADO (2º arg posicional de _upsert_conversation):
        self.assertEqual(mock_conv.call_args[0][1], "tenant-A-verified")

    def test_fallback_reresolves_when_no_verified_tenant(self):
        # Retrocompat: sin tenant verificado, cae a la resolución por waba.
        with patch.object(db_persistence, "get_supabase", return_value=MagicMock()), \
             patch.object(db_persistence, "_resolve_tenant_by_waba", return_value="tenant-B-resolved") as mock_resolve, \
             patch.object(db_persistence, "_upsert_conversation", return_value="conv-1") as mock_conv:
            db_persistence.persist_whatsapp_message(dict(_DATA))

        mock_resolve.assert_called_once()
        self.assertEqual(mock_conv.call_args[0][1], "tenant-B-resolved")


if __name__ == "__main__":
    unittest.main()

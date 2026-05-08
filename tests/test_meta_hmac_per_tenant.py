"""Tests A.2 (simplificado 2026-05-08) + A.4 — HMAC global + tenant
forensics + parser multi-field dispatcher.

Cubre `services/connector-whatsapp/dependencies/meta.py` y
`services/connector-whatsapp/services/parser.py:parse_webhook_events`.

Modelo arquitectónico (post-clarificación con founder):
  - HMAC verify usa META_APP_SECRET GLOBAL (de la Meta App de la plataforma).
  - Lookup phone_number_id → tenant_id es FORENSICS, no auth.
  - Per-tenant: phone_number_id, waba_id, access_token (no app_secret).

Ver `docs/research/meta-app-architecture-2026-05-08.md`.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = REPO_ROOT / "services" / "connector-whatsapp"


def _load_module(rel_path: str, module_name: str):
    full_path = CONNECTOR_PATH / rel_path
    spec = importlib.util.spec_from_file_location(module_name, str(full_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_parser = _load_module("services/parser.py", "_test_meta_parser")


# ─── parse_webhook_events ────────────────────────────────────────────────────

class ParserDispatcherTests(unittest.TestCase):
    """Sem 6 pre-HSM: dispatcher multi-field por change.field."""

    def _payload(self, field: str, value: dict, waba_id: str = "WABA_TEST_001") -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": waba_id,
                "changes": [{"field": field, "value": value}],
            }],
        }

    def test_object_no_whatsapp_returns_empty(self):
        payload = {"object": "instagram", "entry": []}
        self.assertEqual(_parser.parse_webhook_events(payload), [])

    def test_field_messages_inbound_NOT_included(self):
        """Inbound queda en parse_webhook_payloads — dispatcher no duplica."""
        payload = self._payload("messages", {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "990364"},
            "messages": [{"id": "wamid.xxx", "from": "57311555", "type": "text"}],
        })
        events = _parser.parse_webhook_events(payload)
        self.assertEqual(events, [])

    def test_field_messages_with_statuses_outbound(self):
        payload = self._payload("messages", {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "990364"},
            "statuses": [{
                "id": "wamid.outbound_001",
                "recipient_id": "57311555000",
                "status": "delivered",
                "timestamp": "1714000000",
                "conversation": {"id": "conv_xxx", "origin": {"type": "utility"}},
                "pricing": {"category": "utility", "billable": True, "pricing_model": "PMP"},
            }],
        })
        events = _parser.parse_webhook_events(payload)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["event_type"], _parser.EVENT_TYPE_OUTBOUND_STATUS)
        self.assertEqual(e["meta_message_id"], "wamid.outbound_001")
        self.assertEqual(e["status"], "delivered")
        self.assertEqual(e["pricing_category"], "utility")
        self.assertTrue(e["pricing_billable"])
        self.assertEqual(e["destination_phone_id"], "990364")
        self.assertEqual(e["meta_waba_id"], "WABA_TEST_001")

    def test_field_template_status_update_approved(self):
        payload = self._payload("message_template_status_update", {
            "message_template_id": "9876543210",
            "message_template_name": "payment_reminder_v1",
            "message_template_language": "es_CO",
            "event": "APPROVED",
            "reason": None,
        })
        events = _parser.parse_webhook_events(payload)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["event_type"], _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE)
        self.assertEqual(e["new_status"], "APPROVED")
        self.assertEqual(e["template_name"], "payment_reminder_v1")
        self.assertEqual(e["template_language"], "es_CO")

    def test_field_template_status_update_rejected_with_reason(self):
        payload = self._payload("message_template_status_update", {
            "message_template_id": "9876543210",
            "message_template_name": "marketing_v2",
            "message_template_language": "es_CO",
            "event": "REJECTED",
            "reason": "INCORRECT_CATEGORY",
        })
        events = _parser.parse_webhook_events(payload)
        e = events[0]
        self.assertEqual(e["new_status"], "REJECTED")
        self.assertEqual(e["reason"], "INCORRECT_CATEGORY")

    def test_field_template_quality_update(self):
        payload = self._payload("message_template_quality_update", {
            "message_template_id": "9876543210",
            "message_template_name": "payment_reminder_v1",
            "message_template_language": "es_CO",
            "previous_quality_score": "GREEN",
            "new_quality_score": "YELLOW",
        })
        events = _parser.parse_webhook_events(payload)
        e = events[0]
        self.assertEqual(e["event_type"], _parser.EVENT_TYPE_TEMPLATE_QUALITY_UPDATE)
        self.assertEqual(e["previous_quality"], "GREEN")
        self.assertEqual(e["new_quality"], "YELLOW")

    def test_field_phone_quality_update(self):
        payload = self._payload("phone_number_quality_update", {
            "display_phone_number": "+57 311 5678910",
            "current_limit": "TIER_1K",
            "event": "UPGRADED",
        })
        events = _parser.parse_webhook_events(payload)
        e = events[0]
        self.assertEqual(e["event_type"], _parser.EVENT_TYPE_PHONE_QUALITY_UPDATE)
        self.assertEqual(e["current_limit"], "TIER_1K")
        self.assertEqual(e["event"], "UPGRADED")

    def test_field_account_alerts(self):
        payload = self._payload("account_alerts", {
            "alert_type": "POLICY_VIOLATION",
            "alert_severity": "WARNING",
        })
        events = _parser.parse_webhook_events(payload)
        e = events[0]
        self.assertEqual(e["event_type"], _parser.EVENT_TYPE_ACCOUNT_ALERT)
        self.assertEqual(e["field"], "account_alerts")
        self.assertIn("alert_type", e["raw_value"])

    def test_field_account_review_update_clasifica_como_alert(self):
        payload = self._payload("account_review_update", {"decision": "REJECTED"})
        events = _parser.parse_webhook_events(payload)
        self.assertEqual(events[0]["event_type"], _parser.EVENT_TYPE_ACCOUNT_ALERT)
        self.assertEqual(events[0]["field"], "account_review_update")

    def test_field_unknown_ignorado_silenciosamente(self):
        payload = self._payload("foo_bar_unknown_field", {"x": 1})
        events = _parser.parse_webhook_events(payload)
        self.assertEqual(events, [])

    def test_multi_change_un_post_emite_multiples_eventos(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WABA_X",
                "changes": [
                    {"field": "message_template_status_update", "value": {
                        "message_template_id": "1", "message_template_name": "t1",
                        "message_template_language": "es_CO", "event": "APPROVED",
                    }},
                    {"field": "phone_number_quality_update", "value": {
                        "display_phone_number": "+57", "current_limit": "TIER_250",
                        "event": "FLAGGED",
                    }},
                ],
            }],
        }
        events = _parser.parse_webhook_events(payload)
        self.assertEqual(len(events), 2)
        types = {e["event_type"] for e in events}
        self.assertEqual(types, {
            _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            _parser.EVENT_TYPE_PHONE_QUALITY_UPDATE,
        })

    def test_payload_malformado_returns_empty_no_raise(self):
        events = _parser.parse_webhook_events({"object": "whatsapp_business_account", "entry": "not_a_list"})
        self.assertEqual(events, [])


# ─── HMAC global + tenant forensics (rev. 2026-05-08) ────────────────────────


class _FakeSupabaseQuery:
    def __init__(self, response: list[dict]):
        self._response = response

    def select(self, *args, **kwargs):
        return self

    def eq(self, col, val):
        return self

    def execute(self):
        return SimpleNamespace(data=self._response)


class _FakeSupabaseClient:
    def __init__(self, integrations: list[dict]):
        self._integrations = integrations

    def table(self, name: str):
        if name == "tenant_integrations":
            return _FakeSupabaseQuery(self._integrations)
        return _FakeSupabaseQuery([])


def _load_meta_dep_with_fake_supabase(fake_sb, env_app_secret: str = "test_global_secret"):
    """Carga dependencies/meta.py con import de get_supabase mockeado +
    META_APP_SECRET env-var inyectado."""
    services_pkg = sys.modules.get("services")
    if services_pkg is None:
        services_pkg = type(sys)("services")
        services_pkg.__path__ = []  # type: ignore
        sys.modules["services"] = services_pkg

    db_persistence_stub = type(sys)("services.db_persistence")
    db_persistence_stub.get_supabase = lambda: fake_sb  # type: ignore
    sys.modules["services.db_persistence"] = db_persistence_stub

    # Inyectar env var ANTES del import (el módulo lo lee a nivel-modulo).
    import os
    os.environ["META_APP_SECRET"] = env_app_secret

    if "_test_meta_dep" in sys.modules:
        del sys.modules["_test_meta_dep"]
    spec = importlib.util.spec_from_file_location(
        "_test_meta_dep",
        str(CONNECTOR_PATH / "dependencies" / "meta.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_meta_dep"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod._cache_invalidate()
    return mod


class HmacGlobalTests(unittest.TestCase):
    """Sem 6 (simplificado 2026-05-08) — HMAC verify usa META_APP_SECRET global.

    El secret NO es per-tenant. Es de la Meta App de la plataforma (única).
    Tests verifican el comportamiento del helper sin per-tenant dispatch.
    """

    def test_extract_phone_number_id_payload_canonico(self):
        body = json.dumps({
            "entry": [{"changes": [{"value": {
                "metadata": {"phone_number_id": "990364001"}
            }}]}]
        }).encode("utf-8")
        mod = _load_meta_dep_with_fake_supabase(_FakeSupabaseClient([]))
        self.assertEqual(mod._extract_phone_number_id(body), "990364001")

    def test_extract_phone_number_id_payload_vacio(self):
        mod = _load_meta_dep_with_fake_supabase(_FakeSupabaseClient([]))
        self.assertIsNone(mod._extract_phone_number_id(b""))
        self.assertIsNone(mod._extract_phone_number_id(b"not json"))
        self.assertIsNone(mod._extract_phone_number_id(b'{"object":"x"}'))

    def test_hmac_verify_correcto(self):
        mod = _load_meta_dep_with_fake_supabase(_FakeSupabaseClient([]))
        body = b'{"object":"whatsapp_business_account"}'
        secret = "test_secret"
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        self.assertTrue(mod._hmac_verify(body, sig, secret))

    def test_hmac_verify_incorrecto(self):
        mod = _load_meta_dep_with_fake_supabase(_FakeSupabaseClient([]))
        body = b'{"object":"whatsapp_business_account"}'
        self.assertFalse(mod._hmac_verify(body, "0" * 64, "test_secret"))

    def test_hmac_verify_secret_distinto_falla(self):
        mod = _load_meta_dep_with_fake_supabase(_FakeSupabaseClient([]))
        body = b'{"object":"whatsapp_business_account","tenant":"A"}'
        sig_a = hmac.new(b"SECRET_A", body, hashlib.sha256).hexdigest()
        self.assertFalse(mod._hmac_verify(body, sig_a, "SECRET_B"))


class TenantResolutionForensicsTests(unittest.TestCase):
    """Forensics: lookup phone_number_id → tenant_id para auditoría
    Habeas Data + debugging multi-tenant. NO se usa para HMAC."""

    def test_resolve_tenant_id_encontrado(self):
        sb = _FakeSupabaseClient([
            {"tenant_id": "tenant-A", "credentials": {"phone_number_id": "PHONE_A"}},
        ])
        mod = _load_meta_dep_with_fake_supabase(sb)
        self.assertEqual(mod._resolve_tenant_id_for_phone_number("PHONE_A"), "tenant-A")

    def test_resolve_tenant_id_no_encontrado(self):
        sb = _FakeSupabaseClient([
            {"tenant_id": "tenant-A", "credentials": {"phone_number_id": "OTRO"}},
        ])
        mod = _load_meta_dep_with_fake_supabase(sb)
        self.assertIsNone(mod._resolve_tenant_id_for_phone_number("PHONE_A"))

    def test_resolve_tenant_id_aislamiento_multi_tenant(self):
        """Lookup retorna SOLO el tenant correcto, NO mezcla."""
        sb = _FakeSupabaseClient([
            {"tenant_id": "tenant-A", "credentials": {"phone_number_id": "PHONE_A"}},
            {"tenant_id": "tenant-B", "credentials": {"phone_number_id": "PHONE_B"}},
        ])
        mod = _load_meta_dep_with_fake_supabase(sb)
        self.assertEqual(mod._resolve_tenant_id_for_phone_number("PHONE_A"), "tenant-A")
        self.assertEqual(mod._resolve_tenant_id_for_phone_number("PHONE_B"), "tenant-B")
        self.assertIsNone(mod._resolve_tenant_id_for_phone_number("PHONE_C"))

    def test_cache_evita_segundo_lookup_db(self):
        sb = _FakeSupabaseClient([
            {"tenant_id": "tenant-A", "credentials": {"phone_number_id": "PHONE_A"}},
        ])
        mod = _load_meta_dep_with_fake_supabase(sb)
        original_table = sb.table
        call_counter = {"n": 0}
        def counting_table(name):
            call_counter["n"] += 1
            return original_table(name)
        sb.table = counting_table  # type: ignore

        t1 = mod._resolve_tenant_id_for_phone_number("PHONE_A")
        t2 = mod._resolve_tenant_id_for_phone_number("PHONE_A")
        self.assertEqual(t1, "tenant-A")
        self.assertEqual(t2, "tenant-A")
        self.assertEqual(call_counter["n"], 1)

    def test_cache_negativo_tambien_evita_db(self):
        """No-encontrado se cachea — evita lookups repetidos para
        phone_number_ids huérfanos (e.g., tenant offboarded)."""
        sb = _FakeSupabaseClient([])
        mod = _load_meta_dep_with_fake_supabase(sb)
        original_table = sb.table
        call_counter = {"n": 0}
        def counting_table(name):
            call_counter["n"] += 1
            return original_table(name)
        sb.table = counting_table  # type: ignore

        t1 = mod._resolve_tenant_id_for_phone_number("HUERFANO")
        t2 = mod._resolve_tenant_id_for_phone_number("HUERFANO")
        self.assertIsNone(t1)
        self.assertIsNone(t2)
        self.assertEqual(call_counter["n"], 1)


if __name__ == "__main__":
    unittest.main()

"""Tests Model B Direct Provider per-tenant (ADR-0023).

Cubre `services/connector-whatsapp/dependencies/meta.py` post-refactor:
  - HMAC verify usa app_secret per-tenant (Vault lookup) en vez de global env.
  - Cross-tenant invariant: phone_number_id del payload debe resolver al mismo
    tenant_id del path URL.
  - Cache + single-flight.
  - Métricas in-memory.
  - Status filter IN ('connected', 'pending_token').

Reemplaza `test_meta_hmac_per_tenant.py` (que validaba el modelo global obsoleto).
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
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = REPO_ROOT / "services" / "connector-whatsapp"


def _load_module(rel_path: str, module_name: str):
    """Load module from connector deploy unit, isolated from main path."""
    full_path = CONNECTOR_PATH / rel_path
    if str(CONNECTOR_PATH) not in sys.path:
        sys.path.insert(0, str(CONNECTOR_PATH))
    spec = importlib.util.spec_from_file_location(module_name, str(full_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_meta = _load_module("dependencies/meta.py", "_test_model_b_meta")


# ─── Helpers ────────────────────────────────────────────────────────────────

KONVI_DEV_TID = "6115474f-7046-44a8-88ad-182dbf7626a6"
KAIU_TID = "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9"
KONVI_DEV_SECRET = "41eb550c0dad8118ba389fb6822ab2f6"  # mock value
KAIU_SECRET = "1895ac2113e77866574486dbb438e3dd"  # mock value
KONVI_DEV_PHONE_ID = "1124135250785919"
KAIU_PHONE_ID = "990364080831295"


def _sign(secret: str, body: bytes) -> str:
    """Calcula firma X-Hub-Signature-256 con secret dado."""
    return "sha256=" + hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()


def _payload_for(phone_number_id: str) -> bytes:
    """Payload Meta sintético con phone_number_id específico."""
    return json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ANY",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {
                        "phone_number_id": phone_number_id,
                        "display_phone_number": "+57XXX",
                    },
                    "messages": [{
                        "from": "57123",
                        "id": "wamid.test",
                        "timestamp": "1700000000",
                        "type": "text",
                        "text": {"body": "hola"},
                    }],
                },
            }],
        }],
    }).encode("utf-8")


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class FakeRequest:
    """Mimics FastAPI Request just enough for verify_meta_signature_for_tenant.

    Incluye headers + client (Ola 0 añadió Content-Length cap + rate-limit per-IP
    al inicio del dependency; un Request real de FastAPI siempre los tiene)."""

    _ip_counter = 0

    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}
        # IP única por instancia → los tests no comparten el bucket del rate-limit.
        FakeRequest._ip_counter += 1
        self.client = _FakeClient(f"10.0.0.{FakeRequest._ip_counter % 250}")

    async def body(self) -> bytes:
        return self._body


# ─── Mocks de DB + Vault ─────────────────────────────────────────────────────

def _make_fake_credentials(tenant_id: str):
    """Devuelve credentials dict per tenant_id."""
    if tenant_id == KONVI_DEV_TID:
        return {
            "app_secret_secret_id": "vault-konvi-dev-id",
            "verify_token": "konvi-dev-direct-2026",
            "phone_number_id": KONVI_DEV_PHONE_ID,
        }
    if tenant_id == KAIU_TID:
        return {
            "app_secret_secret_id": "vault-kaiu-id",
            "verify_token": "konvi-kaiu-direct-2026",
            "phone_number_id": KAIU_PHONE_ID,
        }
    return None


def _fake_fetch_credentials(tenant_id: str):
    return _make_fake_credentials(tenant_id)


def _fake_vault_read(secret_id: str):
    return {
        "vault-konvi-dev-id": KONVI_DEV_SECRET,
        "vault-kaiu-id": KAIU_SECRET,
    }.get(secret_id)


def _fake_resolve_phone(phone_number_id: str):
    return {
        KONVI_DEV_PHONE_ID: KONVI_DEV_TID,
        KAIU_PHONE_ID: KAIU_TID,
    }.get(phone_number_id)


# ─── Tests ───────────────────────────────────────────────────────────────────

class ModelBHmacTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Reset caches between tests
        _meta._cache_invalidate_all()
        with _meta._metrics_lock:
            for k in _meta._metrics:
                _meta._metrics[k] = 0
            _meta._unique_tenants_seen.clear()

    def _patch_lookups(self):
        """Patches comunes: fetch_credentials, Vault, phone resolve."""
        patches = [
            patch.object(_meta, "_fetch_tenant_credentials", side_effect=_fake_fetch_credentials),
            patch.object(_meta, "_resolve_tenant_id_for_phone_number", side_effect=_fake_resolve_phone),
        ]
        # Patch VaultHelper en `lib.vault_helper`
        fake_vault = SimpleNamespace(read_secret=_fake_vault_read)
        fake_vault_cls = SimpleNamespace(__call__=lambda sb: fake_vault)
        # Mock import dinámico
        fake_vh_module = SimpleNamespace(VaultHelper=lambda sb: fake_vault)
        sys.modules["lib.vault_helper"] = fake_vh_module
        # Mock get_supabase para que _get_sb_client retorne algo no-None
        patches.append(patch.object(_meta, "_get_sb_client", return_value=SimpleNamespace()))
        return patches

    async def test_01_app_secret_resolve_ok(self):
        """_resolve_tenant_app_secret retorna secret correcto Konvi Dev."""
        for p in self._patch_lookups():
            p.start()
        try:
            secret = _meta._resolve_tenant_app_secret(KONVI_DEV_TID)
            self.assertEqual(secret, KONVI_DEV_SECRET)
        finally:
            patch.stopall()

    async def test_02_app_secret_resolve_unknown_tenant(self):
        """Tenant inexistente → None."""
        for p in self._patch_lookups():
            p.start()
        try:
            secret = _meta._resolve_tenant_app_secret("00000000-0000-0000-0000-000000000000")
            self.assertIsNone(secret)
        finally:
            patch.stopall()

    async def test_03_hmac_valid_ok(self):
        """HMAC válido con secret per-tenant → 200 (retorna raw_body)."""
        for p in self._patch_lookups():
            p.start()
        try:
            body = _payload_for(KONVI_DEV_PHONE_ID)
            sig = _sign(KONVI_DEV_SECRET, body)
            request = FakeRequest(body)
            result = await _meta.verify_meta_signature_for_tenant(
                tenant_id=KONVI_DEV_TID, request=request, x_hub_signature_256=sig,
            )
            self.assertEqual(result, body)
            metrics = _meta.get_metrics_snapshot()
            self.assertEqual(metrics["hmac_ok"], 1)
        finally:
            patch.stopall()

    async def test_04_hmac_wrong_secret_403(self):
        """HMAC firmado con secret de tenant A enviado a tenant B → 403."""
        for p in self._patch_lookups():
            p.start()
        try:
            body = _payload_for(KAIU_PHONE_ID)
            sig = _sign(KAIU_SECRET, body)  # firma con KAIU secret
            request = FakeRequest(body)
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as ctx:
                await _meta.verify_meta_signature_for_tenant(
                    tenant_id=KONVI_DEV_TID,  # pero path es Konvi Dev
                    request=request, x_hub_signature_256=sig,
                )
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            patch.stopall()

    async def test_05_missing_signature_403(self):
        """Sin X-Hub-Signature-256 header → 403."""
        for p in self._patch_lookups():
            p.start()
        try:
            from fastapi import HTTPException
            request = FakeRequest(b"{}")
            with self.assertRaises(HTTPException) as ctx:
                await _meta.verify_meta_signature_for_tenant(
                    tenant_id=KONVI_DEV_TID, request=request, x_hub_signature_256=None,
                )
            self.assertEqual(ctx.exception.status_code, 403)
            metrics = _meta.get_metrics_snapshot()
            self.assertEqual(metrics["hmac_fail_missing_signature"], 1)
        finally:
            patch.stopall()

    async def test_06_unknown_tenant_in_path_403(self):
        """Path con tenant_id inexistente → 403 (no leak)."""
        for p in self._patch_lookups():
            p.start()
        try:
            from fastapi import HTTPException
            body = b'{"object": "test"}'
            sig = _sign("any", body)
            request = FakeRequest(body)
            with self.assertRaises(HTTPException) as ctx:
                await _meta.verify_meta_signature_for_tenant(
                    tenant_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
                    request=request, x_hub_signature_256=sig,
                )
            self.assertEqual(ctx.exception.status_code, 403)
            metrics = _meta.get_metrics_snapshot()
            self.assertEqual(metrics["hmac_fail_no_secret_for_tenant"], 1)
        finally:
            patch.stopall()

    async def test_07_cache_hit_avoids_second_vault_lookup(self):
        """2 llamadas consecutivas → 1 Vault hit + 1 cache hit."""
        for p in self._patch_lookups():
            p.start()
        try:
            body = _payload_for(KONVI_DEV_PHONE_ID)
            sig = _sign(KONVI_DEV_SECRET, body)
            request1 = FakeRequest(body)
            request2 = FakeRequest(body)

            await _meta.verify_meta_signature_for_tenant(
                tenant_id=KONVI_DEV_TID, request=request1, x_hub_signature_256=sig,
            )
            await _meta.verify_meta_signature_for_tenant(
                tenant_id=KONVI_DEV_TID, request=request2, x_hub_signature_256=sig,
            )
            metrics = _meta.get_metrics_snapshot()
            self.assertEqual(metrics["vault_hits_app_secret"], 1)
            self.assertEqual(metrics["cache_hits_app_secret"], 1)
        finally:
            patch.stopall()

    async def test_08_cross_tenant_invariant_403(self):
        """Path tenant_A + HMAC válido con secret_A pero payload tiene
        phone_number_id de tenant_B → 403 (cross-tenant attack defense)."""
        # Construir payload con phone_number_id de KAIU, pero firmar y enviar a Konvi Dev
        for p in self._patch_lookups():
            p.start()
        try:
            body = _payload_for(KAIU_PHONE_ID)  # phone_number_id KAIU
            sig = _sign(KONVI_DEV_SECRET, body)  # firmado con Konvi Dev secret (válido)
            request = FakeRequest(body)
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as ctx:
                await _meta.verify_meta_signature_for_tenant(
                    tenant_id=KONVI_DEV_TID,  # path Konvi Dev
                    request=request, x_hub_signature_256=sig,
                )
            self.assertEqual(ctx.exception.status_code, 403)
            metrics = _meta.get_metrics_snapshot()
            self.assertEqual(metrics["hmac_fail_cross_tenant_invariant"], 1)
        finally:
            patch.stopall()

    async def test_09_verify_token_lookup(self):
        """_resolve_tenant_verify_token retorna verify_token desde credentials JSONB."""
        for p in self._patch_lookups():
            p.start()
        try:
            token = _meta._resolve_tenant_verify_token(KAIU_TID)
            self.assertEqual(token, "konvi-kaiu-direct-2026")
            token2 = _meta._resolve_tenant_verify_token(KONVI_DEV_TID)
            self.assertEqual(token2, "konvi-dev-direct-2026")
        finally:
            patch.stopall()

    async def test_10_both_tenants_work_independently(self):
        """Konvi Dev y KAIU procesan webhooks en paralelo con secrets distintos."""
        for p in self._patch_lookups():
            p.start()
        try:
            # Konvi Dev webhook
            body_kd = _payload_for(KONVI_DEV_PHONE_ID)
            sig_kd = _sign(KONVI_DEV_SECRET, body_kd)
            result_kd = await _meta.verify_meta_signature_for_tenant(
                tenant_id=KONVI_DEV_TID, request=FakeRequest(body_kd),
                x_hub_signature_256=sig_kd,
            )
            self.assertEqual(result_kd, body_kd)

            # KAIU webhook (secret distinto)
            body_kaiu = _payload_for(KAIU_PHONE_ID)
            sig_kaiu = _sign(KAIU_SECRET, body_kaiu)
            result_kaiu = await _meta.verify_meta_signature_for_tenant(
                tenant_id=KAIU_TID, request=FakeRequest(body_kaiu),
                x_hub_signature_256=sig_kaiu,
            )
            self.assertEqual(result_kaiu, body_kaiu)

            metrics = _meta.get_metrics_snapshot()
            self.assertEqual(metrics["hmac_ok"], 2)
            self.assertEqual(metrics["unique_tenants_seen"], 2)
        finally:
            patch.stopall()


# ─── Parser dispatcher tests (migrados de test_meta_hmac_per_tenant.py 2026-06-22) ──
# Estos validan parse_webhook_events() del módulo parser. NO se acoplan al modelo
# HMAC (global vs Model B) — son tests de pure parsing del payload Meta.
# Migrados aquí post-deprecación de test_meta_hmac_per_tenant.py.

_parser = _load_module("services/parser.py", "_test_model_b_parser")


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


if __name__ == "__main__":
    unittest.main()

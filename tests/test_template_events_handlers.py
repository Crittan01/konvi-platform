"""Tests handlers persistence template events webhooks
(Sem 7 F2 item 4 / 2026-05-17).

Cubre `services/connector-whatsapp/services/template_events.py`:
  - persist_template_status_update: APPROVED/REJECTED/PAUSED + reason
  - persist_template_quality_update: GREEN/YELLOW/RED
  - persist_phone_quality_update: tier merge en credentials JSONB
  - handle_event: dispatcher por event_type

Mocks Supabase + lookup tenant.
"""
from __future__ import annotations

import importlib.util
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


# Cargar parser para acceder a EVENT_TYPE_* constants
_parser = _load_module("services/parser.py", "_test_parser_for_handlers")


# Cargar template_events con db_persistence + parser stubbeados (no necesitamos
# Supabase real para tests unitarios).
class _FakeQuery:
    def __init__(self, store: list[dict], op: str = "select",
                 payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple] = []
        self._neq_filters: list[tuple] = []
        self._limit_n: int | None = None

    def select(self, *a, **k):
        return _FakeQuery(self._store, op="select")

    def update(self, payload):
        return _FakeQuery(self._store, op="update", payload=payload)

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def neq(self, col, val):
        self._neq_filters.append((col, val))
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def _matches(self, r) -> bool:
        return (
            all(r.get(c) == v for c, v in self._filters)
            and all(r.get(c) != v for c, v in self._neq_filters)
        )

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            if self._limit_n is not None:
                rows = rows[: self._limit_n]
            return SimpleNamespace(data=rows)
        if self._op == "update":
            updated = []
            for row in self._store:
                if self._matches(row):
                    for k, v in self._payload.items():
                        row[k] = v
                    updated.append(row)
            return SimpleNamespace(data=updated)
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict]] = {
            "whatsapp_templates": [],
            "tenant_integrations": [],
            "tenants": [],
        }

    def table(self, name):
        return _FakeQuery(self._tables.setdefault(name, []))


def _setup_modules(fake_sb):
    """Inyecta stubs en sys.modules para que template_events imports OK.
    Reload template_events si ya estaba cargado."""
    # Stub services.db_persistence
    services_pkg = sys.modules.get("services")
    if services_pkg is None:
        services_pkg = type(sys)("services")
        services_pkg.__path__ = []  # type: ignore
        sys.modules["services"] = services_pkg

    db_stub = type(sys)("services.db_persistence")

    def _resolve_by_waba(sb, waba_id):
        for t in fake_sb._tables.get("tenants", []):
            if t.get("meta_waba_id") == waba_id and t.get("status") == "active":
                return t.get("id")
        return None

    db_stub.get_supabase = lambda: fake_sb  # type: ignore
    db_stub._resolve_tenant_by_waba = _resolve_by_waba  # type: ignore
    sys.modules["services.db_persistence"] = db_stub

    # Stub services.parser con event_type constants
    parser_stub = type(sys)("services.parser")
    parser_stub.EVENT_TYPE_OUTBOUND_STATUS = _parser.EVENT_TYPE_OUTBOUND_STATUS
    parser_stub.EVENT_TYPE_TEMPLATE_STATUS_UPDATE = _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE
    parser_stub.EVENT_TYPE_TEMPLATE_QUALITY_UPDATE = _parser.EVENT_TYPE_TEMPLATE_QUALITY_UPDATE
    parser_stub.EVENT_TYPE_PHONE_QUALITY_UPDATE = _parser.EVENT_TYPE_PHONE_QUALITY_UPDATE
    # Track 6 (2026-08-22): constantes nuevas que handle_event importa (lazy).
    parser_stub.EVENT_TYPE_TEMPLATE_CATEGORY_UPDATE = _parser.EVENT_TYPE_TEMPLATE_CATEGORY_UPDATE
    parser_stub.EVENT_TYPE_USER_PREFERENCE = _parser.EVENT_TYPE_USER_PREFERENCE
    parser_stub.EVENT_TYPE_ACCOUNT_ALERT = _parser.EVENT_TYPE_ACCOUNT_ALERT
    sys.modules["services.parser"] = parser_stub

    # Re-load template_events para que use nuestros stubs.
    if "_test_template_events" in sys.modules:
        del sys.modules["_test_template_events"]
    spec = importlib.util.spec_from_file_location(
        "_test_template_events",
        str(CONNECTOR_PATH / "services" / "template_events.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_template_events"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# Track 6 (2026-08-22): restauración xunit de sys.modules — los stubs de este
# archivo (services/services.parser/services.db_persistence) no deben contaminar
# a otros archivos de la suite (lección de aislamiento del repo, bitácora M18/G14;
# la combinación con test_track6_meta_webhook_events.py la hizo visible).
_STUBBED = (
    "services", "services.db_persistence", "services.parser",
    "_test_parser_for_handlers", "_test_template_events",
)
_ORIGINAL_MODULES: dict = {}


def setUpModule():
    for _name in _STUBBED:
        _ORIGINAL_MODULES[_name] = sys.modules.get(_name)


def tearDownModule():
    for _name in _STUBBED:
        _orig = _ORIGINAL_MODULES.get(_name)
        if _orig is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _orig


def _seed_template(sb, *, meta_template_id="META_T1", tenant_id="tenant-A",
                   name="payment_reminder_v1", language="es_CO",
                   status="PENDING", quality="UNKNOWN"):
    sb._tables["whatsapp_templates"].append({
        "id": "tpl-1",
        "tenant_id": tenant_id,
        "waba_id": "WABA_X",
        "meta_template_id": meta_template_id,
        "name": name,
        "language": language,
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": "x"}],
        "parameter_format": "POSITIONAL",
        "status": status,
        "quality_rating": quality,
    })


def _seed_message(sb, *, meta_message_id="wamid.OUT1", tenant_id="tenant-A",
                  direction="outbound", delivery_status=None):
    sb._tables.setdefault("messages", []).append({
        "id": "msg-1",
        "tenant_id": tenant_id,
        "conversation_id": "conv-1",
        "direction": direction,
        "meta_message_id": meta_message_id,
        "delivery_status": delivery_status,
    })


def _seed_tenant_integration(sb, *, tenant_id="tenant-A", waba_id="WABA_X",
                             tier=None):
    sb._tables["tenants"].append({
        "id": tenant_id,
        "meta_waba_id": waba_id,
        "status": "active",
    })
    creds: dict = {"phone_number_id": "PHONE_1", "access_token": "EAAxxx"}
    if tier:
        creds["tier"] = tier
    sb._tables["tenant_integrations"].append({
        "tenant_id": tenant_id,
        "provider": "whatsapp",
        "status": "connected",
        "credentials": creds,
    })


# ─── persist_template_status_update ──────────────────────────────────────────


class StatusUpdateTests(unittest.TestCase):
    def test_approved_sets_approved_at(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, status="PENDING")
        event = {
            "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            "meta_waba_id": "WABA_X",
            "meta_template_id": "META_T1",
            "template_name": "payment_reminder_v1",
            "template_language": "es_CO",
            "new_status": "APPROVED",
            "reason": None,
        }
        result = te.persist_template_status_update(event, tenant_id_verified="tenant-A")
        self.assertTrue(result)
        row = sb._tables["whatsapp_templates"][0]
        self.assertEqual(row["status"], "APPROVED")
        self.assertIsNotNone(row.get("approved_at"))
        self.assertIsNone(row.get("status_reason"))

    def test_rejected_persiste_reason(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, status="PENDING")
        event = {
            "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            "meta_template_id": "META_T1",
            "new_status": "REJECTED",
            "reason": "INCORRECT_CATEGORY",
        }
        result = te.persist_template_status_update(event, tenant_id_verified="tenant-A")
        self.assertTrue(result)
        row = sb._tables["whatsapp_templates"][0]
        self.assertEqual(row["status"], "REJECTED")
        self.assertEqual(row["status_reason"], "INCORRECT_CATEGORY")
        # NO se setea approved_at en REJECTED
        self.assertIsNone(row.get("approved_at"))

    def test_paused_disabled_actualiza_status(self):
        for status in ("PAUSED", "DISABLED", "FLAGGED", "LIMIT_EXCEEDED"):
            sb = _FakeSupabase()
            te = _setup_modules(sb)
            _seed_template(sb, status="APPROVED")
            event = {
                "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
                "meta_template_id": "META_T1",
                "new_status": status,
                "reason": "QUALITY_DROP" if status == "PAUSED" else None,
            }
            te.persist_template_status_update(event, tenant_id_verified="tenant-A")
            row = sb._tables["whatsapp_templates"][0]
            self.assertEqual(row["status"], status)

    def test_local_draft_reabierto_no_es_pisado_por_webhook_tardio(self):
        # El usuario editó el template (volvió a LOCAL_DRAFT). Un webhook tardío del
        # submit viejo NO debe pisar el borrador local: el .neq("status","LOCAL_DRAFT")
        # deja la fila intacta y el handler retorna False.
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, status="LOCAL_DRAFT")
        event = {
            "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            "meta_template_id": "META_T1",
            "new_status": "APPROVED",
            "reason": None,
        }
        result = te.persist_template_status_update(event, tenant_id_verified="tenant-A")
        self.assertFalse(result)
        row = sb._tables["whatsapp_templates"][0]
        self.assertEqual(row["status"], "LOCAL_DRAFT")
        self.assertIsNone(row.get("approved_at"))

    def test_meta_template_id_no_existe_returns_false(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        # No seed template
        event = {
            "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            "meta_template_id": "META_HUERFANO",
            "new_status": "APPROVED",
            "reason": None,
        }
        result = te.persist_template_status_update(event, tenant_id_verified="tenant-A")
        self.assertFalse(result)

    def test_evento_sin_meta_template_id_returns_false(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        result = te.persist_template_status_update({
            "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            "new_status": "APPROVED",
        }, tenant_id_verified="tenant-A")
        self.assertFalse(result)

    def test_evento_sin_new_status_returns_false(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        result = te.persist_template_status_update({
            "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            "meta_template_id": "META_T1",
        }, tenant_id_verified="tenant-A")
        self.assertFalse(result)


# ─── persist_template_quality_update ─────────────────────────────────────────


class QualityUpdateTests(unittest.TestCase):
    def test_yellow(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, status="APPROVED", quality="GREEN")
        event = {
            "event_type": _parser.EVENT_TYPE_TEMPLATE_QUALITY_UPDATE,
            "meta_template_id": "META_T1",
            "previous_quality": "GREEN",
            "new_quality": "YELLOW",
        }
        result = te.persist_template_quality_update(event, tenant_id_verified="tenant-A")
        self.assertTrue(result)
        row = sb._tables["whatsapp_templates"][0]
        self.assertEqual(row["quality_rating"], "YELLOW")

    def test_red(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, quality="YELLOW")
        te.persist_template_quality_update({
            "event_type": _parser.EVENT_TYPE_TEMPLATE_QUALITY_UPDATE,
            "meta_template_id": "META_T1",
            "new_quality": "RED",
        }, tenant_id_verified="tenant-A")
        self.assertEqual(sb._tables["whatsapp_templates"][0]["quality_rating"], "RED")

    def test_template_no_existe_returns_false(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        result = te.persist_template_quality_update({
            "event_type": _parser.EVENT_TYPE_TEMPLATE_QUALITY_UPDATE,
            "meta_template_id": "META_NEVER",
            "new_quality": "YELLOW",
        }, tenant_id_verified="tenant-A")
        self.assertFalse(result)


# ─── persist_phone_quality_update ────────────────────────────────────────────


class PhoneQualityUpdateTests(unittest.TestCase):
    def test_tier_upgrade_merge_jsonb(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_tenant_integration(sb, tier="TIER_250")
        event = {
            "event_type": _parser.EVENT_TYPE_PHONE_QUALITY_UPDATE,
            "meta_waba_id": "WABA_X",
            "display_phone_number": "+57 311 5678910",
            "current_limit": "TIER_1K",
            "event": "UPGRADED",
        }
        result = te.persist_phone_quality_update(event, tenant_id_verified="tenant-A")
        self.assertTrue(result)
        row = sb._tables["tenant_integrations"][0]
        # tier actualizado, phone_number_id preservado
        self.assertEqual(row["credentials"]["tier"], "TIER_1K")
        self.assertEqual(row["credentials"]["phone_number_id"], "PHONE_1")
        self.assertEqual(row["credentials"]["access_token"], "EAAxxx")

    def test_flagged_persiste_quality_signal(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_tenant_integration(sb, tier="TIER_1K")
        te.persist_phone_quality_update({
            "event_type": _parser.EVENT_TYPE_PHONE_QUALITY_UPDATE,
            "meta_waba_id": "WABA_X",
            "current_limit": "TIER_1K",
            "event": "FLAGGED",
        }, tenant_id_verified="tenant-A")
        row = sb._tables["tenant_integrations"][0]
        self.assertEqual(row["credentials"]["quality_signal"], "FLAGGED")

    def test_sin_tenant_integration_returns_false(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        # No seed tenant_integration → el lookup de credentials devuelve [] → False.
        result = te.persist_phone_quality_update({
            "event_type": _parser.EVENT_TYPE_PHONE_QUALITY_UPDATE,
            "meta_waba_id": "WABA_X",
            "current_limit": "TIER_250",
            "event": "UPGRADED",
        }, tenant_id_verified="tenant-A")
        self.assertFalse(result)

    def test_f52_fail_closed_sin_tenant_verificado(self):
        # F52: sin tenant HMAC-verificado, los 3 handlers de escritura fallan cerrado.
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, status="PENDING")
        _seed_tenant_integration(sb, tier="TIER_250")
        self.assertFalse(te.persist_template_status_update(
            {"meta_template_id": "META_T1", "new_status": "APPROVED"}))
        self.assertFalse(te.persist_template_quality_update(
            {"meta_template_id": "META_T1", "new_quality": "YELLOW"}))
        self.assertFalse(te.persist_phone_quality_update(
            {"meta_waba_id": "WABA_X", "current_limit": "TIER_1K", "event": "UPGRADED"}))
        # Nada se modificó.
        self.assertEqual(sb._tables["whatsapp_templates"][0]["status"], "PENDING")

    def test_f52_cross_tenant_rechazado(self):
        # F52: un tenant B (HMAC válido) NO puede mutar el template de A (0 filas matchean).
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, tenant_id="tenant-A", status="PENDING")
        result = te.persist_template_status_update(
            {"meta_template_id": "META_T1", "new_status": "APPROVED"},
            tenant_id_verified="tenant-B",   # atacante
        )
        self.assertFalse(result)
        self.assertEqual(sb._tables["whatsapp_templates"][0]["status"], "PENDING")  # intacto


# ─── handle_event dispatcher ─────────────────────────────────────────────────


class HandleEventDispatcherTests(unittest.TestCase):
    def test_dispatch_template_status(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb, status="PENDING")
        result = te.handle_event({
            "event_type": _parser.EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
            "meta_template_id": "META_T1",
            "new_status": "APPROVED",
        }, tenant_id_verified="tenant-A")
        self.assertTrue(result)

    def test_dispatch_template_quality(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_template(sb)
        result = te.handle_event({
            "event_type": _parser.EVENT_TYPE_TEMPLATE_QUALITY_UPDATE,
            "meta_template_id": "META_T1",
            "new_quality": "YELLOW",
        }, tenant_id_verified="tenant-A")
        self.assertTrue(result)

    def test_dispatch_phone_quality(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_tenant_integration(sb)
        result = te.handle_event({
            "event_type": _parser.EVENT_TYPE_PHONE_QUALITY_UPDATE,
            "meta_waba_id": "WABA_X",
            "current_limit": "TIER_1K",
            "event": "UPGRADED",
        }, tenant_id_verified="tenant-A")
        self.assertTrue(result)

    def test_dispatch_outbound_status(self):
        """outbound_status (delivery receipt) — ahora SÍ tiene handler y persiste."""
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        _seed_message(sb, delivery_status="sent")
        result = te.handle_event({
            "event_type": _parser.EVENT_TYPE_OUTBOUND_STATUS,
            "meta_message_id": "wamid.OUT1",
            "status": "delivered",
            "timestamp": "1700000000",
        }, tenant_id_verified="tenant-A")
        self.assertTrue(result)
        row = sb._tables["messages"][0]
        self.assertEqual(row["delivery_status"], "delivered")
        self.assertIsNotNone(row.get("delivered_at"))

    def test_event_sin_handler_returns_none(self):
        """unknown — sin handler → None.

        Track 6 (2026-08-22): account_alert YA TIENE handler (persiste en
        tenant_provider_health) — sin tenant verificado falla cerrado (False, F52),
        ya no es None. Solo `unknown` sigue sin persistencia.
        """
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        result = te.handle_event({"event_type": _parser.EVENT_TYPE_UNKNOWN, "meta_waba_id": "X"})
        self.assertIsNone(result, "Esperado None para unknown")
        # account_alert sin tenant HMAC-verificado → fail-closed False (no None, no crash)
        result_alert = te.handle_event({"event_type": _parser.EVENT_TYPE_ACCOUNT_ALERT, "raw_value": {}})
        self.assertFalse(result_alert)

    def test_event_no_es_dict_returns_none(self):
        sb = _FakeSupabase()
        te = _setup_modules(sb)
        self.assertIsNone(te.handle_event(None))
        self.assertIsNone(te.handle_event("string"))
        self.assertIsNone(te.handle_event([{"x": 1}]))


# ─── persist_outbound_status (delivery receipts) ─────────────────────────────


class PersistOutboundStatusTests(unittest.TestCase):
    def _handler(self, sb):
        return _setup_modules(sb).persist_outbound_status

    def test_fail_closed_sin_tenant(self):
        sb = _FakeSupabase()
        persist = self._handler(sb)
        _seed_message(sb)
        self.assertFalse(persist({
            "meta_message_id": "wamid.OUT1", "status": "delivered",
        }, tenant_id_verified=None))

    def test_status_invalido_rechazado(self):
        sb = _FakeSupabase()
        persist = self._handler(sb)
        _seed_message(sb)
        self.assertFalse(persist({
            "meta_message_id": "wamid.OUT1", "status": "teleported",
        }, tenant_id_verified="tenant-A"))

    def test_sin_fila_outbound_devuelve_false(self):
        sb = _FakeSupabase()
        persist = self._handler(sb)
        # No se sembró ningún mensaje → carrera worker/receipt.
        self.assertFalse(persist({
            "meta_message_id": "wamid.MISSING", "status": "delivered",
        }, tenant_id_verified="tenant-A"))

    def test_avance_monotono_read_gana(self):
        sb = _FakeSupabase()
        persist = self._handler(sb)
        _seed_message(sb, delivery_status="delivered")
        r = persist({
            "meta_message_id": "wamid.OUT1", "status": "read",
            "timestamp": "1700000100",
        }, tenant_id_verified="tenant-A")
        self.assertTrue(r)
        row = sb._tables["messages"][0]
        self.assertEqual(row["delivery_status"], "read")
        self.assertIsNotNone(row.get("read_at"))

    def test_idempotente_no_degrada(self):
        """Un 'delivered' tardío tras 'read' es no-op (Meta reordena/reenvía)."""
        sb = _FakeSupabase()
        persist = self._handler(sb)
        _seed_message(sb, delivery_status="read")
        r = persist({
            "meta_message_id": "wamid.OUT1", "status": "delivered",
        }, tenant_id_verified="tenant-A")
        self.assertIsNone(r)  # no-op idempotente
        self.assertEqual(sb._tables["messages"][0]["delivery_status"], "read")

    def test_reenvio_mismo_status_es_noop(self):
        sb = _FakeSupabase()
        persist = self._handler(sb)
        _seed_message(sb, delivery_status="delivered")
        self.assertIsNone(persist({
            "meta_message_id": "wamid.OUT1", "status": "delivered",
        }, tenant_id_verified="tenant-A"))

    def test_failed_persiste_error_meta(self):
        sb = _FakeSupabase()
        persist = self._handler(sb)
        _seed_message(sb, delivery_status="sent")
        r = persist({
            "meta_message_id": "wamid.OUT1", "status": "failed",
            "timestamp": "1700000200",
            "errors": [{"code": 131047, "title": "Re-engagement message",
                        "message": "Ventana 24h cerrada"}],
        }, tenant_id_verified="tenant-A")
        self.assertTrue(r)
        row = sb._tables["messages"][0]
        self.assertEqual(row["delivery_status"], "failed")
        self.assertIsNotNone(row.get("failed_at"))
        self.assertEqual(row["delivery_error"][0]["code"], 131047)

    def test_cross_tenant_no_matchea(self):
        """El receipt de tenant-A no puede mutar la fila de tenant-A si el
        UPDATE filtra por otro tenant verificado (aislamiento F52)."""
        sb = _FakeSupabase()
        persist = self._handler(sb)
        _seed_message(sb, tenant_id="tenant-A", delivery_status="sent")
        r = persist({
            "meta_message_id": "wamid.OUT1", "status": "delivered",
        }, tenant_id_verified="tenant-B")
        self.assertFalse(r)
        self.assertEqual(sb._tables["messages"][0]["delivery_status"], "sent")


if __name__ == "__main__":
    unittest.main()

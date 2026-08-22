"""Tests Track 6 / Meta (2026-08-22) — campos de webhook alineados a la doc oficial vigente.

Cubre los 3 campos que antes caían en `unknown` o sin persistencia
(matriz Track 6, fetch live developers.facebook.com 2026-08-22):

  - template_category_update → UPDATE whatsapp_templates.category (recategorización
    de Meta = cambio de PRECIO del template; sin esto la consola muestra precio stale)
  - user_preferences → stop nativo de marketing marca contacts.consent_comercial_revoked_at
    (anti-spam: la barrera comercial ya la consulta outbound_gate.py); resume NO muta
    (el consent comercial Ley 2300 se gana por nuestro flujo, no por Meta)
  - account_alerts → upsert tenant_provider_health (visibilidad de WABA flagged)
  - enums de estado de template ampliados (ARCHIVED/DELETED/REINSTATED/…)

Mismo patrón de stubs que tests/test_template_events_handlers.py.
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


_parser = _load_module("services/parser.py", "_t6_parser")


class _FakeQuery:
    """Fake mínimo con eq/is_/update/upsert/select para los handlers Track 6."""

    def __init__(self, store: list[dict], op: str = "select", payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple] = []
        self._isnull_filters: list[str] = []
        self._limit_n: int | None = None

    def select(self, *a, **k):
        return _FakeQuery(self._store, op="select")

    def update(self, payload):
        return _FakeQuery(self._store, op="update", payload=payload)

    def upsert(self, payload, on_conflict=None):
        return _FakeQuery(self._store, op="upsert", payload=payload)

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def is_(self, col, val):
        if val == "null":
            self._isnull_filters.append(col)
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def _matches(self, r) -> bool:
        return (
            all(r.get(c) == v for c, v in self._filters)
            and all(r.get(c) is None for c in self._isnull_filters)
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
                    row.update(self._payload)
                    updated.append(row)
            return SimpleNamespace(data=updated)
        if self._op == "upsert":
            p = self._payload
            for row in self._store:
                if all(row.get(k) == p.get(k) for k in ("tenant_id", "provider", "metric")):
                    row.update(p)
                    return SimpleNamespace(data=[row])
            self._store.append(dict(p))
            return SimpleNamespace(data=[p])
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict]] = {
            "whatsapp_templates": [],
            "tenant_integrations": [],
            "contacts": [],
            "tenant_provider_health": [],
            "tenants": [],
        }

    def table(self, name):
        return _FakeQuery(self._tables.setdefault(name, []))


_STUBBED_MODULE_NAMES = (
    "services", "services.db_persistence", "services.parser",
    "_t6_parser", "_t6_template_events",
)
_ORIGINAL_MODULES: dict = {}


def setUpModule():
    for name in _STUBBED_MODULE_NAMES:
        _ORIGINAL_MODULES[name] = sys.modules.get(name)


def tearDownModule():
    """Restaura sys.modules — los stubs del test no deben contaminar a otros
    archivos de la suite (lección de aislamiento del repo, bitácora M18/G14)."""
    for name in _STUBBED_MODULE_NAMES:
        original = _ORIGINAL_MODULES.get(name)
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def _setup_template_events(fake_sb):
    services_pkg = sys.modules.get("services")
    if services_pkg is None:
        services_pkg = type(sys)("services")
        services_pkg.__path__ = []  # type: ignore
        sys.modules["services"] = services_pkg

    db_stub = type(sys)("services.db_persistence")
    db_stub.get_supabase = lambda: fake_sb  # type: ignore
    sys.modules["services.db_persistence"] = db_stub

    parser_stub = type(sys)("services.parser")
    for c in (
        "EVENT_TYPE_OUTBOUND_STATUS", "EVENT_TYPE_TEMPLATE_STATUS_UPDATE",
        "EVENT_TYPE_TEMPLATE_QUALITY_UPDATE", "EVENT_TYPE_PHONE_QUALITY_UPDATE",
        "EVENT_TYPE_TEMPLATE_CATEGORY_UPDATE", "EVENT_TYPE_USER_PREFERENCE",
        "EVENT_TYPE_ACCOUNT_ALERT",
    ):
        setattr(parser_stub, c, getattr(_parser, c))
    sys.modules["services.parser"] = parser_stub

    sys.modules.pop("_t6_template_events", None)
    spec = importlib.util.spec_from_file_location(
        "_t6_template_events", str(CONNECTOR_PATH / "services" / "template_events.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_t6_template_events"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


TENANT = "t-tenant-1"
WABA = "2159052118202272"


def _payload(field: str, value: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": WABA, "changes": [{"field": field, "value": value}]}],
    }


class ParserNuevosCamposTests(unittest.TestCase):
    def test_category_update_clasifica_y_parsea(self):
        ev = _parser.parse_webhook_events(_payload("template_category_update", {
            "message_template_id": "tpl-9",
            "message_template_name": "promo_semana",
            "message_template_language": "es",
            "new_category": "MARKETING",
            "previous_category": "UTILITY",
        }))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["event_type"], "template_category_update")
        self.assertEqual(ev[0]["new_category"], "MARKETING")
        self.assertEqual(ev[0]["previous_category"], "UTILITY")

    def test_user_preferences_stop_parsea(self):
        ev = _parser.parse_webhook_events(_payload("user_preferences", {
            "user_preferences": [{
                "wa_id": "573001234567",
                "category": "marketing_messages",
                "value": "stop",
                "detail": "User requested to stop marketing messages",
                "timestamp": "1787400000",
            }],
        }))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["event_type"], "user_preference")
        self.assertEqual(ev[0]["preference"], "stop")
        self.assertEqual(ev[0]["wa_id"], "573001234567")

    def test_user_preferences_shape_roto_no_explotan(self):
        """Fail-safe: shape inesperado → 0 eventos, sin excepción."""
        ev = _parser.parse_webhook_events(_payload("user_preferences", {"user_preferences": "no-es-lista"}))
        self.assertEqual(ev, [])

    def test_account_alert_sigue_clasificando(self):
        ev = _parser.parse_webhook_events(_payload("account_alerts", {
            "event": "INCREASED_CAPABILITIES_DENIED", "alert_type": "LIMIT",
        }))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["event_type"], "account_alert")


class HandlersTrack6Tests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSupabase()
        self.mod = _setup_template_events(self.fake)

    def test_category_update_persiste_categoria(self):
        self.fake._tables["whatsapp_templates"].append({
            "id": "t1", "tenant_id": TENANT, "meta_template_id": "tpl-9", "category": "UTILITY",
        })
        ok = self.mod.persist_template_category_update({
            "meta_template_id": "tpl-9", "new_category": "MARKETING", "previous_category": "UTILITY",
        }, tenant_id_verified=TENANT)
        self.assertTrue(ok)
        self.assertEqual(self.fake._tables["whatsapp_templates"][0]["category"], "MARKETING")

    def test_category_update_fail_closed_sin_tenant(self):
        ok = self.mod.persist_template_category_update(
            {"meta_template_id": "tpl-9", "new_category": "MARKETING"}, tenant_id_verified=None)
        self.assertFalse(ok)

    def test_user_preference_stop_marca_revocacion_comercial(self):
        self.fake._tables["contacts"].append({
            "id": "c1", "tenant_id": TENANT, "phone": "573001234567",
            "consent_comercial_revoked_at": None,
        })
        ok = self.mod.persist_user_preference({
            "wa_id": "573001234567", "category": "marketing_messages", "preference": "stop",
        }, tenant_id_verified=TENANT)
        self.assertTrue(ok)
        self.assertIsNotNone(self.fake._tables["contacts"][0]["consent_comercial_revoked_at"])

    def test_user_preference_stop_es_idempotente(self):
        self.fake._tables["contacts"].append({
            "id": "c1", "tenant_id": TENANT, "phone": "573001234567",
            "consent_comercial_revoked_at": "2026-08-01T00:00:00+00:00",
        })
        ok = self.mod.persist_user_preference({
            "wa_id": "573001234567", "category": "marketing_messages", "preference": "stop",
        }, tenant_id_verified=TENANT)
        self.assertTrue(ok)
        # No pisa una revocación existente
        self.assertEqual(
            self.fake._tables["contacts"][0]["consent_comercial_revoked_at"],
            "2026-08-01T00:00:00+00:00",
        )

    def test_user_preference_resume_NO_muta(self):
        """El resume nativo de Meta no es consentimiento comercial (Ley 2300)."""
        self.fake._tables["contacts"].append({
            "id": "c1", "tenant_id": TENANT, "phone": "573001234567",
            "consent_comercial_revoked_at": "2026-08-01T00:00:00+00:00",
        })
        ok = self.mod.persist_user_preference({
            "wa_id": "573001234567", "category": "marketing_messages", "preference": "resume",
        }, tenant_id_verified=TENANT)
        self.assertTrue(ok)
        self.assertEqual(
            self.fake._tables["contacts"][0]["consent_comercial_revoked_at"],
            "2026-08-01T00:00:00+00:00",
        )

    def test_user_preference_shape_incompleto_no_muta(self):
        ok = self.mod.persist_user_preference(
            {"wa_id": None, "category": "marketing_messages", "preference": "stop"},
            tenant_id_verified=TENANT)
        self.assertFalse(ok)

    def test_account_alert_upsert_en_provider_health(self):
        ok = self.mod.persist_account_alert({
            "field": "account_alerts",
            "raw_value": {"event": "INCREASED_CAPABILITIES_DENIED"},
        }, tenant_id_verified=TENANT)
        self.assertTrue(ok)
        filas = self.fake._tables["tenant_provider_health"]
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["provider"], "whatsapp")
        self.assertEqual(filas[0]["metric"], "account_alert")
        self.assertEqual(filas[0]["value"], "INCREASED_CAPABILITIES_DENIED")

    def test_nuevos_estados_template_son_canonicos(self):
        for st in ("ARCHIVED", "UNARCHIVED", "DELETED", "IN_APPEAL", "LOCKED", "REINSTATED", "PENDING_DELETION"):
            self.assertIn(st, self.mod.VALID_TEMPLATE_STATUSES)
        # Enviabilidad según doc oficial: APPROVED + restaurados
        self.assertEqual(self.mod.SENDABLE_TEMPLATE_STATUSES, {"APPROVED", "REINSTATED", "UNARCHIVED"})

    def test_dispatcher_rutea_los_tres_campos(self):
        for et in ("template_category_update", "user_preference", "account_alert"):
            r = self.mod.handle_event({"event_type": et, "raw_value": {}}, tenant_id_verified=TENANT)
            self.assertIsNotNone(r, f"{et} debe tener handler (no None)")


if __name__ == "__main__":
    unittest.main()

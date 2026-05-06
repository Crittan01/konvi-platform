"""Tests `services/api/lib/compliance/` (rev. 105 Sem 2 F.9 / MA-7).

Cubre los 8 decoradores en escenarios allow + block + audit log.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_PATH = REPO_ROOT / "services" / "api" / "lib" / "compliance"


def _load_module(name: str, file_path: Path):
    pkg_name = "_test_compliance"
    if pkg_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            pkg_name, PKG_PATH / "__init__.py",
            submodule_search_locations=[str(PKG_PATH)],
        )
        pkg_mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = pkg_mod

    full_name = f"{pkg_name}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


errors = _load_module("errors", PKG_PATH / "errors.py")
decorators = _load_module("decorators", PKG_PATH / "decorators.py")


# ─── Fake Supabase para audit log ─────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]]):
        self._store = store

    def insert(self, payload: dict[str, Any]):
        self._payload = payload
        return self

    def execute(self):
        new_id = max((r.get("id", 0) for r in self._store), default=0) + 1
        row = dict(self._payload)
        row["id"] = new_id
        self._store.append(row)
        return SimpleNamespace(data=[row])


class _FakeSupabase:
    def __init__(self):
        self.audit_log: list[dict[str, Any]] = []

    def table(self, name: str):
        if name == "compliance_enforcement_log":
            return _FakeQuery(self.audit_log)
        raise AssertionError(f"Tabla no soportada en test: {name}")


# ─── 1. requires_consent ─────────────────────────────────────────────────────

class RequiresConsentTests(unittest.TestCase):
    def test_consent_ok_ejecuta_funcion(self):
        sb = _FakeSupabase()
        called = {"n": 0}

        @decorators.requires_consent(
            scope="whatsapp_marketing",
            consent_resolver=lambda *a, **kw: True,
            supabase_client=sb,
        )
        def send(tenant_id, contact_id):
            called["n"] += 1
            return "sent"

        result = send(tenant_id="A", contact_id="C")
        self.assertEqual(result, "sent")
        self.assertEqual(called["n"], 1)
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_consent_missing_levanta(self):
        sb = _FakeSupabase()

        @decorators.requires_consent(
            scope="whatsapp_marketing",
            consent_resolver=lambda *a, **kw: False,
            supabase_client=sb,
        )
        def send(tenant_id, contact_id):
            return "sent"

        with self.assertRaises(errors.ConsentMissingError):
            send(tenant_id="A", contact_id="C")
        self.assertEqual(sb.audit_log[-1]["outcome"], "blocked")
        self.assertIn("scope=whatsapp_marketing", sb.audit_log[-1]["blocked_reason"])

    def test_funciona_async(self):
        sb = _FakeSupabase()

        @decorators.requires_consent(
            scope="x", consent_resolver=lambda *a, **kw: True,
            supabase_client=sb,
        )
        async def send(tenant_id):
            return "async-sent"

        result = asyncio.run(send(tenant_id="A"))
        self.assertEqual(result, "async-sent")


# ─── 2. enforce_meta_24h_window ──────────────────────────────────────────────

class MetaWindowTests(unittest.TestCase):
    def test_dentro_de_csw_pasa(self):
        sb = _FakeSupabase()
        recent = datetime.now(timezone.utc) - timedelta(hours=2)

        @decorators.enforce_meta_24h_window(
            last_inbound_resolver=lambda *a, **kw: recent,
            supabase_client=sb,
        )
        def send(tenant_id):
            return "sent"

        send(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_fuera_csw_sin_template_levanta(self):
        sb = _FakeSupabase()
        old = datetime.now(timezone.utc) - timedelta(hours=30)

        @decorators.enforce_meta_24h_window(
            last_inbound_resolver=lambda *a, **kw: old,
            is_template_resolver=lambda *a, **kw: False,
            supabase_client=sb,
        )
        def send(tenant_id):
            return "sent"

        with self.assertRaises(errors.MetaWindowExpiredError):
            send(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["outcome"], "blocked")

    def test_fuera_csw_con_template_pasa(self):
        sb = _FakeSupabase()
        old = datetime.now(timezone.utc) - timedelta(hours=30)

        @decorators.enforce_meta_24h_window(
            last_inbound_resolver=lambda *a, **kw: old,
            is_template_resolver=lambda *a, **kw: True,
            supabase_client=sb,
        )
        def send(tenant_id):
            return "template-sent"

        result = send(tenant_id="A")
        self.assertEqual(result, "template-sent")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")
        self.assertTrue(sb.audit_log[-1]["metadata"]["is_template"])

    def test_sin_inbound_history_levanta(self):
        sb = _FakeSupabase()

        @decorators.enforce_meta_24h_window(
            last_inbound_resolver=lambda *a, **kw: None,
            is_template_resolver=lambda *a, **kw: False,
            supabase_client=sb,
        )
        def send(tenant_id):
            return "sent"

        with self.assertRaises(errors.MetaWindowExpiredError):
            send(tenant_id="A")


# ─── 3. enforce_csw_template_only_outside_24h ─────────────────────────────────

class CSWTemplateTests(unittest.TestCase):
    def test_dentro_csw_libre_pasa(self):
        sb = _FakeSupabase()
        recent = datetime.now(timezone.utc) - timedelta(hours=1)

        @decorators.enforce_csw_template_only_outside_24h(
            last_inbound_resolver=lambda *a, **kw: recent,
            is_template_resolver=lambda *a, **kw: False,
            supabase_client=sb,
        )
        def send(tenant_id):
            return "sent"

        send(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_fuera_csw_sin_template_levanta(self):
        sb = _FakeSupabase()
        old = datetime.now(timezone.utc) - timedelta(hours=30)

        @decorators.enforce_csw_template_only_outside_24h(
            last_inbound_resolver=lambda *a, **kw: old,
            is_template_resolver=lambda *a, **kw: False,
            supabase_client=sb,
        )
        def send(tenant_id):
            return "sent"

        with self.assertRaises(errors.CSWTemplateRequiredError):
            send(tenant_id="A")


# ─── 4. audit_data_access ────────────────────────────────────────────────────

class AuditDataAccessTests(unittest.TestCase):
    def test_no_bloquea_solo_loguea(self):
        sb = _FakeSupabase()

        @decorators.audit_data_access(
            reason="SAR_response",
            pii_fields_resolver=lambda *a, **kw: ["phone", "address"],
            supabase_client=sb,
        )
        def export(tenant_id, contact_id):
            return {"phone": "57...", "address": "Cra 7"}

        result = export(tenant_id="A", contact_id="C")
        self.assertEqual(result["phone"], "57...")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")
        self.assertEqual(sb.audit_log[-1]["metadata"]["reason"], "SAR_response")
        self.assertEqual(
            sb.audit_log[-1]["metadata"]["pii_fields"], ["phone", "address"]
        )

    def test_pii_fields_resolver_falla_no_rompe(self):
        sb = _FakeSupabase()

        @decorators.audit_data_access(
            reason="x",
            pii_fields_resolver=lambda *a, **kw: 1 / 0,
            supabase_client=sb,
        )
        def f(tenant_id):
            return "ok"

        f(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["metadata"]["pii_fields"], [])


# ─── 5. scoped_to_country ────────────────────────────────────────────────────

class ScopedToCountryTests(unittest.TestCase):
    def test_pais_permitido_pasa(self):
        sb = _FakeSupabase()

        @decorators.scoped_to_country(allowed=("CO",), supabase_client=sb)
        def quote(tenant_id, country):
            return "ok"

        quote(tenant_id="A", country="CO")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_pais_no_permitido_levanta(self):
        sb = _FakeSupabase()

        @decorators.scoped_to_country(allowed=("CO",), supabase_client=sb)
        def quote(tenant_id, country):
            return "ok"

        with self.assertRaises(errors.CountryScopeError):
            quote(tenant_id="A", country="MX")
        self.assertEqual(sb.audit_log[-1]["outcome"], "blocked")
        self.assertEqual(sb.audit_log[-1]["metadata"]["received"], "MX")

    def test_country_resolver_custom(self):
        sb = _FakeSupabase()

        @decorators.scoped_to_country(
            allowed=("CO",),
            country_resolver=lambda *a, **kw: kw.get("payload", {}).get("dest_country"),
            supabase_client=sb,
        )
        def quote(tenant_id, payload):
            return "ok"

        quote(tenant_id="A", payload={"dest_country": "CO"})
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")


# ─── 6. requires_verified_dkim_spf ────────────────────────────────────────────

class DkimSpfTests(unittest.TestCase):
    def test_ambos_ok_pasa(self):
        sb = _FakeSupabase()

        @decorators.requires_verified_dkim_spf(
            domain_status_resolver=lambda *a, **kw: {"spf": True, "dkim": True},
            supabase_client=sb,
        )
        def send_email(tenant_id):
            return "sent"

        send_email(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_spf_fail_levanta(self):
        sb = _FakeSupabase()

        @decorators.requires_verified_dkim_spf(
            domain_status_resolver=lambda *a, **kw: {"spf": False, "dkim": True},
            supabase_client=sb,
        )
        def send_email(tenant_id):
            return "sent"

        with self.assertRaises(errors.DKIMSPFNotVerifiedError):
            send_email(tenant_id="A")

    def test_dkim_fail_levanta(self):
        sb = _FakeSupabase()

        @decorators.requires_verified_dkim_spf(
            domain_status_resolver=lambda *a, **kw: {"spf": True, "dkim": False},
            supabase_client=sb,
        )
        def send_email(tenant_id):
            return "sent"

        with self.assertRaises(errors.DKIMSPFNotVerifiedError):
            send_email(tenant_id="A")


# ─── 7. enforce_pci_scope ─────────────────────────────────────────────────────

class PciScopeTests(unittest.TestCase):
    def test_sin_card_data_pasa(self):
        sb = _FakeSupabase()

        @decorators.enforce_pci_scope(
            contains_card_data_resolver=lambda *a, **kw: False,
            supabase_client=sb,
        )
        def f(tenant_id):
            return "ok"

        f(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_card_data_no_compliant_levanta(self):
        sb = _FakeSupabase()

        @decorators.enforce_pci_scope(
            contains_card_data_resolver=lambda *a, **kw: True,
            pci_compliant_path=False,
            supabase_client=sb,
        )
        def f(tenant_id):
            return "ok"

        with self.assertRaises(errors.PCIScopeViolationError):
            f(tenant_id="A")

    def test_card_data_pci_compliant_pasa(self):
        sb = _FakeSupabase()

        @decorators.enforce_pci_scope(
            contains_card_data_resolver=lambda *a, **kw: True,
            pci_compliant_path=True,
            supabase_client=sb,
        )
        def f(tenant_id):
            return "ok"

        f(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")


# ─── 8. enforce_meli_cbt_response_sla ─────────────────────────────────────────

class MeliCbtSlaTests(unittest.TestCase):
    def test_dentro_sla_pasa(self):
        sb = _FakeSupabase()

        @decorators.enforce_meli_cbt_response_sla(
            question_age_hours_resolver=lambda *a, **kw: 3.0,
            sla_hours=8.0,
            supabase_client=sb,
        )
        def reply(tenant_id):
            return "replied"

        reply(tenant_id="A")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_excede_sla_advisory_no_levanta(self):
        sb = _FakeSupabase()

        @decorators.enforce_meli_cbt_response_sla(
            question_age_hours_resolver=lambda *a, **kw: 10.0,
            sla_hours=8.0,
            enforce_strict=False,
            supabase_client=sb,
        )
        def reply(tenant_id):
            return "replied"

        result = reply(tenant_id="A")
        self.assertEqual(result, "replied")
        # Audit log con allowed (advisory mode).
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_excede_sla_strict_levanta(self):
        sb = _FakeSupabase()

        @decorators.enforce_meli_cbt_response_sla(
            question_age_hours_resolver=lambda *a, **kw: 10.0,
            sla_hours=8.0,
            enforce_strict=True,
            supabase_client=sb,
        )
        def reply(tenant_id):
            return "replied"

        with self.assertRaises(errors.MeliCbtSlaViolationError):
            reply(tenant_id="A")


# ─── Resolución de args ───────────────────────────────────────────────────────

class ArgResolutionTests(unittest.TestCase):
    def test_kwarg_funciona(self):
        sb = _FakeSupabase()

        @decorators.scoped_to_country(allowed=("CO",), supabase_client=sb)
        def f(tenant_id, country):
            return "ok"

        f(tenant_id="A", country="CO")
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_attr_de_objeto_funciona(self):
        sb = _FakeSupabase()

        @decorators.scoped_to_country(allowed=("CO",), supabase_client=sb)
        def f(payload):
            return "ok"

        payload = SimpleNamespace(tenant_id="A", country="CO")
        f(payload)
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")

    def test_dict_arg_funciona(self):
        sb = _FakeSupabase()

        @decorators.scoped_to_country(allowed=("CO",), supabase_client=sb)
        def f(payload):
            return "ok"

        f({"tenant_id": "A", "country": "CO"})
        self.assertEqual(sb.audit_log[-1]["outcome"], "allowed")


if __name__ == "__main__":
    unittest.main()

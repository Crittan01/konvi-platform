"""A9 finiquito — Contactos: shipping_phone paridad + audit PII (Habeas Data Art. 9).

El API router de contactos tenía @audit_log (acción de entidad) + idempotency +
RBAC, pero NO escribía pii_access_log (audit field-level del WRITE de PII) — mismo
gap legal que A5 cerró en el bot, pero en el path UI/API. Además ContactCreate/
ContactPatch no tenían shipping_phone (la UI lo escribía directo, drift).

Fix: shipping_phone en ambos modelos + log_pii_access en create/patch con el actor
del JWT, purpose='contact_create'/'contact_update', fields_accessed=<PII escritos>.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from pydantic import ValidationError  # noqa: E402
from routers import contacts as contacts_mod  # noqa: E402
from routers.contacts import ContactCreate, ContactPatch, create_contact, patch_contact  # noqa: E402


class ShippingPhoneModelTests(unittest.TestCase):
    def test_create_accepts_shipping_phone(self):
        c = ContactCreate(phone="+573001112233", shipping_phone="+573009998877")
        self.assertEqual(c.shipping_phone, "+573009998877")

    def test_patch_accepts_shipping_phone(self):
        p = ContactPatch(shipping_phone="3009998877")
        self.assertEqual(p.shipping_phone, "3009998877")

    def test_invalid_shipping_phone_rejected(self):
        with self.assertRaises(ValidationError):
            ContactCreate(phone="+573001112233", shipping_phone="abc")

    def test_shipping_phone_optional(self):
        c = ContactCreate(phone="+573001112233")
        self.assertIsNone(c.shipping_phone)


class _FakeQuery:
    def __init__(self, name, sink):
        self.name = name
        self.sink = sink
        self._payload = None
        self._mode = None

    def insert(self, data):
        self.sink.append((self.name, "insert", data))
        self._mode, self._payload = "insert", data
        return self

    def update(self, data):
        self._mode, self._payload = "update", data
        return self

    def select(self, *a, **k):
        self._mode = "select"
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def maybe_single(self):  # F19: patch_contact usa maybe_single
        return self

    def execute(self):
        if self.name == "contacts" and self._mode == "insert":
            return SimpleNamespace(data=[{"id": "contact-new", **(self._payload or {})}])
        if self.name == "contacts" and self._mode == "update":
            self.sink.append((self.name, "update", self._payload))
            return SimpleNamespace(data=[{"id": "contact-1", **(self._payload or {})}])
        if self.name == "contacts" and self._mode == "select":
            return SimpleNamespace(data={"id": "contact-1", "consent_given": True, "consent_date": "2026-01-01"})
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self):
        self.ops = []

    def table(self, name):
        return _FakeQuery(name, self.ops)


def _fake_request():
    return SimpleNamespace(
        client=SimpleNamespace(host="1.2.3.4"),
        headers={"user-agent": "pytest"},
    )


def _pii_inserts(sb):
    return [d for (n, op, d) in sb.ops if n == "pii_access_log" and op == "insert"]


class PiiAuditEndpointTests(unittest.TestCase):
    def setUp(self):
        # Neutralizar idempotency (no DB) — begin retorna (session, no-replay).
        self._patchers = [
            patch.object(contacts_mod, "begin_idempotency", return_value=("sess", None)),
            patch.object(contacts_mod, "finalize_idempotency", return_value=None),
            patch.object(contacts_mod, "abort_idempotency", return_value=None),
            patch.object(contacts_mod, "_extract_user_info", return_value=("uid-1", "op@kaiu.co")),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def test_create_contact_logs_pii_access(self):
        sb = _FakeSupabase()
        contact = ContactCreate(
            phone="+573001112233", name="Ana", email="ana@x.com",
            shipping_phone="+573009998877",
        )
        body = create_contact(
            contact=contact, request=_fake_request(),
            tenant_id="tenant-A", supabase=sb, _role="manager", _rl=None,
        )
        self.assertEqual(body["id"], "contact-new")
        pii = _pii_inserts(sb)
        self.assertEqual(len(pii), 1)
        a = pii[0]
        self.assertEqual(a["purpose"], "contact_create")
        self.assertEqual(a["accessed_by"], "user:op@kaiu.co")
        self.assertEqual(a["tenant_id"], "tenant-A")
        self.assertEqual(a["contact_id"], "contact-new")
        # Campos PII escritos auditados (incluye shipping_phone).
        for f in ("name", "email", "phone", "shipping_phone"):
            self.assertIn(f, a["fields_accessed"])

    def test_patch_contact_logs_pii_access(self):
        sb = _FakeSupabase()
        patch_body = ContactPatch(name="Ana Maria", shipping_phone="+573001234567")
        body = patch_contact(
            contact_id="contact-1", patch=patch_body, request=_fake_request(),
            tenant_id="tenant-A", supabase=sb, _role="manager", _rl=None,
        )
        self.assertEqual(body["id"], "contact-1")
        pii = _pii_inserts(sb)
        self.assertEqual(len(pii), 1)
        self.assertEqual(pii[0]["purpose"], "contact_update")
        self.assertIn("name", pii[0]["fields_accessed"])
        self.assertIn("shipping_phone", pii[0]["fields_accessed"])

    def test_create_persists_consent_channel_and_actor(self):
        # A9: consent_channel (de la UI) + consent_actor_email (del JWT) se
        # persisten cuando consent_given=True.
        sb = _FakeSupabase()
        contact = ContactCreate(
            phone="+573001112233", name="Ana",
            consent_given=True, consent_source="manual_console",
            consent_channel="dashboard_console",
        )
        create_contact(
            contact=contact, request=_fake_request(),
            tenant_id="tenant-A", supabase=sb, _role="manager", _rl=None,
        )
        inserts = [d for (n, op, d) in sb.ops if n == "contacts" and op == "insert"]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0]["consent_channel"], "dashboard_console")
        self.assertEqual(inserts[0]["consent_actor_email"], "op@kaiu.co")

    def test_create_no_consent_nulls_channel_actor(self):
        # Sin consent → consent_channel/actor null (no se estampan).
        sb = _FakeSupabase()
        contact = ContactCreate(phone="+573001112233", consent_channel="dashboard_console")
        create_contact(
            contact=contact, request=_fake_request(),
            tenant_id="tenant-A", supabase=sb, _role="manager", _rl=None,
        )
        inserts = [d for (n, op, d) in sb.ops if n == "contacts" and op == "insert"]
        self.assertIsNone(inserts[0]["consent_channel"])
        self.assertIsNone(inserts[0]["consent_actor_email"])

    def test_patch_non_pii_only_no_audit(self):
        # Patch de solo 'notes' (no PII de contenido) → no pii_access_log.
        sb = _FakeSupabase()
        body = patch_contact(
            contact_id="contact-1", patch=ContactPatch(notes="recordar llamar"),
            request=_fake_request(), tenant_id="tenant-A", supabase=sb,
            _role="manager", _rl=None,
        )
        self.assertEqual(body["id"], "contact-1")
        self.assertEqual(len(_pii_inserts(sb)), 0)


if __name__ == "__main__":
    unittest.main()

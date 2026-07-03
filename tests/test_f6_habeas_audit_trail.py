"""F6 — audit-trail Habeas Data en el path agéntico (Ley 1581).

Los gates del bot (DSR "borren mis datos" + menor autodeclarado) escalan a humano pero no dejaban
registro en consent_audit_log (el registro canónico para la SIC). `_log_habeas_event` cierra el gap:
inserta el evento (event ∈ {data_rights_request, minor_detected}, añadidos al CHECK por la migración
20260702210000), resolviendo contact_id de la conversación. Best-effort: nunca bloquea la escalación.
"""
import os
import sys
import types
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.dispatcher import _log_habeas_event  # noqa: E402


class _FakeSb:
    """Fake supabase: resuelve contact_id en el SELECT a conversations y captura el INSERT
    a consent_audit_log. `fail_insert` simula un fallo de DB para probar el best-effort."""

    def __init__(self, *, contact_id="contact-1", fail_insert=False):
        self._contact_id = contact_id
        self._fail_insert = fail_insert
        self.inserts = []
        self._tbl = None
        self._pending = None

    def table(self, name):
        self._tbl = name
        self._pending = None
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def limit(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def insert(self, data):
        self._pending = ("insert", self._tbl, data)
        return self

    def execute(self):
        if self._pending and self._pending[0] == "insert":
            if self._fail_insert:
                raise Exception("insert boom")
            self.inserts.append(self._pending)
            return types.SimpleNamespace(data=[{}])
        # F2: _resolve_contact_id → conversations.customer_phone → contacts.phone.
        if self._tbl == "conversations":
            return types.SimpleNamespace(data=[{"customer_phone": "573001112222"}])
        if self._tbl == "contacts":
            return types.SimpleNamespace(
                data=[{"id": self._contact_id}] if self._contact_id is not None else []
            )
        return types.SimpleNamespace(data=[])


class HabeasAuditTrailTests(unittest.TestCase):
    def test_inserts_event_with_resolved_contact_id(self):
        sb = _FakeSb(contact_id="contact-42")
        _log_habeas_event(
            sb, tenant_id="t-1", conversation_id="conv-1",
            event="data_rights_request",
            evidence={"message_text": "borren mis datos", "gate": "dsr"},
        )
        self.assertEqual(len(sb.inserts), 1)
        _, tbl, row = sb.inserts[0]
        self.assertEqual(tbl, "consent_audit_log")
        self.assertEqual(row["event"], "data_rights_request")
        self.assertEqual(row["tenant_id"], "t-1")
        self.assertEqual(row["conversation_id"], "conv-1")
        self.assertEqual(row["source"], "whatsapp")
        self.assertEqual(row["contact_id"], "contact-42")
        self.assertEqual(row["evidence"]["gate"], "dsr")

    def test_minor_detected_event(self):
        sb = _FakeSb()
        _log_habeas_event(
            sb, tenant_id="t-1", conversation_id="conv-1",
            event="minor_detected",
            evidence={"legal_basis": "Decreto 1377/2013 Art. 7"},
        )
        self.assertEqual(sb.inserts[0][2]["event"], "minor_detected")

    def test_contact_id_none_when_lookup_empty(self):
        sb = _FakeSb(contact_id=None)
        _log_habeas_event(
            sb, tenant_id="t-1", conversation_id="conv-1",
            event="data_rights_request", evidence={},
        )
        self.assertIsNone(sb.inserts[0][2]["contact_id"])

    def test_best_effort_does_not_raise_on_db_failure(self):
        sb = _FakeSb(fail_insert=True)
        # No debe propagar: la escalación (side-effect crítico) no puede depender del audit log.
        _log_habeas_event(
            sb, tenant_id="t-1", conversation_id="conv-1",
            event="minor_detected", evidence={},
        )
        self.assertEqual(sb.inserts, [])


if __name__ == "__main__":
    unittest.main()

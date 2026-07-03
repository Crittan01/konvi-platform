"""F107/F121 — los endpoints de consent muertos no deben reaparecer.

POST /contacts/{id}/consent y /contacts/{id}/reactivate-consent eran código muerto
(0 callers HTTP): el registro de consent vive en el bot (RecordConsentTool) y en la
web (reactivateConsentAction, server action). El endpoint reactivate-consent además
double-contaba en vw_consent_events_unified (audit_log del decorator +
consent_audit_log) → su remoción cierra F121.

Guard: falla si alguien reintroduce estas rutas muertas.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers import contacts  # noqa: E402


class DeadConsentEndpointsRemovedTests(unittest.TestCase):
    def test_consent_routes_absent(self):
        paths = {r.path for r in contacts.router.routes}
        self.assertNotIn("/{contact_id}/consent", paths)
        self.assertNotIn("/{contact_id}/reactivate-consent", paths)

    def test_dead_handlers_absent(self):
        # Los handlers muertos ya no existen como atributos del módulo.
        self.assertFalse(hasattr(contacts, "record_consent"))
        self.assertFalse(hasattr(contacts, "reactivate_consent"))

    def test_live_purge_endpoint_still_present(self):
        # Sanidad: la sección siguiente (purge) sigue registrada (no borré de más).
        paths = {r.path for r in contacts.router.routes}
        self.assertIn("/{contact_id}/purge", paths)


if __name__ == "__main__":
    unittest.main()

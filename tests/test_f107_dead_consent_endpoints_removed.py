"""F107/F121 — guard de los endpoints de consent.

Historia:
  • POST /contacts/{id}/consent: código muerto (0 callers) → ELIMINADO. Sigue fuera.
  • POST /contacts/{id}/reactivate-consent: se ELIMINÓ en F107/F121 porque (a) era
    código muerto y (b) double-contaba en vw_consent_events_unified (audit_log del
    decorator @audit_log + consent_audit_log).

Decisión F2 (aprobada) — Módulo Contactos:
  reactivar consent es una mutación de dato de consentimiento (sensible Habeas
  Data) que debe pasar por el pipeline auditado del módulo (RL_WRITE + idempotency
  + consent_audit_log), NO por una escritura DIRECTA con admin client desde el
  server action. Por eso el endpoint /reactivate-consent VUELVE, pero ahora:
    • lo consume reactivateConsentAction (ya NO es código muerto), y
    • NO usa el decorator @audit_log → escribe SOLO consent_audit_log, de modo que
      vw_consent_events_unified sigue contando un único evento (F121 preservado).

Guards:
  • /consent sigue ausente (no reintroducir el endpoint muerto).
  • /reactivate-consent presente (contrato F2).
  • reactivate_consent NO decorado con @audit_log (single-count F121).
  • purge sigue presente (no borré de más).
"""
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers import contacts  # noqa: E402

CONTACTS_SRC = Path(
    "/home/ansible/workspaces/konvi-platform/services/api/routers/contacts.py"
).read_text()


class DeadConsentEndpointsTests(unittest.TestCase):
    def test_dead_consent_route_absent(self):
        # El endpoint muerto POST /{id}/consent NO debe reaparecer.
        paths = {r.path for r in contacts.router.routes}
        self.assertNotIn("/{contact_id}/consent", paths)
        self.assertFalse(hasattr(contacts, "record_consent"))

    def test_reactivate_consent_route_present_f2(self):
        # Decisión F2: el endpoint reactivate-consent vuelve, ahora auditado.
        paths = {r.path for r in contacts.router.routes}
        self.assertIn("/{contact_id}/reactivate-consent", paths)
        self.assertTrue(hasattr(contacts, "reactivate_consent"))

    def test_reactivate_consent_not_audit_log_decorated(self):
        # F121 single-count: reactivate_consent NO puede usar @audit_log (que
        # escribe en audit_log y duplicaría el evento en la vista unificada). El
        # registro canónico es el insert directo en consent_audit_log.
        m = re.search(
            r"((?:@[^\n]+\n)*)\s*async def reactivate_consent\(",
            CONTACTS_SRC,
        )
        self.assertIsNotNone(m, "no se encontró la definición de reactivate_consent")
        decorators = m.group(1)
        self.assertNotIn("@audit_log", decorators,
                         "reactivate_consent NO debe usar @audit_log (F121 double-count)")
        # Debe registrar en consent_audit_log (audit append-only del módulo).
        self.assertIn("consent_audit_log", CONTACTS_SRC)

    def test_live_purge_endpoint_still_present(self):
        paths = {r.path for r in contacts.router.routes}
        self.assertIn("/{contact_id}/purge", paths)


if __name__ == "__main__":
    unittest.main()

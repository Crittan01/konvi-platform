"""Rev. 98 + 99 — Tests de documentación legal y migración tenant_legal_acceptance.

Cobertura:
  • docs/legal/* existen y tienen secciones obligatorias (Ley 1581).
  • ADR-0003 documenta las decisiones técnicas clave.
  • Migración tenant_legal_acceptance: append-only, RLS, indexes.

Tests estructurales (no E2E con DB).
"""
import os
import unittest

DOCS_DIR = "/home/ansible/workspaces/commerce-ops-platform/docs"
LEGAL_DIR = os.path.join(DOCS_DIR, "legal")
ADR_DIR = os.path.join(DOCS_DIR, "adr")
MIGRATION_PATH = (
    "/home/ansible/workspaces/commerce-ops-platform/supabase/migrations/"
    "20260507010000_tenant_legal_acceptance.sql"
)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class LegalDocsExistTests(unittest.TestCase):

    def test_dpa_exists(self):
        self.assertTrue(os.path.exists(os.path.join(LEGAL_DIR, "dpa.md")))

    def test_privacy_policy_exists(self):
        self.assertTrue(os.path.exists(
            os.path.join(LEGAL_DIR, "privacy-policy.md")
        ))

    def test_subprocessors_exists(self):
        self.assertTrue(os.path.exists(
            os.path.join(LEGAL_DIR, "subprocessors.md")
        ))

    def test_incident_response_exists(self):
        self.assertTrue(os.path.exists(
            os.path.join(LEGAL_DIR, "incident-response.md")
        ))

    def test_roles_exists(self):
        self.assertTrue(os.path.exists(os.path.join(LEGAL_DIR, "roles.md")))


class DpaContentTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dpa = _read(os.path.join(LEGAL_DIR, "dpa.md"))

    def test_references_ley_1581(self):
        self.assertIn("1581", self.dpa)

    def test_distinguishes_responsable_encargado(self):
        self.assertIn("Responsable", self.dpa)
        self.assertIn("Encargado", self.dpa)

    def test_lists_data_categories(self):
        for cat in ("Identificación", "Contacto", "Transaccional", "Audit"):
            self.assertIn(cat, self.dpa)

    def test_includes_subprocessors_reference(self):
        self.assertIn("subprocessors", self.dpa.lower())

    def test_includes_termination_clause(self):
        self.assertIn("Terminación", self.dpa)


class PrivacyPolicyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.privacy = _read(os.path.join(LEGAL_DIR, "privacy-policy.md"))

    def test_references_titular_rights(self):
        for art in ("Art. 14", "Art. 15", "Art. 16", "Art. 19"):
            self.assertIn(art, self.privacy)

    def test_mentions_sic(self):
        self.assertIn("SIC", self.privacy)

    def test_lists_subprocessors(self):
        for sub in ("Wompi", "WhatsApp", "Supabase", "Envia"):
            self.assertIn(sub, self.privacy)


class SubprocessorsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.subs = _read(os.path.join(LEGAL_DIR, "subprocessors.md"))

    def test_lists_core_subprocessors(self):
        for sub in ("Supabase", "Meta", "Wompi", "Envia.com",
                    "Resend", "Render"):
            self.assertIn(sub, self.subs)

    def test_specifies_jurisdictions(self):
        self.assertIn("Colombia", self.subs)
        self.assertIn("USA", self.subs)

    def test_includes_change_notification_policy(self):
        self.assertIn("30", self.subs)  # 30 días notice


class IncidentResponseTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ir = _read(os.path.join(LEGAL_DIR, "incident-response.md"))

    def test_severity_levels(self):
        for sev in ("P0", "P1", "P2", "P3"):
            self.assertIn(sev, self.ir)

    def test_72h_notification_window(self):
        self.assertIn("72 h", self.ir)

    def test_sic_contact_listed(self):
        self.assertIn("sic.gov.co", self.ir)

    def test_response_phases(self):
        # 6 fases: detección, contención, evaluación, notificación, remediación, postmortem.
        for phase in ("Detección", "Contención", "Evaluación",
                      "Notificación", "Remediación", "Postmortem"):
            self.assertIn(phase, self.ir)


class RolesDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.roles = _read(os.path.join(LEGAL_DIR, "roles.md"))

    def test_defines_three_legal_roles(self):
        for role in ("Titular", "Responsable", "Encargado"):
            self.assertIn(role, self.roles)

    def test_links_responsable_to_tenant(self):
        self.assertIn("tenant", self.roles.lower())

    def test_lists_responsable_obligations(self):
        # Min. obligaciones: consent, finalidad, derechos, incidentes.
        self.assertIn("consentimiento", self.roles.lower())
        self.assertIn("supresión", self.roles.lower())
        # Audit obligation: notificar incidentes
        self.assertIn("incidente", self.roles.lower())


class Adr0003Tests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.adr = _read(os.path.join(ADR_DIR, "0003-habeas-data-compliance-strategy.md"))

    def test_status_accepted(self):
        self.assertIn("Accepted", self.adr)

    def test_lists_11_gaps(self):
        # ADR debe enumerar los 11 gaps que detonaron el plan.
        for n in range(1, 12):
            # E.g., "1.", "2.", ..., "11."
            self.assertRegex(self.adr, rf"\b{n}\.")

    def test_documents_key_decisions(self):
        for d in ("D1", "D2", "D3", "D4", "D5", "D6", "D7"):
            self.assertIn(d, self.adr)

    def test_lists_alternatives_considered(self):
        for a in ("A1", "A2", "A3", "A4"):
            self.assertIn(a, self.adr)

    def test_lists_followups(self):
        # Open issues numerados.
        for f in ("F1", "F2", "F3", "F4", "F5", "F6"):
            self.assertIn(f, self.adr)


class TenantLegalAcceptanceMigrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = _read(MIGRATION_PATH)
        cls.sql_lower = cls.sql.lower()

    def test_table_created(self):
        self.assertIn("create table if not exists public.tenant_legal_acceptance",
                      self.sql_lower)

    def test_append_only_via_triggers(self):
        # UPDATE y DELETE bloqueados.
        self.assertIn("trg_block_legal_acceptance_update", self.sql_lower)
        self.assertIn("trg_block_legal_acceptance_delete", self.sql_lower)
        self.assertIn("append-only", self.sql.lower())

    def test_unique_constraint_per_version(self):
        # Mismo tenant no puede aceptar la misma versión 2 veces.
        self.assertIn("uq_tenant_legal_acceptance_version", self.sql_lower)

    def test_records_required_audit_fields(self):
        for col in ("accepted_by_user_id", "accepted_by_email",
                    "ip_address", "user_agent", "accepted_at"):
            self.assertIn(col, self.sql_lower)

    def test_supports_multiple_document_types(self):
        # document_id distingue dpa / privacy_policy / subprocessors.
        self.assertIn("document_id", self.sql_lower)
        self.assertIn("document_version", self.sql_lower)

    def test_rls_enabled(self):
        self.assertRegex(
            self.sql,
            r"ALTER\s+TABLE\s+public\.tenant_legal_acceptance\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY",
        )

    def test_only_owner_or_manager_can_insert(self):
        self.assertIn("'owner'", self.sql)
        self.assertIn("'manager'", self.sql)


if __name__ == "__main__":
    unittest.main()

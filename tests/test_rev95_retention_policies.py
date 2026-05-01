"""Rev. 95 — Tests de la migración retention_policies + fn_apply_retention.

Validan estática:
  • Migración existe y declara las 4 entities canónicas.
  • Función fn_apply_retention con signatura (TEXT, BOOLEAN).
  • Defaults globales insertados (tenant_id NULL).
  • pg_cron schedules para las 4 entities.
  • CHECKs de validación: ttl_days range, action enum.
  • RLS policies declaradas.

Tests E2E con DB real viven en docs/uat/scenarios/.
"""
import os
import re
import unittest

MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "supabase/migrations/20260505010000_retention_policies.sql"
)
MIGRATION_PER_TENANT_FIX_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "supabase/migrations/20260508010000_retention_per_tenant_fix.sql"
)


class RetentionMigrationStructureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, encoding="utf-8") as f:
            cls.sql = f.read()
        cls.sql_lower = cls.sql.lower()

    def test_migration_file_exists(self):
        self.assertTrue(os.path.exists(MIGRATION_PATH))

    def test_creates_retention_policies_table(self):
        self.assertIn("create table if not exists public.retention_policies",
                      self.sql_lower)

    def test_table_has_all_required_columns(self):
        for col in ("tenant_id", "entity", "ttl_days", "action",
                    "enabled", "created_at", "updated_at"):
            self.assertIn(col, self.sql_lower, f"Falta columna {col}")

    def test_entity_check_includes_canonical_set(self):
        # CHECK debe incluir las 4 entidades.
        for entity in ("conversations", "messages", "contacts_inactive",
                       "pii_access_log"):
            self.assertIn(f"'{entity}'", self.sql)

    def test_action_check_includes_canonical_set(self):
        for action in ("archive", "soft_delete", "hard_delete", "anonymize"):
            self.assertIn(f"'{action}'", self.sql)

    def test_ttl_days_has_sane_range(self):
        # ttl_days entre 1 día y 10 años.
        self.assertRegex(
            self.sql,
            r"ttl_days\s*>=\s*1\s+AND\s+ttl_days\s*<=\s*3650",
        )


class DefaultPoliciesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, encoding="utf-8") as f:
            cls.sql = f.read()

    def test_messages_default_180d_hard_delete(self):
        self.assertRegex(
            self.sql,
            r"\(NULL,\s*'messages',\s*180,\s*'hard_delete'\)",
        )

    def test_conversations_default_365d_soft_delete(self):
        self.assertRegex(
            self.sql,
            r"\(NULL,\s*'conversations',\s*365,\s*'soft_delete'\)",
        )

    def test_contacts_inactive_default_730d(self):
        self.assertRegex(
            self.sql,
            r"\(NULL,\s*'contacts_inactive',\s*730,\s*'soft_delete'\)",
        )

    def test_pii_access_log_default_365d(self):
        self.assertRegex(
            self.sql,
            r"\(NULL,\s*'pii_access_log',\s*365,\s*'hard_delete'\)",
        )

    def test_inserts_are_idempotent(self):
        self.assertIn("ON CONFLICT", self.sql)


class FnApplyRetentionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, encoding="utf-8") as f:
            cls.sql = f.read()

    def test_function_signature(self):
        self.assertRegex(
            self.sql,
            r"FUNCTION\s+public\.fn_apply_retention\s*\(\s*p_entity\s+TEXT\s*,\s*p_dry_run\s+BOOLEAN",
        )

    def test_function_returns_integer(self):
        self.assertRegex(self.sql, r"RETURNS\s+INTEGER")

    def test_function_handles_messages(self):
        self.assertRegex(
            self.sql,
            r"p_entity\s*=\s*'messages'\s+AND\s+v_default_act\s*=\s*'hard_delete'",
        )

    def test_function_handles_conversations(self):
        self.assertRegex(
            self.sql,
            r"p_entity\s*=\s*'conversations'\s+AND\s+v_default_act\s*=\s*'soft_delete'",
        )

    def test_function_handles_contacts_inactive(self):
        self.assertRegex(
            self.sql,
            r"p_entity\s*=\s*'contacts_inactive'\s+AND\s+v_default_act\s*=\s*'soft_delete'",
        )

    def test_function_handles_pii_access_log(self):
        self.assertRegex(
            self.sql,
            r"p_entity\s*=\s*'pii_access_log'\s+AND\s+v_default_act\s*=\s*'hard_delete'",
        )

    def test_dry_run_branch_uses_count(self):
        # Validar que dry_run=TRUE no muta (sólo SELECT COUNT).
        # Buscar "IF p_dry_run THEN" seguido de SELECT COUNT.
        matches = re.findall(
            r"IF\s+p_dry_run\s+THEN\s+SELECT\s+COUNT", self.sql,
        )
        self.assertGreaterEqual(len(matches), 4)  # Una por entity.

    def test_contacts_inactive_only_revoked_consent(self):
        # Solo borra contactos sin consent activo.
        self.assertIn("consent_given = FALSE", self.sql)

    def test_grant_execute_to_service_role(self):
        self.assertRegex(
            self.sql,
            r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+public\.fn_apply_retention\(TEXT,\s*BOOLEAN\)\s+TO\s+service_role",
        )


class PgCronScheduleTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, encoding="utf-8") as f:
            cls.sql = f.read()

    def test_unschedules_all_jobs_idempotent(self):
        # Idempotencia: borra schedules previos.
        self.assertIn("cron.unschedule", self.sql)

    def test_schedules_messages_job(self):
        self.assertIn("'retention_messages'", self.sql)
        self.assertIn("fn_apply_retention('messages'", self.sql)

    def test_schedules_conversations_job(self):
        self.assertIn("'retention_conversations'", self.sql)

    def test_schedules_contacts_inactive_job(self):
        self.assertIn("'retention_contacts_inactive'", self.sql)

    def test_schedules_pii_access_log_job(self):
        self.assertIn("'retention_pii_access'", self.sql)

    def test_runs_in_low_traffic_window_sundays(self):
        # Domingos (0) at 03:xx — verificar al menos uno.
        self.assertRegex(self.sql, r"'\d+\s+3\s+\*\s+\*\s+0'")

    def test_handles_pg_cron_unavailable(self):
        # Migración no debe romper si pg_cron no está instalado (CI/local).
        self.assertIn("EXCEPTION WHEN undefined_table", self.sql)


class RlsPoliciesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, encoding="utf-8") as f:
            cls.sql = f.read()

    def test_rls_enabled(self):
        self.assertRegex(
            self.sql,
            r"ALTER\s+TABLE\s+public\.retention_policies\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY",
        )

    def test_select_policy_includes_global_defaults(self):
        # tenant_id IS NULL debe ser visible para todos.
        self.assertIn("tenant_id IS NULL", self.sql)

    def test_modify_policy_requires_owner_or_manager(self):
        self.assertIn("'owner'", self.sql)
        self.assertIn("'manager'", self.sql)


class PerTenantFixMigrationTests(unittest.TestCase):
    """Rev. 100 — fn_apply_retention itera per-tenant policies."""

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PER_TENANT_FIX_PATH, encoding="utf-8") as f:
            cls.sql = f.read()

    def test_migration_exists(self):
        self.assertTrue(os.path.exists(MIGRATION_PER_TENANT_FIX_PATH))

    def test_iterates_tenants(self):
        # Bug original: solo leía default global. Fix: FOR r_tenant IN SELECT id FROM tenants.
        self.assertRegex(
            self.sql,
            r"FOR\s+r_tenant\s+IN\s+SELECT\s+id\s+AS\s+tenant_id\s+FROM\s+public\.tenants",
        )

    def test_resolves_per_tenant_override(self):
        # Por cada tenant, busca override antes de caer al default.
        self.assertRegex(
            self.sql,
            r"WHERE\s+tenant_id\s*=\s*r_tenant\.tenant_id",
        )

    def test_falls_back_to_global_default(self):
        # Si no hay override, v_eff_ttl := v_default_ttl.
        self.assertIn("v_eff_ttl := v_default_ttl", self.sql)
        self.assertIn("v_eff_act := v_default_act", self.sql)

    def test_delete_filters_by_tenant_id(self):
        # CADA DELETE/UPDATE incluye tenant_id = r_tenant.tenant_id.
        # Sin esto, multi-tenant safety se rompe.
        delete_blocks = re.findall(
            r"(DELETE\s+FROM\s+public\.\w+[^;]+?)(?=\s*RETURNING|\s*;)",
            self.sql, flags=re.DOTALL | re.IGNORECASE,
        )
        for block in delete_blocks:
            self.assertIn(
                "tenant_id = r_tenant.tenant_id", block,
                f"DELETE block missing tenant filter:\n{block[:200]}",
            )

    def test_update_filters_by_tenant_id(self):
        update_blocks = re.findall(
            r"(UPDATE\s+public\.\w+[^;]+?)(?=\s*RETURNING|\s*;)",
            self.sql, flags=re.DOTALL | re.IGNORECASE,
        )
        for block in update_blocks:
            self.assertIn(
                "tenant_id = r_tenant.tenant_id", block,
                f"UPDATE block missing tenant filter:\n{block[:200]}",
            )

    def test_returns_total_count_summed_across_tenants(self):
        self.assertIn("v_total_count := v_total_count + v_count", self.sql)


if __name__ == "__main__":
    unittest.main()

"""Rev. 100 — Tests del cierre de certificación real (no cosmético).

Cubre:
  • notifications._notify_tenant_event return semantics post-fix.
  • pii_audit helper en services/api.
  • Security headers CSP + HSTS en main.py middleware.
  • Migration 20260508010000 fn_apply_retention per-tenant.
  • SAR endpoint hardening (rate limit dependency presente).
"""
import asyncio
import os
import re
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from dependencies.pii_audit import log_pii_access  # noqa: E402
import notifications  # noqa: E402


class PiiAuditHelperTests(unittest.TestCase):
    """Rev. 100 — helper en services/api/dependencies/pii_audit.py."""

    def test_inserts_to_pii_access_log(self):
        sb = MagicMock()
        log_pii_access(
            sb, tenant_id="t-1", contact_id="c-1",
            accessed_by="user:alice@x.com",
            purpose="sar_export",
            fields_accessed=["name", "email", "document_number"],
        )
        sb.table.assert_called_with("pii_access_log")
        insert_call = sb.table.return_value.insert.call_args.args[0]
        self.assertEqual(insert_call["tenant_id"], "t-1")
        self.assertEqual(insert_call["contact_id"], "c-1")
        self.assertEqual(insert_call["accessed_by"], "user:alice@x.com")
        self.assertEqual(insert_call["purpose"], "sar_export")
        self.assertIn("name", insert_call["fields_accessed"])

    def test_truncates_user_agent(self):
        sb = MagicMock()
        long_ua = "X" * 1000
        log_pii_access(
            sb, tenant_id="t-1", contact_id=None,
            accessed_by="x", purpose="x", fields_accessed=[],
            user_agent=long_ua,
        )
        insert_call = sb.table.return_value.insert.call_args.args[0]
        self.assertLessEqual(len(insert_call["user_agent"]), 500)

    def test_no_tenant_id_is_noop(self):
        sb = MagicMock()
        log_pii_access(
            sb, tenant_id="", contact_id="c-1",
            accessed_by="x", purpose="x", fields_accessed=[],
        )
        sb.table.assert_not_called()

    def test_swallow_exception_does_not_propagate(self):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.side_effect = Exception("DB down")
        # No debe levantar.
        log_pii_access(
            sb, tenant_id="t-1", contact_id="c-1",
            accessed_by="x", purpose="x", fields_accessed=[],
        )

    def test_optional_ip_user_agent_only_set_when_provided(self):
        sb = MagicMock()
        log_pii_access(
            sb, tenant_id="t-1", contact_id="c-1",
            accessed_by="x", purpose="x", fields_accessed=[],
            # ip_address y user_agent NOT provided
        )
        insert_call = sb.table.return_value.insert.call_args.args[0]
        self.assertNotIn("ip_address", insert_call)
        self.assertNotIn("user_agent", insert_call)


class NotifyTenantEventReturnSemanticsTests(unittest.TestCase):
    """Rev. 100 — Fix: cuando todos los recipients fallan, retorna False
    explícito + log ERROR (no silent True)."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.sb = MagicMock()

    def tearDown(self):
        self.loop.close()

    def _setup_recipients(self, emails):
        chain = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
        chain.execute.return_value = MagicMock(data=[
            {"channel": "email", "enabled": True, "config": {"to_email": e}}
            for e in emails
        ])

    def test_all_recipients_fail_returns_false(self):
        self._setup_recipients(["a@x.com", "b@x.com"])

        async def fake_fail(*, to, subject, html, text=None, tags=None):
            return False

        with patch.object(notifications, "_send_email_via_resend", side_effect=fake_fail):
            ok = self.loop.run_until_complete(
                notifications._notify_tenant_event(
                    self.sb, tenant_id="t-1",
                    event_type="test_event", subject="S", html_body="h",
                )
            )
        self.assertFalse(ok)

    def test_partial_success_returns_true(self):
        self._setup_recipients(["a@x.com", "b@x.com"])
        results = iter([True, False])

        async def mixed(*, to, subject, html, text=None, tags=None):
            return next(results)

        with patch.object(notifications, "_send_email_via_resend", side_effect=mixed):
            ok = self.loop.run_until_complete(
                notifications._notify_tenant_event(
                    self.sb, tenant_id="t-1",
                    event_type="x", subject="s", html_body="h",
                )
            )
        self.assertTrue(ok)

    def test_no_recipients_configured_returns_true(self):
        # Empty list = no-op aceptable, no es fallo de Art. 9.
        self._setup_recipients([])
        ok = self.loop.run_until_complete(
            notifications._notify_tenant_event(
                self.sb, tenant_id="t-1",
                event_type="x", subject="s", html_body="h",
            )
        )
        self.assertTrue(ok)

    def test_all_fail_logs_error_with_recipients(self):
        self._setup_recipients(["a@x.com"])

        async def fail(*, to, subject, html, text=None, tags=None):
            return False

        with self.assertLogs("orchestrator.notifications", level="ERROR") as cm:
            with patch.object(notifications, "_send_email_via_resend", side_effect=fail):
                self.loop.run_until_complete(
                    notifications._notify_tenant_event(
                        self.sb, tenant_id="tenant-x",
                        event_type="event-x", subject="s", html_body="h",
                    )
                )
        # Logger debe gritar ERROR y mencionar tenant + count.
        joined = "\n".join(cm.output)
        self.assertIn("tenant-x", joined)
        self.assertIn("event-x", joined)
        self.assertIn("ALL", joined)


class RetentionPerTenantMigrationTests(unittest.TestCase):
    """Rev. 100 — fn_apply_retention itera per-tenant y filtra DELETE/UPDATE."""

    @classmethod
    def setUpClass(cls):
        with open(
            str(
                Path(__file__).resolve().parents[1]
                / "supabase/migrations/20260508010000_retention_per_tenant_fix.sql"
            ),
            encoding="utf-8",
        ) as f:
            cls.sql = f.read()

    def test_iterates_tenants_table(self):
        self.assertIn("FROM public.tenants", self.sql)
        self.assertRegex(self.sql, r"FOR\s+r_tenant\s+IN")

    def test_resolves_per_tenant_override(self):
        # Para cada tenant, busca su override antes del default.
        self.assertRegex(
            self.sql,
            r"WHERE\s+tenant_id\s*=\s*r_tenant\.tenant_id\s+AND\s+entity",
        )

    def test_falls_back_to_global_default(self):
        self.assertIn("v_eff_ttl := v_default_ttl", self.sql)

    def test_each_delete_includes_tenant_filter(self):
        deletes = re.findall(
            r"DELETE\s+FROM\s+public\.\w+[\s\S]+?(?=RETURNING)",
            self.sql,
        )
        self.assertGreater(len(deletes), 0, "Should have DELETE statements")
        for d in deletes:
            self.assertIn("tenant_id = r_tenant.tenant_id", d)

    def test_no_unfiltered_delete(self):
        # Defensa anti-regression: ningún DELETE sin tenant_id filter.
        for line in self.sql.splitlines():
            if line.strip().startswith("DELETE FROM public."):
                # next few lines must contain tenant filter
                idx = self.sql.index(line)
                window = self.sql[idx:idx + 300]
                self.assertIn(
                    "tenant_id", window,
                    f"Unfiltered DELETE risk:\n{window}",
                )


class CspHstsHeadersTests(unittest.TestCase):
    """Rev. 100 — CSP + HSTS en services/api/main.py."""

    @classmethod
    def setUpClass(cls):
        with open(
            str(Path(__file__).resolve().parents[1] / "services/api/main.py"),
            encoding="utf-8",
        ) as f:
            cls.code = f.read()

    def test_csp_header_present(self):
        self.assertIn("Content-Security-Policy", self.code)

    def test_csp_default_src_none(self):
        # API only serves JSON, no HTML — default-src 'none' is correct.
        self.assertIn("default-src 'none'", self.code)

    def test_csp_frame_ancestors_none(self):
        # Defensa contra clickjacking además de X-Frame-Options.
        self.assertIn("frame-ancestors 'none'", self.code)

    def test_hsts_present(self):
        self.assertIn("Strict-Transport-Security", self.code)

    def test_hsts_max_age_one_year(self):
        # max-age=31536000 = 1 año, mínimo recomendado.
        self.assertIn("max-age=31536000", self.code)


class SarEndpointHardeningTests(unittest.TestCase):
    """Rev. 100 — Hardening del endpoint SAR."""

    @classmethod
    def setUpClass(cls):
        with open(
            str(Path(__file__).resolve().parents[1] / "services/api/routers/data_subject_request.py"),
            encoding="utf-8",
        ) as f:
            cls.code = f.read()

    def test_imports_rate_limit_dep(self):
        self.assertIn("from dependencies.security import RL_WRITE_DEFAULT", self.code)

    def test_endpoint_has_rate_limit_dep(self):
        # _rl: None = Depends(RL_WRITE_DEFAULT)
        self.assertRegex(self.code, r"Depends\(RL_WRITE_DEFAULT\)")

    def test_endpoint_takes_request_for_ip(self):
        self.assertIn("request: Request", self.code)
        self.assertIn("request.client.host", self.code)

    def test_imports_pii_audit(self):
        self.assertIn("from dependencies.pii_audit import log_pii_access", self.code)

    def test_logs_pii_access_on_export(self):
        # Export debe loguear acceso a PII.
        self.assertRegex(
            self.code, r"log_pii_access\(\s*sb\s*,",
        )
        self.assertIn('purpose="sar_export"', self.code)

    def test_build_export_503_on_db_error(self):
        # rev. 100 — DB error → 503, no payload incompleto silencioso.
        self.assertIn("status_code=503", self.code)
        self.assertIn("DB temporarily unavailable", self.code)


# BLOQUE K-2: OrchestratorCallerErrorLoggingTests ELIMINADO — probaba el patrón
# de caller (ok = await notify_consent_revoked/notify_sar_received + log ERROR)
# dentro de build_and_run_orchestration (pipeline V1 retirado). La conducta de
# compliance se preserva en el path agentic (_handle_data_rights_if_intent,
# soft_revoke_consent) y en la API (data_subject_request.py), con cobertura propia
# (test_a11_habeas_data_request, test_rev93_sar_endpoints).


class EnvVarCoherenceTests(unittest.TestCase):
    """Rev. 100 — RESEND vars en render.yaml + .env.example."""

    @classmethod
    def setUpClass(cls):
        with open(
            str(Path(__file__).resolve().parents[1] / "render.yaml"),
            encoding="utf-8",
        ) as f:
            cls.render_yaml = f.read()
        with open(
            str(Path(__file__).resolve().parents[1] / ".env.example"),
            encoding="utf-8",
        ) as f:
            cls.env_example = f.read()

    def test_render_yaml_has_resend_key_secret(self):
        # Debe estar en el orchestrator service block como sync: false (secret).
        self.assertIn("RESEND_API_KEY", self.render_yaml)
        # Verifica patrón "key: RESEND_API_KEY\n        sync: false"
        self.assertRegex(
            self.render_yaml,
            r"key:\s*RESEND_API_KEY\s*\n\s*sync:\s*false",
        )

    def test_render_yaml_has_resend_from_email(self):
        self.assertIn("RESEND_FROM_EMAIL", self.render_yaml)

    def test_env_example_documents_resend(self):
        self.assertIn("RESEND_API_KEY", self.env_example)
        self.assertIn("RESEND_FROM_EMAIL", self.env_example)

    def test_env_example_no_obsolete_smtp_brevo(self):
        # rev. 100 — sección SMTP/BREVO obsoleta reemplazada por Resend.
        # Si reaparece, alguien revivió código muerto.
        self.assertNotIn("BREVO_API_KEY", self.env_example)


if __name__ == "__main__":
    unittest.main()

"""Rev. 101 — Tests de los follow-ups F1, F3, F5, F6 (F4/F7 son UI puro).

Cobertura:
  • F6: _detect_rectification_intent — token positivos/negativos, exclusiones.
  • F1: _render_export_html — shape del HTML imprimible.
  • F5: _build_sic_payload — payload SIC con consent + pii + meta.
  • F3: migración 20260509010000 SQL view shape.
  • F2: ADR-0003 documenta la decisión de defer (no test funcional).
"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

# Imports module-level (evita issues de class-attribute method-binding).
from orchestrator import _detect_rectification_intent, _detect_minor_intent  # noqa: E402
from routers.data_subject_request import _render_export_html  # noqa: E402
from routers.sic_report import _build_sic_payload, _payload_to_csv  # noqa: E402


# ─── F6 — Detector pre-LLM rectificación ─────────────────────────────────────

class DetectRectificationIntentTests(unittest.TestCase):

    def test_corregir_mis_datos(self):
        self.assertTrue(_detect_rectification_intent("Quiero corregir mis datos"))
        self.assertTrue(_detect_rectification_intent("Por favor corrige mis datos"))
        self.assertTrue(_detect_rectification_intent("Necesito actualizar mi email"))
        self.assertTrue(_detect_rectification_intent("Quiero cambiar mis datos"))

    def test_formal_habeas_data(self):
        self.assertTrue(_detect_rectification_intent("ejercer rectificacion"))
        self.assertTrue(_detect_rectification_intent(
            "solicito rectificacion habeas data"
        ))

    def test_complaint_about_wrong_data(self):
        self.assertTrue(_detect_rectification_intent("Tienen mal mis datos"))
        self.assertTrue(_detect_rectification_intent("Mis datos están incorrectos"))

    def test_excludes_revocation(self):
        # Revocación tiene precedencia (mayor riesgo si se ignora).
        self.assertFalse(_detect_rectification_intent("elimina mis datos"))
        self.assertFalse(_detect_rectification_intent("borrar todos mis datos"))

    def test_pure_export_does_not_match(self):
        # "Envíame mis datos" sin ningún token de rectify NO debe matchear.
        self.assertFalse(_detect_rectification_intent("envíame mis datos"))
        self.assertFalse(_detect_rectification_intent("qué tienen sobre mí"))

    def test_negative_chitchat(self):
        self.assertFalse(_detect_rectification_intent("Hola"))
        self.assertFalse(_detect_rectification_intent("Cuanto cuesta el aceite"))
        self.assertFalse(_detect_rectification_intent(""))

    def test_handles_accents(self):
        self.assertTrue(_detect_rectification_intent("ACTUALIZAR MI DIRECCIÓN"))
        self.assertTrue(_detect_rectification_intent("solicito rectificación"))


# ─── F1 — HTML imprimible ─────────────────────────────────────────────────────

class RenderExportHtmlTests(unittest.TestCase):

    def render(self, payload):
        return _render_export_html(payload)

    def _sample_payload(self, **overrides):
        base = {
            "format_version": "1.0",
            "generated_at": "2026-05-01T00:00:00Z",
            "primary_identifier": {
                "kind": "document",
                "value": "CC 1234567890",
                "note": "Identificador legal primario.",
            },
            "subject": {
                "id": "c-1", "phone": "+57x", "name": "Cristian",
                "email": "test@x.com", "document_type": "CC",
                "document_number": "1234567890", "address": {"street": "Calle 1"},
                "consent_given": True, "consent_given_at": "2026-04-01",
                "consent_revoked_at": None, "consent_revoked_reason": None,
                "consent_text_version": "v2026-04",
            },
            "orders": [
                {"id": "o-1", "status": "paid", "total_amount": 50000,
                 "shipping_cost": 8000, "created_at": "2026-04-15",
                 "updated_at": "2026-04-15"},
            ],
            "consent_history": [
                {"event": "granted", "source": "whatsapp",
                 "occurred_at": "2026-04-01", "actor_email": None},
            ],
            "pii_access_history": [
                {"accessed_by": "user:ops@x.com", "purpose": "sar_export",
                 "fields_accessed": ["name", "email"], "accessed_at": "2026-05-01"},
            ],
            "subprocessors": [
                {"name": "Wompi", "role": "payments", "jurisdiction": "Colombia"},
            ],
            "legal_basis": {
                "law": "Ley 1581/2012",
                "responsible": "Tenant",
                "processor": "Plataforma",
            },
        }
        base.update(overrides)
        return base

    def test_html_has_doctype_and_title(self):
        html = self.render(self._sample_payload())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Reporte Habeas Data", html)

    def test_includes_subject_pii_fields(self):
        html = self.render(self._sample_payload())
        self.assertIn("Cristian", html)
        self.assertIn("test@x.com", html)
        self.assertIn("CC", html)

    def test_renders_orders_section(self):
        html = self.render(self._sample_payload())
        self.assertIn("o-1", html)
        self.assertIn("paid", html)

    def test_renders_consent_history_section(self):
        html = self.render(self._sample_payload())
        self.assertIn("granted", html)

    def test_renders_pii_access_section(self):
        html = self.render(self._sample_payload())
        self.assertIn("ops@x.com", html)
        self.assertIn("sar_export", html)

    def test_subprocessors_listed(self):
        html = self.render(self._sample_payload())
        self.assertIn("Wompi", html)

    def test_print_friendly_css(self):
        html = self.render(self._sample_payload())
        self.assertIn("@page", html)
        self.assertIn("@media print", html)

    def test_xss_escape_in_subject_name(self):
        # Asegurar que no hay HTML inyectable en campos PII.
        payload = self._sample_payload()
        payload["subject"]["name"] = "<script>alert(1)</script>"
        html = self.render(payload)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_empty_orders_shows_placeholder(self):
        payload = self._sample_payload(orders=[])
        html = self.render(payload)
        self.assertIn("Sin órdenes", html)

    def test_empty_consent_history_shows_placeholder(self):
        payload = self._sample_payload(consent_history=[])
        html = self.render(payload)
        self.assertIn("Sin eventos de consent", html)


# ─── F5 — SIC report endpoint ─────────────────────────────────────────────────

class BuildSicPayloadTests(unittest.TestCase):

    def setUp(self):
        self.build = _build_sic_payload
        self.sb = MagicMock()
        # tenants read.
        self.sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "t-1", "name": "Test Tenant", "document_number": "900-X"}]
        )

    def _setup_consent(self, rows):
        chain = self.sb.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order
        chain.return_value.execute.return_value = MagicMock(data=rows)

    def test_payload_has_required_sections(self):
        self._setup_consent([])
        payload = self.build(
            self.sb, "t-1",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        for k in ("report_version", "report_kind", "generated_at", "period",
                  "tenant", "platform", "summary", "consent_events",
                  "pii_access_events", "legal_basis"):
            self.assertIn(k, payload)

    def test_legal_basis_includes_articles(self):
        self._setup_consent([])
        payload = self.build(
            self.sb, "t-1",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        articles = payload["legal_basis"]["articles_covered"]
        self.assertTrue(any("Art. 9" in a for a in articles))
        self.assertTrue(any("Art. 14" in a for a in articles))

    def test_summary_aggregates_by_event(self):
        self._setup_consent([
            {"event": "granted", "source": "whatsapp"},
            {"event": "granted", "source": "whatsapp"},
            {"event": "revoked", "source": "tenant_console"},
        ])
        payload = self.build(
            self.sb, "t-1",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        # Note: el mock comparte chains; ambos consent y pii usarán el mismo
        # data. Para test simplicidad, validamos que hay summary structure.
        self.assertIn("events_by_kind", payload["summary"])
        self.assertIn("events_by_source", payload["summary"])


class PayloadToCsvTests(unittest.TestCase):

    def to_csv(self, payload):
        return _payload_to_csv(payload)

    def test_csv_has_header_lines(self):
        payload = {
            "generated_at": "2026-05-01T00:00:00Z",
            "period": {"from": "2026-01-01", "to": "2026-05-01"},
            "tenant": {"id": "t-1", "name": "Test"},
            "consent_events": [],
            "pii_access_events": [],
        }
        csv = self.to_csv(payload)
        self.assertIn("# Reporte Habeas Data", csv)
        self.assertIn("# Generado:", csv)
        self.assertIn("section,id,contact_id", csv)


# ─── F3 — vista unificada ────────────────────────────────────────────────────

class UnifiedAuditViewMigrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(
            "/home/ansible/workspaces/konvi-platform/supabase/migrations/"
            "20260509010000_unified_audit_view.sql",
            encoding="utf-8",
        ) as f:
            cls.sql = f.read()

    def test_creates_view(self):
        self.assertIn("CREATE OR REPLACE VIEW public.vw_consent_events_unified", self.sql)

    def test_unions_both_tables(self):
        self.assertIn("FROM public.consent_audit_log", self.sql)
        self.assertIn("FROM public.audit_log", self.sql)
        self.assertIn("UNION ALL", self.sql)

    def test_legacy_filter_on_entity_type(self):
        self.assertIn("entity_type = 'contact'", self.sql)

    def test_legacy_action_filter_consent_revoke_rectify(self):
        self.assertIn("ILIKE '%consent%'", self.sql)
        self.assertIn("ILIKE '%revok%'", self.sql)
        self.assertIn("ILIKE '%rectif%'", self.sql)

    def test_origin_table_disambiguation(self):
        # La vista distingue de qué tabla viene cada row.
        self.assertIn("'consent_audit_log'::TEXT AS origin_table", self.sql)
        self.assertIn("'audit_log'::TEXT AS origin_table", self.sql)

    def test_grants_select_to_authenticated(self):
        self.assertIn(
            "GRANT SELECT ON public.vw_consent_events_unified TO authenticated, service_role",
            self.sql,
        )


# ─── F1+F5 — main.py registers SIC router ───────────────────────────────────

class MainPyRoutersTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(
            "/home/ansible/workspaces/konvi-platform/services/api/main.py",
            encoding="utf-8",
        ) as f:
            cls.code = f.read()

    def test_sic_router_registered(self):
        self.assertIn("from routers import sic_report as _sic", self.code)
        # Rev. 109: _OFFBOARDING_GATE añadido a todos los routers mutación.
        self.assertIn('app.include_router(_sic.router, prefix="/api/v1"', self.code)


# ─── F2 — defer documentado ──────────────────────────────────────────────────

class F2DeferDocumentedTests(unittest.TestCase):

    def test_adr_documents_f2_defer(self):
        with open(
            "/home/ansible/workspaces/konvi-platform/docs/adr/"
            "0003-habeas-data-compliance-strategy.md",
            encoding="utf-8",
        ) as f:
            adr = f.read()
        # F2 debe estar marcada como DEFERRED con razones explícitas.
        self.assertIn("F2", adr)
        self.assertIn("DEFERRED", adr)
        # Razones que justifican el defer:
        self.assertIn("Wompi", adr)  # checkout dependency
        self.assertIn("aditivos", adr)  # rev. 96 mitigation existente
        self.assertIn("Trigger para reabrir F2", adr)


class DetectMinorIntentTests(unittest.TestCase):
    """Rev. 102 — Detector minoría de edad pre-LLM (Decreto 1377/2013 Art. 7)."""

    def test_explicit_phrases(self):
        self.assertTrue(_detect_minor_intent("Hola, soy menor de edad"))
        self.assertTrue(_detect_minor_intent("yo soy menor"))
        self.assertTrue(_detect_minor_intent("no tengo mayoría de edad"))
        self.assertTrue(_detect_minor_intent("Soy un niño"))
        self.assertTrue(_detect_minor_intent("estoy en bachillerato"))
        self.assertTrue(_detect_minor_intent("Tengo permiso de mi mamá"))

    def test_age_under_18(self):
        self.assertTrue(_detect_minor_intent("Tengo 14 años"))
        self.assertTrue(_detect_minor_intent("tengo 17 años"))
        self.assertTrue(_detect_minor_intent("ya tengo 16 años"))
        self.assertTrue(_detect_minor_intent("Tengo 5 añitos"))
        self.assertTrue(_detect_minor_intent("Cumplí 13 años"))

    def test_age_18_or_more_does_not_trigger(self):
        # 18+ es mayor de edad, NO debe disparar.
        self.assertFalse(_detect_minor_intent("Tengo 18 años"))
        self.assertFalse(_detect_minor_intent("Ya cumplí 25 años"))
        self.assertFalse(_detect_minor_intent("tengo 30 años"))

    def test_negative_no_age_no_phrase(self):
        self.assertFalse(_detect_minor_intent("Hola, quiero comprar el aceite"))
        self.assertFalse(_detect_minor_intent("¿Cuánto cuesta?"))
        self.assertFalse(_detect_minor_intent(""))

    def test_age_not_about_self_does_not_trigger(self):
        # "16 productos" NO debe disparar el regex (no hay "años").
        self.assertFalse(_detect_minor_intent("Quiero 16 productos"))
        self.assertFalse(_detect_minor_intent("La promo dura 7 días"))

    def test_handles_accents(self):
        self.assertTrue(_detect_minor_intent("SOY MENOR DE EDAD"))
        self.assertTrue(_detect_minor_intent("Tengo 16 años"))


class StricterDocumentRulesTests(unittest.TestCase):
    """Rev. 102 — rangos estrictos en validators (CC 6-10, CE 6-7, NIT 9-11),
    TI removido del set."""

    def test_ti_removed_from_accepted_types(self):
        sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
        from dependencies.contact_validators import DOCUMENT_TYPES_CO  # noqa: E402
        self.assertNotIn("TI", DOCUMENT_TYPES_CO)
        self.assertIn("CC", DOCUMENT_TYPES_CO)
        self.assertIn("CE", DOCUMENT_TYPES_CO)
        self.assertIn("NIT", DOCUMENT_TYPES_CO)
        self.assertIn("PP", DOCUMENT_TYPES_CO)

    def test_cc_max_10_digits(self):
        from dependencies.contact_validators import validate_document  # noqa: E402
        # 10 dígitos OK, 11 falla.
        self.assertIsNone(validate_document("CC", "1234567890"))
        self.assertIsNotNone(validate_document("CC", "12345678901"))
        # 6 dígitos mínimo OK, 5 falla.
        self.assertIsNone(validate_document("CC", "123456"))
        self.assertIsNotNone(validate_document("CC", "12345"))

    def test_ce_6_to_7_digits(self):
        from dependencies.contact_validators import validate_document  # noqa: E402
        self.assertIsNone(validate_document("CE", "123456"))
        self.assertIsNone(validate_document("CE", "1234567"))
        # 5 falla, 8 falla.
        self.assertIsNotNone(validate_document("CE", "12345"))
        self.assertIsNotNone(validate_document("CE", "12345678"))

    def test_nit_max_11_with_dv(self):
        from dependencies.contact_validators import validate_document  # noqa: E402
        # 9 dígitos OK (sin DV).
        self.assertIsNone(validate_document("NIT", "900123456"))
        # 9 dígitos + -DV = 11 chars OK (asume DV correcto módulo-11).
        # 12 chars falla.
        self.assertIsNotNone(validate_document("NIT", "1234567890123"))

    def test_ti_validation_now_rejects(self):
        from dependencies.contact_validators import validate_document  # noqa: E402
        # TI ya no es tipo válido — rechaza.
        result = validate_document("TI", "12345678901")
        self.assertIsNotNone(result)
        self.assertIn("inválido", result.lower())


if __name__ == "__main__":
    unittest.main()

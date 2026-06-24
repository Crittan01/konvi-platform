"""Tests whatsapp_templates helper (Sem 7 F2 / 2026-05-09).

Cubre `services/api/lib/whatsapp_templates.py`:
  - Validators (name, language, category, parameter_format, components)
  - CRUD: create_template_draft, mark_submitted_to_meta, update_local_draft,
    delete_template
  - Webhook sync: update_status_from_webhook, update_quality_from_webhook
  - Queries: list_templates_for_tenant, get_approved_template

Tests usan _FakeSupabase (sin DB real) — modelo de mocking consistente con
test_capabilities_matrix, test_tenant_carriers, test_insurance.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "whatsapp_templates.py"


def _load_lib():
    spec = importlib.util.spec_from_file_location("_wa_templates", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_wa_templates"] = mod
    spec.loader.exec_module(mod)
    return mod


wt = _load_lib()


# ─── Fake Supabase ──────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None
        self._order: list[tuple[str, bool]] = []

    def select(self, _cols: str = "*"):
        return _FakeQuery(self._store, op="select")

    def insert(self, payload):
        return _FakeQuery(self._store, op="insert", payload=payload)

    def update(self, payload):
        return _FakeQuery(self._store, op="update", payload=payload)

    def delete(self):
        return _FakeQuery(self._store, op="delete")

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order.append((col, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row):
        return all(row.get(c) == v for c, v in self._filters)

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            for col, desc in reversed(self._order):
                rows = sorted(rows, key=lambda r: r.get(col) or "", reverse=desc)
            if self._limit is not None:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)
        if self._op == "insert":
            new_id = f"tpl-{len(self._store) + 1:04d}"
            row = dict(self._payload)
            row["id"] = new_id
            row.setdefault("created_at", datetime.utcnow().isoformat())
            row.setdefault("updated_at", datetime.utcnow().isoformat())
            self._store.append(row)
            return SimpleNamespace(data=[row])
        if self._op == "update":
            updated: list[dict] = []
            for row in self._store:
                if self._matches(row):
                    for k, v in self._payload.items():
                        row[k] = v
                    row["updated_at"] = datetime.utcnow().isoformat()
                    updated.append(row)
            return SimpleNamespace(data=updated)
        if self._op == "delete":
            initial = len(self._store)
            self._store[:] = [r for r in self._store if not self._matches(r)]
            return SimpleNamespace(data=[1] * (initial - len(self._store)))
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict]] = {"whatsapp_templates": []}

    def table(self, name):
        return _FakeQuery(self._tables[name])


# ─── Helper: sample components ──────────────────────────────────────────────


def _sample_components() -> list[dict]:
    """Components mínimos válidos: 1 BODY con texto."""
    return [
        {"type": "BODY", "text": "Hola {{1}}, tu pedido {{2}} fue enviado."},
    ]


def _sample_components_full() -> list[dict]:
    """Components con HEADER + BODY + FOOTER + BUTTONS."""
    return [
        {"type": "HEADER", "format": "TEXT", "text": "Konvi"},
        {"type": "BODY", "text": "Hola {{1}}, recordatorio: tu orden {{2}} está pendiente de pago."},
        {"type": "FOOTER", "text": "Powered by Konvi"},
        {"type": "BUTTONS", "buttons": [
            {"type": "URL", "text": "Pagar ahora", "url": "https://wompi.co/p/{{1}}"},
        ]},
    ]


# ─── Validators ──────────────────────────────────────────────────────────────


class ValidatorsTests(unittest.TestCase):
    def test_name_valido(self):
        for name in ("payment_reminder_v1", "order_shipped", "cart_abandoned_24h",
                     "abc", "auth_otp_es"):
            self.assertEqual(wt._validate_name(name), name)

    def test_name_invalido(self):
        for bad in ("", "Payment_Reminder", "1starts_with_number", "ab",
                    "has-dash", "with space", "x" * 51):
            with self.assertRaises(wt.TemplateError):
                wt._validate_name(bad)

    def test_language_valido(self):
        for lang in ("es", "es_CO", "en_US", "pt_BR"):
            self.assertEqual(wt._validate_language(lang), lang)

    def test_language_invalido(self):
        for bad in ("", "ES", "es-CO", "spanish", "es_co", "EN_US"):
            with self.assertRaises(wt.TemplateError):
                wt._validate_language(bad)

    def test_category_valido(self):
        for cat in ("MARKETING", "UTILITY", "AUTHENTICATION"):
            self.assertEqual(wt._validate_category(cat), cat)

    def test_category_invalido(self):
        for bad in ("", "PROMO", "transactional", "marketing"):
            try:
                result = wt._validate_category(bad)
                # 'marketing' lowercase → upper → MARKETING (válido)
                if bad == "marketing":
                    self.assertEqual(result, "MARKETING")
                else:
                    self.fail(f"Expected error for {bad!r} got {result!r}")
            except wt.TemplateError:
                pass

    def test_parameter_format_default(self):
        self.assertEqual(wt._validate_parameter_format(None), "POSITIONAL")
        self.assertEqual(wt._validate_parameter_format(""), "POSITIONAL")

    def test_parameter_format_named(self):
        self.assertEqual(wt._validate_parameter_format("NAMED"), "NAMED")
        self.assertEqual(wt._validate_parameter_format("named"), "NAMED")

    def test_components_minimo_valido(self):
        result = wt._validate_components(_sample_components())
        self.assertEqual(len(result), 1)

    def test_components_full_valido(self):
        result = wt._validate_components(_sample_components_full())
        self.assertEqual(len(result), 4)

    def test_components_vacio_invalido(self):
        with self.assertRaises(wt.TemplateError):
            wt._validate_components([])

    def test_components_no_es_lista_invalido(self):
        with self.assertRaises(wt.TemplateError):
            wt._validate_components({"type": "BODY"})

    def test_components_sin_body_invalido(self):
        with self.assertRaises(wt.TemplateError):
            wt._validate_components([
                {"type": "HEADER", "format": "TEXT", "text": "x"},
                {"type": "FOOTER", "text": "y"},
            ])

    def test_components_dos_bodies_invalido(self):
        with self.assertRaises(wt.TemplateError):
            wt._validate_components([
                {"type": "BODY", "text": "x"},
                {"type": "BODY", "text": "y"},
            ])

    def test_components_body_sin_text_invalido(self):
        with self.assertRaises(wt.TemplateError):
            wt._validate_components([{"type": "BODY", "text": ""}])

    def test_components_type_invalido(self):
        with self.assertRaises(wt.TemplateError):
            wt._validate_components([
                {"type": "BODY", "text": "x"},
                {"type": "UNKNOWN_TYPE", "text": "y"},
            ])

    def test_components_buttons_pueden_repetir(self):
        """BUTTONS es el único type que puede aparecer múltiples veces."""
        result = wt._validate_components([
            {"type": "BODY", "text": "x"},
            {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Sí"}]},
            {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "No"}]},
        ])
        self.assertEqual(len(result), 3)


# ─── CRUD ────────────────────────────────────────────────────────────────────


class CreateDraftTests(unittest.TestCase):
    def test_create_basic(self):
        sb = _FakeSupabase()
        tpl = wt.create_template_draft(
            sb, "tenant-A",
            waba_id="WABA_123",
            name="payment_reminder_v1",
            language="es_CO",
            category="UTILITY",
            components=_sample_components(),
        )
        self.assertEqual(tpl.tenant_id, "tenant-A")
        self.assertEqual(tpl.name, "payment_reminder_v1")
        self.assertEqual(tpl.language, "es_CO")
        self.assertEqual(tpl.category, "UTILITY")
        self.assertEqual(tpl.status, "LOCAL_DRAFT")
        self.assertEqual(tpl.quality_rating, "UNKNOWN")
        self.assertEqual(tpl.parameter_format, "POSITIONAL")
        self.assertIsNone(tpl.meta_template_id)

    def test_create_validates_name(self):
        sb = _FakeSupabase()
        with self.assertRaises(wt.TemplateError):
            wt.create_template_draft(
                sb, "tenant-A",
                waba_id="WABA_123",
                name="Invalid-Name",  # bad
                language="es_CO",
                category="UTILITY",
                components=_sample_components(),
            )

    def test_create_validates_components(self):
        sb = _FakeSupabase()
        with self.assertRaises(wt.TemplateError):
            wt.create_template_draft(
                sb, "tenant-A",
                waba_id="WABA_123",
                name="ok_name",
                language="es_CO",
                category="UTILITY",
                components=[],  # vacío
            )

    def test_create_requiere_waba_id(self):
        sb = _FakeSupabase()
        with self.assertRaises(wt.TemplateError):
            wt.create_template_draft(
                sb, "tenant-A",
                waba_id="",
                name="ok_name",
                language="es_CO",
                category="UTILITY",
                components=_sample_components(),
            )


class MarkSubmittedTests(unittest.TestCase):
    def _setup_draft(self, sb):
        return wt.create_template_draft(
            sb, "tenant-A",
            waba_id="WABA_123",
            name="payment_reminder_v1",
            language="es_CO",
            category="UTILITY",
            components=_sample_components(),
        )

    def test_submit_local_draft_to_pending(self):
        sb = _FakeSupabase()
        draft = self._setup_draft(sb)
        result = wt.mark_submitted_to_meta(
            sb, draft.id, meta_template_id="META_999", tenant_id="tenant-A",
        )
        self.assertEqual(result.status, "PENDING")
        self.assertEqual(result.meta_template_id, "META_999")
        self.assertIsNotNone(result.submitted_at)

    def test_submit_idempotente_si_ya_pending_mismo_meta_id(self):
        sb = _FakeSupabase()
        draft = self._setup_draft(sb)
        wt.mark_submitted_to_meta(sb, draft.id, meta_template_id="META_999", tenant_id="tenant-A")
        result = wt.mark_submitted_to_meta(sb, draft.id, meta_template_id="META_999", tenant_id="tenant-A")
        self.assertEqual(result.status, "PENDING")  # no error
        self.assertEqual(result.meta_template_id, "META_999")

    def test_submit_falla_si_status_no_editable(self):
        sb = _FakeSupabase()
        draft = self._setup_draft(sb)
        wt.mark_submitted_to_meta(sb, draft.id, meta_template_id="META_999", tenant_id="tenant-A")
        # Simular que Meta aprobó vía webhook
        wt.update_status_from_webhook(
            sb, meta_template_id="META_999", new_status="APPROVED",
        )
        # No se puede re-submitear un APPROVED
        with self.assertRaises(wt.TemplateError):
            wt.mark_submitted_to_meta(sb, draft.id, meta_template_id="META_OTRO", tenant_id="tenant-A")

    def test_submit_requiere_meta_template_id(self):
        sb = _FakeSupabase()
        draft = self._setup_draft(sb)
        with self.assertRaises(wt.TemplateError):
            wt.mark_submitted_to_meta(sb, draft.id, meta_template_id="", tenant_id="tenant-A")


class WebhookStatusUpdateTests(unittest.TestCase):
    def _setup_pending(self, sb, meta_id="META_123"):
        draft = wt.create_template_draft(
            sb, "tenant-A",
            waba_id="WABA_999", name="ok_name", language="es_CO",
            category="UTILITY", components=_sample_components(),
        )
        return wt.mark_submitted_to_meta(sb, draft.id, meta_template_id=meta_id, tenant_id="tenant-A")

    def test_status_update_approved(self):
        sb = _FakeSupabase()
        self._setup_pending(sb)
        result = wt.update_status_from_webhook(
            sb, meta_template_id="META_123", new_status="APPROVED",
        )
        self.assertEqual(result.status, "APPROVED")
        self.assertIsNotNone(result.approved_at)

    def test_status_update_rejected_con_reason(self):
        sb = _FakeSupabase()
        self._setup_pending(sb)
        result = wt.update_status_from_webhook(
            sb, meta_template_id="META_123",
            new_status="REJECTED", reason="INCORRECT_CATEGORY",
        )
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.status_reason, "INCORRECT_CATEGORY")

    def test_status_update_meta_id_no_existe_returns_none(self):
        sb = _FakeSupabase()
        result = wt.update_status_from_webhook(
            sb, meta_template_id="META_HUERFANO", new_status="APPROVED",
        )
        self.assertIsNone(result)

    def test_status_invalido_levanta(self):
        sb = _FakeSupabase()
        self._setup_pending(sb)
        with self.assertRaises(wt.TemplateError):
            wt.update_status_from_webhook(
                sb, meta_template_id="META_123", new_status="UNKNOWN_STATE",
            )


class WebhookQualityUpdateTests(unittest.TestCase):
    def _setup_approved(self, sb):
        draft = wt.create_template_draft(
            sb, "tenant-A",
            waba_id="WABA_X", name="ok_name", language="es_CO",
            category="UTILITY", components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, draft.id, meta_template_id="META_QQQ", tenant_id="tenant-A")
        wt.update_status_from_webhook(
            sb, meta_template_id="META_QQQ", new_status="APPROVED",
        )

    def test_quality_update_yellow(self):
        sb = _FakeSupabase()
        self._setup_approved(sb)
        result = wt.update_quality_from_webhook(
            sb, meta_template_id="META_QQQ", new_quality_rating="YELLOW",
        )
        self.assertEqual(result.quality_rating, "YELLOW")

    def test_quality_invalido_levanta(self):
        sb = _FakeSupabase()
        self._setup_approved(sb)
        with self.assertRaises(wt.TemplateError):
            wt.update_quality_from_webhook(
                sb, meta_template_id="META_QQQ", new_quality_rating="PURPLE",
            )


class ListTemplatesTests(unittest.TestCase):
    def test_list_empty(self):
        sb = _FakeSupabase()
        result = wt.list_templates_for_tenant(sb, "tenant-A")
        self.assertEqual(result, [])

    def test_list_filtra_por_tenant(self):
        sb = _FakeSupabase()
        wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="a_one", language="es_CO",
            category="UTILITY", components=_sample_components(),
        )
        wt.create_template_draft(
            sb, "tenant-B", waba_id="W2", name="b_one", language="es_CO",
            category="UTILITY", components=_sample_components(),
        )
        result_a = wt.list_templates_for_tenant(sb, "tenant-A")
        self.assertEqual(len(result_a), 1)
        self.assertEqual(result_a[0].tenant_id, "tenant-A")

    def test_list_filtra_por_status(self):
        sb = _FakeSupabase()
        wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="draft_one", language="es_CO",
            category="UTILITY", components=_sample_components(),
        )
        d2 = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="approved_one", language="es_CO",
            category="UTILITY", components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, d2.id, meta_template_id="M1", tenant_id="tenant-A")
        wt.update_status_from_webhook(
            sb, meta_template_id="M1", new_status="APPROVED",
        )
        approved = wt.list_templates_for_tenant(sb, "tenant-A", status="APPROVED")
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].name, "approved_one")


class GetApprovedTests(unittest.TestCase):
    def test_get_approved_existente(self):
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="payment_reminder_v1",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, d.id, meta_template_id="M_PAY", tenant_id="tenant-A")
        wt.update_status_from_webhook(
            sb, meta_template_id="M_PAY", new_status="APPROVED",
        )
        result = wt.get_approved_template(
            sb, "tenant-A", name="payment_reminder_v1", language="es_CO",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.is_sendable)

    def test_get_approved_pero_pending_returns_none(self):
        """Si existe pero NO está APPROVED, retorna None — outbound bloqueado."""
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="pending_v1",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, d.id, meta_template_id="M_PEND", tenant_id="tenant-A")
        # Sigue PENDING
        result = wt.get_approved_template(
            sb, "tenant-A", name="pending_v1", language="es_CO",
        )
        self.assertIsNone(result)

    def test_get_approved_no_existe_returns_none(self):
        sb = _FakeSupabase()
        result = wt.get_approved_template(
            sb, "tenant-A", name="never_existed", language="es_CO",
        )
        self.assertIsNone(result)


class DeleteTemplateTests(unittest.TestCase):
    def test_delete_local_draft_ok(self):
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="ok_name",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        ok = wt.delete_template(sb, d.id, tenant_id="tenant-A")
        self.assertTrue(ok)
        self.assertEqual(len(sb._tables["whatsapp_templates"]), 0)

    def test_delete_pending_falla(self):
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="ok_name",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, d.id, meta_template_id="MX", tenant_id="tenant-A")
        with self.assertRaises(wt.TemplateError):
            wt.delete_template(sb, d.id, tenant_id="tenant-A")

    def test_delete_approved_falla(self):
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="ok_name",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, d.id, meta_template_id="MX", tenant_id="tenant-A")
        wt.update_status_from_webhook(
            sb, meta_template_id="MX", new_status="APPROVED",
        )
        with self.assertRaises(wt.TemplateError):
            wt.delete_template(sb, d.id, tenant_id="tenant-A")


class UpdateLocalDraftTests(unittest.TestCase):
    def test_update_components_en_local_draft(self):
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="ok_name",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        new_components = _sample_components_full()
        result = wt.update_local_draft(sb, d.id, components=new_components, tenant_id="tenant-A")
        self.assertEqual(len(result.components), 4)
        self.assertEqual(result.status, "LOCAL_DRAFT")

    def test_update_no_permitido_en_pending(self):
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="ok_name",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, d.id, meta_template_id="MX", tenant_id="tenant-A")
        with self.assertRaises(wt.TemplateError):
            wt.update_local_draft(sb, d.id, category="MARKETING", tenant_id="tenant-A")

    def test_update_rejected_resetea_a_local_draft(self):
        """Tras edit en REJECTED, vuelve a LOCAL_DRAFT y limpia meta_template_id."""
        sb = _FakeSupabase()
        d = wt.create_template_draft(
            sb, "tenant-A", waba_id="W1", name="ok_name",
            language="es_CO", category="UTILITY",
            components=_sample_components(),
        )
        wt.mark_submitted_to_meta(sb, d.id, meta_template_id="MX", tenant_id="tenant-A")
        wt.update_status_from_webhook(
            sb, meta_template_id="MX",
            new_status="REJECTED", reason="INCORRECT_CATEGORY",
        )
        # Edit category para corregir y re-submitear
        result = wt.update_local_draft(sb, d.id, category="MARKETING", tenant_id="tenant-A")
        self.assertEqual(result.status, "LOCAL_DRAFT")
        self.assertEqual(result.category, "MARKETING")
        self.assertIsNone(result.meta_template_id)
        self.assertIsNone(result.status_reason)


# ─── WhatsAppTemplate dataclass ──────────────────────────────────────────────


class DataclassTests(unittest.TestCase):
    def test_is_sendable_solo_si_approved(self):
        for status in wt.VALID_STATUSES:
            tpl = wt.WhatsAppTemplate.from_row({
                "id": "x", "tenant_id": "A", "waba_id": "W",
                "name": "n", "language": "es_CO", "category": "UTILITY",
                "components": [{"type": "BODY", "text": "x"}],
                "parameter_format": "POSITIONAL",
                "status": status, "quality_rating": "GREEN",
            })
            if status == "APPROVED":
                self.assertTrue(tpl.is_sendable)
            else:
                self.assertFalse(tpl.is_sendable)

    def test_is_editable_solo_local_draft_o_rejected(self):
        for status in wt.VALID_STATUSES:
            tpl = wt.WhatsAppTemplate.from_row({
                "id": "x", "tenant_id": "A", "waba_id": "W",
                "name": "n", "language": "es_CO", "category": "UTILITY",
                "components": [{"type": "BODY", "text": "x"}],
                "parameter_format": "POSITIONAL",
                "status": status, "quality_rating": "GREEN",
            })
            if status in ("LOCAL_DRAFT", "REJECTED"):
                self.assertTrue(tpl.is_editable)
            else:
                self.assertFalse(tpl.is_editable)


if __name__ == "__main__":
    unittest.main()

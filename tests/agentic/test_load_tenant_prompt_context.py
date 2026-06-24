"""Tests _load_tenant_prompt_context — A6.2.1 finiquito 2026-06-23.

Super-audit worwkgukx HIGH gap: el `except Exception: pass` previo en
`_run_agentic_full` silenciaba fallos del tenant DB lookup → todos los kwargs
business_ops + philosophy quedaban None → bot reintroducía P1 (improvisación)
sin señal. Estos tests verifican que:

  1. Carga OK con todos los campos cuando DB responde.
  2. Degradación graceful (defaults) cuando DB raises.
  3. Warning emitido con tenant_id cuando DB raises (la señal que faltaba).
  4. Campos vacíos/None se normalizan correctamente.
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.dispatcher import (  # noqa: E402
    _load_tenant_prompt_context,
    TenantPromptContext,
)


class _FakeQuery:
    """Mimic supabase query chain: .select().eq().single().execute()."""

    def __init__(self, *, data=None, raise_exc=None):
        self._data = data
        self._raise = raise_exc

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, *, data=None, raise_exc=None):
        self._q = _FakeQuery(data=data, raise_exc=raise_exc)

    def table(self, name):
        return self._q


KAIU_ROW = {
    "name": "KAIU Living Natural",
    "business_pitch": "Cosmética artesanal 100% natural",
    "tono_comunicacion": "cálido",
    "mision": "Bienestar natural",
    "vision": "Líderes en cosmética natural",
    "valores": "Sostenibilidad",
    "shipping_origin": {"city": "Bogotá D.C.", "street": "Calle 3 sur # 70-84"},
    "store_locations": [],
    "store_type": "virtual",
    "support_schedule": {"days": [1, 2, 3, 4, 5, 6], "open": "08:00", "close": "18:00"},
    "social_links": {"facebook": "fb.com/kaiu", "instagram": "ig.com/kaiu"},
    "after_hours_message": "Atendemos Lun-Sáb 8-6.",
}


class LoadOkTests(unittest.TestCase):
    def test_loads_all_fields_when_db_ok(self):
        sb = _FakeSupabase(data=KAIU_ROW)
        ctx = _load_tenant_prompt_context(sb, "tenant-kaiu")
        self.assertEqual(ctx.name, "KAIU Living Natural")
        self.assertEqual(ctx.pitch, "Cosmética artesanal 100% natural")
        self.assertEqual(ctx.tone, "cálido")
        self.assertIsNotNone(ctx.philosophy)
        self.assertEqual(ctx.philosophy["mision"], "Bienestar natural")
        self.assertEqual(ctx.shipping_origin["city"], "Bogotá D.C.")
        self.assertEqual(ctx.store_type, "virtual")
        self.assertEqual(ctx.support_schedule["open"], "08:00")
        self.assertIn("facebook", ctx.social_links)
        self.assertEqual(ctx.after_hours_message, "Atendemos Lun-Sáb 8-6.")

    def test_default_name_when_name_empty(self):
        sb = _FakeSupabase(data={"name": ""})
        ctx = _load_tenant_prompt_context(sb, "t1", default_name="el negocio")
        self.assertEqual(ctx.name, "el negocio")

    def test_philosophy_none_when_all_empty(self):
        sb = _FakeSupabase(data={"name": "X", "mision": "", "vision": "", "valores": ""})
        ctx = _load_tenant_prompt_context(sb, "t1")
        self.assertIsNone(ctx.philosophy)

    def test_empty_data_returns_defaults(self):
        sb = _FakeSupabase(data={})
        ctx = _load_tenant_prompt_context(sb, "t1", default_name="def")
        self.assertEqual(ctx.name, "def")
        self.assertIsNone(ctx.shipping_origin)
        self.assertIsNone(ctx.support_schedule)


class DegradationTests(unittest.TestCase):
    """A6.2.1 core — DB raises NO debe tumbar el turno + DEBE emitir warning."""

    def test_db_exception_returns_defaults_not_raise(self):
        sb = _FakeSupabase(raise_exc=RuntimeError("supabase timeout"))
        # NO debe propagar la excepción
        ctx = _load_tenant_prompt_context(sb, "t1", default_name="fallback")
        # Duck typing (NO assertIsInstance): bajo pytest con sys.path manipulado
        # el módulo agentic.dispatcher puede cargarse 2x → 2 clases distintas con
        # mismo nombre. Verificamos comportamiento (atributos), no identidad de
        # clase. Robusto para migración a pytest runner (A6.2.5).
        self.assertEqual(type(ctx).__name__, "TenantPromptContext")
        self.assertEqual(ctx.name, "fallback")
        self.assertIsNone(ctx.shipping_origin)
        self.assertIsNone(ctx.support_schedule)
        self.assertIsNone(ctx.social_links)

    def test_db_exception_emits_warning_with_tenant_id(self):
        """La SEÑAL que faltaba: el except: pass previo era silencioso."""
        sb = _FakeSupabase(raise_exc=ValueError("column does not exist"))
        with self.assertLogs("agentic.dispatcher", level="WARNING") as cm:
            _load_tenant_prompt_context(sb, "tenant-xyz-789")
        joined = "\n".join(cm.output)
        self.assertIn("AGENTIC_TENANT_LOAD", joined)
        self.assertIn("tenant-xyz-789", joined)  # tenant_id presente para diagnóstico
        self.assertIn("ValueError", joined)  # tipo de excepción
        self.assertIn("column does not exist", joined)  # mensaje original

    def test_db_exception_warning_mentions_improvisation_risk(self):
        """El warning debe explicar el impacto (bot improvisará)."""
        sb = _FakeSupabase(raise_exc=RuntimeError("boom"))
        with self.assertLogs("agentic.dispatcher", level="WARNING") as cm:
            _load_tenant_prompt_context(sb, "t1")
        joined = "\n".join(cm.output)
        self.assertIn("improvisaci", joined.lower())

    def test_db_ok_emits_no_warning(self):
        """Happy path NO debe loguear warning."""
        sb = _FakeSupabase(data=KAIU_ROW)
        logger = logging.getLogger("agentic.dispatcher")
        with self.assertLogs(logger, level="WARNING") as cm:
            logger.warning("sentinel")  # forzar al menos 1 log para que assertLogs no falle
            _load_tenant_prompt_context(sb, "t1")
        # Solo el sentinel, ningún AGENTIC_TENANT_LOAD
        tenant_load_logs = [m for m in cm.output if "AGENTIC_TENANT_LOAD" in m]
        self.assertEqual(tenant_load_logs, [])


if __name__ == "__main__":
    unittest.main()

"""Tests del dispatcher legacy ↔ agentic.

ADR-0018 Fase B + C.

Verifica:
  • is_tenant_agentic_enabled lee meta.agentic_enabled correctamente.
  • Default False (sin migration aplicada o flag no seteado).
  • Shadow mode env var respetada.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeChain:
    def __init__(self, data=None, raises=None):
        self._data = data
        self._raises = raises
    def select(self, *a, **k): return self
    def eq(self, c, v): return self
    def limit(self, n): return self
    def execute(self):
        if self._raises:
            raise self._raises
        return MagicMock(data=self._data)


class _FakeSupabase:
    def __init__(self):
        self.tables = {}
    def set_table(self, name, data=None, raises=None):
        self.tables[name] = (data, raises)
    def table(self, name):
        data, raises = self.tables.get(name, (None, None))
        return _FakeChain(data=data, raises=raises)


class TenantFlagReadingTests(unittest.TestCase):
    """is_tenant_agentic_enabled lee meta.agentic_enabled correctamente."""

    def test_flag_true_returns_true(self):
        from agentic.dispatcher import is_tenant_agentic_enabled
        sb = _FakeSupabase()
        sb.set_table("tenant_integrations", data=[
            {"meta": {"agentic_enabled": True}},
        ])
        result = _run(is_tenant_agentic_enabled(sb, "tenant-x"))
        self.assertTrue(result)

    def test_flag_false_returns_false(self):
        from agentic.dispatcher import is_tenant_agentic_enabled
        sb = _FakeSupabase()
        sb.set_table("tenant_integrations", data=[
            {"meta": {"agentic_enabled": False}},
        ])
        self.assertFalse(_run(is_tenant_agentic_enabled(sb, "tenant-x")))

    def test_flag_no_seteado_default_false(self):
        from agentic.dispatcher import is_tenant_agentic_enabled
        sb = _FakeSupabase()
        sb.set_table("tenant_integrations", data=[
            {"meta": {"otros": "campos"}},
        ])
        self.assertFalse(_run(is_tenant_agentic_enabled(sb, "tenant-x")))

    def test_tenant_no_existe_default_false(self):
        from agentic.dispatcher import is_tenant_agentic_enabled
        sb = _FakeSupabase()
        sb.set_table("tenant_integrations", data=[])
        self.assertFalse(_run(is_tenant_agentic_enabled(sb, "tenant-x")))

    def test_db_error_default_false_no_crash(self):
        """Si DB falla, dispatcher debe degradarse a legacy (False)."""
        from agentic.dispatcher import is_tenant_agentic_enabled
        sb = _FakeSupabase()
        sb.set_table("tenant_integrations", raises=RuntimeError("db down"))
        self.assertFalse(_run(is_tenant_agentic_enabled(sb, "tenant-x")))

    def test_meta_es_null(self):
        from agentic.dispatcher import is_tenant_agentic_enabled
        sb = _FakeSupabase()
        sb.set_table("tenant_integrations", data=[{"meta": None}])
        self.assertFalse(_run(is_tenant_agentic_enabled(sb, "tenant-x")))


class DispatcherFlagPathsTests(unittest.TestCase):
    """Verifica que el dispatcher elige el path correcto.

    NO testeamos invocación real de agentic full ni shadow porque
    requieren mocks complejos del orchestrator legacy. Eso queda
    cubierto por golden conversation tests E2E.
    """

    def test_agentic_shadow_env_var_default_false(self):
        # Sin env var, shadow está OFF.
        # Re-importamos el módulo en un proceso aislado sería ideal,
        # pero como simple verificación: env var no seteada → False.
        os.environ.pop("AGENTIC_SHADOW_ENABLED", None)
        import importlib
        import agentic.dispatcher as disp
        importlib.reload(disp)
        self.assertFalse(disp.AGENTIC_SHADOW_ENABLED)

    def test_agentic_shadow_env_var_true_se_lee(self):
        os.environ["AGENTIC_SHADOW_ENABLED"] = "true"
        import importlib
        import agentic.dispatcher as disp
        importlib.reload(disp)
        self.assertTrue(disp.AGENTIC_SHADOW_ENABLED)
        # Cleanup.
        os.environ.pop("AGENTIC_SHADOW_ENABLED", None)
        importlib.reload(disp)


if __name__ == "__main__":
    unittest.main()

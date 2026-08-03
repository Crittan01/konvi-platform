"""M11 (2026-08-02) — flag agentic_enabled fail-closed.

Antes: un error transitorio leyendo `tenant_integrations` degradaba el meta
a {} → el gate trataba al tenant como NO migrado → escalación masiva de
conversaciones sanas. Ahora `_get_agentic_meta`:
  1. Reintenta una vez tras backoff corto.
  2. Si persiste, sirve el último valor cacheado aunque esté vencido.
  3. Solo degrada a {} si nunca se leyó valor (o el flag es realmente false).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FlakyChain:
    """Query chain que falla `fail_times` veces y luego sirve `data`."""

    def __init__(self, data=None, fail_times=0):
        self._data = data
        self._fail_times = fail_times
        self.calls = 0

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise RuntimeError("transient db error")
        return MagicMock(data=self._data)


class _FlakySupabase:
    def __init__(self, chain):
        self._chain = chain

    def table(self, name):
        return self._chain


class AgenticEnabledFailClosedTests(unittest.TestCase):
    def setUp(self):
        from agentic.dispatcher import invalidate_agentic_meta_cache
        invalidate_agentic_meta_cache()

    def tearDown(self):
        from agentic.dispatcher import invalidate_agentic_meta_cache
        invalidate_agentic_meta_cache()

    def test_error_transitorio_reintenta_y_no_escala(self):
        """Fallo 1 vez + éxito en el reintento → flag leído, NO escalación."""
        from agentic.dispatcher import is_tenant_agentic_enabled
        chain = _FlakyChain(
            data=[{"meta": {"agentic_enabled": True}}], fail_times=1,
        )
        with patch("agentic.dispatcher.time.sleep") as sleep_mock:
            result = _run(is_tenant_agentic_enabled(_FlakySupabase(chain), "t-1"))
        self.assertTrue(result)
        self.assertEqual(chain.calls, 2)  # 1 fallo + 1 reintento
        sleep_mock.assert_called_once()  # backoff corto entre intentos

    def test_error_persistente_con_cache_vencido_usa_stale(self):
        """Cache expirado + lectura caída → sirve el valor cacheado (stale-ok),
        NO trata al tenant como no-migrado."""
        import agentic.dispatcher as disp
        # Sembrar cache con una lectura OK.
        ok_chain = _FlakyChain(data=[{"meta": {"agentic_enabled": True}}])
        self.assertEqual(
            disp._get_agentic_meta(_FlakySupabase(ok_chain), "t-2"),
            {"agentic_enabled": True},
        )
        # Expirar el cache artificialmente (más viejo que el TTL).
        ts, meta = disp._AGENTIC_META_CACHE["t-2"]
        disp._AGENTIC_META_CACHE["t-2"] = (
            ts - disp._AGENTIC_META_TTL_SECONDS - 1, meta,
        )
        # Lectura ahora cae siempre → debe servir el stale cache.
        down_chain = _FlakyChain(fail_times=99)
        with patch("agentic.dispatcher.time.sleep"):
            meta_out = disp._get_agentic_meta(_FlakySupabase(down_chain), "t-2")
            result = _run(disp.is_tenant_agentic_enabled(_FlakySupabase(down_chain), "t-2"))
        self.assertEqual(meta_out, {"agentic_enabled": True})
        self.assertTrue(result)

    def test_error_persistente_sin_cache_degrada_a_vacio(self):
        """Sin valor cacheado previo → {} (gate fail-closed, comportamiento
        previo): solo aquí se trata como no-migrado."""
        from agentic.dispatcher import is_tenant_agentic_enabled
        chain = _FlakyChain(fail_times=99)
        with patch("agentic.dispatcher.time.sleep"):
            result = _run(is_tenant_agentic_enabled(_FlakySupabase(chain), "t-3"))
        self.assertFalse(result)
        self.assertEqual(chain.calls, 2)  # 1 intento + 1 reintento

    def test_flag_false_explicito_comportamiento_actual(self):
        """Flag explícitamente false (lectura OK) → False, como antes."""
        from agentic.dispatcher import is_tenant_agentic_enabled
        chain = _FlakyChain(data=[{"meta": {"agentic_enabled": False}}])
        result = _run(is_tenant_agentic_enabled(_FlakySupabase(chain), "t-4"))
        self.assertFalse(result)
        self.assertEqual(chain.calls, 1)  # sin error → sin reintento

    def test_row_ausente_lectura_ok_comportamiento_actual(self):
        """Row inexistente (tenant no migrado, lectura OK) → False."""
        from agentic.dispatcher import is_tenant_agentic_enabled
        chain = _FlakyChain(data=[])
        result = _run(is_tenant_agentic_enabled(_FlakySupabase(chain), "t-5"))
        self.assertFalse(result)

    def test_error_no_envenena_el_cache(self):
        """Tras un fallo persistente sin cache, una lectura posterior OK sí
        se usa (el {} defensivo no queda cacheado 30s)."""
        import agentic.dispatcher as disp
        down = _FlakyChain(fail_times=99)
        with patch("agentic.dispatcher.time.sleep"):
            self.assertEqual(disp._get_agentic_meta(_FlakySupabase(down), "t-6"), {})
        ok = _FlakyChain(data=[{"meta": {"agentic_enabled": True}}])
        self.assertEqual(
            disp._get_agentic_meta(_FlakySupabase(ok), "t-6"),
            {"agentic_enabled": True},
        )


if __name__ == "__main__":
    unittest.main()

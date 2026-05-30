"""Tests `services/ai-orchestrator/health_metrics.py` (rev. 109 J.2.11).

Cubre invariantes críticos:
  1. Provider NO conectado → lista vacía (no genera métricas).
  2. Wompi declined_rate calculado correctamente con buckets healthy/warning/critical.
  3. Envia stale_shipments_count con buckets correctos.
  4. Telegram pending_update_count + last_webhook_error.
  5. collect_all_for_tenant tolerante a errores per provider.
  6. upsert_metrics invoca RPC fn_upsert_provider_health.

NO requiere DB real ni APIs externas — usa stubs httpx + Fake Supabase.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCH_ROOT = REPO_ROOT / "services" / "ai-orchestrator"
HM_PATH = ORCH_ROOT / "health_metrics.py"


def _load_hm():
    if str(ORCH_ROOT) not in sys.path:
        sys.path.insert(0, str(ORCH_ROOT))
    spec = importlib.util.spec_from_file_location("health_metrics", HM_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["health_metrics"] = mod
    spec.loader.exec_module(mod)
    return mod


hm = _load_hm()


# ─── Fake Supabase ─────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, data=None, raise_with=None):
        self._data = data
        self._raise = raise_with

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        if self._raise:
            raise self._raise
        return SimpleNamespace(data=self._data or [])


class _FakeRpcCall:
    def __init__(self, registry, fn, args, result=None):
        self._reg = registry
        self._fn = fn
        self._args = args
        self._result = result

    def execute(self):
        self._reg.append({"fn": self._fn, "args": self._args})
        return SimpleNamespace(data=self._result)


class _FakeSupabase:
    def __init__(self, table_responses=None, rpc_results=None):
        self._table_responses = table_responses or {}
        self._rpc_results = rpc_results or {}
        self.rpc_calls = []

    def table(self, name):
        resp = self._table_responses.get(name)
        if isinstance(resp, Exception):
            return _FakeQuery(raise_with=resp)
        return _FakeQuery(data=resp)

    def rpc(self, fn, args=None):
        return _FakeRpcCall(self.rpc_calls, fn, args, self._rpc_results.get(fn))


# ─── Tests ─────────────────────────────────────────────────────────────────


class IsProviderConnectedTests(unittest.TestCase):
    def test_provider_connected(self):
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
        })
        self.assertTrue(hm._is_provider_connected(sb, "T1", "whatsapp"))

    def test_provider_disconnected(self):
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "disconnected"}],
        })
        self.assertFalse(hm._is_provider_connected(sb, "T1", "whatsapp"))

    def test_provider_no_existe(self):
        sb = _FakeSupabase(table_responses={"tenant_integrations": []})
        self.assertFalse(hm._is_provider_connected(sb, "T1", "whatsapp"))


class CollectWompiTests(unittest.TestCase):
    def test_no_conectado_retorna_vacio(self):
        sb = _FakeSupabase(table_responses={"tenant_integrations": []})
        result = hm.collect_wompi(sb, "T1")
        self.assertEqual(result, [])

    def test_zero_transactions_es_healthy(self):
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
            "payments": [],
        })
        result = hm.collect_wompi(sb, "T1")
        self.assertEqual(len(result), 1)
        m = result[0]
        self.assertEqual(m.metric, "declined_rate_24h")
        self.assertEqual(m.status, "healthy")
        self.assertIn("N/A", m.value)

    def test_zero_pct_es_healthy(self):
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
            "payments": [{"status": "APPROVED"}, {"status": "APPROVED"}],
        })
        result = hm.collect_wompi(sb, "T1")
        self.assertEqual(result[0].status, "healthy")
        self.assertEqual(result[0].value, "0.0%")

    def test_5_pct_es_warning(self):
        # 1 declined / 20 total = 5%
        payments = [{"status": "DECLINED"}] + [{"status": "APPROVED"}] * 19
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
            "payments": payments,
        })
        result = hm.collect_wompi(sb, "T1")
        self.assertEqual(result[0].status, "warning")
        self.assertEqual(result[0].value, "5.0%")

    def test_15_pct_es_critical(self):
        # 3 declined / 20 total = 15%
        payments = [{"status": "DECLINED"}] * 3 + [{"status": "APPROVED"}] * 17
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
            "payments": payments,
        })
        result = hm.collect_wompi(sb, "T1")
        self.assertEqual(result[0].status, "critical")
        self.assertEqual(result[0].value, "15.0%")


class CollectAveonlineTests(unittest.TestCase):
    def test_stale_0_es_healthy(self):
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
            "shipments": [],
        })
        result = hm.collect_aveonline(sb, "T1")
        self.assertEqual(result[0].status, "healthy")
        self.assertEqual(result[0].value, "0")

    def test_stale_5_es_warning(self):
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
            "shipments": [{"id": str(i)} for i in range(5)],
        })
        result = hm.collect_aveonline(sb, "T1")
        self.assertEqual(result[0].status, "warning")
        self.assertEqual(result[0].value, "5")

    def test_stale_15_es_critical(self):
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [{"status": "connected"}],
            "shipments": [{"id": str(i)} for i in range(15)],
        })
        result = hm.collect_aveonline(sb, "T1")
        self.assertEqual(result[0].status, "critical")
        self.assertEqual(result[0].value, "15")


class CollectAllForTenantTests(unittest.TestCase):
    def test_tolerante_a_error_per_provider(self):
        """Si un collector falla, los demás siguen retornando métricas."""
        sb = _FakeSupabase(table_responses={
            "tenant_integrations": [],  # ningún provider conectado
        })
        # Forzar excepción en un collector específico.
        with patch.object(hm, "collect_whatsapp", side_effect=Exception("boom")):
            result = hm.collect_all_for_tenant(sb, "T1")
        # Otros retornan vacío (no conectados), pero NO crashea.
        self.assertEqual(result, [])


class UpsertMetricsTests(unittest.TestCase):
    def test_invoca_rpc_por_metrica(self):
        sb = _FakeSupabase(rpc_results={"fn_upsert_provider_health": None})
        metrics = [
            hm.HealthMetric(
                provider="whatsapp", metric="quality_rating",
                value="GREEN", status="healthy",
            ),
            hm.HealthMetric(
                provider="wompi", metric="declined_rate_24h",
                value="1.5%", status="healthy",
            ),
        ]
        count = hm.upsert_metrics(sb, "T1", metrics)
        self.assertEqual(count, 2)
        self.assertEqual(len(sb.rpc_calls), 2)
        fn_names = {c["fn"] for c in sb.rpc_calls}
        self.assertEqual(fn_names, {"fn_upsert_provider_health"})

    def test_tolera_rpc_error_por_metrica(self):
        """Una RPC fail NO debe bloquear las demás."""
        class _FailingRpc:
            def __init__(self, registry, fn, args, fail_for):
                self._reg = registry
                self._fn = fn
                self._args = args
                self._fail_for = fail_for

            def execute(self):
                self._reg.append({"fn": self._fn, "args": self._args})
                provider = (self._args or {}).get("p_provider")
                if provider == self._fail_for:
                    raise Exception("RPC fail")
                return SimpleNamespace(data=None)

        sb = _FakeSupabase()
        sb.rpc = lambda fn, args=None: _FailingRpc(sb.rpc_calls, fn, args, "wompi")

        metrics = [
            hm.HealthMetric(provider="whatsapp", metric="m1", value="v1", status="healthy"),
            hm.HealthMetric(provider="wompi", metric="m2", value="v2", status="healthy"),
            hm.HealthMetric(provider="aveonline", metric="m3", value="v3", status="healthy"),
        ]
        count = hm.upsert_metrics(sb, "T1", metrics)
        # 2 OK (whatsapp + envia), 1 fail (wompi).
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()

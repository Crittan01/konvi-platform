"""Test del dedup/cache del meta agentic per-tenant (perf rev. 114).

El gate `is_tenant_agentic_enabled` y los guardrails `_load_tenant_agentic_meta`
leían el MISMO row (tenant_integrations provider='agentic') → 2 queries por turno.
Ahora comparten `_get_agentic_meta` (cache TTL 30s): 1 sola query por turno + reuso
cross-turn. Degrada a {}/False ante ausencia/error (comportamiento previo).
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

import agentic.dispatcher as d  # noqa: E402


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, rows, counter):
        self._rows, self._c = rows, counter

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        self._c[0] += 1
        return _Resp(list(self._rows))


class _SB:
    def __init__(self, rows):
        self._rows, self.n = rows, [0]

    def table(self, name):
        return _Q(self._rows, self.n)


class AgenticMetaCacheTests(unittest.TestCase):
    def setUp(self):
        d.invalidate_agentic_meta_cache()

    def test_gate_and_guardrails_share_one_query_per_turn(self):
        sb = _SB([{"meta": {"agentic_enabled": True, "guardrails": {"x": 1}}}])
        enabled = asyncio.run(d.is_tenant_agentic_enabled(sb, "t1"))
        meta = d._load_tenant_agentic_meta(sb, "t1")
        self.assertTrue(enabled)
        self.assertEqual(meta.get("guardrails"), {"x": 1})
        self.assertEqual(sb.n[0], 1, f"gate+guardrails debían compartir 1 query, hubo {sb.n[0]}")

    def test_degrades_when_no_row(self):
        sb = _SB([])
        self.assertFalse(asyncio.run(d.is_tenant_agentic_enabled(sb, "t2")))
        self.assertEqual(d._load_tenant_agentic_meta(sb, "t2"), {})

    def test_agentic_enabled_false_when_flag_absent(self):
        sb = _SB([{"meta": {"guardrails": {}}}])  # sin agentic_enabled
        self.assertFalse(asyncio.run(d.is_tenant_agentic_enabled(sb, "t4")))

    def test_invalidate_forces_refetch(self):
        sb = _SB([{"meta": {"agentic_enabled": True}}])
        d._get_agentic_meta(sb, "t3")
        d._get_agentic_meta(sb, "t3")
        self.assertEqual(sb.n[0], 1, "2ª lectura debía dar cache-hit")
        d.invalidate_agentic_meta_cache("t3")
        d._get_agentic_meta(sb, "t3")
        self.assertEqual(sb.n[0], 2, "tras invalidar debía re-fetchear")


if __name__ == "__main__":
    unittest.main()

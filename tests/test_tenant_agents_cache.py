"""Tests del cache de ai_agents + dedup de get_active_agent (perf rev. 114).

get_active_agent hacía 2 queries por turno (list_tenant_agents + query default).
Ahora deriva el default de la lista (cacheada 30s) → 1 query. Preserva: solo un
`is_default` es el default; si no hay, fallback Sara Camila. Error → [] sin cachear.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

import lib.tenant_agents as ta  # noqa: E402


class _Q:
    def __init__(self, rows, counter):
        self._rows, self._c = rows, counter

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        self._c[0] += 1
        return SimpleNamespace(data=list(self._rows))


class _SB:
    def __init__(self, rows):
        self._rows, self.n = rows, [0]

    def table(self, name):
        return _Q(self._rows, self.n)


class TenantAgentsCacheTests(unittest.TestCase):
    def setUp(self):
        ta.invalidate_agents_cache()

    def test_get_active_agent_uses_one_query(self):
        # Antes: 2 queries (list + default). Ahora: 1 (list cacheada, default derivado).
        sb = _SB([{"name": "Andrés", "role": "support", "is_default": True}])
        a = ta.get_active_agent(sb, tenant_id="t1", inbound_text="hola")
        self.assertEqual(a["name"], "Andrés")
        self.assertEqual(sb.n[0], 1, f"esperaba 1 query, hubo {sb.n[0]}")

    def test_list_cache_hit_no_requery(self):
        sb = _SB([{"name": "X", "is_default": True}])
        ta.list_tenant_agents(sb, tenant_id="t2")
        ta.list_tenant_agents(sb, tenant_id="t2")
        self.assertEqual(sb.n[0], 1, "la 2ª lectura debía dar cache-hit")

    def test_default_is_the_is_default_row(self):
        sb = _SB([
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Otro", "role": "support", "is_default": False},
        ])
        a = ta.get_active_agent(sb, tenant_id="t3")  # sin inbound → default
        self.assertEqual(a["name"], "Sara")

    def test_fallback_when_no_is_default(self):
        # Preserva comportamiento: la query previa filtraba is_default=True → si no
        # hay ninguno, fallback (NO devolver un no-default).
        sb = _SB([{"name": "NoDefault", "role": "sales", "is_default": False}])
        a = ta.get_active_agent(sb, tenant_id="t4")
        self.assertEqual(a["name"], "Sara Camila")

    def test_empty_list_fallback(self):
        a = ta.get_active_agent(_SB([]), tenant_id="t5")
        self.assertEqual(a["name"], "Sara Camila")

    def test_error_not_cached_self_heals(self):
        class _ErrSB:
            def table(self, name):
                raise RuntimeError("relation does not exist")

        self.assertEqual(ta.list_tenant_agents(_ErrSB(), tenant_id="t6"), [])
        sb = _SB([{"name": "Rec", "is_default": True}])
        self.assertEqual(ta.list_tenant_agents(sb, tenant_id="t6")[0]["name"], "Rec")

    def test_invalidate_forces_refetch(self):
        self.assertEqual(
            ta.list_tenant_agents(_SB([{"name": "A", "is_default": True}]), tenant_id="t7")[0]["name"],
            "A",
        )
        ta.invalidate_agents_cache("t7")
        self.assertEqual(
            ta.list_tenant_agents(_SB([{"name": "B", "is_default": True}]), tenant_id="t7")[0]["name"],
            "B",
        )


if __name__ == "__main__":
    unittest.main()

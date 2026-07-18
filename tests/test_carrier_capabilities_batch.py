"""Tests del batch de carrier_capabilities (perf rev. 114 — colapso N+1).

Blinda el refactor de `get_all_capabilities_for_tenant`:
  • colapsa de N+1 a 3 queries (canonical + overrides + gate) — invariante de
    performance: el nº de queries NO crece con el nº de carriers;
  • output idéntico al composer per-carrier (override, gate COD, sort);
  • puebla el cache per-carrier (los lookups single subsiguientes dan hit).

El gate COD (`is_method_enabled`) se mockea para aislar la lógica de este módulo
y hacer el conteo de queries determinista (su propia query va aparte + cacheada).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

import lib.carrier_capabilities as cc  # noqa: E402

_GATE = "lib.tenant_payment_methods.is_method_enabled"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Query builder chainable que cuenta execute() y devuelve data por tabla."""

    def __init__(self, table, store, counter):
        self._table, self._store, self._counter = table, store, counter
        self._single = False

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def ilike(self, *a, **k):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        self._counter[0] += 1
        rows = list(self._store.get(self._table, []))
        if self._single:
            return _Resp(rows[0] if rows else None)
        return _Resp(rows)


class _FakeSupabase:
    def __init__(self, store):
        self._store = store
        self.n = [0]  # contador de execute()

    def table(self, name):
        return _Query(name, self._store, self.n)


def _sb(carriers, overrides=None):
    return _FakeSupabase({
        "aveonline_carrier_capabilities": carriers,
        "tenant_carriers": overrides or [],
    })


class CarrierCapabilitiesBatchTests(unittest.TestCase):
    def setUp(self):
        cc.invalidate_cache()

    @patch(_GATE, return_value=True)
    def test_query_count_constant_regardless_of_carrier_count(self, _m):
        # Invariante de perf: 5 carriers → sigue siendo 2 queries del módulo
        # (canonical + tenant_carriers); el gate está mockeado. NO N+1.
        carriers = [
            {"carrier_name": f"C{i}", "supports_cod": bool(i % 2)}
            for i in range(5)
        ]
        sb = _sb(carriers)
        caps = cc.get_all_capabilities_for_tenant(sb, tenant_id="t1")
        self.assertEqual(len(caps), 5)
        self.assertEqual(sb.n[0], 2, f"esperaba 2 queries (canonical+overrides), hubo {sb.n[0]} — ¿N+1?")

    @patch(_GATE, return_value=True)
    def test_override_composition_and_sort(self, _m):
        carriers = [
            {"carrier_name": "SERVIENTREGA", "supports_cod": True, "cod_min_recaudo_cop": 20000},
            {"carrier_name": "TCC", "supports_cod": False},
        ]
        overrides = [{
            "carrier_code": "servientrega", "enabled": False,
            "display_label": "Servi", "cod_override": "force_disable",
        }]
        caps = cc.get_all_capabilities_for_tenant(_sb(carriers, overrides), tenant_id="t1")
        by = {c.carrier_name: c for c in caps}

        serv = by["SERVIENTREGA"]
        self.assertFalse(serv.supports_cod, "force_disable debe apagar COD")
        self.assertEqual(serv.display_label, "Servi")
        self.assertFalse(serv.enabled_for_tenant)
        self.assertEqual(serv.cod_override, "force_disable")

        tcc = by["TCC"]
        self.assertFalse(tcc.supports_cod)
        self.assertTrue(tcc.enabled_for_tenant, "default enabled=True sin override")
        self.assertIsNone(tcc.display_label)

        # Sort: ambos supports_cod False → por carrier_name asc.
        self.assertEqual([c.carrier_name for c in caps], ["SERVIENTREGA", "TCC"])

    @patch(_GATE, return_value=False)
    def test_tenant_cod_gate_off_beats_force_enable(self, _m):
        # El gate tenant-level (COD globalmente off) gana sobre force_enable.
        carriers = [{"carrier_name": "X", "supports_cod": True}]
        overrides = [{"carrier_code": "x", "cod_override": "force_enable"}]
        caps = cc.get_all_capabilities_for_tenant(_sb(carriers, overrides), tenant_id="t1")
        self.assertFalse(caps[0].supports_cod)

    @patch(_GATE, return_value=True)
    def test_batch_warms_single_lookup_cache(self, _m):
        carriers = [{"carrier_name": "SERVIENTREGA", "supports_cod": True}]
        sb = _sb(carriers)
        cc.get_all_capabilities_for_tenant(sb, tenant_id="t1")
        n_after_batch = sb.n[0]
        # El lookup single del mismo carrier debe dar cache-hit (0 queries nuevas).
        cap = cc.get_effective_carrier_capability(sb, tenant_id="t1", carrier_name="Servientrega")
        self.assertEqual(sb.n[0], n_after_batch, "el single debió pegar al cache poblado por el batch")
        self.assertEqual(cap.carrier_name, "SERVIENTREGA")

    @patch(_GATE, return_value=True)
    def test_unknown_and_empty(self, _m):
        # Sin carriers → lista vacía, sin explotar.
        self.assertEqual(cc.get_all_capabilities_for_tenant(_sb([]), tenant_id="t1"), [])


if __name__ == "__main__":
    unittest.main()

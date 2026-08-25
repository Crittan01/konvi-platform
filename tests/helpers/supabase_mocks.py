"""Factories de mocks de Supabase compartidos por la suite (sin efectos
colaterales: este módulo NO toca sys.path ni importa servicios).

Regla de higiene de la suite (lección xdist M2.3, 2026-08-25): las factories
compartidas viven en `tests/helpers/`, NO en módulos de test — los test modules
tienen side effects de colección (`sys.path.insert`, imports de servicios) y
un import test→test puede ejecutarlos en un orden que deje bindings huérfanos
de sys.modules (colisión `integrations.*` api↔orchestrator, purgada por
`_purge_foreign_integrations` de otros archivos).
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock


def make_orders_payments_supabase_mock(state):
    """Mock de supabase con cadenas explícitas inspeccionables (orders/payments).

    Devuelve (supabase, probes) donde probes expone:
      - payments_select: cadena select().eq().eq().eq().gte().order().limit().execute()
      - payments_insert: método insert de la tabla payments
      - orders_update:   método update de la tabla orders

    `state` soporta: "orders_single", "orders_update", "payments_select",
    "payments_insert".
    """
    supabase = MagicMock()

    orders_q = MagicMock(name="orders_table")
    single = MagicMock()
    single.execute.return_value = types.SimpleNamespace(data=state.get("orders_single"))
    eq_chain = MagicMock()
    eq_chain.maybe_single.return_value = single
    eq_chain.single.return_value = single
    eq_chain.eq.return_value = eq_chain
    select_chain = MagicMock()
    select_chain.eq.return_value = eq_chain
    orders_q.select.return_value = select_chain
    upd = MagicMock()
    upd.eq.return_value = upd
    upd.execute.return_value = types.SimpleNamespace(data=state.get("orders_update", []))
    orders_q.update.return_value = upd

    payments_q = MagicMock(name="payments_table")
    sel = MagicMock(name="payments_select_chain")
    sel.eq.return_value = sel
    sel.gte.return_value = sel
    sel.order.return_value = sel
    sel.limit.return_value = sel
    sel.execute.return_value = types.SimpleNamespace(
        data=state.get("payments_select", [])
    )
    payments_q.select.return_value = sel
    ins_execute = MagicMock()
    ins_execute.execute.return_value = types.SimpleNamespace(
        data=state.get("payments_insert", [])
    )
    payments_q.insert.return_value = ins_execute

    def table_side_effect(name):
        if name == "orders":
            return orders_q
        if name == "payments":
            return payments_q
        raise AssertionError(f"Tabla inesperada: {name}")

    supabase.table.side_effect = table_side_effect
    probes = {
        "payments_select": sel,
        "payments_insert": payments_q.insert,
        "orders_update": orders_q.update,
    }
    return supabase, probes

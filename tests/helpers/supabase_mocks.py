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


# ─── Fake genérico con respuestas por tabla (B-2 Fase 0, 2026-08-28) ─────────
# Lo comparten tests/agentic/test_turn_context.py y test_h11_claim_flow.py.
# SIN side effects de colección (regla xdist M2.3): ni sys.path ni imports de
# servicios a nivel módulo.


class FakeTableChain:
    """Cadena supabase mínima: todo método devuelve self salvo execute()."""

    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._single = False

    def __getattr__(self, name):
        if name == "execute":
            return self._execute
        if name == "single":
            def _single(*a, **k):
                self._single = True
                return self
            return _single

        def _m(*args, **kwargs):
            self._fake._record(self._table, name, args, kwargs)
            return self
        return _m

    def _execute(self):
        return self._fake._execute(self._table, single=self._single)


class FakeSupabase:
    """Fake con respuestas por tabla + registro de llamadas/updates.

    `data[table]` puede ser una lista de filas (respuesta fija) o una lista de
    LISTAS (cola: cada execute() consume la siguiente — para simular cambios de
    estado entre lecturas). `counts[table]` fija el count exact/head.
    """

    def __init__(self):
        self.data = {}
        self.counts = {}
        self.calls = []      # (table, method)
        self.updates = []    # (table, fields)

    def table(self, name):
        return FakeTableChain(self, name)

    def _record(self, table, method, args, kwargs):
        self.calls.append((table, method))
        if method == "update" and args:
            self.updates.append((table, args[0]))
            # Aplicar el update a las filas fijas para que re-lecturas lo vean.
            for row in self.data.get(table, []):
                if isinstance(row, dict):
                    row.update(args[0])

    def _execute(self, table, single=False):
        rows = self.data.get(table, [])
        if rows and isinstance(rows[0], list):
            # Cola de respuestas: consumir la primera (o repetir la última).
            rows = rows.pop(0) if len(rows) > 1 else rows[0]
        if single:
            # Paridad con postgrest .single(): 0 filas → excepción.
            if not rows:
                raise Exception("PGRST116: 0 rows")
            return types.SimpleNamespace(data=rows[0], count=1)
        count = self.counts.get(table, len(rows))
        return types.SimpleNamespace(data=rows, count=count)

    def select_count(self, table):
        return sum(
            1 for t, m in self.calls if t == table and m == "select"
        )

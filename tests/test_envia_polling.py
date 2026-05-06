"""Tests envia_polling cron (rev. 105 Sem 4 H.2.3 / MA-9).

Cubre:
  1. _extract_status_from_envia_response mapping correcto
  2. _select_polling_candidates filtra por status + last_polled_at
  3. poll_pending_shipments status changed → update + cart_event-ready
  4. poll_pending_shipments status sin cambio → solo last_polled_at
  5. Track Envia falla → marca last_polled_at pero NO update status
  6. Idempotency F.4: si webhook ya procesó el cambio, skip
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
api_root = REPO_ROOT / "services" / "api"
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))


# Cargar el módulo lib.envia_polling — por ser parte del paquete lib/, lo
# cargamos como módulo aislado para evitar dependencias circulares con el
# resto del paquete services/api.
def _load_envia_polling():
    if "_envia_polling" in sys.modules:
        return sys.modules["_envia_polling"]
    spec = importlib.util.spec_from_file_location(
        "_envia_polling",
        REPO_ROOT / "services" / "api" / "lib" / "envia_polling.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_envia_polling"] = mod
    # webhook_dedup import en runtime — necesitamos también disponible.
    if "webhook_dedup" not in sys.modules:
        spec2 = importlib.util.spec_from_file_location(
            "webhook_dedup",
            REPO_ROOT / "services" / "api" / "lib" / "webhook_dedup.py",
        )
        mod2 = importlib.util.module_from_spec(spec2)
        sys.modules["webhook_dedup"] = mod2
        spec2.loader.exec_module(mod2)
    spec.loader.exec_module(mod)
    return mod


# Stub el sub-import .webhook_dedup que envia_polling hace en runtime.
import types

ep_module_pkg = types.ModuleType("_envia_polling_pkg")
sys.modules.setdefault("_envia_polling_pkg", ep_module_pkg)


ep = _load_envia_polling()


# ─── _extract_status_from_envia_response ──────────────────────────────────────

class ExtractStatusTests(unittest.TestCase):
    def test_response_vacio_es_none(self):
        self.assertIsNone(ep._extract_status_from_envia_response(None))
        self.assertIsNone(ep._extract_status_from_envia_response({}))
        self.assertIsNone(ep._extract_status_from_envia_response({"data": []}))

    def test_status_mapping(self):
        cases = [
            ("created", "labeled"),
            ("picked_up", "picked_up"),
            ("in_transit", "in_transit"),
            ("on_route", "in_transit"),
            ("delivered", "delivered"),
            ("cancelled", "cancelled"),
            ("canceled", "cancelled"),
            ("returned", "returned"),
            ("failed", "failed"),
            ("lost", "failed"),
        ]
        for envia_status, expected in cases:
            with self.subTest(envia_status=envia_status):
                resp = {"data": [{"status": envia_status}]}
                self.assertEqual(
                    ep._extract_status_from_envia_response(resp),
                    expected,
                )

    def test_status_uppercase_se_normaliza(self):
        resp = {"data": [{"status": "  IN_TRANSIT  "}]}
        self.assertEqual(
            ep._extract_status_from_envia_response(resp),
            "in_transit",
        )

    def test_status_desconocido_se_retorna_lowercase(self):
        resp = {"data": [{"status": "EXOTIC_STATUS"}]}
        self.assertEqual(
            ep._extract_status_from_envia_response(resp),
            "exotic_status",
        )


# ─── Fake Supabase con shipments table ────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, str, Any]] = []
        self._cols = "*"
        self._limit: int | None = None
        self._not_chain = False

    def select(self, cols: str = "*"):
        q = _FakeQuery(self._store, op="select")
        q._cols = cols
        return q

    def update(self, payload: dict[str, Any]):
        return _FakeQuery(self._store, op="update", payload=payload)

    def eq(self, col: str, val: Any):
        self._filters.append((col, "eq", val))
        return self

    def in_(self, col: str, vals: list[Any]):
        self._filters.append((col, "in", set(vals)))
        return self

    def gte(self, col: str, val: Any):
        self._filters.append((col, "gte", val))
        return self

    @property
    def not_(self):
        self._not_chain = True
        return self

    def is_(self, col: str, val: Any):
        op = "is_not" if self._not_chain else "is"
        self._not_chain = False
        self._filters.append((col, op, val))
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for col, op, val in self._filters:
            row_val = row.get(col)
            if op == "eq":
                if row_val != val:
                    return False
            elif op == "in":
                if row_val not in val:
                    return False
            elif op == "gte":
                if row_val is None or str(row_val) < str(val):
                    return False
            elif op == "is":
                if val == "null" and row_val is not None:
                    return False
            elif op == "is_not":
                if val == "null" and row_val is None:
                    return False
        return True

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            if self._limit:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)
        if self._op == "update":
            updated = []
            for row in self._store:
                if self._matches(row):
                    for k, v in self._payload.items():
                        row[k] = v
                    updated.append(row)
            return SimpleNamespace(data=updated)
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeRpc:
    def __init__(self, name: str, args: dict, dedup_seen: set):
        self._name = name
        self._args = args
        self._dedup = dedup_seen

    def execute(self):
        if self._name == "webhook_event_check_or_register":
            key = (self._args["p_integration"], self._args["p_event_uid"])
            if key in self._dedup:
                return SimpleNamespace(data=True)
            self._dedup.add(key)
            return SimpleNamespace(data=False)
        return SimpleNamespace(data=False)


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict[str, Any]]] = {"shipments": []}
        self._dedup_seen: set = set()

    def table(self, name: str):
        return _FakeQuery(self._tables[name])

    def rpc(self, name: str, args: dict):
        return _FakeRpc(name, args, self._dedup_seen)


class _FakeEnviaClient:
    def __init__(self, response: dict | None = None, raise_exc: Exception | None = None):
        self._response = response
        self._raise = raise_exc
        self.calls: list[list[str]] = []

    async def track_shipments(self, tracking_numbers: list[str]) -> dict:
        self.calls.append(list(tracking_numbers))
        if self._raise:
            raise self._raise
        return self._response or {}


# ─── poll_pending_shipments ─────────────────────────────────────────────────

class PollPendingShipmentsTests(unittest.IsolatedAsyncioTestCase):
    def _seed(self, status: str = "in_transit", last_polled: str | None = None,
              created_days_ago: int = 1):
        sb = _FakeSupabase()
        created = (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()
        sb._tables["shipments"].append({
            "id": "ship-1",
            "tenant_id": "tenant-A",
            "order_id": "order-1",
            "tracking_number": "TRK-001",
            "status": status,
            "envia_shipment_id": "ESH-1",
            "last_polled_at": last_polled,
            "created_at": created,
        })
        return sb

    async def test_status_no_cambio_solo_marca_polled(self):
        sb = self._seed(status="in_transit")
        envia = _FakeEnviaClient(response={"data": [{"status": "in_transit"}]})
        result = await ep.poll_pending_shipments(
            sb, envia_factory=lambda tid: envia,
        )
        self.assertEqual(result.polled_count, 1)
        self.assertEqual(result.status_changed_count, 0)
        # last_polled_at fue actualizado.
        self.assertIsNotNone(sb._tables["shipments"][0]["last_polled_at"])

    async def test_status_cambio_actualiza_y_cuenta(self):
        sb = self._seed(status="in_transit")
        envia = _FakeEnviaClient(response={"data": [{"status": "delivered"}]})
        result = await ep.poll_pending_shipments(
            sb, envia_factory=lambda tid: envia,
        )
        self.assertEqual(result.polled_count, 1)
        self.assertEqual(result.status_changed_count, 1)
        self.assertEqual(sb._tables["shipments"][0]["status"], "delivered")
        self.assertIn("ship-1", result.shipment_ids_updated)
        self.assertAlmostEqual(result.diff_rate, 1.0)

    async def test_envia_falla_marca_polled_no_cambia_status(self):
        sb = self._seed(status="in_transit")
        envia = _FakeEnviaClient(raise_exc=Exception("Envia 503"))
        result = await ep.poll_pending_shipments(
            sb, envia_factory=lambda tid: envia,
        )
        self.assertEqual(result.errors_count, 1)
        # Status NO cambió.
        self.assertEqual(sb._tables["shipments"][0]["status"], "in_transit")
        # last_polled_at SÍ se actualizó (para no quedar en loop).
        self.assertIsNotNone(sb._tables["shipments"][0]["last_polled_at"])

    async def test_terminal_status_no_es_candidate(self):
        sb = self._seed(status="delivered")  # ya terminal
        envia = _FakeEnviaClient(response={"data": [{"status": "delivered"}]})
        result = await ep.poll_pending_shipments(
            sb, envia_factory=lambda tid: envia,
        )
        self.assertEqual(result.polled_count, 0)
        # Envia NO fue invocado.
        self.assertEqual(len(envia.calls), 0)

    async def test_recientemente_polled_no_es_candidate(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        sb = self._seed(status="in_transit", last_polled=recent)
        envia = _FakeEnviaClient(response={"data": [{"status": "in_transit"}]})
        result = await ep.poll_pending_shipments(
            sb, envia_factory=lambda tid: envia, poll_interval_hours=6,
        )
        self.assertEqual(result.polled_count, 0)

    async def test_idempotency_skip_si_webhook_ya_proceso(self):
        sb = self._seed(status="in_transit")
        # Pre-marcar event_uid como visto en F.4 dedup.
        event_uid = "poll:ship-1:delivered"
        sb._dedup_seen.add(("envia", event_uid))

        envia = _FakeEnviaClient(response={"data": [{"status": "delivered"}]})
        result = await ep.poll_pending_shipments(
            sb, envia_factory=lambda tid: envia,
        )
        # Polled pero skip duplicate.
        self.assertEqual(result.polled_count, 1)
        self.assertEqual(result.skipped_duplicate_count, 1)
        # Status NO se actualizó porque webhook ya lo procesó.
        self.assertEqual(sb._tables["shipments"][0]["status"], "in_transit")

    async def test_factory_falla_cuenta_error(self):
        sb = self._seed(status="in_transit")

        def _bad_factory(tenant_id):
            raise RuntimeError("token resolver failed")

        result = await ep.poll_pending_shipments(
            sb, envia_factory=_bad_factory,
        )
        self.assertEqual(result.errors_count, 1)
        self.assertEqual(result.status_changed_count, 0)


class DiffRateTests(unittest.TestCase):
    def test_diff_rate_zero_polled(self):
        r = ep.PollingResult()
        self.assertEqual(r.diff_rate, 0.0)

    def test_diff_rate_calculation(self):
        r = ep.PollingResult(polled_count=10, status_changed_count=2)
        self.assertAlmostEqual(r.diff_rate, 0.2)


if __name__ == "__main__":
    unittest.main()

"""Tests procesador webhook Envia (rev. 105 Sem 4 H.2.2 Fase B).

Cubre:
  1. map_envia_status_text — mapping correcto incluido casos empíricos
     2026-05-07 ('Created' capitalizado, 'In Transit' con espacio)
  2. _validate_origin — UA + IP allowlist
  3. _process_status_update:
     - shipment found + status change → outcome='updated'
     - shipment found + mismo status → outcome='no_change'
     - shipment NOT found → outcome='skipped' (cross-tenant defense)
     - missing fields → outcome='skipped' reason='missing_tracking_or_status'
     - status unmappable → outcome='skipped'
     - terminal status → is_terminal=True
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
api_root = REPO_ROOT / "services" / "api"
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))


def _load_module(name: str, rel_path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / rel_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Carga lib.envia_polling (donde vive map_envia_status_text).
ep = _load_module("envia_polling", "services/api/lib/envia_polling.py")


# Carga el handler envia_webhook. Necesita stubs para evitar imports
# pesados (FastAPI/Supabase/auth) — solo usamos las funciones puras.
def _load_envia_webhook_router():
    """Carga routers.envia_webhook reusando los módulos reales del repo.

    Solo necesitamos las funciones puras (`_validate_origin`,
    `_process_status_update`) — el handler async POST no se ejecuta.
    Los lazy imports adentro del handler (`webhook_secret_manager`,
    `webhook_dedup`) NO se evalúan hasta que el endpoint se invoca.

    NO stubeamos `dependencies.auth` porque otros tests importan de ahí
    el módulo real (`get_current_tenant`, etc.) y compartimos sys.modules
    en la sesión pytest.
    """
    if "envia_webhook_router" in sys.modules:
        return sys.modules["envia_webhook_router"]

    # Asegurar que `dependencies` y `lib` cargan desde el repo real.
    # services/api/* ya está en sys.path (api_root insertado arriba), así
    # que `from dependencies.auth import _get_service_client` resuelve al
    # archivo real services/api/dependencies/auth.py.

    # `lib.envia_polling` → reusar el módulo `ep` ya cargado pero
    # registrándolo bajo el nombre canónico que usa el handler.
    sys.modules.setdefault("lib", types.ModuleType("lib"))
    sys.modules["lib.envia_polling"] = ep

    spec = importlib.util.spec_from_file_location(
        "envia_webhook_router",
        REPO_ROOT / "services" / "api" / "routers" / "envia_webhook.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["envia_webhook_router"] = mod
    spec.loader.exec_module(mod)
    return mod


router_mod = _load_envia_webhook_router()


# ─── map_envia_status_text ───────────────────────────────────────────────────

class MapEnviaStatusTextTests(unittest.TestCase):
    def test_empirical_capitalized_created(self):
        """Caso empírico 2026-05-07: webhook payload llegó con 'Created'."""
        self.assertEqual(ep.map_envia_status_text("Created"), "labeled")

    def test_lowercase_created(self):
        self.assertEqual(ep.map_envia_status_text("created"), "labeled")

    def test_known_statuses(self):
        cases = [
            ("Created", "labeled"),
            ("Picked Up", "picked_up"),
            ("picked_up", "picked_up"),
            ("In Transit", "in_transit"),
            ("in_transit", "in_transit"),
            ("On Route", "in_transit"),
            ("Out for Delivery", "in_transit"),
            ("Delivered", "delivered"),
            ("Cancelled", "cancelled"),
            ("Canceled", "cancelled"),
            ("Returned", "returned"),
            ("Failed", "failed"),
            ("Lost", "failed"),
        ]
        for envia_status, expected in cases:
            with self.subTest(envia_status=envia_status):
                self.assertEqual(
                    ep.map_envia_status_text(envia_status), expected,
                )

    def test_whitespace_tolerated(self):
        self.assertEqual(ep.map_envia_status_text("  Created  "), "labeled")
        self.assertEqual(ep.map_envia_status_text("DELIVERED"), "delivered")

    def test_empty_returns_none(self):
        self.assertIsNone(ep.map_envia_status_text(None))
        self.assertIsNone(ep.map_envia_status_text(""))
        self.assertIsNone(ep.map_envia_status_text("   "))
        self.assertIsNone(ep.map_envia_status_text(123))  # not str

    def test_unknown_returns_lowered_raw(self):
        # No truena — devuelve raw lowercased para que upstream emita
        # warning sin perder data.
        self.assertEqual(ep.map_envia_status_text("WeirdStatus"), "weirdstatus")


# ─── _validate_origin ────────────────────────────────────────────────────────

class ValidateOriginTests(unittest.TestCase):
    def test_official_ua_and_ip(self):
        ok, reason = router_mod._validate_origin(
            {"user-agent": "Envia-Carriers"}, "3.211.106.119",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_ua_with_extra_text(self):
        # User-Agent puede traer subpath/version — solo verificamos contains.
        ok, _ = router_mod._validate_origin(
            {"user-agent": "Envia-Carriers/1.0 (curl)"}, "3.211.106.119",
        )
        self.assertTrue(ok)

    def test_ua_missing_fails_soft(self):
        ok, reason = router_mod._validate_origin(
            {"user-agent": "Mozilla"}, "3.211.106.119",
        )
        self.assertFalse(ok)
        self.assertIn("UA mismatch", reason)

    def test_ip_not_in_allowlist_fails_soft(self):
        ok, reason = router_mod._validate_origin(
            {"user-agent": "Envia-Carriers"}, "1.2.3.4",
        )
        self.assertFalse(ok)
        self.assertIn("IP not in allowlist", reason)

    def test_no_ip_passes_ua_check(self):
        # Si no resolvimos IP (ngrok, edge cases), no bloqueamos por IP.
        ok, _ = router_mod._validate_origin(
            {"user-agent": "Envia-Carriers"}, None,
        )
        self.assertTrue(ok)


# ─── _process_status_update ──────────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, str, Any]] = []
        self._cols = "*"
        self._limit: int | None = None

    def select(self, cols: str = "*"):
        q = _FakeQuery(self._store, op="select")
        q._cols = cols
        return q

    def update(self, payload: dict[str, Any]):
        return _FakeQuery(self._store, op="update", payload=payload)

    def eq(self, col: str, val: Any):
        self._filters.append((col, "eq", val))
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for col, op, val in self._filters:
            if op == "eq" and row.get(col) != val:
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


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict[str, Any]]] = {"shipments": []}

    def table(self, name: str):
        return _FakeQuery(self._tables[name])


class ProcessStatusUpdateTests(unittest.TestCase):
    def _seed(self, status: str = "labeled", carrier: str | None = "fedex"):
        sb = _FakeSupabase()
        sb._tables["shipments"].append({
            "id": "ship-1",
            "tenant_id": "tenant-A",
            "order_id": "order-1",
            "tracking_number": "794813020143",
            "carrier": carrier,
            "status": status,
        })
        return sb

    def test_payload_canonico_status_change_updates(self):
        sb = self._seed(status="labeled")
        result = router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "tracking_number": "794813020143",
             "shipment_status": "Delivered"},
        )
        self.assertEqual(result["outcome"], "updated")
        self.assertEqual(result["old_status"], "labeled")
        self.assertEqual(result["new_status"], "delivered")
        self.assertTrue(result["is_terminal"])
        # Verifica que la fila se actualizó.
        self.assertEqual(sb._tables["shipments"][0]["status"], "delivered")

    def test_status_no_cambio_no_actualiza(self):
        sb = self._seed(status="labeled")
        result = router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "tracking_number": "794813020143",
             "shipment_status": "Created"},   # mapea a 'labeled'
        )
        self.assertEqual(result["outcome"], "no_change")
        self.assertEqual(result["status"], "labeled")

    def test_shipment_not_found_skips(self):
        """Defensa cross-tenant: tracking de OTRO tenant no procesa nada."""
        sb = self._seed(status="labeled")
        result = router_mod._process_status_update(
            sb, "tenant-B",  # <-- distinto tenant
            {"carrier": "fedex", "tracking_number": "794813020143",
             "shipment_status": "Delivered"},
        )
        self.assertEqual(result["outcome"], "skipped")
        self.assertEqual(result["reason"], "shipment_not_found")
        # La fila del tenant-A NO se modificó.
        self.assertEqual(sb._tables["shipments"][0]["status"], "labeled")

    def test_missing_tracking_skips(self):
        sb = self._seed()
        result = router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "shipment_status": "Delivered"},
        )
        self.assertEqual(result["outcome"], "skipped")
        self.assertEqual(result["reason"], "missing_tracking_or_status")

    def test_missing_status_skips(self):
        sb = self._seed()
        result = router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "tracking_number": "794813020143"},
        )
        self.assertEqual(result["outcome"], "skipped")
        self.assertEqual(result["reason"], "missing_tracking_or_status")

    def test_terminal_delivered_marca_is_terminal(self):
        sb = self._seed(status="in_transit")
        result = router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "tracking_number": "794813020143",
             "shipment_status": "Delivered"},
        )
        self.assertTrue(result["is_terminal"])

    def test_terminal_cancelled_marca_is_terminal(self):
        sb = self._seed(status="labeled")
        result = router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "tracking_number": "794813020143",
             "shipment_status": "Cancelled"},
        )
        self.assertEqual(result["new_status"], "cancelled")
        self.assertTrue(result["is_terminal"])

    def test_in_transit_no_es_terminal(self):
        sb = self._seed(status="picked_up")
        result = router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "tracking_number": "794813020143",
             "shipment_status": "In Transit"},
        )
        self.assertEqual(result["new_status"], "in_transit")
        self.assertFalse(result["is_terminal"])

    def test_carrier_se_persiste_si_falta_en_row(self):
        sb = self._seed(status="labeled", carrier=None)
        router_mod._process_status_update(
            sb, "tenant-A",
            {"carrier": "fedex", "tracking_number": "794813020143",
             "shipment_status": "Delivered"},
        )
        self.assertEqual(sb._tables["shipments"][0]["carrier"], "fedex")

    def test_payload_vacio_skips(self):
        sb = self._seed()
        result = router_mod._process_status_update(sb, "tenant-A", {})
        self.assertEqual(result["outcome"], "skipped")


if __name__ == "__main__":
    unittest.main()

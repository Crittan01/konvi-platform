"""NIVEL 5 finiquito — A3 (cotizador columns) + A4 (claims status alignment).

A3 (audit §3 BUG#1): shipping.py insertaba columnas provider/rates_snapshot
inexistentes en `shipments` → insert fallaba 100%, historial Cotizador vacío.
Fix: drop provider, rates_snapshot→quote_response (columna real).

A4 (audit §3 BUG#2): status reclamos desalineado API↔UI → 3 botones rotos (422).
Fix: vocabulario canónico unificado {open, investigating, resolved, refunded,
rejected, cancelled} en API router + tool agentic + CHECK constraint.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

REPO = Path("/home/ansible/workspaces/konvi-platform")


class A3ShippingColumnsTests(unittest.TestCase):
    """El insert del Cotizador usa SOLO columnas reales de shipments."""

    # Columnas reales verificadas en la DB remota. pickup_id + last_polled_at
    # dropeadas 2026-07-02 (F7: Envia-legacy, Aveonline usa webhooks no polling).
    REAL_SHIPMENTS_COLUMNS = {
        "id", "tenant_id", "order_id", "status", "carrier", "service",
        "origin_address", "destination_address", "parcels", "quote_response",
        "selected_rate", "label_url", "tracking_number", "tracking_url",
        "estimated_delivery", "created_at", "updated_at",
    }

    def setUp(self):
        self.src = (REPO / "services/api/routers/shipping.py").read_text()

    def test_no_provider_column_in_shipments_insert(self):
        # `provider` NO existe en shipments → no debe estar en el insert.
        insert_idx = self.src.find('.table("shipments").insert({')
        self.assertGreater(insert_idx, 0)
        insert_block = self.src[insert_idx:insert_idx + 400]
        self.assertNotIn('"provider"', insert_block)

    def test_no_rates_snapshot_uses_quote_response(self):
        insert_idx = self.src.find('.table("shipments").insert({')
        insert_block = self.src[insert_idx:insert_idx + 400]
        self.assertNotIn('"rates_snapshot"', insert_block)
        self.assertIn('"quote_response"', insert_block)


class A4ClaimsStatusTests(unittest.TestCase):
    """Vocabulario de status alineado entre API router, tool agentic y UI."""

    CANONICAL = {"open", "investigating", "resolved", "refunded", "rejected", "cancelled"}
    UI_BUTTONS = {"investigating", "refunded", "rejected"}

    def test_api_router_canonical(self):
        sys.path.insert(0, str(REPO / "services" / "api"))
        from routers.claims import VALID_STATUSES, _validate_status
        from fastapi import HTTPException
        self.assertEqual(set(VALID_STATUSES), self.CANONICAL)
        # Los 3 botones de la UI ahora son válidos (antes 422).
        for s in self.UI_BUTTONS:
            _validate_status(s)  # no levanta
        # Los valores viejos desalineados ya NO son válidos.
        with self.assertRaises(HTTPException):
            _validate_status("in_progress")

    def test_agentic_tool_matches_router(self):
        sys.path.insert(0, str(REPO / "services" / "ai-orchestrator"))
        from agentic.tools.claims import _VALID_STATUSES
        self.assertEqual(set(_VALID_STATUSES), self.CANONICAL)

    def test_ui_status_map_matches_canonical(self):
        # El STATUS_MAP de la UI usa el mismo vocabulario.
        ui = (REPO / "apps/web/app/dashboard/(sales)/claims/_components/claims-manager.tsx").read_text()
        for s in self.CANONICAL - {"cancelled"}:  # cancelled no tiene chip en UI
            self.assertIn(f"{s}:", ui, f"status {s} ausente en UI STATUS_MAP")

    def test_check_migration_matches_canonical(self):
        mig = (REPO / "supabase/migrations/20260624010000_claims_status_check.sql").read_text()
        for s in self.CANONICAL:
            self.assertIn(f"'{s}'", mig)
        self.assertIn("claims_status_check", mig)


if __name__ == "__main__":
    unittest.main()

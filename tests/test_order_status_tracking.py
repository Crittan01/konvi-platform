"""
Tests F2: Tracking real en bot via order_tracking.

Cubre:
- Pedido shipped con tracking completo → muestra guía, carrier, URL, ETA
- Pedido shipped sin tracking → mensaje "guía no disponible"
- Pedido delivered con tracking → muestra tracking + mensaje de satisfacción
- Pedido confirmed → estado normal sin tracking
- _format_tracking_date: DATE y TIMESTAMPTZ
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools.order_status_tool import _build_order_response, _format_tracking_date


class TrackingFormatTests(unittest.TestCase):

    def test_format_date_iso(self):
        result = _format_tracking_date("2026-05-10T00:00:00.000Z")
        self.assertEqual(result, "10/05/2026")

    def test_format_date_plain(self):
        result = _format_tracking_date("2026-05-10")
        self.assertEqual(result, "10/05/2026")

    def test_format_date_none(self):
        result = _format_tracking_date(None)
        self.assertEqual(result, "N/D")

    def test_format_date_invalid(self):
        result = _format_tracking_date("not-a-date")
        self.assertEqual(result, "not-a-date")  # str[:10], 10 chars


class BuildOrderResponseTrackingTests(unittest.TestCase):

    def _base_order(self, status="shipped"):
        return {
            "id": "order-123",
            "status": status,
            "total_amount": 135_000,
            "created_at": "2026-04-25T10:00:00Z",
            "notes": "",
            "order_items": [{"id": "item-1"}],
        }

    def _full_tracking(self):
        return {
            "tracking_number": "9001234567",
            "carrier": "Deprisa",
            "tracking_url": "https://tracking.deprisa.com/9001234567",
            "estimated_delivery": "2026-04-28",
        }

    def test_shipped_with_full_tracking(self):
        order = self._base_order("shipped")
        tracking = self._full_tracking()
        response = _build_order_response(order, 1, tracking)

        self.assertIn("9001234567", response)
        self.assertIn("Deprisa", response)
        self.assertIn("https://tracking.deprisa.com/9001234567", response)
        self.assertIn("28/04/2026", response)
        self.assertNotIn("guía no disponible", response)

    def test_shipped_without_tracking(self):
        order = self._base_order("shipped")
        response = _build_order_response(order, 1, None)

        self.assertIn("guía", response.lower())
        self.assertNotIn("Guía:", response)  # no muestra número de guía

    def test_shipped_tracking_without_url(self):
        order = self._base_order("shipped")
        tracking = {"tracking_number": "9001234567", "carrier": "Servientrega",
                    "tracking_url": None, "estimated_delivery": None}
        response = _build_order_response(order, 1, tracking)

        self.assertIn("9001234567", response)
        self.assertIn("Servientrega", response)
        self.assertNotIn("Seguimiento", response)

    def test_delivered_with_tracking(self):
        order = self._base_order("delivered")
        tracking = self._full_tracking()
        response = _build_order_response(order, 1, tracking)

        self.assertIn("9001234567", response)
        self.assertIn("¿Recibiste todo bien?", response)

    def test_confirmed_no_tracking_shown(self):
        """En estado confirmed no se muestra tracking aunque exista."""
        order = self._base_order("confirmed")
        tracking = self._full_tracking()
        response = _build_order_response(order, 1, tracking)

        # El estado confirmed no activa la sección de tracking
        self.assertNotIn("Guía", response)
        self.assertIn("confirmado", response)

    def test_processing_with_tracking(self):
        order = self._base_order("processing")
        tracking = self._full_tracking()
        response = _build_order_response(order, 1, tracking)

        self.assertIn("9001234567", response)

    def test_no_tracking_data_at_all(self):
        """Pedido shipped con tracking vacío ({}) → no muestra número de guía."""
        order = self._base_order("shipped")
        response = _build_order_response(order, 1, {})

        # {} es falsy → rama elif → mensaje de guía no disponible
        self.assertIn("guía", response.lower())
        self.assertNotIn("Guía:", response)


class GetOrderTrackingTests(unittest.TestCase):

    def test_returns_none_on_empty(self):
        from unittest.mock import MagicMock
        from tools.order_status_tool import _get_order_tracking

        supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        supabase.table.return_value.select.return_value \
            .eq.return_value.eq.return_value \
            .order.return_value.limit.return_value = chain

        result = _get_order_tracking(supabase, "tenant-1", "order-1")
        self.assertIsNone(result)

    def test_returns_first_row(self):
        from unittest.mock import MagicMock
        from tools.order_status_tool import _get_order_tracking

        tracking_row = {"tracking_number": "TRK999", "carrier": "DHL",
                        "tracking_url": "https://dhl.co/TRK999",
                        "estimated_delivery": "2026-05-01", "status": "in_transit"}
        supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[tracking_row])
        supabase.table.return_value.select.return_value \
            .eq.return_value.eq.return_value \
            .order.return_value.limit.return_value = chain

        result = _get_order_tracking(supabase, "tenant-1", "order-1")
        self.assertEqual(result["tracking_number"], "TRK999")
        self.assertEqual(result["carrier"], "DHL")

    def test_returns_none_on_exception(self):
        from unittest.mock import MagicMock
        from tools.order_status_tool import _get_order_tracking

        supabase = MagicMock()
        supabase.table.side_effect = RuntimeError("DB error")

        result = _get_order_tracking(supabase, "tenant-1", "order-1")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

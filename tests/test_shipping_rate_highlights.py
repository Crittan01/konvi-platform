import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from routers import shipping


class ShippingRateHighlightsTests(unittest.TestCase):
    def test_build_rate_highlights_returns_cheapest_and_fastest(self):
        rates = [
            {
                "carrier": "Carrier A",
                "service": "Standard",
                "total_price": 21000,
                "currency": "COP",
                "delivery_estimate": "72 horas",
            },
            {
                "carrier": "Carrier B",
                "service": "Economy",
                "total_price": 15000,
                "currency": "COP",
                "delivery_estimate": "96 horas",
            },
            {
                "carrier": "Carrier C",
                "service": "Express",
                "total_price": 35000,
                "currency": "COP",
                "delivery_estimate": "24 horas",
            },
        ]

        highlights = shipping._build_rate_highlights(rates)
        self.assertEqual(highlights["cheapest"]["carrier"], "Carrier B")
        self.assertEqual(highlights["fastest"]["carrier"], "Carrier C")

    def test_build_rate_highlights_prioritizes_delivery_date_for_fastest(self):
        rates = [
            {
                "carrier": "Carrier A",
                "service": "Standard",
                "total_price": 18000,
                "currency": "COP",
                "delivery_date": "2026-05-10",
                "delivery_estimate": "24 horas",
            },
            {
                "carrier": "Carrier B",
                "service": "Express",
                "total_price": 26000,
                "currency": "COP",
                "delivery_date": "2026-05-08",
                "delivery_estimate": "72 horas",
            },
        ]

        highlights = shipping._build_rate_highlights(rates)
        self.assertEqual(highlights["fastest"]["carrier"], "Carrier B")

    def test_build_rate_highlights_omits_fastest_if_speed_signals_missing(self):
        rates = [
            {
                "carrier": "Carrier A",
                "service": "Standard",
                "total_price": 18000,
                "currency": "COP",
            },
            {
                "carrier": "Carrier B",
                "service": "Economy",
                "total_price": 12000,
                "currency": "COP",
            },
        ]

        highlights = shipping._build_rate_highlights(rates)
        self.assertIn("cheapest", highlights)
        self.assertNotIn("fastest", highlights)
        self.assertEqual(highlights["cheapest"]["carrier"], "Carrier B")


if __name__ == "__main__":
    unittest.main()

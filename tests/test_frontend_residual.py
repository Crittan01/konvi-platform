from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]


class FrontendResidualTests(unittest.TestCase):
    def test_inventory_links_removed_from_dashboard_shortcuts(self):
        dashboard_page = (REPO / 'apps/web/app/dashboard/page.tsx').read_text()
        dashboard_client = (REPO / 'apps/web/app/dashboard/dashboard-client.tsx').read_text()
        self.assertNotIn('/dashboard/inventory', dashboard_page)
        self.assertNotIn('/dashboard/inventory', dashboard_client)

    def test_legacy_inventory_route_redirects_to_catalog(self):
        legacy_inventory = (REPO / 'apps/web/app/dashboard/(products)/inventory/page.tsx').read_text()
        self.assertIn("redirect('/dashboard/catalog')", legacy_inventory)

    def test_marketplace_badge_renders_on_child_items(self):
        sidebar = (REPO / 'apps/web/app/dashboard/sidebar-client.tsx').read_text()
        self.assertIn('shouldRenderMarketplaceBadge(child.href, meliBadge)', sidebar)


if __name__ == '__main__':
    unittest.main()

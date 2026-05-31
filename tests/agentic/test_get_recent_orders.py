"""Tests del GetRecentOrdersTool.

Rev. 107 — UX gap: bot no sabía consultar historial cliente cuando
cart estaba vacío. Ahora puede.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_sb_chain(orders, items=None, ships=None, variations=None):
    """Mock supabase chain-aware. 4 tablas (orders/order_items/shipments/
    product_variations) se diferencian por el nombre que recibe .table()."""
    sb = MagicMock()
    items = items or []
    ships = ships or []
    variations = variations or []

    def _table(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.in_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        if name == "orders":
            chain.execute.return_value = MagicMock(data=orders)
        elif name == "order_items":
            chain.execute.return_value = MagicMock(data=items)
        elif name == "shipments":
            chain.execute.return_value = MagicMock(data=ships)
        elif name == "product_variations":
            chain.execute.return_value = MagicMock(data=variations)
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain

    sb.table.side_effect = _table
    return sb


class GetRecentOrdersTests(unittest.TestCase):

    def setUp(self):
        import agentic.tools.orders  # noqa: F401 — registra
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext
        self.tool = get_tool("get_recent_orders")
        self.ctx_factory = lambda sb: ToolContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            contact_id="00000000-0000-0000-0000-000000000003",
            supabase=sb, extras={}, logger=MagicMock(),
        )

    def test_sin_contact_id_returns_empty_note(self):
        from agentic.tools.base import ToolContext
        ctx = ToolContext(
            tenant_id="t", conversation_id="c", contact_id=None,
            supabase=MagicMock(), extras={}, logger=MagicMock(),
        )
        args = self.tool.args_schema()
        r = _run(self.tool.execute(args, ctx))
        self.assertTrue(r.success)
        self.assertEqual(r.data["orders"], [])
        self.assertIn("cliente nuevo", r.data["note"].lower())

    def test_sin_orders_recientes(self):
        sb = _make_sb_chain([])
        r = _run(self.tool.execute(self.tool.args_schema(), self.ctx_factory(sb)))
        self.assertTrue(r.success)
        self.assertEqual(r.data["orders"], [])
        self.assertIn("pedido nuevo", r.data["note"].lower())

    def test_orders_confirmed_con_shipment_detalle(self):
        """Orden con detalle completo de items + presentación + tracking."""
        sb = _make_sb_chain(
            orders=[
                {"id": "07624ce1-ac9d-433e-8be8-8f5bf51b0ee5",
                 "status": "confirmed", "total_amount": 177950,
                 "shipping_cost": 17950, "created_at": "2026-05-23T13:35:00Z",
                 "updated_at": "2026-05-23T13:40:21Z", "notes": None},
            ],
            items=[
                {"order_id": "07624ce1-ac9d-433e-8be8-8f5bf51b0ee5",
                 "title": "Jabón Artesanal de Coco", "quantity": 1,
                 "unit_price": 18000, "variation_id": "v-coco-60"},
                {"order_id": "07624ce1-ac9d-433e-8be8-8f5bf51b0ee5",
                 "title": "Sérum de Ácido Hialurónico", "quantity": 1,
                 "unit_price": 92000, "variation_id": "v-serum-30"},
            ],
            ships=[
                {"order_id": "07624ce1-ac9d-433e-8be8-8f5bf51b0ee5",
                 "status": "labeled", "carrier": "SERVIENTREGA",
                 "tracking_number": "TRACK123", "tracking_url": "https://..."},
            ],
            variations=[
                {"id": "v-coco-60", "attributes": {"Presentación": "60g"}},
                {"id": "v-serum-30", "attributes": {"Volumen": "30ml"}},
            ],
        )
        r = _run(self.tool.execute(self.tool.args_schema(), self.ctx_factory(sb)))
        self.assertTrue(r.success)
        o = r.data["orders"][0]
        self.assertEqual(o["order_short"], "07624CE1")
        self.assertEqual(o["status"], "confirmed")
        self.assertEqual(o["total_cop"], 177950)
        self.assertEqual(o["subtotal_cop"], 160000)
        self.assertEqual(o["shipping_cost_cop"], 17950)
        self.assertEqual(o["items_count"], 2)
        # Items detallados con variant_label.
        self.assertEqual(len(o["items"]), 2)
        titles = [i["title"] for i in o["items"]]
        labels = [i["variant_label"] for i in o["items"]]
        self.assertIn("Jabón Artesanal de Coco", titles)
        self.assertIn("60g", labels)
        self.assertIn("30ml", labels)
        self.assertEqual(o["shipment"]["tracking_number"], "TRACK123")

    def test_orders_cancelled(self):
        sb = _make_sb_chain(orders=[
            {"id": "abc-cancelled", "status": "cancelled",
             "total_amount": 100000, "shipping_cost": 10000,
             "created_at": "2026-05-23T10:00:00Z",
             "updated_at": "2026-05-23T11:00:00Z", "notes": None},
        ])
        r = _run(self.tool.execute(self.tool.args_schema(), self.ctx_factory(sb)))
        self.assertEqual(r.data["orders"][0]["status"], "cancelled")

    def test_args_default_values(self):
        args = self.tool.args_schema()
        self.assertEqual(args.days, 30)
        self.assertEqual(args.limit, 5)


if __name__ == "__main__":
    unittest.main()

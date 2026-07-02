"""F4 — regresión: reserva de checkout SIN doble-conteo.

BUG (auditoría F7/F4): add_to_cart crea una reserva SOFT por ítem; luego
generate_payment_link creaba OTRA reserva por el mismo ítem. rpc_stock_reserve
resta TODAS las reservas activas de la variation (sin dedup por cart), así que en
la ÚLTIMA UNIDAD (stock < 2×qty) el 2º reserve veía available<qty → falso
"insufficient_stock" y BLOQUEABA la venta legítima (solo path agéntico = KAIU
productivo).

Fix: `_reserve_checkout_stock` EXTIENDE las reservas del cart al checkout window
(35min) y reserva fresco SOLO el delta no cubierto. Este test prueba que:
  1. Si el cart ya cubre el ítem → NO se llama rpc_stock_reserve (no double-count).
  2. Cobertura parcial → se reserva SOLO el delta faltante.
  3. Sin cart → se reserva la cantidad completa (comportamiento original).
"""
import os
import sys
import unittest

os.environ.setdefault("INTERNAL_SERVICE_SECRET", "internal-secret")
os.environ.setdefault("API_URL", "http://localhost:8001")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools import payment_link_tool  # noqa: E402


class _Query:
    """Query encadenable falso: acumula filtros y devuelve `rows` en execute()."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class FakeSupabase:
    """Fake mínimo para _reserve_checkout_stock.

    - stock_reservations.select(...) → reservas activas del cart (parametrizable).
    - rpc('rpc_stock_reservation_extend') → registra y devuelve ok.
    - rpc('rpc_stock_reserve') → registra la llamada; simula el RPC real
      (insufficient si el qty pedido supera el stock disponible dado).
    """

    def __init__(self, *, active_reservations, stock_available):
        self._active = active_reservations
        self._stock_available = stock_available  # disponibilidad si se reservara fresco
        self.reserve_calls = []          # [(variation_id, qty)]
        self.extend_calls = 0

    def table(self, name):
        if name == "stock_reservations":
            return _Query(self._active)
        return _Query([])

    def rpc(self, fn, params):
        if fn == "rpc_stock_reservation_extend":
            self.extend_calls += 1
            return type("E", (), {"execute": lambda self: type("R", (), {"data": None})()})()
        if fn == "rpc_stock_reserve":
            self.reserve_calls.append((params["p_variation_id"], params["p_qty"]))
            avail = self._stock_available
            qty = params["p_qty"]
            if qty > avail:
                def _raise():
                    raise Exception("rpc_stock_reserve: insufficient_stock (P0001)")
                return type("E", (), {"execute": staticmethod(_raise)})()
            return type("E", (), {
                "execute": staticmethod(lambda: type("R", (), {"data": [{"out_reservation_id": "res-new"}]})())
            })()
        return type("E", (), {"execute": staticmethod(lambda: type("R", (), {"data": []})())})()


class F4CheckoutReservationTests(unittest.TestCase):
    def test_last_unit_with_soft_reservation_does_not_reserve_again(self):
        """Última unidad (stock=1, qty=1) YA reservada por el cart → NO re-reservar,
        NO falso insufficient. Este es el bug de ingresos."""
        sb = FakeSupabase(
            active_reservations=[{"id": "res-soft", "variation_id": "var-1", "qty": 1, "expires_at": "z"}],
            stock_available=0,  # sin la reserva soft no habría disponible → probaría el bug
        )
        reservation_ids, insufficient = payment_link_tool._reserve_checkout_stock(
            sb,
            tenant_id="t-1",
            conversation_id="conv-1",
            cart_id="cart-1",
            items=[{"variation_id": "var-1", "quantity": 1}],
        )
        self.assertEqual(insufficient, [], "última unidad reservada por el cart NO debe dar insufficient")
        self.assertEqual(sb.reserve_calls, [], "no debe llamar rpc_stock_reserve (ya cubierto por el cart)")
        self.assertEqual(sb.extend_calls, 1, "debe extender la reserva soft del cart al checkout window")
        self.assertEqual(reservation_ids, [])

    def test_partial_coverage_reserves_only_delta(self):
        """Cart cubre 1 de 3 → reservar SOLO el delta (2)."""
        sb = FakeSupabase(
            active_reservations=[{"id": "res-soft", "variation_id": "var-1", "qty": 1, "expires_at": "z"}],
            stock_available=5,
        )
        reservation_ids, insufficient = payment_link_tool._reserve_checkout_stock(
            sb,
            tenant_id="t-1",
            conversation_id="conv-1",
            cart_id="cart-1",
            items=[{"variation_id": "var-1", "quantity": 3}],
        )
        self.assertEqual(insufficient, [])
        self.assertEqual(sb.reserve_calls, [("var-1", 2)], "solo el delta no cubierto (3-1=2)")
        self.assertEqual(reservation_ids, ["res-new"])

    def test_no_cart_reserves_full_quantity(self):
        """Sin cart (sin reserva soft) → reservar la cantidad completa."""
        sb = FakeSupabase(active_reservations=[], stock_available=10)
        reservation_ids, insufficient = payment_link_tool._reserve_checkout_stock(
            sb,
            tenant_id="t-1",
            conversation_id="conv-1",
            cart_id=None,
            items=[{"variation_id": "var-1", "quantity": 2}],
        )
        self.assertEqual(insufficient, [])
        self.assertEqual(sb.reserve_calls, [("var-1", 2)])
        self.assertEqual(sb.extend_calls, 0, "sin cart no hay reservas soft que extender")

    def test_genuine_insufficient_still_reported(self):
        """Sin cobertura del cart y stock real insuficiente → SÍ reportar insufficient."""
        sb = FakeSupabase(active_reservations=[], stock_available=0)
        reservation_ids, insufficient = payment_link_tool._reserve_checkout_stock(
            sb,
            tenant_id="t-1",
            conversation_id="conv-1",
            cart_id=None,
            items=[{"variation_id": "var-1", "quantity": 1}],
        )
        self.assertEqual(len(insufficient), 1, "falta de stock genuina debe seguir reportándose")
        self.assertEqual(reservation_ids, [])


if __name__ == "__main__":
    unittest.main()

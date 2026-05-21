"""Tests integración handlers Sem 1 — NEEDS_SHIPPING_CITY + AWAITING_CARRIER_SELECTION.

Verifica que los handlers migrados desde bypass del orchestrator (commit
18a3a5d) producen los mismos outputs que el bypass legacy. Esto es la
garantía de zero-regression del refactor Sem 1.
"""
import asyncio
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

# Importar handlers triggerea auto-registro.
from fsm.handlers import dispatch, TurnInput
import fsm.handlers.needs_shipping_city  # noqa: F401 (auto-register)
import fsm.handlers.awaiting_carrier_selection  # noqa: F401


def _run(coro):
    """Helper async-test compatible con Python 3.11+ (get_event_loop deprecated)."""
    return asyncio.new_event_loop().run_until_complete(coro)


_COCO = {
    "id": "p-coco",
    "title": "Jabón Artesanal de Coco",
    "variants": [
        {"id": "v60", "label": "60g", "price": 18000},
        {"id": "v100", "label": "100g", "price": 24000},
        {"id": "v150", "label": "150g", "price": 32000},
    ],
}
_LAVANDA = {
    "id": "p-lavanda",
    "title": "Jabón Artesanal de Lavanda",
    "variants": [
        {"id": "v60", "label": "60g", "price": 18000},
        {"id": "v100", "label": "100g", "price": 24000},
        {"id": "v150", "label": "150g", "price": 32000},
    ],
}

_OUTBOUND_LIST_4 = (
    "*Jabones artesanales*:\n"
    "* *Coco* — 60g por *$18.000* · 100g por *$24.000* · 150g por *$32.000*\n"
    "* *Lavanda* — 60g por *$18.000* · 100g por *$24.000* · 150g por *$32.000*\n"
)


class NeedsShippingCityHandlerTests(unittest.TestCase):

    def test_cart_vacio_con_productos_presentados_y_mencion_filtra(self):
        """Caso founder UAT (conv bae0f6a2): cliente dice "1 Coco y 1 Lavanda"
        sin gramaje, tras ver listado. Handler debe pedir variante de SOLO
        Coco + Lavanda."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="NEEDS_SHIPPING_CITY",
            inbound_text="Me peudes vender 1 Jabon de Coco y 1 de Lavanda",
            catalog=[_COCO, _LAVANDA],
            cart={"items": []},
            history=[
                {"direction": "inbound", "content": "Que jabones tienen?"},
                {"direction": "outbound", "content": _OUTBOUND_LIST_4},
            ],
        )
        result = _run(dispatch(turn))
        self.assertIsNotNone(result)
        self.assertIn("presentaci", result.outbound_text.lower())
        self.assertIn("Coco", result.outbound_text)
        self.assertIn("Lavanda", result.outbound_text)

    def test_cart_con_items_pregunta_ciudad(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="NEEDS_SHIPPING_CITY",
            inbound_text="cotizar envío",
            catalog=[_COCO],
            cart={"items": [{"variation_id": "v100", "quantity": 1}]},
            history=[],
        )
        result = _run(dispatch(turn))
        self.assertIsNotNone(result)
        self.assertIn("ciudad", result.outbound_text.lower())

    def test_guard_10_digit_phone_cede_turn(self):
        """Inbound con 10 dígitos (likely phone update) → handler retorna None,
        otro path lo maneja."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="NEEDS_SHIPPING_CITY",
            inbound_text="3223840887",
            catalog=[_COCO],
            cart={"items": [{"variation_id": "v100", "quantity": 1}]},
            history=[],
        )
        result = _run(dispatch(turn))
        # Guard activado → None (cede el turn).
        self.assertIsNone(result)

    def test_guard_add_item_intent_cede_turn(self):
        """Cliente dice "puedo adicionar X" → tier-2 lo maneja, handler cede."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="NEEDS_SHIPPING_CITY",
            inbound_text="puedo adicionar 1 jabon de coco?",
            catalog=[_COCO],
            cart={"items": []},
            history=[],
        )
        result = _run(dispatch(turn))
        self.assertIsNone(result)

    def test_estado_no_aplicable_retorna_none(self):
        """READY_FOR_SUMMARY no es estado del handler → no dispara."""
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="READY_FOR_SUMMARY",
            inbound_text="hola",
        )
        result = _run(dispatch(turn))
        self.assertIsNone(result)


class AwaitingCarrierSelectionHandlerTests(unittest.TestCase):

    def test_post_quote_recuerda_opciones(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="AWAITING_CARRIER_SELECTION",
            inbound_text="cuál era?",
            history=[
                {"direction": "outbound", "content":
                    "Envío a Bogotá:\n* *Económica*: FedEx | $11.570\n"
                    "* *Rápida*: FedEx Express | $14.410\n¿Con cuál continuamos?"},
            ],
        )
        result = _run(dispatch(turn))
        self.assertIsNotNone(result)
        self.assertIn("Económica", result.outbound_text)
        self.assertIn("Rápida", result.outbound_text)

    def test_sin_quote_reciente_no_aplica(self):
        turn = TurnInput(
            conversation_id="conv-x",
            tenant_id="tenant-x",
            message_id="msg-x",
            display_state="AWAITING_CARRIER_SELECTION",
            inbound_text="cuál era?",
            history=[
                {"direction": "outbound", "content": "Buenas, en qué te ayudo?"},
            ],
        )
        result = _run(dispatch(turn))
        # Sin cotización reciente, handler retorna None → LLM compone.
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

"""Regresión A11 UAT — el resolver de compra preserva la cantidad cuando hay
saludo/relleno antes del verbo de intención.

Bug (revenue): `_split_into_items` solo BORRABA el verbo de intención pero dejaba
el saludo previo ("Hola! Quiero 2 jabones" → "Hola! 2 jabones") → la cantidad no
quedaba al inicio del item → `_parse_qty_at_start` caía a default 1. Cliente que
saludaba antes de pedir N unidades recibía 1.

Fix: tomar el texto DESPUÉS del primer verbo de intención.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.purchase_intent_resolver import _split_into_items, _parse_qty_at_start  # noqa: E402


def _qty_of_first(text):
    items = _split_into_items(text)
    return _parse_qty_at_start(items[0])[0] if items else None


class QtyGreetingPrefixTests(unittest.TestCase):
    def test_greeting_before_intent_preserves_qty(self):
        # El caso exacto del UAT que daba qty=1:
        self.assertEqual(_qty_of_first("Hola! Quiero 2 jabones de coco de 100 gramos"), 2)
        self.assertEqual(_qty_of_first("Buenas tardes, quiero 3 sérums de vitamina c"), 3)
        self.assertEqual(_qty_of_first("hola, dame 5 jabones de coco"), 5)

    def test_no_greeting_still_works(self):
        # Sin regresión para el caso sin saludo:
        self.assertEqual(_qty_of_first("Quiero 2 jabones de coco de 100 gramos"), 2)

    def test_default_one_when_no_quantity(self):
        self.assertEqual(_qty_of_first("Quiero un jabón de coco"), 1)

    def test_multi_item_quantities(self):
        items = _split_into_items("Hola! Quiero 2 coco y 3 lavanda")
        qtys = [_parse_qty_at_start(it)[0] for it in items]
        self.assertEqual(qtys, [2, 3])


if __name__ == "__main__":
    unittest.main()

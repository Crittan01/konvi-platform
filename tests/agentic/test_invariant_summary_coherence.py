"""Tests del SummaryCoherenceInvariant.

Rev. 107 — bug runtime KAIU conv be046dbb 2026-05-23:
  Bot emitió resumen completamente inventado tras `save_address ok=True`.
  Producto fantasma + carrier inventado + total falso vs cart real DB.

Este invariant cierra el gap. Tests cubren:
  • outbound NO es resumen → OK.
  • outbound es resumen + cart real → OK si total match.
  • outbound es resumen + cart real → REWRITE si total mismatch.
  • outbound es resumen + cart vacío/null → REWRITE.
  • outbound es resumen + cart unreadable (exception) → OK (best-effort).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_cart(total_cents: int, items_count: int = 1, carrier: str = "SERVIENTREGA"):
    """Construye un dict cart de prueba estilo `get_cart_with_items`."""
    return {
        "id": "cart-1",
        "status": "open",
        "subtotal_cents": total_cents - 1795000 if total_cents > 1795000 else total_cents,
        "shipping_cents": 1795000 if total_cents > 1795000 else 0,
        "total_cents": total_cents,
        "shipping_meta": {"carrier": carrier, "city": "Medellín"},
        "items": [
            {
                "id": f"i{i}",
                "product_id": "p1",
                "variation_id": "v1",
                "quantity": 1,
                "unit_price_cents": (total_cents // max(items_count, 1)),
                "subtotal_cents": (total_cents // max(items_count, 1)),
                "variation": {"attributes": {"size": "60g"}},
                "product": {"title": "Jabón Coco"},
            }
            for i in range(items_count)
        ],
    }


class SummaryCoherenceTests(unittest.TestCase):

    def setUp(self):
        from agentic.invariants.summary_coherence import SummaryCoherenceInvariant
        self.inv = SummaryCoherenceInvariant()
        self.base = {
            "tenant_id": "t", "conversation_id": "c", "contact_id": "ct",
            "supabase": MagicMock(),
        }

    def test_outbound_no_es_resumen_ok(self):
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="¿Cuál presentación prefieres?",
            tool_call_log=[],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_outbound_resumen_pero_sin_precios_ok(self):
        """'Total perfecto' sin $ no dispara — el regex exige precio."""
        from agentic.invariants.base import InvariantOutcome
        r = _run(self.inv.validate(
            candidate_text="Total perfecto. Confirmas?",
            tool_call_log=[],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_resumen_real_runtime_kaiu_total_mismatch(self):
        """Texto EXACTO observado en conv 8f96520e KAIU 2026-05-23 — bot
        dijo $162.950 pero cart real era $159.950. Items sin precio por línea
        (solo presentaciones) + Total con asteriscos. Antes del fix de regex
        este caso NO disparaba el detector."""
        from agentic.invariants.base import InvariantOutcome
        text_bug = (
            "Perfecto, Cristian! Ya tengo tu dirección registrada.\n\n"
            "📋 *Resumen de tu pedido:*\n\n"
            "* 2 *Jabones Artesanales de Coco* (60g y 150g)\n"
            "* 1 *Sérum de Ácido Hialurónico* (30ml)\n"
            "* Envío a Medellín por *SERVIENTREGA* (3 días)\n\n"
            "*Total a pagar: $162.950 COP*\n\n"
            "Confirmas el pedido para generar el link de pago seguro?"
        )
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = _fake_cart(15995000, items_count=3)  # real $159.950
            r = _run(self.inv.validate(
                candidate_text=text_bug, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("159.950", r.replacement_text)

    def test_resumen_con_total_correcto_ok(self):
        from agentic.invariants.base import InvariantOutcome
        text = (
            "Resumen de tu pedido:\n"
            "* 1 Jabón Coco 60g: *$18.000 COP*\n"
            "* Envío: *$17.950 COP*\n"
            "* Total: *$159.950 COP*"
        )
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = _fake_cart(15995000)
            r = _run(self.inv.validate(
                candidate_text=text, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_resumen_con_total_inventado_rewrite(self):
        """Bug runtime KAIU: bot dijo $48.000 pero cart real era $159.950."""
        from agentic.invariants.base import InvariantOutcome
        text_bug = (
            "Resumen de tu pedido:\n"
            "* 1 Aceite de Coco Virgen 250ml: *$38.000 COP*\n"
            "* Envío a Medellín: *$10.000 COP* (Transportadora Rápida)\n"
            "* Total: *$48.000 COP*"
        )
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = _fake_cart(15995000)  # cart real $159.950
            r = _run(self.inv.validate(
                candidate_text=text_bug, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        # Replacement debe incluir el total real $159.950.
        self.assertIn("159.950", r.replacement_text)

    def test_resumen_sin_cart_real_rewrite(self):
        """Bot habla de resumen pero cart no existe → claramente inventando."""
        from agentic.invariants.base import InvariantOutcome
        text = (
            "Resumen de tu pedido:\n"
            "* 1 Item: *$30.000 COP*\n"
            "* Total: *$30.000 COP*"
        )
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = None
            r = _run(self.inv.validate(
                candidate_text=text, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_cart_unreadable_excepcion_ok_best_effort(self):
        """Si get_cart_with_items lanza, NO bloqueamos al cliente — OK."""
        from agentic.invariants.base import InvariantOutcome
        text = (
            "Resumen:\n"
            "* Item: *$10.000*\n"
            "* Total: *$10.000*"
        )
        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=Exception("db down")):
            r = _run(self.inv.validate(
                candidate_text=text, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)


class ExtractTotalTests(unittest.TestCase):
    """Tests directos del helper de parseo de Total."""

    def test_extract_total_various_formats(self):
        from agentic.invariants.summary_coherence import _extract_total_cop
        # Casos representativos observados en runtime.
        self.assertEqual(_extract_total_cop("Total: $159.950 COP"), 159950)
        self.assertEqual(_extract_total_cop("Total: *$159.950*"), 159950)
        self.assertEqual(_extract_total_cop("Total $48.000"), 48000)
        self.assertEqual(_extract_total_cop("Total a pagar: $162.950 COP"), 162950)
        self.assertIsNone(_extract_total_cop("no hay total aquí"))

    def test_extract_total_markdown_bold_separado(self):
        """Bug runtime KAIU turno 12: '*Total:* *$160.000 COP*' con asteriscos
        markdown separando 'Total:' del precio. Antes del fix el regex sólo
        toleraba 1 asterisco continuo, fallaba con esta forma."""
        from agentic.invariants.summary_coherence import _extract_total_cop
        self.assertEqual(
            _extract_total_cop("*Total:* *$160.000 COP*"), 160000,
        )
        self.assertEqual(_extract_total_cop("* *Total:* $48.000"), 48000)


if __name__ == "__main__":
    unittest.main()

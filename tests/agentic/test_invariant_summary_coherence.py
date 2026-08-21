"""Tests del SummaryCoherenceInvariant.

Rev. 107 — bug runtime KAIU conv be046dbb 2026-05-23:
  Bot emitió resumen completamente inventado tras `save_address ok=True`.
  Producto fantasma + carrier inventado + total falso vs cart real DB.

B-0 (2026-08-21) — lote dinero/verdad:
  • F1a: parser tolerante a markdown — caso prod `*Total a pagar*: *$104.990 COP*`
    hacía bypass de los regex (bold cerrado entre label y monto) y un total
    falso salía OK "no total parseable".
  • F1b: guard simétrico de descuento — outbound con línea "Descuento (KAIU15):
    -$17.100" sobre cart SIN descuento → REWRITE.
  • F2: cart unreadable ya NO es OK best-effort — la excepción escapa y
    `apply_invariants` (fail-closed) la convierte en BLOCK + mensaje neutro.
    Skip de `get_recent_orders` acotado a histórico EXCLUSIVO.

Este invariant cierra el gap. Tests cubren:
  • outbound NO es resumen → OK.
  • outbound es resumen + cart real → OK si total match.
  • outbound es resumen + cart real → REWRITE si total mismatch.
  • outbound es resumen + cart vacío/null → REWRITE.
  • outbound es resumen + cart unreadable (exception) → excepción escapa
    (fail-closed → BLOCK vía apply_invariants).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
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

    def test_skip_si_get_recent_orders_se_uso(self):
        """Rev. 107: si el LLM consultó get_recent_orders exitosamente,
        el outbound puede mencionar totals históricos. NO validar contra
        cart actual (caso runtime KAIU: bot reportó pedido confirmed
        histórico y el invariant lo reescribía como falso positivo)."""
        from agentic.invariants.base import InvariantOutcome
        text = (
            "Tu pedido *#07624CE1* (total $177.950 COP, *SERVIENTREGA*) "
            "está confirmado y en preparación."
        )
        r = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[
                {"tool": "get_recent_orders",
                 "result": {"orders": [{"order_short": "07624CE1",
                                        "status": "confirmed",
                                        "total_cop": 177950}]}},
            ],
            **self.base,
        ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)
        self.assertIn("histórico", r.reason)

    def test_cart_unreadable_excepcion_escapa_fail_closed(self):
        """B-0 F2: si get_cart_with_items lanza, la excepción ESCAPA del
        invariant (NO retorna OK best-effort) — un resumen de dinero no sale
        sin validar. El wrapper `apply_invariants` (fail-closed A4, este
        invariant está en FAIL_CLOSED_INVARIANTS) la convierte en BLOCK +
        mensaje neutro."""
        from agentic.degraded_messages import DEGRADED_GENERIC
        from agentic.invariants.base import InvariantOutcome, apply_invariants
        text = (
            "Resumen:\n"
            "* Item: *$10.000*\n"
            "* Total: *$10.000*"
        )
        with patch("tools.cart_tool.get_cart_with_items",
                   side_effect=Exception("db down")):
            # 1. La excepción escapa de validate() (fail-closed real).
            with self.assertRaises(Exception):
                _run(self.inv.validate(
                    candidate_text=text, tool_call_log=[], **self.base,
                ))
            # 2. Vía pipeline: BLOCK + mensaje neutro, NO el texto del LLM.
            r = _run(apply_invariants(
                [self.inv],
                candidate_text=text,
                tenant_id="t", conversation_id="c", contact_id="ct",
                supabase=MagicMock(), tool_call_log=[],
            ))
        self.assertEqual(r.outcome, InvariantOutcome.BLOCK)
        self.assertEqual(r.invariant_name, "summary_coherence")
        self.assertEqual(r.replacement_text, DEGRADED_GENERIC)

    def test_total_real_prod_asterisco_entre_label_y_colon(self):
        """B-0 F1a — texto EXACTO prod 2026-08: '*Total a pagar*: *$104.990 COP*'.
        El '*' de cierre de bold entre 'pagar' y ':' rompía ambos regex →
        total no parseable → OK con total FALSO (cart real $122.090, el link
        cobraba de más). Ahora parsea 104990 y dispara REWRITE."""
        from agentic.invariants.base import InvariantOutcome
        from agentic.invariants.summary_coherence import _extract_total_cop
        text_real = (
            "📋 *Resumen de tu pedido:*\n\n"
            "* 1 *Sérum Facial*: *$122.090 COP*\n\n"
            "*Total a pagar*: *$104.990 COP*\n\n"
            "Confirmas para generar el link de pago?"
        )
        # Parseo directo del fragmento exacto.
        self.assertEqual(
            _extract_total_cop("*Total a pagar*: *$104.990 COP*"), 104990,
        )
        # End-to-end: cart real $122.090 ≠ afirmado $104.990 → REWRITE.
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = _fake_cart(12209000)
            r = _run(self.inv.validate(
                candidate_text=text_real, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("122.090", r.replacement_text)

    def test_descuento_inventado_sobre_cart_sin_descuento_rewrite(self):
        """B-0 F1b — guard simétrico BUG 38d: outbound muestra línea
        'Descuento (KAIU15): -$17.100' pero el cart tiene discount_cents=0
        y sin cupón → REWRITE con resumen canónico (sin línea Descuento y
        total real recomputado)."""
        from agentic.invariants.base import InvariantOutcome
        text_bug = (
            "📋 *Resumen de tu pedido:*\n\n"
            "* 1 *Sérum Facial*: *$122.090 COP*\n"
            "* Descuento (KAIU15): *-$17.100 COP*\n\n"
            "*Total a pagar*: *$104.990 COP*"
        )
        cart = _fake_cart(12209000)
        cart["discount_cents"] = 0  # explícito: SIN descuento real
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = cart
            r = _run(self.inv.validate(
                candidate_text=text_bug, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("122.090", r.replacement_text)
        self.assertNotIn("Descuento", r.replacement_text)
        self.assertIn("descuento", r.reason.lower())

    def test_descuento_real_en_cart_y_outbound_coherente_ok(self):
        """Negativo del F1b: cart CON cupón y outbound SÍ muestra la línea
        Descuento con el total correcto → OK (el guard simétrico no dispara)."""
        from agentic.invariants.base import InvariantOutcome
        cart = _fake_cart(10499000)
        cart["discount_cents"] = 1710000
        cart["coupon_code"] = "KAIU15"
        text = (
            "Resumen de tu pedido:\n"
            "* 1 Sérum Facial: *$122.090 COP*\n"
            "* Descuento (KAIU15): *-$17.100 COP*\n"
            "* Total: *$104.990 COP*"
        )
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = cart
            r = _run(self.inv.validate(
                candidate_text=text, tool_call_log=[], **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_skip_get_recent_orders_no_aplica_si_mezcla_resumen_cart(self):
        """B-0 F2 — skip acotado: el LLM invocó get_recent_orders PERO el
        outbound mezcla histórico con señales de checkout del cart actual
        ('Resumen', 'Total a pagar') → NO skip: valida contra cart real y
        corrige el total falso."""
        from agentic.invariants.base import InvariantOutcome
        text = (
            "Tu pedido #07624CE1 quedó confirmado.\n\n"
            "Y tu nuevo pedido:\n"
            "Resumen de tu pedido:\n"
            "* 1 Jabón Coco: *$50.000 COP*\n"
            "* Total a pagar: *$50.000 COP*"
        )
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = _fake_cart(15995000)  # cart real $159.950
            r = _run(self.inv.validate(
                candidate_text=text,
                tool_call_log=[
                    {"tool": "get_recent_orders",
                     "result": {"orders": [{"order_short": "07624CE1",
                                            "status": "confirmed",
                                            "total_cop": 177950}]}},
                ],
                **self.base,
            ))
        # Sin el fix: skip ciego → OK. Con el fix: valida y REWRITE (50.000 ≠ 159.950).
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("159.950", r.replacement_text)

    def test_skip_get_recent_orders_total_no_historico_no_skip(self):
        """B-0 F2 — aunque el texto NO tenga señales de checkout, si el total
        afirmado no corresponde a ninguna orden histórica reportada por la
        tool, el skip NO aplica (posible mezcla/invención)."""
        from agentic.invariants.base import InvariantOutcome
        text = "Tu pedido está confirmado, total $99.999 COP."
        with patch("tools.cart_tool.get_cart_with_items") as mock_get:
            mock_get.return_value = _fake_cart(15995000)
            r = _run(self.inv.validate(
                candidate_text=text,
                tool_call_log=[
                    {"tool": "get_recent_orders",
                     "result": {"orders": [{"order_short": "07624CE1",
                                            "status": "confirmed",
                                            "total_cop": 177950}]}},
                ],
                **self.base,
            ))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)


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

    def test_extract_total_markdown_entre_label_y_colon(self):
        """B-0 F1a — caso prod: '*Total a pagar*: *$104.990 COP*' (bold cerrado
        ENTRE el label y los dos puntos). Bypass total pre-fix. También cubre
        itálica con underscore."""
        from agentic.invariants.summary_coherence import _extract_total_cop
        self.assertEqual(
            _extract_total_cop("*Total a pagar*: *$104.990 COP*"), 104990,
        )
        self.assertEqual(_extract_total_cop("_Total_: _$48.000_"), 48000)
        self.assertEqual(
            _extract_total_cop("*Total a pagar* : *$122.090 COP*"), 122090,
        )


if __name__ == "__main__":
    unittest.main()

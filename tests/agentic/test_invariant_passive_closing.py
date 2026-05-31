"""Tests del invariant PassiveClosingInvariant.

ADR-0018. Defensa en profundidad: si el LLM ignora la regla #8 del
system_prompt (no cierre pasivo "¿algo más?") este invariant
reescribe el cierre con CTA según estado real del cart.

Caso runtime motivador: conv 3b0452e8 (founder UAT 2026-05-22).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.invariants import PassiveClosingInvariant, InvariantOutcome


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_supabase_with_cart(
    *, items_count: int = 0, shipping_cents: int = 0,
    pii_complete: bool = False,
):
    """Mock supabase que retorna cart con estado controlado."""
    sb = MagicMock()

    cart_data = {"id": "cart-123", "shipping_cents": shipping_cents, "contact_id": "ct-1"}
    cart_res = MagicMock(data=cart_data if items_count > 0 or shipping_cents > 0 else None)

    items_res = MagicMock()
    items_res.count = items_count

    contact_data = {
        "consent_given": pii_complete,
        "email": "x@y.com" if pii_complete else None,
        "name": "Juan" if pii_complete else None,
        "document_number": "123" if pii_complete else None,
        "address": "Calle 1" if pii_complete else None,
    }
    contact_res = MagicMock(data=contact_data)

    # Chain de calls .table().select().eq().eq().eq().maybe_single().execute()
    def table_side_effect(name):
        chain = MagicMock()
        if name == "conversation_carts":
            chain.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = cart_res
        elif name == "cart_items":
            chain.select.return_value.eq.return_value.execute.return_value = items_res
        elif name == "contacts":
            chain.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = contact_res
        return chain

    sb.table.side_effect = table_side_effect
    return sb


class PassiveClosingTests(unittest.TestCase):

    def setUp(self):
        self.inv = PassiveClosingInvariant()
        self.kw_base = {
            "tenant_id": "t", "conversation_id": "c",
            "contact_id": "ct", "tool_call_log": [],
        }

    def test_texto_sin_cierre_pasivo_ok(self):
        """Outbound sin frase pasiva → OK."""
        result = _run(self.inv.validate(
            candidate_text="Te muestro los aceites disponibles.",
            supabase=_mock_supabase_with_cart(),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_pregunta_avanzante_no_se_reescribe(self):
        """Si LLM ya promueve siguiente paso, NO reescribir aunque
        tenga 'algo más' en otra parte."""
        result = _run(self.inv.validate(
            candidate_text=(
                "Agregué los jabones. ¿Sumamos algo más al pedido "
                "o ya coordinamos el envío? Dime a qué ciudad."
            ),
            supabase=_mock_supabase_with_cart(items_count=2),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_caso_runtime_3b0452e8_cart_sin_shipping(self):
        """Caso founder real (2026-05-22): 3 jabones agregados, sin
        cotización envío. Bot cierra '¿Hay algo más en lo que pueda
        ayudarte hoy?' → REWRITE con CTA de cotización."""
        result = _run(self.inv.validate(
            candidate_text=(
                "Perfecto! He agregado a tu carrito:\n"
                "* 1 Jabón Artesanal de Coco de 100g por $24.000\n"
                "* 2 Jabones Artesanales de Lavanda de 150g por $32.000 cada uno\n\n"
                "Hay algo más en lo que pueda ayudarte hoy?"
            ),
            supabase=_mock_supabase_with_cart(items_count=2, shipping_cents=0),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        # CTA correcto para cart con items + sin shipping.
        self.assertIn("envío", result.replacement_text.lower())
        # No debe quedar la frase pasiva.
        self.assertNotIn(
            "hay algo más en lo que pueda",
            result.replacement_text.lower(),
        )
        # Contenido útil preservado.
        self.assertIn("Jabón", result.replacement_text)
        self.assertIn("$24.000", result.replacement_text)

    def test_cart_con_shipping_sin_pii_pide_datos(self):
        """Cart con shipping cotizado pero PII incompleta → CTA pide PII."""
        result = _run(self.inv.validate(
            candidate_text=(
                "Listo, envío cotizado.\n\n"
                "¿Necesitas algo más?"
            ),
            supabase=_mock_supabase_with_cart(
                items_count=1, shipping_cents=15000, pii_complete=False,
            ),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        text = result.replacement_text.lower()
        # Pide datos / PII en lugar de "algo más".
        self.assertTrue(
            any(w in text for w in ["nombre", "dirección", "datos"]),
            f"Replacement no pide PII: {result.replacement_text}",
        )

    def test_cart_listo_pide_confirmacion_pago(self):
        """Cart con todo + PII completa → CTA pide confirmación pago."""
        result = _run(self.inv.validate(
            candidate_text=(
                "📋 *Resumen*\n* Coco 100g: $24.000\n"
                "Envío: $15.000\nTotal: $39.000\n\n"
                "¿Algo más?"
            ),
            supabase=_mock_supabase_with_cart(
                items_count=1, shipping_cents=15000, pii_complete=True,
            ),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        text = result.replacement_text.lower()
        self.assertTrue(
            any(w in text for w in ["confirmas", "link", "pago"]),
            f"Replacement no pide confirmación: {result.replacement_text}",
        )

    def test_cart_vacio_promueve_browse(self):
        """Cart vacío + cierre pasivo → empuja a presentar productos."""
        result = _run(self.inv.validate(
            candidate_text="Soy Sara. ¿En qué más puedo ayudarte?",
            supabase=_mock_supabase_with_cart(items_count=0),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        text = result.replacement_text.lower()
        self.assertTrue(
            any(w in text for w in ["producto", "categoría", "buscas"]),
            f"Replacement no promueve browse: {result.replacement_text}",
        )

    def test_estoy_a_tu_orden_se_reescribe(self):
        """'Quedo a tu orden / estoy a tu disposición' también es pasivo."""
        result = _run(self.inv.validate(
            candidate_text="Listo, agregado. Quedo a tu disposición.",
            supabase=_mock_supabase_with_cart(items_count=1),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)

    def test_supabase_falla_no_bloquea(self):
        """Si DB read falla, invariant no debe bloquear outbound."""
        sb = MagicMock()
        sb.table.side_effect = Exception("DB unreachable")
        result = _run(self.inv.validate(
            candidate_text="Listo. ¿Algo más?",
            supabase=sb,
            **self.kw_base,
        ))
        # Si falló DB, state defaults a items_count=0 → rewrite con browse.
        # NO debe raise. NO debe ser OK silenciosamente — re-escribe con CTA seguro.
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)

    def test_texto_vacio_ok(self):
        result = _run(self.inv.validate(
            candidate_text="",
            supabase=_mock_supabase_with_cart(),
            **self.kw_base,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)


if __name__ == "__main__":
    unittest.main()

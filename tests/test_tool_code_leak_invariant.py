"""ToolCodeLeakInvariant — el bot nunca filtra una tool-call como texto al cliente.

Bug runtime KAIU 2026-06-26 (cert ADR-0026): Gemini emitió
'tool_code\\nprint(add_to_cart(variation_id=..., quantity=1))' como texto.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.invariants.tool_code_leak import ToolCodeLeakInvariant  # noqa: E402
from agentic.invariants.base import InvariantOutcome  # noqa: E402


def _run(text):
    inv = ToolCodeLeakInvariant()
    return asyncio.run(
        inv.validate(
            candidate_text=text, tenant_id="t1", conversation_id="c1234567",
            contact_id="ct1", supabase=None, tool_call_log=[], inbound_text="",
        )
    )


class ToolCodeLeakTests(unittest.TestCase):
    def test_exact_founder_leak_rewritten(self):
        leak = ("tool_code\n"
                "print(add_to_cart(variation_id='9abc7c35-b8e9-49b9-ad20-7871773e1ba8', "
                "quantity=1))")
        r = _run(leak)
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("add_to_cart", r.replacement_text)
        self.assertNotIn("tool_code", r.replacement_text)
        self.assertNotIn("print(", r.replacement_text)

    def test_print_tool_pattern(self):
        r = _run("Claro!\nprint(quote_shipping(city='Medellín'))")
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_bare_tool_call_as_text(self):
        r = _run("Voy a agregarlo: add_to_cart(variation_id='x', quantity=2)")
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_code_fence_with_kwargs(self):
        r = _run("```python\nadd(variation_id='x')\n```")
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_normal_text_passes(self):
        r = _run("Listo, Cristian. Agregué el Sérum de Vitamina C de 30ml por $85.000.")
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_normal_text_with_parens_passes(self):
        # Texto legítimo con paréntesis NO debe disparar (sin nombre de tool).
        r = _run("Tu pedido (2 productos) queda en $109.000. ¿Coordinamos el envío?")
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_mentions_print_word_passes(self):
        # "imprime" / "print" en prosa sin call no dispara.
        r = _run("Te puedo enviar la factura para que la imprimas si gustas.")
        self.assertEqual(r.outcome, InvariantOutcome.OK)


if __name__ == "__main__":
    unittest.main()

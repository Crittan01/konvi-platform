"""Tests del CanonicalCategoriesInvariant (rev. 109 UAT live)."""
import asyncio
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.invariants import CanonicalCategoriesInvariant, InvariantOutcome


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_BASE_KWARGS = {
    "tenant_id": "t",
    "conversation_id": "c",
    "contact_id": "ct",
    "supabase": None,
    "tool_call_log": [],
    "inbound_text": "",
}


class CanonicalCategoriesTests(unittest.TestCase):
    def setUp(self):
        self.inv = CanonicalCategoriesInvariant()

    def test_serums_faciales_normalized(self):
        text = (
            "Buenas noches. Bienvenido/a a *KAIU Living Natural*.\n\n"
            "Te cuento lo que tenemos:\n"
            "* *Aceites Vegetales*: Naturales para piel y cabello.\n"
            "* *Aceites Esenciales*: Aromaterapia y bienestar.\n"
            "* *Jabones Artesanales*: Limpieza natural.\n"
            "* *Sérums Faciales*: Cuidado específico de la piel.\n"
            "* *Kits de Cuidado*: Rutinas completas.\n"
        )
        r = _run(self.inv.validate(candidate_text=text, **_BASE_KWARGS))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("Sérums", r.replacement_text)
        self.assertNotIn("Sérums Faciales", r.replacement_text)
        self.assertIn("Kits", r.replacement_text)
        self.assertNotIn("Kits de Cuidado", r.replacement_text)

    def test_serums_canonical_ok(self):
        text = (
            "Te cuento lo que tenemos:\n"
            "* *Aceites Vegetales*: ...\n"
            "* *Aceites Esenciales*: ...\n"
            "* *Jabones Artesanales*: ...\n"
            "* *Sérums*: ...\n"
            "* *Kits*: ...\n"
        )
        r = _run(self.inv.validate(candidate_text=text, **_BASE_KWARGS))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_not_category_listing_passes_through(self):
        """Outbound de cotización, pago, etc. NO se toca."""
        text = (
            "Para *Sérum de Vitamina C*, tenemos estas presentaciones:\n"
            "* 15ml por *$52.000 COP*\n"
            "* 30ml por *$85.000 COP*\n"
        )
        r = _run(self.inv.validate(candidate_text=text, **_BASE_KWARGS))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_kits_de_productos_normalized(self):
        text = (
            "* *Aceites Vegetales*: A.\n"
            "* *Aceites Esenciales*: B.\n"
            "* *Jabones Artesanales*: C.\n"
            "* *Sérums Faciales*: D.\n"
            "* *Kits de Productos*: E.\n"
        )
        r = _run(self.inv.validate(candidate_text=text, **_BASE_KWARGS))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("Kits de Productos", r.replacement_text)
        self.assertIn("Kits", r.replacement_text)

    def test_empty_text_ok(self):
        r = _run(self.inv.validate(candidate_text="", **_BASE_KWARGS))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_no_categories_in_short_response_ok(self):
        text = "Listo, agregué 1 Sérum al carrito."
        r = _run(self.inv.validate(candidate_text=text, **_BASE_KWARGS))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_preserves_surrounding_text(self):
        text = (
            "Buenas tardes.\n\n"
            "* *Aceites Vegetales*: aceites puros.\n"
            "* *Aceites Esenciales*: extractos.\n"
            "* *Jabones Artesanales*: a mano.\n"
            "* *Sérums Faciales*: fórmulas.\n"
            "* *Kits de Cuidado*: rutinas.\n\n"
            "Qué te interesa?"
        )
        r = _run(self.inv.validate(candidate_text=text, **_BASE_KWARGS))
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("Buenas tardes", r.replacement_text)
        self.assertIn("Qué te interesa?", r.replacement_text)


if __name__ == "__main__":
    unittest.main()

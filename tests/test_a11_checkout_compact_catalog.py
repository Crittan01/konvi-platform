"""A11 2026-06-26 — Fix B: catálogo compacto en estados de checkout.

Causa raíz del falso "solo 30ml": el prompt omitía el catálogo en estados
post-carrito (_NO_CATALOG_STATES). Fix B inyecta una referencia COMPACTA
(variantes+precio, sin descripciones/safety) en checkout para que el bot
conozca las variantes reales si el cliente agrega un producto a mitad de flujo.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.prompt.builder import build_prompt_for_state  # noqa: E402
from agentic.state_machine.states import AgenticState  # noqa: E402

_CATALOG = [{
    "id": "be7cdeca", "title": "Sérum de Vitamina C",
    "description": "Descripción larga de beneficios y usos del sérum.",
    "safety_note": "No aplicar directo en los ojos.",
    "variants": [
        {"id": "v15", "label": "15ml", "price": 52000},
        {"id": "v30", "label": "30ml", "price": 85000},
    ],
}]


def _prompt(state):
    return build_prompt_for_state(state=state, tenant_name="KAIU", catalog=_CATALOG)


class CheckoutCompactCatalogTests(unittest.TestCase):
    def test_payment_tiene_variantes_pero_no_descripcion(self):
        p = _prompt(AgenticState.PAYMENT)
        self.assertIn("15ml", p)
        self.assertIn("30ml", p)
        self.assertIn("52.000", p)
        # Compacto: SIN descripción larga ni safety proactiva.
        self.assertNotIn("Descripción larga", p)
        self.assertNotIn("No aplicar directo", p)

    def test_carrier_selection_tiene_variantes(self):
        p = _prompt(AgenticState.CARRIER_SELECTION)
        self.assertIn("15ml", p)
        self.assertIn("30ml", p)

    def test_exploring_tiene_catalogo_completo(self):
        p = _prompt(AgenticState.EXPLORING)
        self.assertIn("15ml", p)
        self.assertIn("Descripción larga", p)  # full catalog incluye descripción

    def test_post_payment_sin_catalogo(self):
        # POST_PAYMENT no recibe catálogo (no aplica agregar productos).
        p = _prompt(AgenticState.POST_PAYMENT)
        self.assertNotIn("15ml", p)


if __name__ == "__main__":
    unittest.main()

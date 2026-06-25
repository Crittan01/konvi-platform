"""FITNESS FUNCTION (A11 maturity, Clase A) — contrato de catálogo single-source.

Hace IMPOSIBLE de reintroducir el bug más severo de la auditoría: el guard
anti-alucinación leía `product_variations` mientras el productor emitía `variants`
→ bloqueaba TODA venta por el path agentic. La cura estructural es una constante
ÚNICA compartida (`CATALOG_VARIATIONS_KEY`); este pact falla si productor y
consumidor dejan de compartirla.

Corre SIEMPRE en la suite (no mutation test manual) — esa es la garantía durable
contra que el guardrail se degrade a no-op (estrategia A11, §3 regla anti-no-op).
"""
import inspect
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.catalog_contract import CATALOG_VARIATIONS_KEY  # noqa: E402
import tools.catalog_tool as catalog_tool  # noqa: E402
from agentic.invariants import tool_id_referential_integrity as invariant  # noqa: E402


class CatalogContractPactTests(unittest.TestCase):
    def test_producer_and_consumer_import_same_constant(self):
        # Provablemente alineados: el mismo objeto-constante en ambos lados.
        self.assertIs(catalog_tool.CATALOG_VARIATIONS_KEY, CATALOG_VARIATIONS_KEY)
        self.assertIs(invariant.CATALOG_VARIATIONS_KEY, CATALOG_VARIATIONS_KEY)

    def test_consumer_recognizes_catalog_built_with_canonical_key(self):
        # PACT round-trip: el guard DEBE reconocer variation_ids de un catálogo
        # construido bajo la clave canónica. Si el guard deja de leerla → falla.
        item = {"id": "p1", CATALOG_VARIATIONS_KEY: [{"id": "v1"}, {"id": "v2"}]}
        known = invariant._extract_known_ids_from_catalog([item])
        self.assertIn("v1", known)
        self.assertIn("v2", known)

    def test_producer_emits_under_canonical_constant_not_literal(self):
        # El productor DEBE emitir las variantes bajo la constante compartida,
        # no un literal divergente (que reintroduciría la Clase A).
        src = inspect.getsource(catalog_tool.get_tenant_catalog)
        self.assertIn(
            "CATALOG_VARIATIONS_KEY:", src,
            "get_tenant_catalog debe emitir variantes bajo CATALOG_VARIATIONS_KEY, "
            "no un literal hardcoded (Clase A regresaría)",
        )

    def test_fixture_bug_divergent_key_is_caught(self):
        # Auto-validación del guardrail (fixture-bug): si el catálogo usa una clave
        # DISTINTA a la canónica, el consumidor NO reconoce la variación → el bug
        # se manifiesta. Demuestra que el pact detecta la divergencia.
        divergent = {"id": "p1", "variaciones": [{"id": "v1"}]}  # clave equivocada
        known = invariant._extract_known_ids_from_catalog([divergent])
        self.assertNotIn("v1", known)  # NO reconocida → el pact protege contra esto


if __name__ == "__main__":
    unittest.main()

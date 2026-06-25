"""Tests de regresión — P0 hallados por la auditoría arquitectónica A11 (2026-06-25).

Estos 3 bugs eran de Clase A (contrato de datos desincronizado entre productor y
consumidor) y escaparon a los 2948 tests porque los fixtures mockeaban la *forma
equivocada* que coincidía con el código roto. La cura de la clase: anclar el test
al OUTPUT REAL del productor, no a un shape inventado.

P0-1  Guard anti-alucinación leía key `product_variations`/`variations` mientras
      `catalog_tool.get_tenant_catalog` emite `variants` → known_ids nunca tenía
      variation_ids → bloqueaba TODO add_to_cart válido por el path agentic LLM.
P0-3  Startup sweep de mensajes atascados hacía SELECT sin `tenant_id` pero luego
      `.eq("tenant_id", msg["tenant_id"])` → KeyError → recuperación rota.
P0-4  `sys` usado bare en el cron hard-delete sin `import sys` a nivel módulo →
      NameError al ejecutar.
"""
import os
import re
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
ORCH = os.path.join(REPO, "services", "ai-orchestrator")
sys.path.insert(0, ORCH)

from agentic.invariants.tool_id_referential_integrity import (  # noqa: E402
    _extract_known_ids_from_catalog,
    check_tool_id_referential_integrity,
)

WORKER_PY = os.path.join(ORCH, "worker.py")
CATALOG_TOOL_PY = os.path.join(ORCH, "tools", "catalog_tool.py")


class P0_1_CatalogVariantsKeyTests(unittest.TestCase):
    """El guard DEBE reconocer variation_ids del catálogo canónico (key `variants`)."""

    def test_extract_known_ids_reads_variants_key(self):
        # Shape EXACTO que produce catalog_tool.get_tenant_catalog (key `variants`).
        catalog = [{"id": "p1", "title": "Coco", "variants": [{"id": "v60"}, {"id": "v100"}]}]
        known = _extract_known_ids_from_catalog(catalog)
        self.assertIn("v60", known)
        self.assertIn("v100", known)
        self.assertIn("p1", known)

    def test_valid_variation_not_blocked_with_variants_catalog(self):
        catalog = [{"id": "p1", "variants": [{"id": "v60"}]}]
        block = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": "p1", "variation_id": "v60"},
            catalog=catalog,
        )
        self.assertIsNone(block, "variation_id válido NO debe bloquearse (rompía ventas)")

    def test_invented_variation_still_blocked(self):
        # El guard NO debe perder su función anti-alucinación.
        catalog = [{"id": "p1", "variants": [{"id": "v60"}]}]
        block = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": "p1", "variation_id": "INVENTADO-UUID"},
            catalog=catalog,
        )
        self.assertIsNotNone(block)
        self.assertEqual(block.get("code"), "MUST_LIST_CATALOG_FIRST")

    def test_legacy_product_variations_key_still_works(self):
        # Retrocompat: si alguna vez se pasa el shape crudo de DB, sigue funcionando.
        catalog = [{"id": "p1", "product_variations": [{"id": "v60"}]}]
        self.assertIn("v60", _extract_known_ids_from_catalog(catalog))

    def test_catalog_tool_emits_under_shared_constant(self):
        """COHERENCE PACT (A11 maturity): el productor emite variantes bajo la
        constante compartida CATALOG_VARIATIONS_KEY (single source), no un literal.
        El pact completo vive en tests/test_audit_catalog_contract.py."""
        src = open(CATALOG_TOOL_PY, encoding="utf-8").read()
        self.assertIn("CATALOG_VARIATIONS_KEY:", src,
                      "catalog_tool dejó de emitir bajo la constante — Clase A regresaría")


class P0_3_WorkerSweepTenantIdTests(unittest.TestCase):
    """El SELECT del sweep DEBE incluir tenant_id (las updates lo usan)."""

    def test_sweep_select_includes_tenant_id(self):
        src = open(WORKER_PY, encoding="utf-8").read()
        # El sweep de mensajes atascados selecciona id + processing_attempts + tenant_id.
        self.assertIn('.select("id, processing_attempts, tenant_id")', src,
                      "el sweep debe seleccionar tenant_id o las updates lanzan KeyError")


class P0_4_WorkerImportsSysTests(unittest.TestCase):
    """`sys` usado bare en el cron hard-delete requiere import a nivel módulo."""

    def test_worker_imports_sys_module_level(self):
        src = open(WORKER_PY, encoding="utf-8").read()
        self.assertRegex(src, r"(?m)^import sys\b",
                         "worker.py usa sys.path bare → requiere import sys a nivel módulo")


if __name__ == "__main__":
    unittest.main()

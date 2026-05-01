"""Rev. 90 + 92 — Test del rule LISTADO TRUNCADO en el system prompt.

UX observado: cuando el bot lista catálogo ("¿qué tienen?"), si lista
TODOS los productos por categoría puede:
  • Abrumar al cliente (paredes de texto).
  • Crear sensación falsa de "esos son TODOS los productos" cuando
    en realidad hay más en el catálogo del tenant.

Patrón canónico (rev. 92): MÁXIMO 2 ítems concretos por categoría +
3er bullet en cursiva `* _Entre otros..._` cuando hay ≥3 ítems.

Como el system prompt está hardcoded, este test verifica que el string
de la regla esté presente y no se haya removido por accidente.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")


class ListadoTruncadoPromptRuleTests(unittest.TestCase):

    def setUp(self):
        with open(
            "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator/orchestrator.py",
            encoding="utf-8",
        ) as fh:
            self.src = fh.read()

    def test_listado_truncado_rule_present(self):
        self.assertIn("LISTADO TRUNCADO", self.src)

    def test_rule_specifies_max_2_items_per_category(self):
        # Rev. 92: pasamos de "máximo 3" a "máximo 2".
        self.assertIn("MÁXIMO 2 ítems", self.src)

    def test_rule_specifies_entre_otros_marker(self):
        # Patrón canónico rev. 92: cursiva genérica "Entre otros".
        self.assertIn("_Entre otros..._", self.src)

    def test_rule_explains_motivation(self):
        # Justificación: evitar abrumar + sensación falsa de "todos".
        self.assertTrue(
            "abrumar" in self.src.lower()
            or "sensación falsa" in self.src.lower()
        )

    def test_rule_handles_n_equals_1_case(self):
        # Si solo hay 1 ítem en la categoría, mostrar solo ese 1
        # (sin "Entre otros").
        self.assertIn("Si la categoría tiene N=1", self.src)

    def test_rule_handles_n_equals_2_case(self):
        # Si hay 2 ítems exactos, mostrar los 2 sin "Entre otros".
        self.assertIn("Si la categoría tiene N=2", self.src)

    def test_rule_allows_4_items_for_single_category_query(self):
        # Cuando el cliente pregunta específico, hasta 4 + "Entre otros".
        self.assertIn("hasta 4 ítems", self.src)


if __name__ == "__main__":
    unittest.main()

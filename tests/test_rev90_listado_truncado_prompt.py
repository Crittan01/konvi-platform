"""Rev. 90 — Test del rule LISTADO TRUNCADO en el system prompt.

UX observado: cuando el bot lista catálogo ("¿qué tienen?"), si lista
TODOS los productos por categoría puede:
  • Abrumar al cliente (paredes de texto).
  • Crear sensación falsa de "esos son TODOS los productos" cuando
    en realidad hay más en el catálogo del tenant.

Fix rev. 90: agregar regla en el FORMATO WhatsApp del system prompt
indicando truncar cada categoría a 3 ítems + "y N más..." en cursiva.

Como el system prompt está hardcoded, este test verifica que el string
de la regla esté presente y no se haya removido por accidente. No es
un test de comportamiento del LLM (eso vive en E2E), es un test de
contrato del prompt.
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

    def test_rule_specifies_max_3_items_per_category(self):
        # Frase clave: "NO listes más de 3 ítems".
        self.assertIn("NO listes más de 3 ítems", self.src)

    def test_rule_specifies_y_N_mas_pattern(self):
        # Patrón canónico para indicar productos restantes.
        self.assertIn("y N-3 más", self.src)

    def test_rule_explains_motivation(self):
        # Justificación: evitar abrumar + sensación falsa de "todos".
        self.assertTrue(
            "abrumar" in self.src.lower()
            or "sensación falsa" in self.src.lower()
        )

    def test_rule_allows_5_items_for_single_category_query(self):
        # Si el cliente pregunta específico ("¿qué jabones tienen?"),
        # se permite hasta 5.
        self.assertTrue(
            "hasta 5" in self.src or "puedes mostrar hasta 5" in self.src
        )


if __name__ == "__main__":
    unittest.main()

"""Rev. 90 + 92 + 103 — Test del rule de listado de catálogo en system prompt.

Evolución:
  Rev. 90 — listado truncado a máx 3 ítems por categoría.
  Rev. 92 — endurecido a máx 2 ítems + cursiva "Entre otros".
  Rev. 103 — minimalismo agresivo (UAT S2 feedback): catálogo AMPLIO
    muestra SOLO nombres de categorías (≤5), sin productos. Cuando
    cliente pregunta UNA categoría, profundiza hasta 4 productos.

Como el system prompt está hardcoded, este test verifica que las reglas
clave estén presentes y no se hayan removido por accidente.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")


class ListadoTruncadoPromptRuleTests(unittest.TestCase):

    def setUp(self):
        # Rev. 104 (F1-4) — el cuerpo del system prompt vive ahora en
        # `prompt/builder.py`. Concatenamos ambos archivos para que los
        # asserts por substring sigan validando contenido sin importar
        # en qué módulo aterrizó tras la extracción.
        sources = []
        for path in (
            "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/orchestrator.py",
            "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/prompt/builder.py",
        ):
            with open(path, encoding="utf-8") as fh:
                sources.append(fh.read())
        self.src = "\n".join(sources)

    def test_catalogo_amplio_rule_present(self):
        # Rev. 103 — sustituye "LISTADO TRUNCADO" por "LISTADO DE CATÁLOGO AMPLIO".
        self.assertIn("LISTADO DE CATÁLOGO AMPLIO", self.src)

    def test_rule_specifies_max_5_categories(self):
        # Rev. 103: catálogo amplio muestra máx 5 categorías.
        self.assertIn("MÁXIMO 5 categorías", self.src)

    def test_rule_specifies_no_products_in_amplio(self):
        # Rev. 103: catálogo amplio NO muestra productos ejemplo.
        self.assertIn("sin productos ejemplo", self.src)

    def test_rule_specifies_no_prices_in_amplio(self):
        # Rev. 103: catálogo amplio NO muestra precios.
        self.assertIn("SIN precios en respuesta amplia", self.src)

    def test_rule_specifies_entre_otros_marker(self):
        # Patrón canónico cuando se profundiza: cursiva "_Entre otros..._".
        self.assertIn("_Entre otros..._", self.src)

    def test_rule_explains_motivation(self):
        # Justificación: ahorro tokens + minimalismo.
        self.assertTrue(
            "minimalismo" in self.src.lower()
            or "ahorro" in self.src.lower()
            or "abrumar" in self.src.lower()
        )

    def test_rule_allows_4_items_for_specific_category_query(self):
        # Cuando el cliente pregunta específico (UNA categoría), bot
        # profundiza hasta 4 productos + "Entre otros".
        self.assertIn("hasta 4 productos", self.src)

    def test_rule_specifies_marketing_blockquote(self):
        # Rev. 103: blockquote con marketing indirecto al final.
        self.assertIn("MARKETING INDIRECTO", self.src)

    def test_rule_specifies_discovery_question(self):
        # Cierre con pregunta de discovery activo.
        self.assertIn("Sobre cuál te cuento más", self.src)


if __name__ == "__main__":
    unittest.main()

"""Rev. 81 — Test de integración: el call site principal de orchestrator
usa generate_with_cascade en vez de invocación directa.

No corremos el orchestrator completo (requiere muchos fixtures); validamos
la integración por inspección estructural.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")


class CascadeIntegrationTests(unittest.TestCase):

    def test_orchestrator_imports_cascade_helpers(self):
        """orchestrator.py debe importar generate_with_cascade y
        degraded_response_text en el call site principal."""
        with open(
            "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/orchestrator.py",
            encoding="utf-8",
        ) as f:
            src = f.read()
        self.assertIn(
            "from llm_invoke import generate_with_cascade, degraded_response_text",
            src,
            "Falta import de cascada en orchestrator",
        )
        self.assertIn(
            "cascade = generate_with_cascade(",
            src,
            "Falta invocación de generate_with_cascade",
        )
        self.assertIn(
            "from llm_router import classify_intent, model_pair_for",
            src,
            "Falta integración del model router",
        )
        self.assertIn(
            "if cascade.degraded:",
            src,
            "Falta branch de degradado en orchestrator",
        )
        self.assertIn(
            "raw_json = degraded_response_text()",
            src,
            "Falta uso de degraded_response_text como fallback",
        )

    def test_old_direct_call_replaced_in_main_path(self):
        """La llamada directa a client.models.generate_content ya no debe
        estar en el call site principal (sigue existiendo en línea 626
        para audio transcription, eso es OK)."""
        with open(
            "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/orchestrator.py",
            encoding="utf-8",
        ) as f:
            src = f.read()
        # Localizar la sección "## ── 4. Llamar a Gemini" — debe haber
        # mención de cascade, no llamada directa con system_instruction.
        section_idx = src.find("# ── 4. Llamar a Gemini")
        self.assertGreater(section_idx, 0, "No se encontró sección Gemini call")
        section = src[section_idx:section_idx + 3000]
        # En el call site principal debe usar la cascada.
        self.assertIn("generate_with_cascade", section)
        # Debe haber un closure _invoke_gemini.
        self.assertIn("def _invoke_gemini(model_name", section)


if __name__ == "__main__":
    unittest.main()

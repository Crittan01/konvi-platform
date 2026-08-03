"""M8 (2026-08-02) — default de modelo Gemini unificado.

Antes: `orchestrator.py` defaultaba GEMINI_MODEL a gemini-3.5-flash y
`llm_invoke.py` a gemini-3.1-flash-lite (el primario real de prod en
render.yaml). Ahora la fuente única es `llm_invoke.DEFAULT_PRIMARY_MODEL` /
`DEFAULT_FALLBACK_MODEL` y todos los consumidores los referencian.
"""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

import llm_invoke


class SingleSourceOfTruthTests(unittest.TestCase):
    def test_default_primario_es_el_de_prod(self):
        """render.yaml declara GEMINI_MODEL=gemini-3.1-flash-lite para el
        orchestrator — el default de código debe coincidir."""
        self.assertEqual(llm_invoke.DEFAULT_PRIMARY_MODEL, "gemini-3.1-flash-lite")
        self.assertEqual(llm_invoke.DEFAULT_FALLBACK_MODEL, "gemini-3.5-flash")

    def test_orchestrator_consume_la_constante(self):
        """orchestrator.GEMINI_MODEL = env GEMINI_MODEL o, en su defecto,
        el default unificado de llm_invoke (no un literal propio)."""
        import orchestrator
        expected = os.getenv("GEMINI_MODEL", llm_invoke.DEFAULT_PRIMARY_MODEL)
        self.assertEqual(orchestrator.GEMINI_MODEL, expected)
        if "GEMINI_MODEL" not in os.environ:
            self.assertEqual(
                orchestrator.GEMINI_MODEL, llm_invoke.DEFAULT_PRIMARY_MODEL,
            )

    def test_router_sin_divergencia(self):
        """llm_router: los defaults de GEMINI_MODEL / GEMINI_FALLBACK_MODEL
        son las constantes de llm_invoke (guard anti-drift)."""
        import llm_router
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GEMINI_SIMPLE_MODEL")
        }
        with patch.dict(os.environ, env, clear=True):
            primary_t, fallback_t = llm_router._models_transactional()
            primary_s, fallback_s = llm_router._models_simple()
        self.assertEqual(primary_t, llm_invoke.DEFAULT_PRIMARY_MODEL)
        self.assertEqual(fallback_t, llm_invoke.DEFAULT_FALLBACK_MODEL)
        self.assertEqual(primary_s, llm_invoke.DEFAULT_PRIMARY_MODEL)
        self.assertEqual(fallback_s, llm_invoke.DEFAULT_FALLBACK_MODEL)

    def test_env_gemini_model_sigue_ganando(self):
        """La unificación no rompe el override por env (prod lo usa)."""
        import llm_router
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-custom-x"}):
            primary_t, _ = llm_router._models_transactional()
        self.assertEqual(primary_t, "gemini-custom-x")


if __name__ == "__main__":
    unittest.main()

"""A6 (2026-08-02) — rescate Claude eliminado.

El paquete `anthropic` nunca estuvo en requirements → `is_available()` era
siempre False y el tier de rescate era código muerto que mentía en los
docstrings. Se eliminó `llm_claude_rescue.py` y su invocación en
`agentic/agent.py`; los recoveries reales (retry history reducido, retry
text-only) quedaron intactos.
"""
import importlib.util
import os
import pathlib
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

_SERVICE_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"
)
sys.path.insert(0, str(_SERVICE_DIR))


class ClaudeRescueRemovedTests(unittest.TestCase):
    def test_modulo_no_existe(self):
        self.assertFalse((_SERVICE_DIR / "llm_claude_rescue.py").exists())

    def test_modulo_no_importable(self):
        self.assertIsNone(importlib.util.find_spec("llm_claude_rescue"))

    def test_agent_py_no_lo_referencia(self):
        src = (_SERVICE_DIR / "agentic" / "agent.py").read_text(encoding="utf-8")
        self.assertNotIn("llm_claude_rescue", src)
        self.assertNotIn("invoke_claude_text_only", src)
        self.assertNotIn("claude_available", src)
        self.assertNotIn("AGENTIC_CLAUDE_RESCUE", src)

    def test_anthropic_no_esta_en_requirements(self):
        """Guard de la causa raíz: si alguien añade el tier de vuelta, debe
        ser una decisión consciente (paquete + tier + tests juntos)."""
        req = (_SERVICE_DIR / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("anthropic", req.lower())

    def test_agent_py_sigue_importable(self):
        """El agentic loop conserva sus recoveries reales tras la poda."""
        import agentic.agent  # noqa: F401


if __name__ == "__main__":
    unittest.main()

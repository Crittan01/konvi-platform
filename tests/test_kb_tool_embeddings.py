"""Tests `kb_tool._embed_query_vector` post-rev106 cascada delegada a llm_embed.

Rev. 106 movió toda la lógica de cascade + retries + cache a
`services/ai-orchestrator/llm_embed.py:embed_with_cascade`. Antes el test
patcheaba `kb_tool.GEMINI_EMBEDDING_MODEL` directo — ese símbolo ya NO
existe en kb_tool (ahora vive en llm_embed). Cleanup 2026-05-29:
re-mockear embed_with_cascade y testear el wrapper delgado de kb_tool
(delegación correcta + raise si degraded).
"""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools import kb_tool
from llm_embed import EmbedResult


class _ClientStub:
    """Cliente genai stub — solo presente; toda lógica está en embed_with_cascade."""


class KbToolEmbeddingsTests(unittest.TestCase):
    """Cubre `_embed_query_vector` post-rev106 (wrapper delgado sobre llm_embed)."""

    def test_embed_query_retorna_values_si_no_degraded(self):
        """Happy path: embed_with_cascade retorna vector → wrapper lo devuelve."""
        client = _ClientStub()
        result_ok = EmbedResult(
            values=[0.1, 0.2, 0.3],
            model_used="gemini-embedding-001",
            attempts=1,
            degraded=False,
        )
        with patch.object(kb_tool, "embed_with_cascade", return_value=result_ok):
            vector = kb_tool._embed_query_vector(client, "hola")
        self.assertEqual(vector, [0.1, 0.2, 0.3])

    def test_embed_query_levanta_si_degraded(self):
        """Si embed_with_cascade retorna degraded=True → RuntimeError con detalle."""
        client = _ClientStub()
        result_degraded = EmbedResult(
            values=None,
            model_used=None,
            attempts=7,
            degraded=True,
            last_error="503 Service Unavailable",
        )
        with patch.object(kb_tool, "embed_with_cascade", return_value=result_degraded):
            with self.assertRaises(RuntimeError) as ctx:
                kb_tool._embed_query_vector(client, "consulta")
        self.assertIn("embed_cascade_exhausted", str(ctx.exception))
        self.assertIn("7 attempts", str(ctx.exception))
        self.assertIn("503 Service Unavailable", str(ctx.exception))

    def test_embed_query_levanta_si_values_vacios(self):
        """Si values está vacío (defensa contra response malformed), también RuntimeError."""
        client = _ClientStub()
        result_empty = EmbedResult(
            values=[],  # vector vacío inesperado
            model_used="gemini-embedding-001",
            attempts=1,
            degraded=False,
        )
        with patch.object(kb_tool, "embed_with_cascade", return_value=result_empty):
            with self.assertRaises(RuntimeError):
                kb_tool._embed_query_vector(client, "x")

    def test_embed_query_pasa_query_a_cascade(self):
        """Verifica que el query del caller llega tal cual a embed_with_cascade."""
        client = _ClientStub()
        captured = {}

        def fake_cascade(c, text, **kwargs):
            captured["client"] = c
            captured["text"] = text
            return EmbedResult(values=[1.0], model_used="m1", attempts=1, degraded=False)

        with patch.object(kb_tool, "embed_with_cascade", side_effect=fake_cascade):
            kb_tool._embed_query_vector(client, "mi consulta de búsqueda")

        self.assertIs(captured["client"], client)
        self.assertEqual(captured["text"], "mi consulta de búsqueda")


if __name__ == "__main__":
    unittest.main()

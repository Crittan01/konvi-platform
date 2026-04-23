import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools import kb_tool


class _Embedding:
    def __init__(self, values):
        self.values = values


class _EmbedResponse:
    def __init__(self, values):
        self.embeddings = [_Embedding(values)]


class _ModelsStub:
    def __init__(self, responses):
        self._responses = list(responses)
        self.called_models = []

    def embed_content(self, model, contents):
        self.called_models.append(model)
        if not self._responses:
            raise AssertionError("No hay respuestas stub configuradas")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _ClientStub:
    def __init__(self, responses):
        self.models = _ModelsStub(responses)


class KbToolEmbeddingsTests(unittest.TestCase):
    def test_embed_query_uses_primary_model(self):
        client = _ClientStub([_EmbedResponse([0.1, 0.2, 0.3])])
        with (
            patch.object(kb_tool, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
            patch.object(kb_tool, "GEMINI_EMBEDDING_FALLBACK_MODEL", "text-embedding-004"),
        ):
            vector = kb_tool._embed_query_vector(client, "hola")

        self.assertEqual(vector, [0.1, 0.2, 0.3])
        self.assertEqual(client.models.called_models, ["gemini-embedding-001"])

    def test_embed_query_retries_with_fallback_on_404(self):
        client = _ClientStub(
            [
                RuntimeError("404 NOT_FOUND: model unavailable"),
                _EmbedResponse([0.9, 0.8]),
            ]
        )
        with (
            patch.object(kb_tool, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
            patch.object(kb_tool, "GEMINI_EMBEDDING_FALLBACK_MODEL", "text-embedding-004"),
        ):
            vector = kb_tool._embed_query_vector(client, "consulta prueba")

        self.assertEqual(vector, [0.9, 0.8])
        self.assertEqual(
            client.models.called_models,
            ["gemini-embedding-001", "text-embedding-004"],
        )


if __name__ == "__main__":
    unittest.main()

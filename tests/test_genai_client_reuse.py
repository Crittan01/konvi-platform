"""Test del reuso del cliente Gemini por proceso (perf rev. 114).

Invariante: `_get_genai_client` reusa un único genai.Client por api_key (no crea
uno —con pool TLS nuevo— por mensaje). Distinta api_key → cliente distinto (no
filtra entre entornos/tests).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

import agentic.agent as agent_mod  # noqa: E402


class _FakeTypes:
    @staticmethod
    def HttpOptions(**kwargs):
        return kwargs


class _FakeGenai:
    def __init__(self):
        self.constructed = 0

    def Client(self, **kwargs):
        self.constructed += 1
        return f"client-{self.constructed}"


class GenaiClientReuseTests(unittest.TestCase):
    def setUp(self):
        agent_mod._GENAI_CLIENTS.clear()

    def test_reused_within_same_key(self):
        fg, ft = _FakeGenai(), _FakeTypes()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k1"}):
            c1 = agent_mod._get_genai_client(fg, ft)
            c2 = agent_mod._get_genai_client(fg, ft)
        self.assertIs(c1, c2, "debe reusar el mismo cliente")
        self.assertEqual(fg.constructed, 1, "debe construir el cliente 1 sola vez")

    def test_distinct_key_distinct_client(self):
        fg, ft = _FakeGenai(), _FakeTypes()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k1"}):
            c1 = agent_mod._get_genai_client(fg, ft)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k2"}):
            c3 = agent_mod._get_genai_client(fg, ft)
        self.assertNotEqual(c1, c3, "distinta api_key → cliente distinto")
        self.assertEqual(fg.constructed, 2)


if __name__ == "__main__":
    unittest.main()

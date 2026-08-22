"""Tests Track 6 / Gemini (2026-08-22) — telemetría de uso desagregada + flag VALIDATED.

Fase 0 del ahorro por caching: la doc oficial NO garantiza implicit caching para
gemini-3.1-flash-lite (la tabla de mínimos omite los Lite) → medir, no asumir.
`_extract_usage` desagrega usage_metadata (prompt/cached/thoughts) por turno.
VALIDATED (constrained decoding de function calls) va detrás de flag env para
canary STG antes de volverse default.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))

from agentic import agent  # noqa: E402


class ExtractUsageTests(unittest.TestCase):
    def test_breakdown_completo(self):
        resp = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                total_token_count=1200,
                prompt_token_count=1000,
                cached_content_token_count=800,
                thoughts_token_count=50,
            )
        )
        u = agent._extract_usage(resp)
        self.assertEqual(u["total_tokens"], 1200)
        self.assertEqual(u["prompt_tokens"], 1000)
        self.assertEqual(u["cached_tokens"], 800)
        self.assertEqual(u["thoughts_tokens"], 50)

    def test_sin_usage_metadata_ceros(self):
        resp = SimpleNamespace(usage_metadata=None)
        u = agent._extract_usage(resp)
        self.assertEqual(u, {"total_tokens": 0, "prompt_tokens": 0, "cached_tokens": 0, "thoughts_tokens": 0})

    def test_response_sin_usage_no_rompe(self):
        u = agent._extract_usage(object())
        self.assertEqual(u["total_tokens"], 0)

    def test_campos_parciales(self):
        resp = SimpleNamespace(usage_metadata=SimpleNamespace(total_token_count=100))
        u = agent._extract_usage(resp)
        self.assertEqual(u["total_tokens"], 100)
        self.assertEqual(u["cached_tokens"], 0)

    def test_extract_total_tokens_consistente(self):
        resp = SimpleNamespace(usage_metadata=SimpleNamespace(total_token_count=42))
        self.assertEqual(agent._extract_total_tokens(resp), 42)


class ValidatedFlagTests(unittest.TestCase):
    """El tool_config con mode=VALIDATED solo se activa con el flag env (canary STG)."""

    def _build_config(self, tools_present: bool):
        from google.genai import types as genai_types
        _cfg_kwargs = dict(system_instruction="x", temperature=0.2, tools=["tool"] if tools_present else None)
        if tools_present and os.getenv("AGENTIC_TOOL_VALIDATED_ENABLED", "false").lower() == "true":
            _cfg_kwargs["tool_config"] = genai_types.ToolConfig(
                function_calling_config=genai_types.FunctionCallingConfig(
                    mode=genai_types.FunctionCallingConfigMode.VALIDATED
                )
            )
        return genai_types.GenerateContentConfig(**_cfg_kwargs)

    def test_flag_off_no_tool_config(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTIC_TOOL_VALIDATED_ENABLED", None)
            cfg = self._build_config(tools_present=True)
            self.assertIsNone(cfg.tool_config)

    def test_flag_on_tool_config_validated(self):
        with patch.dict(os.environ, {"AGENTIC_TOOL_VALIDATED_ENABLED": "true"}):
            cfg = self._build_config(tools_present=True)
            self.assertIsNotNone(cfg.tool_config)
            self.assertEqual(
                cfg.tool_config.function_calling_config.mode.name, "VALIDATED",
            )

    def test_flag_on_sin_tools_no_tool_config(self):
        """Sin tools en el turn (retry text-only), no se fija tool_config."""
        with patch.dict(os.environ, {"AGENTIC_TOOL_VALIDATED_ENABLED": "true"}):
            cfg = self._build_config(tools_present=False)
            self.assertIsNone(cfg.tool_config)


if __name__ == "__main__":
    unittest.main()

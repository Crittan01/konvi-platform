"""Tests cascada Gemini en agentic.

Rev. 106 — fix bug observado conv 2eb3bb48 (founder UAT 2026-05-22):
Gemini 2.5 flash 503 UNAVAILABLE colapsó agentic directo a empty_output
sin reintentos ni fallback. Causa: `_gemini_generate_async` no usaba
`generate_with_cascade` de llm_invoke.py (Rev. 80, ADR-0001) que ya
existía en legacy.

Fix: envolver invocación en cascada heredada — 4 intentos en primary
(flash) + 4 en fallback (flash-lite) con backoff exponencial, NO
retries en errores no-transitorios (bug schema/prompt).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
# NO seteamos GEMINI_API_KEY: el test usa MagicMock() para el client
# y ningún componente real consume la env var. Si se seteara con valor
# fake, contaminaría tests E2E posteriores (golden conversations).

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeGenAIPart:
    def __init__(self, text=None, function_call=None, function_response=None):
        self.text = text
        self.function_call = function_call
        self.function_response = function_response


class _FakeContent:
    def __init__(self, parts):
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts):
        self.content = _FakeContent(parts)


class _FakeResponse:
    def __init__(self, text):
        self.candidates = [_FakeCandidate([_FakeGenAIPart(text=text)])]


class GeminiCascadeTests(unittest.TestCase):
    """Verifica que la cascada heredada de llm_invoke.py funciona dentro
    del agentic agent.py post-rev. 106."""

    def test_503_primary_se_recupera_fallback_lite(self):
        """503 sostenido en flash → switch a flash-lite → éxito."""
        from agentic import agent as agentic_agent

        client = MagicMock()
        call_log: list[str] = []

        def gen_content(model, contents, config):
            call_log.append(model)
            if model == "gemini-3.5-flash":
                # Simula 503 todos los intentos en flash.
                raise RuntimeError("503 UNAVAILABLE — high demand")
            elif model == "gemini-3.1-flash-lite":
                return _FakeResponse("Hola desde lite")
            raise RuntimeError(f"unexpected model: {model}")

        client.models.generate_content.side_effect = gen_content

        # Stub sleep para evitar tests lentos (cascade hace backoff exponencial).
        with patch("llm_invoke.time.sleep", lambda s: None):
            result = _run(agentic_agent._gemini_generate_async(
                client,
                model="gemini-3.5-flash",
                messages=[{"role": "user", "parts": [{"text": "hola"}]}],
                system_prompt="Eres un test bot.",
                tools_config=[],
                temperature=0.0,
            ))

        # La cascada llamó flash al menos una vez, falló transitorio,
        # luego intentó flash-lite y obtuvo éxito.
        self.assertIn("gemini-3.5-flash", call_log)
        self.assertIn("gemini-3.1-flash-lite", call_log)
        # Verificar que el fallback respondió.
        text = "".join(
            getattr(p, "text", "") or ""
            for c in result.candidates for p in c.content.parts
        )
        self.assertEqual(text, "Hola desde lite")

    def test_429_se_reintenta_y_pasa(self):
        """429 transitorio en intento 1, éxito en intento 2 (mismo modelo)."""
        from agentic import agent as agentic_agent

        client = MagicMock()
        calls = {"count": 0}

        def gen_content(model, contents, config):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("429 rate limit")
            return _FakeResponse("Recuperado")

        client.models.generate_content.side_effect = gen_content

        with patch("llm_invoke.time.sleep", lambda s: None):
            result = _run(agentic_agent._gemini_generate_async(
                client,
                model="gemini-3.5-flash",
                messages=[{"role": "user", "parts": [{"text": "x"}]}],
                system_prompt="t",
                tools_config=[],
                temperature=0.0,
            ))

        self.assertEqual(calls["count"], 2)
        text = "".join(
            getattr(p, "text", "") or ""
            for c in result.candidates for p in c.content.parts
        )
        self.assertEqual(text, "Recuperado")

    def test_error_no_transitorio_se_relanza_sin_reintento(self):
        """Bug de schema/prompt (400) NO debe gastar reintentos."""
        from agentic import agent as agentic_agent

        client = MagicMock()
        calls = {"count": 0}

        def gen_content(model, contents, config):
            calls["count"] += 1
            # 400 INVALID_ARGUMENT NO es transitorio.
            raise RuntimeError("400 INVALID_ARGUMENT: bad schema")

        client.models.generate_content.side_effect = gen_content

        with patch("llm_invoke.time.sleep", lambda s: None):
            with self.assertRaises(Exception) as ctx:
                _run(agentic_agent._gemini_generate_async(
                    client,
                    model="gemini-3.5-flash",
                    messages=[{"role": "user", "parts": [{"text": "x"}]}],
                    system_prompt="t",
                    tools_config=[],
                    temperature=0.0,
                ))

        # NO se reintentó — 1 sola call.
        self.assertEqual(calls["count"], 1, "no debe reintentar errores no-transitorios")
        # El error original se propaga (no se enmascara como cascade_exhausted).
        self.assertIn("INVALID_ARGUMENT", str(ctx.exception))

    def test_cascada_agotada_lanza_cascade_exhausted(self):
        """Si flash + flash-lite TODOS fallan transitorios → RuntimeError
        con 'gemini_cascade_exhausted' (dispatcher hace fallback legacy)."""
        from agentic import agent as agentic_agent

        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError(
            "503 service unavailable",
        )

        with patch("llm_invoke.time.sleep", lambda s: None):
            with self.assertRaises(RuntimeError) as ctx:
                _run(agentic_agent._gemini_generate_async(
                    client,
                    model="gemini-3.5-flash",
                    messages=[{"role": "user", "parts": [{"text": "x"}]}],
                    system_prompt="t",
                    tools_config=[],
                    temperature=0.0,
                ))

        self.assertIn("gemini_cascade_exhausted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

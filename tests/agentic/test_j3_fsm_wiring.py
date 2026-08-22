"""BLOQUE J-3 (auditoría 2026-07-12) — cableado FSM/tools.

(1) Enforcement en RUNTIME de allowed_tools: si el LLM invoca un tool FUERA de su
    subset per-state (hallucinación / drift), agent.py lo bloquea ANTES de ejecutar
    (defense-in-depth; antes allowed_tools solo filtraba las DECLARACIONES a Gemini).
(2) requires_requote wiring: el SELECT del cart en _resolve_and_persist_agentic_state
    ahora trae requires_requote → el resolver puede enrutar a SHIPPING_QUOTE cuando el
    cliente cambió items tras cotizar (la LÓGICA ya está cubierta en el test del
    resolver; esto cierra el wiring runtime que la hacía inerte).
(3) Paridad subset⊆registry: en test_prompt_per_state.py (ya no circular).
"""
import asyncio
import inspect
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
# genai.Client() se crea al inicio de run_agentic_turn y exige api_key no vacía
# (aunque _gemini_generate_async esté patcheado, el client se instancia). Key dummy:
# el client nunca se usa de verdad (la llamada LLM está mockeada).
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))

import agentic.agent as agent_mod  # noqa: E402
from agentic.agent import run_agentic_turn  # noqa: E402


def _fc_response(name: str, args: dict | None = None):
    """Respuesta Gemini fake con UNA function_call (la parsea el _extract real)."""
    fc = MagicMock()
    fc.name = name
    fc.args = args or {}
    part = MagicMock()
    part.function_call = fc
    part.text = None          # evita que _extract_text lo tome como texto
    part.thought_signature = None
    cand = MagicMock()
    cand.content = MagicMock()
    cand.content.parts = [part]
    cand.finish_reason = "STOP"
    resp = MagicMock()
    resp.candidates = [cand]
    resp.usage_metadata = None
    return resp


def _text_response(text: str):
    """Respuesta Gemini fake con solo texto (termina el loop de tools)."""
    part = MagicMock()
    part.function_call = None  # sin function_call → _extract_function_calls=[]
    part.text = text
    cand = MagicMock()
    cand.content = MagicMock()
    cand.content.parts = [part]
    cand.finish_reason = "STOP"
    resp = MagicMock()
    resp.candidates = [cand]
    resp.usage_metadata = None
    return resp


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class RuntimeToolEnforcementTest(unittest.TestCase):
    """Test FUNCIONAL (no AST): patchea _gemini_generate_async con respuestas reales
    que el _extract_function_calls REAL parsea, y verifica el comportamiento
    security-critical — que el tool bloqueado NO se ejecuta (mutation-catching: si se
    borra el `continue` del guard, el tool caería a execute y este test fallaría)."""

    def _drive(self, *, allowed_tools, tool_called, get_tool_return=None):
        # Turno 1: el LLM invoca `tool_called`; turno 2: texto final (fin del loop).
        # B-1 (routing): _gemini_generate_async devuelve (response, model_used).
        responses = [
            (_fc_response(tool_called), "gemini-test"),
            (_text_response("Listo."), "gemini-test"),
        ]
        with patch.object(agent_mod, "_gemini_generate_async",
                          new=AsyncMock(side_effect=responses)), \
             patch.object(agent_mod, "get_tool",
                          return_value=get_tool_return) as get_tool_mock:
            result = _run(run_agentic_turn(
                tenant_id="t-1", conversation_id="c-1", contact_id="ct-1",
                inbound_text="genérame el link de pago",
                contact_record={"id": "ct-1"}, catalog=[], history=[],
                supabase=MagicMock(), system_prompt="SP",
                allowed_tools=allowed_tools,
            ))
        return result, get_tool_mock

    def test_disallowed_tool_blocked_not_executed(self):
        # generate_payment_link NO está en allowed_tools → bloqueado ANTES de ejecutar.
        result, get_tool_mock = self._drive(
            allowed_tools={"list_catalog"}, tool_called="generate_payment_link",
        )
        entry = next(e for e in result.tool_call_log
                     if e["tool"] == "generate_payment_link")
        self.assertEqual(entry["result"].get("code"), "TOOL_NOT_ALLOWED")
        # SECURITY-CRITICAL: get_tool NUNCA se llamó para el bloqueado → no ejecutado.
        # (Si se borra el `continue` del guard, caería a get_tool y esto fallaría.)
        called = [c.args[0] for c in get_tool_mock.call_args_list if c.args]
        self.assertNotIn("generate_payment_link", called)

    def test_allowed_tool_passes_and_executes(self):
        # list_catalog SÍ está en allowed_tools → pasa el guard, se ejecuta.
        tool = MagicMock()
        tool.args_schema = MagicMock(return_value=MagicMock())
        _res = MagicMock()
        _res.success = True
        _res.data = {"ok": True}
        tool.execute = AsyncMock(return_value=_res)
        result, get_tool_mock = self._drive(
            allowed_tools={"list_catalog"}, tool_called="list_catalog",
            get_tool_return=tool,
        )
        called = [c.args[0] for c in get_tool_mock.call_args_list if c.args]
        self.assertIn("list_catalog", called)   # el guard lo dejó pasar
        tool.execute.assert_awaited()            # y se ejecutó

    def test_allowed_tools_none_no_enforcement(self):
        # allowed_tools=None (fallback monolito) → sin enforcement: get_tool SÍ se
        # consulta incluso para un tool cualquiera.
        result, get_tool_mock = self._drive(
            allowed_tools=None, tool_called="generate_payment_link",
        )
        called = [c.args[0] for c in get_tool_mock.call_args_list if c.args]
        self.assertIn("generate_payment_link", called)
        # No hay bloqueo TOOL_NOT_ALLOWED.
        codes = [e["result"].get("code") for e in result.tool_call_log]
        self.assertNotIn("TOOL_NOT_ALLOWED", codes)


class RequiresRequoteWiringTest(unittest.TestCase):
    """La LÓGICA del resolver (requires_requote → SHIPPING_QUOTE) ya está cubierta en
    test_state_machine_resolver. Aquí se cierra el WIRING runtime: que el SELECT del
    dispatcher realmente traiga la columna (si no, el resolver la ve None → gate
    inerte). Test load-bearing: extrae SOLO el string del .select() y verifica la
    columna ahí (no en un comentario, evitando el grep no-load-bearing del review)."""

    def _code_without_comments(self):
        import agentic.dispatcher as d
        src = inspect.getsource(d._resolve_and_persist_agentic_state)
        # Quitar líneas de comentario (así "requires_requote" en un comentario NO
        # cuenta — solo el código real, cerrando el grep no-load-bearing del review).
        return "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )

    def test_resolver_cart_select_includes_requires_requote(self):
        code = self._code_without_comments()
        # La columna aparece en el SELECT real (la lista de columnas termina en
        # 'converted_order_id, requires_requote' — substring único del SELECT del cart).
        self.assertIn("converted_order_id, requires_requote", code,
                      "requires_requote no está en el SELECT (código, no comentario) "
                      "del resolver → el gate de re-cotización quedaría inerte")


if __name__ == "__main__":
    unittest.main()

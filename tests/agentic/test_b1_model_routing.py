"""B-1 — tests del routing de modelo por estado FSM (lite→flash en transaccional).

Auditoría bot 2026-08-21 (§3): "mismo modelo lite para 'hola' y para el
checkout" — el checkout necesita el modelo fuerte; la exploración no.

Cobertura:
  • model_for_state: flag OFF → (None,None) en todos los estados (comportamiento
    idéntico a hoy); flag ON → pre-cart sigue default, checkout/carrito →
    (flash, lite-fallback — nunca el modelo caro como fallback).
  • _gemini_generate_async: propaga fallback_model a generate_with_cascade y
    devuelve (response, model_used).
  • run_agentic_turn: usa el modelo del turno (no el global) cuando se pasa.
  • _persist_turn_audit: incluye model_used y degrada seguro si falta la columna.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.model_routing import model_for_state  # noqa: E402
from agentic.state_machine import AgenticState  # noqa: E402


class ModelForStateTests(unittest.TestCase):

    def test_flag_off_returns_defaults_everywhere(self):
        with patch.dict(os.environ, {"AGENTIC_STATE_ROUTING_ENABLED": "false"}):
            for state in AgenticState:
                self.assertEqual(model_for_state(state), (None, None), state.value)

    def test_flag_on_pre_cart_keeps_default(self):
        with patch.dict(os.environ, {"AGENTIC_STATE_ROUTING_ENABLED": "true"}):
            for state in (AgenticState.GREETING, AgenticState.EXPLORING):
                self.assertEqual(model_for_state(state), (None, None), state.value)

    def test_flag_on_checkout_uses_transactional_with_lite_fallback(self):
        with patch.dict(os.environ, {"AGENTIC_STATE_ROUTING_ENABLED": "true"}):
            for state in (
                AgenticState.CART_BUILDING, AgenticState.PII_COLLECTION,
                AgenticState.SHIPPING_QUOTE, AgenticState.CARRIER_SELECTION,
                AgenticState.PAYMENT,
            ):
                primary, fallback = model_for_state(state)
                self.assertEqual(primary, "gemini-3.5-flash", state.value)
                # El fallback del tier transaccional es el LITE — NUNCA el
                # modelo caro como respaldo (inversión de 2026-07-07).
                self.assertEqual(fallback, "gemini-3.1-flash-lite", state.value)

    def test_flag_on_custom_transactional_model(self):
        with patch.dict(os.environ, {
            "AGENTIC_STATE_ROUTING_ENABLED": "true",
            "AGENTIC_MODEL_TRANSACTIONAL": "gemini-3.5-flash-lite",
        }):
            primary, _fb = model_for_state(AgenticState.PAYMENT)
            self.assertEqual(primary, "gemini-3.5-flash-lite")

    def test_none_state_returns_defaults(self):
        with patch.dict(os.environ, {"AGENTIC_STATE_ROUTING_ENABLED": "true"}):
            self.assertEqual(model_for_state(None), (None, None))


class GeminiGenerateFallbackTests(unittest.IsolatedAsyncioTestCase):

    async def test_fallback_model_propagated_and_tuple_returned(self):
        from agentic.agent import _gemini_generate_async

        captured = {}

        def _fake_cascade(invoke_fn, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                response=SimpleNamespace(text="ok"),
                model_used=kwargs.get("primary_model"),
                attempts=1,
                degraded=False,
            )

        with patch("llm_invoke.generate_with_cascade", side_effect=_fake_cascade):
            resp, model_used = await _gemini_generate_async(
                MagicMock(),
                model="gemini-3.5-flash",
                messages=[{"role": "user", "parts": [{"text": "hola"}]}],
                system_prompt="sys",
                tools_config=[],
                temperature=0.0,
                fallback_model="gemini-3.1-flash-lite",
            )
        self.assertEqual(captured["primary_model"], "gemini-3.5-flash")
        self.assertEqual(captured["fallback_model"], "gemini-3.1-flash-lite")
        self.assertEqual(model_used, "gemini-3.5-flash")


class RunTurnModelTests(unittest.IsolatedAsyncioTestCase):

    async def test_turn_uses_passed_model_not_global(self):
        """El turno con routing usa el modelo del estado, no AGENTIC_MODEL."""
        from agentic import agent as agent_mod

        seen = {}

        async def _fake_gen(client, *, model, messages, system_prompt,
                            tools_config, temperature, fallback_model=None):
            seen["model"] = model
            seen["fallback_model"] = fallback_model
            return SimpleNamespace(
                candidates=[SimpleNamespace(
                    content=SimpleNamespace(parts=[SimpleNamespace(text="respuesta")]),
                    finish_reason="STOP",
                )],
                text="respuesta",
            ), model

        with patch.object(agent_mod, "_gemini_generate_async", side_effect=_fake_gen), \
             patch.object(agent_mod, "_get_genai_client", return_value=MagicMock()), \
             patch("agentic.tools.registry.gemini_function_schemas", return_value=[]):
            result = await agent_mod.run_agentic_turn(
                tenant_id="t1", conversation_id="c1", contact_id=None,
                inbound_text="hola", contact_record={}, catalog=[],
                history=[], supabase=MagicMock(), system_prompt="sys",
                model="gemini-3.5-flash", fallback_model="gemini-3.1-flash-lite",
            )
        self.assertEqual(seen["model"], "gemini-3.5-flash")
        self.assertEqual(seen["fallback_model"], "gemini-3.1-flash-lite")
        self.assertEqual(result.model_used, "gemini-3.5-flash")

    async def test_turn_without_model_uses_global_default(self):
        from agentic import agent as agent_mod

        seen = {}

        async def _fake_gen(client, *, model, messages, system_prompt,
                            tools_config, temperature, fallback_model=None):
            seen["model"] = model
            return SimpleNamespace(
                candidates=[SimpleNamespace(
                    content=SimpleNamespace(parts=[SimpleNamespace(text="ok")]),
                    finish_reason="STOP",
                )],
                text="ok",
            ), model

        with patch.object(agent_mod, "_gemini_generate_async", side_effect=_fake_gen), \
             patch.object(agent_mod, "_get_genai_client", return_value=MagicMock()), \
             patch("agentic.tools.registry.gemini_function_schemas", return_value=[]):
            await agent_mod.run_agentic_turn(
                tenant_id="t1", conversation_id="c1", contact_id=None,
                inbound_text="hola", contact_record={}, catalog=[],
                history=[], supabase=MagicMock(), system_prompt="sys",
            )
        self.assertEqual(seen["model"], agent_mod.AGENTIC_MODEL)


class PersistAuditModelUsedTests(unittest.TestCase):

    def test_row_includes_model_used(self):
        from agentic.dispatcher import _persist_turn_audit
        sb = MagicMock()
        captured = {}
        sb.table.return_value.insert.side_effect = lambda row: captured.setdefault("row", row) or MagicMock(execute=lambda: None)
        result = SimpleNamespace(
            outbound_text="x", tool_calls_executed=0, tool_call_log=[],
            truncated=False, truncated_reason=None, error=None,
            finish_reason="STOP", total_tokens=0, prompt_tokens=0,
            cached_tokens=0, thoughts_tokens=0, model_used="gemini-3.5-flash",
        )
        _persist_turn_audit(
            sb, mode="cutover", message_id="m1", tenant_id="t1",
            conversation_id="c1", inbound_text="hola", result=result,
            elapsed_s=1.0, final_text="x", invariant_outcome="ok",
            invariant_name="ok", system_prompt_chars=10, history_turns=1,
        )
        self.assertEqual(captured["row"]["model_used"], "gemini-3.5-flash")

    def test_degrade_pops_model_used_when_column_missing(self):
        from agentic.dispatcher import _persist_turn_audit
        sb = MagicMock()
        attempts = {"n": 0, "rows": []}

        class _Insert:
            def __init__(self, row):
                self.row = row

            def execute(self):
                attempts["n"] += 1
                attempts["rows"].append(dict(self.row))
                if "model_used" in self.row:
                    raise Exception("column model_used does not exist")
                return SimpleNamespace(data=[])

        sb.table.return_value.insert.side_effect = lambda row: _Insert(row)
        result = SimpleNamespace(
            outbound_text="x", tool_calls_executed=0, tool_call_log=[],
            truncated=False, truncated_reason=None, error=None,
            finish_reason="STOP", total_tokens=0, prompt_tokens=0,
            cached_tokens=0, thoughts_tokens=0, model_used="gemini-3.5-flash",
        )
        _persist_turn_audit(
            sb, mode="cutover", message_id="m1", tenant_id="t1",
            conversation_id="c1", inbound_text="hola", result=result,
            elapsed_s=1.0, final_text="x", invariant_outcome="ok",
            invariant_name="ok", system_prompt_chars=10, history_turns=1,
        )
        self.assertEqual(attempts["n"], 2)
        self.assertNotIn("model_used", attempts["rows"][-1])


if __name__ == "__main__":
    unittest.main()

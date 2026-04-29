"""Tests de ``llm/parsers.py``.

Cubre:
- FinishReason.from_str con valores válidos, inválidos, None.
- map_finish_reason_to_action devuelve la acción correcta para cada caso.
- parse_response con: respuesta vacía, solo texto, solo function_call,
  ambos, MALFORMED_FUNCTION_CALL, SAFETY block.
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from llm.parsers import (  # noqa: E402
    FinishAction,
    FinishReason,
    FunctionCall,
    LlmTurn,
    map_finish_reason_to_action,
    parse_response,
)


class FinishReasonTests(unittest.TestCase):
    def test_from_str_valid(self):
        self.assertEqual(FinishReason.from_str("STOP"), FinishReason.STOP)
        self.assertEqual(FinishReason.from_str("safety"), FinishReason.SAFETY)

    def test_from_str_invalid(self):
        self.assertEqual(FinishReason.from_str("BOGUS"), FinishReason.UNKNOWN)
        self.assertEqual(FinishReason.from_str(None), FinishReason.UNKNOWN)
        self.assertEqual(FinishReason.from_str(""), FinishReason.UNKNOWN)


class MapFinishToActionTests(unittest.TestCase):
    def test_stop_is_ok(self):
        self.assertEqual(map_finish_reason_to_action(FinishReason.STOP), FinishAction.OK)

    def test_max_tokens_retries(self):
        self.assertEqual(
            map_finish_reason_to_action(FinishReason.MAX_TOKENS), FinishAction.RETRY,
        )

    def test_safety_handsoff(self):
        for reason in [
            FinishReason.SAFETY,
            FinishReason.BLOCKLIST,
            FinishReason.PROHIBITED_CONTENT,
            FinishReason.SPII,
            FinishReason.IMAGE_SAFETY,
        ]:
            self.assertEqual(
                map_finish_reason_to_action(reason), FinishAction.HUMAN_HANDOFF,
                f"{reason} debería disparar handoff",
            )

    def test_malformed_function_call_retries(self):
        self.assertEqual(
            map_finish_reason_to_action(FinishReason.MALFORMED_FUNCTION_CALL),
            FinishAction.RETRY,
        )


class ParseResponseTests(unittest.TestCase):
    def _make_response(self, *, finish_reason="STOP", parts=None):
        candidate = SimpleNamespace(
            finish_reason=SimpleNamespace(name=finish_reason),
            content=SimpleNamespace(parts=parts or []),
        )
        return SimpleNamespace(candidates=[candidate])

    def _text_part(self, text: str):
        return SimpleNamespace(text=text, function_call=None)

    def _fc_part(self, name: str, args: dict, call_id: str = "call-1"):
        fc = SimpleNamespace(name=name, args=args, id=call_id)
        return SimpleNamespace(text=None, function_call=fc)

    def test_empty_response(self):
        resp = SimpleNamespace(candidates=[])
        turn = parse_response(resp)
        self.assertIsNone(turn.text)
        self.assertEqual(turn.function_calls, [])
        self.assertEqual(turn.finish_reason, FinishReason.UNKNOWN)
        self.assertEqual(turn.finish_action, FinishAction.RETRY)

    def test_text_only(self):
        resp = self._make_response(parts=[self._text_part("Hola, ¿en qué te ayudo?")])
        turn = parse_response(resp)
        self.assertEqual(turn.text, "Hola, ¿en qué te ayudo?")
        self.assertEqual(turn.function_calls, [])
        self.assertEqual(turn.finish_reason, FinishReason.STOP)
        self.assertEqual(turn.finish_action, FinishAction.OK)

    def test_function_call_only(self):
        resp = self._make_response(
            parts=[self._fc_part(
                "add_item_to_cart",
                {"product_id": "p1", "variation_id": "v1", "quantity": 1},
            )],
        )
        turn = parse_response(resp)
        self.assertIsNone(turn.text)
        self.assertEqual(len(turn.function_calls), 1)
        fc = turn.function_calls[0]
        self.assertEqual(fc.name, "add_item_to_cart")
        self.assertEqual(fc.args["variation_id"], "v1")

    def test_multiple_function_calls(self):
        # Caso real: cliente "1 de 10ml y 1 de 30ml" → 2 add_item_to_cart
        resp = self._make_response(
            parts=[
                self._fc_part(
                    "add_item_to_cart",
                    {"product_id": "p1", "variation_id": "v1", "quantity": 1},
                    call_id="call-a",
                ),
                self._fc_part(
                    "add_item_to_cart",
                    {"product_id": "p1", "variation_id": "v2", "quantity": 1},
                    call_id="call-b",
                ),
            ],
        )
        turn = parse_response(resp)
        self.assertEqual(len(turn.function_calls), 2)
        self.assertEqual(turn.function_calls[0].args["variation_id"], "v1")
        self.assertEqual(turn.function_calls[1].args["variation_id"], "v2")

    def test_safety_block(self):
        resp = self._make_response(finish_reason="SAFETY", parts=[])
        turn = parse_response(resp)
        self.assertEqual(turn.finish_reason, FinishReason.SAFETY)
        self.assertEqual(turn.finish_action, FinishAction.HUMAN_HANDOFF)

    def test_malformed_function_call(self):
        resp = self._make_response(finish_reason="MALFORMED_FUNCTION_CALL", parts=[])
        turn = parse_response(resp)
        self.assertEqual(turn.finish_reason, FinishReason.MALFORMED_FUNCTION_CALL)
        self.assertEqual(turn.finish_action, FinishAction.RETRY)

    def test_text_and_function_call_coexist(self):
        resp = self._make_response(parts=[
            self._text_part("Voy a buscar el producto."),
            self._fc_part("search_catalog", {"query": "lavanda"}),
        ])
        turn = parse_response(resp)
        self.assertEqual(turn.text, "Voy a buscar el producto.")
        self.assertEqual(len(turn.function_calls), 1)


if __name__ == "__main__":
    unittest.main()

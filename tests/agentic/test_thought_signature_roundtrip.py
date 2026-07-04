"""Regresión: round-trip de thought_signature en el loop agéntico (Gemini 3.x).

Bug 2026-07-03 (gemini-3.5-flash): Gemini 3.x devuelve un `thought_signature`
(bytes) en cada functionCall que DEBE reenviarse en el turno siguiente del
tool-loop, o la API responde `400 INVALID_ARGUMENT` ('Function call is missing
a thought_signature') y el bot degrada a modo 'no te entendí' → escala. Gemini
2.5 no lo exigía. El loop reconstruía el turno del modelo solo con name+args y
descartaba la firma → TODO add_to_cart/quote_shipping fallaba en la 2ª llamada.

Este test fija que `_extract_function_calls` captura la firma y `_part_from_dict`
la reinyecta al reconstruir el Part del historial.
"""
import os
import sys
import unittest
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _mock_response(sig):
    """Response Gemini mínimo: 1 functionCall (add_to_cart) con thought_signature."""
    fc = SimpleNamespace(name="add_to_cart", args={"variation_id": "v1", "quantity": 2})
    part = SimpleNamespace(function_call=fc, thought_signature=sig, text=None)
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


class ThoughtSignatureRoundTripTests(unittest.TestCase):

    def test_extract_captura_la_firma(self):
        from agentic.agent import _extract_function_calls
        sig = b"\x0a\x1bthought-sig-bytes"
        calls = _extract_function_calls(_mock_response(sig))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "add_to_cart")
        self.assertEqual(calls[0]["thought_signature"], sig)

    def test_extract_sin_firma_queda_none(self):
        # Gemini 2.5 (sin firma) NO debe romper — queda None.
        from agentic.agent import _extract_function_calls
        calls = _extract_function_calls(_mock_response(None))
        self.assertIsNone(calls[0]["thought_signature"])

    def test_part_from_dict_reinyecta_la_firma(self):
        from agentic.agent import _part_from_dict
        sig = b"\x0a\x1bthought-sig-bytes"
        part = _part_from_dict({
            "function_call": {"name": "add_to_cart", "args": {"variation_id": "v1"}},
            "thought_signature": sig,
        })
        self.assertEqual(part.thought_signature, sig)
        self.assertEqual(part.function_call.name, "add_to_cart")

    def test_roundtrip_completo_preserva_la_firma(self):
        # extract → dict del historial (como en agent.py) → Part reconstruido.
        from agentic.agent import _extract_function_calls, _part_from_dict
        sig = b"sig-xyz-0123"
        calls = _extract_function_calls(_mock_response(sig))
        hist_part = {
            "function_call": {"name": calls[0]["name"], "args": calls[0]["args"]},
            "thought_signature": calls[0].get("thought_signature"),
        }
        part = _part_from_dict(hist_part)
        self.assertEqual(part.thought_signature, sig)


if __name__ == "__main__":
    unittest.main()

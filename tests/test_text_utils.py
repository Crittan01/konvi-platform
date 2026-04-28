"""Tests de utilidades de texto compartidas (services/ai-orchestrator/text_utils.py).

Cobertura del módulo extraído tras el refactor de orchestrator.py.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from text_utils import (
    normalize_text,
    tokenize_text,
    normalize_phone,
    safe_float,
    format_pesos,
    format_cents_cop,
)


class NormalizeTextTests(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize_text("HOLA"), "hola")

    def test_strips_accents(self):
        self.assertEqual(normalize_text("camión"), "camion")
        self.assertEqual(normalize_text("Bogotá"), "bogota")
        self.assertEqual(normalize_text("ñoño"), "nono")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize_text("  hola   mundo  "), "hola mundo")
        self.assertEqual(normalize_text("línea\n\notra"), "linea otra")

    def test_handles_none_and_empty(self):
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text(None), "")  # type: ignore[arg-type]

    def test_preserves_punctuation(self):
        # ¡ (U+00A1) se elimina al pasar a ASCII; ! se mantiene.
        self.assertEqual(normalize_text("¡Hola, BUENAS!"), "hola, buenas!")


class TokenizeTextTests(unittest.TestCase):
    def test_extracts_alphanum_tokens(self):
        self.assertEqual(tokenize_text("Hola, mundo 123!"), ["hola", "mundo", "123"])

    def test_strips_accents_in_tokens(self):
        self.assertEqual(tokenize_text("Camión café"), ["camion", "cafe"])

    def test_empty_input(self):
        self.assertEqual(tokenize_text(""), [])
        self.assertEqual(tokenize_text("!!!"), [])


class NormalizePhoneTests(unittest.TestCase):
    def test_strips_plus_and_spaces(self):
        self.assertEqual(normalize_phone("+57 312 583 5649"), "573125835649")

    def test_handles_no_plus(self):
        self.assertEqual(normalize_phone("3125835649"), "3125835649")

    def test_handles_none(self):
        self.assertEqual(normalize_phone(None), "")  # type: ignore[arg-type]

    def test_handles_only_spaces(self):
        self.assertEqual(normalize_phone("  "), "")


class SafeFloatTests(unittest.TestCase):
    def test_parses_int(self):
        self.assertEqual(safe_float(100), 100.0)

    def test_parses_float(self):
        self.assertEqual(safe_float(99.5), 99.5)

    def test_parses_numeric_string(self):
        self.assertEqual(safe_float("42.5"), 42.5)

    def test_returns_none_on_invalid(self):
        self.assertIsNone(safe_float("abc"))
        self.assertIsNone(safe_float(None))
        self.assertIsNone(safe_float([1, 2]))


class FormatPesosTests(unittest.TestCase):
    def test_formats_with_thousands_separator(self):
        self.assertEqual(format_pesos(13500), "$13.500")
        self.assertEqual(format_pesos(1500000), "$1.500.000")

    def test_rounds_decimals(self):
        self.assertEqual(format_pesos(100.7), "$101")
        self.assertEqual(format_pesos(100.4), "$100")

    def test_returns_nd_on_invalid(self):
        self.assertEqual(format_pesos(None), "N/D")
        self.assertEqual(format_pesos("xx"), "N/D")


class FormatCentsCopTests(unittest.TestCase):
    def test_converts_cents_to_pesos(self):
        self.assertEqual(format_cents_cop(1_350_000), "$13.500 COP")

    def test_zero(self):
        self.assertEqual(format_cents_cop(0), "$0 COP")

    def test_handles_none_like_zero(self):
        self.assertEqual(format_cents_cop(None), "$0 COP")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()

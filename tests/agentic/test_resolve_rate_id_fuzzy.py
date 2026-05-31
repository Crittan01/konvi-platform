"""Tests del helper `_resolve_rate_id_fuzzy` aislado de SelectCarrierTool.

Validación profesional del comportamiento determinístico ante:
  • Match exact (rate_id literal).
  • Case-insensitive en rate_id.
  • Fuzzy normalizado con separadores variables.
  • Ambigüedad determinística (carriers con nombres relacionados).
  • Confidence boundary (rechazo de matches de baja confianza).
  • Order-stability (tie-breaking por orden de cotización).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.tools.shipping import (
    FuzzyMatchResult,
    _resolve_rate_id_fuzzy,
    _normalize_for_match,
    _FUZZY_MIN_CONFIDENCE,
)


# ─── Helpers de fixture ────────────────────────────────────────────────────


def _opt(rate_id, carrier, **kw):
    return {"rate_id": rate_id, "carrier": carrier, **kw}


# ─── Match types: exact / case-insensitive / fuzzy ────────────────────────


class ExactMatchTests(unittest.TestCase):

    def test_exact_match_case_sensitive_confidence_1(self):
        options = [_opt("29", "ENVIA"), _opt("33", "SERVIENTREGA")]
        r = _resolve_rate_id_fuzzy("29", options)
        self.assertEqual(r.match_type, "exact")
        self.assertEqual(r.confidence, 1.0)
        self.assertEqual(r.rate_data["rate_id"], "29")

    def test_case_insensitive_match_confidence_high(self):
        options = [_opt("ABC123", "ENVIA")]
        r = _resolve_rate_id_fuzzy("abc123", options)
        self.assertEqual(r.match_type, "case_insensitive")
        self.assertEqual(r.confidence, 0.95)
        self.assertEqual(r.rate_data["rate_id"], "ABC123")


class FuzzyNormalizedMatchTests(unittest.TestCase):

    def test_underscore_vs_space_caso_founder(self):
        """Caso real conv 146fe9ec founder."""
        options = [
            _opt("1009", "COORDINADORA MERCANTIL"),
            _opt("29", "ENVIA"),
        ]
        r = _resolve_rate_id_fuzzy("rate_coordinadora_mercantil", options)
        self.assertEqual(r.match_type, "fuzzy_normalized")
        self.assertEqual(r.rate_data["rate_id"], "1009")
        # confidence = len('coordinadoramercantil')=21 / len('ratecoordinadoramercantil')=25 = 0.84
        self.assertGreater(r.confidence, 0.8)
        self.assertLessEqual(r.confidence, 1.0)

    def test_uuid_inventado_con_substring_carrier(self):
        """LLM inventó UUID pero contiene 'envia' embebido."""
        options = [_opt("29", "ENVIA"), _opt("1009", "COORDINADORA MERCANTIL")]
        r = _resolve_rate_id_fuzzy("envia-medellin-uuid-1234", options)
        self.assertEqual(r.rate_data["rate_id"], "29")

    def test_dashes_normalizados(self):
        options = [_opt("1010", "TCC SA")]
        r = _resolve_rate_id_fuzzy("rate-tcc-sa", options)
        self.assertEqual(r.rate_data["rate_id"], "1010")


# ─── Ambigüedad determinística (la deuda que esta refactor cierra) ─────────


class AmbiguityTests(unittest.TestCase):
    """Carriers con nombres relacionados — el scoring length-ratio debe
    elegir el match más específico, NO el primero del array."""

    def test_envia_simple_gana_sobre_envia_express_para_query_corto(self):
        """LLM dice 'envia' → debe matchear ENVIA exact, no ENVIA EXPRESS."""
        options = [
            _opt("29", "ENVIA"),
            _opt("99", "ENVIA EXPRESS"),
        ]
        r = _resolve_rate_id_fuzzy("envia", options)
        self.assertEqual(r.rate_data["rate_id"], "29")  # ENVIA, no EXPRESS
        # Verifica scoring: 'envia'(5) match contra 'envia'(5)=1.0 vs 'enviaexpress'(12)=5/12=0.42.
        self.assertEqual(r.confidence, 1.0)

    def test_envia_express_gana_sobre_envia_para_query_largo(self):
        """LLM dice 'envia_express' → debe matchear ENVIA EXPRESS, no ENVIA."""
        options = [
            _opt("29", "ENVIA"),
            _opt("99", "ENVIA EXPRESS"),
        ]
        r = _resolve_rate_id_fuzzy("envia_express", options)
        self.assertEqual(r.rate_data["rate_id"], "99")  # ENVIA EXPRESS
        self.assertEqual(r.confidence, 1.0)

    def test_envia_express_gana_aunque_envia_esta_primero(self):
        """Si ENVIA está antes que ENVIA EXPRESS en el array, scoring
        debe ganarle a orden de cotización."""
        options = [
            _opt("29", "ENVIA"),         # primero
            _opt("99", "ENVIA EXPRESS"), # segundo
        ]
        # Query 'enviaexpress' completo — debe ganar ENVIA EXPRESS (12 chars)
        # sobre ENVIA (5 chars) por scoring 1.0 vs 0.42.
        r = _resolve_rate_id_fuzzy("enviaexpress", options)
        self.assertEqual(r.rate_data["rate_id"], "99")

    def test_coordinadora_simple_vs_coordinadora_mercantil(self):
        """Caso producción más probable."""
        options = [
            _opt("1009", "COORDINADORA MERCANTIL"),
            _opt("888", "COORDINADORA"),
        ]
        # Query 'coordinadora' simple → debe matchear COORDINADORA exact.
        r = _resolve_rate_id_fuzzy("coordinadora", options)
        self.assertEqual(r.rate_data["rate_id"], "888")

        # Query con detalle → COORDINADORA MERCANTIL.
        r = _resolve_rate_id_fuzzy("coordinadora_mercantil", options)
        self.assertEqual(r.rate_data["rate_id"], "1009")


# ─── Rechazo de matches débiles + edge cases ──────────────────────────────


class RejectionTests(unittest.TestCase):

    def test_no_match_si_carrier_diferente(self):
        options = [_opt("1009", "COORDINADORA MERCANTIL")]
        r = _resolve_rate_id_fuzzy("fedex-ground", options)
        self.assertEqual(r.match_type, "none")
        self.assertIsNone(r.rate_data)

    def test_confidence_below_threshold_rejected(self):
        """Carrier muy corto matcheando dentro de string LLM muy largo.
        confidence = 2/30 = 0.06 < 0.3 → rechazo."""
        options = [_opt("1", "XY")]  # carrier_norm 'xy' (2 chars)
        long_req = "this-is-a-very-long-llm-invented-id"  # ~30 chars
        # 'xy' está en 'thisisaverylongllminventedid'? No → no candidato.
        r = _resolve_rate_id_fuzzy(long_req, options)
        self.assertEqual(r.match_type, "none")

    def test_empty_options_returns_none(self):
        r = _resolve_rate_id_fuzzy("anything", [])
        self.assertEqual(r.match_type, "none")
        self.assertEqual(r.confidence, 0.0)

    def test_empty_requested_returns_none(self):
        options = [_opt("29", "ENVIA")]
        r = _resolve_rate_id_fuzzy("", options)
        self.assertEqual(r.match_type, "none")

    def test_carrier_sin_nombre_se_omite(self):
        options = [_opt("29", ""), _opt("33", "SERVIENTREGA")]
        r = _resolve_rate_id_fuzzy("servientrega", options)
        self.assertEqual(r.rate_data["rate_id"], "33")


# ─── _normalize_for_match ──────────────────────────────────────────────────


class NormalizeTests(unittest.TestCase):

    def test_lowercase(self):
        self.assertEqual(_normalize_for_match("ENVIA"), "envia")

    def test_collapses_spaces(self):
        self.assertEqual(_normalize_for_match("TCC SA"), "tccsa")

    def test_collapses_underscores(self):
        self.assertEqual(_normalize_for_match("rate_coord_merc"), "ratecoordmerc")

    def test_collapses_dashes(self):
        self.assertEqual(_normalize_for_match("rate-tcc-sa"), "ratetccsa")

    def test_collapses_mixed_separators(self):
        self.assertEqual(_normalize_for_match("A B-C_D"), "abcd")

    def test_idempotent(self):
        s = "envia"
        self.assertEqual(_normalize_for_match(_normalize_for_match(s)), _normalize_for_match(s))


if __name__ == "__main__":
    unittest.main()

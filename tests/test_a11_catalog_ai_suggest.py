"""A11 — endpoint catalog_ai suggest-content: fallback robusto + anti-claims.

Verifica la lógica del endpoint (sin Gemini real): degraded→fallback, claims
médicos quitados, passthrough limpio. run_suggestion se mockea.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from routers.catalog_ai import (  # noqa: E402
    suggest_product_content, SuggestContentRequest, _strip_blocked_claims,
    RL_CATALOG_AI_SUGGEST, router as catalog_ai_router,
)
from lib.llm_suggest import SuggestionResult  # noqa: E402


def _mock_sb(name="KAIU"):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data={"name": name})
    return sb


def _call(payload, result):
    with patch("lib.llm_suggest.run_suggestion", return_value=result):
        # suggest_product_content ahora es `def` (Wave 3 threadpool) → llamada directa.
        return suggest_product_content(
            payload=payload, tenant_id="t-1", supabase=_mock_sb(), _role="owner",
        )


class CatalogAISuggestTests(unittest.TestCase):
    def test_degraded_cae_a_fallback(self):
        payload = SuggestContentRequest(title="Aceite X", current_description="texto previo del merchant")
        r = _call(payload, SuggestionResult(text="", data=None, model_used=None, degraded=True))
        self.assertEqual(r.description, "texto previo del merchant")
        self.assertEqual(r.safety_note, "")
        self.assertIn("revísalo", r.disclaimer.lower())

    def test_passthrough_limpio_con_safety(self):
        payload = SuggestContentRequest(title="Aceite Esencial de Lavanda")
        data = {"description": "Aceite de lavanda relajante para aromaterapia y masajes.",
                "safety_note": "Diluir antes de usar, no aplicar directo en la piel.",
                "is_sensitive_category": True}
        r = _call(payload, SuggestionResult(text="{}", data=data, model_used="gemini-3.5-flash", degraded=False))
        self.assertIn("relajante", r.description)
        self.assertIn("Diluir", r.safety_note)
        self.assertTrue(r.is_sensitive_category)

    def test_claim_medico_se_quita(self):
        payload = SuggestContentRequest(title="Aceite X", current_description="prev")
        data = {"description": "Aceite nutritivo. Cura el acné y previene enfermedades. Ideal para masajes.",
                "safety_note": "", "is_sensitive_category": False}
        r = _call(payload, SuggestionResult(text="{}", data=data, model_used="m", degraded=False))
        self.assertNotIn("cura", r.description.lower())
        self.assertNotIn("previene", r.description.lower())
        self.assertIn("nutritivo", r.description)

    def test_blocklist_helper(self):
        # Unidad directa del helper anti-claims.
        self.assertEqual(
            _strip_blocked_claims("Hidratante. Trata la enfermedad. Suave."),
            "Hidratante. Suave.",
        )
        self.assertEqual(_strip_blocked_claims("Aceite suave y nutritivo."),
                         "Aceite suave y nutritivo.")


class CatalogAIRateLimitWiringTests(unittest.TestCase):
    """G4 — /suggest-content lleva bucket RL propio (molde RL_AI_SUGGEST de
    ai_agents): endpoint LLM costoso con tope 20/h por tenant+user+IP.
    Wiring estructural — no golpea el limiter real."""

    def test_rl_dependency_registrada_en_ruta(self):
        route = next(
            r for r in catalog_ai_router.routes
            if getattr(r, "path", "") == "/catalog/suggest-content"
        )
        deps = [getattr(d, "dependency", None) for d in route.dependencies]
        self.assertIn(RL_CATALOG_AI_SUGGEST, deps)

    def test_bucket_y_tope_del_rule(self):
        # La dependency cierra sobre el RateLimitRule (ver build_rate_limit_dependency).
        closure = {
            var: cell.cell_contents
            for var, cell in zip(
                RL_CATALOG_AI_SUGGEST.__code__.co_freevars,
                RL_CATALOG_AI_SUGGEST.__closure__,
            )
        }
        rule = closure["rule"]
        self.assertEqual(rule.bucket, "catalog_ai.suggest")
        self.assertEqual(rule.limit, 20)          # mismo tope que ai.suggest
        self.assertEqual(rule.window_seconds, 3600)
        self.assertTrue(closure["include_user_id"])


if __name__ == "__main__":
    unittest.main()

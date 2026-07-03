"""A11 — endpoint catalog_ai suggest-content: fallback robusto + anti-claims.

Verifica la lógica del endpoint (sin Gemini real): degraded→fallback, claims
médicos quitados, passthrough limpio. run_suggestion se mockea.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers.catalog_ai import (  # noqa: E402
    suggest_product_content, SuggestContentRequest, _strip_blocked_claims,
)
from lib.llm_suggest import SuggestionResult  # noqa: E402


def _mock_sb(name="KAIU"):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data={"name": name})
    return sb


def _call(payload, result):
    with patch("lib.llm_suggest.run_suggestion", return_value=result):
        return asyncio.new_event_loop().run_until_complete(
            suggest_product_content(
                payload=payload, tenant_id="t-1", supabase=_mock_sb(), _role="owner",
            )
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


if __name__ == "__main__":
    unittest.main()

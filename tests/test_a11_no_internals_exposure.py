"""Regresión A11 — invariant NoInternalsExposure: el bot nunca expone su
mecánica interna (KB/sistema/catálogo) al cliente.

Incidente (founder UAT conv 56a0d757): "...la base de conocimiento no me da
detalles específicos de sus beneficios...". Defensa en profundidad determinística
(ADR-0024): si la frase aparece, REWRITE quitándola y conservando lo útil.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.invariants.no_internals_exposure import (  # noqa: E402
    NoInternalsExposureInvariant,
)
from agentic.invariants.base import InvariantOutcome  # noqa: E402


def _run(text):
    inv = NoInternalsExposureInvariant()
    return asyncio.new_event_loop().run_until_complete(
        inv.validate(
            candidate_text=text, tenant_id="t", conversation_id="c",
            contact_id=None, supabase=None, tool_call_log=[],
        )
    )


class NoInternalsExposureTests(unittest.TestCase):
    def test_incidente_exacto_se_reescribe(self):
        r = _run(
            "Para el Árbol de Té y la Lavanda, la base de conocimiento no me "
            "da detalles específicos de sus beneficios."
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("base de conocimiento", r.replacement_text.lower())

    def test_conserva_beneficios_quita_exposicion(self):
        r = _run(
            "El Árbol de Té tiene propiedades antimicrobianas y antisépticas. "
            "Sobre la Lavanda, mi sistema no tiene esa información registrada."
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        # Conserva el beneficio real:
        self.assertIn("antimicrobianas", r.replacement_text)
        # Quita la exposición:
        self.assertNotIn("mi sistema no tiene", r.replacement_text.lower())

    def test_respuesta_limpia_pasa_ok(self):
        r = _run(
            "El Aceite de Lavanda tiene propiedades relajantes y cicatrizantes. "
            "¿Cuál te interesa más?"
        )
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_base_de_datos_tambien_se_reescribe(self):
        r = _run("No tengo eso en mi base de datos.")
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_fixture_bug_anti_noop(self):
        # Frase fija que SIEMPRE debe reescribirse (anti no-op durable).
        r = _run("Eso no está en mi catálogo, no cuenta con esa info.")
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)


if __name__ == "__main__":
    unittest.main()

"""Regresión A11 audit (Clase C — fail-closed) — gate de opt-out.

El gate de opt-out tenía un `except Exception` que tragaba el error y avanzaba al
LLM (fail-open): si el procesamiento de un STOP fallaba, el bot respondía a quien
pidió parar → violación Habeas Data Ley 1581 Art.9 + Meta Business Policy.

Fix: ante error del handler, `_optout_failclosed_should_skip(content)` decide
fail-closed (silencio) SOLO si el contenido era keyword de opt-out — sin afectar
el tráfico normal (NO-STOP sigue al LLM). Test con `is_optout_keyword` REAL.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.dispatcher import _optout_failclosed_should_skip as should_skip  # noqa: E402


class OptOutFailClosedTests(unittest.TestCase):
    def test_stop_keywords_fail_closed(self):
        # Si era STOP y el handler falló → NO responder (fail-closed).
        for kw in ("STOP", "stop", "BAJA", "baja ", "CANCELAR"):
            self.assertTrue(should_skip(kw), f"{kw!r} debe fail-closed (era opt-out)")

    def test_normal_messages_proceed(self):
        # NO-STOP: el error del handler NO bloquea el tráfico normal (fail-open
        # aquí es correcto — no era una solicitud de opt-out).
        for msg in ("Hola quiero comprar", "cuánto cuesta el jabón", "2 de coco"):
            self.assertFalse(should_skip(msg), f"{msg!r} NO debe bloquearse")

    def test_none_and_nonstr_safe(self):
        # Entrada degenerada → False (no rompe, no bloquea de más).
        self.assertFalse(should_skip(None))
        self.assertFalse(should_skip(123))
        self.assertFalse(should_skip(""))


if __name__ == "__main__":
    unittest.main()

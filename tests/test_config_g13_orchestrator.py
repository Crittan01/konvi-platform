"""Tests G13 fase 2a — config central del AI Orchestrator
(services/ai-orchestrator/config.py).

Cubre: defaults seguros (importar nunca rompe), cache por proceso, los checks
de boot (URL Supabase https-o-loopback, alguna key Supabase, e
INTERNAL_SERVICE_SECRET) y el check de producción GEMINI_API_KEY (el
orchestrator es el consumidor principal del LLM).

Nota de carga: el módulo se carga por ruta con importlib (nombre único
`g13_orchestrator_config`) porque `tests/test_config_g13.py` ya importa
`config` del api en sys.modules — un `import config` con sys.path chocaría
con él.
"""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "g13_orchestrator_config",
    Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator" / "config.py",
)
cfg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cfg)

_BASE_ENV = {
    "NEXT_PUBLIC_SUPABASE_URL": "https://tenant.supabase.co",
    "SUPABASE_SECRET_KEY": "sb_secret_x",
    "INTERNAL_SERVICE_SECRET": "x" * 40,
}


def _validate_with(env: dict) -> list[str]:
    """Corre validate_critical con un env controlado y settings frescas."""
    with patch.dict(os.environ, env, clear=True):
        cfg.get_settings.cache_clear()
        try:
            return cfg.validate_critical()
        finally:
            cfg.get_settings.cache_clear()


class SettingsBasicsTests(unittest.TestCase):
    def test_cache_mismo_objeto(self):
        cfg.get_settings.cache_clear()
        a = cfg.get_settings()
        b = cfg.get_settings()
        self.assertIs(a, b)
        cfg.get_settings.cache_clear()

    def test_defaults_no_rompen_sin_env(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg.get_settings.cache_clear()
            s = cfg.get_settings()
            self.assertEqual(s.INTERNAL_SERVICE_SECRET, "")
            self.assertEqual(s.INTERNAL_SERVICE_SECRET_PREVIOUS, "")
            self.assertEqual(s.GEMINI_API_KEY, "")
            self.assertEqual(s.GEMINI_MODEL, "gemini-3.1-flash-lite")
            self.assertEqual(s.ANTHROPIC_API_KEY, "")
            self.assertEqual(s.RESEND_FROM_EMAIL, "Konvi <noreply@commerce-ops.local>")
            self.assertEqual(s.POLL_INTERVAL_SECONDS, 3)
            self.assertEqual(s.MAX_PROCESSING_ATTEMPTS, 5)
            self.assertEqual(s.CONVERSATION_HISTORY_LIMIT, 25)
            cfg.get_settings.cache_clear()


class ValidateCriticalTests(unittest.TestCase):
    def test_ok_completo(self):
        self.assertEqual(_validate_with(_BASE_ENV), [])

    def test_falta_url_supabase(self):
        env = {**_BASE_ENV, "NEXT_PUBLIC_SUPABASE_URL": ""}
        self.assertTrue(any("NEXT_PUBLIC_SUPABASE_URL" in e for e in _validate_with(env)))

    def test_url_local_loopback_aceptada(self):
        env = {**_BASE_ENV, "NEXT_PUBLIC_SUPABASE_URL": "http://127.0.0.1:54321"}
        self.assertEqual(_validate_with(env), [])

    def test_falta_secret_key_pero_legacy_cubre(self):
        env = {**_BASE_ENV, "SUPABASE_SECRET_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "legacy"}
        self.assertEqual(_validate_with(env), [])

    def test_sin_ninguna_key_supabase(self):
        env = {**_BASE_ENV, "SUPABASE_SECRET_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": ""}
        self.assertTrue(any("SUPABASE_SECRET_KEY" in e for e in _validate_with(env)))

    def test_falta_internal_secret(self):
        env = {**_BASE_ENV, "INTERNAL_SERVICE_SECRET": ""}
        self.assertTrue(any("INTERNAL_SERVICE_SECRET" in e for e in _validate_with(env)))

    def test_prod_sin_gemini(self):
        env = {**_BASE_ENV, "APP_ENV": "production", "GEMINI_API_KEY": ""}
        self.assertTrue(any("GEMINI_API_KEY" in e for e in _validate_with(env)))

    def test_prod_con_gemini_ok(self):
        env = {**_BASE_ENV, "APP_ENV": "production", "GEMINI_API_KEY": "g-key"}
        self.assertEqual(_validate_with(env), [])

    def test_no_prod_no_exige_gemini(self):
        # APP_ENV vacío (dev local): GEMINI_API_KEY no se exige
        self.assertEqual(_validate_with({**_BASE_ENV, "GEMINI_API_KEY": ""}), [])


if __name__ == "__main__":
    unittest.main()

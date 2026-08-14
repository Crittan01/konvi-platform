"""Tests G13 — config central del Core API (services/api/config.py).

Cubre: defaults seguros (importar nunca rompe), cache por proceso, los 3 checks
históricos de boot (mismo comportamiento que main.py pre-G13) y los checks
nuevos de coherencia producción.
"""
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

import config as cfg  # noqa: E402

_BASE_ENV = {
    "NEXT_PUBLIC_SUPABASE_URL": "https://tenant.supabase.co",
    "SUPABASE_SECRET_KEY": "sb_secret_x",
    "INTERNAL_SERVICE_SECRET": "x" * 40,
    "GEMINI_API_KEY": "g-key",
    "SENTRY_DSN": "https://sentry.io/x",
    "ALLOWED_ORIGINS": "https://konvi-web.onrender.com",
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
            self.assertEqual(s.MFA_MANDATORY_GRACE_DAYS, 14)
            self.assertEqual(s.MAX_REQUEST_BODY_BYTES, 2_097_152)
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

    def test_prod_secret_corta(self):
        env = {**_BASE_ENV, "APP_ENV": "production", "INTERNAL_SERVICE_SECRET": "corta"}
        self.assertTrue(any("demasiado corta" in e for e in _validate_with(env)))

    def test_prod_localhost_en_cors(self):
        env = {**_BASE_ENV, "APP_ENV": "production", "ALLOWED_ORIGINS": "http://localhost:3000"}
        self.assertTrue(any("ALLOWED_ORIGINS" in e for e in _validate_with(env)))

    def test_prod_sin_sentry(self):
        env = {**_BASE_ENV, "APP_ENV": "production", "SENTRY_DSN": ""}
        self.assertTrue(any("SENTRY_DSN" in e for e in _validate_with(env)))

    def test_prod_sin_gemini(self):
        env = {**_BASE_ENV, "APP_ENV": "production", "GEMINI_API_KEY": ""}
        self.assertTrue(any("GEMINI_API_KEY" in e for e in _validate_with(env)))

    def test_prod_meli_redirect_http(self):
        env = {**_BASE_ENV, "APP_ENV": "production", "MELI_CLIENT_ID": "id",
               "MELI_REDIRECT_URI": "http://inseguro/cb"}
        self.assertTrue(any("MELI_REDIRECT_URI" in e for e in _validate_with(env)))

    def test_no_prod_no_exige_los_nuevos(self):
        # APP_ENV vacío (dev local): solo los 3 checks históricos aplican
        self.assertEqual(_validate_with(_BASE_ENV), [])


if __name__ == "__main__":
    unittest.main()

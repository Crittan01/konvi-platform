"""Tests del guard anti-prod para scripts destructivos (cutover D.4).

Cubre el contrato de `scripts/_env_guard.py`: fail-closed contra el ref de
producción, permisivo contra dev, y override auditable `KONVI_ALLOW_PROD=1`.
"""
import importlib.util
import os
import sys

import pytest

_GUARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "_env_guard.py",
)


def _load_guard():
    """Importa scripts/_env_guard.py por path (scripts no es paquete)."""
    spec = importlib.util.spec_from_file_location("_env_guard", _GUARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()

PROD_URL = f"https://{guard.PROD_REF}.supabase.co"
DEV_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": "https://qkltqxbhssgnyjqltwcr.supabase.co"}
PROD_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": PROD_URL}


def test_extract_ref_from_url():
    assert guard.extract_ref(PROD_CREDS) == guard.PROD_REF
    assert guard.extract_ref(DEV_CREDS) == "qkltqxbhssgnyjqltwcr"


def test_extract_ref_fallback_supabase_url_var():
    assert guard.extract_ref({"SUPABASE_URL": PROD_URL}) == guard.PROD_REF


def test_extract_ref_none_when_absent():
    assert guard.extract_ref({}) is None
    assert guard.extract_ref({"NEXT_PUBLIC_SUPABASE_URL": "not-a-url"}) is None


def test_is_prod_true_false():
    assert guard.is_prod(PROD_CREDS) is True
    assert guard.is_prod(DEV_CREDS) is False
    assert guard.is_prod({}) is False


def test_assert_not_prod_dev_passes(monkeypatch):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    # No debe levantar ni salir con credenciales dev.
    guard.assert_not_prod(DEV_CREDS, action="wipe")


def test_assert_not_prod_prod_aborts_fail_closed(monkeypatch):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    with pytest.raises(SystemExit) as exc:
        guard.assert_not_prod(PROD_CREDS, action="wipe")
    assert exc.value.code == 2


def test_assert_not_prod_prod_invalid_override_still_aborts(monkeypatch):
    # Valor distinto de "1" NO habilita (fail-closed).
    monkeypatch.setenv("KONVI_ALLOW_PROD", "true")
    with pytest.raises(SystemExit) as exc:
        guard.assert_not_prod(PROD_CREDS, action="wipe")
    assert exc.value.code == 2


def test_assert_not_prod_prod_with_override_passes(monkeypatch, capsys):
    monkeypatch.setenv("KONVI_ALLOW_PROD", "1")
    guard.assert_not_prod(PROD_CREDS, action="wipe")  # no debe salir
    err = capsys.readouterr().err
    assert "PRODUCCIÓN" in err and "override" in err


def test_assert_not_prod_empty_creds_passes(monkeypatch):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    guard.assert_not_prod({}, action="wipe")  # sin URL → no es prod → pasa

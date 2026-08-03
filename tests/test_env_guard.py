"""Tests del guard fail-closed anti-prod para scripts destructivos (cutover D.4).

Modelo DENY-BY-DEFAULT (allow-only-known-dev): solo un ref de dev reconocido (o
un Supabase local) pasa; prod, ref desconocido y host no-parseable ABORTAN salvo
override `KONVI_ALLOW_PROD=1`. Cubre los fail-open que la review adversarial
encontró (custom domain, pooler, `db.<ref>`, creds vacías).

PRE-LANZAMIENTO (2026-07-20): eliminado el proyecto konvi-dev, konvi-prod es el
único entorno hasta el lanzamiento real. Mientras `LAUNCHED` sea False el ref de
prod clasifica 'prelaunch' y los scripts corren AVISANDO. Estos tests cubren los
DOS modos: el contrato fail-closed completo se re-verifica con `KONVI_LAUNCHED=1`
(fixture `launched`), de modo que apagar el modo pre-lanzamiento no puede
introducir un fail-open silencioso.
"""
import importlib.util
import os

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

# Ref de dev de ejemplo: ya NO viene en la allowlist por default (konvi-dev fue
# eliminado). Los tests que lo tratan como dev lo habilitan vía KONVI_SAFE_REFS,
# que es exactamente el mecanismo previsto si vuelve a existir un proyecto dev.
DEV_REF = "qkltqxbhssgnyjqltwcr"
PROD_URL = f"https://{guard.PROD_REF}.supabase.co"
DEV_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": f"https://{DEV_REF}.supabase.co"}
PROD_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": PROD_URL}
# Formas de prod que NO ponen el ref como primer label → fail-open en el modelo viejo.
POOLER_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": "https://aws-0-us-east-1.pooler.supabase.com:6543"}
CUSTOM_DOMAIN_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": "https://db.konvi.co"}
DBHOST_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": f"https://db.{guard.PROD_REF}.supabase.co"}
LOCAL_CREDS = {"NEXT_PUBLIC_SUPABASE_URL": "http://localhost:54321"}


@pytest.fixture
def launched(monkeypatch):
    """Modo POST-lanzamiento: konvi-prod vuelve a ser 'prod' duro (fail-closed)."""
    monkeypatch.setenv("KONVI_LAUNCHED", "1")


@pytest.fixture
def dev_allowed(monkeypatch):
    """Habilita DEV_REF en la allowlist (ya no viene por default)."""
    monkeypatch.setenv("KONVI_SAFE_REFS", DEV_REF)


# ── extract_ref / _host ─────────────────────────────────────────────────────
def test_extract_ref_canonical():
    assert guard.extract_ref(PROD_CREDS) == guard.PROD_REF
    assert guard.extract_ref(DEV_CREDS) == DEV_REF


def test_extract_ref_handles_db_host_form():
    # `db.<ref>.supabase.co` también resuelve el ref (antes era fail-open).
    assert guard.extract_ref(DBHOST_CREDS) == guard.PROD_REF


def test_extract_ref_robust_to_case_port_path():
    assert guard.extract_ref({"NEXT_PUBLIC_SUPABASE_URL": PROD_URL.upper()}) == guard.PROD_REF
    assert guard.extract_ref({"NEXT_PUBLIC_SUPABASE_URL": PROD_URL + ":443/rest/v1"}) == guard.PROD_REF


def test_extract_ref_fallback_supabase_url_var():
    assert guard.extract_ref({"SUPABASE_URL": PROD_URL}) == guard.PROD_REF


def test_extract_ref_none_for_pooler_custom_empty():
    assert guard.extract_ref(POOLER_CREDS) is None
    assert guard.extract_ref(CUSTOM_DOMAIN_CREDS) is None
    assert guard.extract_ref({}) is None


# ── classify ────────────────────────────────────────────────────────────────
def test_classify_prelaunch(dev_allowed):
    assert guard.classify(DEV_CREDS) == "dev-safe"
    assert guard.classify(LOCAL_CREDS) == "dev-safe"
    assert guard.classify(PROD_CREDS) == "prelaunch"
    assert guard.classify(DBHOST_CREDS) == "prelaunch"
    assert guard.classify(POOLER_CREDS) == "unknown"
    assert guard.classify(CUSTOM_DOMAIN_CREDS) == "unknown"
    assert guard.classify({}) == "unknown"


def test_classify_launched(launched, dev_allowed):
    assert guard.classify(PROD_CREDS) == "prod"
    assert guard.classify(DBHOST_CREDS) == "prod"
    assert guard.classify(DEV_CREDS) == "dev-safe"
    assert guard.classify(POOLER_CREDS) == "unknown"


def test_dev_ref_eliminado_ya_no_es_dev_safe_por_default(monkeypatch):
    """konvi-dev fue eliminado: su ref no debe seguir siendo seguro por inercia."""
    monkeypatch.delenv("KONVI_SAFE_REFS", raising=False)
    assert guard.classify(DEV_CREDS) == "unknown"


def test_is_prod_cubre_prelaunch():
    """'prelaunch' SIGUE siendo el proyecto de producción — is_prod debe decir True."""
    assert guard.is_prod(PROD_CREDS) is True


# ── assert_safe_target: allow known-dev ─────────────────────────────────────
def test_dev_passes(monkeypatch, dev_allowed):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    guard.assert_safe_target(DEV_CREDS, action="wipe")  # no debe salir


def test_local_passes(monkeypatch):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    guard.assert_safe_target(LOCAL_CREDS, action="wipe")


# ── PRE-LANZAMIENTO: prod pasa, pero NUNCA en silencio ──────────────────────
def test_prelaunch_pasa_pero_avisa(monkeypatch, capsys):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    guard.assert_safe_target(PROD_CREDS, action="wipe")  # no debe salir
    err = capsys.readouterr().err
    assert "PRE-LANZAMIENTO" in err, "el aviso es la única red que queda: no puede faltar"
    assert guard.PROD_REF in err


def test_prelaunch_no_afloja_lo_desconocido(monkeypatch):
    """El modo pre-lanzamiento habilita SOLO el ref de prod, no un destino opaco."""
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    for creds in (POOLER_CREDS, CUSTOM_DOMAIN_CREDS, {}):
        with pytest.raises(SystemExit) as exc:
            guard.assert_safe_target(creds, action="wipe")
        assert exc.value.code == 2


# ── assert_safe_target: deny prod / unknown (fail-closed) ───────────────────
@pytest.mark.parametrize("creds", [PROD_CREDS, DBHOST_CREDS, POOLER_CREDS, CUSTOM_DOMAIN_CREDS, {}])
def test_non_dev_aborts_fail_closed(monkeypatch, launched, creds):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    with pytest.raises(SystemExit) as exc:
        guard.assert_safe_target(creds, action="wipe")
    assert exc.value.code == 2


def test_invalid_override_still_aborts(monkeypatch, launched):
    # Cualquier valor != "1" NO habilita (fail-closed).
    for val in ("true", "TRUE", "yes", "0", "01", "11", ""):
        monkeypatch.setenv("KONVI_ALLOW_PROD", val)
        with pytest.raises(SystemExit) as exc:
            guard.assert_safe_target(PROD_CREDS, action="wipe")
        assert exc.value.code == 2


def test_launched_flag_invalido_no_lanza(monkeypatch):
    """Sólo "1" activa el modo lanzado; cualquier otro valor deja pre-lanzamiento."""
    for val in ("true", "TRUE", "yes", "0", "01", ""):
        monkeypatch.setenv("KONVI_LAUNCHED", val)
        assert guard.classify(PROD_CREDS) == "prelaunch", f"KONVI_LAUNCHED={val!r}"


# ── assert_safe_target: override permite destino no-dev ─────────────────────
def test_override_allows_prod(monkeypatch, launched, capsys):
    monkeypatch.setenv("KONVI_ALLOW_PROD", "1")
    guard.assert_safe_target(PROD_CREDS, action="wipe")  # no debe salir
    err = capsys.readouterr().err
    assert "override" in err and "prod" in err.lower()


def test_override_allows_unknown(monkeypatch):
    monkeypatch.setenv("KONVI_ALLOW_PROD", "1")
    guard.assert_safe_target(POOLER_CREDS, action="wipe")  # no debe salir


def test_override_tolerates_whitespace(monkeypatch, launched):
    monkeypatch.setenv("KONVI_ALLOW_PROD", "  1  ")
    guard.assert_safe_target(PROD_CREDS, action="wipe")


# ── KONVI_SAFE_REFS configurable ────────────────────────────────────────────
def test_safe_refs_configurable(monkeypatch):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    other = {"NEXT_PUBLIC_SUPABASE_URL": "https://abcdefghij0123456789.supabase.co"}
    # sin allowlist → unknown → aborta
    monkeypatch.delenv("KONVI_SAFE_REFS", raising=False)
    with pytest.raises(SystemExit):
        guard.assert_safe_target(other, action="wipe")
    # con allowlist → dev-safe → pasa
    monkeypatch.setenv("KONVI_SAFE_REFS", "abcdefghij0123456789")
    guard.assert_safe_target(other, action="wipe")


# ── alias de compat ─────────────────────────────────────────────────────────
def test_assert_not_prod_alias(monkeypatch, launched):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    assert guard.assert_not_prod is guard.assert_safe_target
    with pytest.raises(SystemExit):
        guard.assert_not_prod(PROD_CREDS, action="wipe")


# ── Multi-fuente: DATABASE_URL + SUPABASE_PROJECT_REF (cierre del fail-open) ──
_DBURL_PROD_POOLER = f"postgresql://postgres.{guard.PROD_REF}:pw@aws-0-us.pooler.supabase.com:6543/postgres"
_DBURL_DEV_DIRECT = f"postgresql://postgres:pw@db.{DEV_REF}.supabase.co:5432/postgres"


def test_classify_database_url_prod_pooler_is_prod(launched):
    assert guard.classify({"DATABASE_URL": _DBURL_PROD_POOLER}) == "prod"


def test_classify_database_url_dev_direct_is_dev_safe(dev_allowed):
    assert guard.classify({"DATABASE_URL": _DBURL_DEV_DIRECT}) == "dev-safe"


def test_classify_url_dev_but_database_url_prod_is_prod(launched, dev_allowed):
    # EL FAIL-OPEN QUE CERRAMOS: URL Supabase=dev pero DATABASE_URL=prod → NO dev-safe.
    assert guard.classify({
        "NEXT_PUBLIC_SUPABASE_URL": f"https://{DEV_REF}.supabase.co",
        "DATABASE_URL": _DBURL_PROD_POOLER,
    }) == "prod"


def test_classify_project_ref_prod_is_prod(launched):
    assert guard.classify({"SUPABASE_PROJECT_REF": guard.PROD_REF}) == "prod"


def test_classify_project_ref_dev_is_dev_safe(dev_allowed):
    assert guard.classify({"SUPABASE_PROJECT_REF": DEV_REF}) == "dev-safe"


def test_classify_project_ref_local_slug_es_neutro():
    """ENV-1: el project_id local del CLI ('konvi-platform', con guion) NO es un ref
    cloud — no puede direccionar ningún proyecto *.supabase.co → es neutro y la
    clasificación la deciden URL + DATABASE_URL."""
    local = {
        "NEXT_PUBLIC_SUPABASE_URL": "http://127.0.0.1:54321",
        "SUPABASE_PROJECT_REF": "konvi-platform",
    }
    assert guard.classify(local) == "dev-safe"
    # Solo el slug, sin URL/DATABASE_URL local: no prueba nada → sigue fail-closed.
    assert guard.classify({"SUPABASE_PROJECT_REF": "konvi-platform"}) == "unknown"


def test_classify_project_ref_forma_cloud_desconocido_sigue_fail_closed():
    """Un string CON forma de ref cloud (16+ alnum) fuera de la allowlist sigue
    siendo 'unknown' aunque la URL sea local — el fail-closed no se afloja."""
    assert guard.classify({
        "NEXT_PUBLIC_SUPABASE_URL": "http://127.0.0.1:54321",
        "SUPABASE_PROJECT_REF": "zzzzzzzzzzzzzzzzzzzz",
    }) == "unknown"


def test_classify_database_url_local_is_dev_safe():
    assert guard.classify(
        {"DATABASE_URL": "postgresql://postgres:pw@localhost:54322/postgres"}
    ) == "dev-safe"


def test_assert_safe_target_aborts_on_database_url_prod(monkeypatch, launched):
    monkeypatch.delenv("KONVI_ALLOW_PROD", raising=False)
    with pytest.raises(SystemExit) as e:
        guard.assert_safe_target({"DATABASE_URL": _DBURL_PROD_POOLER}, action="test")
    assert e.value.code == 2

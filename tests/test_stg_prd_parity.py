"""Tests de paridad STG↔PRD (fase S7 — homologación total del entorno local).

Certifica en CI que el entorno local queda homologado a la topología real de
producción, sin depender de Render:

  1. `scripts/dev_env_for_service.py` deriva el set de env vars por servicio de
     render.yaml (la fuente de verdad de PRD) y aplica la precedencia correcta:
     valor local gana · ancladas de ambiente NUNCA heredan el valor PRD ·
     sync:false sin valor local solo pasan si son delta documentado · tuning con
     `value:` se hereda (idéntico a PRD).
  2. `.local/Makefile` arranca cada servicio con el MISMO entrypoint que
     render.yaml (uvicorn main:app api/connector, uvicorn server:app
     orchestrator, pnpm web) y ya no contiene el "megáfono" (-include .env.local
     global) que le daba todas las vars a todos los servicios.
  3. Toda key de render.yaml está documentada en el contrato `.env.example`
     (declarada o en el bloque de tuning) — nada de config PRD fuera del contrato.

Si render.yaml cambia su superficie de env vars, estos tests fallan a propósito:
el cambio debe ser deliberado y reflejarse aquí y en el contrato.
"""
import importlib.util
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = REPO / "scripts" / "dev_env_for_service.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("dev_env_for_service", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_mod()

# Snapshot de la superficie env por servicio en PRD (render.yaml). Si cambia,
# actualiza estos conteos en el mismo commit — es la revisión deliberada.
EXPECTED_KEY_COUNTS = {
    "konvi-web": 13,
    "konvi-connector": 5,
    "konvi-api": 35,
    "konvi-orchestrator": 96,
}


# ─── 1. Parser de render.yaml ────────────────────────────────────────────────

def test_service_spec_cubre_los_4_servicios_con_snapshot_de_conteo():
    for render_name, expected in EXPECTED_KEY_COUNTS.items():
        spec = mod.service_spec(render_name)
        assert len(spec) == expected, (
            f"{render_name}: {len(spec)} keys en render.yaml, esperadas {expected}. "
            "Si el cambio es deliberado, actualiza EXPECTED_KEY_COUNTS."
        )
        keys = [k for k, _ in spec]
        assert len(keys) == len(set(keys)), f"{render_name}: keys duplicadas en render.yaml"


def test_service_spec_servicio_inexistente_aborta():
    try:
        mod.service_spec("konvi-no-existe")
    except KeyError:
        return
    raise AssertionError("servicio inexistente debió levantar KeyError")


def test_sync_false_se_parsean_como_value_none():
    spec = dict(mod.service_spec("konvi-api"))
    # INTERNAL_SERVICE_SECRET es sync:false (secreto de dashboard) en PRD
    assert spec["INTERNAL_SERVICE_SECRET"] is None
    # APP_ENV tiene value: inline en render.yaml
    assert spec["APP_ENV"] is not None


# ─── 2. Precedencia del filtro (build_service_env) ───────────────────────────

def _env_file(tmp_path, content):
    f = tmp_path / ".env.test"
    f.write_text(content)
    return f


def test_valor_local_siempre_gana_sobre_render(tmp_path):
    f = _env_file(tmp_path, "APP_ENV=staging\n")
    env, missing, inherited = mod.build_service_env("api", f)
    assert env["APP_ENV"] == "staging"
    assert "APP_ENV" not in inherited
    assert "APP_ENV" not in missing  # anclada con valor local → OK


def test_anclada_sin_valor_local_es_faltante_nunca_hereda(tmp_path):
    f = _env_file(tmp_path, "")
    _, missing, inherited = mod.build_service_env("api", f)
    for anchored in ("APP_ENV", "APP_URL", "PUBLIC_WEBHOOK_URL", "AVEONLINE_GENERATE_REAL_GUIDES"):
        assert anchored in missing, f"{anchored} debió ser faltante (anclada de ambiente)"
        assert anchored not in inherited


def test_tuning_con_value_en_render_se_hereda(tmp_path):
    f = _env_file(tmp_path, "")
    _, _, inherited = mod.build_service_env("orchestrator", f)
    # tuning operativo con value: en render.yaml → heredado = idéntico a PRD
    assert "POLL_INTERVAL_SECONDS" in inherited
    assert "CONVERSATION_HISTORY_LIMIT" in inherited


def test_sync_false_delta_documentado_se_omite_sin_faltar(tmp_path):
    f = _env_file(tmp_path, "")
    env, missing, _ = mod.build_service_env("orchestrator", f)
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_API_KEY" not in missing
    assert "TELEGRAM_WEBHOOK_SECRET" not in env and "TELEGRAM_WEBHOOK_SECRET" not in missing


def test_sync_false_no_documentado_es_faltante(tmp_path):
    f = _env_file(tmp_path, "")
    _, missing, _ = mod.build_service_env("api", f)
    # secreto sync:false real (no está en _STG_DELTA_OK): debe exigir valor local
    assert "INTERNAL_SERVICE_SECRET" in missing
    assert "SUPABASE_SECRET_KEY" in missing


def test_vars_ajenas_al_servicio_no_se_emiten(tmp_path):
    """Fin del megáfono: aunque el env-file traiga vars de otro servicio, el
    filtrado solo emite las del set PRD del servicio pedido."""
    f = _env_file(tmp_path, "INTERNAL_SERVICE_SECRET=x\nGEMINI_MODEL=gemini-x\n")
    env, _, _ = mod.build_service_env("connector", f)
    assert "INTERNAL_SERVICE_SECRET" not in env  # connector no la recibe en PRD
    assert "GEMINI_MODEL" not in env


def test_web_excluye_vars_de_toolchain(tmp_path):
    f = _env_file(tmp_path, "")
    env, missing, _ = mod.build_service_env("web", f)
    assert "NODE_ENV" not in env and "NODE_ENV" not in missing
    assert "COREPACK_ENABLE_DOWNLOAD_PROMPT" not in env


# ─── 3. Makefile homologado ──────────────────────────────────────────────────

def test_makefile_entrypoints_iguales_a_render():
    mk = (REPO / ".local" / "Makefile").read_text()
    assert "uvicorn main:app --host 0.0.0.0 --port 8001" in mk  # api = PRD
    assert "uvicorn main:app --host 0.0.0.0 --port 8000" in mk  # connector = PRD
    assert "uvicorn server:app --host 0.0.0.0 --port 8002" in mk  # orchestrator = PRD (server:app)
    assert "pnpm --filter web dev" in mk and "pnpm --filter web start" in mk


def test_makefile_sin_megafono_y_con_filtro_por_servicio():
    mk = (REPO / ".local" / "Makefile").read_text()
    assert "-include $(REPO)/.env.local" not in mk  # megáfono eliminado
    # cada start-* genera su env filtrado (fail-closed) antes de arrancar
    for svc in ("api", "connector", "orchestrator", "web"):
        assert f'dev_env_for_service.py" {svc}' in mk, f"Makefile no filtra env para {svc}"
    assert "env -i" in mk  # entorno limpio (sin heredar el env de make)


# ─── 4. Toda key de render.yaml está en el contrato .env.example ─────────────

def _contrato_documented_keys():
    """Keys documentadas en .env.example: declaradas KEY= o mencionadas en el
    bloque de tuning/comentarios (misma regla que test_env_contract_guard)."""
    declared, mentioned = set(), set()
    for line in (REPO / ".env.example").read_text().splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            text = s.lstrip("#").strip()
            for token in text.replace("·", " ").replace(",", " ").split():
                # el contrato agrupa familias con '/': TENANT_HARD_DELETE_ENABLED/INTERVAL_SECONDS/…
                for part in token.split("/"):
                    name = part.split("=")[0].strip()
                    if name.isupper() and "_" in name:
                        mentioned.add(name)
        elif "=" in s:
            declared.add(s.split("=", 1)[0].strip())
    return declared | mentioned


def test_toda_key_de_render_yaml_esta_en_el_contrato():
    documented = _contrato_documented_keys()
    missing_by_service = {}
    for render_name in EXPECTED_KEY_COUNTS:
        faltan = [k for k, _ in mod.service_spec(render_name) if k not in documented]
        if faltan:
            missing_by_service[render_name] = faltan
    assert not missing_by_service, (
        f"keys de render.yaml fuera del contrato .env.example: {missing_by_service}"
    )

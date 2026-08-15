"""Tests del guard anti-mezcla tenant-data ↔ ambiente (scripts/check_env_data_mix.py).

Cubre la lógica pura `evaluate()` (sin DB): las reglas de coherencia entre la
clasificación del destino (dev-safe=STG / prelaunch|prod=PRD) y los datos de
integraciones per-tenant (Wompi environment, Aveonline real_guides_enabled).

Reglas certificadas aquí (docs/infra/environment-segregation.md §5 gap #3):
  • STG + Wompi 'production' (CUALQUIER status — las llaves ya están en Vault) → FAIL
  • STG + real_guides_enabled=true → FAIL (guías reales facturables desde sintéticos)
  • STG limpio → sin findings
  • PRD + Wompi connected en sandbox → WARN (vender sin cobrar; transitorio pre-launch)
  • PRD + Wompi connected en production → sin findings
  • PRD + real_guides_enabled=true → sin findings (decisión legítima del tenant en PRD)
"""
import importlib.util
import os

_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "check_env_data_mix.py",
)


def _load_mod():
    """Importa el script por path (scripts no es paquete)."""
    spec = importlib.util.spec_from_file_location("check_env_data_mix", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_mod()


def _wompi(environment="sandbox", status="connected", tenant="t-1"):
    return {"tenant_id": tenant, "status": status, "environment": environment}


def _shipping(real=False, provider="aveonline", tenant="t-1"):
    return {"tenant_id": tenant, "active_provider": provider, "real_guides_enabled": real}


# ─── STG (dev-safe): fail-closed contra cualquier config productiva ──────────

def test_stg_wompi_production_connected_falla():
    findings = mod.evaluate("dev-safe", [_wompi("production")], [])
    assert [f for f in findings if f[0] == mod.FAIL and f[1] == "wompi-env"]


def test_stg_wompi_production_aunque_no_este_connected_falla():
    """Llaves prod en Vault sintético = fuga, aunque la integración esté pending."""
    for status in ("pending", "disconnected", "error"):
        findings = mod.evaluate("dev-safe", [_wompi("production", status=status)], [])
        assert any(f[0] == mod.FAIL and f[1] == "wompi-env" for f in findings), status


def test_stg_wompi_sandbox_no_falla():
    findings = mod.evaluate("dev-safe", [_wompi("sandbox")], [])
    assert not [f for f in findings if f[0] == mod.FAIL]


def test_stg_real_guides_enabled_falla():
    findings = mod.evaluate("dev-safe", [], [_shipping(real=True)])
    assert [f for f in findings if f[0] == mod.FAIL and f[1] == "aveonline-guides"]


def test_stg_real_guides_false_ok():
    findings = mod.evaluate("dev-safe", [], [_shipping(real=False)])
    assert not findings


def test_stg_limpio_sin_findings():
    findings = mod.evaluate("dev-safe", [_wompi("sandbox")], [_shipping(real=False)])
    assert findings == []


def test_stg_multiples_violaciones_todas_reportadas():
    rows = [_wompi("production", tenant="t-1"), _wompi("production", tenant="t-2")]
    findings = mod.evaluate("dev-safe", rows, [_shipping(real=True, tenant="t-3")])
    fails = [f for f in findings if f[0] == mod.FAIL]
    assert len(fails) == 3  # 2 wompi + 1 guides — ninguna se traga a otra


# ─── PRD (prelaunch/prod): WARN ante sandbox, nunca FAIL por opt-ins ─────────

def test_prd_wompi_sandbox_connected_advierte():
    for kind in ("prelaunch", "prod"):
        findings = mod.evaluate(kind, [_wompi("sandbox")], [])
        assert [f for f in findings if f[0] == mod.WARN and f[1] == "wompi-env"], kind
        assert not [f for f in findings if f[0] == mod.FAIL], kind


def test_prd_wompi_production_connected_ok():
    for kind in ("prelaunch", "prod"):
        findings = mod.evaluate(kind, [_wompi("production")], [])
        assert findings == [], kind


def test_prd_wompi_sandbox_no_connected_no_advierte():
    """Una integración pending/disconnected no procesa pagos: no es mezcla activa."""
    findings = mod.evaluate("prelaunch", [_wompi("sandbox", status="pending")], [])
    assert findings == []


def test_prd_real_guides_enabled_es_decision_legitima():
    findings = mod.evaluate("prod", [], [_shipping(real=True)])
    assert findings == []


def test_prd_wompi_environment_default_ausente_se_trata_sandbox():
    """meta sin 'environment' → wompi_client default 'sandbox' → WARN en PRD."""
    row = {"tenant_id": "t-1", "status": "connected", "environment": "sandbox"}
    findings = mod.evaluate("prod", [row], [])
    assert [f for f in findings if f[0] == mod.WARN]


# ─── Parser del env-file ──────────────────────────────────────────────────────

def test_load_env_file_parsea_y_limpia(tmp_path):
    f = tmp_path / ".env.test"
    f.write_text(
        "# comentario\n"
        "NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321\n"
        'QUOTED="valor con = adentro"\n'
        "SINGLE='x'\n"
        "\n"
        "SIN_IGUAL\n"
    )
    creds = mod._load_env_file(f)
    assert creds["NEXT_PUBLIC_SUPABASE_URL"] == "http://127.0.0.1:54321"
    assert creds["QUOTED"] == "valor con = adentro"
    assert creds["SINGLE"] == "x"
    assert "SIN_IGUAL" not in creds

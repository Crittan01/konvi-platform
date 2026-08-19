#!/usr/bin/env python3.11
"""Guard anti-mezcla tenant-data ↔ ambiente (segregación de ambientes, gap #3).

`_env_guard.py` clasifica el DESTINO (¿a qué proyecto Supabase apunta este
env?). Este script complementa: verifica que los DATOS de integraciones
per-tenant dentro de esa DB sean coherentes con el ambiente — la mezcla
peligrosa no la ve el clasificador de destino:

  • STG (dev-safe, DB sintética local) con config de PRODUCCIÓN:
      - `tenant_integrations` Wompi con `meta.environment='production'`
        (cualquier status): llaves de dinero REAL guardadas en la DB/Vault
        sintéticos — fuga de credenciales productivas al ambiente menos
        controlado, y riesgo de mover plata real desde pruebas.
      - `tenant_shipping_provider_config.real_guides_enabled=true`: guías
        Aveonline REALES (facturables) generadas desde datos sintéticos.
    → FAIL (exit 1). En STG nada productivo tiene sentido: fail-closed.

  • PRD (prelaunch/prod) con config de SANDBOX:
      - Wompi `connected` con `environment != 'production'`: los pagos de
        clientes reales irían al sandbox de Wompi (se "vende" sin cobrar).
    → WARN (exit 0): pre-lanzamiento es un estado legítimo transitorio
      (KAIU sigue sandbox hasta que el founder configure las llaves prod —
      ver docs/PLAN.md "Pendiente inmediato"). Con `--strict` también falla.

Lo que NO se puede verificar desde la DB (documentado, no chequeado):
  • Meta/Telegram: las credenciales viven cifradas en Vault y la config del
    webhook vive en el dashboard del proveedor. "Meta App prod apuntando a
    ngrok" solo se detecta en la consola de Meta al registrar el webhook
    (HITL, docs/infra/environment-segregation.md §3.2/§3.5).

Solo lectura (SELECTs con la secret key; ningún check escribe).

Uso:
    python3.11 scripts/check_env_data_mix.py                     # .env.local (STG)
    python3.11 scripts/check_env_data_mix.py --env-file .env.prd-backup  # PRD
    python3.11 scripts/check_env_data_mix.py --strict            # WARN → FAIL

Exit: 0 = coherente (o solo WARN sin --strict) · 1 = mezcla detectada ·
2 = destino no clasificable o error de lectura (fail-closed).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env_guard import classify  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

# Severidades
FAIL = "FAIL"
WARN = "WARN"


# ─── Lógica pura (testeable sin DB) ──────────────────────────────────────────

def evaluate(target_kind: str, wompi_rows: list[dict], shipping_rows: list[dict]) -> list[tuple[str, str, str]]:
    """Evalúa coherencia ambiente↔datos. Retorna [(severidad, check, detalle)].

    `target_kind` es la salida de _env_guard.classify: 'dev-safe' (STG) o
    'prelaunch'/'prod' (PRD). `wompi_rows`: dicts con tenant_id, status y
    environment (ya extraído de meta). `shipping_rows`: dicts con tenant_id,
    active_provider, real_guides_enabled.
    """
    findings: list[tuple[str, str, str]] = []

    if target_kind == "dev-safe":
        for row in wompi_rows:
            if (row.get("environment") or "").lower() == "production":
                findings.append((
                    FAIL, "wompi-env",
                    f"tenant={row.get('tenant_id')} status={row.get('status')}: "
                    "Wompi environment='production' en STG — llaves de dinero real "
                    "en la DB/Vault sintéticos. Pasar el tenant a 'sandbox' con "
                    "llaves test, o borrar la integración.",
                ))
        for row in shipping_rows:
            if row.get("real_guides_enabled"):
                findings.append((
                    FAIL, "aveonline-guides",
                    f"tenant={row.get('tenant_id')} provider={row.get('active_provider')}: "
                    "real_guides_enabled=true en STG — generaría guías Aveonline "
                    "REALES (facturables) desde datos sintéticos. Poner el flag en false.",
                ))
    else:  # prelaunch / prod
        for row in wompi_rows:
            if (row.get("status") or "") == "connected" and (row.get("environment") or "").lower() != "production":
                findings.append((
                    WARN, "wompi-env",
                    f"tenant={row.get('tenant_id')}: Wompi connected con "
                    f"environment='{row.get('environment') or 'sandbox'}' en PRD — "
                    "los pagos de clientes reales irían al SANDBOX de Wompi "
                    "(vender sin cobrar). Configurar llaves prod + environment='production'.",
                ))
    return findings


# ─── Infra de CLI ─────────────────────────────────────────────────────────────

def _load_env_file(path: Path) -> dict:
    """Parsea un archivo .env a dict (sin tocar os.environ)."""
    creds: dict = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds


def _fetch_rows(creds: dict) -> tuple[list[dict], list[dict]]:
    """Lee las filas relevantes (solo SELECT). Retorna (wompi_rows, shipping_rows)."""
    from supabase import create_client  # type: ignore

    url = creds.get("NEXT_PUBLIC_SUPABASE_URL") or creds.get("SUPABASE_URL")
    key = creds["SUPABASE_SECRET_KEY"]
    if not url or not key:
        raise RuntimeError("falta NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY en el env-file")
    sb = create_client(url, key)

    wompi = (
        sb.table("tenant_integrations")
        .select("tenant_id, status, meta")
        .eq("provider", "wompi")
        .execute()
    )
    wompi_rows = [
        {
            "tenant_id": r.get("tenant_id"),
            "status": r.get("status"),
            "environment": (r.get("meta") or {}).get("environment", "sandbox"),
        }
        for r in (wompi.data or [])
    ]
    shipping = (
        sb.table("tenant_shipping_provider_config")
        .select("tenant_id, active_provider, real_guides_enabled")
        .execute()
    )
    return wompi_rows, (shipping.data or [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", default=str(REPO_ROOT / ".env.local"),
                    help="Env del ambiente a auditar (default: .env.local = STG)")
    ap.add_argument("--strict", action="store_true", help="WARN también cuenta como falla (exit 1)")
    args = ap.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"ABORTADO: no existe {env_path}", file=sys.stderr)
        return 2
    creds = _load_env_file(env_path)

    kind = classify(creds)
    print(f"Target: {env_path.name} → classify='{kind}'")
    if kind == "unknown":
        print(
            "ABORTADO: destino no clasificable como STG ni PRD conocido — "
            "no se puede certificar la coherencia de un ambiente no identificado.",
            file=sys.stderr,
        )
        return 2

    try:
        wompi_rows, shipping_rows = _fetch_rows(creds)
    except Exception as e:
        print(f"ABORTADO: error leyendo la DB ({type(e).__name__}: {e})", file=sys.stderr)
        return 2

    label = "STG" if kind == "dev-safe" else "PRD"
    print(f"Filas auditadas: {len(wompi_rows)} integración(es) Wompi · {len(shipping_rows)} config(s) de envíos")
    findings = evaluate(kind, wompi_rows, shipping_rows)

    for sev, check, detail in findings:
        print(f"  {sev} [{check}] {detail}")

    fails = [f for f in findings if f[0] == FAIL]
    warns = [f for f in findings if f[0] == WARN]
    if fails or (args.strict and warns):
        print(f"\n❌ MEZCLA DETECTADA en {label}: {len(fails)} FAIL, {len(warns)} WARN")
        return 1
    if warns:
        print(f"\n⚠️  {label} coherente con {len(warns)} advertencia(s) (transitorio pre-lanzamiento; --strict las vuelve falla)")
    else:
        print(f"\n✅ {label} coherente: ningún dato de integración contradice el ambiente")
    print("Nota: Meta/Telegram no son auto-chequeables (credenciales en Vault + webhook en dashboard del proveedor) — ver environment-segregation.md §3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

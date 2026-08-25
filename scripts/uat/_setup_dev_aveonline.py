"""Setup de la integración Aveonline DEMO pública para el tenant DEV KAIU — habilita
la cotización real de envíos en el harness UAT (B-3, 2026-08-23).

Cuenta demo PÚBLICA de Aveonline (`demointegracion`, empresa 15289, agente 6135 —
ver docs/integrations/aveonline.md): sin ella el bot no cotiza envíos en el
sandbox local y los escenarios de shipping del harness caen por catálogo, no por
coherencia. La password va al Vault (patrón canónico, igual que _setup_dev_wompi).

También fija en `tenants` los datos que cotizar/guía necesitan (shipping_origin,
email_contacto, nit) — espejo de scratch/track9_restore_stg.py §4, pero
idempotente y env-driven para el CI nocturno.

Guardado fail-closed (testing-only) + idempotente.
Uso: python3.11 scripts/uat/_setup_dev_aveonline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, f"{REPO}/scripts")

creds: dict[str, str] = {}
with open(f"{REPO}/.env.local") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402

print(f"env_guard: {classify(creds)}")
assert_safe_target(creds, action="setup_dev_aveonline (courier demo UAT)")

import os  # noqa: E402

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds["SUPABASE_SECRET_KEY"],
)

TENANT = "d0000000-0000-0000-0000-000000000001"  # KAIU Dev (sandbox)

# Password demo: de .env.local (STG local) o del entorno (CI nocturno — GH secret
# AVEONLINE_DEMO_PASSWORD). Es la cuenta demo PÚBLICA documentada por Aveonline.
USUARIO = creds.get("AVEONLINE_DEMO_USER") or os.environ.get("AVEONLINE_DEMO_USER", "demointegracion")
PASSWORD = creds.get("AVEONLINE_DEMO_PASSWORD") or os.environ.get("AVEONLINE_DEMO_PASSWORD", "")
EMPRESA = creds.get("AVEONLINE_DEMO_EMPRESA") or os.environ.get("AVEONLINE_DEMO_EMPRESA", "15289")
AGENTE = creds.get("AVEONLINE_DEMO_AGENTE") or os.environ.get("AVEONLINE_DEMO_AGENTE", "6135")
if not PASSWORD:
    sys.exit("ERROR: falta AVEONLINE_DEMO_PASSWORD (env o .env.local). Abortado.")

sys.path.insert(0, f"{REPO}/services/ai-orchestrator")
from vault_helper import VaultHelper  # noqa: E402

vault = VaultHelper(sb)

existing = (
    sb.table("tenant_integrations").select("id, credentials")
    .eq("tenant_id", TENANT).eq("provider", "aveonline").execute().data
)
if existing and (existing[0].get("credentials") or {}).get("password_secret_id"):
    print("= integración aveonline ya existe con password_secret_id — no se pisa")
else:
    pwd_id = vault.create_secret(
        secret=PASSWORD,
        name=f"{TENANT}/aveonline/password",
        description="DEV UAT — Aveonline demo pública password.",
    )
    if not pwd_id:
        sys.exit("ERROR: create_secret devolvió None")
    payload = {
        "tenant_id": TENANT,
        "provider": "aveonline",
        "status": "connected",
        "credentials": {
            "usuario": USUARIO,
            "empresa_id": EMPRESA,
            "idagente": AGENTE,
            "password_secret_id": pwd_id,
        },
        "meta": {},
    }
    if existing:
        sb.table("tenant_integrations").update(payload).eq("id", existing[0]["id"]).execute()
        print("~ integración aveonline actualizada (demo)")
    else:
        sb.table("tenant_integrations").insert(payload).execute()
        print("+ integración aveonline creada (demo)")

# Datos del tenant que cotizar/guía necesitan (E2E 2026-08-22): origen Bogotá +
# email de contacto + NIT sintético. Idempotente.
sb.table("tenants").update({
    "shipping_origin": {
        "city": "Bogotá",
        "state": "Bogotá D.C.",
        "street": "Cra 7 # 32-16",
        "dane_code": "11001000",
    },
    "email_contacto": "operaciones.stg@konvi.test",
    "nit": "901000000",
}).eq("id", TENANT).execute()
print("+ tenants: shipping_origin + email_contacto + nit")

print(f"\nOK Aveonline demo listo para tenant {TENANT} (usuario={USUARIO}, empresa={EMPRESA})")

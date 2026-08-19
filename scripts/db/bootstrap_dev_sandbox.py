"""Bootstrap del sandbox DEV tras un replay de migraciones — identidad del tenant KAIU Dev.

POR QUÉ NO USA provision_tenant DIRECTO: el RPC canónico genera un UUID aleatorio, pero el
sandbox DEV usa un UUID FIJO (d0000000-…-0001) del que dependen los seeds, e2e_chat y los
runbooks de UAT. Este script es el ESPEJO EXACTO de los efectos del RPC
(tenants + tenant_users owner + tenant_subscriptions + tenant_integrations 'agentic'),
con ese id fijo. Si el RPC cambia, actualizar aquí.

Guardado fail-closed (testing-only) + idempotente.
Uso: python3.11 scripts/db/bootstrap_dev_sandbox.py
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
assert_safe_target(creds, action="bootstrap_dev_sandbox (crea tenant/owners de prueba)")

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds["SUPABASE_SECRET_KEY"],
)

TENANT_ID = "d0000000-0000-0000-0000-000000000001"
TENANT_NAME = "KAIU Dev (sandbox)"
# Owners del sandbox — deben existir ya en auth.users (sobreviven al replay, que sólo toca public).
OWNER_EMAILS = ("dev-owner@konvi.test", "visual-qa@konvi-qa.test")


def _auth_user_ids() -> dict[str, str]:
    out: dict[str, str] = {}
    page = 1
    while True:
        batch = sb.auth.admin.list_users(page=page, per_page=200)
        users = getattr(batch, "users", None)
        if users is None:
            users = batch if isinstance(batch, list) else []
        if not users:
            break
        for u in users:
            if u.email in OWNER_EMAILS:
                out[u.email] = u.id
        if len(users) < 200:
            break
        page += 1
    return out


# 1. tenant (id fijo)
if sb.table("tenants").select("id").eq("id", TENANT_ID).execute().data:
    print(f"= tenant {TENANT_ID} ya existe")
else:
    sb.table("tenants").insert({"id": TENANT_ID, "name": TENANT_NAME, "status": "active"}).execute()
    print(f"+ tenant creado: {TENANT_NAME}")

# 2. owners (tenant_users)
ids = _auth_user_ids()
missing = [e for e in OWNER_EMAILS if e not in ids]
if missing:
    # No es fatal: el sandbox funciona con al menos un owner. Se reporta para trazabilidad.
    print(f"! auth.users ausentes (no se enlazan): {missing}", file=sys.stderr)
for email, uid in ids.items():
    have = (
        sb.table("tenant_users").select("id")
        .eq("tenant_id", TENANT_ID).eq("user_id", uid).execute().data
    )
    if have:
        print(f"= owner ya enlazado: {email}")
    else:
        sb.table("tenant_users").insert(
            {"user_id": uid, "tenant_id": TENANT_ID, "role": "owner", "status": "active"}
        ).execute()
        print(f"+ owner enlazado: {email}")

# 3. suscripción
if sb.table("tenant_subscriptions").select("id").eq("tenant_id", TENANT_ID).execute().data:
    print("= tenant_subscriptions ya existe")
else:
    sb.table("tenant_subscriptions").insert(
        {"tenant_id": TENANT_ID, "plan_code": "basic", "status": "active"}
    ).execute()
    print("+ tenant_subscriptions basic/active")

# 4. integración 'agentic' (el RPC la crea por defecto desde 20260704155300).
#    SIN esto el dispatcher DEGRADA a escalación humana ("no te entendí") — gap real de UAT.
row = (
    sb.table("tenant_integrations").select("id, meta")
    .eq("tenant_id", TENANT_ID).eq("provider", "agentic").execute().data
)
if row and (row[0].get("meta") or {}).get("agentic_enabled") is True:
    print("= integración agentic ya habilitada")
elif row:
    sb.table("tenant_integrations").update(
        {"status": "connected", "meta": {**(row[0].get("meta") or {}), "agentic_enabled": True}}
    ).eq("id", row[0]["id"]).execute()
    print("~ integración agentic habilitada")
else:
    sb.table("tenant_integrations").insert(
        {"tenant_id": TENANT_ID, "provider": "agentic", "status": "connected",
         "meta": {"agentic_enabled": True}}
    ).execute()
    print("+ integración agentic creada")

print(f"\nOK sandbox DEV listo — tenant_id={TENANT_ID}")
print("Siguiente: scripts/uat/_setup_dev_kaiu_whatsapp.py, seed_kaiu_dev_ux.py, seed_kaiu_dev_finance.py")

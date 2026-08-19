"""Setup de la integración Wompi SANDBOX para el tenant DEV KAIU — habilita el UAT de pagos.

Usa el camino CANÓNICO (el mismo que la UI de Ajustes → Integraciones): las llaves van al
Vault y `tenant_integrations.credentials` guarda sólo los `*_secret_id`. NO se escriben
llaves en claro (aunque el resolver las soporte por legacy).

Las llaves salen de .env (WOMPI_*_SANDBOX) — son de sandbox de Wompi, no de producción.
Guardado fail-closed (testing-only) + idempotente.

Uso: python3.11 scripts/uat/_setup_dev_wompi.py
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
assert_safe_target(creds, action="setup_dev_wompi (integración de pagos sandbox)")

PRIVATE_KEY = creds.get("WOMPI_PRIVATE_KEY_SANDBOX", "")
EVENTS_KEY = creds.get("WOMPI_EVENTS_KEY_SANDBOX", "")
if not PRIVATE_KEY or not EVENTS_KEY:
    sys.exit("ERROR: faltan WOMPI_PRIVATE_KEY_SANDBOX / WOMPI_EVENTS_KEY_SANDBOX en .env")
# Cinturón extra: nunca sembrar llaves de PRODUCCIÓN de Wompi en el sandbox.
if not PRIVATE_KEY.startswith("prv_test_"):
    sys.exit("ERROR: WOMPI_PRIVATE_KEY_SANDBOX no es una llave de test (prv_test_*). Abortado.")

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds["SUPABASE_SECRET_KEY"],
)

TENANT = "d0000000-0000-0000-0000-000000000001"

sys.path.insert(0, f"{REPO}/services/ai-orchestrator")
from vault_helper import VaultHelper  # noqa: E402

vault = VaultHelper(sb)

priv_id = vault.create_secret(
    secret=PRIVATE_KEY,
    name=f"{TENANT}/wompi/private_key",
    description="DEV UAT — Wompi sandbox private key.",
)
ev_id = vault.create_secret(
    secret=EVENTS_KEY,
    name=f"{TENANT}/wompi/events_key",
    description="DEV UAT — Wompi sandbox events key (firma de webhooks).",
)
if not priv_id or not ev_id:
    sys.exit("ERROR: create_secret devolvió None")

payload = {
    "tenant_id": TENANT,
    "provider": "wompi",
    "status": "connected",
    "credentials": {"private_key_secret_id": priv_id, "events_key_secret_id": ev_id},
    "meta": {"environment": "sandbox", "private_key_preview": PRIVATE_KEY[:12] + "…"},
}
existing = (
    sb.table("tenant_integrations").select("id")
    .eq("tenant_id", TENANT).eq("provider", "wompi").execute().data
)
if existing:
    sb.table("tenant_integrations").update(payload).eq("id", existing[0]["id"]).execute()
    print("~ integración wompi actualizada")
else:
    sb.table("tenant_integrations").insert(payload).execute()
    print("+ integración wompi creada")

# Métodos de pago: explícitos (el default es fallback-open = ambos habilitados, pero
# dejarlo explícito hace el UAT determinista y permite probar el gating).
for method, label in (("online_wompi", "Pago en línea"), ("cod", "Contraentrega")):
    row = (
        sb.table("tenant_payment_methods").select("id")
        .eq("tenant_id", TENANT).eq("method", method).execute().data
    )
    if row:
        sb.table("tenant_payment_methods").update(
            {"enabled": True, "display_label": label}
        ).eq("id", row[0]["id"]).execute()
        print(f"~ método {method} habilitado")
    else:
        sb.table("tenant_payment_methods").insert(
            {"tenant_id": TENANT, "method": method, "enabled": True, "display_label": label}
        ).execute()
        print(f"+ método {method} habilitado")

print(f"\nOK Wompi sandbox listo para tenant {TENANT} (environment=sandbox)")

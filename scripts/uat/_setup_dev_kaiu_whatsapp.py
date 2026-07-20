"""Setup WhatsApp integration para el tenant DEV KAIU (d0000000) — habilita UAT del bot
vía e2e_chat.py. Guardado fail-closed (testing-only). Idempotente.

El app_secret es arbitrario pero self-consistent: e2e_chat y el connector leen el MISMO
del Vault (via credentials.app_secret_secret_id) → el HMAC casa. waba_id/phone_id = los
defaults de e2e_chat (coinciden con el cross-tenant invariant del connector).
"""
import sys

sys.path.insert(0, "scripts")
REPO = "/home/ansible/workspaces/konvi-platform"
creds = {}
with open(f"{REPO}/.env") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402
print("env:", classify(creds))
assert_safe_target(creds, action="setup_dev_kaiu_whatsapp (UAT)")

from supabase import create_client  # noqa: E402
sb = create_client(creds["NEXT_PUBLIC_SUPABASE_URL"],
                   creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"])

TENANT = "d0000000-0000-0000-0000-000000000001"
WABA = "2159052118202272"        # DEFAULT_META_WABA_ID de e2e_chat
PHONE_ID = "990364080831295"     # DEFAULT_DEST_PHONE_ID de e2e_chat
APP_SECRET = "dev-uat-app-secret-konvi-kaiu"  # arbitrario self-consistent

sys.path.insert(0, "services/ai-orchestrator")
from vault_helper import VaultHelper  # noqa: E402
vault = VaultHelper(sb)

existing = (sb.table("tenant_integrations").select("id, credentials")
            .eq("tenant_id", TENANT).eq("provider", "whatsapp").execute().data)
if existing and (existing[0].get("credentials") or {}).get("app_secret_secret_id"):
    print("SKIP: ya hay integración WhatsApp con app_secret_secret_id — nada que hacer.")
    sys.exit(0)

secret_id = vault.create_secret(
    secret=APP_SECRET,
    name=f"{TENANT}/whatsapp/app_secret",
    description="DEV UAT — WhatsApp app_secret (Model B ADR-0023).",
)
if not secret_id:
    print("ERROR: create_secret retornó None", file=sys.stderr)
    sys.exit(1)

creds_json = {"app_secret_secret_id": secret_id, "waba_id": WABA, "phone_number_id": PHONE_ID}
meta_json = {"waba_id": WABA, "phone_number_id": PHONE_ID}
if existing:
    sb.table("tenant_integrations").update(
        {"credentials": creds_json, "meta": meta_json, "status": "connected"}
    ).eq("tenant_id", TENANT).eq("provider", "whatsapp").execute()
else:
    sb.table("tenant_integrations").insert(
        {"tenant_id": TENANT, "provider": "whatsapp", "status": "connected",
         "credentials": creds_json, "meta": meta_json}
    ).execute()

print(f"OK: integración WhatsApp DEV KAIU lista. secret_id={secret_id}")
print(f"    Correr UAT: python3.11 scripts/uat/e2e_chat.py send \"...\" --tenant-id {TENANT}")

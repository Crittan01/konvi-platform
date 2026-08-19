"""Phase 1 ADR-0023 — Seed Konvi Dev tenant Vault con META_APP_SECRET env-var.

Idempotente:
  - Si Vault secret ya existe para Konvi Dev, retorna su UUID sin crear nuevo.
  - Si tenant_integrations.credentials.app_secret_secret_id ya está, no overrides.

Uso:
  python3.11 scripts/admin/seed_konvi_dev_app_secret_vault.py

Pre-requisitos:
  - .env con META_APP_SECRET cargado (debe ser el secret de Konvi App ID 819229210624423)
  - .env con NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(".env.local")
load_dotenv("apps/web/.env.local", override=False)

KONVI_DEV_TENANT_ID = "6115474f-7046-44a8-88ad-182dbf7626a6"
KONVI_APP_ID = "819229210624423"


def main() -> int:
    sb_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SECRET_KEY", "")
    meta_app_secret = os.getenv("META_APP_SECRET")

    if not (sb_url and sb_key):
        print("ERROR: faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY en .env",
              file=sys.stderr)
        return 1
    if not meta_app_secret:
        print("ERROR: META_APP_SECRET no está en .env", file=sys.stderr)
        return 1

    # Guard fail-closed (segregación DEV/PROD): siembra el Vault de DEV (konvi_dev).
    # Aborta si el destino Supabase no es un dev reconocido — deny-by-default sobre
    # URL + DATABASE_URL + SUPABASE_PROJECT_REF. Override auditable: KONVI_ALLOW_PROD=1.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from _env_guard import assert_safe_target  # noqa: E402
    assert_safe_target(
        {
            "NEXT_PUBLIC_SUPABASE_URL": sb_url,
            "DATABASE_URL": os.getenv("DATABASE_URL"),
            "SUPABASE_PROJECT_REF": os.getenv("SUPABASE_PROJECT_REF"),
        },
        action="seed_konvi_dev_app_secret_vault",
    )

    sb = create_client(sb_url, sb_key)

    sys.path.insert(0, "services/ai-orchestrator")
    from vault_helper import VaultHelper

    vault = VaultHelper(sb)

    # Idempotency: check if tenant_integrations already has app_secret_secret_id
    row_res = (
        sb.table("tenant_integrations")
        .select("credentials")
        .eq("tenant_id", KONVI_DEV_TENANT_ID)
        .eq("provider", "whatsapp")
        .single()
        .execute()
    )
    creds = (row_res.data or {}).get("credentials") or {}
    if creds.get("app_secret_secret_id"):
        print(
            f"SKIP: Konvi Dev ya tiene app_secret_secret_id="
            f"{creds['app_secret_secret_id']} — nada que hacer."
        )
        return 0

    # Crear nuevo Vault secret
    secret_id = vault.create_secret(
        secret=meta_app_secret,
        name=f"{KONVI_DEV_TENANT_ID}/whatsapp/app_secret",
        description=f"Konvi Dev WhatsApp App Secret (Konvi App {KONVI_APP_ID}). "
                    f"Per-tenant Model B ADR-0023.",
    )
    if not secret_id:
        print("ERROR: create_secret retornó None", file=sys.stderr)
        return 1
    print(f"Vault secret created: {secret_id}")

    # Update credentials con app_secret_secret_id (merge no destructivo)
    new_creds = {**creds, "app_secret_secret_id": secret_id}
    upd = (
        sb.table("tenant_integrations")
        .update({"credentials": new_creds})
        .eq("tenant_id", KONVI_DEV_TENANT_ID)
        .eq("provider", "whatsapp")
        .execute()
    )
    if not upd.data:
        print("ERROR: update tenant_integrations falló", file=sys.stderr)
        return 1
    print(f"tenant_integrations.credentials.app_secret_secret_id = {secret_id}")
    print("OK Konvi Dev sembrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

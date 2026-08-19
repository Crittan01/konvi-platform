#!/usr/bin/env python3.11
"""Submit template a Meta para review (Sem 7 F2 item 6.a / 2026-05-17).

Lee un template en estado LOCAL_DRAFT de la tabla `whatsapp_templates`,
lo submitea a Meta vía `POST /{WABA_ID}/message_templates`, y persiste
el `meta_template_id` retornado + transiciona status a PENDING.

Cuando Meta termina review (15min-48h), envía webhook
`message_template_status_update` → connector persiste APPROVED/REJECTED
automáticamente (item 4).

Uso:
  python3.11 scripts/admin/submit_template_to_meta.py \\
    --tenant-id 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9 \\
    --template-name payment_reminder_v1 \\
    --language es_CO

  # Submit TODOS los LOCAL_DRAFT de un tenant:
  python3.11 scripts/admin/submit_template_to_meta.py \\
    --tenant-id 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9 \\
    --all-drafts

Pre-requisitos:
  - .env con NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY
  - Template en DB con status=LOCAL_DRAFT
  - tenant_integrations.credentials.access_token + waba_id configurados
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("submit_template")


def _load_env():
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _resolve_credentials(sb, tenant_id: str) -> tuple[str, str]:
    """Lee access_token + waba_id de tenant_integrations.credentials."""
    res = (
        sb.table("tenant_integrations")
        .select("credentials, status")
        .eq("tenant_id", tenant_id)
        .eq("provider", "whatsapp")
        .single()
        .execute()
    )
    if not res.data or res.data.get("status") != "connected":
        raise RuntimeError(
            f"tenant_id={tenant_id} no tiene whatsapp connected"
        )
    creds = res.data.get("credentials") or {}
    waba_id = creds.get("waba_id")
    if not waba_id:
        raise RuntimeError(
            f"tenant_id={tenant_id} no tiene waba_id en credentials. "
            "Configurarlo primero en panel admin o vía SQL."
        )

    # Resolver access_token (Vault first, plaintext fallback)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))
    from vault_helper import VaultHelper, resolve_secret  # type: ignore
    access_token = resolve_secret(VaultHelper(sb), creds, "access_token")
    if not access_token:
        raise RuntimeError(
            f"tenant_id={tenant_id} no tiene access_token resolvable"
        )
    return access_token, waba_id


async def submit_one(sb, tenant_id: str, template_name: str, language: str) -> int:
    """Submit UN template específico. Retorna exit code (0 OK)."""
    # 1. Lookup template en DB
    res = (
        sb.table("whatsapp_templates")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("name", template_name)
        .eq("language", language)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        logger.error(
            "[ERROR] template no encontrado tenant=%s name=%s lang=%s",
            tenant_id, template_name, language,
        )
        return 2
    tpl = rows[0]
    if tpl["status"] not in ("LOCAL_DRAFT", "REJECTED"):
        logger.error(
            "[ERROR] template status=%s no permite submit. Solo LOCAL_DRAFT/REJECTED.",
            tpl["status"],
        )
        return 3

    # 2. Credenciales tenant
    try:
        access_token, waba_id = _resolve_credentials(sb, tenant_id)
    except Exception as e:
        logger.error("[ERROR] %s", e)
        return 4

    # 3. Submit a Meta vía MetaBusinessManagementClient
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))
    from lib.meta_business_management_client import (  # type: ignore
        MetaBusinessManagementClient, MetaAuthError, MetaRateLimitError,
        MetaTemplateError,
    )

    client = MetaBusinessManagementClient(
        tenant_id=tenant_id,
        access_token=access_token,
        waba_id=waba_id,
        supabase_client=sb,
        idempotency_enabled=True,
    )

    logger.info(
        "[META] submitting tenant=%s name=%s lang=%s category=%s",
        tenant_id, template_name, language, tpl["category"],
    )

    try:
        result = await client.create_template(
            name=tpl["name"],
            language=tpl["language"],
            category=tpl["category"],
            components=tpl["components"],
            parameter_format=tpl.get("parameter_format") or "POSITIONAL",
        )
    except MetaAuthError as e:
        logger.error("[ERROR] Meta auth (token inválido/expirado): %s", e)
        return 5
    except MetaRateLimitError as e:
        logger.error("[ERROR] Meta rate limit: %s — reintentar en minutos", e)
        return 6
    except MetaTemplateError as e:
        logger.error("[ERROR] Meta template error: %s", e)
        return 7
    except Exception as e:
        logger.error("[ERROR] inesperado: %s", e)
        return 8

    meta_template_id = result["body"].get("id")
    meta_status = result["body"].get("status", "PENDING")

    if not meta_template_id:
        logger.error(
            "[ERROR] Meta no retornó template id. body=%s",
            json.dumps(result["body"], ensure_ascii=False)[:300],
        )
        return 9

    # 4. Actualizar DB: status=PENDING + meta_template_id
    from datetime import datetime, timezone
    sb.table("whatsapp_templates").update({
        "status": "PENDING",
        "meta_template_id": meta_template_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status_reason": None,
    }).eq("id", tpl["id"]).execute()

    logger.info(
        "[META] ✓ submitted name=%s meta_template_id=%s meta_status=%s",
        template_name, meta_template_id, meta_status,
    )
    logger.info(
        "[INFO] Meta hará review en ~15min-48h. Cuando termine, webhook "
        "message_template_status_update actualizará status a APPROVED/REJECTED."
    )
    return 0


async def submit_all_drafts(sb, tenant_id: str) -> int:
    """Submit TODOS los templates LOCAL_DRAFT del tenant."""
    res = (
        sb.table("whatsapp_templates")
        .select("name, language, status")
        .eq("tenant_id", tenant_id)
        .eq("status", "LOCAL_DRAFT")
        .execute()
    )
    drafts = res.data or []
    if not drafts:
        logger.info("[INFO] no hay templates LOCAL_DRAFT para tenant=%s", tenant_id)
        return 0

    logger.info("[INFO] %d templates LOCAL_DRAFT a submitear", len(drafts))
    failed = 0
    for d in drafts:
        rc = await submit_one(sb, tenant_id, d["name"], d["language"])
        if rc != 0:
            failed += 1
    if failed > 0:
        logger.warning("[INFO] %d/%d templates fallaron submit", failed, len(drafts))
        return 1
    logger.info("[INFO] ✓ todos los templates submitted OK")
    return 0


async def main():
    _load_env()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant-id", required=True, help="UUID del tenant")
    p.add_argument("--template-name", help="Nombre canonical (e.g. payment_reminder_v1)")
    p.add_argument("--language", default="es_CO")
    p.add_argument("--all-drafts", action="store_true",
                   help="Submit TODOS los LOCAL_DRAFT del tenant")
    args = p.parse_args()

    if not args.all_drafts and not args.template_name:
        p.error("--template-name requerido si no usás --all-drafts")

    from supabase import create_client  # type: ignore
    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["SUPABASE_SECRET_KEY"],
    )

    if args.all_drafts:
        rc = await submit_all_drafts(sb, args.tenant_id)
    else:
        rc = await submit_one(sb, args.tenant_id, args.template_name, args.language)
    sys.exit(rc)


if __name__ == "__main__":
    asyncio.run(main())

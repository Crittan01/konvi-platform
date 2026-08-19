#!/usr/bin/env python3
"""Cleanup Vault secrets Envia huérfanos post-pivote Aveonline (rev. 109).

Tras aplicar migration `20260601000000_deprecate_envia_provider.sql`, las
rows de `tenant_integrations` con `provider='envia'` se eliminan, pero los
secrets en Supabase Vault (`<tenant_id>/envia/api_token`) NO se borran
automáticamente — quedan huérfanos (data residual, no expuesta runtime).

Este script:
  1. Lee `audit_log` o backup pre-migration para identificar tenant_ids
     que tuvieron provider='envia' conectado.
  2. Por cada tenant: invoca `vault.secrets DELETE` vía RPC.
  3. Loggea acción en `audit_log` (post-cleanup).

INTERVENCION HUMANA REQUERIDA:
  - Antes de ejecutar: backup tabla `vault.secrets` filtered por
    `name LIKE '%/envia/%'` (los nombres del secret reflejan el provider).
  - Después de ejecutar: verificar 0 secrets restantes con
    `SELECT count(*) FROM vault.secrets WHERE name LIKE '%/envia/%';`
  - Si el ENVIA_API_KEY local del .env era productivo compartido,
    rotar manualmente con Envia antes de eliminar (aunque la cuenta
    Envia ya no se usa, evitar exposición de credenciales en logs/git).

Uso:
    python3 scripts/admin/cleanup_envia_vault_secrets.py --dry-run    # listar sin eliminar
    python3 scripts/admin/cleanup_envia_vault_secrets.py --execute    # ejecutar cleanup real
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main(dry_run: bool = True) -> int:
    """Ejecuta cleanup. Retorna exit code (0=OK, 1=error)."""
    try:
        from supabase import create_client, Client
    except ImportError:
        logger.error("supabase-py no instalado. pip install supabase==2.28.3")
        return 1

    supabase_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
    service_key = os.getenv("SUPABASE_SECRET_KEY", "")
    if not supabase_url or not service_key:
        logger.error(
            "Faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY. "
            "Exportar antes de ejecutar."
        )
        return 1

    client: Client = create_client(supabase_url, service_key)

    # 1. Listar secrets Envia residuales en vault.secrets.
    #    El name pattern del secret incluye el provider: `<tenant_id>/envia/<credential_name>`.
    try:
        result = client.rpc("pgsec_list_secrets_by_name_pattern", {
            "p_pattern": "%/envia/%",
        }).execute()
    except Exception as exc:
        logger.error(
            "No pude listar secrets via RPC pgsec_list_secrets_by_name_pattern: %s",
            exc,
        )
        logger.info(
            "Fallback: query directa vault.secrets requiere acceso DB privilegiado. "
            "Ejecutar manualmente:\n"
            "    SELECT id, name FROM vault.secrets WHERE name LIKE '%/envia/%';"
        )
        return 1

    rows = result.data or []
    if not rows:
        logger.info("✅ 0 secrets Envia residuales en Vault. Nada que limpiar.")
        return 0

    logger.info("Encontrados %d secrets Envia residuales en Vault:", len(rows))
    for row in rows:
        logger.info("  - id=%s name=%s", row.get("id"), row.get("name"))

    if dry_run:
        logger.info(
            "DRY RUN: NO se eliminaron secrets. "
            "Re-ejecutar con --execute para limpieza real."
        )
        return 0

    # 2. Ejecutar DELETE de cada secret via RPC.
    deleted = 0
    failed = 0
    for row in rows:
        secret_id = row.get("id")
        if not secret_id:
            continue
        try:
            client.rpc("pgsec_delete_secret", {"p_id": secret_id}).execute()
            deleted += 1
        except Exception as exc:
            logger.error("Failed delete secret id=%s: %s", secret_id, exc)
            failed += 1

    logger.info("✅ Cleanup completo: %d deleted, %d failed", deleted, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cleanup Vault secrets Envia huérfanos post-pivote Aveonline."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Listar secrets sin eliminar (default).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Ejecutar cleanup real (DELETE secrets).",
    )
    args = parser.parse_args()

    # --execute override --dry-run
    if args.execute:
        sys.exit(main(dry_run=False))
    else:
        sys.exit(main(dry_run=True))

"""Cutover agentic per tenant.

ADR-0018 Fase C. Production-grade.

Activa/desactiva el flag `tenant_integrations.meta.agentic_enabled` para
un tenant específico. Sin flag = comportamiento legacy idéntico al
pre-refactor (rollback inmediato disponible).

Uso:
    python3.11 scripts/agentic_cutover.py --tenant <UUID> --enable
    python3.11 scripts/agentic_cutover.py --tenant <UUID> --disable
    python3.11 scripts/agentic_cutover.py --status               # lista tenants con flag
    python3.11 scripts/agentic_cutover.py --tenant <UUID> --shadow-only

Modos:
  --enable        agentic_enabled=True (responde al cliente).
  --disable       agentic_enabled=False (legacy responde).
  --shadow-only   marca metadata.agentic_shadow_observation=True; no
                  afecta dispatcher pero sirve para tracking de tenants
                  bajo observación.
  --status        imprime tabla de tenants con sus flags actuales.

Antes de --enable en producción:
  1. Verificar suite verde (2,240+ tests).
  2. Verificar golden conversations E2E pasan con Gemini real
     (tests/agentic/test_golden_conversations.py).
  3. Ejecutar 7 días de shadow mode (AGENTIC_SHADOW_ENABLED=true env
     del worker) sobre el tenant target. Analizar agentic_shadow_log
     para divergencias.
  4. Solo entonces --enable. Cliente recibirá respuestas del agentic.

Rollback:
  --disable revierte al instante. El worker en su siguiente polling
  cycle (≤3s) usa legacy para ese tenant.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path("/home/ansible/workspaces/commerce-ops-platform")
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))


def _load_env():
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        if k.strip() and v:
            os.environ.setdefault(k.strip(), v)


def _get_supabase():
    from supabase import create_client
    url = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _read_current_meta(sb, tenant_id: str) -> dict:
    """Lee tenant_integrations.meta del tenant (puede no existir todavía)."""
    res = (
        sb.table("tenant_integrations")
        .select("id, meta")
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return {"_row_exists": False, "meta": {}}
    return {
        "_row_exists": True,
        "_row_id": rows[0]["id"],
        "meta": rows[0].get("meta") or {},
    }


def _update_meta(sb, tenant_id: str, new_meta: dict) -> None:
    current = _read_current_meta(sb, tenant_id)
    if current["_row_exists"]:
        merged = {**(current["meta"] or {}), **new_meta}
        sb.table("tenant_integrations").update({"meta": merged}).eq(
            "id", current["_row_id"]
        ).execute()
    else:
        # Crear row mínimo para el tenant.
        sb.table("tenant_integrations").insert({
            "tenant_id": tenant_id,
            "integration_type": "agentic_config",
            "status": "active",
            "meta": new_meta,
        }).execute()


def cmd_enable(sb, tenant_id: str) -> None:
    print(f"[CUTOVER] Activando agentic_enabled=True para tenant {tenant_id}")
    _update_meta(sb, tenant_id, {"agentic_enabled": True})
    print("✓ Tenant en modo AGENTIC FULL.")
    print(
        "El cliente verá respuestas del agente (Gemini function calling). "
        "Rollback inmediato con --disable."
    )


def cmd_disable(sb, tenant_id: str) -> None:
    print(f"[CUTOVER] Desactivando agentic_enabled para tenant {tenant_id}")
    _update_meta(sb, tenant_id, {"agentic_enabled": False})
    print("✓ Tenant en modo LEGACY.")
    print(
        "El worker en su próximo polling cycle (≤3s) usará legacy "
        "para ese tenant."
    )


def cmd_shadow_only(sb, tenant_id: str) -> None:
    print(f"[CUTOVER] Marcando tenant {tenant_id} para observación shadow")
    _update_meta(sb, tenant_id, {
        "agentic_enabled": False,
        "agentic_shadow_observation": True,
    })
    print("✓ Tenant marcado para shadow.")
    print(
        "NOTA: shadow mode se activa con AGENTIC_SHADOW_ENABLED=true env "
        "del worker (afecta TODOS los tenants, no per-tenant). Este flag "
        "solo sirve para tracking + analytics posterior."
    )


def cmd_status(sb) -> None:
    print("[CUTOVER] Estado de tenants:")
    print()
    res = (
        sb.table("tenant_integrations")
        .select("tenant_id, meta")
        .execute()
    )
    rows = res.data or []
    if not rows:
        print("  (Sin filas en tenant_integrations.)")
        return
    enabled = []
    shadow_only = []
    disabled = []
    for row in rows:
        tid = row.get("tenant_id")
        meta = row.get("meta") or {}
        if meta.get("agentic_enabled"):
            enabled.append(tid)
        elif meta.get("agentic_shadow_observation"):
            shadow_only.append(tid)
        else:
            disabled.append(tid)
    print(f"AGENTIC FULL (cliente ve agentic):  {len(enabled)} tenants")
    for tid in enabled:
        print(f"  • {tid}")
    print(f"SHADOW observation marked:          {len(shadow_only)} tenants")
    for tid in shadow_only:
        print(f"  • {tid}")
    print(f"LEGACY (default):                   {len(disabled)} tenants")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", type=str, help="tenant_id UUID")
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--shadow-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    _load_env()
    sb = _get_supabase()

    if args.status:
        cmd_status(sb)
        return

    if not args.tenant:
        parser.error("--tenant <UUID> requerido salvo con --status")

    if args.enable:
        cmd_enable(sb, args.tenant)
    elif args.disable:
        cmd_disable(sb, args.tenant)
    elif args.shadow_only:
        cmd_shadow_only(sb, args.tenant)
    else:
        parser.error("--enable | --disable | --shadow-only requerido")


if __name__ == "__main__":
    main()

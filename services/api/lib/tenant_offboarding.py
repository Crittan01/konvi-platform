"""Tenant offboarding workflow (rev. 109 J.2.4.4).

Implementa el ciclo completo de cierre de cuenta de un tenant cumpliendo
Habeas Data Ley 1581 Art. 16 (derecho de eliminación) + Art. 22 (deber
de custodia trazabilidad post-cierre).

Modelo lifecycle:
    ACTIVE → request_deletion() → SOFT_DELETED (30d grace)
              ↓ cancel_deletion()          ↓ cron @ scheduled_for
            ACTIVE                       HARD_DELETED (deleted_at NOT NULL)

Funciones:
    - export_tenant_data(sb, tenant_id, requester) → dict portabilidad completa.
    - request_tenant_deletion(sb, tenant_id, actor_*) → soft-delete vía RPC.
    - cancel_tenant_deletion(sb, tenant_id, actor_*) → revierte soft-delete.
    - hard_delete_tenant(sb, tenant_id) → cron-only, ejecuta cascade + archive.

Patrón de uso:
    from lib.tenant_offboarding import (
        export_tenant_data, request_tenant_deletion, cancel_tenant_deletion,
    )

    # Endpoint POST /api/v1/tenant/offboarding/export:
    payload = export_tenant_data(supabase, tenant_id, actor_email)
    return JSONResponse(payload)

    # Endpoint POST /api/v1/tenant/offboarding/request-deletion:
    scheduled = request_tenant_deletion(
        supabase, tenant_id, actor_user_id, actor_email, actor_ip, reason,
    )
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Tablas tenant-scoped que entran al export. Listado verificado contra
# audit Plan K (2026-05-29) — refresh si se agregan tablas nuevas con tenant_id.
# Ordenadas por importancia: identidad del tenant → operación → audit.
EXPORTABLE_TABLES_CORE = (
    # Identidad + config del tenant
    "tenant_integrations",
    "tenant_legal_acceptance",
    "tenant_subscriptions",
    "tenant_payment_methods",
    "tenant_carriers",
    "tenant_cancellation_policy",
    "ai_agents",
    "notification_settings",
)

EXPORTABLE_TABLES_OPERATION = (
    # Catálogo + operación comercial
    "products",
    "product_variations",
    "marketplace_listings",
    "kb_documents",
)

EXPORTABLE_TABLES_CUSTOMERS = (
    # Customers + conversaciones (data sujeto Ley 1581 — PII)
    "contacts",
    "conversations",
    "messages",
    "orders",
    "order_items",
    "shipments",
    "shipment_tracking_events",
    "claims",
    "payments",
    "stock_movements",
    "rma_requests",
)

EXPORTABLE_TABLES_AUDIT = (
    # Audit (preservado en archive antes de hard-delete por Art. 22)
    "consent_audit_log",
    "pii_access_log",
    "audit_log",
)


# Tablas que requieren PRESERVACIÓN en cold archive antes del hard-delete
# (Art. 22 deber custodia trazabilidad 5 años post-cierre).
ARCHIVE_BEFORE_HARD_DELETE = (
    "consent_audit_log",
    "pii_access_log",
    "audit_log",
    "tenant_legal_acceptance",
    "tenant_offboarding_log",
)


# Límite de filas por tabla en el export. Defensivo contra OOM en tenants
# grandes (e.g. 100k mensajes). Mensaje claro al usuario en cada export.
MAX_ROWS_PER_TABLE = 10_000


class TenantOffboardingError(Exception):
    """Error de negocio del módulo (no IO). Mapeable a HTTP 4xx."""


@dataclass(frozen=True)
class ExportSummary:
    """Resumen de un export — cabecera del payload."""
    tenant_id: str
    format_version: str
    generated_at: str
    truncated_tables: tuple[str, ...]
    total_rows_exported: int


def _query_tenant_scoped(
    sb: Any, table: str, tenant_id: str, limit: int = MAX_ROWS_PER_TABLE,
) -> tuple[list[dict[str, Any]], bool]:
    """Lee filas tenant-scoped de una tabla con límite defensivo. Retorna
    (rows, truncated) donde truncated=True si rows == limit (puede haber más).
    """
    try:
        res = (
            sb.table(table)
            .select("*")
            .eq("tenant_id", tenant_id)
            .limit(limit)
            .execute()
        )
        rows = res.data or []
        return rows, len(rows) >= limit
    except Exception as exc:
        # NO levantar: una tabla faltante (e.g. migration no aplicada) NO debe
        # bloquear el export entero. Loguear y continuar con resto.
        logger.warning(
            "[OFFBOARDING] Error leyendo tabla %s para tenant %s: %s. "
            "Continuando con resto del export.",
            table, tenant_id, exc,
        )
        return [], False


def export_tenant_data(
    sb: Any,
    tenant_id: str,
    requester_email: Optional[str] = None,
) -> dict[str, Any]:
    """Genera payload completo de export del tenant para portabilidad
    Habeas Data Ley 1581 Art. 19.

    Retorna dict serializable JSON con: tenant metadata + 4 secciones
    (core, operation, customers, audit) + summary.

    Lanza TenantOffboardingError si el tenant no existe.
    Tolerante a tablas faltantes (loguea warning, sigue con resto).
    """
    # 1. Verificar tenant existe + leer metadata.
    try:
        tenant_res = (
            sb.table("tenants")
            .select("*")
            .eq("id", tenant_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("[OFFBOARDING] Error DB leyendo tenant %s: %s", tenant_id, exc)
        raise TenantOffboardingError(
            "DB no disponible para componer export. Reintenta en unos segundos."
        )
    if not tenant_res.data:
        raise TenantOffboardingError(f"Tenant {tenant_id} no encontrado")
    tenant = tenant_res.data[0]

    # 2. Iterar tablas por grupo, capturando truncados.
    truncated: list[str] = []
    total_rows = 0

    def _collect(tables: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
        nonlocal total_rows
        out: dict[str, list[dict[str, Any]]] = {}
        for t in tables:
            rows, was_truncated = _query_tenant_scoped(sb, t, tenant_id)
            out[t] = rows
            total_rows += len(rows)
            if was_truncated:
                truncated.append(t)
        return out

    core = _collect(EXPORTABLE_TABLES_CORE)
    operation = _collect(EXPORTABLE_TABLES_OPERATION)
    customers = _collect(EXPORTABLE_TABLES_CUSTOMERS)
    audit = _collect(EXPORTABLE_TABLES_AUDIT)

    # 3. Componer payload final.
    summary = ExportSummary(
        tenant_id=tenant_id,
        format_version="1.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        truncated_tables=tuple(truncated),
        total_rows_exported=total_rows,
    )

    return {
        "format_version": summary.format_version,
        "generated_at": summary.generated_at,
        "tenant": {
            "id": tenant.get("id"),
            "name": tenant.get("name"),
            "slug": tenant.get("slug"),
            "owner_email": tenant.get("owner_email"),
            "phone": tenant.get("phone"),
            "country": tenant.get("country"),
            "created_at": tenant.get("created_at"),
            "deletion_requested_at": tenant.get("deletion_requested_at"),
            "deletion_scheduled_for": tenant.get("deletion_scheduled_for"),
        },
        "requested_by": requester_email,
        "summary": {
            "total_rows_exported": summary.total_rows_exported,
            "truncated_tables": list(summary.truncated_tables),
            "max_rows_per_table": MAX_ROWS_PER_TABLE,
            "note": (
                "Tablas listadas en truncated_tables exceden el límite de "
                f"{MAX_ROWS_PER_TABLE} filas. Para export completo contacta "
                "soporte por enlace dedicado de descarga."
                if truncated else None
            ),
        },
        "data": {
            "core_config": core,
            "operation": operation,
            "customers_and_pii": customers,
            "audit_trail": audit,
        },
        "legal_basis": {
            "law": "Ley 1581/2012 Colombia (Habeas Data) — Art. 19 portabilidad",
            "responsible": "Tenant (encargado del dato)",
            "processor": "Plataforma Konvi (responsable del tratamiento técnico)",
        },
    }


def request_tenant_deletion(
    sb: Any,
    tenant_id: str,
    actor_user_id: str,
    actor_email: str,
    actor_ip: Optional[str],
    reason: str,
    grace_period_days: int = 30,
) -> datetime:
    """Inicia soft-delete del tenant. Invoca RPC SQL transaccional
    fn_request_tenant_deletion.

    Returns: scheduled_for (timestamp del hard-delete programado).
    Raises TenantOffboardingError si ya hay offboarding en curso.
    """
    if not reason or not reason.strip():
        raise TenantOffboardingError("Razón de eliminación es obligatoria.")

    try:
        res = sb.rpc(
            "fn_request_tenant_deletion",
            {
                "p_tenant_id": tenant_id,
                "p_actor_user_id": actor_user_id,
                "p_actor_email": actor_email,
                "p_actor_ip": actor_ip,
                "p_reason": reason.strip(),
                "p_grace_period_days": grace_period_days,
            },
        ).execute()
    except Exception as exc:
        # SQLSTATE 40000 levantado por la RPC si ya hay offboarding.
        msg = str(exc).lower()
        if "ya tiene offboarding en curso" in msg or "40000" in msg:
            raise TenantOffboardingError(
                "Este tenant ya tiene una solicitud de eliminación en curso. "
                "Usa /cancel-deletion antes de iniciar una nueva."
            )
        logger.error(
            "[OFFBOARDING] Error invocando fn_request_tenant_deletion "
            "tenant=%s actor=%s: %s",
            tenant_id, actor_email, exc,
        )
        raise TenantOffboardingError("DB no disponible. Reintenta en unos segundos.")

    raw = res.data
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if isinstance(raw, dict):
        raw = next(iter(raw.values()), None)
    if raw is None:
        raise TenantOffboardingError(
            "RPC retornó valor inesperado. Contacta soporte."
        )

    # Parse timestamp ISO Postgres → datetime UTC.
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if isinstance(raw, datetime):
        return raw
    raise TenantOffboardingError(
        f"Timestamp retornado inválido: {type(raw)!r}"
    )


def cancel_tenant_deletion(
    sb: Any,
    tenant_id: str,
    actor_user_id: str,
    actor_email: str,
    actor_ip: Optional[str],
) -> bool:
    """Cancela soft-delete dentro del grace period. Invoca RPC
    fn_cancel_tenant_deletion.

    Returns: True si se canceló (estaba en curso), False si no había
    offboarding pendiente para este tenant.
    Raises TenantOffboardingError si el tenant ya fue hard-deleted.
    """
    try:
        res = sb.rpc(
            "fn_cancel_tenant_deletion",
            {
                "p_tenant_id": tenant_id,
                "p_actor_user_id": actor_user_id,
                "p_actor_email": actor_email,
                "p_actor_ip": actor_ip,
            },
        ).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "ya fue hard-deleted" in msg or "40000" in msg:
            raise TenantOffboardingError(
                "Este tenant ya fue eliminado permanentemente; no se puede cancelar."
            )
        logger.error(
            "[OFFBOARDING] Error invocando fn_cancel_tenant_deletion "
            "tenant=%s actor=%s: %s",
            tenant_id, actor_email, exc,
        )
        raise TenantOffboardingError("DB no disponible. Reintenta en unos segundos.")

    raw = res.data
    if isinstance(raw, list):
        raw = raw[0] if raw else False
    if isinstance(raw, dict):
        raw = next(iter(raw.values()), False)
    return bool(raw)


def get_offboarding_status(sb: Any, tenant_id: str) -> dict[str, Any]:
    """Retorna estado actual del offboarding para un tenant.

    Útil para el endpoint GET /api/v1/tenant/offboarding/status que la UI
    consulta para mostrar el banner "tu cuenta será eliminada en X días".
    """
    try:
        res = (
            sb.table("tenants")
            .select(
                "id, deletion_requested_at, deletion_scheduled_for, "
                "deletion_requested_by, deletion_reason, deleted_at"
            )
            .eq("id", tenant_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("[OFFBOARDING] Error DB status tenant=%s: %s", tenant_id, exc)
        raise TenantOffboardingError("DB no disponible.")
    if not res.data:
        raise TenantOffboardingError(f"Tenant {tenant_id} no encontrado")

    t = res.data[0]
    requested_at = t.get("deletion_requested_at")
    scheduled_for = t.get("deletion_scheduled_for")
    deleted_at = t.get("deleted_at")

    if deleted_at:
        state = "hard_deleted"
    elif requested_at:
        state = "soft_deleted_grace_period"
    else:
        state = "active"

    return {
        "tenant_id": tenant_id,
        "state": state,
        "deletion_requested_at": requested_at,
        "deletion_scheduled_for": scheduled_for,
        "deletion_reason": t.get("deletion_reason"),
        "deleted_at": deleted_at,
        "is_recoverable": state == "soft_deleted_grace_period",
    }


# ─── Hard-delete (cron-only, NO exponer en router HTTP) ──────────────────────

ARCHIVE_BUCKET = "offboarding-archive"


def _snapshot_to_archive(sb: Any, tenant_id: str) -> tuple[str, dict[str, int]]:
    """Snapshot de tablas ARCHIVE_BEFORE_HARD_DELETE al bucket Storage
    'offboarding-archive'. Retorna (archive_path, counts_per_table).

    Path format: {tenant_id}/{utc_iso_timestamp}/manifest.json + 1 file per table.
    Retention: manual 5 años (Supabase Free tier NO tiene TTL automático;
    cleanup vía script admin SIC-driven post-grace).
    """
    import json as _json
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_path = f"{tenant_id}/{timestamp}"
    counts: dict[str, int] = {}

    manifest: dict[str, Any] = {
        "tenant_id": tenant_id,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "retention_years": 5,
        "legal_basis": "Ley 1581 Art. 22 — deber custodia trazabilidad post-cierre",
        "tables": [],
    }

    for table in ARCHIVE_BEFORE_HARD_DELETE:
        try:
            rows, _truncated = _query_tenant_scoped(sb, table, tenant_id, limit=100_000)
        except Exception as exc:
            logger.warning(
                "[OFFBOARDING-ARCHIVE] Skip tabla %s (no existe o sin permisos): %s",
                table, exc,
            )
            counts[table] = 0
            continue

        counts[table] = len(rows)
        manifest["tables"].append({"name": table, "row_count": len(rows)})

        if not rows:
            continue

        # Upload jsonl al bucket — append-only audit data.
        content_jsonl = "\n".join(_json.dumps(r, default=str) for r in rows)
        file_path = f"{base_path}/{table}.jsonl"
        try:
            sb.storage.from_(ARCHIVE_BUCKET).upload(
                file_path,
                content_jsonl.encode("utf-8"),
                {"content-type": "application/x-ndjson", "upsert": "false"},
            )
        except Exception as exc:
            # NO romper si el upload falla — preferimos audit log degradado
            # a NO borrar el tenant (compliance Art. 16 derecho eliminación).
            logger.error(
                "[OFFBOARDING-ARCHIVE] Falló upload %s tenant=%s: %s. "
                "Procediendo con hard-delete sin esta tabla en archive.",
                table, tenant_id, exc,
            )

    # Subir manifest.json
    manifest["counts"] = counts
    manifest_path = f"{base_path}/manifest.json"
    try:
        sb.storage.from_(ARCHIVE_BUCKET).upload(
            manifest_path,
            _json.dumps(manifest, indent=2).encode("utf-8"),
            {"content-type": "application/json", "upsert": "false"},
        )
    except Exception as exc:
        logger.error(
            "[OFFBOARDING-ARCHIVE] Falló upload manifest tenant=%s: %s",
            tenant_id, exc,
        )

    return base_path, counts


def hard_delete_tenant(sb: Any, tenant_id: str) -> dict[str, Any]:
    """Ejecuta hard-delete del tenant. Invocada por cron worker tras
    grace_period vencido (deletion_scheduled_for <= NOW + deleted_at IS NULL).

    NO exponer en endpoint HTTP — solo cron job autorizado.

    Flujo:
      1. Snapshot ARCHIVE_BEFORE_HARD_DELETE a Storage 'offboarding-archive'
         (audit_log + consent + pii_access + legal + offboarding_log).
         Retention manual 5y (Art. 22 deber custodia).
      2. RPC fn_hard_delete_tenant ejecuta atómicamente:
         - Log 'archived' con archive_path.
         - UPDATE tenants SET deleted_at = NOW().
         - Log 'hard_deleted' (sobrevive CASCADE por diseño Fase 1).
         - DELETE FROM tenants — CASCADE limpia ~50 tablas hijas.

    Returns dict con: tenant_id, archive_path, archive_counts,
    total_archived_rows, rpc_result.

    Raises TenantOffboardingError si tenant no elegible o RPC falla.
    """
    # 1. Snapshot a archive.
    archive_path, counts = _snapshot_to_archive(sb, tenant_id)
    total_archived = sum(counts.values())
    logger.info(
        "[OFFBOARDING] Snapshot tenant=%s path=%s rows=%s",
        tenant_id, archive_path, total_archived,
    )

    # 2. Invocar RPC atómica.
    try:
        res = sb.rpc(
            "fn_hard_delete_tenant",
            {
                "p_tenant_id": tenant_id,
                "p_archive_path": archive_path,
                "p_evidence": {
                    "counts": counts,
                    "total_archived_rows": total_archived,
                },
            },
        ).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if (
            "no es elegible" in msg
            or "todavía en grace period" in msg
            or "40000" in msg
        ):
            raise TenantOffboardingError(str(exc))
        logger.error(
            "[OFFBOARDING] Error invocando fn_hard_delete_tenant tenant=%s: %s",
            tenant_id, exc,
        )
        raise TenantOffboardingError(
            f"Hard-delete falló para tenant {tenant_id}: {exc}. "
            "Snapshot ya subido a archive — re-intentar tras resolver."
        )

    rpc_result = res.data
    if isinstance(rpc_result, list):
        rpc_result = rpc_result[0] if rpc_result else False
    if isinstance(rpc_result, dict):
        rpc_result = next(iter(rpc_result.values()), False)

    return {
        "tenant_id": tenant_id,
        "archive_path": archive_path,
        "archive_counts": counts,
        "total_archived_rows": total_archived,
        "rpc_result": bool(rpc_result),
    }


def list_tenants_pending_hard_delete(sb: Any, limit: int = 50) -> list[dict[str, Any]]:
    """Invocado por worker cron — lista tenants cuyo grace period expiró
    y aún no fueron hard-deleted.

    Returns lista de dicts con tenant_id, deletion_scheduled_for,
    deletion_requested_at, grace_period_days. Lista vacía si Fase 2
    migration no aplicada (gate gracioso).
    """
    try:
        res = sb.rpc(
            "fn_list_tenants_pending_hard_delete",
            {"p_limit": limit},
        ).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "does not exist" in msg or "fn_list_tenants_pending_hard_delete" in msg:
            logger.warning(
                "[OFFBOARDING] fn_list_tenants_pending_hard_delete no disponible "
                "(Fase 2 migration pendiente). Hard-delete cron desactivado."
            )
            return []
        logger.error("[OFFBOARDING] Error listing pending tenants: %s", exc)
        return []

    rows = res.data or []
    return rows if isinstance(rows, list) else []

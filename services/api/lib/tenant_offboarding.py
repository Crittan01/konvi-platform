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

def hard_delete_tenant(sb: Any, tenant_id: str) -> dict[str, int]:
    """Ejecuta hard-delete del tenant. Invocada por cron worker tras
    grace_period vencido (deletion_scheduled_for <= NOW + deleted_at IS NULL).

    NO exponer en endpoint HTTP — solo cron job autorizado.

    Flujo:
      1. Snapshot de ARCHIVE_BEFORE_HARD_DELETE a Storage 'offboarding-archive'
         con retention 5y (Art. 22 deber custodia).
      2. DELETE FROM tenants WHERE id = tenant_id — CASCADE limpia el resto.
      3. Marca tenants.deleted_at = NOW() vía RPC (pero como CASCADE borra
         la fila tenants, el log queda en tenant_offboarding_log que NO
         cascade).
      4. Log evento 'hard_deleted' en tenant_offboarding_log.

    Returns dict con conteo de filas archivadas por tabla.

    FASE 2 / TODO: implementar archive a Storage bucket + ejecución real
    del DELETE. Por ahora esta función es stub que solo loguea — el cron
    worker no debe ejecutarla hasta que esté completa.
    """
    raise NotImplementedError(
        "hard_delete_tenant pendiente implementación Fase 2. "
        "Requiere: (1) Storage bucket 'offboarding-archive' creado, "
        "(2) función de snapshot a bucket, (3) DELETE FROM tenants con "
        "verificación FK CASCADE completa, (4) trigger NOTIFY post-delete. "
        "Ver docs/refactor/0005-tenant-offboarding-phase-2.md (TODO)."
    )

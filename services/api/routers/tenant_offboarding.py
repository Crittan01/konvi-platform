"""Tenant offboarding endpoints (rev. 109 J.2.4.4).

Endpoints HTTP del lifecycle de cierre de cuenta del tenant cumpliendo
Habeas Data Ley 1581 Art. 16 (derecho de eliminación) + Art. 22 (custodia
trazabilidad post-cierre).

Endpoints:
  GET  /api/v1/tenant/offboarding/status            — estado del offboarding
  POST /api/v1/tenant/offboarding/export            — descarga JSON portabilidad
  POST /api/v1/tenant/offboarding/request-deletion  — inicia soft-delete + 30d
  POST /api/v1/tenant/offboarding/cancel-deletion   — revierte soft-delete

Auth: solo role=owner del tenant (NO manager, NO operator). Verificación
en cada endpoint vía dependencies.auth.require_write_role + check manual
de role='owner' en tenant_users.

Rate-limit: export es 1/hora por tenant (heavy I/O). request-deletion es
1/día (cualquier operador no técnico se daría cuenta antes de pedir varias).

Audit: cada acción registra en tenant_offboarding_log (append-only, sobrevive
hard-delete por FK NO CASCADE — Art. 22 custodia).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import (
    _extract_jwt_payload,  # type: ignore
    enforce_mfa,
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.security import (
    RL_OFFBOARDING_DELETION,
    RL_OFFBOARDING_EXPORT,
    RL_WRITE_DEFAULT,
)
from lib.tenant_offboarding import (
    TenantOffboardingError,
    cancel_tenant_deletion,
    export_tenant_data,
    get_offboarding_status,
    request_tenant_deletion,
)

logger = logging.getLogger("api.tenant_offboarding")
router = APIRouter(tags=["Tenant Offboarding"])


# ─── Helpers ────────────────────────────────────────────────────────────────


def _actor_from_request(request: Request) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Devuelve (user_id, user_email, ip) del JWT + headers."""
    try:
        payload = _extract_jwt_payload(request)
        user_id = payload.get("sub")
        email = payload.get("email")
    except Exception:
        user_id, email = None, None
    ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )
    return user_id, email, ip


def _require_owner(sb: Client, tenant_id: str, user_id: Optional[str]) -> None:
    """Verifica que el actor sea OWNER del tenant. Manager/operator NO pueden
    iniciar offboarding."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    try:
        res = (
            sb.table("tenant_users")
            .select("role")
            .eq("tenant_id", tenant_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("[OFFBOARDING] Error verificando role: %s", exc)
        raise HTTPException(status_code=503, detail="DB no disponible")
    rows = res.data or []
    if not rows or rows[0].get("role") != "owner":
        raise HTTPException(
            status_code=403,
            detail=(
                "Solo el dueño de la cuenta (role=owner) puede gestionar el "
                "offboarding. Pídeselo al titular."
            ),
        )


# ─── Models ─────────────────────────────────────────────────────────────────


class RequestDeletionBody(BaseModel):
    confirmation_phrase: str = Field(
        ...,
        description=(
            "Debe ser exactamente 'ELIMINAR <tenant_name>' (anti-fat-finger). "
            "El nombre del tenant es visible en Settings → Empresa."
        ),
    )
    reason: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Razón textual del cierre (obligatoria por compliance).",
    )


class CancelDeletionBody(BaseModel):
    confirm: bool = Field(
        ...,
        description="Confirmación explícita de cancelación. Debe ser true.",
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/status")
async def offboarding_status(
    tenant_id: str = Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
):
    """Estado actual del offboarding para el tenant del JWT.

    Open a authenticated users (no requiere owner — manager/operator deben
    poder ver si la cuenta está en grace period para no asumir que sigue
    activa).
    """
    try:
        return get_offboarding_status(sb, tenant_id)
    except TenantOffboardingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/export", dependencies=[Depends(RL_OFFBOARDING_EXPORT), Depends(enforce_mfa)])
async def export_data(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
    _writer=Depends(require_write_role),
):
    """Genera export JSON portabilidad Habeas Data Ley 1581 Art. 19.

    Owner-only. Rate-limited a 1/hora por tenant (RL_OFFBOARDING_EXPORT):
    el export es heavy I/O y no debe ser invocable en ráfaga.
    Devuelve JSON inline (no streaming aún — Fase 2 si tenants crecen >100k
    filas y bajamos a chunked download zip).

    Cada export se loguea en tenant_offboarding_log con event='exported'.
    """
    user_id, user_email, ip = _actor_from_request(request)
    _require_owner(sb, tenant_id, user_id)

    try:
        payload = export_tenant_data(sb, tenant_id, requester_email=user_email)
    except TenantOffboardingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Log evento (best-effort, no debe bloquear el export).
    try:
        sb.rpc(
            "fn_log_tenant_offboarding_event",
            {
                "p_tenant_id": tenant_id,
                "p_event": "exported",
                "p_actor_user_id": user_id,
                "p_actor_email": user_email,
                "p_actor_ip": ip,
                "p_evidence": {
                    "total_rows": payload["summary"]["total_rows_exported"],
                    "truncated_tables": payload["summary"]["truncated_tables"],
                },
            },
        ).execute()
    except Exception as exc:
        logger.warning(
            "[OFFBOARDING] No se pudo loguear evento 'exported' "
            "tenant=%s: %s (no bloquea respuesta)",
            tenant_id, exc,
        )

    return payload


@router.post("/request-deletion", dependencies=[Depends(RL_OFFBOARDING_DELETION), Depends(enforce_mfa)])
async def request_deletion(
    body: RequestDeletionBody,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
    _writer=Depends(require_write_role),
):
    """Inicia soft-delete del tenant con 30d de grace period.

    Owner-only. Requiere confirmation_phrase = 'ELIMINAR <tenant_name>'
    EXACTO (anti-fat-finger). Razón textual obligatoria (compliance).

    Tras 30d, cron worker ejecuta hard-delete (CASCADE + archive de audit).
    Cancelable vía /cancel-deletion mientras grace > now.
    """
    user_id, user_email, ip = _actor_from_request(request)
    _require_owner(sb, tenant_id, user_id)

    # Leer nombre del tenant para validar confirmation_phrase.
    try:
        tenant_res = (
            sb.table("tenants")
            .select("name")
            .eq("id", tenant_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("[OFFBOARDING] Error DB leyendo tenant: %s", exc)
        raise HTTPException(status_code=503, detail="DB no disponible")
    if not tenant_res.data:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    tenant_name = tenant_res.data[0].get("name", "")

    expected_phrase = f"ELIMINAR {tenant_name}".strip()
    if body.confirmation_phrase.strip() != expected_phrase:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Frase de confirmación inválida. Esperada exactamente: "
                f"'{expected_phrase}'. Esta protección es intencional para "
                f"evitar eliminación accidental."
            ),
        )

    try:
        scheduled_for = request_tenant_deletion(
            sb,
            tenant_id=tenant_id,
            actor_user_id=user_id or "",
            actor_email=user_email or "",
            actor_ip=ip,
            reason=body.reason,
        )
    except TenantOffboardingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "ok": True,
        "scheduled_for": scheduled_for.isoformat(),
        "message": (
            f"Cuenta programada para eliminación el {scheduled_for.isoformat()}. "
            f"Mientras tanto la cuenta queda en modo lectura-solo. Puedes "
            f"cancelar via /cancel-deletion. Tus credenciales de integraciones "
            f"(Wompi/Aveonline/MeLi/Meta/Telegram) fueron invalidadas — si cancelas, "
            f"deberás reconectarlas."
        ),
    }


@router.post("/cancel-deletion", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def cancel_deletion(
    body: CancelDeletionBody,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
    _writer=Depends(require_write_role),
):
    """Cancela soft-delete dentro del grace period.

    Owner-only. NO restaura credenciales invalidadas (decisión consciente
    de seguridad: si el secret estuvo "out" durante el grace period, mejor
    rotar). El owner debe re-conectar integraciones vía UI Settings.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm debe ser true para cancelar la eliminación.",
        )

    user_id, user_email, ip = _actor_from_request(request)
    _require_owner(sb, tenant_id, user_id)

    try:
        was_cancelled = cancel_tenant_deletion(
            sb,
            tenant_id=tenant_id,
            actor_user_id=user_id or "",
            actor_email=user_email or "",
            actor_ip=ip,
        )
    except TenantOffboardingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not was_cancelled:
        return {
            "ok": False,
            "message": "No había una solicitud de eliminación pendiente para este tenant.",
        }

    return {
        "ok": True,
        "message": (
            "Eliminación cancelada. La cuenta vuelve a estar activa, pero "
            "debes re-conectar las integraciones (Wompi/Aveonline/MeLi/Meta/"
            "Telegram) desde Settings → Integraciones. Es por seguridad: los "
            "secrets pueden haber sido expuestos durante el grace period."
        ),
    }

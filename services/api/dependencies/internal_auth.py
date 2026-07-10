"""
Service-to-service authentication entre servicios internos Konvi.

A0.2c 2026-05-31 — reemplazo del truco JWT HS256 (que firmaba un token
impersonando usuario authenticated) por shared secret simple + tenant_id
explícito en header.

Patrón:
  - Servicios internos (orchestrator → api) envían header X-Internal-Service-Secret
    + X-Tenant-Id en cada request.
  - api valida con `hmac.compare_digest` (timing-attack safe).
  - tenant_id se extrae del header, NO del JWT.

Trust boundary: ambos servicios viven en la misma red Render (no Internet),
así que el shared secret + HTTPS basta. Para extender a clients públicos
externos hay que usar JWT firmado u OAuth — fuera de scope.

INTERNAL_SERVICE_SECRET se genera con `openssl rand -hex 32` y vive en
env vars de api + orchestrator (MISMO valor en ambos).
"""
import hmac
import logging
import os

from fastapi import Depends, HTTPException, Request
from supabase import Client

from dependencies.auth import (
    _get_service_client,
    enforce_mfa,
    get_current_role,
    get_current_tenant,
)

logger = logging.getLogger(__name__)

INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")


def _verify_internal_secret(req: Request) -> bool:
    """Compara header X-Internal-Service-Secret con env var (constant-time).

    Retorna True si match, False si missing/wrong.
    """
    sent = req.headers.get("X-Internal-Service-Secret", "")
    if not sent or not INTERNAL_SERVICE_SECRET:
        return False
    return hmac.compare_digest(sent, INTERNAL_SERVICE_SECRET)


async def get_tenant_id_internal_or_user(request: Request) -> str:
    """Dependencia FastAPI dual-auth: internal-secret O JWT user.

    Resolución:
      1. Si request trae header X-Internal-Service-Secret válido + X-Tenant-Id
         → retorna ese tenant_id (service-to-service path).
      2. Else → cae a flujo normal `get_current_tenant` (JWT user del Tenant Console).

    Usar en endpoints invocados desde AMBOS contextos (orchestrator + frontend),
    como /api/v1/orders, /orders/{id}/payment-link, /shipping/quote.
    """
    if _verify_internal_secret(request):
        tenant_id = request.headers.get("X-Tenant-Id", "")
        if not tenant_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "MISSING_TENANT_ID",
                    "msg": "X-Tenant-Id header requerido para auth internal-service",
                },
            )
        return tenant_id

    # Fallback: flujo JWT user normal
    return await get_current_tenant(request)


async def get_role_internal_or_user(request: Request) -> str:
    """Dependencia dual-auth para role.

    Si internal-secret: retorna 'owner' (servicio interno tiene permisos plenos).
    Else: cae a get_current_role.
    """
    if _verify_internal_secret(request):
        return "owner"
    return await get_current_role(request)


async def require_write_internal_or_user(
    role: str = Depends(get_role_internal_or_user),
) -> str:
    """Equivalente a require_write_role pero acepta internal-secret."""
    if role not in {"owner", "manager"}:
        raise HTTPException(
            status_code=403,
            detail=f"Permiso insuficiente (rol: {role})",
        )
    return role


async def get_service_client_internal_or_user(
    tenant_id: str = Depends(get_tenant_id_internal_or_user),
) -> Client:
    """Cliente service_role con tenant resuelto via internal-or-user."""
    return _get_service_client()


async def enforce_mfa_internal_or_user(request: Request) -> None:
    """MFA gate para endpoints dual-auth (BLOQUE 0).

    NO-OP en llamadas service-to-service (X-Internal-Service-Secret válido → el
    orchestrator/bot es de confianza y no tiene sesión MFA). Para llamadas de
    usuario (JWT), aplica enforce_mfa normal (AAL2 si el user tiene factor).
    Usar en endpoints money-movement invocados por AMBOS (ej. /orders/{id}/payment-link)."""
    if _verify_internal_secret(request):
        return
    await enforce_mfa(request)

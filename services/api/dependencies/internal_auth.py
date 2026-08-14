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
import uuid

from fastapi import Depends, HTTPException, Request
from supabase import Client

from dependencies.auth import (
    _get_service_client,
    enforce_mfa,
    get_current_role,
    get_current_tenant,
)

logger = logging.getLogger(__name__)

from config import get_settings as _get_settings  # G13: fuente única de config

INTERNAL_SERVICE_SECRET = _get_settings().INTERNAL_SERVICE_SECRET
# Rotación sin-caída (docs/operations/runbooks/credential-rotation.md): durante
# la ventana de rotación, el secret SALIENTE se publica en esta var y ambos se
# aceptan. Fuera de la ventana debe estar VACÍA — un solo secreto activo es la
# postura (no se documenta en render.yaml a propósito: es efímera por diseño).
# Nota G13: el ATRIBUTO de módulo se conserva como punto de lectura — los tests
# lo parchean aquí (patch.object) y ese contrato no cambia.
INTERNAL_SERVICE_SECRET_PREVIOUS = _get_settings().INTERNAL_SERVICE_SECRET_PREVIOUS


def _verify_internal_secret(req: Request) -> bool:
    """Compara header X-Internal-Service-Secret con env var (constant-time).

    Retorna True si match con el secret vigente (o con PREVIOUS durante la
    ventana de rotación), False si missing/wrong/sin configurar.
    """
    sent = req.headers.get("X-Internal-Service-Secret", "")
    if not sent or not INTERNAL_SERVICE_SECRET:
        return False
    if hmac.compare_digest(sent, INTERNAL_SERVICE_SECRET):
        return True
    return bool(INTERNAL_SERVICE_SECRET_PREVIOUS) and hmac.compare_digest(
        sent, INTERNAL_SERVICE_SECRET_PREVIOUS
    )


def _audit_internal_call(
    request: Request, *, tenant_id: str, outcome: str, status_code: int,
) -> None:
    """A12 (auditoría 2026-08-02) — trail del path dual-auth internal-secret.

    Antes: una llamada con X-Internal-Service-Secret válido + X-Tenant-Id
    AUTODECLARADO actuaba como cualquier tenant con rol owner SIN dejar rastro
    (única barrera = el secret). Ahora cada llamada internal autenticada deja
    fila en `api_security_events` (misma tabla que rate-limit/idempotency, vía
    dependencies.observability.record_api_security_event): tenant declarado,
    path, método, resultado y user-agent (no hay header de service-name; el UA
    es la mejor señal disponible del llamante).

    Best-effort / fail-open (paridad con el resto de security logging del
    repo): un fallo de auditoría NUNCA rompe la request. La fila exige
    tenant_id UUID válido (FK a tenants) — si el header trae basura, el
    intento queda solo en logs (el insert fallaría la FK de todas formas).
    """
    try:
        uuid.UUID(str(tenant_id))  # guard FK: api_security_events.tenant_id → tenants
    except (ValueError, TypeError, AttributeError):
        return
    try:
        from dependencies.observability import record_api_security_event
        record_api_security_event(
            supabase=_get_service_client(),
            tenant_id=tenant_id,
            event_type=f"internal_auth.{outcome}",
            status_code=status_code,
            request=request,
            metadata={
                "auth": "internal_secret",
                "user_agent": (request.headers.get("user-agent") or "")[:200],
            },
        )
    except Exception as exc:
        logger.warning("[INTERNAL_AUTH] audit event falló (%s): %s", outcome, exc)


async def require_internal_service(request: Request) -> None:
    """Guard para endpoints SOLO service-to-service (sin fallback JWT, sin tenant).

    A diferencia de `get_tenant_id_internal_or_user` (dual-auth con X-Tenant-Id
    obligatorio), esta dependencia es para endpoints de mantenimiento CROSS-TENANT
    invocados únicamente por otro servicio Konvi (ej. el worker del orchestrator
    llamando /api/v1/internal/meli/refresh-tokens): no hay tenant declarado y un
    JWT de usuario NUNCA debe autorizar el barrido.

    401 tanto si falta como si es incorrecto (no se filtra cuál de los dos falló).
    """
    if not _verify_internal_secret(request):
        logger.warning(
            "[INTERNAL_AUTH] endpoint internal-only sin secret válido — 401 "
            "path=%s method=%s ua=%s",
            request.url.path, request.method,
            (request.headers.get("user-agent") or "")[:100],
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "INTERNAL_AUTH_REQUIRED", "msg": "X-Internal-Service-Secret inválido o ausente"},
        )


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
            # Denegado: secret válido pero sin tenant declarado. No hay fila
            # posible en api_security_events (tenant_id NOT NULL FK) → el
            # trail de este 400 queda en logs.
            logger.warning(
                "[INTERNAL_AUTH] secret válido SIN X-Tenant-Id — 400 "
                "path=%s method=%s ua=%s",
                request.url.path, request.method,
                (request.headers.get("user-agent") or "")[:100],
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "MISSING_TENANT_ID",
                    "msg": "X-Tenant-Id header requerido para auth internal-service",
                },
            )
        _audit_internal_call(request, tenant_id=tenant_id, outcome="ok", status_code=200)
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

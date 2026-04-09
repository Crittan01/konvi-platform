"""
Dependencia de autenticación y contexto de tenant.

Valida el JWT de Supabase, extrae tenant_id y role del custom claim app_metadata,
y registra el contexto en el cliente de Supabase para que RLS aplique.

Referencia oficial Supabase JWT:
  https://supabase.com/docs/guides/auth/jwts
"""
import os
import logging
from typing import Optional
from fastapi import Request, HTTPException, Depends
import jwt  # PyJWT
from supabase import create_client, Client

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# Roles con permiso de escritura
WRITE_ROLES = {"owner", "manager"}


def _get_service_client() -> Client:
    """Cliente con service_role para operaciones que requieren bypass de RLS."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _decode_supabase_jwt(token: str) -> Optional[dict]:
    """
    Decodifica y valida el JWT emitido por Supabase Auth.
    Retorna el payload completo si es válido, None si no.
    """
    if not SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET no configurado")
        return None
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT expirado")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning("JWT inválido: %s", e)
        return None


def _extract_jwt_payload(request: Request) -> dict:
    """
    Extrae y valida el JWT del header Authorization.
    Lanza 401 si falta o es inválido.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header faltante o inválido")

    token = auth_header.split(" ", 1)[1]
    payload = _decode_supabase_jwt(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    return payload


async def get_current_tenant(request: Request) -> str:
    """
    Dependencia FastAPI que extrae y valida el tenant_id del JWT.
    El tenant_id se inyecta en app_metadata vía trigger handle_new_user_claims.
    """
    payload = _extract_jwt_payload(request)
    app_metadata = payload.get("app_metadata") or {}
    tenant_id: Optional[str] = app_metadata.get("tenant_id")

    if not tenant_id:
        logger.error("JWT sin tenant_id en app_metadata. sub=%s", payload.get("sub"))
        raise HTTPException(status_code=403, detail="Contexto de tenant no encontrado en el token")

    return tenant_id


async def get_current_role(request: Request) -> str:
    """
    Dependencia FastAPI que extrae el role del JWT.
    Roles válidos: owner, manager, agent.
    Si no hay role en app_metadata, retorna 'agent' (mínimo privilegio).
    """
    payload = _extract_jwt_payload(request)
    app_metadata = payload.get("app_metadata") or {}
    role: str = app_metadata.get("role", "agent")
    return role


async def require_write_role(role: str = Depends(get_current_role)) -> str:
    """
    Dependencia que exige role owner o manager.
    Lanza 403 si el role es agent.
    """
    if role not in WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Permiso insuficiente. Se requiere owner o manager (rol actual: {role})"
        )
    return role


async def get_service_client(tenant_id: str = Depends(get_current_tenant)) -> Client:
    """
    Retorna un cliente Supabase con service_role autenticado.
    Setea app.current_tenant_id para que RLS opere via app_current_tenant().
    """
    client = _get_service_client()
    try:
        client.rpc("set_config", {
            "parameter": "app.current_tenant_id",
            "value": tenant_id,
            "is_local": True,
        }).execute()
    except Exception as e:
        logger.warning("No se pudo setear app.current_tenant_id: %s", e)
    return client

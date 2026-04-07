"""
Dependencia de autenticación y contexto de tenant.

Valida el JWT de Supabase, extrae el tenant_id del custom claim,
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


async def get_current_tenant(request: Request) -> str:
    """
    Dependencia FastAPI que:
    1. Extrae el Bearer token del header Authorization
    2. Valida el JWT contra el secreto de Supabase
    3. Extrae tenant_id del custom claim `app_metadata.tenant_id`
    4. Lanza 401/403 si falla cualquier paso

    El tenant_id retornado es de confianza para usar en queries
    como filtro adicional (defensa en profundidad — RLS es la barrera final).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header faltante o inválido")

    token = auth_header.split(" ", 1)[1]
    payload = _decode_supabase_jwt(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    # El tenant_id se inyecta en el JWT via trigger de Supabase (migration 20260406181239)
    app_metadata = payload.get("app_metadata") or {}
    tenant_id: Optional[str] = app_metadata.get("tenant_id")

    if not tenant_id:
        logger.error("JWT sin tenant_id en app_metadata. sub=%s", payload.get("sub"))
        raise HTTPException(status_code=403, detail="Contexto de tenant no encontrado en el token")

    return tenant_id


async def get_service_client(tenant_id: str = Depends(get_current_tenant)) -> Client:
    """
    Retorna un cliente Supabase con service_role autenticado.
    Usar cuando se necesita hacer SET de la variable de sesión para RLS.

    Nota: Para producción, usar el cliente con el JWT del usuario directamente
    (Supabase client con access_token) para que RLS opere nativamente.
    """
    client = _get_service_client()
    # Setear el contexto del tenant para que app_current_tenant() en RLS lo resuelva
    try:
        client.rpc("set_config", {
            "parameter": "app.current_tenant_id",
            "value": tenant_id,
            "is_local": True,
        }).execute()
    except Exception as e:
        logger.warning("No se pudo setear app.current_tenant_id: %s", e)
    return client

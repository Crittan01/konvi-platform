"""
Dependencia de autenticación y contexto de tenant.

Valida el JWT de Supabase, extrae tenant_id y role del custom claim app_metadata,
y entrega un cliente service_role para operaciones de backend.

IMPORTANTE:
- service_role puede bypassar RLS.
- El aislamiento multi-tenant en runtime depende de filtros explícitos por tenant_id
  en cada query sensible (defensa en profundidad).
- app.current_tenant_id se mantiene para funciones SQL que lo utilizan.

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

# Roles runtime
RUNTIME_ROLES = {"owner", "manager", "operator"}

# Roles con permiso de escritura
WRITE_ROLES = {"owner", "manager"}


def _get_service_client() -> Client:
    """Cliente con service_role para operaciones que requieren bypass de RLS."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _decode_supabase_jwt(token: str) -> Optional[dict]:
    """
    Decodifica y valida el JWT. Si es HS256 (local/default) usa el SECRET.
    Si es ES256 (nuevo default de Supabase Cloud), delega a supabase.auth.get_user
    para confirmación criptográfica en su infraestructura y luego decodifica.
    """
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "HS256")

    if alg == "HS256":
        if not SUPABASE_JWT_SECRET:
            logger.error("SUPABASE_JWT_SECRET no configurado")
            return None
        try:
            return jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        except Exception as e:
            logger.warning("HS256 JWT inválido: %s", e)
            return None
    else:
        # Para ES256 / RS256, delegamos validación al servidor de Supabase
        sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) # admin client
        try:
            # Validates against Supabase server
            user_res = sb.auth.get_user(token)
            if not user_res.user:
                return None
            # Return unverified payload since Supabase just verified the real token
            return jwt.decode(token, options={"verify_signature": False})
        except Exception as e:
            logger.warning("Validación delegada a Supabase falló para ES256: %s", e)
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
    Roles runtime válidos: owner, manager, operator.
    Si no hay role o es inválido, retorna 'operator' (mínimo privilegio runtime).
    """
    payload = _extract_jwt_payload(request)
    app_metadata = payload.get("app_metadata") or {}
    role = app_metadata.get("role", "operator")
    if role not in RUNTIME_ROLES:
        role = "operator"
    return role


async def require_write_role(role: str = Depends(get_current_role)) -> str:
    """
    Dependencia que exige role owner o manager.
    Lanza 403 si el role es operator.
    """
    if role not in WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Permiso insuficiente. Se requiere owner o manager (rol actual: {role})"
        )
    return role


async def require_owner_role(role: str = Depends(get_current_role)) -> str:
    """
    Dependencia que exige role owner exclusivamente.
    Usar para operaciones de configuración crítica: editar tenant, gestionar equipo.
    Lanza 403 si el role es manager u operator.
    """
    if role != "owner":
        raise HTTPException(
            status_code=403,
            detail=f"Permiso insuficiente. Se requiere owner (rol actual: {role})"
        )
    return role


async def get_service_client(tenant_id: str = Depends(get_current_tenant)) -> Client:
    """
    Retorna un cliente Supabase con service_role autenticado.
    Setea app.current_tenant_id para funciones SQL que dependen de app_current_tenant().
    Nota: service_role puede bypassar RLS; por eso todas las queries deben filtrar
    tenant_id explícitamente en runtime.
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

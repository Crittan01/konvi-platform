"""
Dependencia de autenticación y contexto de tenant.

Valida el JWT de Supabase (sistema NUEVO Asymmetric Signing Keys ES256, fallback
opcional HS256 legacy), extrae tenant_id y role del custom claim app_metadata,
y entrega un cliente service_role para operaciones de backend.

A0.2b 2026-05-31 — migración a JWKS asymmetric:
- Default: ES256 con JWKS endpoint público (sin shared secret).
- Fallback HS256 con SUPABASE_JWT_SECRET legacy SOLO si la var está presente
  (sesiones HS256 vigentes pre-migración). Sin la var, ES256-only.

IMPORTANTE:
- service_role puede bypassar RLS.
- El aislamiento multi-tenant en runtime depende de filtros explícitos por tenant_id
  en cada query sensible (defensa en profundidad).
- app.current_tenant_id se mantiene para funciones SQL que lo utilizan.

Referencia oficial Supabase:
  https://supabase.com/docs/guides/auth/jwts
  https://supabase.com/docs/guides/auth/signing-keys
"""
import logging
import os
from typing import Optional

import jwt  # PyJWT 2.5+ con PyJWKClient
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient
from supabase import Client, create_client

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
# Nuevo nombre canónico Publishable+Secret keys (fallback al legacy
# SUPABASE_SERVICE_ROLE_KEY durante transición A0.2c).
SUPABASE_SERVICE_KEY = (
    os.getenv("SUPABASE_SECRET_KEY", "")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
)
# Legacy HS256 secret — opcional. Si está, se usa como fallback para sesiones
# pre-migración. Si no, solo ES256 (sistema nuevo asymmetric).
_LEGACY_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# JWKS client — cache de signing keys, TTL 1h. Rotación de keys Supabase
# es manejada automáticamente por PyJWKClient (re-fetch al miss kid).
_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else ""
_jwks_client: Optional[PyJWKClient] = (
    PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=3600) if _JWKS_URL else None
)

# Roles runtime
RUNTIME_ROLES = {"owner", "manager", "operator"}

# Roles con permiso de escritura
WRITE_ROLES = {"owner", "manager"}


# F7 — copy RBAC canónico (single source of truth). Otros routers con literales
# inline (integrations.py, settings.py, …) deberían importar estos helpers para
# eliminar el drift de mensajes; se centralizan aquí primero.
def msg_require_write_role(role: str) -> str:
    return f"Permiso insuficiente. Se requiere owner o manager (rol actual: {role})"


def msg_require_owner_role(role: str) -> str:
    return f"Permiso insuficiente. Se requiere owner (rol actual: {role})"


def _get_service_client() -> Client:
    """Cliente con service_role/secret para operaciones que requieren bypass de RLS."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _decode_supabase_jwt(token: str) -> Optional[dict]:
    """Valida JWT Supabase Auth.

    Estrategia:
      1. Inspeccionar header.alg.
      2. Si ES256/RS256 (sistema NUEVO asymmetric): verificar con JWKS endpoint
         + signing key (sin shared secret).
      3. Si HS256 (sistema LEGACY): verificar con SUPABASE_JWT_SECRET shared.
         Sin la var → reject (sesión legacy ya expirada o sistema migrado).

    Retorna payload decodificado o None si inválido.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as e:
        logger.warning("JWT header no parseable: %s", e)
        return None

    alg = header.get("alg", "")

    if alg in ("ES256", "RS256"):
        if not _jwks_client:
            logger.error(
                "JWKS endpoint no configurado (NEXT_PUBLIC_SUPABASE_URL ausente)"
            )
            return None
        try:
            signing_key = _jwks_client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=[alg],
                audience="authenticated",
            )
        except Exception as e:
            logger.warning("JWKS %s JWT inválido: %s", alg, e)
            return None

    if alg == "HS256":
        if not _LEGACY_JWT_SECRET:
            # Sistema migró a asymmetric — tokens HS256 viejos ya no se aceptan.
            logger.info(
                "HS256 token rechazado: SUPABASE_JWT_SECRET no configurado "
                "(sistema migró a asymmetric keys)"
            )
            return None
        try:
            return jwt.decode(
                token,
                _LEGACY_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except Exception as e:
            logger.warning("HS256 legacy JWT inválido: %s", e)
            return None

    logger.warning("Algoritmo JWT no soportado: %s", alg)
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
        raise HTTPException(status_code=403, detail=msg_require_write_role(role))
    return role


async def require_owner_role(role: str = Depends(get_current_role)) -> str:
    """
    Dependencia que exige role owner exclusivamente.
    Usar para operaciones de configuración crítica: editar tenant, gestionar equipo.
    Lanza 403 si el role es manager u operator.
    """
    if role != "owner":
        raise HTTPException(status_code=403, detail=msg_require_owner_role(role))
    return role


async def get_service_client(tenant_id: str = Depends(get_current_tenant)) -> Client:
    """
    Retorna un cliente Supabase con service_role para el tenant autenticado.
    service_role bypasa RLS — toda query debe filtrar tenant_id explícitamente.
    """
    return _get_service_client()


async def reject_if_tenant_deleting(
    request: Request,
) -> str:
    """Rev. 109 J.2.4.4 Fase 2 — middleware lectura-solo durante offboarding.

    Rechaza writes con HTTP 423 Locked si el tenant tiene
    `deletion_requested_at IS NOT NULL` Y `deleted_at IS NULL` (en grace period).

    NO aplicar a:
      - GET/HEAD/OPTIONS requests (read-only tolerable durante grace) —
        skip automático sin DB query.
      - Endpoints de offboarding (cancel-deletion, status) — el owner DEBE
        poder cancelar dentro del grace. Se excluyen por NO aplicar este
        Depends al router de tenant_offboarding.

    APLICAR como Depends en include_router() de routers de mutación
    (orders, conversations, contacts, products, settings, integrations,
    claims, purchases, marketplace, ai_agents, knowledge_base, shipping).

    A11 UAT 2026-06-25 (BUG_REAL): la resolución de tenant usa DUAL-AUTH
    (`get_tenant_id_internal_or_user`), NO solo JWT. Estos routers también
    reciben escrituras service-to-service del orchestrator (crear orden,
    payment-link, shipping). Con `get_current_tenant` (JWT-only) toda llamada
    interna recibía 401 ANTES del internal-auth del endpoint — rompía el flujo
    de pago del bot. El gate de offboarding igual aplica al tenant resuelto
    (el bot tampoco debe escribir durante grace). Import lazy evita el ciclo
    auth.py ↔ internal_auth.py.

    Tras hard-delete (deleted_at NOT NULL), get_current_tenant ya retornaría
    error porque el JWT del usuario sigue válido pero la fila tenants no existe;
    Supabase queries con tenant_id=X fallan silently con 0 rows. Este middleware
    NO cubre ese caso post-delete (el JWT debería re-emitirse).
    """
    from dependencies.internal_auth import get_tenant_id_internal_or_user
    tenant_id = await get_tenant_id_internal_or_user(request)

    # Fix audit 2026-05-29: skip GET/HEAD/OPTIONS automáticamente — no
    # tiene sentido bloquear reads durante grace + ahorra 1 query per req.
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return tenant_id

    sb = _get_service_client()
    try:
        res = (
            sb.table("tenants")
            .select("deletion_requested_at, deleted_at, deletion_scheduled_for")
            .eq("id", tenant_id)
            .limit(1)
            .execute()
        )
    except Exception:
        # Si la consulta falla (DB outage), NO bloquear writes — fail open
        # es menos malo que un degraded service. Sentry captura el error.
        return tenant_id

    rows = res.data or []
    if not rows:
        return tenant_id  # tenant no existe → otros guards lo rechazarán

    t = rows[0]
    if t.get("deleted_at") is not None:
        # Tenant ya hard-deleted — el JWT debería invalidarse. Defensa:
        raise HTTPException(
            status_code=410,  # Gone
            detail=(
                "Esta cuenta fue eliminada permanentemente. Si crees que es "
                "un error, contacta soporte con tu document_number."
            ),
        )
    if t.get("deletion_requested_at") is not None:
        scheduled = t.get("deletion_scheduled_for")
        raise HTTPException(
            status_code=423,  # Locked
            detail=(
                f"Esta cuenta está en proceso de eliminación (programada para "
                f"{scheduled}). No se permiten cambios. Si quieres cancelar, ve "
                f"a Settings → Cerrar cuenta y haz click en 'Cancelar eliminación'."
            ),
        )
    return tenant_id

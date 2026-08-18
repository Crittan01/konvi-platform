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

# ─── MFA OBLIGATORIO (D1/D2/D3, 2026-07-18) ────────────────────────────────
# Enforcement de ENROLAMIENTO — distinto del step-up de enforce_mfa. Los roles
# de escritura DEBEN tener un factor MFA verificado tras un periodo de gracia; si
# no, sus mutaciones se rechazan con 403 (los gates de rol lo invocan). Config por
# env para rollout SEGURO: deploy con ENABLED=false → notificar a usuarios → setear
# MFA_MANDATORY_START a la fecha del flip → poner ENABLED=true (todos reciben la
# gracia desde START). FAIL-OPEN ante outage del Auth admin (disponibilidad).
#   MFA_MANDATORY_ENABLED   — "true"/"false" (default false: no-op hasta el flip).
#   MFA_MANDATORY_GRACE_DAYS — días de gracia para enrolar (default 14).
#   MFA_MANDATORY_START      — fecha ISO piso; deadline = max(created_at, START)+gracia.
MFA_MANDATORY_ROLES = WRITE_ROLES  # D1: owner + manager (operator NO forzado)


def _mfa_mandatory_enabled() -> bool:
    """Lee el flag en runtime (permite rollout/rollback sin redeploy de código)."""
    return os.getenv("MFA_MANDATORY_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


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


async def get_current_user_id(request: Request) -> Optional[str]:
    """user_id (claim `sub`) del JWT — para trails de auditoría (ej. reversed_by)."""
    payload = _extract_jwt_payload(request)
    return payload.get("sub")


async def require_write_role(
    request: Request = None,
    role: str = Depends(get_current_role),
) -> str:
    """
    Dependencia que exige role owner o manager.
    Lanza 403 si el role es operator.
    MFA OBLIGATORIO (D1): tras la gracia, exige factor MFA verificado (403 si no).
    El `sub` se extrae del request SOLO cuando el enforcement está activo (no
    introduce dependencia auth nueva → no rompe tests que mockean get_current_role).
    """
    if role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail=msg_require_write_role(role))
    _enforce_mfa_enrollment_from_request(request, role)
    return role


async def require_owner_role(
    request: Request = None,
    role: str = Depends(get_current_role),
) -> str:
    """
    Dependencia que exige role owner exclusivamente.
    Usar para operaciones de configuración crítica: editar tenant, gestionar equipo.
    Lanza 403 si el role es manager u operator.
    MFA OBLIGATORIO (D1): tras la gracia, exige factor MFA verificado (403 si no).
    """
    if role != "owner":
        raise HTTPException(status_code=403, detail=msg_require_owner_role(role))
    _enforce_mfa_enrollment_from_request(request, role)
    return role


# ─── BLOQUE 0 · MFA enforcement en el gateway (P1, 2026-07-10) ──────────────
# El middleware de Next (F85) exige AAL2 en el servicio web, pero el gateway FastAPI
# público NO lo hacía → un access token AAL1 (password sin completar el 2º factor)
# podía operar contra la API directa, saltándose el MFA. enforce_mfa cierra el hueco:
# si el JWT es aal1 y el usuario TIENE un factor MFA verificado, rechaza 401.
_MFA_CACHE: dict = {}
_MFA_CACHE_TTL = 60.0  # segundos (evita consultar el Auth admin en cada request)


class _MfaLookupError(Exception):
    """El estado de MFA no se pudo determinar (outage del Auth admin). El caller decide
    fail-open (gate amplio) o fail-closed (operaciones crown-jewel)."""


def _lookup_mfa_state_cached(sub: str) -> tuple:
    """(has_verified_factor: bool, created_at_iso: Optional[str]) del usuario.
    Cacheado (TTL 60s) — UNA sola llamada al Auth admin sirve a enforce_mfa (step-up)
    Y a enforce_mfa_enrollment (obligatorio). RAISES _MfaLookupError si el lookup
    falla — NO decide política aquí (el caller elige fail-open/closed)."""
    import time
    now = time.time()
    hit = _MFA_CACHE.get(sub)
    if hit and hit[2] > now:
        return hit[0], hit[1]
    try:
        resp = _get_service_client().auth.admin.get_user_by_id(sub)
        user = getattr(resp, "user", None) or resp
        factors = getattr(user, "factors", None) or []
        def _status(f):
            return getattr(f, "status", None) or (f.get("status") if isinstance(f, dict) else None)
        has = any(_status(f) == "verified" for f in factors)
        created = getattr(user, "created_at", None)
        if created is not None and not isinstance(created, str):
            # datetime → ISO; cualquier otro tipo raro → None (no rompe el enforcement).
            created = getattr(created, "isoformat", lambda: None)()
    except Exception as exc:  # noqa: BLE001
        raise _MfaLookupError(str(exc)) from exc
    _MFA_CACHE[sub] = (has, created, now + _MFA_CACHE_TTL)
    return has, created


def _lookup_verified_mfa_cached(sub: str) -> bool:
    """¿El usuario tiene un factor MFA verificado? Cacheado (TTL 60s).
    RAISES _MfaLookupError si el lookup falla. Wrapper de _lookup_mfa_state_cached."""
    return _lookup_mfa_state_cached(sub)[0]


def _user_has_verified_mfa(sub: str) -> bool:
    """Wrapper FAIL-OPEN (contrato del gate amplio): ante error de lookup retorna False
    (no bloquear a quien no activó MFA por un outage; el gate primario es aal2 + web
    middleware). Para operaciones crown-jewel usar enforce_mfa_strict (fail-closed)."""
    try:
        return _lookup_verified_mfa_cached(sub)
    except _MfaLookupError as exc:
        logger.warning("[MFA] lookup de factores falló para sub=%s (%s) — fail-open", sub, exc)
        return False


def _within_mfa_grace(created_at_iso: Optional[str]) -> bool:
    """True si el usuario aún está dentro de la ventana de gracia para enrolar MFA.
    deadline = max(created_at, MFA_MANDATORY_START) + MFA_MANDATORY_GRACE_DAYS días.
    Sin ninguna ancla temporal parseable → conservador: True (no bloquear)."""
    from datetime import datetime, timedelta, timezone

    def _parse(s: Optional[str]):
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    anchors = [d for d in (_parse(created_at_iso), _parse(os.getenv("MFA_MANDATORY_START", ""))) if d]
    if not anchors:
        return True
    try:
        grace_days = int(os.getenv("MFA_MANDATORY_GRACE_DAYS", "14"))
    except ValueError:
        grace_days = 14
    deadline = max(anchors) + timedelta(days=grace_days)
    return datetime.now(timezone.utc) <= deadline


def _enforce_mfa_enrollment_for(role: str, sub: str) -> None:
    """Núcleo de MFA OBLIGATORIO (D1/D2/D3). Si el enforcement está activo, el rol
    está en MFA_MANDATORY_ROLES, el usuario NO tiene factor MFA verificado y venció
    la gracia → 403. FAIL-OPEN ante outage del lookup (disponibilidad: no encerrar a
    nadie por un blip del Auth admin; el gate de seguridad primario sigue siendo
    enforce_mfa/strict + el middleware web). aal2 no necesita chequeo: implica factor
    verificado → has_factor True lo deja pasar."""
    if not _mfa_mandatory_enabled():
        return
    if role not in MFA_MANDATORY_ROLES or not sub:
        return
    try:
        has_factor, created_at = _lookup_mfa_state_cached(sub)
    except _MfaLookupError as exc:
        logger.warning("[MFA obligatorio] lookup falló para sub=%s (%s) — fail-open", sub, exc)
        return
    if has_factor or _within_mfa_grace(created_at):
        return
    raise HTTPException(
        status_code=403,
        detail=("Tu cuenta requiere activar la verificación en dos pasos (MFA) para "
                "continuar. Actívala en Ajustes → Seguridad."),
    )


def _enforce_mfa_enrollment_from_request(request: Optional[Request], role: str) -> None:
    """Invocado por los gates de rol. Extrae el `sub` del JWT del request SOLO cuando
    el enforcement está activo — así con MFA off (default) NO toca el request y los
    tests que mockean solo get_current_role no reciben un 401 espurio. Resiliente a
    request None (llamada directa) o sin JWT (override en test) → sub vacío → no-op."""
    if not _mfa_mandatory_enabled():
        return
    sub = ""
    if request is not None:
        try:
            sub = _extract_jwt_payload(request).get("sub") or ""
        except HTTPException:
            sub = ""  # sin JWT resoluble → no encerrar (el 401 real lo da otro gate)
    _enforce_mfa_enrollment_for(role, sub)


async def enforce_mfa_enrollment(request: Request) -> None:
    """Dependencia standalone de MFA OBLIGATORIO — para endpoints que NO pasan por
    require_write_role/require_owner_role pero deben forzar enrolamiento. Los gates de
    rol ya invocan _enforce_mfa_enrollment_from_request; esta cubre el resto."""
    if not _mfa_mandatory_enabled():
        return
    payload = _extract_jwt_payload(request)
    app_metadata = payload.get("app_metadata") or {}
    role = app_metadata.get("role", "operator")
    if role not in RUNTIME_ROLES:
        role = "operator"
    _enforce_mfa_enrollment_for(role, payload.get("sub") or "")


async def enforce_mfa(request: Request) -> None:
    """Dependencia: exige AAL2 si el usuario tiene MFA verificado. Aplicar en routers
    sensibles (settings, team, integraciones, mutaciones owner). Si el user no tiene
    MFA, aal1 es aceptable (no rompe a quien no lo activó). FAIL-OPEN ante lookup caído."""
    payload = _extract_jwt_payload(request)
    aal = payload.get("aal") or "aal1"
    if aal == "aal2":
        return
    sub = payload.get("sub") or ""
    if sub and _user_has_verified_mfa(sub):
        raise HTTPException(
            status_code=401,
            detail=("Esta operación requiere verificación en dos pasos (MFA). "
                    "Inicia sesión completando el segundo factor."),
        )


async def enforce_mfa_strict(request: Request) -> None:
    """Variante FAIL-CLOSED para operaciones crown-jewel irreversibles (export de datos
    personales, borrado de cuenta). Igual que enforce_mfa PERO ante INCERTIDUMBRE —
    lookup del Auth admin caído, o JWT sin sub — DENIEGA (503/401) en vez de permitir:
    no se mueve dato sensible sin poder verificar el nivel de aseguramiento.

    Trade-off ACEPTADO: durante un outage del Auth admin estas rutas quedan bloqueadas
    para TODOS (son destructivas/irreversibles; mejor 503 que un export/borrado no
    verificado). Como enforce_mfa, NO fuerza MFA a quien no lo activó (aal1 sin factor
    verificado sigue permitido)."""
    payload = _extract_jwt_payload(request)
    aal = payload.get("aal") or "aal1"
    if aal == "aal2":
        return
    sub = payload.get("sub") or ""
    if not sub:
        raise HTTPException(status_code=401, detail="Sesión inválida: no se pudo verificar identidad.")
    try:
        has = _lookup_verified_mfa_cached(sub)
    except _MfaLookupError as exc:
        logger.error("[MFA strict] lookup falló para sub=%s (%s) — FAIL-CLOSED (503)", sub, exc)
        raise HTTPException(
            status_code=503,
            detail="No se pudo verificar el estado de MFA en este momento. Reintenta en unos segundos.",
        )
    if has:
        raise HTTPException(
            status_code=401,
            detail=("Esta operación sensible requiere verificación en dos pasos (MFA). "
                    "Inicia sesión completando el segundo factor."),
        )


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
        # es menos malo que un degraded service.
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

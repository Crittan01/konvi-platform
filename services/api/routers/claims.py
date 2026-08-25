"""
Router de Reclamos / Claims — ADAPTADOR HTTP sobre `konvi_domain.claims` (Track 5 M2.4).

La lógica de negocio vive en el paquete compartido (única fuente, contrato §5.1):
create unificado (reason cerrado + reason_detail + dedup + titularidad por actor),
get/list/list_by_contact, transition (FSM formalizada), reversión delegada en las
RPCs SECURITY DEFINER. Este router conserva EXACTAMENTE la seguridad heredada:
JWT (`get_current_tenant`), RBAC asimétrico G-4 (create = owner/manager/operator
SIN require_write_role; patch/resolve/reversion = owner/manager), rate-limit,
audit decorators y mapeo DomainError→HTTP.

Endpoints:
  GET    /api/v1/claims/                 — listar reclamos del tenant (con embeds)
  POST   /api/v1/claims/                 — crear reclamo (dedup → 200)  [owner, manager, operator]
  GET    /api/v1/claims/{id}             — detalle
  PATCH  /api/v1/claims/{id}             — cambiar status / resolution_notes   [owner, manager]
  POST   /api/v1/claims/{id}/resolve     — atajo: status=resolved + notas      [owner, manager]
  POST   /api/v1/claims/{id}/reversion   — radicar queja de reversión + constancia [owner, manager]
  GET    /api/v1/claims/{id}/reversion   — leer la constancia
  POST   /api/v1/claims/{id}/reversion/movimiento — registrar vía de devolución [owner, manager]

Estados válidos: open → investigating → resolved | refunded | rejected | cancelled
(canon único en `konvi_domain.claims.models` — los nombres históricos de este
módulo quedan como alias, patrón FSM de M2.1).

Coexistencia con orchestrator: el bot inserta claims via service_role direct
(`.table('claims').insert({'tenant_id': ..., ...})`), bypassa este router. Es
intencional (R4 — bot congelado hasta B-2/M3): ambos paths escriben a la misma
tabla y la duplicación queda con alarma (`tests/test_claims_policy_parity.py`).
RLS + tenant_id explícito mantiene aislamiento; patrón canónico
`.table(X).eq('tenant_id', tid)` enforced por lint AST scripts/audit_tenant_filter.py.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

# ── Capa de dominio compartida (Track 5 M2.4) ────────────────────────────────
from konvi_domain import Actor, Channel, DomainError, ErrorCode, Role
from konvi_domain.claims import (
    CLAIM_REASONS,
    CLAIM_REOPENABLE_STATUSES,
    CLAIM_STATUSES,
    CLAIM_TERMINAL_STATUSES,
    ClaimCreateInput,
    ClaimTransitionInput,
    ReversionInput,
)
from konvi_domain.claims import reversion as reversion_service
from konvi_domain.claims import service as claims_service
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.security import RL_WRITE_DEFAULT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Claims"])

# Aliases con los nombres históricos (los usan tests/consumidores del router —
# patrón alias de M2.1). La ÚNICA fuente es `konvi_domain.claims.models`:
# A4 finiquito (audit §3 BUG#2 CRITICAL) — vocabulario canónico alineado con la UI
# (claims-manager.tsx STATUS_MAP + botones Investigando/Reembolsar/Rechazar) y el
# tool agentic (espejo congelado, defendido por test de paridad) + CHECK
# constraint DB (migración 20260624010000).
VALID_STATUSES = CLAIM_STATUSES
TERMINAL_STATUSES = CLAIM_TERMINAL_STATUSES
REOPENABLE_STATUSES = CLAIM_REOPENABLE_STATUSES
# Vocabulario canónico de 'reason' (decisión founder 2026-08-25 #3 — espejo del
# REASON_MAP de la UI). La DB NO tiene CHECK sobre reason justamente para no
# romper la escritura libre del bot congelado (hasta B-2/M3).
VALID_REASONS = CLAIM_REASONS


# ── Adaptador HTTP ↔ capa de dominio (patrón M2.1) ───────────────────────────

_DOMAIN_ERROR_HTTP = {
    ErrorCode.VALIDATION: 422,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.PRECONDITION: 409,
    ErrorCode.UPSTREAM: 500,
    ErrorCode.TENANT_MISMATCH: 403,
}


def _domain_error_to_http(exc: DomainError) -> HTTPException:
    """Mapeo único DomainError → HTTPException (mismos status/detalle heredados).
    `exc.http_status` overridea cuando el dominio conoce el status exacto (la
    tabla _MOTIVO_HTTP de la reversión: 404/409/422 según el motivo)."""
    return HTTPException(
        status_code=exc.http_status or _DOMAIN_ERROR_HTTP.get(exc.code, 500),
        detail=exc.message,
    )


def _to_role(role: Optional[str]) -> Optional[Role]:
    try:
        return Role(role) if role else None
    except ValueError:
        return None


def _build_actor(request: Request, tenant_id: str, role: Optional[str]) -> Actor:
    """Actor del contrato desde el borde HTTP (dual-auth).

    Canal: header X-Internal-Service-Secret presente → BOT (orchestrator→API);
    si no, CONSOLE (JWT usuario). Rol: el verificado por la dependency; None en
    operaciones sin verificación de rol (create G-4 / lecturas tenant-scoped).
    """
    channel = Channel.BOT if request.headers.get("X-Internal-Service-Secret") else Channel.CONSOLE
    return Actor(channel=channel, tenant_id=tenant_id, role=_to_role(role))


# Wrappers HTTP legacy — `test_a3_a4_nivel5` importa `_validate_status` del
# router y exige HTTPException. La validación de negocio vive en el servicio
# (DomainError); estos quedan para compatibilidad de imports.
def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Status inválido '{status}'. Válidos: {sorted(VALID_STATUSES)}",
        )


def _validate_reason(reason: str) -> None:
    if reason not in VALID_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Motivo inválido '{reason}'. Válidos: {sorted(VALID_REASONS)}",
        )


# ─── Modelos ─────────────────────────────────────────────────────────────────

class ClaimCreate(BaseModel):
    order_id: str = Field(..., description="UUID del pedido reclamado.")
    customer_id: Optional[str] = Field(default=None, description="UUID del contacto. Si no viene, el back lo deriva del order.")
    reason: str = Field(..., min_length=3, max_length=500)
    # Decisión founder 2026-08-25 #3: detalle libre opcional (las palabras del
    # cliente), complemento del reason cerrado — máx 500 como el free-text del bot.
    reason_detail: Optional[str] = Field(default=None, max_length=500)
    requested_amount: Optional[float] = Field(default=None, ge=0)
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)


class ClaimPatch(BaseModel):
    status: Optional[str] = None
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)
    # BLOQUE G-2 — monto REAL reembolsado (obligatorio al pasar a 'refunded'). Es lo
    # que el KPI net-revenue resta; NO uses requested_amount (intención del cliente).
    refunded_amount: Optional[float] = Field(default=None, ge=0)


class ClaimResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=3, max_length=2000)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
def list_claims(
    status: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
    order_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista reclamos del tenant con embeds de pedido/contacto + reason_detail
    (lo que la consola necesita — M2.4: page.tsx migra su listado a este REST).
    Filtros opcionales por status / customer / order (semántica heredada)."""
    try:
        return claims_service.list_claims(
            supabase,
            tenant_id=tenant_id,
            actor=Actor(channel=Channel.CONSOLE, tenant_id=tenant_id),
            status=status,
            customer_id=customer_id,
            order_id=order_id,
            limit=limit,
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de


@router.post("/", response_model=dict, status_code=201, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="created")
def create_claim(
    body: ClaimCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Crea un reclamo vía el writer unificado del dominio.

    BLOQUE G-4 (decisión founder): CREAR reclamos es owner/manager/operator — el
    operator es front-line de soporte y la UI ya expone «Nuevo Reclamo» (canWrite
    incluye operator). Se quitó require_write_role para alinear la API con la UI
    (antes el operator veía el botón y recibía 403). RESOLVER/reembolsar sigue
    restringido (patch_claim/resolve_claim mantienen require_write_role).

    M2.4: la dedup del dominio (reclamo abierto para ese pedido+cliente) responde
    200 + el claim existente + `deduplicated: true` — sin duplicar fila.
    """
    from lib.claim_ports import build_api_claim_ports

    try:
        result = claims_service.create_claim(
            supabase,
            tenant_id=tenant_id,
            input=ClaimCreateInput(
                order_id=body.order_id,
                reason=body.reason,
                customer_id=body.customer_id,
                reason_detail=body.reason_detail,
                requested_amount=body.requested_amount,
                resolution_notes=body.resolution_notes,
            ),
            actor=_build_actor(request, tenant_id, None),
            ports=build_api_claim_ports(supabase, tenant_id),
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de
    if not result.created:
        # Dedup (patrón adopt-winner de orders.create): 200 + claim existente.
        return JSONResponse(status_code=200, content=result.body())
    return result.body()


@router.get("/{claim_id}", response_model=dict)
def get_claim(
    claim_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    try:
        return claims_service.get_claim(
            supabase,
            tenant_id=tenant_id,
            actor=Actor(channel=Channel.CONSOLE, tenant_id=tenant_id),
            claim_id=claim_id,
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de


@router.patch("/{claim_id}", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="updated")
def patch_claim(
    claim_id: str,
    patch: ClaimPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Actualiza status y/o resolution_notes. RBAC: owner+manager.

    Reapertura (terminal → no-terminal): restringida a OWNER y solo desde
    'rejected'/'cancelled'. 'refunded' nunca se reabre (el reembolso ya movió
    dinero); 'resolved' tampoco (cierre positivo). Decisión F2 — Opción B.
    La FSM completa vive en `konvi_domain.claims.transition_claim`.
    """
    from lib.claim_ports import build_api_claim_ports

    try:
        return claims_service.transition_claim(
            supabase,
            tenant_id=tenant_id,
            claim_id=claim_id,
            input=ClaimTransitionInput(
                status=patch.status,
                resolution_notes=patch.resolution_notes,
                refunded_amount=patch.refunded_amount,
            ),
            actor=_build_actor(request, tenant_id, _role),
            ports=build_api_claim_ports(supabase, tenant_id),
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de


@router.post("/{claim_id}/resolve", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="status_changed")
def resolve_claim(
    claim_id: str,
    body: ClaimResolve,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Atajo: marca status=resolved + persiste resolution_notes obligatoria.
    Misma transición del dominio (el guard de 'refunded' FINAL y la
    notificación F-5 solo-en-transición-real los garantiza el servicio)."""
    from lib.claim_ports import build_api_claim_ports

    try:
        return claims_service.transition_claim(
            supabase,
            tenant_id=tenant_id,
            claim_id=claim_id,
            input=ClaimTransitionInput(
                status="resolved",
                resolution_notes=body.resolution_notes,
            ),
            actor=_build_actor(request, tenant_id, _role),
            ports=build_api_claim_ports(supabase, tenant_id),
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de


# ─── Reversión del pago (Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51) ──────
#
# Es una figura DISTINTA del reembolso. Acá el dinero no lo devolvemos nosotros:
# el consumidor le pide al EMISOR de su medio de pago que deshaga el cargo.
# Nuestra única obligación —y es dura— es emitir la constancia de la queja con
# fecha y causal (art. 2.2.2.51.4). La lógica delega en las RPCs SECURITY
# DEFINER vía `konvi_domain.claims.reversion` (R2 — no se reimplementan).
#
# La causal la DECLARA el consumidor y el operador la transcribe: la norma pide
# "indicación de la causal que sustenta la petición", y clasificarla con un LLM
# sería ponerlo a decidir verdad legal.

class ReversionCreate(BaseModel):
    causal: str = Field(..., description="Una de las cinco del art. 2.2.2.51.2.")
    razones: str = Field(..., min_length=3, max_length=2000,
                         description="En las palabras del consumidor; no se resume.")
    valor: float = Field(..., gt=0, description="Valor sobre el que se pide la reversión.")
    instrumento: Optional[str] = Field(
        default=None, max_length=120,
        description="Descriptor del medio de pago (p. ej. 'Visa terminada en 4242'). "
                    "NUNCA el número completo.",
    )
    es_parcial: bool = Field(default=False)
    items: Optional[list] = Field(default=None)
    bien_a_disposicion: bool = Field(
        default=False,
        description="El consumidor manifestó que el bien queda a disposición para "
                    "recogerlo (art. 2.2.2.51.4 inc. 3).",
    )
    canal: str = Field(default="inbox", max_length=40)
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    meta_message_id: Optional[str] = None


class MovimientoReversion(BaseModel):
    via: str = Field(..., description="reembolso_directo | reversion_emisor")
    valor: float = Field(..., gt=0)


@router.post("/{claim_id}/reversion", response_model=dict,
             dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="payment_reversal", action="created")
def registrar_reversion(
    claim_id: str,
    body: ReversionCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Radica la queja de reversión y emite su constancia, en el mismo acto.

    No son dos pasos: el art. 2.2.2.51.4 no condiciona la constancia a nada, así que el
    estado "radicada sin constancia" sería justamente el incumplimiento.

    Idempotente por reclamo. Un reintento devuelve la constancia que ya existe y NO emite
    una segunda con otra fecha: la fecha es lo que prueba que la queja llegó dentro de los
    cinco días hábiles del art. 2.2.2.51.4.
    """
    try:
        return reversion_service.register_reversion(
            supabase,
            tenant_id=tenant_id,
            claim_id=claim_id,
            input=ReversionInput(
                causal=body.causal,
                razones=body.razones,
                valor=body.valor,
                instrumento=body.instrumento,
                es_parcial=body.es_parcial,
                items=body.items,
                bien_a_disposicion=body.bien_a_disposicion,
                canal=body.canal,
                conversation_id=body.conversation_id,
                message_id=body.message_id,
                meta_message_id=body.meta_message_id,
            ),
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de


@router.get("/{claim_id}/reversion", response_model=dict)
def obtener_reversion(
    claim_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """La constancia radicada de un reclamo, o 404 si no hay ninguna."""
    try:
        return reversion_service.read_reversion(
            supabase, tenant_id=tenant_id, claim_id=claim_id,
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de


@router.post("/{claim_id}/reversion/movimiento", response_model=dict,
             dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="payment_reversal", action="updated")
def registrar_movimiento(
    claim_id: str,
    body: MovimientoReversion,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Registra por cuál de los dos caminos volvió el dinero.

    Y si volvió por LOS DOS, lo marca. El art. 2.2.2.51.10 contempla expresamente ese
    escenario —el comerciante reembolsa mientras el emisor reversa en paralelo— y dice que
    el consumidor debe devolver esos recursos. Sin registrarlo sería invisible: no se puede
    reclamar lo que no se sabe que se pagó.
    """
    try:
        return reversion_service.register_reversion_movement(
            supabase,
            tenant_id=tenant_id,
            claim_id=claim_id,
            via=body.via,
            valor=body.valor,
        )
    except DomainError as de:
        raise _domain_error_to_http(de) from de

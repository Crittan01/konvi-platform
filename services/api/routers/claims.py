"""
Router de Reclamos / Claims — CRUD con aislamiento multi-tenant.

Rev. 72 — cierra el drift D1 (Claims escribía directo a DB desde RSC sin pasar por API).

Endpoints:
  GET    /api/v1/claims/                 — listar reclamos del tenant
  POST   /api/v1/claims/                 — crear reclamo                       [owner, manager, operator]
  GET    /api/v1/claims/{id}             — detalle
  PATCH  /api/v1/claims/{id}             — cambiar status / resolution_notes   [owner, manager]
  POST   /api/v1/claims/{id}/resolve     — atajo: status=resolved + notas      [owner, manager]

Estados válidos: open → in_progress → resolved | closed | cancelled

Coexistencia con orchestrator: el bot inserta claims via service_role direct
(`.table('claims').insert({'tenant_id': ..., ...})`), bypassa este router. Es
intencional: el bot tiene contexto de conversación que el frontend no tiene.
Ambos paths escriben a la misma tabla; RLS + tenant_id explícito mantiene
aislamiento. Patrón canónico `.table(X).eq('tenant_id', tid)` enforced por lint
AST scripts/audit_tenant_filter.py (ADR-0025 — helper scoped_table eliminado).
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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

# A4 finiquito (audit §3 BUG#2 CRITICAL) — vocabulario canónico alineado con la UI
# (claims-manager.tsx STATUS_MAP + botones Investigando/Reembolsar/Rechazar). Antes
# el API tenía {in_progress, closed} que la UI NO usaba, y rechazaba 422 los
# {investigating, refunded, rejected} de los botones → 3 botones rotos. 0 claims en
# DB al alinear (sin migración de datos). Mismo set en el tool agentic
# (tools/claims.py) + CHECK constraint DB (migración 20260624010000).
VALID_STATUSES = {"open", "investigating", "resolved", "refunded", "rejected", "cancelled"}

# Estados terminales: el ticket ya está cerrado. Coincide con TERMINAL en la UI
# (claims-manager.tsx). Reabrir uno de estos es una transición especial (ver abajo).
TERMINAL_STATUSES = {"resolved", "refunded", "rejected", "cancelled"}

# Terminales que un OWNER puede reabrir (decisión F2 — Opción B).
#   - 'rejected' / 'cancelled': reversibles, sin impacto financiero → reabribles.
#   - 'refunded': revertir un reembolso ya movió dinero → NUNCA reabrir.
#   - 'resolved': cierre positivo → se maneja como reclamo nuevo, no se reabre.
# Reabrir = pasar de un estado terminal a uno no-terminal ('open' / 'investigating').
REOPENABLE_STATUSES = {"rejected", "cancelled"}

# Vocabulario canónico de 'reason' (decisión F2 — Opción A). El set de la UI
# (claims-manager.tsx REASON_MAP + dropdown de "Nuevo Reclamo") es la fuente de
# verdad; este API lo valida en create para mantener reporting consistente.
# El bot escribe reason en texto libre directo a DB (bypassa este router) y su
# mapeo a estas keys vive en el orchestrator (fuera de este router). La DB NO tiene
# CHECK sobre reason justamente para no romper esa escritura libre del bot.
VALID_REASONS = {"defective", "wrong_item", "missing_parts", "delayed", "other"}


# ─── Modelos ─────────────────────────────────────────────────────────────────

class ClaimCreate(BaseModel):
    order_id: str = Field(..., description="UUID del pedido reclamado.")
    customer_id: Optional[str] = Field(default=None, description="UUID del contacto. Si no viene, el back lo deriva del order.")
    reason: str = Field(..., min_length=3, max_length=500)
    requested_amount: Optional[float] = Field(default=None, ge=0)
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)


class ClaimPatch(BaseModel):
    status: Optional[str] = None
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)


class ClaimResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=3, max_length=2000)


# ─── Helpers ─────────────────────────────────────────────────────────────────

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


def _fetch_claim(supabase: Client, tenant_id: str, claim_id: str) -> dict:
    """Lee un reclamo del tenant o lanza 404. Usado para validar transiciones."""
    res = (
        supabase.table("claims")
        .select("id, status")
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    return res.data


def _ensure_order_belongs_to_tenant(supabase: Client, tenant_id: str, order_id: str) -> dict:
    res = (
        supabase.table("orders")
        .select("id, tenant_id, contact_id, status")
        .eq("id", order_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Pedido no encontrado para este tenant")
    return res.data


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_claims(
    status: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
    order_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista reclamos del tenant. Filtros opcionales por status / customer / order."""
    q = supabase.table("claims").select("*").eq("tenant_id", tenant_id)
    if status:
        _validate_status(status)
        q = q.eq("status", status)
    if customer_id:
        q = q.eq("customer_id", customer_id)
    if order_id:
        q = q.eq("order_id", order_id)
    q = q.order("created_at", desc=True).limit(limit)
    res = q.execute()
    return res.data or []


@router.post("/", response_model=dict, status_code=201, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="created")
async def create_claim(
    body: ClaimCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea un reclamo. Valida que el order pertenezca al tenant.
    Si customer_id no viene, se deriva del order.contact_id."""
    order = _ensure_order_belongs_to_tenant(supabase, tenant_id, body.order_id)
    _validate_reason(body.reason.strip())

    customer_id = body.customer_id or order.get("contact_id")

    payload: dict = {
        "tenant_id": tenant_id,
        "order_id":  body.order_id,
        "customer_id": customer_id,
        "reason":    body.reason.strip(),
        "status":    "open",
    }
    if body.requested_amount is not None:
        payload["requested_amount"] = body.requested_amount
    if body.resolution_notes:
        payload["resolution_notes"] = body.resolution_notes.strip()

    res = supabase.table("claims").insert(payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    if not res.data:
        raise HTTPException(status_code=500, detail="No fue posible crear el reclamo")
    return res.data[0]


@router.get("/{claim_id}", response_model=dict)
async def get_claim(
    claim_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    res = (
        supabase.table("claims")
        .select("*")
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    return res.data


@router.patch("/{claim_id}", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="updated")
async def patch_claim(
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
    """
    update: dict = {}
    if patch.status is not None:
        _validate_status(patch.status)
        update["status"] = patch.status
    if patch.resolution_notes is not None:
        update["resolution_notes"] = patch.resolution_notes.strip() or None

    if not update:
        raise HTTPException(status_code=422, detail="Sin campos a actualizar")

    # Guard de reapertura: solo si el status cambia de terminal → no-terminal.
    if "status" in update:
        new_status = update["status"]
        current = _fetch_claim(supabase, tenant_id, claim_id)
        cur_status = current.get("status")
        is_reopen = cur_status in TERMINAL_STATUSES and new_status not in TERMINAL_STATUSES
        if is_reopen:
            if _role != "owner":
                raise HTTPException(
                    status_code=403,
                    detail="Solo el owner puede reabrir un reclamo cerrado.",
                )
            if cur_status == "refunded":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "No se puede reabrir un reclamo reembolsado: el reembolso ya "
                        "movió dinero. Crea un reclamo nuevo si es necesario."
                    ),
                )
            if cur_status not in REOPENABLE_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"No se puede reabrir un reclamo en estado '{cur_status}'. "
                        "Solo 'rejected' o 'cancelled' se pueden reabrir."
                    ),
                )

    res = (
        supabase.table("claims")
        .update(update)
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    return res.data[0]


@router.post("/{claim_id}/resolve", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="status_changed")
async def resolve_claim(
    claim_id: str,
    body: ClaimResolve,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Atajo: marca status=resolved + persiste resolution_notes obligatoria."""
    res = (
        supabase.table("claims")
        .update({
            "status": "resolved",
            "resolution_notes": body.resolution_notes.strip(),
        })
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    return res.data[0]

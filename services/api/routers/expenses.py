"""Registro de gastos per-tenant — escrituras auditadas (F2.2 / auditoría 2026-06-29).

`addExpense` escribía directo a Supabase (RLS) SIN @audit_log. Los gastos son registros financieros:
la traza forense de quién registró qué gasto y cuándo importa (integridad contable). Ahora vía API.
La LECTURA del dashboard sigue directa (RLS). Solo existe creación (no edición/borrado de gastos).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    get_current_tenant,
    get_current_user_id,
    get_service_client,
    require_owner_role,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Expenses"])


class ExpenseCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=500)
    amount: float = Field(..., gt=0)
    expense_date: Optional[str] = None  # ISO; default = ahora si se omite


class ExpenseReverse(BaseModel):
    reason: str = Field(..., min_length=3, max_length=300)


@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="expense", action="created")
async def create_expense(
    expense: ExpenseCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    # BLOQUE F-2: registrar gastos = OWNER-ONLY (decisión founder). Antes require_write_role
    # permitía manager, contradiciendo la matriz de roles para datos financieros.
    _role: str = Depends(require_owner_role),
):
    """Registra un gasto. Solo owner. `expense_date` por defecto = ahora."""
    try:
        result = supabase.table("expenses").insert({
            "tenant_id": tenant_id,
            "category": expense.category,
            "description": expense.description.strip(),
            "amount": expense.amount,
            "expense_date": expense.expense_date or datetime.now(timezone.utc).isoformat(),
        }).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Error al registrar el gasto")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error registrando gasto tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al registrar el gasto") from e


@router.post("/{expense_id}/reverse", response_model=dict)
@audit_log(entity_type="expense", action="reversed")
async def reverse_expense(
    expense_id: str,
    body: ExpenseReverse,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    user_id: Optional[str] = Depends(get_current_user_id),
    _role: str = Depends(require_owner_role),
):
    """BLOQUE F-4 — anula (soft-void) un gasto. Solo owner. NO se borra: preserva el trail contable
    (reversed_by/at/reason, exigido por el CHECK expenses_reversal_trail_ck) y el P&L excluye el
    anulado (índice parcial WHERE reversed_at IS NULL). La UI ya llamaba a este endpoint (server
    action reverseExpense) pero NO existía → 404. Idempotente/race-safe: el UPDATE filtra
    reversed_at IS NULL, así que una doble-anulación concurrente da 409, no doble-trail."""
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="El motivo debe tener al menos 3 caracteres")
    if not user_id:
        raise HTTPException(status_code=403, detail="No se pudo identificar al usuario")

    existing = (
        supabase.table("expenses")
        .select("id, reversed_at")
        .eq("id", expense_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not existing or not existing.data:  # maybe_single() → None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if existing.data.get("reversed_at"):
        raise HTTPException(status_code=409, detail="El gasto ya está anulado")

    # UPDATE atómico con guard `reversed_at IS NULL` → no doble-anula bajo concurrencia.
    try:
        upd = (
            supabase.table("expenses")
            .update({
                "reversed_at": datetime.now(timezone.utc).isoformat(),
                "reversed_by": user_id,
                "reversal_reason": reason,
            })
            .eq("id", expense_id)
            .eq("tenant_id", tenant_id)
            .is_("reversed_at", "null")
            .execute()
        )
    except Exception as e:
        logger.error("Error anulando gasto %s tenant %s: %s", expense_id, tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al anular el gasto") from e
    if not upd.data:
        # Perdió la carrera: otro request lo anuló entremedio.
        raise HTTPException(status_code=409, detail="El gasto ya está anulado")
    return upd.data[0]

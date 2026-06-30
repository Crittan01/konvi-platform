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
from dependencies.auth import get_current_tenant, get_service_client, require_write_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Expenses"])


class ExpenseCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=500)
    amount: float = Field(..., gt=0)
    expense_date: Optional[str] = None  # ISO; default = ahora si se omite


@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="expense", action="created")
async def create_expense(
    expense: ExpenseCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Registra un gasto. Solo owner/manager. `expense_date` por defecto = ahora."""
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

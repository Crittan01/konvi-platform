"""
Router de Contactos — CRUD con aislamiento multi-tenant via RLS.

Endpoints:
  GET    /api/v1/contacts/        — listar contactos del tenant
  POST   /api/v1/contacts/        — crear contacto             [owner, manager]
  PATCH  /api/v1/contacts/{id}    — editar nombre / notas      [owner, manager]
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, require_write_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Contacts"])


# ─── Modelos ─────────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    phone: str = Field(..., min_length=5, max_length=30)
    name: Optional[str] = None
    notes: Optional[str] = None


class ContactPatch(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_contacts(
    search: Optional[str] = Query(default=None, description="Filtra por teléfono o nombre"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista contactos del tenant. Soporta búsqueda por teléfono o nombre."""
    try:
        query = (
            supabase.table("contacts")
            .select("id, phone, name, notes, created_at")
            .eq("tenant_id", tenant_id)
            .order("name", desc=False, nullsfirst=False)
            .limit(limit)
            .offset(offset)
        )
        result = query.execute()
        rows = result.data or []

        # Filtro básico client-side si hay búsqueda (Supabase Free no tiene full-text fácil)
        if search:
            s = search.lower()
            rows = [r for r in rows if s in (r.get("phone") or "").lower()
                    or s in (r.get("name") or "").lower()]
        return rows
    except Exception as e:
        logger.error("Error listando contactos tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener contactos")


@router.post("/", response_model=dict, status_code=201)
async def create_contact(
    contact: ContactCreate,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea contacto. El teléfono debe ser único por tenant. Solo owner/manager."""
    try:
        result = supabase.table("contacts").insert({
            "tenant_id": tenant_id,
            "phone": contact.phone,
            "name": contact.name,
            "notes": contact.notes,
        }).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear contacto")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        # Violación de UNIQUE(tenant_id, phone)
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Ya existe un contacto con ese teléfono")
        logger.error("Error creando contacto tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear contacto")


@router.patch("/{contact_id}", response_model=dict)
async def patch_contact(
    contact_id: str,
    patch: ContactPatch,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Edita nombre y/o notas del contacto. Solo owner/manager."""
    try:
        data = {k: v for k, v in patch.model_dump().items() if v is not None}
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        result = (
            supabase.table("contacts")
            .update(data)
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando contacto %s: %s", contact_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar contacto")

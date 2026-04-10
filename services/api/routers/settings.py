"""
Router de Configuración — Tenant info, equipo y notificaciones.

Endpoints:
  GET    /api/v1/settings/tenant              — datos del tenant
  PATCH  /api/v1/settings/tenant              — editar nombre/waba_id  [owner]
  GET    /api/v1/settings/team                — listar equipo con emails
  PATCH  /api/v1/settings/team/{user_id}      — cambiar rol             [owner]
  DELETE /api/v1/settings/team/{user_id}      — eliminar miembro        [owner]
  GET    /api/v1/settings/notifications       — config de notificaciones
  PUT    /api/v1/settings/notifications/{ch}  — upsert config canal     [owner, manager]
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, get_current_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Settings"])

VALID_ROLES = {"owner", "manager", "agent"}


# ─── Modelos ─────────────────────────────────────────────────────────────────

class ShippingOrigin(BaseModel):
    name: Optional[str] = None           # Nombre del remitente
    company: Optional[str] = None        # Nombre de la empresa
    street: Optional[str] = None         # Calle y número
    city: Optional[str] = None           # Ciudad
    state: Optional[str] = None          # Estado / departamento
    postal_code: Optional[str] = None    # Código postal
    country: Optional[str] = None        # Código de país ISO (ej: MX, CO)
    phone: Optional[str] = None          # Teléfono de contacto


class TenantPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    meta_waba_id: Optional[str] = None
    shipping_origin: Optional[ShippingOrigin] = None


class TeamRolePatch(BaseModel):
    role: str = Field(..., pattern="^(owner|manager|agent)$")


class NotificationConfig(BaseModel):
    enabled: bool
    config: dict = Field(default_factory=dict)


# ─── Tenant ───────────────────────────────────────────────────────────────────

@router.get("/tenant", response_model=dict)
async def get_tenant(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Retorna datos básicos del tenant."""
    try:
        result = (
            supabase.table("tenants")
            .select("id, name, status, meta_waba_id, shipping_origin, logo_url, created_at")
            .eq("id", tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener configuración")


@router.patch("/tenant", response_model=dict)
async def patch_tenant(
    patch: TenantPatch,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Edita nombre o WABA ID del tenant. Solo owner."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede editar la configuración del tenant")
    try:
        raw = patch.model_dump()
        # Serializar shipping_origin a dict si es un objeto Pydantic
        if raw.get("shipping_origin") is not None:
            raw["shipping_origin"] = {k: v for k, v in raw["shipping_origin"].items() if v is not None}
        data = {k: v for k, v in raw.items() if v is not None}
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        result = (
            supabase.table("tenants")
            .update(data)
            .eq("id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar configuración")


# ─── Team ─────────────────────────────────────────────────────────────────────

@router.get("/team", response_model=list)
async def get_team(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista miembros del equipo con email y rol. Usa función SECURITY DEFINER."""
    try:
        result = supabase.rpc("get_tenant_team").execute()
        return result.data or []
    except Exception as e:
        logger.error("Error listando equipo tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener equipo")


@router.patch("/team/{member_user_id}", response_model=dict)
async def patch_team_member(
    member_user_id: str,
    patch: TeamRolePatch,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Cambia el rol de un miembro. Solo owner."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede cambiar roles")
    try:
        result = (
            supabase.table("tenant_users")
            .update({"role": patch.role})
            .eq("user_id", member_user_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Miembro no encontrado en este tenant")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error cambiando rol user %s en tenant %s: %s", member_user_id, tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al cambiar rol")


@router.delete("/team/{member_user_id}", status_code=204)
async def remove_team_member(
    member_user_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Elimina miembro del equipo. Solo owner. No puede eliminarse a sí mismo."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede eliminar miembros")
    try:
        # Verificar que no es el propio owner intentando eliminarse
        # (el tenant_id ya garantiza aislamiento)
        result = (
            supabase.table("tenant_users")
            .delete()
            .eq("user_id", member_user_id)
            .eq("tenant_id", tenant_id)
            .neq("role", "owner")  # No eliminar al owner
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Miembro no encontrado o no se puede eliminar al owner")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando miembro %s de tenant %s: %s", member_user_id, tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al eliminar miembro")


# ─── Notifications ────────────────────────────────────────────────────────────

@router.get("/notifications", response_model=list)
async def get_notifications(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista configuración de notificaciones por canal."""
    try:
        result = (
            supabase.table("notification_settings")
            .select("id, channel, enabled, config, updated_at")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error("Error obteniendo notificaciones tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener notificaciones")


@router.put("/notifications/{channel}", response_model=dict)
async def upsert_notification(
    channel: str,
    cfg: NotificationConfig,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Guarda o actualiza configuración de un canal de notificación. Owner/manager."""
    if role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Se requiere owner o manager")
    if channel not in ("telegram", "email"):
        raise HTTPException(status_code=422, detail="Canal inválido. Válidos: telegram, email")
    try:
        result = supabase.table("notification_settings").upsert({
            "tenant_id": tenant_id,
            "channel": channel,
            "enabled": cfg.enabled,
            "config": cfg.config,
        }, on_conflict="tenant_id,channel").execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al guardar configuración")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error guardando notificación canal %s tenant %s: %s", channel, tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al guardar notificación")

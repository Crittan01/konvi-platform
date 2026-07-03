"""
Router de Configuración — Tenant info, equipo y notificaciones.

Endpoints:
  GET    /api/v1/settings/tenant              — datos del tenant
  PATCH  /api/v1/settings/tenant              — editar nombre/waba_id  [owner]
  GET    /api/v1/settings/plan-capabilities   — plan + capabilities + cuotas
  POST   /api/v1/settings/maintenance/idempotency-cleanup — limpieza de llaves expiradas [owner]
  PATCH  /api/v1/settings/team/{user_id}      — cambiar rol             [owner]
  DELETE /api/v1/settings/team/{user_id}      — eliminar miembro        [owner]
  GET    /api/v1/settings/notifications       — config de notificaciones
  PUT    /api/v1/settings/notifications/{ch}  — upsert config canal     [owner, manager]
"""
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_owner_role,
    require_write_role,
)
from vault_helper import VaultHelper

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Settings"])

VALID_ROLES      = {"owner", "manager", "operator"}   # roles válidos en el sistema
ASSIGNABLE_ROLES = {"manager", "operator"}             # roles asignables vía API (nunca owner)


# ─── Modelos ─────────────────────────────────────────────────────────────────

class ShippingOrigin(BaseModel):
    name: Optional[str] = None           # Nombre del remitente
    company: Optional[str] = None        # Nombre de la empresa
    street: Optional[str] = None         # Dirección
    city: Optional[str] = None           # Ciudad
    state: Optional[str] = None          # Estado / departamento
    postal_code: Optional[str] = None    # Código postal
    country: Optional[str] = None        # Código de país ISO (ej: MX, CO)
    phone: Optional[str] = None          # Teléfono de contacto


class SocialLinks(BaseModel):
    instagram: Optional[str] = None
    facebook:  Optional[str] = None
    tiktok:    Optional[str] = None
    youtube:   Optional[str] = None
    website:   Optional[str] = None


class StoreLocation(BaseModel):
    name:       Optional[str]  = Field(default=None, max_length=80)
    city:       Optional[str]  = None
    state:      Optional[str]  = None
    street:     Optional[str]  = None
    phone:      Optional[str]  = Field(default=None, pattern=r'^[0-9]{10}$')
    email:      Optional[str]  = Field(default=None, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    # Rev. 71 — sede principal: el bot la menciona primero y la rotula como
    # "(principal)" en el system prompt. Solo una sede debe tener is_primary=True.
    is_primary: Optional[bool] = None


class TenantPatch(BaseModel):
    name:               Optional[str] = Field(default=None, min_length=1, max_length=100)
    meta_waba_id:       Optional[str] = None
    shipping_origin:    Optional[ShippingOrigin] = None
    store_type:         Optional[Literal["fisica", "virtual", "fisica_virtual"]] = None
    social_links:       Optional[SocialLinks] = None
    store_locations:    Optional[list[StoreLocation]] = None
    # Identidad legal
    nit:                Optional[str] = None
    email_contacto:     Optional[str] = Field(
        default=None, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$'
    )
    telefono_contacto:  Optional[str] = Field(
        default=None, pattern=r'^3[0-9]{9}$'
    )
    low_stock_threshold: Optional[int] = Field(default=None, ge=1, le=999)
    # Filosofía de marca — alimenta el system prompt del bot
    mision:              Optional[str] = Field(default=None, max_length=280)
    vision:              Optional[str] = Field(default=None, max_length=280)
    valores:             Optional[str] = Field(default=None, max_length=280)
    tono_comunicacion:   Optional[Literal['formal', 'amigable', 'cercano', 'profesional', 'juvenil']] = None
    # Horario de soporte y mensajes automáticos
    support_schedule:    Optional[dict] = None
    after_hours_message: Optional[str] = None


class TeamRolePatch(BaseModel):
    role: str = Field(..., pattern="^(owner|manager|operator)$")


class NotificationConfig(BaseModel):
    enabled: bool
    config: dict = Field(default_factory=dict)


class IdempotencyCleanupRequest(BaseModel):
    limit: int = Field(default=5000, ge=1, le=50000)


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
            .select("id, name, status, meta_waba_id, shipping_origin, logo_url, "
                    "store_type, social_links, store_locations, "
                    "nit, email_contacto, telefono_contacto, low_stock_threshold, "
                    "mision, vision, valores, tono_comunicacion, "
                    "support_schedule, after_hours_message, escalation_role, created_at")
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
@audit_log(entity_type="settings", action="updated")
async def patch_tenant(
    patch: TenantPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
):
    """Actualiza campos del tenant. Solo owner.
    Soporta: name, meta_waba_id, shipping_origin, store_type, social_links,
    store_locations, nit, email_contacto, telefono_contacto,
    low_stock_threshold, support_schedule, after_hours_message, escalation_role,
    mision, vision, valores, tono_comunicacion."""
    try:
        raw = patch.model_dump()
        # Serializar objetos Pydantic anidados a dict
        if raw.get("shipping_origin") is not None:
            raw["shipping_origin"] = {k: v for k, v in raw["shipping_origin"].items() if v is not None}
        if raw.get("social_links") is not None:
            raw["social_links"] = {k: v for k, v in raw["social_links"].items() if v is not None}
        if raw.get("store_locations") is not None:
            raw["store_locations"] = [
                {k: v for k, v in loc.items() if v is not None}
                for loc in raw["store_locations"]
                if any(v for v in loc.values() if v)
            ]
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

# F21: GET /team eliminado (código muerto). La RPC get_tenant_team resuelve el tenant
# vía auth.jwt()->app_metadata, pero este handler la invocaba con el cliente service_role
# (sin ese claim) → devolvía SIEMPRE [] con HTTP 200. Sin callers (el frontend usa la RPC
# directo bajo JWT de usuario con RLS, no este endpoint). La RPC se conserva intacta.


@router.patch("/team/{member_user_id}", response_model=dict)
@audit_log(entity_type="team_member", action="role_changed")
async def patch_team_member(
    member_user_id: str,
    patch: TeamRolePatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
):
    """Cambia el rol de un miembro. Solo owner."""
    if patch.role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Rol no asignable. Solo se permite: {sorted(ASSIGNABLE_ROLES)}. El rol 'owner' no puede asignarse vía API.",
        )
    try:
        result = (
            supabase.table("tenant_users")
            .update({"role": patch.role})
            .eq("user_id", member_user_id)
            .eq("tenant_id", tenant_id)
            .neq("role", "owner")  # F22: el rol del owner no se cambia vía API (simétrico al DELETE)
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Miembro no encontrado o es el owner (rol no modificable vía API)",
            )
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error cambiando rol user %s en tenant %s: %s", member_user_id, tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al cambiar rol")


@router.delete("/team/{member_user_id}", status_code=204)
@audit_log(entity_type="team_member", action="deleted")
async def remove_team_member(
    member_user_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
):
    """Elimina miembro del equipo. Solo owner. No puede eliminarse a sí mismo."""
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
@audit_log(entity_type="settings", action="updated")
async def upsert_notification(
    channel: str,
    cfg: NotificationConfig,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Guarda o actualiza configuración de un canal de notificación. Owner/manager."""
    if channel not in ("telegram", "email"):
        raise HTTPException(status_code=422, detail="Canal inválido. Válidos: telegram, email")
    try:
        config = dict(cfg.config)

        # Telegram: cifrar bot_token en Vault si viene en texto plano
        if channel == "telegram" and config.get("bot_token"):
            vault = VaultHelper(supabase)
            existing_res = (
                supabase.table("notification_settings").select("config")
                .eq("tenant_id", tenant_id).eq("channel", "telegram")
                .maybe_single().execute()
            )
            existing_sid = (existing_res.data or {}).get("config", {}).get("bot_token_secret_id")
            if existing_sid:
                vault.update_secret(existing_sid, config["bot_token"])
                secret_id = existing_sid
            else:
                secret_id = vault.create_secret(
                    config["bot_token"], f"{tenant_id}/telegram/bot_token", "Telegram bot token"
                )
            if secret_id:
                del config["bot_token"]
                config["bot_token_secret_id"] = secret_id

        # Si disabled y hay secret_id, eliminar de Vault
        if channel == "telegram" and not cfg.enabled:
            vault = VaultHelper(supabase)
            existing_res = (
                supabase.table("notification_settings").select("config")
                .eq("tenant_id", tenant_id).eq("channel", "telegram")
                .maybe_single().execute()
            )
            sid = (existing_res.data or {}).get("config", {}).get("bot_token_secret_id")
            vault.delete_secret(sid)
            config = {}

        result = supabase.table("notification_settings").upsert({
            "tenant_id": tenant_id,
            "channel": channel,
            "enabled": cfg.enabled,
            "config": config,
        }, on_conflict="tenant_id,channel").execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al guardar configuración")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error guardando notificación canal %s tenant %s: %s", channel, tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al guardar notificación")


@router.get("/plan-capabilities", response_model=dict)
async def get_plan_capabilities(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Retorna snapshot del plan activo del tenant con capabilities y cuotas/uso actual.
    """
    try:
        res = supabase.rpc("get_tenant_plan_capabilities", {"p_tenant_id": tenant_id}).execute()
        rows = res.data or []
        if not rows:
            return {"plan_code": "basic", "capabilities": []}
        plan_code = rows[0].get("plan_code", "basic")
        return {"plan_code": plan_code, "capabilities": rows}
    except Exception as e:
        logger.error("Error obteniendo plan capabilities tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener plan capabilities")


@router.post("/maintenance/idempotency-cleanup", response_model=dict)
async def cleanup_idempotency(
    body: IdempotencyCleanupRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
):
    """
    Ejecuta limpieza de idempotency keys expiradas.
    Operación de mantenimiento global (owner del tenant autenticado).
    """
    try:
        res = supabase.rpc("cleanup_expired_idempotency_keys", {"p_limit": body.limit}).execute()
        raw = res.data
        if isinstance(raw, list):
            value = raw[0] if raw else 0
            if isinstance(value, dict):
                value = next(iter(value.values()), 0)
            deleted = int(value or 0)
        else:
            deleted = int(raw or 0)
        return {"ok": True, "deleted": deleted, "limit": body.limit}
    except Exception as e:
        logger.error("Error ejecutando cleanup idempotency tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error ejecutando limpieza de idempotencia")

"""
Router de Integraciones — Gestión de conexiones MeLi y Envia por tenant.

Endpoints:
  GET    /api/v1/integrations/              — estado de todas las integraciones del tenant
  POST   /api/v1/integrations/envia         — guardar API key de Envia  [owner]
  DELETE /api/v1/integrations/envia         — desconectar Envia          [owner]
  GET    /api/v1/integrations/meli/auth-url — URL OAuth para iniciar flujo MeLi [owner]
  GET    /api/v1/integrations/meli/callback — callback OAuth (browser redirect) — NO requiere JWT
  DELETE /api/v1/integrations/meli          — desconectar MeLi            [owner]
"""
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.audit import audit_log
from dependencies.auth import _get_service_client, get_current_tenant, get_service_client, get_current_role
from vault_helper import VaultHelper
from dependencies.plans import PLAN_INTEGRATIONS_MELI
from integrations import meli_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Integrations"])

FRONTEND_BASE_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
FRONTEND_INTEGRATIONS_URL = f"{FRONTEND_BASE_URL}/dashboard/integrations"


# ─── Modelos ─────────────────────────────────────────────────────────────────

class EnviaConnect(BaseModel):
    api_token: str = Field(..., min_length=10)
    sandbox: bool = Field(default=False)


class EnviaCarrierUpsert(BaseModel):
    """Sem 5 H.2.7 — preferencias de carriers per-tenant."""
    carrier_code: str = Field(..., min_length=2, max_length=64)
    enabled: bool = Field(default=True)
    display_label: Optional[str] = Field(default=None, max_length=120)
    priority: int = Field(default=100, ge=0, le=999)
    supports_insurance: bool = Field(default=False)
    notes: Optional[str] = Field(default=None, max_length=500)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mask_token(token: str) -> str:
    """Retorna los primeros 6 y últimos 4 chars para mostrar en UI sin exponer el token."""
    if len(token) <= 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=list)
async def list_integrations(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista el estado de todas las integraciones del tenant (Envia, MeLi)."""
    try:
        result = (
            supabase.table("tenant_integrations")
            .select("id, provider, status, meta, updated_at")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        rows = result.data or []

        # Añadir si MeLi está globalmente configurado en la plataforma
        meli_row = next((r for r in rows if r["provider"] == "mercadolibre"), None)
        if not meli_row:
            rows.append({
                "provider": "mercadolibre",
                "status": "disconnected",
                "meta": {},
                "platform_configured": meli_client.is_configured(),
            })
        else:
            meli_row["platform_configured"] = meli_client.is_configured()

        envia_row = next((r for r in rows if r["provider"] == "envia"), None)
        if not envia_row:
            rows.append({"provider": "envia", "status": "disconnected", "meta": {}})

        return rows
    except Exception as e:
        logger.error("Error listando integraciones tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener integraciones")


# ── Envia ──────────────────────────────────────────────────────────────────

@router.post("/envia", response_model=dict, status_code=201)
@audit_log(entity_type="integration", action="connected")
async def connect_envia(
    body: EnviaConnect,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """
    Guarda la API key de Envia para el tenant. Solo owner.
    La API key nunca se retorna en GET para no exponerla.
    """
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede conectar integraciones")
    try:
        vault = VaultHelper(supabase)

        # Leer secret_id existente para actualizar en lugar de crear uno nuevo
        existing = (
            supabase.table("tenant_integrations")
            .select("credentials")
            .eq("tenant_id", tenant_id).eq("provider", "envia")
            .maybe_single().execute()
        )
        existing_creds = (existing.data or {}).get("credentials", {})
        existing_sid = existing_creds.get("api_token_secret_id")

        if existing_sid:
            vault.update_secret(existing_sid, body.api_token)
            secret_id = existing_sid
        else:
            secret_id = vault.create_secret(
                body.api_token, f"{tenant_id}/envia/api_token", "Envia API token"
            )
        if not secret_id:
            raise HTTPException(status_code=500, detail="Error cifrando API key en Vault")

        result = supabase.table("tenant_integrations").upsert({
            "tenant_id": tenant_id,
            "provider": "envia",
            "status": "connected",
            "credentials": {"api_token_secret_id": secret_id, "sandbox": body.sandbox},
            "meta": {
                "token_preview": _mask_token(body.api_token),
                "environment": "sandbox" if body.sandbox else "production",
            },
        }, on_conflict="tenant_id,provider").execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al guardar integración")

        data = result.data[0]
        data.pop("credentials", None)
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error conectando Envia tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al conectar Envia")


@router.delete("/envia", status_code=204)
@audit_log(entity_type="integration", action="disconnected")
async def disconnect_envia(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Desconecta Envia borrando credenciales y el secreto en Vault. Solo owner."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede desconectar integraciones")
    creds_res = (
        supabase.table("tenant_integrations").select("credentials")
        .eq("tenant_id", tenant_id).eq("provider", "envia").maybe_single().execute()
    )
    creds = (creds_res.data or {}).get("credentials", {})
    VaultHelper(supabase).delete_secret(creds.get("api_token_secret_id"))
    supabase.table("tenant_integrations").update({
        "status": "disconnected", "credentials": {},
    }).eq("tenant_id", tenant_id).eq("provider", "envia").execute()


# ── Sem 5 H.2.7 — Envia carriers preferences per-tenant ──────────────────────


@router.get("/envia/carriers", response_model=list)
async def list_envia_carriers(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista preferencias de carriers Envia del tenant. Cualquier rol.

    Retorna lista (puede estar vacía si tenant no configuró aún → quote
    devuelve todos los carriers globales por default open).
    """
    from lib.tenant_carriers import list_preferences
    prefs = list_preferences(supabase, tenant_id, "envia")
    return [
        {
            "carrier_code": p.carrier_code,
            "enabled": p.enabled,
            "display_label": p.display_label,
            "priority": p.priority,
            "supports_insurance": p.supports_insurance,
            "notes": p.notes,
        }
        for p in prefs
    ]


@router.put("/envia/carriers", response_model=dict)
@audit_log(entity_type="integration", action="updated")
async def upsert_envia_carrier(
    body: EnviaCarrierUpsert,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Upsert preferencia carrier Envia. Solo owner+manager.

    Idempotente vía UNIQUE constraint (tenant_id, provider, carrier_code).
    """
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail="Solo owner o manager pueden gestionar carriers.",
        )
    try:
        from lib.tenant_carriers import upsert_preference
        pref = upsert_preference(
            supabase, tenant_id, "envia",
            carrier_code=body.carrier_code,
            enabled=body.enabled,
            display_label=body.display_label,
            priority=body.priority,
            supports_insurance=body.supports_insurance,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("[CARRIERS] upsert error tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="Error guardando preferencia")
    return {
        "carrier_code": pref.carrier_code,
        "enabled": pref.enabled,
        "display_label": pref.display_label,
        "priority": pref.priority,
        "supports_insurance": pref.supports_insurance,
        "notes": pref.notes,
    }


@router.delete("/envia/carriers/{carrier_code}", status_code=204)
@audit_log(entity_type="integration", action="updated")
async def delete_envia_carrier(
    carrier_code: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Borra preferencia de un carrier (vuelve a default global).
    Solo owner+manager.
    """
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail="Solo owner o manager pueden gestionar carriers.",
        )
    code = (carrier_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="carrier_code requerido")
    supabase.table("tenant_carriers").delete().eq(
        "tenant_id", tenant_id,
    ).eq("provider", "envia").eq("carrier_code", code).execute()


# ── MeLi ───────────────────────────────────────────────────────────────────

@router.get("/meli/auth-url")
async def get_meli_auth_url(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
    _plan: object = Depends(PLAN_INTEGRATIONS_MELI),
):
    """Retorna la URL de autorización OAuth de MeLi. Solo owner."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede conectar integraciones")
    if not meli_client.is_configured():
        missing = meli_client.missing_required_config()
        missing_text = ", ".join(missing) if missing else "credenciales incompletas"
        raise HTTPException(
            status_code=503,
            detail=f"MeLi no configurado completamente en API. Faltan: {missing_text}.",
        )
    try:
        url = meli_client.get_auth_url(tenant_id, supabase)
        return {"auth_url": url}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/meli/callback")
async def meli_oauth_callback(
    code: str = Query(...),
    state: Optional[str] = Query(default=None),
):
    """
    Callback OAuth de MeLi. Llamado directamente por el browser después de la autorización.
    NO requiere JWT — el tenant_id se obtiene de un state firmado y de un solo uso.
    Solo si state es válido, no expirado y no reutilizado, intercambia code por tokens
    y los almacena en tenant_integrations.
    """
    if not state:
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=missing_state")

    supabase = _get_service_client()
    tenant_id = meli_client.validate_and_consume_oauth_state(supabase, state)
    if not tenant_id:
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=invalid_state")

    try:
        token_data = await meli_client.exchange_code(code)
    except Exception as e:
        logger.error("Error intercambiando code MeLi: %s", e)
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=token_exchange_failed")

    try:
        expires_in = token_data.get("expires_in", 21600)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        vault = VaultHelper(supabase)

        # Leer secret_ids existentes para update-or-create
        existing = (
            supabase.table("tenant_integrations").select("credentials")
            .eq("tenant_id", tenant_id).eq("provider", "mercadolibre")
            .maybe_single().execute()
        )
        existing_creds = (existing.data or {}).get("credentials", {})

        at = token_data.get("access_token", "")
        rt = token_data.get("refresh_token", "")

        at_sid = existing_creds.get("access_token_secret_id")
        rt_sid = existing_creds.get("refresh_token_secret_id")

        if at_sid:
            vault.update_secret(at_sid, at)
        else:
            at_sid = vault.create_secret(at, f"{tenant_id}/meli/access_token", "MeLi access token")

        if rt_sid:
            vault.update_secret(rt_sid, rt)
        else:
            rt_sid = vault.create_secret(rt, f"{tenant_id}/meli/refresh_token", "MeLi refresh token")

        if not at_sid:
            return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=vault_failed")

        supabase.table("tenant_integrations").upsert({
            "tenant_id": tenant_id,
            "provider": "mercadolibre",
            "status": "connected",
            "credentials": {
                "access_token_secret_id":  at_sid,
                "refresh_token_secret_id": rt_sid,
                "expires_in":  expires_in,
                "expires_at":  expires_at,
            },
            "meta": {
                "user_id":    str(token_data.get("user_id", "")),
                "scope":      token_data.get("scope", ""),
                "token_type": token_data.get("token_type", "Bearer"),
            },
        }, on_conflict="tenant_id,provider").execute()
    except Exception as e:
        logger.error("Error guardando tokens MeLi tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=storage_failed")

    return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?connected=mercadolibre")


@router.delete("/meli", status_code=204)
@audit_log(entity_type="integration", action="disconnected")
async def disconnect_meli(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """
    Desconecta MeLi: revoca el token en MeLi (detiene webhooks) y limpia localmente.
    El disconnect local ocurre aunque la revocación falle — nunca queda bloqueado.
    Solo owner.
    """
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede desconectar integraciones")

    creds_res = (
        supabase.table("tenant_integrations").select("credentials")
        .eq("tenant_id", tenant_id).eq("provider", "mercadolibre")
        .maybe_single().execute()
    )
    creds = (creds_res.data or {}).get("credentials", {})
    vault = VaultHelper(supabase)

    # Leer access_token desde Vault para poder revocarlo en MeLi
    access_token = vault.read_secret(creds.get("access_token_secret_id"))
    if access_token:
        try:
            await meli_client.revoke_token(access_token)
        except Exception as e:
            logger.warning("No se pudo revocar token MeLi tenant %s: %s", tenant_id, e)

    # Eliminar secretos de Vault
    vault.delete_secret(creds.get("access_token_secret_id"))
    vault.delete_secret(creds.get("refresh_token_secret_id"))

    supabase.table("tenant_integrations").update({
        "status": "disconnected", "credentials": {}, "meta": {},
    }).eq("tenant_id", tenant_id).eq("provider", "mercadolibre").execute()
    logger.info("MeLi desconectado para tenant %s", tenant_id)

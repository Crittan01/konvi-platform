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
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, get_current_role
from integrations import meli_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Integrations"])

FRONTEND_INTEGRATIONS_URL = "https://commerce-ops-web.onrender.com/dashboard/integrations"


# ─── Modelos ─────────────────────────────────────────────────────────────────

class EnviaConnect(BaseModel):
    api_token: str = Field(..., min_length=10)
    sandbox: bool = Field(default=False)


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
async def connect_envia(
    body: EnviaConnect,
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
        result = supabase.table("tenant_integrations").upsert({
            "tenant_id": tenant_id,
            "provider": "envia",
            "status": "connected",
            "credentials": {
                "api_token": body.api_token,
                "sandbox": body.sandbox,
            },
            "meta": {
                "token_preview": _mask_token(body.api_token),
                "environment": "sandbox" if body.sandbox else "production",
            },
        }, on_conflict="tenant_id,provider").execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al guardar integración")

        data = result.data[0]
        data.pop("credentials", None)  # No retornar credenciales
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error conectando Envia tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al conectar Envia")


@router.delete("/envia", status_code=204)
async def disconnect_envia(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Desconecta Envia borrando credenciales. Solo owner."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede desconectar integraciones")
    supabase.table("tenant_integrations").update({
        "status": "disconnected",
        "credentials": {},
    }).eq("tenant_id", tenant_id).eq("provider", "envia").execute()


# ── MeLi ───────────────────────────────────────────────────────────────────

@router.get("/meli/auth-url")
async def get_meli_auth_url(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
):
    """Retorna la URL de autorización OAuth de MeLi. Solo owner."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede conectar integraciones")
    if not meli_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail="MeLi no configurado en la plataforma. Se requiere IH-007 (registrar app MeLi)."
        )
    try:
        url = meli_client.get_auth_url(tenant_id)
        return {"auth_url": url}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/meli/callback")
async def meli_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """
    Callback OAuth de MeLi. Llamado directamente por el browser después de la autorización.
    NO requiere JWT — el tenant_id se obtiene del state parameter.
    Intercambia el code por tokens y los almacena en tenant_integrations.
    """
    from dependencies.auth import _get_service_client

    tenant_id = meli_client.decode_state(state)
    if not tenant_id:
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=invalid_state")

    try:
        token_data = await meli_client.exchange_code(code)
    except Exception as e:
        logger.error("Error intercambiando code MeLi: %s", e)
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=token_exchange_failed")

    try:
        supabase = _get_service_client()
        supabase.table("tenant_integrations").upsert({
            "tenant_id": tenant_id,
            "provider": "mercadolibre",
            "status": "connected",
            "credentials": {
                "access_token":  token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "expires_in":    token_data.get("expires_in"),
            },
            "meta": {
                "user_id":     str(token_data.get("user_id", "")),
                "scope":       token_data.get("scope", ""),
                "token_type":  token_data.get("token_type", "Bearer"),
            },
        }, on_conflict="tenant_id,provider").execute()
    except Exception as e:
        logger.error("Error guardando tokens MeLi tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=storage_failed")

    return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?connected=mercadolibre")


@router.delete("/meli", status_code=204)
async def disconnect_meli(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Desconecta MeLi revocando tokens locales. Solo owner."""
    if role != "owner":
        raise HTTPException(status_code=403, detail="Solo el owner puede desconectar integraciones")
    supabase.table("tenant_integrations").update({
        "status": "disconnected",
        "credentials": {},
        "meta": {},
    }).eq("tenant_id", tenant_id).eq("provider", "mercadolibre").execute()

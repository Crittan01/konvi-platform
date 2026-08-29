"""
Router de Integraciones — Gestión de conexiones MeLi y Aveonline por tenant.

Endpoints:
  GET    /api/v1/integrations/                — estado de todas las integraciones del tenant
  GET    /api/v1/integrations/meli/auth-url   — URL OAuth para iniciar flujo MeLi [owner]
  GET    /api/v1/integrations/meli/callback   — callback OAuth (browser redirect) — NO requiere JWT
  DELETE /api/v1/integrations/meli            — desconectar MeLi            [owner]
  POST   /api/v1/integrations/aveonline/*     — gestión Aveonline (provider único shipping, ADR-0019)

Post-rev. 109: Envia eliminado del runtime. Para añadir Courier N+1 seguir
ADR-0023 (Shipping Provider Integration Pattern).
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    _get_service_client,
    get_current_role,
    get_current_tenant,
    get_service_client,
)
from dependencies.internal_auth import (
    get_role_internal_or_user,
    get_service_client_internal_or_user,
    get_tenant_id_internal_or_user,
)
from dependencies.plans import PLAN_INTEGRATIONS_MELI
from dependencies.security import RL_WRITE_DEFAULT
from integrations import meli_client
from vault_helper import VaultHelper

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Integrations"])

FRONTEND_BASE_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
FRONTEND_INTEGRATIONS_URL = f"{FRONTEND_BASE_URL}/dashboard/integrations"


# ─── Modelos ─────────────────────────────────────────────────────────────────

# Nota rev. 109: EnviaConnect + EnviaCarrierUpsert eliminados con el pivote
# a Aveonline (ADR-0019). Aveonline tiene sus propios models en endpoints
# /aveonline/* más abajo.


class AveonlineCarrierItem(BaseModel):
    """Rev. 108 — preferencias per-tenant para carriers Aveonline.

    Diferencia vs Envia: incluye `supports_cod` opt-in del tenant
    (Aveonline tiene comisiones COD variables por carrier — dossier §7.2).
    """
    carrier_code: str = Field(..., min_length=1, max_length=64)
    enabled: bool = Field(default=True)
    display_label: Optional[str] = Field(default=None, max_length=120)
    priority: int = Field(default=100, ge=0, le=999)
    notes: Optional[str] = Field(default=None, max_length=500)
    supports_cod: bool = Field(default=False)


class AveonlineCarriersBulk(BaseModel):
    """Bulk update — sustituye preferencias completas del tenant."""
    items: list[AveonlineCarrierItem] = Field(default_factory=list, max_length=50)


class WhatsAppCredentialsInput(BaseModel):
    """F3 activación — las 6 credenciales que un tenant entrega de SU Meta App (ADR-0023 Model B).
    app_secret + access_token se cifran en Vault; el resto va en tenant_integrations.credentials."""
    app_id: str = Field(..., min_length=1, max_length=64)
    app_secret: str = Field(..., min_length=8)
    verify_token: str = Field(..., min_length=1, max_length=200)
    phone_number_id: str = Field(..., min_length=1, max_length=64)
    waba_id: str = Field(..., min_length=1, max_length=64)
    access_token: str = Field(..., min_length=20)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mask_token(token: str) -> str:
    """Retorna los primeros 6 y últimos 4 chars para mostrar en UI sin exponer el token."""
    if len(token) <= 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/whatsapp/credentials", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])  # F25: escribe secretos a Vault
@audit_log(entity_type="integration", action="connected")
def upsert_whatsapp_credentials(
    payload: WhatsAppCredentialsInput,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """F3 activación (ADR-0023 Model B) — captura self-service de las credenciales WhatsApp del tenant:
    app_secret + access_token → Vault (cifrado); app_id/verify_token/phone_number_id/waba_id + los
    secret_id → tenant_integrations.credentials (shape EXACTO que el connector lee). Solo owner/manager.
    Idempotente: reusa los secret_id existentes (update in-place) para no dejar secretos huérfanos."""
    if role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Solo owner/manager pueden configurar integraciones")
    vault = VaultHelper(supabase)
    existing = (
        supabase.table("tenant_integrations").select("credentials")
        .eq("tenant_id", tenant_id).eq("provider", "whatsapp").limit(1).execute()
    )
    existing_creds = (existing.data or [{}])[0].get("credentials") or {}
    as_sid = existing_creds.get("app_secret_secret_id")
    at_sid = existing_creds.get("access_token_secret_id")

    if as_sid:
        vault.update_secret(as_sid, payload.app_secret)
    else:
        as_sid = vault.create_secret(payload.app_secret, f"{tenant_id}/whatsapp/app_secret", "WhatsApp App Secret")
    if at_sid:
        vault.update_secret(at_sid, payload.access_token)
    else:
        at_sid = vault.create_secret(payload.access_token, f"{tenant_id}/whatsapp/access_token", "WhatsApp access token")
    if not (as_sid and at_sid):
        raise HTTPException(status_code=500, detail="No se pudieron guardar las credenciales en Vault")

    supabase.table("tenant_integrations").upsert({
        "tenant_id": tenant_id,
        "provider": "whatsapp",
        "status": "connected",
        "credentials": {
            "app_id": payload.app_id,
            "app_secret_secret_id": as_sid,
            "verify_token": payload.verify_token,
            "phone_number_id": payload.phone_number_id,
            "waba_id": payload.waba_id,
            "access_token_secret_id": at_sid,
            "access_token_rotated_at": datetime.now(timezone.utc).isoformat(),
        },
        "meta": {"integration_type": "direct_provider"},  # ADR-0023 Model B
    }, on_conflict="tenant_id,provider").execute()

    # El webhook WhatsApp lo sirve el servicio CONNECTOR (konvi-connector.onrender.com), NO la API.
    # Antes el default era api.konvi.co (NXDOMAIN, sin DNS) → rompía el handshake Meta día-1 y el
    # onboarding self-service Model B. Default al host LIVE del connector; overridable por
    # WHATSAPP_CONNECTOR_URL cuando el DNS entre (connector.konvi.co, ADR-0023 OQ-4). DEBE coincidir
    # con el frontend (CONNECTOR_WEBHOOK_HOST en webhook-urls.ts).
    webhook_base = os.getenv("WHATSAPP_CONNECTOR_URL", "https://konvi-connector.onrender.com").rstrip("/")
    return {
        "status": "connected",
        "provider": "whatsapp",
        "webhook_url": f"{webhook_base}/api/v1/whatsapp/webhook/{tenant_id}",
    }


@router.get("/", response_model=list)
def list_integrations(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista el estado de todas las integraciones del tenant (MeLi, Aveonline, Wompi,
    WhatsApp; Envia eliminado del runtime — ADR-0019)."""
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

        # Nota rev. 109: Envia eliminado del listado (ADR-0019).
        # Aveonline aparece automáticamente vía rows si está conectado.

        return rows
    except Exception as e:
        logger.error("Error listando integraciones tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener integraciones")


# Nota rev. 109: bloque Envia eliminado (ADR-0019). Endpoints `/envia`,
# `/envia/carriers/*` removidos junto con sus models. Aveonline tiene
# endpoints equivalentes en `/aveonline/*` más abajo.


# ── MeLi ───────────────────────────────────────────────────────────────────

@router.get("/meli/auth-url")
def get_meli_auth_url(
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

        # Leer secret_ids existentes + meta para update-or-create
        existing = (
            supabase.table("tenant_integrations").select("credentials, meta")
            .eq("tenant_id", tenant_id).eq("provider", "mercadolibre")
            .maybe_single().execute()
        )
        existing_creds = (existing.data or {}).get("credentials", {})
        existing_meta = (existing.data or {}).get("meta", {}) or {}

        # Rev. 108 Layer C — detectar same-user reconnect.
        # Si el usuario hizo disconnect (que persistió last_disconnected_user_id
        # en meta) y ahora el OAuth callback retorna EL MISMO user_id, MeLi
        # le auto-confirmó (no cambió de cuenta). Flag para que UI alerte.
        last_disconnected_user_id = existing_meta.get("last_disconnected_user_id")
        new_user_id = str(token_data.get("user_id", ""))
        same_user_reconnect = bool(
            last_disconnected_user_id
            and new_user_id
            and last_disconnected_user_id == new_user_id
        )
        if same_user_reconnect:
            logger.info(
                "[MELI_OAUTH] tenant=%s reconectó con MISMA cuenta MeLi user_id=%s "
                "(post-disconnect). MeLi auto-confirmó por sesión activa.",
                tenant_id[:8], new_user_id,
            )

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

        # ML reliability (ADR-0037): al RECONECTAR, resetear el contador de fallos consecutivos y
        # limpiar cualquier lease de refresh residual. Sin esto, una integración que murió (count=3,
        # status='error') vuelve a 'connected' arrastrando count=3 → el primer fallo de refresh
        # post-reconnect (incluso un 400 transitorio) la re-marcaría 'error' de inmediato (la
        # protección de "N fallos consecutivos" sería nula). Best-effort SEPARADO del upsert: si la
        # migración de las columnas aún no se aplicó, no debe romper el callback OAuth (path crítico).
        try:
            supabase.table("tenant_integrations").update({
                "refresh_fail_count": 0,
                "refresh_lease_until": None,
                "refresh_lease_token": None,
            }).eq("tenant_id", tenant_id).eq("provider", "mercadolibre").execute()
        except Exception:
            pass
    except Exception as e:
        logger.error("Error guardando tokens MeLi tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{FRONTEND_INTEGRATIONS_URL}?error=storage_failed")

    # Rev. 108 Layer C — pasar flag al frontend si fue same-user reconnect
    # para que UI muestre banner: "Te conectaste con la misma cuenta MeLi.
    # Si querías cambiar, desconecta + cierra sesión MeLi + reconecta".
    suffix = "&meli_same_user=1" if same_user_reconnect else ""
    return RedirectResponse(
        f"{FRONTEND_INTEGRATIONS_URL}?connected=mercadolibre{suffix}"
    )


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
        supabase.table("tenant_integrations").select("credentials, meta")
        .eq("tenant_id", tenant_id).eq("provider", "mercadolibre")
        .maybe_single().execute()
    )
    creds = (creds_res.data or {}).get("credentials", {})
    meta_pre = (creds_res.data or {}).get("meta", {}) or {}
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

    # Rev. 108 (founder 2026-05-27 — disconnect+reconnect auto-loguea
    # mismo user MeLi). Layer C: persistir user_id previo en
    # meta.last_disconnected_user_id para que el callback post-reconnect
    # pueda detectar si el OAuth retornó el MISMO usuario y avisar al
    # tenant si pretendía cambiar de cuenta.
    last_user_id = (
        meta_pre.get("user_id")
        or meta_pre.get("seller_id")
        or creds.get("user_id")
        or creds.get("seller_id")
    )
    new_meta = {}
    if last_user_id:
        new_meta["last_disconnected_user_id"] = str(last_user_id)

    supabase.table("tenant_integrations").update({
        "status": "disconnected", "credentials": {}, "meta": new_meta,
    }).eq("tenant_id", tenant_id).eq("provider", "mercadolibre").execute()
    logger.info(
        "MeLi desconectado para tenant %s (last_user_id=%s persisted en meta)",
        tenant_id, last_user_id or "—",
    )


# ─── Telegram: revocar identidad de operador al desconectar ──────────────────


@router.delete("/telegram/identity", status_code=204)
@audit_log(entity_type="integration", action="disconnected")
def revoke_telegram_identity(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Fase 0 F7 (seguridad) — al desconectar Telegram, revoca la identidad del
    operador en `tenant_provider_identity` (provider='telegram', chat_id).

    Sin esto, un ex-operador cuyo chat_id sigue mapeado CONSERVA autoridad para
    ejecutar comandos /resolver · /estado sobre las conversaciones del tenant
    (hueco de escalación). El DELETE directo de esa tabla NO es posible desde el
    cliente autenticado (RLS solo permite SELECT por GUC de tenant), por eso la
    Console lo delega a este endpoint (service_role), igual que `disconnect_meli`.

    Idempotente: 204 aunque no exista identidad. El chat_id se deriva de
    `notification_settings` del PROPIO tenant (scoped por tenant_id) y solo se
    revoca si la identidad pertenece a este tenant — un tenant no puede borrar la
    identidad de otro. Solo owner/manager (paridad con save/disconnect Telegram).
    """
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail="Solo owner/manager pueden desconectar Telegram",
        )

    settings_res = (
        supabase.table("notification_settings")
        .select("config")
        .eq("tenant_id", tenant_id)
        .eq("channel", "telegram")
        .limit(1)
        .execute()
    )
    cfg = (settings_res.data or [{}])[0].get("config") or {}
    chat_id = cfg.get("chat_id")
    if not chat_id:
        # Nada mapeado (nunca se configuró chat_id o config ya vaciada) → no-op.
        logger.info("[TG] revoke_identity: tenant=%s sin chat_id — no-op", tenant_id)
        return

    from lib.identity_registry import (
        IdentityRegistryError,
        get_identity,
        revoke_identity,
    )

    try:
        ident = get_identity(supabase, "telegram", chat_id)
        # Defensa cross-tenant: solo revocamos si la identidad es de ESTE tenant.
        # UNIQUE(provider, internal_id) ya garantiza 1:1, este check es cinturón.
        if ident is not None and ident.tenant_id == tenant_id:
            revoke_identity(supabase, "telegram", chat_id)
            logger.info(
                "[TG] identity revocada tenant=%s chat=%s (disconnect)",
                tenant_id, chat_id,
            )
        else:
            logger.info(
                "[TG] revoke_identity: chat_id=%s no pertenece a tenant=%s — no-op",
                chat_id, tenant_id,
            )
    except IdentityRegistryError as exc:
        logger.error("[TG] revoke_identity falló tenant=%s: %s", tenant_id, exc)
        raise HTTPException(
            status_code=500,
            detail="No se pudo revocar la identidad del operador de Telegram",
        )


# ─── Telegram: setup del webhook del bot del tenant (Track 6 — cierra M17) ─────


@router.post("/telegram/setup", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="integration", action="telegram_setup")
async def telegram_setup(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Track 6 (cierra M17): registra el webhook del bot del tenant contra la
    Bot API oficial — antes era un paso manual con curl por fuera de la UI.

    Cadena (doc oficial core.telegram.org/bots/api, fetch live 2026-08-22):
      1. getMe — valida el token y entrega el username del bot.
      2. setWebhook — URL {PUBLIC_WEBHOOK_URL}/api/v1/integrations/telegram/webhook
         con secret_token=TELEGRAM_WEBHOOK_SECRET (así el inbound queda
         autenticado) y allowed_updates=["message", "callback_query"] (los
         comandos + el botón inline "✅ Resolver" de Track 6).
         drop_pending_updates=True: no se procesan updates viejos encolados.
      3. setMyCommands — menú de comandos del bot (/resolver /estado /ayuda).
      4. getWebhookInfo — verificación final (url + last_error_message).

    Solo owner/manager (paridad con save/disconnect Telegram). El token se
    resuelve desde Vault y NUNCA sale en la respuesta ni en logs.
    """
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail="Solo owner/manager pueden configurar el webhook de Telegram",
        )

    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="TELEGRAM_WEBHOOK_SECRET no configurado en el API",
        )

    # bot_token del tenant: notification_settings + Vault (fuente única ADR-0021).
    settings_res = (
        supabase.table("notification_settings")
        .select("config")
        .eq("tenant_id", tenant_id)
        .eq("channel", "telegram")
        .eq("enabled", True)
        .limit(1)
        .execute()
    )
    cfg = (settings_res.data or [{}])[0].get("config") or {}
    from vault_helper import VaultHelper, resolve_secret
    token = (resolve_secret(VaultHelper(supabase), dict(cfg), "bot_token") or "").strip()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Configura primero el bot de Telegram (token + chat_id) en Integraciones",
        )

    base_url = _public_webhook_base_url()
    if "YOUR_PUBLIC_HOST" in base_url:
        raise HTTPException(
            status_code=503,
            detail="PUBLIC_WEBHOOK_URL no configurada — no se puede registrar el webhook",
        )
    webhook_url = f"{base_url}/api/v1/integrations/telegram/webhook"
    api = f"https://api.telegram.org/bot{token}"

    async def _post(method: str, payload: dict) -> dict:
        """POST a la Bot API; 502 con la descripción de Telegram si falla."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{api}/{method}", json=payload)
            body = resp.json() if resp.content else {}
        except Exception as exc:
            logger.error("[TG_SETUP] %s unreachable tenant=%s: %s", method, tenant_id[:8], exc)
            raise HTTPException(status_code=502, detail=f"Telegram {method} no responde") from exc
        if not (200 <= resp.status_code < 300 and body.get("ok") is True):
            desc = body.get("description") or resp.text[:200]
            logger.warning(
                "[TG_SETUP] %s rechazado tenant=%s: %s", method, tenant_id[:8], desc,
            )
            raise HTTPException(status_code=502, detail=f"Telegram {method}: {desc}")
        return body.get("result") if body.get("result") is not None else True

    # 1. getMe — valida el token.
    me = await _post("getMe", {})
    bot_username = (me or {}).get("username", "")

    # 2. setWebhook — con secret_token (auth del inbound) + los update types que
    #    este módulo consume (comandos + callback_query del inline keyboard).
    await _post("setWebhook", {
        "url": webhook_url,
        "secret_token": webhook_secret,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    })

    # 3. setMyCommands — menú del bot (mismo set que /ayuda del webhook).
    await _post("setMyCommands", {
        "commands": [
            {"command": "resolver", "description": "Restaurar el bot en una conversación"},
            {"command": "estado", "description": "Consultar el estado de una conversación"},
            {"command": "ayuda", "description": "Lista de comandos disponibles"},
        ],
    })

    # 4. getWebhookInfo — verificación final (criterio de éxito documentado en
    #    docs/integrations/telegram.md: url registrada + last_error vacío).
    info = await _post("getWebhookInfo", {})
    logger.info(
        "[TG_SETUP] webhook registrado tenant=%s bot=@%s url=%s",
        tenant_id[:8], bot_username, (info or {}).get("url", ""),
    )
    return {
        "ok": True,
        "bot_username": bot_username,
        "webhook": {
            "url": (info or {}).get("url", ""),
            "pending_update_count": (info or {}).get("pending_update_count", 0),
            "last_error_message": (info or {}).get("last_error_message") or None,
        },
        "commands_registered": 3,
    }


# ─── Aveonline: listar agentes del tenant ────────────────────────────────────


@router.get("/aveonline/agents")
async def list_aveonline_agents(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
):
    """Lista los agentes (puntos de despacho) registrados en la cuenta
    Aveonline del tenant.

    Delega en `AveonlineClient.list_agents()` (endpoint oficial
    `listarAgentesPorEmpresaAuth`, doc
    `integraciones.aveonline.co/docs/nacional/agentes/listadoAgentes`).

    UX: tenant elige un agente del dropdown (en lugar de buscar el ID
    manualmente en el panel Aveonline). El `principal` se sugiere
    por default. Se persiste en `tenant_integrations.credentials.idagente`.
    Si el tenant nunca elige, el cliente auto-resuelve al principal en
    runtime (cache 24h) — ver `_resolve_idagente`.

    Permite a `owner` y `manager` — config operacional, no destructiva.
    """
    if role not in ("owner", "manager"):
        raise HTTPException(403, "Solo owner/manager pueden ver agentes")

    from integrations.aveonline_client import AveonlineClient

    client = AveonlineClient(supabase=supabase, tenant_id=tenant_id)
    try:
        creds = await client._load_credentials()
        result = await client.list_agents()
    except Exception as exc:
        raise HTTPException(
            502,
            f"No se pudo autenticar con Aveonline: {exc}. "
            f"Verifica que la integración esté conectada.",
        )

    if not result.get("ok"):
        return {
            "agents": [],
            "warning": result.get("message") or "sin agentes",
        }

    agents = sorted(
        result.get("agents") or [],
        key=lambda x: (not x["principal"], x["nombre"]),
    )
    return {
        "agents": agents,
        "current_idagente": creds.get("idagente") or None,
    }


# ─── Aveonline guide dry-run (UAT aislado, NO en producción flow) ────────────


class AveonlineGuideDryRunReq(BaseModel):
    """Request del endpoint UAT — `POST /aveonline/guide-dry-run`.

    Test aislado de `AveonlineClient.generate_guide()` con una orden real
    del tenant sin pasar por wompi_webhook hooks. Útil para:
      • Certificar body canónico vs dossier sec 4.
      • Identificar errores específicos (idagente missing, transportador
        inválido, etc.) sin acoplar a flow conversación.
      • Una vez certificado standalone, integrar a wompi_webhook con
        confianza.

    simulate=True por default — Aveonline NO factura. Pone
    `bloquegenerarguia="0"` y retorna guía dummy con shape canónico.
    Para guía real facturable: simulate=False (riesgo: factura asociada).
    """
    order_id: str = Field(..., min_length=8, max_length=64)
    simulate: bool = Field(
        default=True,
        description="True=NO factura (bloquegenerarguia=0). False=guía real.",
    )


@router.post("/aveonline/guide-dry-run")
async def aveonline_guide_dry_run(
    req: AveonlineGuideDryRunReq,
    # Dual-auth (A0.2c): JWT owner (Tenant Console) o X-Internal-Service-Secret
    # + X-Tenant-Id (ops/orchestrator) — el path interno resuelve role=owner.
    tenant_id: str = Depends(get_tenant_id_internal_or_user),
    role: str = Depends(get_role_internal_or_user),
    supabase: Client = Depends(get_service_client_internal_or_user),
):
    """UAT aislado de generate_guide. Solo `owner` puede invocar.

    Lee order + contact del tenant, construye payload canónico, invoca
    `AveonlineClient.generate_guide()`, retorna response detallado +
    diagnostics. NO persiste nada en `shipments` (es dry-run pure).
    """
    if role != "owner":
        raise HTTPException(403, "Solo el owner puede ejecutar dry-run")

    # 1. Cargar order + contact.
    order_res = (
        supabase.table("orders")
        .select(
            "id, total_amount, shipping_cost, notes, contact_id, "
            "contacts(name, email, phone, shipping_phone, "
            "document_type, document_number, address)"
        )
        .eq("id", req.order_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    order = (order_res.data if order_res else None) or {}
    if not order.get("id"):
        raise HTTPException(404, f"Order {req.order_id[:8]} no encontrada")
    contact = order.get("contacts") or {}
    if not contact.get("name") or not contact.get("phone"):
        raise HTTPException(
            422,
            "Order tiene contact incompleto (falta name o phone). "
            "Aveonline rechazará la guía con error -9 o -12.",
        )
    address = contact.get("address") or {}

    # 2. Cargar shipping_meta del cart QUE CONVIRTIÓ A ESTA ORDEN (carrier seleccionado).
    # BUG F5 (guía cruzada): antes tomaba el ÚLTIMO cart del TENANT (order by created_at) → bajo
    # concurrencia la guía de la orden A usaba el shipping_meta del cart de la orden B. Ahora se filtra
    # por converted_order_id = esta orden (link exacto); sin cart vinculado → shipping_meta vacío → path "sin rate".
    cart_res = (
        supabase.table("conversation_carts")
        .select("shipping_meta")
        .eq("tenant_id", tenant_id)
        .eq("converted_order_id", req.order_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    cart = (cart_res.data or [{}])[0]
    shipping_meta = cart.get("shipping_meta") or {}
    rate_id = shipping_meta.get("rate_id")
    carrier_name = shipping_meta.get("carrier") or ""
    if not rate_id:
        return {
            "ok": False,
            "error": "Cart no tiene rate_id (carrier) seleccionado. "
                     "Necesitas correr quote_shipping + select_carrier antes.",
            "code": "NO_CARRIER_SELECTED",
            "diagnostics": {
                "order_id": req.order_id,
                "shipping_meta": shipping_meta,
            },
        }

    # 3. Cargar tenant shipping origin. Schema real: el origen vive en
    # `tenants.shipping_origin` JSONB (keys: city, state, street, dane_code,
    # phone, name, company, country, postal_code) y nit/teléfono/email en las
    # columnas planas de contacto — mismo select que el flujo real
    # (wompi_webhook._generate_shipping_guide_async).
    tenant_res = (
        supabase.table("tenants")
        .select("name, shipping_origin, telefono_contacto, email_contacto, nit")
        .eq("id", tenant_id).single().execute()
    )
    tenant = tenant_res.data or {}
    tenant_origin = tenant.get("shipping_origin") or {}
    # Misma validación "origin completo" del flujo real (wompi_webhook.py):
    # sin city/street Aveonline rechaza la guía — 422 explícito aquí.
    if not tenant_origin.get("city") or not tenant_origin.get("street"):
        raise HTTPException(
            422,
            "Tenant sin shipping_origin completo (falta city o street). "
            "Configura la dirección de despacho en Settings antes del dry-run.",
        )

    # 4. Construir payload canónico.
    from integrations.aveonline_client import (
        AveonlineAuthError,
        AveonlineClient,
        AveonlinePermanentError,
        AveonlineTransientError,
        to_aveonline_city_format,
    )
    from lib.dane_resolver import resolve_dane_from_city
    client = AveonlineClient(supabase=supabase, tenant_id=tenant_id)
    # `idagente` (dirección de despacho Aveonline) NO vive en tenants: se lee
    # de las credenciales de la integración. Aquí solo para diagnostics — el
    # cliente lo auto-resuelve internamente al generar (credentials.idagente →
    # listarAgentes principal con cache 24h, ver `_resolve_idagente`). El
    # fallback histórico a `asesor_logistico` se eliminó 2026-08-22: es el
    # asesor COMERCIAL de la cuenta, no un agente de despacho.
    try:
        _creds = await client._load_credentials()
    except Exception:
        _creds = {}
    idagente = str(_creds.get("idagente") or "")

    # Bug fix rev. 109 (2026-05-31): Aveonline `generarGuia2` rechaza destino
    # sin DANE. Precedencia: shipping_meta.dane_code (resuelto al cotizar) →
    # contact.address.dane_code (si save_address persistió) → DIVIPOLA fallback.
    # Origin: dane_code del jsonb → DIVIPOLA; city en formato canónico
    # Aveonline ("BOGOTA(CUNDINAMARCA)") — ambos igual que el flujo real.
    origin_city_norm = to_aveonline_city_format(
        str(tenant_origin.get("city") or ""),
        str(tenant_origin.get("state") or ""),
    )
    origin = {
        "dane": (
            str(tenant_origin.get("dane_code") or "")
            or resolve_dane_from_city(
                str(tenant_origin.get("city") or ""),
                tenant_origin.get("state"),
            )
        ),
        "city": origin_city_norm or str(tenant_origin.get("city") or ""),
    }
    destination = {
        "dane": (
            str(shipping_meta.get("dane_code") or "")
            or str(address.get("dane_code") or "")
            or resolve_dane_from_city(
                str(address.get("city") or ""),
                address.get("state"),
            )
        ),
        "city": str(address.get("city") or ""),
    }
    # F5: peso/dims REALES cotizados (el quote los persiste en shipping_meta.weight_inputs). La guía los
    # REUSA para que Aveonline reciba el peso real y no dispare reajuste retroactivo en la factura semanal.
    # Fallback a defaults SOLO si el cart no los tiene (p.ej. guía manual sin cotización previa).
    _wi = shipping_meta.get("weight_inputs") or {}
    package = {
        "weight_kg": float(_wi.get("weight_kg") or 0.5),
        "length_cm": float(_wi.get("length_cm") or 15),
        "width_cm": float(_wi.get("width_cm") or 10),
        "height_cm": float(_wi.get("height_cm") or 5),
        "declared_value_cop": int(order.get("total_amount") or 50000),
        "units": 1,
        "content": "Productos KAIU — dry-run",
    }
    carrier_payload = {
        "idtransportador": str(rate_id),
        "service_level": str(shipping_meta.get("service_level") or ""),
    }
    # Sender idéntico al flujo real (wompi_webhook): nit/email/teléfono de las
    # columnas planas de contacto; nombre/dirección del jsonb shipping_origin.
    sender = {
        "nit": str(tenant.get("nit") or ""),
        "nombre": str(tenant_origin.get("name") or tenant.get("name") or "")[:80],
        "direccion": str(tenant_origin.get("street") or ""),
        "barrio": "",
        "telefono": str(tenant.get("telefono_contacto") or tenant_origin.get("phone") or ""),
        "celular": str(tenant.get("telefono_contacto") or tenant_origin.get("phone") or ""),
        "email": str(tenant.get("email_contacto") or ""),
    }
    recipient = {
        "doc": str(contact.get("document_number") or ""),
        "nombre": str(contact.get("name") or ""),
        # A2 finiquito 2026-06-23: schema canónico `street` (rev. 110).
        # Fallback `line1` defensivo durante ventana migración (regla #4).
        "direccion": str(address.get("street") or address.get("line1") or ""),
        "barrio": "",
        "telefono": str(contact.get("shipping_phone") or contact.get("phone") or ""),
        "celular": str(contact.get("shipping_phone") or contact.get("phone") or ""),
        "email": str(contact.get("email") or ""),
    }

    # 5. Invocar generate_guide.
    # BLOQUE B (item 3): techo per-tenant. Aunque el operador pida simulate=False, un tenant
    # sin real_guides_enabled (o con el master global off) NUNCA factura una guía real. La
    # activación de guías reales es acción founder deliberada por-tenant (default fail-safe).
    effective_simulate = req.simulate
    if not effective_simulate:
        try:
            _cfg = (
                supabase.table("tenant_shipping_provider_config")
                .select("real_guides_enabled")
                .eq("tenant_id", tenant_id)
                .maybe_single()
                .execute()
            )
            _tenant_real = bool((_cfg.data or {}).get("real_guides_enabled"))
        except Exception:
            _tenant_real = False
        _master_real = os.getenv("AVEONLINE_GENERATE_REAL_GUIDES", "false").lower() == "true"
        if not (_master_real and _tenant_real):
            logger.info(
                "[AVEONLINE][dry-run] tenant=%s pidió simulate=False pero no está habilitado "
                "para guías reales → forzando simulate=True (fail-safe)", tenant_id[:8],
            )
            effective_simulate = True
    try:
        result = await client.generate_guide(
            origin=origin, destination=destination,
            package=package, carrier=carrier_payload,
            sender=sender, recipient=recipient,
            simulate=effective_simulate,
        )
    except AveonlineAuthError as exc:
        return {"ok": False, "error": str(exc), "code": "AUTH_ERROR"}
    except AveonlineTransientError as exc:
        return {"ok": False, "error": str(exc), "code": "TRANSIENT_ERROR"}
    except AveonlinePermanentError as exc:
        return {"ok": False, "error": str(exc), "code": "PERMANENT_ERROR"}

    # 6. Retornar response + diagnostics.
    return {
        "ok": bool(result.get("ok")),
        "result": result,
        "diagnostics": {
            "tenant_idagente": idagente or None,
            "carrier_selected": carrier_name,
            "rate_id": rate_id,
            "origin": origin,
            "destination": destination,
            "simulate": effective_simulate,
            "simulate_requested": req.simulate,
            "warning_idagente_missing": not idagente,
        },
    }


# ─── Aveonline: webhook estados de guía (Rev. 108) ───────────────────────────
# Endpoints para configurar / rotar / consultar / eliminar el webhook
# `webhookEstadosGuias` de Aveonline para este tenant.
#
# Flujo configure (2026-08-22 — oficial primero, legacy fallback):
#   1. OFICIAL (`webhookPersonalizadoApi`): `register_custom_webhook` hace
#      upsert por empresa (única URL de tracking por cuenta); Aveonline
#      devuelve `data.token` y lo reenvía top-level en cada POST → su hash
#      bcrypt se persiste vía `store_external_secret` (con grace period).
#   2. FALLBACK legacy AveCRM: backend genera UUIDv4 plaintext, lo hashea
#      (F.10), lo persiste en `tenant_webhook_secrets` y llama
#      `AveonlineClient.create_webhook` (avestock) con URL + plaintext como
#      param1. Retorna URL + plaintext UNA VEZ.
#   En ambos casos el response incluye `mechanism` para diagnóstico.
#
# Flujo rotate:
#   1. Mismo doble camino (rotate = configure).
#   2. El hash anterior pasa a `previous_secret_hash` con `grace_period_until`
#      = now+7d (Aveonline puede seguir enviando con el viejo durante la
#      migración del panel).


def _public_webhook_base_url() -> str:
    """URL pública del API donde Aveonline hará POST.

    En prod: `https://api.konvi.co` (dominio propio LIVE desde 2026-08-27,
    Track 3.1 — seteado vía `PUBLIC_WEBHOOK_URL` en Render). En local: env var
    `PUBLIC_WEBHOOK_URL` (ngrok). El endpoint final es:
      `{base}/api/v1/webhooks/aveonline/{tenant_id}` (secret en body
      como param1_value) — coherente con docstring del router.
    """
    base = os.getenv("PUBLIC_WEBHOOK_URL", "").rstrip("/")
    if not base:
        # Fallback razonable cuando PUBLIC_WEBHOOK_URL no está seteada
        # (dev local sin ngrok). El tenant verá la URL como placeholder y
        # puede setear env antes de prod.
        base = "https://YOUR_PUBLIC_HOST"
    return base


def _build_aveonline_webhook_url(tenant_id: str) -> str:
    """URL completa que se registra en Aveonline para este tenant."""
    return f"{_public_webhook_base_url()}/api/v1/webhooks/aveonline/{tenant_id}"


@router.get("/aveonline/webhook")
def aveonline_webhook_status(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
):
    """Retorna estado del webhook Aveonline configurado para el tenant.

    Response shape:
      {
        "configured": bool,
        "url": str,
        "rotated_at": iso8601 | None,
        "expires_at": iso8601 | None,
        "has_grace_period": bool,
        "audit_log_count": int,
      }

    NO devuelve secret plaintext — eso solo se entrega al rotar/configurar.
    """
    if role not in ("owner", "manager"):
        raise HTTPException(403, "Solo owner/manager pueden ver webhook config")

    from lib.webhook_secret_manager import get_record

    record = get_record(supabase, tenant_id, "aveonline")
    url = _build_aveonline_webhook_url(tenant_id)
    if not record:
        return {
            "configured": False,
            "url": url,
            "rotated_at": None,
            "expires_at": None,
            "has_grace_period": False,
            "audit_log_count": 0,
        }
    return {
        "configured": True,
        "url": url,
        "rotated_at": record.rotated_at,
        "expires_at": record.expires_at,
        "has_grace_period": record.is_in_grace_period,
        "audit_log_count": len(record.audit_log),
    }


@router.post("/aveonline/webhook/configure", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def aveonline_webhook_configure(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
):
    """Configura webhook por primera vez (o lo rota si ya existía).

    Pasos:
      1. Intenta el mecanismo OFICIAL vigente (`webhookPersonalizadoApi`):
         upsert por empresa vía `register_custom_webhook` — Aveonline genera
         el token y lo reenvía top-level en cada POST; su hash se persiste
         via `store_external_secret` (grace period igual que una rotación).
      2. Fallback LEGACY AveCRM (`createWebhook.php` con param1 secret
         generado localmente) si el oficial no está disponible para la
         cuenta — comportamiento previo a 2026-08-22.

    Response:
      {
        "ok": bool,
        "url": str,
        "mechanism": "custom-webhook" | "legacy-avestock" | None,
        "plaintext_secret": str,   # SOLO UNA VEZ
        "aveonline_registered": bool,
        "aveonline_message": str,
      }
    """
    if role != "owner":
        raise HTTPException(
            403, "Solo el owner puede configurar webhooks de integraciones",
        )

    from lib.webhook_secret_manager import rotate_secret, store_external_secret

    url = _build_aveonline_webhook_url(tenant_id)

    aveonline_registered = False
    aveonline_message = ""
    mechanism: str | None = None
    rotation = None
    plaintext = ""

    from integrations.aveonline_client import AveonlineClient
    client = AveonlineClient(tenant_id=tenant_id, supabase=supabase)

    # 1) OFICIAL: custom-webhook (upsert por empresa; token generado por
    #    Aveonline). Si responde OK con token → persistir hash de ESE token.
    try:
        official = await client.register_custom_webhook(
            name=f"Konvi tracking {tenant_id[:8]}",
            webhook_url=url,
        )
        if official.get("ok") and official.get("token"):
            rotation = store_external_secret(
                supabase, tenant_id=tenant_id, integration="aveonline",
                plaintext=official["token"],
                actor_id=None,  # FastAPI Depends de user no se incluyó — futuro F2.
                reason="aveonline_webhook_configure_official",
            )
            plaintext = official["token"]
            aveonline_registered = True
            mechanism = "custom-webhook"
            aveonline_message = official.get("message") or ""
            logger.info(
                "[AVEONLINE_WH_CFG] official register tenant=%s updated=%s msg=%s",
                tenant_id, official.get("updated"), aveonline_message,
            )
        else:
            aveonline_message = (
                official.get("message") or "custom-webhook sin token en response"
            )
            logger.warning(
                "[AVEONLINE_WH_CFG] official register not-ok tenant=%s: %s — "
                "fallback legacy",
                tenant_id, aveonline_message,
            )
    except Exception as exc:
        logger.warning(
            "[AVEONLINE_WH_CFG] official register err tenant=%s: %s — "
            "fallback legacy",
            tenant_id, exc,
        )
        aveonline_message = f"custom-webhook: {exc}"

    # 2) FALLBACK LEGACY (AveCRM avestock con secret local en param1).
    if not aveonline_registered:
        rotation = rotate_secret(
            supabase, tenant_id=tenant_id, integration="aveonline",
            actor_id=None,  # FastAPI Depends de user no se incluyó — futuro F2.
            reason="aveonline_webhook_configure",
        )
        plaintext = rotation.plaintext_secret
        try:
            # Defensive: borrar webhook viejo con misma URL si existe.
            try:
                await client.delete_webhook(url=url)
            except Exception as exc:
                logger.info(
                    "[AVEONLINE_WH_CFG] delete_webhook previo falló (esperable "
                    "si era primera config): %s",
                    exc,
                )

            result = await client.create_webhook(
                url=url,
                secret=plaintext,
                extra_params={"tenant_id": tenant_id, "source": "konvi"},
            )
            aveonline_registered = bool(result.get("ok"))
            if aveonline_registered:
                mechanism = "legacy-avestock"
            legacy_msg = result.get("message") or ""
            aveonline_message = (
                f"{aveonline_message} | legacy: {legacy_msg}"
                if aveonline_message else legacy_msg
            )
            logger.info(
                "[AVEONLINE_WH_CFG] legacy register tenant=%s ok=%s msg=%s",
                tenant_id, aveonline_registered, legacy_msg,
            )
        except Exception as exc:
            logger.warning(
                "[AVEONLINE_WH_CFG] legacy register err tenant=%s: %s",
                tenant_id, exc,
            )
            aveonline_message = (
                f"{aveonline_message} | legacy error: {exc}"
                if aveonline_message else f"error registrando en Aveonline: {exc}"
            )

    # Audit nota: `audit_log` en este repo es un decorador FastAPI (opt-in
    # via @audit_log(...) sobre handlers). Para auditoría imperativa el
    # registro queda implícito en `tenant_webhook_secrets.audit_log` JSONB
    # via `rotate_secret()`/`store_external_secret()` arriba — esa fila
    # lleva el historial de eventos (created|rotated|revoked, actor_id,
    # reason, timestamp).
    logger.info(
        "[AVEONLINE_WH_CFG] tenant=%s configured url=%s mechanism=%s aveonline_ok=%s",
        tenant_id, url, mechanism, aveonline_registered,
    )

    return {
        "ok": True,
        "url": url,
        "mechanism": mechanism,
        "plaintext_secret": plaintext,
        "aveonline_registered": aveonline_registered,
        "aveonline_message": aveonline_message,
        "rotated_at": rotation.record.rotated_at if rotation else None,
        "expires_at": rotation.record.expires_at if rotation else None,
    }


@router.post("/aveonline/webhook/rotate", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def aveonline_webhook_rotate(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
):
    """Rota secret + re-registra webhook con nuevo plaintext.

    Equivalente a configure pero con audit_log explícito de rotación
    (vs primera config). Misma response shape.
    """
    if role != "owner":
        raise HTTPException(403, "Solo el owner puede rotar webhooks")

    # Idéntico a configure por dentro — la distinción ocurre en
    # rotate_secret() que detecta si la fila ya existía (= rotación).
    return await aveonline_webhook_configure(
        tenant_id=tenant_id, role=role, supabase=supabase,
    )


@router.delete("/aveonline/webhook", status_code=204, dependencies=[Depends(RL_WRITE_DEFAULT)])
async def aveonline_webhook_delete(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
):
    """Elimina webhook tanto en Aveonline como en DB local.

    Útil si el tenant quiere desactivar tracking. La integración Aveonline
    sigue activa (cotización + guías) — solo se desconecta el reporting
    de estados.
    """
    if role != "owner":
        raise HTTPException(403, "Solo el owner puede eliminar webhooks")

    url = _build_aveonline_webhook_url(tenant_id)

    # 1. Aveonline.
    try:
        from integrations.aveonline_client import AveonlineClient
        client = AveonlineClient(tenant_id=tenant_id, supabase=supabase)
        await client.delete_webhook(url=url)
    except Exception as exc:
        logger.warning(
            "[AVEONLINE_WH_DEL] delete remoto err tenant=%s: %s",
            tenant_id, exc,
        )

    # 2. DB local: borrar fila tenant_webhook_secrets.
    try:
        supabase.table("tenant_webhook_secrets").delete().eq(
            "tenant_id", tenant_id,
        ).eq("integration", "aveonline").execute()
    except Exception as exc:
        # GREEN-18 (OWASP 2026-08-23): no devolver str(exc) crudo al cliente.
        logger.warning(
            "[AVEONLINE_WH_DEL] DB delete err tenant=%s: %s",
            tenant_id, exc,
        )
        raise HTTPException(500, "Error eliminando secret local")

    logger.info(
        "[AVEONLINE_WH_DEL] tenant=%s deleted url=%s", tenant_id, url,
    )
    return None


# ─── Aveonline: carriers preferences per-tenant (Rev. 108) ───────────────────
# Matriz tenant_carriers para provider='aveonline' — espejo del patrón Envia
# (Sem 5 H.2.7) extendido con `supports_cod` (Aveonline tiene COD nativo y
# tenant elige por carrier vs Envia donde COD es decisión global).
#
# Política UX:
#   • Default open: tenant sin filas → todos los carriers Aveonline disponibles
#     se ofrecen en cotización.
#   • Seed (al conectar): poblar fila por carrier con enabled=true + cod=false
#     (decisión comercial explícita post-onboarding).
#   • Bulk PUT: tenant edita matrix completa en UI (más eficiente que upserts
#     individuales — UI envía estado deseado, backend reconcilia).


@router.get("/aveonline/carriers", response_model=list)
def list_aveonline_carriers(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista preferencias de carriers Aveonline del tenant."""
    from lib.tenant_carriers import list_preferences
    prefs = list_preferences(supabase, tenant_id, "aveonline")
    return [
        {
            "carrier_code": p.carrier_code,
            "enabled": p.enabled,
            "display_label": p.display_label,
            "priority": p.priority,
            "notes": p.notes,
            "supports_cod": p.supports_cod,
        }
        for p in prefs
    ]


@router.put("/aveonline/carriers", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
def bulk_upsert_aveonline_carriers(
    body: AveonlineCarriersBulk,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Bulk update preferencias Aveonline — sustituye estado completo.

    UI envía toda la matriz visible en una llamada. Backend hace upsert
    de cada item (UNIQUE constraint maneja conflictos). Si el body NO
    incluye un carrier que existía antes → ese carrier QUEDA tal cual
    (preserva preferencia previa sin tocar — semántica patch, no replace).

    Para borrar explícitamente un carrier, usa DELETE individual.
    """
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail="Solo owner o manager pueden gestionar carriers.",
        )
    from lib.tenant_carriers import upsert_preference

    updated: list[dict] = []
    errors: list[dict] = []
    for item in body.items:
        try:
            pref = upsert_preference(
                supabase, tenant_id, "aveonline",
                carrier_code=item.carrier_code,
                enabled=item.enabled,
                display_label=item.display_label,
                priority=item.priority,
                notes=item.notes,
                supports_cod=item.supports_cod,
            )
            updated.append({
                "carrier_code": pref.carrier_code,
                "enabled": pref.enabled,
                "display_label": pref.display_label,
                "priority": pref.priority,
                "notes": pref.notes,
                "supports_cod": pref.supports_cod,
            })
        except Exception as exc:
            logger.warning(
                "[AVEONLINE_CARRIERS] upsert err tenant=%s code=%s: %s",
                tenant_id, item.carrier_code, exc,
            )
            errors.append({
                "carrier_code": item.carrier_code,
                "error": str(exc),
            })

    return {"updated": updated, "errors": errors}


@router.delete("/aveonline/carriers/{carrier_code}", status_code=204, dependencies=[Depends(RL_WRITE_DEFAULT)])
def delete_aveonline_carrier(
    carrier_code: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Borra preferencia (vuelve a default — todos visibles)."""
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
    ).eq("provider", "aveonline").eq("carrier_code", code).execute()


@router.post("/aveonline/carriers/seed", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
async def seed_aveonline_carriers(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
):
    """Pobla `tenant_carriers` con los carriers que Aveonline retorna en
    `listarTransportadorasPorEmpresa` para esta cuenta.

    Llamado automáticamente al conectar Aveonline (vía connect action) y
    expuesto también para re-sync manual desde UI si Aveonline agrega
    carriers nuevos al contrato del tenant.

    Idempotente: solo INSERTA filas nuevas (UNIQUE constraint protege
    duplicados). NO sobreescribe `enabled`, `supports_cod`, `priority`,
    `notes` si el carrier ya existía — preserva configuración del tenant.
    """
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail="Solo owner o manager pueden re-sincronizar carriers.",
        )

    from integrations.aveonline_client import AveonlineClient
    client = AveonlineClient(tenant_id=tenant_id, supabase=supabase)
    try:
        result = await client.list_carriers()
    except Exception as exc:
        # GREEN-18 (OWASP 2026-08-23): no devolver str(exc) crudo al cliente.
        logger.warning("[AVEONLINE_CARRIERS] list err tenant=%s: %s", tenant_id, exc)
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar carriers Aveonline",
        )

    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=result.get("message") or "Aveonline no retornó carriers",
        )

    items = result.get("items") or []
    if not items:
        return {"discovered": 0, "inserted": 0, "items": []}

    # Lookup existentes para evitar override de preferencias.
    existing_res = (
        supabase.table("tenant_carriers")
        .select("carrier_code")
        .eq("tenant_id", tenant_id)
        .eq("provider", "aveonline")
        .execute()
    )
    existing_codes = {
        (r.get("carrier_code") or "").lower()
        for r in (existing_res.data or [])
    }

    inserted = 0
    response_items: list[dict] = []
    for it in items:
        # Carrier code canónico: usar `text` de Aveonline (ej. "SERVIENTREGA")
        # normalizado a lowercase para consistencia con lookups internos.
        text = (it.get("text") or "").strip()
        code = text.lower().replace(" ", "_") or it.get("id")
        if not code:
            continue
        response_items.append({
            "carrier_code": code,
            "display_label": text,
            "aveonline_id": it.get("id"),
        })
        if code.lower() in existing_codes:
            continue
        try:
            supabase.table("tenant_carriers").insert({
                "tenant_id": tenant_id,
                "provider": "aveonline",
                "carrier_code": code,
                "enabled": True,
                "display_label": text,
                "priority": 100,
                "notes": f"Aveonline ID: {it.get('id')}",
                "supports_cod": False,  # opt-in explícito post-onboarding
            }).execute()
            inserted += 1
        except Exception as exc:
            logger.warning(
                "[AVEONLINE_CARRIERS] seed insert err tenant=%s code=%s: %s",
                tenant_id, code, exc,
            )

    logger.info(
        "[AVEONLINE_CARRIERS] seed tenant=%s discovered=%d inserted=%d "
        "existing=%d",
        tenant_id, len(items), inserted, len(existing_codes),
    )
    return {
        "discovered": len(items),
        "inserted": inserted,
        "preserved": len(existing_codes),
        "items": response_items,
    }

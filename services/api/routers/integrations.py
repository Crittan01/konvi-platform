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


# ─── Aveonline: listar agentes del tenant ────────────────────────────────────


@router.get("/aveonline/agents")
async def list_aveonline_agents(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
):
    """Lista los agentes (puntos de despacho) registrados en la cuenta
    Aveonline del tenant.

    Endpoint Aveonline:
      `POST https://app.aveonline.co/api/comunes/v1.0/agentes.php`
      body: `{tipo: 'listarAgentesPorEmpresaAuth', token, idempresa}`

    UX: tenant elige un agente del dropdown (en lugar de buscar el ID
    manualmente en el panel Aveonline). El `principal: 'SI'` se sugiere
    por default. Se persiste en `tenant_integrations.credentials.idagente`.

    Permite a `owner` y `manager` — config operacional, no destructiva.
    """
    if role not in ("owner", "manager"):
        raise HTTPException(403, "Solo owner/manager pueden ver agentes")

    from integrations.aveonline_client import AveonlineClient
    import httpx

    client = AveonlineClient(supabase=supabase, tenant_id=tenant_id)
    try:
        jwt = await client._get_valid_jwt()
        creds = await client._load_credentials()
    except Exception as exc:
        raise HTTPException(
            502,
            f"No se pudo autenticar con Aveonline: {exc}. "
            f"Verifica que la integración esté conectada.",
        )

    empresa_id = creds.get("empresa_id")
    if not empresa_id:
        raise HTTPException(422, "Aveonline no retornó empresa_id en auth")

    body = {
        "tipo": "listarAgentesPorEmpresaAuth",
        "token": jwt,
        "idempresa": empresa_id,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.post(
                "https://app.aveonline.co/api/comunes/v1.0/agentes.php",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Aveonline HTTP error: {exc}")

    if data.get("status") != "ok":
        return {
            "agents": [],
            "warning": data.get("message") or "sin agentes",
        }

    agents_raw = data.get("agentes") or []
    agents = [
        {
            "id": str(a.get("id") or ""),
            "nombre": str(a.get("nombre") or ""),
            "direccion": str(a.get("direccion") or ""),
            "idciudad": str(a.get("idciudad") or ""),
            "telefono": str(a.get("telefono") or ""),
            "email": str(a.get("email") or ""),
            "principal": (a.get("principal") or "").upper() in ("S", "SI"),
        }
        for a in agents_raw
        if a.get("id")
    ]
    agents.sort(key=lambda x: (not x["principal"], x["nombre"]))
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
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
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

    # 2. Cargar shipping_meta del cart (carrier seleccionado).
    cart_res = (
        supabase.table("conversation_carts")
        .select("shipping_meta")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
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

    # 3. Cargar tenant shipping origin.
    tenant_res = (
        supabase.table("tenants")
        .select(
            "name, shipping_origin_city, shipping_origin_state, "
            "shipping_origin_dane, shipping_origin_address, "
            "shipping_origin_nit, shipping_origin_phone, "
            "shipping_origin_email, idagente"
        )
        .eq("id", tenant_id).single().execute()
    )
    tenant = tenant_res.data or {}

    # 4. Construir payload canónico.
    from integrations.aveonline_client import (
        AveonlineClient, AveonlineAuthError,
        AveonlineTransientError, AveonlinePermanentError,
    )
    from lib.dane_resolver import resolve_dane_from_city
    client = AveonlineClient(supabase=supabase, tenant_id=tenant_id)

    # Bug fix rev. 109 (2026-05-31): Aveonline `generarGuia2` rechaza destino
    # sin DANE. Precedencia: shipping_meta.dane_code (resuelto al cotizar) →
    # contact.address.dane_code (si save_address persistió) → DIVIPOLA fallback.
    # zfill defensivo: tenant.shipping_origin_dane legacy puede estar como
    # int "5001" (Bogotá sin leading zero) — Aveonline exige 5 dígitos.
    def _normalize_dane5(raw: object) -> str:
        digits = "".join(c for c in str(raw or "") if c.isdigit())
        if len(digits) == 5: return digits
        if len(digits) == 4: return digits.zfill(5)
        return ""
    origin = {
        "dane": (
            _normalize_dane5(tenant.get("shipping_origin_dane"))
            or resolve_dane_from_city(
                str(tenant.get("shipping_origin_city") or ""),
                tenant.get("shipping_origin_state"),
            )
        ),
        "city": str(tenant.get("shipping_origin_city") or ""),
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
    # Peso/dimensiones por default si la order no los tiene.
    package = {
        "weight_kg": 0.5,
        "length_cm": 15,
        "width_cm": 10,
        "height_cm": 5,
        "declared_value_cop": int(order.get("total_amount") or 50000),
        "units": 1,
        "content": "Productos KAIU — dry-run",
    }
    carrier_payload = {
        "idtransportador": str(rate_id),
        "service_level": str(shipping_meta.get("service_level") or ""),
    }
    sender = {
        "nit": str(tenant.get("shipping_origin_nit") or ""),
        "nombre": str(tenant.get("name") or ""),
        "direccion": str(tenant.get("shipping_origin_address") or ""),
        "barrio": "",
        "telefono": str(tenant.get("shipping_origin_phone") or ""),
        "celular": str(tenant.get("shipping_origin_phone") or ""),
        "email": str(tenant.get("shipping_origin_email") or ""),
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
    try:
        result = await client.generate_guide(
            origin=origin, destination=destination,
            package=package, carrier=carrier_payload,
            sender=sender, recipient=recipient,
            simulate=req.simulate,
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
            "tenant_idagente": tenant.get("idagente"),
            "carrier_selected": carrier_name,
            "rate_id": rate_id,
            "origin": origin,
            "destination": destination,
            "simulate": req.simulate,
            "warning_idagente_missing": not tenant.get("idagente"),
        },
    }


# ─── Aveonline: webhook estados de guía (Rev. 108) ───────────────────────────
# Endpoints para configurar / rotar / consultar / eliminar el webhook
# `webhookEstadosGuias` de Aveonline para este tenant.
#
# Flujo configure (primera vez):
#   1. Backend genera UUIDv4 plaintext, lo hashea con bcrypt (F.10).
#   2. Persiste hash en `tenant_webhook_secrets` (integration='aveonline').
#   3. Llama `AveonlineClient.create_webhook` con URL pública + plaintext.
#   4. Retorna URL + plaintext UNA VEZ (UI lo muestra al tenant para
#      copiar si Aveonline lo pide después; después se descarta).
#
# Flujo rotate:
#   1. Genera nuevo plaintext + nuevo hash.
#   2. Mueve hash actual a `previous_secret_hash` con `grace_period_until`
#      = now+7d (permite que Aveonline siga enviando con el viejo durante
#      la migración del panel).
#   3. Llama Aveonline `delete_webhook` (vieja URL si cambió) + `create_webhook`
#      con nuevo plaintext.
#   4. Retorna nuevo plaintext UNA VEZ.


def _public_webhook_base_url() -> str:
    """URL pública del API donde Aveonline hará POST.

    En prod: `https://api.konvi.app`. En local: env var `PUBLIC_WEBHOOK_URL`
    (ngrok). El endpoint final es:
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
async def aveonline_webhook_status(
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


@router.post("/aveonline/webhook/configure")
async def aveonline_webhook_configure(
    tenant_id: str = Depends(get_current_tenant),
    role: str = Depends(get_current_role),
    supabase: Client = Depends(get_service_client),
):
    """Configura webhook por primera vez (o lo rota si ya existía).

    Pasos:
      1. Genera secret plaintext + hash (F.10).
      2. Persiste en `tenant_webhook_secrets`.
      3. Intenta eliminar webhook viejo en Aveonline (si existe).
      4. Registra webhook nuevo en Aveonline con URL + secret.

    Response:
      {
        "ok": bool,
        "url": str,
        "plaintext_secret": str,   # SOLO UNA VEZ
        "aveonline_registered": bool,
        "aveonline_message": str,
      }
    """
    if role != "owner":
        raise HTTPException(
            403, "Solo el owner puede configurar webhooks de integraciones",
        )

    from lib.webhook_secret_manager import rotate_secret

    url = _build_aveonline_webhook_url(tenant_id)
    rotation = rotate_secret(
        supabase, tenant_id=tenant_id, integration="aveonline",
        actor_id=None,  # FastAPI Depends de user no se incluyó — futuro F2.
        reason="aveonline_webhook_configure",
    )
    plaintext = rotation.plaintext_secret

    # Intentar registrar en Aveonline (best-effort — si falla, el secret
    # ya quedó en DB y el tenant puede invocar registro manual).
    aveonline_registered = False
    aveonline_message = ""
    try:
        from integrations.aveonline_client import AveonlineClient
        client = AveonlineClient(tenant_id=tenant_id, supabase=supabase)

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
        aveonline_message = result.get("message") or ""
        logger.info(
            "[AVEONLINE_WH_CFG] register tenant=%s ok=%s msg=%s",
            tenant_id, aveonline_registered, aveonline_message,
        )
    except Exception as exc:
        logger.warning(
            "[AVEONLINE_WH_CFG] aveonline register err tenant=%s: %s",
            tenant_id, exc,
        )
        aveonline_message = f"error registrando en Aveonline: {exc}"

    # Audit nota: `audit_log` en este repo es un decorador FastAPI (opt-in
    # via @audit_log(...) sobre handlers). Para auditoría imperativa el
    # registro queda implícito en `tenant_webhook_secrets.audit_log` JSONB
    # via `rotate_secret()` arriba — esa fila lleva el historial de
    # eventos (created|rotated|revoked, actor_id, reason, timestamp).
    logger.info(
        "[AVEONLINE_WH_CFG] tenant=%s configured url=%s aveonline_ok=%s",
        tenant_id, url, aveonline_registered,
    )

    return {
        "ok": True,
        "url": url,
        "plaintext_secret": plaintext,
        "aveonline_registered": aveonline_registered,
        "aveonline_message": aveonline_message,
        "rotated_at": rotation.record.rotated_at,
        "expires_at": rotation.record.expires_at,
    }


@router.post("/aveonline/webhook/rotate")
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


@router.delete("/aveonline/webhook", status_code=204)
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
        logger.warning(
            "[AVEONLINE_WH_DEL] DB delete err tenant=%s: %s",
            tenant_id, exc,
        )
        raise HTTPException(500, f"Error eliminando secret local: {exc}")

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
async def list_aveonline_carriers(
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


@router.put("/aveonline/carriers", response_model=dict)
async def bulk_upsert_aveonline_carriers(
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


@router.delete("/aveonline/carriers/{carrier_code}", status_code=204)
async def delete_aveonline_carrier(
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


@router.post("/aveonline/carriers/seed", response_model=dict)
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
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo consultar carriers Aveonline: {exc}",
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

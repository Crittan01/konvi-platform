"""
Cliente OAuth 2.0 para MercadoLibre.

Validado: PV-06 — 2026-04-09. Extendido para gestión de items — 2026-04-13.
Referencia oficial: https://developers.mercadolibre.com.ar/en_us/items-and-searches
                    https://developers.mercadolibre.com.ar/devsite/sync-and-modify-listings-gs

Modelo de tokens:
  - App credentials (client_id, client_secret): GLOBALES — env vars de plataforma.
  - Token por tenant: almacenado en tenant_integrations.credentials.
    { access_token, refresh_token, user_id, expires_at }

Scopes disponibles (NO granulares por recurso):
  - read          → GET requests (items, orders, etc.)
  - write         → GET + POST/PUT (items, orders, shipping)
  - offline_access → habilita refresh_token (obligatorio para uso sin interacción)

Access token: válido 6 horas (expires_in=21600, doc oficial MeLi). Refresh automático
cuando expira (expires_at se calcula desde expires_in del token, no del comentario).

Endpoints de items usados:
  - GET  /users/{user_id}/items/search          → listar IDs de items del seller
  - GET  /items?ids=ID1,ID2&attributes=...      → detalle de múltiples items (multiget)
  - GET  /items/{item_id}                       → detalle de un item
  - PUT  /items/{item_id}                       → actualizar cantidad, precio o status
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _token_still_valid(expires_at_s: Optional[str]) -> bool:
    """True si `expires_at_s` parsea a un instante AÚN futuro (token todavía usable).

    Conservador: si no hay expiry o no parsea, retorna False (no lo damos por válido)
    para NO usar un token de vigencia desconocida como si fuera bueno. Base del fix del
    401-loop: solo marcamos la integración 'error' cuando SABEMOS que el token expiró.
    """
    if not expires_at_s:
        return False
    try:
        exp = datetime.fromisoformat(expires_at_s)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp > datetime.now(timezone.utc)
    except Exception:
        return False

MELI_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
MELI_API_URL   = "https://api.mercadolibre.com"

# URL de autorización OAuth — country-specific.
# CO: https://auth.mercadolibre.com.co/authorization
# AR: https://auth.mercadolibre.com.ar/authorization
# MX: https://auth.mercadolibre.com.mx/authorization
MELI_AUTH_URL = os.getenv("MELI_AUTH_URL", "https://auth.mercadolibre.com.co/authorization")

MELI_CLIENT_ID     = os.getenv("MELI_CLIENT_ID", "")
MELI_CLIENT_SECRET = os.getenv("MELI_CLIENT_SECRET", "")
MELI_REDIRECT_URI  = os.getenv("MELI_REDIRECT_URI", "")
MELI_OAUTH_STATE_SECRET = os.getenv("MELI_OAUTH_STATE_SECRET", "")
MELI_OAUTH_STATE_TTL_SECONDS = int(os.getenv("MELI_OAUTH_STATE_TTL_SECONDS", "600"))

# Atributos que se traen en el multiget para no pagar ancho de banda innecesario
ITEM_ATTRIBUTES = "id,title,status,price,available_quantity,permalink,thumbnail,variations,condition,category_id"


# ─── OAuth ────────────────────────────────────────────────────────────────────

def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(f"{raw}{padding}")


def _state_secret_bytes() -> bytes:
    if not MELI_OAUTH_STATE_SECRET:
        raise ValueError("MELI_OAUTH_STATE_SECRET no configurado")
    return MELI_OAUTH_STATE_SECRET.encode()


def _sign_state_payload(payload_b64: str) -> str:
    digest = hmac.new(_state_secret_bytes(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _hash_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def _persist_oauth_nonce(supabase, tenant_id: str, nonce: str, expires_at: datetime) -> None:
    supabase.table("integration_oauth_states").insert(
        {
            "tenant_id": tenant_id,
            "provider": "mercadolibre",
            "nonce_hash": _hash_nonce(nonce),
            "expires_at": expires_at.isoformat(),
        }
    ).execute()


def issue_oauth_state(supabase, tenant_id: str) -> str:
    """Genera state firmado con expiración y nonce de un solo uso."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=MELI_OAUTH_STATE_TTL_SECONDS)
    nonce = secrets.token_urlsafe(24)
    payload = {
        "tid": tenant_id,
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature_b64 = _sign_state_payload(payload_b64)
    _persist_oauth_nonce(supabase, tenant_id, nonce, expires_at)
    return f"{payload_b64}.{signature_b64}"


def validate_and_consume_oauth_state(supabase, state: str) -> Optional[str]:
    """
    Valida state firmado y consume nonce one-time.
    Retorna tenant_id si es válido; None si está manipulado, expirado o reutilizado.
    """
    try:
        payload_b64, signature_b64 = state.split(".", 1)
    except ValueError:
        return None

    expected_sig = _sign_state_payload(payload_b64)
    if not hmac.compare_digest(signature_b64, expected_sig):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
        tenant_id = str(payload["tid"])
        nonce = str(payload["nonce"])
        exp = int(payload["exp"])
    except Exception:
        return None

    now = datetime.now(timezone.utc)
    if now.timestamp() > exp:
        return None

    lookup = (
        supabase.table("integration_oauth_states")
        .select("id, expires_at, consumed_at")
        .eq("provider", "mercadolibre")
        .eq("tenant_id", tenant_id)
        .eq("nonce_hash", _hash_nonce(nonce))
        .maybe_single()
        .execute()
    )
    row = lookup.data
    if not row:
        return None
    if row.get("consumed_at") is not None:
        return None

    try:
        stored_exp = datetime.fromisoformat(str(row["expires_at"]))
        if stored_exp.tzinfo is None:
            stored_exp = stored_exp.replace(tzinfo=timezone.utc)
    except Exception:
        return None

    if stored_exp < now:
        return None

    consume = (
        supabase.table("integration_oauth_states")  # tenant_filter:exempt:payload_includes_tenant_id
        .update({"consumed_at": now.isoformat()})
        .eq("id", row["id"])
        .is_("consumed_at", "null")
        .execute()
    )
    if not consume.data:
        return None

    return tenant_id


def get_auth_url(tenant_id: str, supabase, force_login: bool = True) -> str:
    """
    Genera la URL de autorización OAuth para redirigir al tenant.
    El state es firmado, expira y es one-time (nonce anti-replay).

    Rev. 108 (founder feedback 2026-05-27 — disconnect + reconnect
    auto-loguea al usuario anterior):
      • `prompt=login` (OIDC-style) — best-effort: MeLi puede ignorarlo
        si no lo soporta. Si en futuro lo respeta, ya está implementado.
      • `auth_type=reauthenticate` (FB-style fallback) — mismo principio.

    Estos params NO están documentados oficialmente por MeLi (dossier
    §2.2 line 46-56 confirma). Append es zero-risk: si MeLi los ignora,
    URL sigue válida. Si los respeta, fuerza pantalla de login MeLi.

    Defensa complementaria en frontend (UI hint pre-connect) y backend
    (callback detect same-user). Las 3 capas A+B+C trabajan juntas.
    """
    if not MELI_CLIENT_ID or not MELI_REDIRECT_URI or not MELI_OAUTH_STATE_SECRET:
        raise ValueError(
            "MELI_CLIENT_ID, MELI_REDIRECT_URI y MELI_OAUTH_STATE_SECRET deben estar configurados"
        )

    state = issue_oauth_state(supabase, tenant_id)
    params = (
        f"response_type=code"
        f"&client_id={MELI_CLIENT_ID}"
        f"&redirect_uri={MELI_REDIRECT_URI}"
        f"&state={state}"
    )
    if force_login:
        # Layer A: best-effort force re-authentication.
        params += "&prompt=login&auth_type=reauthenticate"
    return f"{MELI_AUTH_URL}?{params}"


async def revoke_token(access_token: str) -> bool:
    """
    Revoca el access_token en MeLi para que deje de enviar webhooks al seller.
    MeLi detiene las notificaciones cuando la autorización es revocada.

    Referencia: https://developers.mercadolibre.com.ar/en_us/authentication-and-authorization
    Endpoint: DELETE https://api.mercadolibre.com/oauth/token
              Authorization: Bearer {access_token}

    Retorna True si revocado correctamente. False si falla (no bloquea el disconnect local).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            MELI_TOKEN_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code in (200, 204):
            logger.info("Token MeLi revocado correctamente")
            return True
        logger.warning("Revocación MeLi respondió %d: %s", resp.status_code, resp.text[:200])
        return False


async def exchange_code(code: str) -> dict:
    """
    Intercambia el authorization code por access_token + refresh_token.
    Retorna el payload completo de MeLi (access_token, refresh_token, user_id, etc.).
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            MELI_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": MELI_CLIENT_ID,
                "client_secret": MELI_CLIENT_SECRET,
                "code": code,
                "redirect_uri": MELI_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_token(refresh_tok: str) -> dict:
    """Renueva el access_token usando el refresh_token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            MELI_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": MELI_CLIENT_ID,
                "client_secret": MELI_CLIENT_SECRET,
                "refresh_token": refresh_tok,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def is_configured() -> bool:
    """Verifica si las credenciales de la app MeLi están configuradas."""
    return len(missing_required_config()) == 0


def missing_required_config() -> list[str]:
    """
    Lista env vars requeridas faltantes para habilitar OAuth MeLi seguro.
    """
    required = {
        "MELI_CLIENT_ID": MELI_CLIENT_ID,
        "MELI_CLIENT_SECRET": MELI_CLIENT_SECRET,
        "MELI_REDIRECT_URI": MELI_REDIRECT_URI,
        "MELI_AUTH_URL": MELI_AUTH_URL,
        "MELI_OAUTH_STATE_SECRET": MELI_OAUTH_STATE_SECRET,
    }
    return [key for key, value in required.items() if not value]


# ─── Token por tenant ─────────────────────────────────────────────────────────

async def get_valid_token(supabase, tenant_id: str, refresh_window: timedelta = timedelta(hours=1)) -> Optional[str]:
    """
    Retorna un access_token válido para el tenant.
    Refresca automáticamente si expires_at < now + refresh_window (default 1h —
    margen para uso inmediato). El barrido proactivo M17 (endpoint interno
    /api/v1/internal/meli/refresh-tokens) lo invoca con una ventana de 24h para
    rotar tokens ANTES de que expiren aunque el tenant no tenga actividad MeLi,
    manteniendo vivo el refresh_token (~6 meses de TTL si no rota).
    Guarda el token nuevo en DB tras un refresh exitoso.
    """
    try:
        result = (
            supabase.table("tenant_integrations")
            .select("credentials")
            .eq("tenant_id", tenant_id)
            .eq("provider", "mercadolibre")
            .eq("status", "connected")
            .single()
            .execute()
        )
        if not result.data:
            return None

        creds        = result.data.get("credentials") or {}
        from vault_helper import VaultHelper, resolve_secret
        vault        = VaultHelper(supabase)
        access_token = resolve_secret(vault, creds, "access_token")
        refresh_tok  = resolve_secret(vault, creds, "refresh_token")
        expires_at_s = creds.get("expires_at")

        if not access_token:
            return None

        # Decidir si refrescar
        needs_refresh = False
        if refresh_tok:
            if not expires_at_s:
                needs_refresh = True
            else:
                try:
                    exp = datetime.fromisoformat(expires_at_s)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    needs_refresh = exp < datetime.now(timezone.utc) + refresh_window
                except Exception:
                    needs_refresh = True

        if needs_refresh and refresh_tok:
            # SINGLE-FLIGHT vía LEASE atómico en DB (cross-loop/worker/réplica). Solo el ganador del
            # lease refresca; los perdedores esperan y re-leen el token fresco. Con el lease en mano,
            # un 400/401 del refresh es invalid_grant GENUINO (no un 'perdedor' concurrente) → es
            # SEGURO marcar status='error' (surfacing del 401-loop; el guard viejo `if not
            # access_token` era código muerto → nunca marcaba). Si la RPC del lease no existe aún
            # (migración pendiente) → lease_state='unavailable' → se refresca sin lease y NO se marca
            # error (degradación segura al comportamiento previo). asyncio.sleep es loop-safe (a
            # diferencia de asyncio.Lock, que es loop-BOUND y rompía cross-loop).
            lease_state = "unavailable"
            lease_token = None
            try:
                _lease = supabase.rpc("rpc_meli_try_refresh_lease", {
                    "p_tenant_id": tenant_id, "p_provider": "mercadolibre", "p_ttl_seconds": 90,
                }).execute()
                lease_token = _lease.data  # fencing token (uuid) si ganó; None si perdió
                lease_state = "won" if lease_token else "lost"
            except Exception:
                lease_state = "unavailable"  # RPC ausente (migración pendiente) → degradar

            if lease_state == "lost":
                # Otro caller está refrescando → esperar (bounded) y re-leer su token fresco.
                for _ in range(8):
                    await asyncio.sleep(0.25)
                    try:
                        _p = (
                            supabase.table("tenant_integrations")
                            .select("credentials")
                            .eq("tenant_id", tenant_id)
                            .eq("provider", "mercadolibre")
                            .single()
                            .execute()
                        )
                        _pc = (_p.data or {}).get("credentials") or {}
                        _pa = resolve_secret(vault, _pc, "access_token")
                        if _pa and _pa != access_token and _token_still_valid(_pc.get("expires_at")):
                            return _pa
                    except Exception:
                        pass
                return access_token  # el holder aún no persiste → token vigente (retry luego)

            # lease_state in ('won', 'unavailable') → nosotros refrescamos.
            try:
                # Double-check: entre la lectura inicial y el lease, otro pudo refrescar+liberar.
                refresh_to_use = refresh_tok
                try:
                    _fresh = (
                        supabase.table("tenant_integrations")
                        .select("credentials")
                        .eq("tenant_id", tenant_id)
                        .eq("provider", "mercadolibre")
                        .single()
                        .execute()
                    )
                    _fresh_creds = (_fresh.data or {}).get("credentials") or {}
                    _fresh_access = resolve_secret(vault, _fresh_creds, "access_token")
                    if (
                        _fresh_access and _fresh_access != access_token
                        and _token_still_valid(_fresh_creds.get("expires_at"))
                    ):
                        return _fresh_access  # otro caller ya refrescó → usar su token fresco
                    refresh_to_use = resolve_secret(vault, _fresh_creds, "refresh_token") or refresh_tok
                except Exception:
                    refresh_to_use = refresh_tok

                try:
                    token_data  = await refresh_token(refresh_to_use)
                    new_access  = token_data.get("access_token")
                    new_refresh = token_data.get("refresh_token", refresh_to_use)
                    new_exp_in  = token_data.get("expires_in", 21600)
                    new_exp_at  = (datetime.now(timezone.utc) + timedelta(seconds=new_exp_in)).isoformat()

                    # WRITE-BEFORE-CONSUME: persistir el token rotado a Vault + DB ANTES de usarlo,
                    # para que un crash entre la rotación MeLi y la persistencia no pierda el
                    # refresh_token de un solo uso (que mataría la integración permanentemente).
                    at_sid = creds.get("access_token_secret_id")
                    rt_sid = creds.get("refresh_token_secret_id")
                    if at_sid:
                        vault.update_secret(at_sid, new_access)
                    else:
                        at_sid = vault.create_secret(new_access, f"{tenant_id}/meli/access_token", "MeLi access token")
                    if rt_sid:
                        vault.update_secret(rt_sid, new_refresh)
                    else:
                        rt_sid = vault.create_secret(new_refresh, f"{tenant_id}/meli/refresh_token", "MeLi refresh token")

                    _upd = {
                        "credentials": {
                            "access_token_secret_id":  at_sid,
                            "refresh_token_secret_id": rt_sid,
                            "expires_in":  new_exp_in,
                            "expires_at":  new_exp_at,
                        },
                    }
                    # Reset del contador de fallos SOLO si la migración está aplicada (lease_state
                    # 'won' ⇒ la RPC existe ⇒ la columna existe). Si no, omitir para no romper el
                    # persist con una columna inexistente (degradación segura).
                    if lease_state == "won":
                        _upd["refresh_fail_count"] = 0
                    supabase.table("tenant_integrations").update(_upd).eq(
                        "tenant_id", tenant_id).eq("provider", "mercadolibre").execute()

                    logger.info("Token MeLi renovado tenant %s, expira %s", tenant_id, new_exp_at)
                    return new_access
                except Exception as e:
                    logger.warning(
                        "No se pudo renovar token MeLi tenant %s: %s — evaluando", tenant_id, e,
                    )
                    # Recuperación graceful: re-leer; si ya hay un token válido, usarlo.
                    try:
                        _r = (
                            supabase.table("tenant_integrations")
                            .select("credentials")
                            .eq("tenant_id", tenant_id)
                            .eq("provider", "mercadolibre")
                            .single()
                            .execute()
                        )
                        _rc = (_r.data or {}).get("credentials") or {}
                        _ra = resolve_secret(vault, _rc, "access_token")
                        if _ra and _token_still_valid(_rc.get("expires_at")):
                            return _ra
                    except Exception:
                        pass
                    # FIX 401-loop (SEGURO): en un 400/401 (invalid_grant) CON el lease en mano,
                    # registrar el fallo vía RPC FENCED. rpc_meli_note_refresh_failure marca
                    # status='error' SOLO tras N fallos CONSECUTIVOS y solo si el fencing token sigue
                    # siendo el nuestro → un 400 falso aislado de un 'perdedor' concurrente / un
                    # double-win por TTL NO marca (el éxito de un refresh resetea el contador; un
                    # holder con lease retomado no matchea el token → no cuenta). Fallo transitorio
                    # (5xx/timeout/red/DB) o sin lease (migración pendiente) NO cuenta (degradación).
                    _definitive = (
                        lease_state == "won" and lease_token
                        and isinstance(e, httpx.HTTPStatusError)
                        and e.response is not None
                        and e.response.status_code in (400, 401)
                    )
                    if _definitive:
                        try:
                            _marked = supabase.rpc("rpc_meli_note_refresh_failure", {
                                "p_tenant_id": tenant_id, "p_lease_token": lease_token,
                                "p_provider": "mercadolibre", "p_max_fails": 3,
                            }).execute()
                            if bool(_marked.data):
                                logger.warning(
                                    "MeLi marcada 'error' (refresh_token rechazado %s, N fallos consecutivos) tenant %s",
                                    e.response.status_code, tenant_id,
                                )
                                return None
                        except Exception:
                            pass
                    # Sin marcar (transitorio / bajo umbral / RPC falló) → devolver el token vigente.
            finally:
                # Release FENCED por el token: si nuestro lease expiró y fue retomado por otro,
                # el compare-and-set no matchea → no clobbeamos al holder actual.
                if lease_state == "won" and lease_token:
                    try:
                        supabase.rpc("rpc_meli_release_refresh_lease", {
                            "p_tenant_id": tenant_id, "p_lease_token": lease_token,
                            "p_provider": "mercadolibre",
                        }).execute()
                    except Exception:
                        pass

        return access_token

    except Exception as e:
        logger.warning("Error obteniendo token MeLi tenant %s: %s", tenant_id, e)
        return None


def get_tenant_meli_credentials(supabase, tenant_id: str) -> Optional[dict]:
    """
    Lee las credenciales MeLi del tenant desde tenant_integrations.
    Retorna { access_token, refresh_token, user_id } o None si no conectado.

    Nota: access_token está en 'credentials', user_id está en 'meta' —
    ambos campos se seleccionan y se fusionan en el resultado.
    """
    try:
        result = (
            supabase.table("tenant_integrations")
            .select("credentials, meta")
            .eq("tenant_id", tenant_id)
            .eq("provider", "mercadolibre")
            .eq("status", "connected")
            .single()
            .execute()
        )
        if not result.data:
            return None
        creds = result.data.get("credentials") or {}
        meta  = result.data.get("meta") or {}
        from vault_helper import VaultHelper, resolve_secret
        vault = VaultHelper(supabase)
        access_token  = resolve_secret(vault, creds, "access_token")
        refresh_token = resolve_secret(vault, creds, "refresh_token")
        if not access_token:
            return None
        resolved = dict(creds)
        resolved["access_token"]  = access_token
        resolved["refresh_token"] = refresh_token
        if meta.get("user_id"):
            resolved["user_id"] = meta["user_id"]
        return resolved
    except Exception as e:
        logger.warning("No se pudo leer credenciales MeLi para tenant %s: %s", tenant_id, e)
        return None


# ─── Items API ────────────────────────────────────────────────────────────────

async def get_user_items(
    user_id: str,
    access_token: str,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
) -> dict:
    """
    Lista los IDs de items publicados por el seller.

    GET /users/{user_id}/items/search
    Docs: https://developers.mercadolibre.com.ar/en_us/items-and-searches

    Respuesta: { results: [item_id, ...], paging: { limit, offset, total } }
    Límite máximo: 100 por llamada.
    Para >1000 items usar search_type=scan (no implementado aquí — edge case).
    """
    params = {"limit": min(limit, 100), "offset": offset}
    if status:
        params["status"] = status

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{MELI_API_URL}/users/{user_id}/items/search",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_items_details(item_ids: list, access_token: str) -> list:
    """
    Trae detalles de múltiples items en una sola llamada (multiget).

    GET /items?ids=ID1,ID2,...&attributes=id,title,status,price,available_quantity,...
    Docs: https://developers.mercadolibre.com.ar/en_us/items-and-searches

    Retorna lista de { code, body } donde body tiene los datos del item.
    Si un item no existe, code=404 y body es None.
    MeLi permite hasta ~20 IDs por llamada — para lotes más grandes hacer chunking.
    """
    if not item_ids:
        return []

    # MeLi recomienda máximo 20 IDs por request en multiget
    chunk_size = 20
    all_items = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        for i in range(0, len(item_ids), chunk_size):
            chunk = item_ids[i:i + chunk_size]
            resp = await client.get(
                f"{MELI_API_URL}/items",
                params={"ids": ",".join(chunk), "attributes": ITEM_ATTRIBUTES},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            all_items.extend(resp.json())

    return all_items


async def get_item(item_id: str, access_token: str) -> dict:
    """
    Detalle de un item individual.
    GET /items/{item_id}
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{MELI_API_URL}/items/{item_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_shipment(shipment_id: str, access_token: str) -> dict:
    """
    Detalle de un envío MeLi.
    GET /shipments/{shipment_id}
    Retorna tracking_number, carrier (shipping_option.name), estimated_delivery_final, receiver_address, etc.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{MELI_API_URL}/shipments/{shipment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


# ─── Mutaciones ───────────────────────────────────────────────────────────────

async def update_item_quantity(item_id: str, quantity: int, access_token: str) -> dict:
    """
    Actualiza la cantidad disponible de un item en MeLi.

    PUT /items/{item_id}  body: { "available_quantity": N }
    Docs: https://developers.mercadolibre.com.ar/devsite/sync-and-modify-listings-gs

    Comportamiento MeLi:
      - quantity = 0  → status cambia automáticamente a 'paused' (out_of_stock)
      - quantity > 0 desde out_of_stock → status vuelve a 'active' automáticamente
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{MELI_API_URL}/items/{item_id}",
            json={"available_quantity": max(0, quantity)},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def update_item_status(item_id: str, status: str, access_token: str) -> dict:
    """
    Cambia el status de un item en MeLi.

    PUT /items/{item_id}  body: { "status": "active" | "paused" | "closed" }
    Docs: https://developers.mercadolibre.com.ar/devsite/sync-and-modify-listings-gs

    Nota: 'closed' es irreversible desde la API — el item queda finalizado.
    """
    if status not in ("active", "paused", "closed"):
        raise ValueError(f"Status inválido: {status}. Válidos: active, paused, closed")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{MELI_API_URL}/items/{item_id}",
            json={"status": status},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def update_item_price(item_id: str, price: float, access_token: str) -> dict:
    """
    Actualiza el precio de un item en MeLi.
    PUT /items/{item_id}  body: { "price": N }
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{MELI_API_URL}/items/{item_id}",
            json={"price": int(round(price))},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def update_item_listing(
    item_id: str,
    quantity: int,
    price: float,
    original_price: Optional[float],
    access_token: str,
    meli_variations: Optional[list] = None,
) -> dict:
    """
    Sincroniza stock + precio en un solo PUT.

    NOTA: original_price (precio tachado) NO se envía en el sync automático.
    MeLi rechaza modificarlo con 400 cuando el item tiene has_bids:true.
    Si el item no tuviera bids, se podría incluir, pero el riesgo de 400 no
    justifica la diferencia cosmética. El precio tachado se gestiona manualmente en MeLi.

    Items CON variaciones en MeLi:
      La API rechaza 400 si se envía available_quantity a nivel item.
      Se debe enviar { "variations": [{ "id": X, "available_quantity": N }, ...] }
      con TODAS las variaciones existentes.

    PUT /items/{item_id}
    Docs: https://developers.mercadolibre.com.ar/devsite/sync-and-modify-listings-gs
    """
    # COP no soporta decimales — MeLi rechaza con 400 si se envía precio con decimales.
    # round() + int() garantiza entero independiente de la moneda del tenant.
    body: dict = {"price": int(round(price))}

    if meli_variations:
        variations_body = []
        for i, v in enumerate(meli_variations):
            vid = v.get("id")
            if vid:
                # Si la variación ya trae available_quantity explícita
                # (ej. mapping exacto desde marketplace.py), respetarla.
                if "available_quantity" in v and v.get("available_quantity") is not None:
                    qty = int(v.get("available_quantity") or 0)
                else:
                    # Fallback legacy: primera variación recibe el qty objetivo.
                    qty = max(0, quantity) if i == 0 else 0
                variations_body.append({
                    "id": vid,
                    "available_quantity": max(0, qty),
                })
        if variations_body:
            body["variations"] = variations_body
    else:
        body["available_quantity"] = max(0, quantity)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{MELI_API_URL}/items/{item_id}",
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()

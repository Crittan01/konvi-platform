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

Access token: válido 180 días. Refresh automático cuando expira.

Endpoints de items usados:
  - GET  /users/{user_id}/items/search          → listar IDs de items del seller
  - GET  /items?ids=ID1,ID2&attributes=...      → detalle de múltiples items (multiget)
  - GET  /items/{item_id}                       → detalle de un item
  - PUT  /items/{item_id}                       → actualizar cantidad, precio o status
"""
import os
import httpx
import base64
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

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

# Atributos que se traen en el multiget para no pagar ancho de banda innecesario
ITEM_ATTRIBUTES = "id,title,status,price,available_quantity,permalink,thumbnail,variations"


# ─── OAuth ────────────────────────────────────────────────────────────────────

def get_auth_url(tenant_id: str) -> str:
    """
    Genera la URL de autorización OAuth para redirigir al tenant.
    El state codifica el tenant_id para recuperarlo en el callback.
    """
    if not MELI_CLIENT_ID or not MELI_REDIRECT_URI:
        raise ValueError("MELI_CLIENT_ID y MELI_REDIRECT_URI deben estar configurados")

    state = base64.urlsafe_b64encode(tenant_id.encode()).decode()
    params = (
        f"response_type=code"
        f"&client_id={MELI_CLIENT_ID}"
        f"&redirect_uri={MELI_REDIRECT_URI}"
        f"&state={state}"
    )
    return f"{MELI_AUTH_URL}?{params}"


def decode_state(state: str) -> Optional[str]:
    """Decodifica el state para recuperar el tenant_id."""
    try:
        return base64.urlsafe_b64decode(state.encode()).decode()
    except Exception:
        return None


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
    return bool(MELI_CLIENT_ID and MELI_CLIENT_SECRET and MELI_REDIRECT_URI)


# ─── Token por tenant ─────────────────────────────────────────────────────────

def get_tenant_meli_credentials(supabase, tenant_id: str) -> Optional[dict]:
    """
    Lee las credenciales MeLi del tenant desde tenant_integrations.
    Retorna { access_token, refresh_token, user_id } o None si no conectado.
    """
    try:
        result = (
            supabase.table("tenant_integrations")
            .select("credentials")
            .eq("tenant_id", tenant_id)
            .eq("provider", "mercadolibre")
            .eq("active", True)
            .single()
            .execute()
        )
        if result.data and result.data.get("credentials"):
            return result.data["credentials"]
        return None
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
            json={"price": price},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()

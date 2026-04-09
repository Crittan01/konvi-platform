"""
Cliente OAuth 2.0 para MercadoLibre.

Validado: PV-06 — 2026-04-09.
Referencia: https://developers.mercadolibre.com.mx/es_ar/autenticacion-y-autorizacion

Modelo:
  - App credentials (client_id, client_secret): GLOBALES — env vars de plataforma.
  - Token por tenant: almacenado en tenant_integrations.credentials.
    { access_token, refresh_token, user_id, expires_at }

Scopes disponibles (NO granulares por recurso):
  - read          → GET requests (items, orders, etc.)
  - write         → GET + POST/PUT (items, orders, shipping)
  - offline_access → habilita refresh_token (obligatorio para uso sin interacción)

Access token: válido 180 días. Refresh automático cuando expira.
"""
import os
import httpx
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

MELI_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
MELI_API_URL   = "https://api.mercadolibre.com"

# URL de autorización OAuth — country-specific.
# Por defecto Colombia. Configurar via env var si el tenant opera en otro país.
# MX: https://auth.mercadolibre.com.mx/authorization
# CO: https://auth.mercadolibre.com.co/authorization
# AR: https://auth.mercadolibre.com.ar/authorization
MELI_AUTH_URL = os.getenv("MELI_AUTH_URL", "https://auth.mercadolibre.com.co/authorization")

MELI_CLIENT_ID     = os.getenv("MELI_CLIENT_ID", "")
MELI_CLIENT_SECRET = os.getenv("MELI_CLIENT_SECRET", "")
MELI_REDIRECT_URI  = os.getenv("MELI_REDIRECT_URI", "")


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

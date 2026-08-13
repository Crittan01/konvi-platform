"""Cliente para descargar media de Meta Cloud API.

Usado por el orquestador multimodal: cuando llega un audio del cliente,
necesitamos los bytes para enviarlos inline al modelo Gemini.

Flujo Meta:
    1. GET https://graph.facebook.com/v22.0/{media_id}
       → retorna {url, mime_type, sha256, file_size, ...}
    2. GET <url> con Bearer
       → retorna binary

La URL temporal del paso 1 expira en ~5 min. Por eso este módulo cachea
los bytes (no la URL) por TTL corto, así reintentos cercanos no doblan
el tráfico a Meta ni vuelven a pedir el access_token.
"""
import hashlib
import logging
import os
import time
import threading
from typing import Optional

import httpx

logger = logging.getLogger("orchestrator.meta_media")

# Versión de Meta Graph API — ÚNICA definición del servicio API (G26).
# Env: META_GRAPH_API_VERSION (default "v22.0"). Existe para el bump
# calendarizado Q4-2026: Meta depreca versiones ~trimestralmente y subir de
# versión no debe exigir tocar N archivos — basta el env en Render.
# La consume también lib/meta_business_management_client.py.
GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v22.0")
META_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("META_MEDIA_DOWNLOAD_TIMEOUT_SECONDS", "10"))
MEDIA_MAX_BYTES = int(os.getenv("META_MEDIA_MAX_BYTES", str(16 * 1024 * 1024)))

# Caché in-memory. TTL corto porque la URL temporal de Meta expira en ~5 min.
# COPIA API (diverge del orchestrator): endurecida para exposición operator-facing —
#  · CAP DURO por nº de entradas Y por bytes totales, con evicción LRU (oldest-first)
#    INDEPENDIENTE del TTL → no crece sin tope aunque lleguen >N media distintos en la ventana
#    (antes solo evictaba expirados → OOM del proceso API compartido = DoS cross-tenant).
#  · Clave con NAMESPACE por access_token (per-tenant, Model B) → un cache-hit nunca cruza
#    tenants aunque dos media_id coincidieran (defensa en profundidad; el aislamiento principal
#    lo da el check (tenant_id, media_id) del endpoint).
_CACHE_TTL_SECONDS = 240
_CACHE_MAX_ENTRIES = 32
_CACHE_MAX_TOTAL_BYTES = 64 * 1024 * 1024  # 64 MB tope duro del proceso
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, bytes, str]] = {}


class MediaDownloadError(Exception):
    """Cualquier fallo de descarga (timeout, 4xx/5xx, tamaño excedido)."""


def _ns(access_token: str) -> str:
    """Namespace de caché derivado del token (per-tenant) — no expone el secreto."""
    return hashlib.sha256((access_token or "").encode("utf-8")).hexdigest()[:16]


def _cached(cache_key: str) -> Optional[tuple[bytes, str]]:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(cache_key)
        if not entry:
            return None
        ts, data, mime = entry
        if now - ts > _CACHE_TTL_SECONDS:
            _cache.pop(cache_key, None)
            return None
        return data, mime


def _store(cache_key: str, data: bytes, mime: str) -> None:
    with _cache_lock:
        _cache[cache_key] = (time.time(), data, mime)
        # CAP DURO: evictar oldest-first hasta quedar bajo AMBOS límites (entradas y bytes),
        # sin importar el TTL. Esto sí acota la memoria (a diferencia de "solo expirados").
        if len(_cache) > _CACHE_MAX_ENTRIES or sum(len(v[1]) for v in _cache.values()) > _CACHE_MAX_TOTAL_BYTES:
            for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0]):  # por ts ascendente
                if len(_cache) <= _CACHE_MAX_ENTRIES and sum(len(v[1]) for v in _cache.values()) <= _CACHE_MAX_TOTAL_BYTES:
                    break
                _cache.pop(k, None)


async def fetch_media_bytes(media_id: str, access_token: str) -> tuple[bytes, str]:
    """Descarga binary + mime_type de un media_id Meta. Levanta MediaDownloadError.

    Cumple los límites: timeout configurable, tamaño máximo, retorno (bytes, mime).
    """
    if not media_id or not access_token:
        raise MediaDownloadError("media_id o access_token vacío")

    cache_key = f"{_ns(access_token)}:{media_id}"
    cached = _cached(cache_key)
    if cached:
        return cached

    headers = {"Authorization": f"Bearer {access_token}"}
    timeout = httpx.Timeout(DOWNLOAD_TIMEOUT_SECONDS)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Paso 1: resolver URL temporal + mime_type
            meta_resp = await client.get(f"{META_BASE_URL}/{media_id}", headers=headers)
            if meta_resp.status_code != 200:
                raise MediaDownloadError(
                    f"Meta API {meta_resp.status_code} resolviendo media_id={media_id}: {meta_resp.text[:200]}"
                )
            meta_payload = meta_resp.json()
            url = meta_payload.get("url")
            mime = meta_payload.get("mime_type") or ""
            file_size = int(meta_payload.get("file_size") or 0)
            if not url:
                raise MediaDownloadError(f"Meta sin url para media_id={media_id}")
            if file_size and file_size > MEDIA_MAX_BYTES:
                raise MediaDownloadError(
                    f"Media excede límite ({file_size} > {MEDIA_MAX_BYTES} bytes)"
                )

            # Paso 2: descargar binary (Bearer requerido también aquí).
            data_resp = await client.get(url, headers=headers)
            if data_resp.status_code != 200:
                raise MediaDownloadError(
                    f"Meta CDN {data_resp.status_code} descargando media_id={media_id}"
                )
            data = data_resp.content
            if len(data) > MEDIA_MAX_BYTES:
                raise MediaDownloadError(
                    f"Media descargado excede límite ({len(data)} > {MEDIA_MAX_BYTES} bytes)"
                )

            _store(cache_key, data, mime)
            return data, mime

    except httpx.TimeoutException as exc:
        raise MediaDownloadError(f"Timeout ({DOWNLOAD_TIMEOUT_SECONDS}s) descargando media_id={media_id}") from exc
    except httpx.HTTPError as exc:
        raise MediaDownloadError(f"HTTP error descargando media_id={media_id}: {exc}") from exc


# Mime types soportados por gemini-3.5-flash para audio.
# Fuente: https://ai.google.dev/gemini-api/docs/audio
SUPPORTED_AUDIO_MIMES: frozenset[str] = frozenset({
    "audio/wav",
    "audio/mp3",
    "audio/mpeg",
    "audio/aiff",
    "audio/aac",
    "audio/ogg",
    "audio/flac",
})


def is_supported_audio_mime(mime: Optional[str]) -> bool:
    if not mime:
        return False
    base = mime.split(";")[0].strip().lower()
    return base in SUPPORTED_AUDIO_MIMES

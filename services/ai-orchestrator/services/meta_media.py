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
import logging
import os
import time
import threading
from typing import Optional

import httpx

logger = logging.getLogger("orchestrator.meta_media")

META_API_VERSION = "v22.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"

DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("META_MEDIA_DOWNLOAD_TIMEOUT_SECONDS", "10"))
MEDIA_MAX_BYTES = int(os.getenv("META_MEDIA_MAX_BYTES", str(16 * 1024 * 1024)))

# Caché in-memory por media_id. TTL corto porque la URL temporal de Meta
# expira en ~5 min — más allá de eso ya no podemos volver a descargar.
_CACHE_TTL_SECONDS = 240
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, bytes, str]] = {}


class MediaDownloadError(Exception):
    """Cualquier fallo de descarga (timeout, 4xx/5xx, tamaño excedido)."""


def _cached(media_id: str) -> Optional[tuple[bytes, str]]:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(media_id)
        if not entry:
            return None
        ts, data, mime = entry
        if now - ts > _CACHE_TTL_SECONDS:
            _cache.pop(media_id, None)
            return None
        return data, mime


def _store(media_id: str, data: bytes, mime: str) -> None:
    with _cache_lock:
        _cache[media_id] = (time.time(), data, mime)
        # Cleanup oportunista para no crecer sin tope.
        if len(_cache) > 200:
            cutoff = time.time() - _CACHE_TTL_SECONDS
            for k, (ts, _, _) in list(_cache.items()):
                if ts < cutoff:
                    _cache.pop(k, None)


async def fetch_media_bytes(media_id: str, access_token: str) -> tuple[bytes, str]:
    """Descarga binary + mime_type de un media_id Meta. Levanta MediaDownloadError.

    Cumple los límites: timeout configurable, tamaño máximo, retorno (bytes, mime).
    """
    if not media_id or not access_token:
        raise MediaDownloadError("media_id o access_token vacío")

    cached = _cached(media_id)
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

            _store(media_id, data, mime)
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

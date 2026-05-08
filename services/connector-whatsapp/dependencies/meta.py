"""HMAC verification webhooks Meta WhatsApp + tenant resolution forensics.

Rev. 106 Sem 6 (rewrite 2026-05-08, simplificado post-clarificación
arquitectónica con founder).

Modelo arquitectónico real (ver `docs/research/meta-app-architecture-2026-05-08.md`):

  Hay UNA SOLA Meta App, propiedad del Business Portfolio de la plataforma.
  Cada tenant conecta su propia WABA + Phone Number a esa App vía System
  User token generado en el Business Manager del tenant.

  → `app_secret` es GLOBAL (de nuestra App): `META_APP_SECRET` env-var.
  → `phone_number_id`, `waba_id`, `access_token` son PER-TENANT.
  → HMAC `X-Hub-Signature-256` se valida con el global. Punto.

  Lo que SÍ es útil per-tenant aquí: lookup `phone_number_id → tenant_id`
  para forensics + future routing. Cada webhook loguea qué tenant lo
  generó (auditoría Habeas Data + debugging multi-tenant).

Trade-off: no usa F.1 webhook framework por aislamiento de deploy unit
(Render rootDir distinto). Cuando se consolide en services/api, migrar.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import threading
import time
from typing import Optional

from fastapi import Request, HTTPException, Header

logger = logging.getLogger(__name__)

# App Secret de la Meta App de la plataforma. Único, global.
# Configurado en Render env: services/connector-whatsapp/META_APP_SECRET.
# Meta firma TODOS los webhooks con este secret (todos los tenants comparten).
META_APP_SECRET = os.getenv("META_APP_SECRET", "")

# Cache TTL para lookup `phone_number_id → tenant_id`. 5min balance entre
# frescura post-onboarding nuevo tenant y reducción hits Supabase.
_CACHE_TTL_SECONDS = 300

_cache_lock = threading.RLock()
_tenant_cache: dict[str, tuple[Optional[str], float]] = {}  # phone_number_id → (tenant_id, expires_at)


def _cache_get_tenant(phone_number_id: str) -> tuple[bool, Optional[str]]:
    """Retorna (cache_hit, tenant_id_or_none). cache_hit=False puede ser
    miss o expiración. tenant_id_or_none=None es un valor cacheable
    legítimo ("ningún tenant tiene este phone_number_id")."""
    with _cache_lock:
        entry = _tenant_cache.get(phone_number_id)
        if entry is None:
            return False, None
        tenant_id, expires_at = entry
        if time.time() >= expires_at:
            del _tenant_cache[phone_number_id]
            return False, None
        return True, tenant_id


def _cache_put_tenant(phone_number_id: str, tenant_id: Optional[str]) -> None:
    """Cachea el resultado del lookup (puede ser None — "no encontrado")."""
    with _cache_lock:
        _tenant_cache[phone_number_id] = (tenant_id, time.time() + _CACHE_TTL_SECONDS)


def _cache_invalidate(phone_number_id: Optional[str] = None) -> int:
    """Invalida cache. Útil tras onboarding nuevo tenant. Retorna # entries."""
    with _cache_lock:
        if phone_number_id is None:
            n = len(_tenant_cache)
            _tenant_cache.clear()
            return n
        if phone_number_id in _tenant_cache:
            del _tenant_cache[phone_number_id]
            return 1
        return 0


def _extract_phone_number_id(raw_body: bytes) -> Optional[str]:
    """Parsea raw_body como JSON Meta y extrae el primer `phone_number_id`
    encontrado en `entry[].changes[].value.metadata.phone_number_id`.

    Retorna None si payload no es JSON o no tiene phone_number_id (caso
    GET handshake, payload de account_alerts, etc.). Caller decide.
    """
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, ValueError):
        return None

    entries = payload.get("entry") or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes") or []
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") or {}
            if isinstance(metadata, dict):
                pid = metadata.get("phone_number_id")
                if pid:
                    return str(pid)
    return None


def _resolve_tenant_id_for_phone_number(phone_number_id: str) -> Optional[str]:
    """Lookup `phone_number_id → tenant_id` para forensics + routing.

    NO se usa para HMAC (el secret es global). Sólo para:
      - Loguear `tenant_id` en cada webhook (auditoría + debugging).
      - Future: routing per-tenant si fuera necesario.

    Cache TTL 5min para evitar hits Supabase en cada webhook.
    Resultado None se cachea ("no hay tenant con ese phone_number_id"
    — caso edge: tenant offboarded pero Meta sigue enviando webhooks
    durante ventana de propagación).
    """
    cache_hit, cached = _cache_get_tenant(phone_number_id)
    if cache_hit:
        return cached

    try:
        from services.db_persistence import get_supabase  # noqa: PLC0415
    except ImportError as e:
        logger.error("[META_HMAC] no se puede importar get_supabase: %s", e)
        return None

    try:
        sb = get_supabase()
    except RuntimeError as e:
        logger.error("[META_HMAC] Supabase no configurado: %s", e)
        return None

    try:
        res = (
            sb.table("tenant_integrations")
            .select("tenant_id, credentials")
            .eq("provider", "whatsapp")
            .eq("status", "connected")
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        logger.error("[META_HMAC] error consultando tenant_integrations: %s", e)
        return None

    for row in rows:
        creds = (row or {}).get("credentials") or {}
        if not isinstance(creds, dict):
            continue
        if str(creds.get("phone_number_id") or "") == phone_number_id:
            tenant_id = row.get("tenant_id")
            _cache_put_tenant(phone_number_id, tenant_id)
            return tenant_id

    # No tenant found — cache también (TTL 5min limit) para evitar
    # hits repetidos en webhooks de phone_number_ids huérfanos.
    _cache_put_tenant(phone_number_id, None)
    return None


def _hmac_verify(raw_body: bytes, signature_hex: str, app_secret: str) -> bool:
    """Verifica HMAC SHA-256 constant-time."""
    expected = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_hex)


async def verify_meta_signature(
    request: Request,
    x_hub_signature_256: str = Header(None),
) -> bytes:
    """Dependencia FastAPI: bloquea requests con HMAC inválido.

    Modelo (rev. 2026-05-08):
      1. Lee raw_body.
      2. Verifica HMAC SHA-256 con `META_APP_SECRET` global (de nuestra
         Meta App, propiedad del Business Portfolio de la plataforma).
      3. (Forensics) Extrae phone_number_id del payload, resuelve
         tenant_id, loguea para auditoría/debugging. NO bloquea ni
         cambia el HMAC verify — sólo informativo.

    Levanta HTTPException 403 ante:
      - Missing X-Hub-Signature-256
      - Algoritmo distinto a sha256
      - META_APP_SECRET no configurado en runtime
      - HMAC mismatch (payload manipulado o secret incorrecto)

    Retorna raw_body para uso downstream (BackgroundTask procesamiento).
    """
    if not x_hub_signature_256:
        logger.warning("[META_HMAC] firma X-Hub-Signature-256 ausente")
        raise HTTPException(status_code=403, detail="Missing signature")

    algo, _, signature_hex = x_hub_signature_256.partition("=")
    if algo != "sha256" or not signature_hex:
        raise HTTPException(status_code=403, detail="Unsupported signature algorithm")

    if not META_APP_SECRET:
        logger.error("[META_HMAC] META_APP_SECRET no configurado en runtime")
        raise HTTPException(status_code=503, detail="Server misconfigured: app_secret missing")

    raw_body = await request.body()

    if not _hmac_verify(raw_body, signature_hex, META_APP_SECRET):
        logger.warning(
            "[META_HMAC] HMAC mismatch — payload manipulado o META_APP_SECRET "
            "no coincide con el de la Meta App registrada en developers.facebook.com"
        )
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Forensics (no-bloqueante): resolver tenant_id por phone_number_id.
    # Sirve para loguear auditoría Habeas Data Ley 1581 + debugging
    # multi-tenant. Si no resuelve, payload sigue procesándose normal.
    phone_number_id = _extract_phone_number_id(raw_body)
    if phone_number_id:
        tenant_id = _resolve_tenant_id_for_phone_number(phone_number_id)
        if tenant_id:
            logger.info(
                "[META_HMAC] webhook OK tenant=%s phone_number_id=%s",
                tenant_id, phone_number_id,
            )
        else:
            # phone_number_id no resuelve a tenant — log INFO, no warn.
            # Casos legítimos: GET handshake, account_alerts pre-onboarding,
            # webhooks durante propagación post-disconnect tenant.
            logger.info(
                "[META_HMAC] webhook OK pero phone_number_id=%s no resuelve "
                "tenant (puede ser pre-onboarding o tenant disconnected)",
                phone_number_id,
            )
    # Si no hay phone_number_id → payload no-message (account_alerts,
    # GET handshake, etc.). No log adicional — sigue flujo normal.

    return raw_body

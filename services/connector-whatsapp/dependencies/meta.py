"""HMAC verification per-tenant para webhooks Meta WhatsApp.

Rev. 106 Sem 6 pre-HSM (2026-05-08): rewrite del módulo histórico que
usaba `META_APP_SECRET` global env-var. Ahora resuelve el `app_secret`
**per-tenant** via lookup en `tenant_integrations.credentials` por
`phone_number_id` extraído del payload Meta.

Por qué inline (no F.1 webhook framework):
  - `connector-whatsapp` es deploy unit independiente en Render
    (rootDir: services/connector-whatsapp). NO puede importar de
    `services/api/lib/webhook_framework/` sin cross-service coupling.
  - F.1 sigue siendo el patrón canónico para webhooks que viven en
    `services/api/` (Wompi, MeLi, Envia inbound).
  - Cuando el connector se consolide en services/api (futuro refactor
    arquitectónico), migrar a F.1 será trivial — la lógica HMAC es
    idéntica.

Trade-off: pequeña duplicación (HMAC SHA-256 + constant-time compare)
a cambio de aislamiento de deploy unit. Aceptado en gap audit
docs/research/f1-f2-meta-gap-audit-2026-05-08.md sec. 2.4.

Backward compat: si `META_APP_SECRET` env-var está presente Y NO se
encuentra `phone_number_id` en payload, usa el secret global (modo
mono-tenant legacy). Logueado como WARN para forzar migración.

Cache TTL 5min para evitar hit DB en cada webhook (similar pattern F.11).
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

# Backward compat env-var. Si presente, se usa como fallback cuando no se
# resuelve secret per-tenant (warn). Borrar tras migración completa.
LEGACY_META_APP_SECRET = os.getenv("META_APP_SECRET", "")

# Cache TTL para (phone_number_id → app_secret) lookups. 5min balance
# entre frescura post-rotación y reducción hits Supabase + Vault.
_CACHE_TTL_SECONDS = 300

# In-memory cache thread-safe. NO persiste — single-process FastAPI.
_cache_lock = threading.RLock()
_secret_cache: dict[str, tuple[str, float]] = {}  # phone_number_id → (secret, expires_at)


def _cache_get(phone_number_id: str) -> Optional[str]:
    with _cache_lock:
        entry = _secret_cache.get(phone_number_id)
        if entry is None:
            return None
        secret, expires_at = entry
        if time.time() >= expires_at:
            del _secret_cache[phone_number_id]
            return None
        return secret


def _cache_put(phone_number_id: str, secret: str) -> None:
    with _cache_lock:
        _secret_cache[phone_number_id] = (secret, time.time() + _CACHE_TTL_SECONDS)


def _cache_invalidate(phone_number_id: Optional[str] = None) -> int:
    """Invalida cache. Útil tras rotación de credenciales/offboarding.
    Si phone_number_id=None borra todo. Retorna # entradas borradas."""
    with _cache_lock:
        if phone_number_id is None:
            n = len(_secret_cache)
            _secret_cache.clear()
            return n
        if phone_number_id in _secret_cache:
            del _secret_cache[phone_number_id]
            return 1
        return 0


def _extract_phone_number_id(raw_body: bytes) -> Optional[str]:
    """Parsea raw_body como JSON Meta y extrae el primer phone_number_id
    encontrado en `entry[].changes[].value.metadata.phone_number_id`.

    Retorna None si payload no es JSON o no tiene phone_number_id (caso
    GET handshake o payload malformado — handler superior decide qué hacer).
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


def _resolve_app_secret_for_phone_number(phone_number_id: str) -> Optional[str]:
    """Resuelve app_secret para el WABA dueño de phone_number_id.

    Lookup:
      1. Cache TTL 5min.
      2. Si miss: SELECT credentials FROM tenant_integrations
         WHERE provider='whatsapp' AND credentials->>'phone_number_id' = ?
      3. Resolver app_secret: Vault first (`app_secret_secret_id`) → plaintext fallback.
      4. Cache result.
    """
    cached = _cache_get(phone_number_id)
    if cached is not None:
        return cached

    # Lazy import — evita romper el módulo si Supabase no está configurado
    # en runtime (ej. tests unitarios sin DB).
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
        # PostgREST: usar `eq()` con notación JSONB `->>` no se soporta directo,
        # pero podemos filtrar con `.eq("credentials->>phone_number_id", ...)`
        # vía la sintaxis `select(...).filter(...)`. Más simple: select todos
        # whatsapp connected y filtrar in-Python (pocos tenants por ahora).
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
        if str(creds.get("phone_number_id") or "") != phone_number_id:
            continue

        # Match — resolver app_secret.
        secret_id = creds.get("app_secret_secret_id")
        if secret_id:
            secret = _read_vault_secret(sb, secret_id)
            if secret:
                _cache_put(phone_number_id, secret)
                return secret
            logger.warning(
                "[META_HMAC] app_secret_secret_id presente pero Vault retornó vacío "
                "tenant=%s phone_number_id=%s",
                row.get("tenant_id"), phone_number_id,
            )

        plain = creds.get("app_secret")
        if plain:
            logger.warning(
                "[META_HMAC] app_secret en plaintext — migrar a Vault recomendado "
                "tenant=%s phone_number_id=%s",
                row.get("tenant_id"), phone_number_id,
            )
            _cache_put(phone_number_id, plain)
            return plain

        logger.warning(
            "[META_HMAC] tenant matchea phone_number_id=%s pero no tiene "
            "app_secret_secret_id ni app_secret en credentials",
            phone_number_id,
        )
        return None

    logger.warning(
        "[META_HMAC] no se encontró tenant con phone_number_id=%s",
        phone_number_id,
    )
    return None


def _read_vault_secret(sb, secret_id: str) -> Optional[str]:
    """Lee secret de Vault via RPC pgsec_read_secret. Inline para evitar
    dep de services/api/vault_helper.py (cross-service coupling)."""
    try:
        r = sb.rpc("pgsec_read_secret", {"p_id": secret_id}).execute()
        return r.data
    except Exception as e:
        logger.error("[META_HMAC] Vault read '%s' error: %s", secret_id, e)
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

    Resolución per-tenant rev. 2026-05-08:
      1. Lee raw_body.
      2. Extrae phone_number_id del payload (JSON entry[].changes[].value.metadata).
      3. Lookup tenant via tenant_integrations.credentials.phone_number_id.
      4. Resuelve app_secret per-tenant (Vault o plaintext).
      5. Verifica HMAC SHA-256 contra X-Hub-Signature-256.

    Backward compat: si phone_number_id NO se extrae Y `META_APP_SECRET`
    env-var está presente, usa el secret global (warn). Útil durante
    transición; remover env-var fuerza modo per-tenant exclusivamente.

    Levanta HTTPException 403 ante cualquier fallo de verificación.
    Retorna raw_body para uso downstream (BackgroundTask procesamiento).
    """
    if not x_hub_signature_256:
        logger.warning("[META_HMAC] firma X-Hub-Signature-256 ausente")
        raise HTTPException(status_code=403, detail="Missing signature")

    # Header puede venir con prefijo "sha256=".
    algo, _, signature_hex = x_hub_signature_256.partition("=")
    if algo != "sha256" or not signature_hex:
        raise HTTPException(status_code=403, detail="Unsupported signature algorithm")

    raw_body = await request.body()

    # Resolver app_secret per-tenant.
    phone_number_id = _extract_phone_number_id(raw_body)
    app_secret: Optional[str] = None

    if phone_number_id:
        app_secret = _resolve_app_secret_for_phone_number(phone_number_id)

    if not app_secret:
        # Fallback global (legacy mono-tenant). Warn agresivo para forzar migración.
        if LEGACY_META_APP_SECRET and not phone_number_id:
            logger.warning(
                "[META_HMAC] usando META_APP_SECRET global (legacy) — "
                "phone_number_id no extraído del payload"
            )
            app_secret = LEGACY_META_APP_SECRET
        elif LEGACY_META_APP_SECRET:
            logger.warning(
                "[META_HMAC] usando META_APP_SECRET global (legacy) — "
                "phone_number_id=%s no resolvió tenant. Migrar tenant a "
                "credentials.app_secret_secret_id",
                phone_number_id,
            )
            app_secret = LEGACY_META_APP_SECRET

    if not app_secret:
        logger.error(
            "[META_HMAC] app_secret no resuelto. phone_number_id=%s legacy_present=%s",
            phone_number_id, bool(LEGACY_META_APP_SECRET),
        )
        raise HTTPException(status_code=403, detail="App secret not resolved")

    if not _hmac_verify(raw_body, signature_hex, app_secret):
        logger.warning(
            "[META_HMAC] HMAC mismatch — payload manipulado o app_secret incorrecto. "
            "phone_number_id=%s",
            phone_number_id,
        )
        raise HTTPException(status_code=403, detail="Invalid signature")

    return raw_body

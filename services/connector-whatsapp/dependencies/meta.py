"""HMAC verification webhooks Meta WhatsApp — Model B Direct Provider per-tenant.

Rev. 110 (rewrite 2026-06-22 per ADR-0023).

Modelo arquitectónico Model B (Direct Provider per-tenant):

  Cada tenant trae SU PROPIA Meta App (con SU PROPIO App Secret + Verify Token
  + WABA + Phone Number + System User token). Konvi connector recibe webhooks
  de N Meta Apps distintas y enruta por path:

    POST /api/v1/whatsapp/webhook/{tenant_id}

  → `tenant_id` viene del URL path (routing seguro pre-HMAC, evita chicken-and-egg)
  → Para cada tenant, lookup `credentials.app_secret_secret_id` en Vault
  → HMAC SHA-256 valida con el secret per-tenant
  → Defense-in-depth: tras HMAC OK, verifica que `payload.phone_number_id` también
    resuelva a `tenant_id` (cross-tenant attack defense)

Tablas:
  - `tenant_integrations.credentials`:
      app_id: str (Meta App ID del tenant)
      app_secret_secret_id: UUID (Vault reference, secret en claro vía pgsec_read_secret)
      verify_token: str (clear en JSONB, no es secret crítico)
      phone_number_id: str
      waba_id: str
      access_token_secret_id: UUID (Vault reference)
      webhook_url_path_segment: str (decorativo, no usado para routing — el tenant_id UUID es la PK)
      integration_role: 'tenant_internal' | 'tenant_1st' | etc.
      integration_type: 'direct_provider'

Caches (300s TTL):
  - phone_number_id → tenant_id (forensics + invariant check)
  - tenant_id → app_secret (per-request HMAC)
  - tenant_id → verify_token (GET handshake)
  Single-flight lock previene stampede de Vault lookups en cold cache.

Status filter:
  Lookup acepta status IN ('connected', 'pending_token') durante onboarding window
  (permite recibir 1er webhook antes de que el tenant tenga access_token outbound).

Trade-off: no usa F.1 webhook framework por aislamiento de deploy unit
(Render rootDir distinto). Cuando se consolide en services/api, migrar.

Métricas en memoria expuestas en GET /health/metrics:
  hmac_ok, hmac_fail_invalid, hmac_fail_no_tenant, hmac_fail_no_secret,
  hmac_fail_cross_tenant, vault_hits, cache_hits (per cache),
  unique_tenants_seen.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import threading
import time
from typing import Optional

from starlette.concurrency import run_in_threadpool

from fastapi import Request, HTTPException, Header

logger = logging.getLogger(__name__)

# ─── Caches ─────────────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 300

_cache_lock = threading.RLock()
_phone_to_tenant_cache: dict[str, tuple[Optional[str], float]] = {}
_app_secret_cache: dict[str, tuple[Optional[str], float]] = {}
_verify_token_cache: dict[str, tuple[Optional[str], float]] = {}

# Single-flight: previene stampede en cold cache (E2 adversarial)
_inflight_app_secret: dict[str, threading.Event] = {}
_inflight_verify_token: dict[str, threading.Event] = {}

# ─── Métricas en memoria (observabilidad G-OPS-1) ───────────────────────────

_metrics_lock = threading.Lock()
_metrics: dict[str, int] = {
    "hmac_ok": 0,
    "hmac_fail_invalid_signature": 0,
    "hmac_fail_missing_signature": 0,
    "hmac_fail_unsupported_algo": 0,
    "hmac_fail_no_tenant_in_path": 0,
    "hmac_fail_no_secret_for_tenant": 0,
    "hmac_fail_cross_tenant_invariant": 0,
    "vault_hits_app_secret": 0,
    "vault_hits_verify_token": 0,
    "cache_hits_app_secret": 0,
    "cache_hits_verify_token": 0,
    "cache_hits_phone_to_tenant": 0,
}
_unique_tenants_seen: set[str] = set()


def get_metrics_snapshot() -> dict:
    """Snapshot inmutable de métricas para exponer en /health/metrics."""
    with _metrics_lock:
        return {
            **_metrics,
            "unique_tenants_seen": len(_unique_tenants_seen),
        }


def _incr_metric(name: str, n: int = 1) -> None:
    with _metrics_lock:
        _metrics[name] = _metrics.get(name, 0) + n


def _record_tenant_seen(tenant_id: str) -> None:
    with _metrics_lock:
        _unique_tenants_seen.add(tenant_id)


# ─── Cache helpers ──────────────────────────────────────────────────────────


def _cache_get(cache: dict, key: str) -> tuple[bool, Optional[str]]:
    with _cache_lock:
        entry = cache.get(key)
        if entry is None:
            return False, None
        value, expires_at = entry
        if time.time() >= expires_at:
            del cache[key]
            return False, None
        return True, value


def _cache_put(cache: dict, key: str, value: Optional[str]) -> None:
    with _cache_lock:
        cache[key] = (value, time.time() + _CACHE_TTL_SECONDS)


def _cache_invalidate_all() -> int:
    """Limpia todos los caches (útil tras onboarding nuevo tenant)."""
    with _cache_lock:
        n = (
            len(_phone_to_tenant_cache)
            + len(_app_secret_cache)
            + len(_verify_token_cache)
        )
        _phone_to_tenant_cache.clear()
        _app_secret_cache.clear()
        _verify_token_cache.clear()
        return n


# ─── Single-flight wrapper ──────────────────────────────────────────────────


def _single_flight(
    cache: dict,
    inflight: dict,
    key: str,
    fetch_fn,
) -> Optional[str]:
    """Si otro hilo está fetcheando la misma key, espera; sino fetch + cache.

    Previene stampede de N peticiones simultáneas al Vault para mismo tenant
    en cold cache (E2 adversarial review)."""
    cache_hit, cached = _cache_get(cache, key)
    if cache_hit:
        return cached

    # Determine if we are leader (do fetch) or follower (wait)
    do_fetch = False
    with _cache_lock:
        event = inflight.get(key)
        if event is None:
            event = threading.Event()
            inflight[key] = event
            do_fetch = True

    if not do_fetch:
        event.wait(timeout=5.0)
        _, cached = _cache_get(cache, key)
        return cached

    try:
        value = fetch_fn()
        _cache_put(cache, key, value)
        return value
    finally:
        with _cache_lock:
            inflight.pop(key, None)
            event.set()


# ─── Supabase helper (lazy import para no romper test units sin Supabase) ───


def _get_sb_client():
    """Obtiene Supabase client. Lazy import + lazy load .env."""
    try:
        from services.db_persistence import get_supabase
    except ImportError as e:
        logger.error("[META_HMAC] no se puede importar get_supabase: %s", e)
        return None
    try:
        return get_supabase()
    except RuntimeError as e:
        logger.error("[META_HMAC] Supabase no configurado: %s", e)
        return None


# ─── Lookups per-tenant ─────────────────────────────────────────────────────


def _fetch_tenant_credentials(tenant_id: str) -> Optional[dict]:
    """Lookup directo `tenant_integrations.credentials` por tenant_id.

    Acepta status IN ('connected', 'pending_token') durante onboarding window
    (Q3 ADR-0023).
    """
    sb = _get_sb_client()
    if sb is None:
        return None
    try:
        res = (
            sb.table("tenant_integrations")
            .select("credentials")
            .eq("tenant_id", tenant_id)
            .eq("provider", "whatsapp")
            .in_("status", ["connected", "pending_token"])
            .maybe_single()
            .execute()
        )
    except Exception as e:
        logger.error("[META_HMAC] error consultando credentials tenant=%s: %s",
                     tenant_id, e)
        return None
    row = (res.data or {}) if res else {}
    return row.get("credentials") or {}


def _resolve_tenant_app_secret(tenant_id: str) -> Optional[str]:
    """Lookup app_secret per-tenant via Vault. Cacheado 300s + single-flight."""
    def fetch():
        t0 = time.time()
        creds = _fetch_tenant_credentials(tenant_id)
        if not creds:
            return None
        secret_id = creds.get("app_secret_secret_id")
        if not secret_id:
            return None
        # Vault lookup via VaultHelper
        try:
            from lib.vault_helper import VaultHelper
        except ImportError as e:
            logger.error("[META_HMAC] no se puede importar VaultHelper: %s", e)
            return None
        sb = _get_sb_client()
        if sb is None:
            return None
        vault = VaultHelper(sb)
        secret = vault.read_secret(secret_id)
        elapsed_ms = int((time.time() - t0) * 1000)
        _incr_metric("vault_hits_app_secret")
        logger.info(
            "[META_HMAC] vault lookup app_secret tenant=%s elapsed_ms=%d ok=%s",
            tenant_id, elapsed_ms, bool(secret),
        )
        return secret

    cache_hit, _ = _cache_get(_app_secret_cache, tenant_id)
    if cache_hit:
        _incr_metric("cache_hits_app_secret")
    return _single_flight(_app_secret_cache, _inflight_app_secret, tenant_id, fetch)


def _resolve_tenant_verify_token(tenant_id: str) -> Optional[str]:
    """Lookup verify_token per-tenant. NO en Vault — vive en claro en credentials JSONB."""
    def fetch():
        creds = _fetch_tenant_credentials(tenant_id)
        if not creds:
            return None
        token = creds.get("verify_token")
        return str(token) if token else None

    cache_hit, _ = _cache_get(_verify_token_cache, tenant_id)
    if cache_hit:
        _incr_metric("cache_hits_verify_token")
    return _single_flight(_verify_token_cache, _inflight_verify_token, tenant_id, fetch)


def _extract_phone_number_id(raw_body: bytes) -> Optional[str]:
    """Parsea raw_body como JSON Meta y extrae el primer `phone_number_id`."""
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
    """Lookup `phone_number_id → tenant_id` para forensics + invariant check
    cross-tenant. Cacheado 300s. Acepta status IN ('connected','pending_token').
    """
    cache_hit, cached = _cache_get(_phone_to_tenant_cache, phone_number_id)
    if cache_hit:
        _incr_metric("cache_hits_phone_to_tenant")
        return cached

    sb = _get_sb_client()
    if sb is None:
        return None

    try:
        res = (
            sb.table("tenant_integrations")  # tenant_filter:exempt:resolution_lookup_phone_number_id_to_tenant
            .select("tenant_id, credentials")
            .eq("provider", "whatsapp")
            .in_("status", ["connected", "pending_token"])
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
            _cache_put(_phone_to_tenant_cache, phone_number_id, tenant_id)
            return tenant_id

    _cache_put(_phone_to_tenant_cache, phone_number_id, None)
    return None


# ─── HMAC verification ──────────────────────────────────────────────────────


def _hmac_verify(raw_body: bytes, signature_hex: str, app_secret: str) -> bool:
    """Verifica HMAC SHA-256 constant-time."""
    expected = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_hex)


async def verify_meta_signature_for_tenant(
    tenant_id: str,
    request: Request,
    x_hub_signature_256: str = Header(None),
) -> bytes:
    """Dependencia FastAPI: valida HMAC con secret per-tenant.

    Flow Model B:
      1. tenant_id viene del URL path.
      2. Lookup `app_secret` per-tenant en Vault (cache + single-flight).
      3. Validate HMAC SHA-256 con el secret resolved.
      4. Defense-in-depth: extrae phone_number_id del payload, resuelve
         a tenant_id_resolved. Si difiere de tenant_id (path) → 403.
      5. Retorna raw_body para downstream procesamiento.

    Responses:
      403 Forbidden — cualquier fallo de auth (NO 503 para no distinguir
                      "no tenant" vs "wrong signature" a un atacante).
      raw_body bytes — éxito.
    """
    if not x_hub_signature_256:
        _incr_metric("hmac_fail_missing_signature")
        logger.warning("[META_HMAC] tenant=%s signature missing", tenant_id)
        raise HTTPException(status_code=403, detail="Missing signature")

    algo, _, signature_hex = x_hub_signature_256.partition("=")
    if algo != "sha256" or not signature_hex:
        _incr_metric("hmac_fail_unsupported_algo")
        logger.warning("[META_HMAC] tenant=%s unsupported algo=%s", tenant_id, algo)
        raise HTTPException(status_code=403, detail="Unsupported signature algorithm")

    if not tenant_id:
        _incr_metric("hmac_fail_no_tenant_in_path")
        raise HTTPException(status_code=403, detail="Missing tenant_id")

    # F53: lookup con HTTP síncrono (Supabase + Vault) — al threadpool para no bloquear el event loop.
    app_secret = await run_in_threadpool(_resolve_tenant_app_secret, tenant_id)
    if not app_secret:
        _incr_metric("hmac_fail_no_secret_for_tenant")
        logger.warning(
            "[META_HMAC] tenant=%s no app_secret en Vault — credentials incompletos "
            "o tenant no whatsapp-connected", tenant_id,
        )
        # Misma response que invalid signature — no leak de existencia tenant.
        raise HTTPException(status_code=403, detail="Invalid signature")

    raw_body = await request.body()

    if not _hmac_verify(raw_body, signature_hex, app_secret):
        _incr_metric("hmac_fail_invalid_signature")
        logger.warning(
            "[META_HMAC] tenant=%s HMAC mismatch — payload manipulado o secret no "
            "coincide con Meta App registrada", tenant_id,
        )
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Defense-in-depth: cross-tenant invariant.
    # Si payload tiene phone_number_id, debe resolver al MISMO tenant_id del path.
    # Sin esto, un atacante con secret de tenant A podría enviar payload de tenant B
    # al endpoint /webhook/{tenant_a_id}. Cierre del scope.
    phone_number_id = _extract_phone_number_id(raw_body)
    if phone_number_id:
        tenant_id_resolved = await run_in_threadpool(_resolve_tenant_id_for_phone_number, phone_number_id)
        if tenant_id_resolved and tenant_id_resolved != tenant_id:
            _incr_metric("hmac_fail_cross_tenant_invariant")
            logger.warning(
                "[META_HMAC] cross-tenant invariant FAIL: path_tenant=%s payload_tenant=%s "
                "phone_number_id=%s — posible attack",
                tenant_id, tenant_id_resolved, phone_number_id,
            )
            raise HTTPException(status_code=403, detail="Invalid signature")
        # tenant_id_resolved == tenant_id (OK) o None (legítimo en onboarding window)

    _incr_metric("hmac_ok")
    _record_tenant_seen(tenant_id)
    logger.info(
        "[META_HMAC] tenant=%s phone_number_id=%s webhook OK",
        tenant_id, phone_number_id or "<none>",
    )

    return raw_body

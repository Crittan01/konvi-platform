"""TenantCredentialsFacade — acceso unificado a credenciales per-tenant
(rev. 105 Sem 2 F.11 / MA-3).

Resuelve dos problemas identificados en meta-análisis cross-dossier 2026-05-05:
  1. **Boilerplate**: 9 esquemas auth distintos (Wompi 4 keys, Envia bearer,
     MeLi OAuth 6h refresh, WhatsApp Token, Telegram bot token, etc.) generan
     código repetido tipo "obtener key X de tenant Y" en cada router.
  2. **Sin forensics**: no hay registro de quién accedió a qué credencial
     cuándo. Habeas Data Ley 1581 ART. 17 exige auditoría de accesos a
     datos personales — credenciales son meta-datos sensibles equivalentes.

El facade:
  - **Cachea in-memory TTL 5min** por (tenant_id, provider, credential_name).
    Reduce hits a Vault/DB en ~95% para flujos de alta frecuencia
    (orchestrator, webhooks).
  - **Audit log forensics** vía tabla credential_access_log (append-only,
    retención 7 años). Cada read se loguea con cache_hit flag.
  - **Wrappea VaultHelper.resolve_secret existente** — no rompe nada,
    sólo agrega caché + audit alrededor.

Uso típico:
    from lib.credentials_facade import TenantCredentialsFacade

    facade = TenantCredentialsFacade(supabase_client, service_name="api")
    private_key = facade.get(tenant_id, "wompi", "private_key")
    bot_token = facade.get(tenant_id, "telegram", "bot_token")
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# TTL caché in-memory. 5min balance entre frescura (rotación de secrets,
# offboarding) y reducción de hits Vault.
DEFAULT_CACHE_TTL_SECONDS = 300

# Servicios canónicos que pueden invocar el facade. NO es enum — solo
# para validación defensiva del audit log.
KNOWN_SERVICES = frozenset({
    "api", "orchestrator", "connector-whatsapp", "connector-meli",
    "cron", "worker", "test",
})


@dataclass(frozen=True)
class _CacheEntry:
    value: Optional[str]
    expires_at: float  # epoch seconds


class _Cache:
    """Caché in-memory thread-safe TTL. NO persiste — se reinicia con el
    proceso. Apropiado para servicios FastAPI single-process; en futuro
    multi-worker considerar Redis."""

    def __init__(self, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._store: dict[tuple[str, str, str], _CacheEntry] = {}
        self._lock = threading.RLock()

    def get(self, key: tuple[str, str, str]) -> tuple[bool, Optional[str]]:
        """Retorna (cache_hit, value). cache_hit=False puede deberse a
        miss o a expiración (ambos requieren refresh)."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False, None
            if time.time() >= entry.expires_at:
                del self._store[key]
                return False, None
            return True, entry.value

    def put(self, key: tuple[str, str, str], value: Optional[str]) -> None:
        with self._lock:
            self._store[key] = _CacheEntry(
                value=value,
                expires_at=time.time() + self._ttl,
            )

    def invalidate(self, tenant_id: str, provider: Optional[str] = None) -> int:
        """Borra entries de un tenant (todas o por provider). Útil tras
        rotación de credenciales / offboarding. Retorna # entries borradas."""
        with self._lock:
            keys_to_del = []
            for key in self._store.keys():
                if key[0] != tenant_id:
                    continue
                if provider is not None and key[1] != provider:
                    continue
                keys_to_del.append(key)
            for key in keys_to_del:
                del self._store[key]
            return len(keys_to_del)

    def clear(self) -> None:
        """Borra TODA la caché (usar con cuidado, ej. tests, restart sentinel)."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


# Singleton caché compartida entre instancias del facade en mismo proceso.
_GLOBAL_CACHE = _Cache()


class TenantCredentialsFacade:
    """Facade unificado per request. Construir uno por request del API
    (idealmente como dependency injection en FastAPI).

    NOTA: la caché es global al proceso — múltiples instancias del facade
    comparten el mismo store. Esto es deseable para reducir hits a Vault,
    pero impone que la invalidación sea explícita tras rotaciones."""

    def __init__(
        self,
        supabase_client: Any,
        service_name: str = "api",
        request_id: Optional[str] = None,
        cache: Optional[_Cache] = None,
        audit_enabled: bool = True,
    ):
        if service_name not in KNOWN_SERVICES:
            logger.warning(
                "[CRED_FACADE] service_name %r no canónico (esperado %s)",
                service_name, sorted(KNOWN_SERVICES),
            )
        self._sb = supabase_client
        self._service = service_name
        self._request_id = request_id
        self._cache = cache if cache is not None else _GLOBAL_CACHE
        self._audit_enabled = audit_enabled

    def get(
        self,
        tenant_id: str,
        provider: str,
        credential_name: str,
    ) -> Optional[str]:
        """Lee una credencial. Caché-first; on miss, lee de tenant_integrations
        + Vault. Loguea acceso en credential_access_log (cache_hit=True/False).

        Retorna None si la credencial no existe (no es error — el caller
        decide cómo manejar tenant sin esa integración configurada)."""
        key = (tenant_id, provider, credential_name)
        cache_hit, cached_value = self._cache.get(key)
        if cache_hit:
            self._log_access(tenant_id, provider, credential_name, cache_hit=True)
            return cached_value

        # Miss: leer desde DB + Vault.
        value = self._read_from_source(tenant_id, provider, credential_name)
        self._cache.put(key, value)
        self._log_access(tenant_id, provider, credential_name, cache_hit=False)
        return value

    def invalidate(self, tenant_id: str, provider: Optional[str] = None) -> int:
        """Invalida caché para un tenant. Llamar tras rotación de credenciales
        o offboarding del tenant. Retorna # entries invalidadas."""
        n = self._cache.invalidate(tenant_id, provider)
        logger.info(
            "[CRED_FACADE] invalidate tenant=%s provider=%s entries=%d",
            tenant_id, provider or "*", n,
        )
        return n

    # ─── Internos ─────────────────────────────────────────────────────────

    def _read_from_source(
        self,
        tenant_id: str,
        provider: str,
        credential_name: str,
    ) -> Optional[str]:
        """Lee credencial desde tenant_integrations.credentials (JSONB) +
        Vault si está como secret_id. Compatible con el patrón existente
        VaultHelper.resolve_secret."""
        try:
            res = (
                self._sb.table("tenant_integrations")
                .select("credentials")
                .eq("tenant_id", tenant_id)
                .eq("provider", provider)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return None
            creds = (rows[0] or {}).get("credentials") or {}

            # Vault primero (preferido) — patrón {field}_secret_id apunta a Vault UUID.
            secret_id = creds.get(f"{credential_name}_secret_id")
            if secret_id:
                # Lazy import para no forzar dependency en clientes que no usen Vault.
                try:
                    from vault_helper import VaultHelper  # noqa: PLC0415
                    return VaultHelper(self._sb).read_secret(secret_id)
                except Exception as e:  # pragma: no cover
                    logger.error(
                        "[CRED_FACADE] error leyendo Vault tenant=%s provider=%s "
                        "field=%s: %s",
                        tenant_id, provider, credential_name, e,
                    )
                    return None

            # Fallback plaintext (legacy, advertir migración).
            plain = creds.get(credential_name)
            if plain:
                logger.warning(
                    "[CRED_FACADE] credential %s.%s en plaintext para tenant %s "
                    "— migrar a Vault recomendado",
                    provider, credential_name, tenant_id,
                )
            return plain
        except Exception as e:  # pragma: no cover
            logger.error(
                "[CRED_FACADE] read_from_source error tenant=%s provider=%s "
                "field=%s: %s",
                tenant_id, provider, credential_name, e,
            )
            return None

    def _log_access(
        self,
        tenant_id: str,
        provider: str,
        credential_name: str,
        cache_hit: bool,
    ) -> None:
        """Append-only insert a credential_access_log. NO levanta excepciones —
        si el log falla, el read principal no debe romperse."""
        if not self._audit_enabled:
            return
        try:
            self._sb.table("credential_access_log").insert({
                "tenant_id": tenant_id,
                "provider": provider,
                "credential_name": credential_name,
                "accessed_by_service": self._service,
                "cache_hit": cache_hit,
                "request_id": self._request_id,
            }).execute()
        except Exception as e:  # pragma: no cover
            logger.error(
                "[CRED_FACADE] audit log falló (no crítico) tenant=%s "
                "provider=%s field=%s: %s",
                tenant_id, provider, credential_name, e,
            )


# Test/admin helpers
def _global_cache_size() -> int:
    """Helper para tests/healthcheck — devuelve tamaño caché global."""
    return _GLOBAL_CACHE.size()


def _reset_global_cache() -> None:
    """Helper para tests — borra caché global. NO usar en producción."""
    _GLOBAL_CACHE.clear()

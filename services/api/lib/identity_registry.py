"""Tenant provider identity registry — cross-mapping universal (rev. 105 Sem 2 F.12 / MA-10).

Resuelve "¿qué tenant maneja esta entidad externa?" para webhooks inbound y
clientes outbound multi-tenant. Cierra estructuralmente el bug "primer tenant
activo" del Telegram dossier (`telegram_webhook._send_telegram_reply`).

Ejemplos canónicos de identidades por provider:
  - whatsapp:  phone_number_id (WABA business phone identifier)
  - wompi:     merchant_id
  - aveonline: account_id (provider único shipping post-ADR-0019)
  - meli:      user_id (Mercado Libre)
  - telegram:  chat_id (str del operador) o bot_username
  - resend:    verified_domain

UNIQUE(provider, provider_internal_id) en DB garantiza que el mapeo es 1:1
desde la identidad externa hacia un único tenant. Esta lib es el helper
oficial para resolver y registrar identidades.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Set canónico de providers (snake_case). Validar contra esta lista en
# application layer — no constraint enum SQL para facilitar extensión.
SUPPORTED_PROVIDERS = frozenset({
    "whatsapp",
    "wompi",
    "aveonline",
    "meli",
    "telegram",
    "resend",
})


class IdentityRegistryError(Exception):
    """Raise cuando el registry rechaza una operación (provider inválido,
    colisión cross-tenant, etc.)."""


@dataclass(frozen=True)
class ProviderIdentity:
    """Snapshot inmutable de una identidad externa registrada."""
    id: int
    tenant_id: str
    provider: str
    provider_internal_id: str
    metadata: dict[str, Any]
    verified_at: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ProviderIdentity":
        return cls(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            provider=str(row["provider"]),
            provider_internal_id=str(row["provider_internal_id"]),
            metadata=dict(row.get("metadata") or {}),
            verified_at=row.get("verified_at"),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _validate_provider(provider: str) -> str:
    p = provider.strip().lower()
    if p not in SUPPORTED_PROVIDERS:
        raise IdentityRegistryError(
            f"provider inválido: {provider!r}. Soportados: {sorted(SUPPORTED_PROVIDERS)}"
        )
    return p


def _normalize_internal_id(value: Any) -> str:
    """Provider internal_id se almacena siempre como str. Acepta int, UUID, etc."""
    if value is None:
        raise IdentityRegistryError("provider_internal_id no puede ser None")
    s = str(value).strip()
    if not s:
        raise IdentityRegistryError("provider_internal_id no puede ser vacío")
    return s


def resolve_tenant_id(
    supabase_client: Any,
    provider: str,
    provider_internal_id: Any,
) -> Optional[str]:
    """Devuelve el tenant_id propietario de una identidad externa, o None
    si no existe. NO levanta excepción cuando no encuentra — el caller
    decide cómo manejar identidades desconocidas (auto-register, reject,
    fallback al "primer activo" legacy, etc.).

    Uso típico (webhook inbound):
        tenant_id = resolve_tenant_id(client, "telegram", chat_id)
        if not tenant_id:
            logger.warning("[TG_WH] chat_id %s sin tenant registrado", chat_id)
            return  # rechazar o caer a flujo legacy
    """
    p = _validate_provider(provider)
    iid = _normalize_internal_id(provider_internal_id)
    res = (
        supabase_client.table("tenant_provider_identity")
        .select("tenant_id")
        .eq("provider", p)
        .eq("provider_internal_id", iid)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return str(rows[0]["tenant_id"]) if rows else None


def get_identity(
    supabase_client: Any,
    provider: str,
    provider_internal_id: Any,
) -> Optional[ProviderIdentity]:
    """Versión completa de resolve_tenant_id que devuelve la fila completa."""
    p = _validate_provider(provider)
    iid = _normalize_internal_id(provider_internal_id)
    res = (
        supabase_client.table("tenant_provider_identity")
        .select("*")
        .eq("provider", p)
        .eq("provider_internal_id", iid)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return ProviderIdentity.from_row(rows[0]) if rows else None


def list_identities_for_tenant(
    supabase_client: Any,
    tenant_id: str,
    provider: Optional[str] = None,
) -> list[ProviderIdentity]:
    """Devuelve todas las identidades registradas para un tenant. Opcional
    filtro por provider."""
    query = (
        supabase_client.table("tenant_provider_identity")
        .select("*")
        .eq("tenant_id", tenant_id)
    )
    if provider:
        query = query.eq("provider", _validate_provider(provider))
    res = query.execute()
    return [ProviderIdentity.from_row(r) for r in (res.data or [])]


def register_identity(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
    provider_internal_id: Any,
    metadata: Optional[dict[str, Any]] = None,
    mark_verified: bool = False,
) -> ProviderIdentity:
    """Registra una nueva identidad. Falla si ya existe (provider, internal_id)
    asignado a OTRO tenant — esto es la defensa central contra cross-talk.

    Si la identidad ya existe asignada al MISMO tenant, actualiza metadata
    + verified_at y retorna la fila existente (idempotente para re-registros).

    Nota: usa service_role (asume supabase_client ya tiene esos privilegios)
    porque los webhooks inbound no tienen tenant context al momento de
    registrar identidades.
    """
    p = _validate_provider(provider)
    iid = _normalize_internal_id(provider_internal_id)
    md = dict(metadata or {})

    # Check colisión cross-tenant antes de insertar.
    existing = get_identity(supabase_client, p, iid)
    if existing is not None:
        if existing.tenant_id != tenant_id:
            raise IdentityRegistryError(
                f"Cross-tenant identity collision: ({p}, {iid}) ya asignado al "
                f"tenant {existing.tenant_id}, no puede reasignarse a {tenant_id}. "
                f"Use revoke_identity primero si la transferencia es intencional."
            )
        # Mismo tenant: actualizar metadata + verified_at (idempotente).
        update_payload: dict[str, Any] = {"metadata": md}
        if mark_verified:
            update_payload["verified_at"] = "now()"
        res = (
            supabase_client.table("tenant_provider_identity")
            .update(update_payload)
            .eq("id", existing.id)
            .execute()
        )
        rows = res.data or []
        return ProviderIdentity.from_row(rows[0]) if rows else existing

    # Insert nueva identidad. La UNIQUE constraint en DB hace doble-check
    # contra race conditions entre el check anterior y este insert.
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "provider": p,
        "provider_internal_id": iid,
        "metadata": md,
    }
    if mark_verified:
        payload["verified_at"] = "now()"
    res = supabase_client.table("tenant_provider_identity").insert(payload).execute()
    rows = res.data or []
    if not rows:
        raise IdentityRegistryError(
            f"Insert vacío al registrar ({p}, {iid}) → tenant {tenant_id}"
        )
    return ProviderIdentity.from_row(rows[0])


def revoke_identity(
    supabase_client: Any,
    provider: str,
    provider_internal_id: Any,
) -> bool:
    """Borra una identidad (offboarding tenant, transferencia provider, etc.).
    Retorna True si había fila, False si no existía."""
    p = _validate_provider(provider)
    iid = _normalize_internal_id(provider_internal_id)
    res = (
        supabase_client.table("tenant_provider_identity")
        .delete()
        .eq("provider", p)
        .eq("provider_internal_id", iid)
        .execute()
    )
    return bool(res.data)

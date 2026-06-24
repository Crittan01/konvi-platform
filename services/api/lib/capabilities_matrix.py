"""Capabilities matrix per-tenant per-provider (rev. 105 Sem 2 F.3).

Wrappea consultas a `tenant_provider_capabilities` table. Es el helper que
clientes outbound + orchestrator usan ANTES de invocar una feature, para
saber si está habilitada para ese tenant.

Ejemplos de uso:

    from lib.capabilities_matrix import is_capability_enabled, get_capability_config

    # Antes de generar etiqueta Aveonline
    if is_capability_enabled(client, tenant_id, "aveonline", "label_generation"):
        ...

    # Antes de enviar HSM template
    if is_capability_enabled(client, tenant_id, "meta", "hsm_templates"):
        cfg = get_capability_config(client, tenant_id, "meta", "hsm_templates")
        approved = cfg.get("approved", [])
        ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Catálogo canónico de capabilities por provider. Application layer valida
# `capability` contra este dict antes de set/get para evitar typos silentes.
CAPABILITIES_BY_PROVIDER: dict[str, frozenset[str]] = {
    "wompi": frozenset({
        "payment_method_card",
        "payment_method_pse",
        "payment_method_nequi",
        "payment_method_bancolombia",
        "payment_method_daviplata",
        "tokenized_cards",
        "refund",
    }),
    "meta": frozenset({
        "hsm_templates",
        "tier_unlimited",
        "interactive_messages",
        "document_outbound",
        "location_outbound",
        "commerce_catalog",
        "free_entry_point",
    }),
    "meli": frozenset({
        "qna_reply",
        "messages_postsale",
        "order_ack",
        "cbt_compliant",
        "ads",
        "promotions",
    }),
    "telegram": frozenset({
        "multi_bot_per_tenant",
        "inline_keyboards",
        "callback_query",
        "operator_commands_advanced",
    }),
    "resend": frozenset({
        "custom_domain",
        "webhooks_delivery",
        "list_unsubscribe",
    }),
    "aveonline": frozenset({
        "label_generation",
        "pickup",
        "cancel",
        "tracking_webhook",
        "cod_native",
    }),
}


class CapabilityError(Exception):
    """Operación rechazada (provider/capability inválido)."""


@dataclass(frozen=True)
class CapabilityRecord:
    """Snapshot inmutable de una fila tenant_provider_capabilities."""
    id: int
    tenant_id: str
    provider: str
    capability: str
    enabled: bool
    config: dict[str, Any]
    notes: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "CapabilityRecord":
        return cls(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            provider=str(row["provider"]),
            capability=str(row["capability"]),
            enabled=bool(row["enabled"]),
            config=dict(row.get("config") or {}),
            notes=row.get("notes"),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _validate(provider: str, capability: str) -> tuple[str, str]:
    p = provider.strip().lower()
    c = capability.strip().lower()
    if p not in CAPABILITIES_BY_PROVIDER:
        raise CapabilityError(
            f"provider inválido: {provider!r}. "
            f"Soportados: {sorted(CAPABILITIES_BY_PROVIDER)}"
        )
    if c not in CAPABILITIES_BY_PROVIDER[p]:
        raise CapabilityError(
            f"capability {c!r} inválida para provider {p!r}. "
            f"Soportadas: {sorted(CAPABILITIES_BY_PROVIDER[p])}"
        )
    return p, c


def is_capability_enabled(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
    capability: str,
    default: bool = False,
) -> bool:
    """Retorna True si capability está enabled=true para tenant. Si la fila
    no existe, retorna `default` (default False — capabilities son opt-in
    explícito, NO opt-out)."""
    p, c = _validate(provider, capability)
    res = (
        supabase_client.table("tenant_provider_capabilities")
        .select("enabled")
        .eq("tenant_id", tenant_id)
        .eq("provider", p)
        .eq("capability", c)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return default
    return bool(rows[0]["enabled"])


def get_capability_config(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
    capability: str,
) -> dict[str, Any]:
    """Retorna config JSONB de una capability. Dict vacío si no existe o
    está deshabilitada (caller debe usar is_capability_enabled antes para
    distinguir 'no existe' vs 'disabled con config histórica')."""
    p, c = _validate(provider, capability)
    res = (
        supabase_client.table("tenant_provider_capabilities")
        .select("config, enabled")
        .eq("tenant_id", tenant_id)
        .eq("provider", p)
        .eq("capability", c)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows or not rows[0].get("enabled"):
        return {}
    return dict(rows[0].get("config") or {})


def get_record(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
    capability: str,
) -> Optional[CapabilityRecord]:
    """Versión completa: retorna fila completa (incluido enabled=False y
    notes). Útil para UI Settings que muestra estado."""
    p, c = _validate(provider, capability)
    res = (
        supabase_client.table("tenant_provider_capabilities")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("provider", p)
        .eq("capability", c)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return CapabilityRecord.from_row(rows[0]) if rows else None


def list_capabilities_for_tenant(
    supabase_client: Any,
    tenant_id: str,
    provider: Optional[str] = None,
) -> list[CapabilityRecord]:
    """Lista todas las capabilities de un tenant (opcional filtro por provider).
    Útil para UI Settings → Integraciones → Capabilities tab."""
    query = (
        supabase_client.table("tenant_provider_capabilities")
        .select("*")
        .eq("tenant_id", tenant_id)
    )
    if provider is not None:
        if provider not in CAPABILITIES_BY_PROVIDER:
            raise CapabilityError(
                f"provider inválido: {provider!r}"
            )
        query = query.eq("provider", provider)
    res = query.execute()
    return [CapabilityRecord.from_row(r) for r in (res.data or [])]


def upsert_capability(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
    capability: str,
    enabled: bool,
    config: Optional[dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> CapabilityRecord:
    """Crea o actualiza una capability. Idempotente (UNIQUE constraint en DB)."""
    p, c = _validate(provider, capability)
    existing = get_record(supabase_client, tenant_id, p, c)
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "provider": p,
        "capability": c,
        "enabled": enabled,
        "config": dict(config or {}),
        "notes": notes,
    }
    if existing is None:
        res = (
            supabase_client.table("tenant_provider_capabilities")  # tenant_filter:exempt:payload_includes_tenant_id
            .insert(payload)
            .execute()
        )
    else:
        res = (
            supabase_client.table("tenant_provider_capabilities")  # tenant_filter:exempt:payload_includes_tenant_id
            .update(payload)
            .eq("id", existing.id)
            .execute()
        )
    rows = res.data or []
    if not rows:
        raise CapabilityError(
            f"upsert vacío para ({tenant_id}, {p}, {c})"
        )
    return CapabilityRecord.from_row(rows[0])

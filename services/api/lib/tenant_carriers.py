"""Tenant carriers preferences helper — Sem 5 H.2.7 (rev. 105).

Wrappea consultas a `tenant_carriers` table. La tabla permite a cada
tenant elegir qué carriers (de los disponibles globalmente vía Queries
API) ofrecer en cotización.

Política default: si el tenant NO tiene NINGUNA fila en
`tenant_carriers` para `provider`, asumimos "todos enabled" (backward
compat con tenants pre-rev105). Si tiene ≥1 fila, solo los `enabled=true`
aparecen.

Uso típico desde `routers/shipping.py:_resolve_carriers_for_quote`:

    from lib.tenant_carriers import filter_enabled_carriers

    dynamic = await client.get_available_carriers(...)
    carriers = filter_enabled_carriers(
        supabase, tenant_id, "envia", dynamic_carrier_codes,
    )
    # → solo carriers que el tenant tiene enabled (o todos si no
    #   configuró preferencias).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


VALID_PROVIDERS = frozenset({"envia"})


@dataclass(frozen=True)
class CarrierPreference:
    """Snapshot de una fila tenant_carriers.

    Nota rev. 2026-05-08: `supports_insurance` removido (col dropeada).
    Insurance es decisión del carrier (no opt-in del tenant) — ver
    `services/api/lib/insurance.py:apply_insurance_to_packages`.
    """
    carrier_code: str
    enabled: bool
    display_label: Optional[str]
    priority: int
    notes: Optional[str]


def _validate_provider(provider: str) -> str:
    p = provider.strip().lower()
    if p not in VALID_PROVIDERS:
        raise ValueError(
            f"Provider inválido: {provider!r}. Soportados: {sorted(VALID_PROVIDERS)}"
        )
    return p


def list_preferences(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
) -> list[CarrierPreference]:
    """Retorna todas las preferencias del tenant para el provider,
    ordenadas por priority asc.

    Lista vacía si el tenant no tiene preferencias configuradas — caller
    interpreta como "default open" (todos enabled)."""
    p = _validate_provider(provider)
    res = (
        supabase_client.table("tenant_carriers")
        .select("carrier_code, enabled, display_label, priority, notes")
        .eq("tenant_id", tenant_id)
        .eq("provider", p)
        .order("priority", desc=False)
        .order("carrier_code", desc=False)
        .execute()
    )
    rows = res.data or []
    return [
        CarrierPreference(
            carrier_code=r.get("carrier_code") or "",
            enabled=bool(r.get("enabled", False)),
            display_label=r.get("display_label"),
            priority=int(r.get("priority") or 100),
            notes=r.get("notes"),
        )
        for r in rows
    ]


def filter_enabled_carriers(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
    candidates: list[str],
) -> list[str]:
    """Filtra `candidates` (carriers disponibles globalmente vía API
    Envia/Queries) por los que el tenant tiene `enabled=true`.

    Política backward-compat:
      - Tenant sin preferencias (lista_preferencias vacía) → retorna
        `candidates` tal cual (todos enabled by default).
      - Tenant con preferencias → retorna SOLO los candidates cuyo
        carrier_code matchee (case-insensitive) con un row enabled=true.
        Preserva orden de `candidates` original.

    Comparación case-insensitive porque Envia mezcla camelCase
    (`interRapidisimo`, `mensajerosUrbanos`) y snake_case en distintos
    endpoints.
    """
    if not candidates:
        return []
    prefs = list_preferences(supabase_client, tenant_id, provider)
    if not prefs:
        # Default open: tenant sin configuración → todos.
        return list(candidates)

    enabled_lower: set[str] = {
        p.carrier_code.lower() for p in prefs if p.enabled
    }
    if not enabled_lower:
        # Tenant configuró pero deshabilitó todos → ofrecer 0 carriers.
        # Esto NO es default — es una decisión explícita del tenant.
        # Caller (quote endpoint) debe alertar (no devolver 502 con
        # mensaje genérico de "Envia no responde", sino un 400 claro).
        logger.warning(
            "[CARRIERS] tenant=%s provider=%s tiene preferencias pero NINGUNO enabled. "
            "Cotización devolverá 0 tarifas.",
            tenant_id, provider,
        )
        return []

    return [c for c in candidates if c.lower() in enabled_lower]


def upsert_preference(
    supabase_client: Any,
    tenant_id: str,
    provider: str,
    carrier_code: str,
    *,
    enabled: bool = True,
    display_label: Optional[str] = None,
    priority: int = 100,
    notes: Optional[str] = None,
) -> CarrierPreference:
    """Upsert (idempotente vía UNIQUE constraint). Usado por endpoint
    admin POST /api/v1/integrations/envia/carriers."""
    p = _validate_provider(provider)
    code = (carrier_code or "").strip()
    if not code:
        raise ValueError("carrier_code requerido.")

    payload = {
        "tenant_id": tenant_id,
        "provider": p,
        "carrier_code": code,
        "enabled": enabled,
        "display_label": display_label,
        "priority": int(priority),
        "notes": notes,
    }
    res = (
        supabase_client.table("tenant_carriers")
        .upsert(payload, on_conflict="tenant_id,provider,carrier_code")
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise RuntimeError("Upsert no retornó row")
    r = rows[0]
    return CarrierPreference(
        carrier_code=r.get("carrier_code") or "",
        enabled=bool(r.get("enabled", False)),
        display_label=r.get("display_label"),
        priority=int(r.get("priority") or 100),
        notes=r.get("notes"),
    )

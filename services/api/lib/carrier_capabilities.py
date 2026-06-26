"""Servicio de lookup de capacidades efectivas por carrier (rev. 108 holístico).

Capa de abstracción única que combina:
  1. `aveonline_carrier_capabilities` (canonical platform-level)
  2. `tenant_carriers` (per-tenant: enabled + cod_override + display_label)

Returns una vista efectiva por carrier que el resto del sistema usa:
  • bot prompt builder
  • shipping_quote_tool (filter pre-quote)
  • UI Settings tab Carriers
  • payment_link_tool (warning devolución en resumen)

Diseño:
  • TTL cache 5min per (tenant_id, carrier_name) para evitar N queries
    durante una conversación.
  • Lookup robusto: si carrier_name no está en canonical, retorna
    "unknown" capability (NO bloquea — el LLM aún puede ofrecerlo,
    sólo no tiene info de COD/devolución).
  • Función pure: NO side effects, NO writes.

NO machetazos: este módulo NO tiene business logic distinta de combinar
fuentes. Toda regla (mínimos, max peso, etc.) vive en el canonical seed.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

# In-memory TTL cache (per-process).
# Rev. 108 modular tuning (founder 2026-05-27 Opción A): TTL 30s en lugar
# de 5min. Coherente con tenant_payment_methods — tenant cambia overrides
# de carriers (cod_override per-carrier) y debe ver efecto rápido. Trade-off
# performance ~50ms × turn vs UX inmediato. Si crece demanda escalar a
# Postgres LISTEN/NOTIFY.
_CACHE: dict[tuple, tuple[float, "CarrierCapability"]] = {}
_TTL_SECONDS = 30


@dataclass(frozen=True)
class CarrierCapability:
    """Vista efectiva de las capacidades de un carrier para un tenant."""

    carrier_name: str
    carrier_id: Optional[str]

    # COD effective (canonical + override resolution).
    supports_cod: bool
    cod_min_recaudo_cop: Optional[int]
    cod_min_recaudo_heavy_cop: Optional[int]
    cod_weight_threshold_kg: Optional[float]
    cod_commission_pct: Optional[float]
    cod_liquidation_days_range: Optional[str]
    cod_liquidation_weekday: Optional[str]

    # Risk indicator.
    charges_return_fee: bool

    # Package constraints.
    max_weight_kg: Optional[float]
    max_dim_cm: Optional[int]
    valor_declarado_min_cop: int
    valor_declarado_max_cop: Optional[int]

    # Tenant-specific.
    enabled_for_tenant: bool
    display_label: Optional[str]
    cod_override: Optional[str]   # 'force_enable' | 'force_disable' | None

    # Provenance.
    fuente_doc_url: Optional[str]
    notes: Optional[str]

    # Composite signals derived for downstream consumers.
    @property
    def effective_min_recaudo_cop(self) -> Optional[int]:
        """Mínimo de recaudo aplicable. NULL si carrier no soporta COD."""
        return self.cod_min_recaudo_cop if self.supports_cod else None

    def min_recaudo_for_weight(self, weight_kg: float) -> Optional[int]:
        """Mínimo de recaudo según peso (Interrapidisimo varía por threshold)."""
        if not self.supports_cod:
            return None
        if (
            self.cod_weight_threshold_kg is not None
            and self.cod_min_recaudo_heavy_cop is not None
            and weight_kg > self.cod_weight_threshold_kg
        ):
            return self.cod_min_recaudo_heavy_cop
        return self.cod_min_recaudo_cop

    def as_dict(self) -> dict:
        return asdict(self)


def _normalize_name(name: str) -> str:
    """UPPERCASE + collapse espacios para match con canonical PK."""
    return " ".join((name or "").upper().split())


def _resolve_cod(
    canonical_supports_cod: bool,
    cod_override: Optional[str],
    tenant_cod_globally_enabled: bool = True,
) -> bool:
    """Resuelve `supports_cod` efectivo.

    Precedencia:
      1. Si tenant globalmente DISABLED COD (tenant_payment_methods.cod
         enabled=false) → SIEMPRE false (gate tenant-level).
      2. Si cod_override='force_enable' → true.
      3. Si cod_override='force_disable' → false.
      4. Fallback: canonical_supports_cod.

    El gate tenant-level (#1) es el switch maestro modular: tenant que
    NO quiere COD apaga 1 vez, todos los carriers quedan ✗COD sin tocar
    overrides per-carrier.
    """
    if not tenant_cod_globally_enabled:
        return False
    if cod_override == "force_enable":
        return True
    if cod_override == "force_disable":
        return False
    return canonical_supports_cod


def get_effective_carrier_capability(
    supabase: Any,
    *,
    tenant_id: str,
    carrier_name: str,
) -> CarrierCapability:
    """Lookup efectivo combinando canonical + tenant overrides.

    Cache TTL 5min per (tenant_id, carrier_name).

    Si carrier_name no está en canonical, retorna CarrierCapability
    con valores neutros (supports_cod=False, todos los mins NULL,
    notes='unknown carrier — sin información en canonical').
    """
    name_normalized = _normalize_name(carrier_name)
    cache_key = (tenant_id, name_normalized)
    now = time.time()

    cached = _CACHE.get(cache_key)
    if cached and (now - cached[0]) < _TTL_SECONDS:
        return cached[1]

    # 1. Canonical lookup (platform-level).
    try:
        cap_q = (
            supabase.table("aveonline_carrier_capabilities")
            .select("*")
            .eq("carrier_name", name_normalized)
            .maybe_single()
            .execute()
        )
        canonical = cap_q.data if cap_q else None
    except Exception:
        canonical = None

    # 2. Per-tenant override lookup.
    try:
        tc_q = (
            supabase.table("tenant_carriers")
            .select("enabled, display_label, cod_override")
            .eq("tenant_id", tenant_id)
            .eq("provider", "aveonline")
            .ilike("carrier_code", name_normalized.lower())
            .maybe_single()
            .execute()
        )
        tenant_row = tc_q.data if tc_q else None
    except Exception:
        tenant_row = None

    # 2.5. Tenant-level COD gate (rev. 108 modular).
    # Si el tenant globalmente NO tiene 'cod' habilitado en
    # tenant_payment_methods, supports_cod efectivo será SIEMPRE false
    # para cualquier carrier — un solo switch tenant-wide.
    try:
        from lib.tenant_payment_methods import is_method_enabled
        tenant_cod_globally_enabled = is_method_enabled(
            supabase, tenant_id=tenant_id, method="cod",
        )
    except Exception:
        tenant_cod_globally_enabled = True  # fail-open

    # 3. Compose effective view.
    if canonical:
        cap = CarrierCapability(
            carrier_name=name_normalized,
            carrier_id=canonical.get("carrier_id"),
            supports_cod=_resolve_cod(
                bool(canonical.get("supports_cod", False)),
                (tenant_row or {}).get("cod_override"),
                tenant_cod_globally_enabled,
            ),
            cod_min_recaudo_cop=canonical.get("cod_min_recaudo_cop"),
            cod_min_recaudo_heavy_cop=canonical.get("cod_min_recaudo_heavy_cop"),
            cod_weight_threshold_kg=(
                float(canonical["cod_weight_threshold_kg"])
                if canonical.get("cod_weight_threshold_kg") is not None
                else None
            ),
            cod_commission_pct=(
                float(canonical["cod_commission_pct"])
                if canonical.get("cod_commission_pct") is not None
                else None
            ),
            cod_liquidation_days_range=canonical.get("cod_liquidation_days_range"),
            cod_liquidation_weekday=canonical.get("cod_liquidation_weekday"),
            charges_return_fee=bool(canonical.get("charges_return_fee", False)),
            max_weight_kg=(
                float(canonical["max_weight_kg"])
                if canonical.get("max_weight_kg") is not None
                else None
            ),
            max_dim_cm=canonical.get("max_dim_cm"),
            valor_declarado_min_cop=int(canonical.get("valor_declarado_min_cop") or 10000),
            valor_declarado_max_cop=canonical.get("valor_declarado_max_cop"),
            enabled_for_tenant=bool((tenant_row or {}).get("enabled", True)),
            display_label=(tenant_row or {}).get("display_label"),
            cod_override=(tenant_row or {}).get("cod_override"),
            fuente_doc_url=canonical.get("fuente_doc_url"),
            notes=canonical.get("notes"),
        )
    else:
        # Unknown carrier — capability vacía pero no bloqueante.
        cap = CarrierCapability(
            carrier_name=name_normalized,
            carrier_id=None,
            supports_cod=False,
            cod_min_recaudo_cop=None,
            cod_min_recaudo_heavy_cop=None,
            cod_weight_threshold_kg=None,
            cod_commission_pct=None,
            cod_liquidation_days_range=None,
            cod_liquidation_weekday=None,
            charges_return_fee=False,
            max_weight_kg=None,
            max_dim_cm=None,
            valor_declarado_min_cop=10000,
            valor_declarado_max_cop=None,
            enabled_for_tenant=bool((tenant_row or {}).get("enabled", True)),
            display_label=(tenant_row or {}).get("display_label"),
            cod_override=(tenant_row or {}).get("cod_override"),
            fuente_doc_url=None,
            notes=f"unknown carrier '{name_normalized}' — sin información en canonical",
        )

    _CACHE[cache_key] = (now, cap)
    return cap


def get_all_capabilities_for_tenant(
    supabase: Any,
    *,
    tenant_id: str,
) -> list[CarrierCapability]:
    """Retorna capacidades efectivas de TODOS los carriers conocidos.

    Útil para UI Settings tab Carriers + bot prompt block.
    Lista ordenada por: supports_cod desc, carrier_name asc.
    """
    try:
        cap_q = (
            supabase.table("aveonline_carrier_capabilities")
            .select("carrier_name")
            .execute()
        )
        names = [row["carrier_name"] for row in (cap_q.data or [])]
    except Exception:
        names = []

    caps = [
        get_effective_carrier_capability(
            supabase, tenant_id=tenant_id, carrier_name=n,
        )
        for n in names
    ]
    caps.sort(key=lambda c: (not c.supports_cod, c.carrier_name))
    return caps


def invalidate_cache(tenant_id: Optional[str] = None) -> None:
    """Invalida cache. Llamar tras cambios en tenant_carriers o
    aveonline_carrier_capabilities."""
    if tenant_id is None:
        _CACHE.clear()
    else:
        for k in list(_CACHE.keys()):
            if k[0] == tenant_id:
                del _CACHE[k]

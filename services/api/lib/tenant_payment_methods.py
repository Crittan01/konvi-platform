"""Servicio de lookup de métodos de pago habilitados per-tenant (rev. 108).

Capa de abstracción única que consulta `tenant_payment_methods` table
y combina con:
  • Default backward-compat: si tenant NO tiene filas → todos enabled
    (fallback open consistente con `tenant_carriers`).

Consumidores:
  • `lib.carrier_capabilities` → short-circuit cod si method='cod' disabled
  • `agentic.invariants.payment_method_explicit` → adapta pregunta
  • `agentic.payment_method_availability_resolver` (pre-LLM) → short-circuit
  • `agentic.system_prompt` → bloque [MÉTODOS DE PAGO] dinámico
  • UI Settings → Pagos (CRUD)

Diseño:
  • TTL cache 5min per tenant_id.
  • Modular: cualquier `method` futuro funciona sin cambiar la API
    (se agrega via migration extendiendo CHECK constraint).
  • Función pura — NO side effects, NO writes.

Símil de `tenant_carriers.py` legacy (mismo patrón fallback-open).

NO machetazos — solo lookup + cache. Toda business logic vive en
consumidores específicos (cada uno aplica reglas según su contexto).
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

# In-memory TTL cache (per-process).
# Rev. 108 modular tuning (founder 2026-05-27 Opción A): TTL 30s en lugar
# de 5min. Trade-off: ~50ms extra DB query per turn cuando cache expira,
# pero tenant ve cambios reflejados en ≤30s (en lugar de hasta 5min).
# Aceptable para producción: tenant raramente cambia config; cuando
# cambia, espera ≤30s. Si demanda crece, escalar a Postgres LISTEN/NOTIFY.
_CACHE: dict[str, tuple[float, "TenantPaymentMethodsConfig"]] = {}
_TTL_SECONDS = 30


# Métodos canónicos conocidos (matchean CHECK constraint del DB).
KNOWN_METHODS = ("cod", "online_wompi")

# Labels por defecto en español Colombia (fallback si tenant no override).
DEFAULT_LABELS = {
    "cod": "Contraentrega",
    "online_wompi": "Pago online (tarjeta, PSE, Nequi)",
}


@dataclass(frozen=True)
class PaymentMethodConfig:
    method: str
    enabled: bool
    display_label: str
    config: dict
    notes: Optional[str]


@dataclass(frozen=True)
class TenantPaymentMethodsConfig:
    tenant_id: str
    methods: tuple[PaymentMethodConfig, ...]
    # Si tenant NO tenía filas en DB y caímos al fallback-open.
    fallback_open: bool

    def enabled_methods(self) -> list[str]:
        return [m.method for m in self.methods if m.enabled]

    def is_enabled(self, method: str) -> bool:
        for m in self.methods:
            if m.method == method:
                return m.enabled
        # Method desconocido → no enabled (defensive).
        return False

    def get(self, method: str) -> Optional[PaymentMethodConfig]:
        for m in self.methods:
            if m.method == method:
                return m
        return None

    def label_for(self, method: str) -> str:
        m = self.get(method)
        if m and m.display_label:
            return m.display_label
        return DEFAULT_LABELS.get(method, method)

    def as_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "fallback_open": self.fallback_open,
            "methods": [asdict(m) for m in self.methods],
        }


def get_tenant_payment_methods(
    supabase: Any,
    *,
    tenant_id: str,
) -> TenantPaymentMethodsConfig:
    """Lookup config completa de métodos de pago para el tenant.

    Backward-compat (rev. 108): si NO hay filas en tenant_payment_methods
    para este tenant, retorna fallback_open=True + todos los KNOWN_METHODS
    con enabled=true. Eso preserva comportamiento legacy mientras la
    feature se rollout per-tenant via Settings UI.

    Returns:
        TenantPaymentMethodsConfig con .is_enabled('cod'), .enabled_methods(),
        .label_for('cod'), etc.
    """
    now = time.time()
    cached = _CACHE.get(tenant_id)
    if cached and (now - cached[0]) < _TTL_SECONDS:
        return cached[1]

    rows: list[dict] = []
    try:
        q = (
            supabase.table("tenant_payment_methods")
            .select("method, enabled, display_label, config_json, notes")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        rows = q.data or []
    except Exception:
        rows = []

    if not rows:
        # Fallback open: todos los KNOWN_METHODS enabled.
        cfg = TenantPaymentMethodsConfig(
            tenant_id=tenant_id,
            methods=tuple(
                PaymentMethodConfig(
                    method=m,
                    enabled=True,
                    display_label=DEFAULT_LABELS.get(m, m),
                    config={},
                    notes="fallback: tenant sin configuración explícita",
                )
                for m in KNOWN_METHODS
            ),
            fallback_open=True,
        )
    else:
        seen = set()
        methods = []
        for row in rows:
            method = (row.get("method") or "").lower()
            if not method or method in seen:
                continue
            seen.add(method)
            methods.append(PaymentMethodConfig(
                method=method,
                enabled=bool(row.get("enabled", True)),
                display_label=(
                    row.get("display_label")
                    or DEFAULT_LABELS.get(method, method)
                ),
                config=row.get("config_json") or {},
                notes=row.get("notes"),
            ))
        # Completar con KNOWN_METHODS faltantes en enabled=true (defensive).
        for m in KNOWN_METHODS:
            if m not in seen:
                methods.append(PaymentMethodConfig(
                    method=m,
                    enabled=True,
                    display_label=DEFAULT_LABELS.get(m, m),
                    config={},
                    notes="default enabled (no row in tenant_payment_methods)",
                ))
        cfg = TenantPaymentMethodsConfig(
            tenant_id=tenant_id,
            methods=tuple(methods),
            fallback_open=False,
        )

    _CACHE[tenant_id] = (now, cfg)
    return cfg


def is_method_enabled(
    supabase: Any,
    *,
    tenant_id: str,
    method: str,
) -> bool:
    """Conveniencia: shortcut booleano per (tenant, method)."""
    return get_tenant_payment_methods(
        supabase, tenant_id=tenant_id,
    ).is_enabled(method)


def list_enabled_methods(
    supabase: Any,
    *,
    tenant_id: str,
) -> list[str]:
    """Conveniencia: lista de métodos enabled para el tenant."""
    return get_tenant_payment_methods(
        supabase, tenant_id=tenant_id,
    ).enabled_methods()


def invalidate_cache(tenant_id: Optional[str] = None) -> None:
    """Invalida cache. Llamar tras CRUD en tenant_payment_methods."""
    if tenant_id is None:
        _CACHE.clear()
    elif tenant_id in _CACHE:
        del _CACHE[tenant_id]

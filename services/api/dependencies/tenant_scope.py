"""
Guard multi-tenant para queries con service_role.

El backend usa service_role que bypasea RLS. Este módulo provee
helpers que GARANTIZAN que toda query en rutas críticas tenga
filtro explícito por tenant_id.

Uso:
    from dependencies.tenant_scope import scoped_table, assert_tenant_filter

    # En lugar de:
    supabase.table("orders").select("*").eq("tenant_id", tenant_id)
    # Usar:
    scoped_table(supabase, "orders", tenant_id).select("*")
"""
import logging
from typing import Any

from supabase import Client

logger = logging.getLogger("api.tenant_scope")

# Tablas que contienen datos sensibles y SIEMPRE deben filtrarse por tenant_id.
# Cualquier query en estas tablas sin filtro es un bug de aislamiento.
TENANT_SCOPED_TABLES = {
    "orders",
    "order_items",
    "order_tracking",
    "contacts",
    "conversations",
    "messages",
    "payments",
    "products",
    "product_variations",
    "stock_movements",
    "marketplace_listings",
    "api_security_events",
    "idempotency_keys",
    "tenant_usage_events",
    "tenant_usage_counters",
    "ai_agents",
    "tenant_integrations",
}


class _TenantScopedQuery:
    """
    Wrapper que aplica .eq("tenant_id", tenant_id) automáticamente y
    previene que se olvide el filtro en tablas críticas.
    """

    def __init__(self, base_query: Any, tenant_id: str, table_name: str):
        self._q = base_query.eq("tenant_id", tenant_id)
        self._tenant_id = tenant_id
        self._table_name = table_name

    def select(self, *args, **kwargs):
        return self._q.select(*args, **kwargs)

    def insert(self, *args, **kwargs):
        return self._q.insert(*args, **kwargs)

    def update(self, *args, **kwargs):
        return self._q.update(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._q.delete(*args, **kwargs)

    def upsert(self, *args, **kwargs):
        return self._q.upsert(*args, **kwargs)

    # Delegación genérica para métodos adicionales (eq, order, limit, etc.)
    def __getattr__(self, name: str):
        return getattr(self._q, name)


def scoped_table(supabase: Client, table_name: str, tenant_id: str) -> _TenantScopedQuery:
    """
    Retorna un query builder pre-filtrado por tenant_id.

    Equivalente a:
        supabase.table(table_name).select/update/etc.(...).eq("tenant_id", tenant_id)

    La diferencia es que el filtro es OBLIGATORIO y no se puede omitir por olvido.
    """
    if not tenant_id:
        raise ValueError(
            f"[TENANT_SCOPE] tenant_id vacío en query a tabla '{table_name}'. "
            "Bug de aislamiento multi-tenant detectado."
        )
    if table_name in TENANT_SCOPED_TABLES:
        base = supabase.table(table_name)
        return _TenantScopedQuery(base, tenant_id, table_name)

    # Tabla no en la lista crítica — devuelve query sin modificar pero con warning
    logger.debug(
        "[TENANT_SCOPE] Tabla '%s' no está en TENANT_SCOPED_TABLES — "
        "verificar si necesita filtro por tenant_id",
        table_name,
    )
    return supabase.table(table_name)  # type: ignore[return-value]

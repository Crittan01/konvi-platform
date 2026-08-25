"""Contrato declarado del dominio pedidos (D2; domain-services-contract.md §4.1).

Fuente que M3 leerá para generar las tools del bot y la Platform Console para
descubrir capacidades. `implemented=True` solo cuando el `service_fn` es el
camino real de producción (los adaptadores se migran por fases M2.1→M2.4).
"""
from __future__ import annotations

from konvi_domain.contract import DomainContract, Operation

ORDERS_CONTRACT = DomainContract(
    domain="orders",
    operations=(
        Operation(
            name="orders.create",
            description=(
                "Crea un pedido con ítems recomputando el total en servidor "
                "(subtotal − cupón vivo del cart + envío), con validación de "
                "FKs del tenant, adopt-winner anti doble-cobro y estados "
                "iniciales por modalidad (credit/cod)."
            ),
            service_fn="create_order",
            rbac={
                "console": ("owner", "manager", "operator"),
                "bot": ("customer",),       # vía REST dual-auth hoy; in-process en M3
                "worker": ("system",),
            },
            audience=("customer", "operator"),
            idempotency="explicit_key",     # Idempotency-Key + unique_natural (índice parcial)
            events=("order.created", "order.adopted_existing"),
            errors=("VALIDATION", "NOT_FOUND", "CONFLICT", "UPSTREAM"),
            customer_facing=True,
            implemented=True,
        ),
        Operation(
            name="orders.get",
            description="Detalle de un pedido con ítems y contacto.",
            service_fn="get_order",
            rbac={"console": ("owner", "manager", "operator"), "bot": ("customer",)},
            audience=("customer", "operator"),
            idempotency="read_only",
            events=(),
            errors=("NOT_FOUND",),
            customer_facing=True,
            implemented=True,
        ),
        Operation(
            name="orders.list",
            description=(
                "Listado paginado de pedidos del tenant con filtros "
                "(estado/contacto/búsqueda) y conteos por estado."
            ),
            service_fn="list_orders",
            rbac={"console": ("owner", "manager", "operator")},
            audience=("operator", "owner"),
            idempotency="read_only",
            events=(),
            errors=("VALIDATION",),
            customer_facing=False,
            implemented=True,
        ),
        Operation(
            name="orders.list_by_contact",
            description=(
                "Historial reciente de pedidos de un contacto (cliente actual "
                "del bot, o ficha del contacto en consola)."
            ),
            service_fn="list_orders_by_contact",
            rbac={"console": ("owner", "manager", "operator"), "bot": ("customer",)},
            audience=("customer", "operator"),
            idempotency="read_only",
            events=(),
            errors=(),
            customer_facing=True,
            implemented=True,
        ),
        # ── Declaradas, aún no migradas (M2.2/M2.3) — el camino real sigue en
        # el router/orchestrator hasta su fase (strangler).
        Operation(
            name="orders.transition",
            description=(
                "Transición de estado forward-only (pending→confirmed→…→delivered) "
                "con efectos de stock (decrement al confirmar, restore al cancelar "
                "desde estado decrementado)."
            ),
            service_fn="transition_order",
            rbac={"console": ("owner", "manager", "operator")},
            audience=("operator",),
            idempotency="unique_natural",   # movements únicos por (order, variation, reason)
            events=("order.status_changed",),
            errors=("VALIDATION", "NOT_FOUND", "PRECONDITION", "FORBIDDEN"),
            customer_facing=False,
            implemented=False,              # M2.2
        ),
        Operation(
            name="orders.cancel",
            description=(
                "Cancelación con pipeline legal completo (reglas tenant, void "
                "Wompi, cancel guía Aveonline, restock idempotente, audit "
                "order_cancellations, notificaciones). UNA semántica para ambos "
                "canales (decisión founder 2026-08-25 #2)."
            ),
            service_fn="cancel_order",
            rbac={
                "console": ("owner", "manager"),   # MFA AAL2 humano
                "bot": ("customer",),              # confirmación en 2 turnos (B6)
            },
            audience=("customer", "operator"),
            idempotency="unique_natural",   # order_cancellations + rpc_stock_restore
            events=("order.cancelled",),
            errors=("NOT_FOUND", "PRECONDITION", "FORBIDDEN", "UPSTREAM"),
            customer_facing=True,
            implemented=True,               # M2.2 — konvi_domain.orders.cancellation.cancel_order
        ),
        Operation(
            name="payments.get_or_create_link",
            description=(
                "Link de pago Wompi para un pedido: reuso por TTL vigente o "
                "creación con mínimo $1.500 COP; colapsa la política espejada "
                "router↔bot (M1 §3.3)."
            ),
            service_fn="get_or_create_payment_link",
            rbac={"console": ("owner", "manager"), "bot": ("customer",)},
            audience=("customer", "operator"),
            idempotency="derived_key",      # plink:{order}:b{bucket} + reuso TTL
            events=("payment.link_created",),
            errors=("NOT_FOUND", "PRECONDITION", "VALIDATION", "UPSTREAM"),
            customer_facing=True,
            implemented=False,              # M2.3
        ),
        Operation(
            name="payments.confirm",
            description=(
                "Confirmación de pago (webhook Wompi): dedup por checksum, "
                "guard monto/moneda fail-closed, decremento de stock, guía, "
                "notificaciones. Frontera webhook→servicio."
            ),
            service_fn="confirm_payment",
            rbac={"worker": ("system",)},
            audience=("operator",),
            idempotency="unique_natural",   # wompi_events_seen + upsert anti-degradación
            events=("payment.confirmed",),
            errors=("VALIDATION", "PRECONDITION", "UPSTREAM"),
            customer_facing=False,
            implemented=False,              # referencia (no se mueve en los pilotos)
        ),
    ),
)

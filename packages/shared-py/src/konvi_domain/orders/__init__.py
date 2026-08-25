"""Dominio pedidos — service + contrato (Track 5 M2.1)."""
from konvi_domain.orders.contract import ORDERS_CONTRACT
from konvi_domain.orders.models import (
    ORDER_STATUS_RANK,
    ORDER_TERMINAL_STATUSES,
    PAYMENT_METHOD_COD,
    PAYMENT_METHOD_CREDIT,
    STATUS_PRESENTATION_ORDER,
    VALID_PAYMENT_METHODS,
    VALID_STATUSES,
    CreateOrderInput,
    CreateOrderResult,
    OrderItemInput,
    OrdersPage,
)
from konvi_domain.orders.service import (
    create_order,
    get_order,
    is_allowed_order_transition,
    list_orders,
    list_orders_by_contact,
)
from konvi_domain.orders.cancellation import (
    CancellationItem,
    CancellationPorts,
    CancellationRequest,
    CancellationResult,
    TenantPolicy,
    cancel_order,
    detect_escalation_reasons,
    is_void_eligible,
    load_policy,
)

__all__ = [
    "ORDERS_CONTRACT",
    "VALID_STATUSES",
    "ORDER_STATUS_RANK",
    "ORDER_TERMINAL_STATUSES",
    "STATUS_PRESENTATION_ORDER",
    "PAYMENT_METHOD_COD",
    "PAYMENT_METHOD_CREDIT",
    "VALID_PAYMENT_METHODS",
    "CreateOrderInput",
    "CreateOrderResult",
    "OrderItemInput",
    "OrdersPage",
    "create_order",
    "get_order",
    "list_orders",
    "list_orders_by_contact",
    "is_allowed_order_transition",
    # Cancelación unificada (M2.2)
    "CancellationItem",
    "CancellationPorts",
    "CancellationRequest",
    "CancellationResult",
    "TenantPolicy",
    "cancel_order",
    "detect_escalation_reasons",
    "is_void_eligible",
    "load_policy",
]

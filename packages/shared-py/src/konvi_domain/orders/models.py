"""DTOs del dominio pedidos (Track 5 M2.1).

Dataclasses inmutables — el paquete no depende de pydantic para los modelos de
entrada/salida del servicio (el router FastAPI mantiene sus propios modelos de
borde y los traduce; M3 generará schemas LLM de estos mismos campos).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from konvi_domain.events import DomainEvent

# Máquina de estados de la orden (A11 audit ORD-01) — canon de dominio.
VALID_STATUSES = frozenset({
    "pending", "pending_payment", "confirmed", "processing",
    "shipped", "delivered", "cancelled",
})
ORDER_STATUS_RANK = {
    "pending": 0, "pending_payment": 0,
    "confirmed": 1, "processing": 2, "shipped": 3, "delivered": 4,
}
ORDER_TERMINAL_STATUSES = frozenset({"delivered", "cancelled"})

# Orden canónico de presentación (badges de la consola, conteos por estado).
STATUS_PRESENTATION_ORDER = (
    "pending", "pending_payment", "confirmed", "processing",
    "shipped", "delivered", "cancelled",
)

PAYMENT_METHOD_CREDIT = "credit"
PAYMENT_METHOD_COD = "cod"
VALID_PAYMENT_METHODS = frozenset({PAYMENT_METHOD_CREDIT, PAYMENT_METHOD_COD})


@dataclass(frozen=True)
class OrderItemInput:
    product_id: Optional[str] = None
    variation_id: Optional[str] = None
    title: str = ""
    unit_price: float = 0.0
    unit_cost: Optional[float] = None
    quantity: int = 1


@dataclass(frozen=True)
class CreateOrderInput:
    """Entrada de `orders.create` — espejo de los campos de negocio de
    `OrderCreate` (router). La validación de forma (min_length, ge, pattern)
    la hace el modelo pydantic del borde; aquí llegan valores ya válidos."""

    items: tuple[OrderItemInput, ...]
    contact_id: Optional[str] = None
    conversation_id: Optional[str] = None
    notes: Optional[str] = None
    shipping_cost: float = 0.0
    auto_confirm: bool = False
    payment_link: bool = False
    payment_method: str = PAYMENT_METHOD_CREDIT


@dataclass
class CreateOrderResult:
    """Resultado de `orders.create`.

    `http_status` codifica la semántica heredada del money-path: 201 creada ·
    200 adoptada (carrera 23505 — el caller recibe la orden ganadora).
    """

    order: dict[str, Any]
    items: list[dict[str, Any]]
    adopted_existing: bool = False
    http_status: int = 201
    events: tuple[DomainEvent, ...] = ()

    def body(self) -> dict[str, Any]:
        """Shape exacto de la respuesta REST heredada (compatibilidad total)."""
        b: dict[str, Any] = {**self.order, "items": self.items}
        if self.adopted_existing:
            b["adopted_existing"] = True
        return b


@dataclass
class OrdersPage:
    """Página de `orders.list` para la consola (listado + conteos por estado)."""

    orders: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    counts: dict[str, int] = field(default_factory=dict)

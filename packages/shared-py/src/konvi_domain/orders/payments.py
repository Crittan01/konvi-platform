"""Payments del dominio pedidos — `payments.get_or_create_link` (Track 5 M2.3).

UNA política de reuso/TTL del link de pago Wompi, extraída intacta de
`services/api/routers/orders.py:create_payment_link` (que queda como adaptador
HTTP: dual-auth, Idempotency-Key, audit decorator, mapeo de errores). Colapsa
la duplicación medida en M1 §3.3 (criterio espejado router↔bot + TTL espejado):

  - El bot conserva su espejo CONGELADO (`services/ai-orchestrator/tools/
    payment_link_tool.py`) hasta el bloque bot (B-2/M3 lo adopta del paquete).
    La duplicación time-boxed queda con alarma:
    `tests/test_payment_link_policy_parity.py`.
  - La regeneración post-pago fallido (`routers/wompi_webhook.py`) sigue
    consumiendo el TTL vía el shim `integrations/wompi_client` (re-export).

Espejos que asumen el TTL (mantener alineados — heredado del comentario de
`wompi_client.py`):
  • `tools/payment_link_tool.py:WOMPI_LINK_TTL_MINUTES` (boundary bucket a/b
    del idempotency guard del bot).
  • `worker.py:PAYMENT_REMINDER_DELAY_MINUTES` (recordatorio 5 min antes).
El cron de cancelación de orden (PENDING_PAYMENT_TTL_MINUTES) se diseña 5 min
POR ENCIMA de este valor para permitir regeneración sobre la misma orden.
Detalles: docs/adr/0011-payment-link-lifecycle.md.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from konvi_domain.actor import Actor
from konvi_domain.errors import DomainError, ErrorCode
from konvi_domain.events import DomainEvent

logger = logging.getLogger(__name__)

# ── TTL del link de pago (ÚNICA fuente de la política) ───────────────────────
# Antes del cierre 2026-08-02 había DOS lecturas divergentes: orders.py
# hardcodeaba 30 (creación) y wompi_webhook.py leía el env (regeneración) → un
# override del env solo aplicaba a la mitad de los links. Hoy es UNA función;
# el env NO está seteado en render.yaml ni .env.local (default 30 en ambos
# canales) — si alguien lo setea, la alarma de paridad con el bot lo destapa.
DEFAULT_PAYMENT_LINK_TTL_MINUTES = 30

# Mínimo Wompi modelo Agregador: $1.500 COP (validado contra docs oficiales).
MIN_WOMPI_AMOUNT_CENTS = 150_000


def payment_link_ttl_minutes() -> int:
    """TTL (minutos) del link de pago Wompi (`expires_at` al crear/regenerar).

    Lee `WOMPI_PAYMENT_LINK_TTL_MINUTES` del env en CADA llamada (testeable y
    coherente entre creación y regeneración). Default 30; valor inválido o <1
    cae al default con warning (fail-safe: un TTL malformado nunca rompe la
    generación del link de pago).
    """
    raw = os.getenv("WOMPI_PAYMENT_LINK_TTL_MINUTES", "").strip()
    if not raw:
        return DEFAULT_PAYMENT_LINK_TTL_MINUTES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "[WOMPI] WOMPI_PAYMENT_LINK_TTL_MINUTES inválido (%r) — usando default %d",
            raw, DEFAULT_PAYMENT_LINK_TTL_MINUTES,
        )
        return DEFAULT_PAYMENT_LINK_TTL_MINUTES
    if value < 1:
        logger.warning(
            "[WOMPI] WOMPI_PAYMENT_LINK_TTL_MINUTES=%d <1 — usando default %d",
            value, DEFAULT_PAYMENT_LINK_TTL_MINUTES,
        )
        return DEFAULT_PAYMENT_LINK_TTL_MINUTES
    return value


def payment_link_expires_at(created_at: object) -> str:
    """Deriva el `expires_at` de un link REUTILIZADO: created_at + TTL (misma
    regla que en la creación; la fila payments no persiste expires_at).
    Formato idéntico al de creación ('%Y-%m-%dT%H:%M:%S.000Z'). Si created_at
    no es parseable retorna '' (degradación segura — espeja al bot, que en
    reuso responde expires_at='')."""
    if not isinstance(created_at, str) or not created_at:
        return ""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (created + timedelta(minutes=payment_link_ttl_minutes())).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def find_reusable_payment_link(
    supabase: Any, *, tenant_id: str, order_id: str
) -> Optional[dict]:
    """Fila `payments` con link vigente (dentro del TTL) para la orden, o None.

    Criterio EXACTO heredado (espejo del bot `payment_link_tool.py:
    _find_pending_order` — paridad defendida por test): payments de la orden
    con status='pending', created_at >= now - TTL, más reciente primero;
    reusable SOLO si la fila tiene checkout_url no vacío. Lookup defensivo:
    si FALLA → None (degradar a crear — disponibilidad, igual que el bot).
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=payment_link_ttl_minutes())
    ).isoformat()
    try:
        res = (
            supabase.table("payments")
            .select("checkout_url, wompi_link_id, status, created_at, amount_in_cents")
            .eq("tenant_id", tenant_id)
            .eq("order_id", order_id)
            .eq("status", "pending")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data if isinstance(res.data, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[PAYMENT_LINK] reuso lookup falló order=%s: %s — procediendo a crear",
            order_id, exc,
        )
        return None
    if rows and isinstance(rows[0], dict) and rows[0].get("checkout_url"):
        return rows[0]
    return None


def amount_to_cents(total_amount: float) -> int:
    """BLOQUE A (P1): round, NO int() — total_amount es numeric(10,2) leído
    como float; total_amount*100 puede producir X.9999998 y int() trunca 1
    cent (subcobro). round() recupera los cents exactos acordados."""
    return int(round(total_amount * 100))


def validate_link_amount(total_amount: float) -> int:
    """Monto en cents para el link; exige el mínimo Wompi ($1.500 COP).

    La rama de REUSO salta este guard (hoy y siempre): un link vigente ya
    superó la validación cuando se creó.
    """
    amount_in_cents = amount_to_cents(total_amount)
    if amount_in_cents < MIN_WOMPI_AMOUNT_CENTS:
        raise DomainError(
            ErrorCode.VALIDATION,
            f"Monto mínimo Wompi es $1.500 COP. Monto actual: ${total_amount:,.0f}",
        )
    return amount_in_cents


# ── Puertos inyectados por el adaptador del canal ────────────────────────────


@dataclass(frozen=True)
class PaymentLinkPorts:
    """Efectos de proveedor que cada canal cablea con sus piezas.

    - `wompi_credentials(tenant_id) -> (private_key, environment) | None`:
      credenciales Wompi del tenant (Vault). None = sin llave configurada.
    - `create_link(...) -> dict`: crea el link en Wompi (async) con los kwargs
      del cliente oficial (private_key/environment/order_id/name/description/
      amount_in_cents/expires_at/contact); retorna {link_id, checkout_url, …}.
      El tuning de resiliencia (max_attempts, circuit breaker) es decisión del
      canal y vive en la implementación inyectada.
    """

    wompi_credentials: Callable[[str], Optional[tuple[str, str]]]
    create_link: Callable[..., Awaitable[dict]]


@dataclass
class PaymentLinkOutcome:
    """Resultado de `payments.get_or_create_link`.

    `reused=True` → el link vigente se reusó (sin llamada a Wompi, sin fila
    payments nueva, sin update de la orden). El shape de `body()` es el de la
    respuesta REST heredada (compatibilidad total).
    """

    order_id: str
    checkout_url: str
    amount_in_cents: int
    expires_at: str
    wompi_link_id: Optional[str]
    reused: bool = False
    events: tuple[DomainEvent, ...] = field(default_factory=tuple)

    def body(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "checkout_url": self.checkout_url,
            "amount_in_cents": self.amount_in_cents,
            "expires_at": self.expires_at,
            "wompi_link_id": self.wompi_link_id,
        }


async def get_or_create_payment_link(
    supabase: Any,
    *,
    tenant_id: str,
    order_id: str,
    actor: Actor,
    ports: PaymentLinkPorts,
) -> PaymentLinkOutcome:
    """Link de pago Wompi para un pedido pending|pending_payment: reuso por
    TTL vigente o creación nueva. UNA semántica para todos los canales.

    Orden de pasos heredado (certificado por los tests del endpoint):
      creds (503 si sin private_key) → order lookup (404) → status check (409)
      → reuso (sin Wompi ni insert ni update) → guard de monto (422, la rama
      de reuso lo salta) → crear link en Wompi → insert payments (pending /
      wompi_status ACTIVE) → flip de la orden a pending_payment si no lo está.
    """
    # 1) Credenciales Wompi del tenant (Vault, vía puerto del canal).
    creds = ports.wompi_credentials(tenant_id)
    if not creds or not creds[0]:
        raise DomainError(
            ErrorCode.UPSTREAM,
            "Integración Wompi no configurada. Conéctala en Ajustes → Integraciones.",
            # 503 heredado (proveedor no configurado ≠ fallo interno 500).
            http_status=503,
        )
    private_key, wompi_environment = creds

    # 2) Pedido + contacto embebido (customer_data Wompi, rev. 68).
    order_res = (
        supabase.table("orders")
        .select(
            "id, status, total_amount, shipping_cost, notes, contact_id, "
            "contacts(name, phone, email, document_type, document_number)"
        )
        .eq("id", order_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not order_res or not order_res.data:  # maybe_single() retorna None en 0 filas
        raise DomainError(ErrorCode.NOT_FOUND, "Pedido no encontrado")

    order = order_res.data
    # 3) Solo pedidos aún pagables.
    if order["status"] not in ("pending", "pending_payment"):
        raise DomainError(
            ErrorCode.PRECONDITION,
            f"El pedido está en estado '{order['status']}' — solo se puede "
            "generar link para pedidos pending o pending_payment",
        )

    # 4) Reuso anti-duplicado de DINERO: link vigente → responderlo tal cual.
    reusable = find_reusable_payment_link(
        supabase, tenant_id=tenant_id, order_id=order_id
    )
    if reusable is not None:
        logger.info(
            "[PAYMENT_LINK] reutilizando link vigente order=%s link=%s "
            "(sin llamada a Wompi ni fila payments nueva)",
            order_id, reusable.get("wompi_link_id"),
        )
        return PaymentLinkOutcome(
            order_id=order_id,
            checkout_url=reusable["checkout_url"],
            amount_in_cents=int(reusable.get("amount_in_cents") or 0),
            expires_at=payment_link_expires_at(reusable.get("created_at")),
            wompi_link_id=reusable.get("wompi_link_id"),
            reused=True,
        )

    # 5) Guard de dinero (la rama de reuso lo salta — ya validó al crearse).
    total_amount = float(order.get("total_amount") or 0)
    amount_in_cents = validate_link_amount(total_amount)

    # 6) Crear el link en Wompi (puerto del canal — resiliencia inyectada).
    contact = order.get("contacts") or {}
    contact_name = contact.get("name") or "Cliente"
    short_id = order_id[:8].upper()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=payment_link_ttl_minutes())
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    link_data = await ports.create_link(
        private_key=private_key,
        environment=wompi_environment,
        order_id=order_id,
        name=f"Pedido #{short_id} — {contact_name}"[:100],
        description=order.get("notes") or f"Pedido #{short_id}",
        amount_in_cents=amount_in_cents,
        expires_at=expires_at,
        contact=contact,  # rev. 68 — preservado para futuro Widget/Transactions
    )

    # 7) Persistir el link en payments.
    supabase.table("payments").insert({
        "tenant_id": tenant_id,
        "order_id": order_id,
        "provider": "wompi",
        "wompi_link_id": link_data["link_id"],
        "checkout_url": link_data["checkout_url"],
        "amount_in_cents": amount_in_cents,
        "currency": "COP",
        "status": "pending",
        "wompi_status": "ACTIVE",
    }).execute()

    # 8) Asegurar que el pedido quede en pending_payment.
    if order["status"] != "pending_payment":
        supabase.table("orders").update({"status": "pending_payment"}).eq(
            "id", order_id
        ).eq("tenant_id", tenant_id).execute()

    logger.info(
        "Payment link generado para order %s: %s", order_id, link_data["checkout_url"]
    )
    return PaymentLinkOutcome(
        order_id=order_id,
        checkout_url=link_data["checkout_url"],
        amount_in_cents=amount_in_cents,
        expires_at=expires_at,
        wompi_link_id=link_data["link_id"],
        reused=False,
        events=(DomainEvent("payment.link_created", {
            "order_id": order_id,
            "tenant_id": tenant_id,
            "wompi_link_id": link_data["link_id"],
            "amount_in_cents": amount_in_cents,
            "channel": actor.channel.value,
        }),),
    )

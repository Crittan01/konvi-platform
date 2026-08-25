"""Contrato declarado del dominio reclamos (D2; domain-services-contract.md §5.1).

Fuente que M3 leerá para generar las tools del bot (create_claim / get_claim_status
dejan de ser código escrito a mano) y la Platform Console para descubrir
capacidades. Las 7 operaciones del piloto están implementadas (M2.4).
"""
from __future__ import annotations

from konvi_domain.contract import DomainContract, Operation

CLAIMS_CONTRACT = DomainContract(
    domain="claims",
    operations=(
        Operation(
            name="claims.create",
            description=(
                "Registra un reclamo sobre un pedido: reason de vocabulario "
                "cerrado + reason_detail libre opcional (decisión founder #3), "
                "dedup de reclamo abierto por (tenant, pedido, cliente), "
                "titularidad por actor (customer solo sobre pedidos suyos) y "
                "eventos unidos (audit + claim_audit + Telegram operador)."
            ),
            service_fn="create_claim",
            rbac={
                "console": ("owner", "manager", "operator"),  # G-4: operator es front-line
                "bot": ("customer",),
            },
            audience=("customer", "operator"),
            # Dedup: un reclamo open/investigating por (tenant, order, customer)
            # devuelve el existente (patrón adopt-winner).
            idempotency="unique_natural",
            events=("claim.created", "claim.deduplicated"),
            errors=("VALIDATION", "NOT_FOUND", "FORBIDDEN", "UPSTREAM"),
            customer_facing=True,
            implemented=True,
        ),
        Operation(
            name="claims.get",
            description=(
                "Detalle de un reclamo por id o por número de ticket "
                "(secuencial per-tenant). Customer solo lee los suyos."
            ),
            service_fn="get_claim",
            rbac={
                "console": ("owner", "manager", "operator"),
                "bot": ("customer",),
            },
            audience=("customer", "operator"),
            idempotency="read_only",
            events=(),
            errors=("VALIDATION", "NOT_FOUND", "FORBIDDEN"),
            customer_facing=True,
            implemented=True,
        ),
        Operation(
            name="claims.list",
            description=(
                "Listado del tenant para la consola con embeds de pedido y "
                "contacto + reason_detail; filtros por estado/cliente/pedido."
            ),
            service_fn="list_claims",
            rbac={"console": ("owner", "manager", "operator")},
            audience=("operator", "owner"),
            idempotency="read_only",
            events=(),
            errors=("VALIDATION",),
            customer_facing=False,
            implemented=True,
        ),
        Operation(
            name="claims.list_by_contact",
            description=(
                "Reclamos de un contacto (cliente actual del bot sin necesidad "
                "de ticket — hueco M1 §3.8 — o ficha del contacto en consola)."
            ),
            service_fn="list_claims_by_contact",
            rbac={
                "console": ("owner", "manager", "operator"),
                "bot": ("customer",),
            },
            audience=("customer", "operator"),
            idempotency="read_only",
            events=(),
            errors=(),
            customer_facing=True,
            implemented=True,
        ),
        Operation(
            name="claims.transition",
            description=(
                "Transición de estado con FSM formalizada: 'refunded' FINAL, "
                "refunded_amount write-once (sellando el KPI net-revenue), "
                "reapertura solo owner desde rejected/cancelled, notificación "
                "WhatsApp al cliente en outcome real (F-5)."
            ),
            service_fn="transition_claim",
            rbac={"console": ("owner", "manager")},
            audience=("operator",),
            # refunded_amount write-once + refunded final + mismo-status no-op.
            idempotency="unique_natural",
            events=("claim.status_changed",),
            errors=("VALIDATION", "NOT_FOUND", "CONFLICT", "FORBIDDEN"),
            customer_facing=False,
            implemented=True,
        ),
        Operation(
            name="claims.register_reversion",
            description=(
                "Radica la queja de reversión del pago (Ley 1480 art. 51 + "
                "Decreto 1074 cap. 2.2.2.51) y emite la constancia con fecha y "
                "causal en el mismo acto, delegando en la RPC SECURITY DEFINER. "
                "Idempotente por reclamo (el reintento devuelve la constancia "
                "existente sin re-fechas)."
            ),
            service_fn="register_reversion",
            rbac={"console": ("owner", "manager")},
            audience=("operator",),
            # UNIQUE(claim_id) en payment_reversal_requests (la RPC lo garantiza).
            idempotency="unique_natural",
            events=("payment_reversion.created",),
            errors=("VALIDATION", "NOT_FOUND", "CONFLICT"),
            customer_facing=False,
            implemented=True,
        ),
        Operation(
            name="claims.register_reversion_movement",
            description=(
                "Registra por cuál vía volvió el dinero (reembolso_directo / "
                "reversion_emisor) y detecta el doble pago del art. 2.2.2.51.10, "
                "delegando en la RPC SECURITY DEFINER."
            ),
            service_fn="register_reversion_movement",
            rbac={"console": ("owner", "manager")},
            audience=("operator",),
            # Movimientos sobre la constancia única del reclamo (UNIQUE(claim_id)).
            idempotency="unique_natural",
            events=("payment_reversion.updated",),
            errors=("VALIDATION", "NOT_FOUND"),
            customer_facing=False,
            implemented=True,
        ),
    ),
)

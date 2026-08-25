"""DTOs y enums canónicos del dominio reclamos (Track 5 M2.4; contrato §5).

Enums ÚNICOS del dominio — mata el drift medido en M1 §3.8:
  - `CLAIM_STATUSES` / `CLAIM_TERMINAL_STATUSES` / `CLAIM_REOPENABLE_STATUSES`
    (hoy `routers/claims.py:47,51,58` — quedan como alias del paquete). El set
    espejo del bot (`agentic/tools/claims.py:52`) queda CONGELADO hasta B-2/M3,
    defendido por la alarma de paridad (`tests/test_claims_policy_parity.py`).
  - `CLAIM_REASONS`: vocabulario cerrado de `reason` (decisión founder #3 —
    espejo del REASON_MAP de la UI `claims-manager.tsx:61-67`). La DB NO lleva
    CHECK: el bot congelado sigue escribiendo free-text hasta M3 (deliberado,
    `routers/claims.py:60-66` histórico).
  - `CAUSALES_REVERSION` / `VIAS_REVERSION`: las cinco del art. 2.2.2.51.2 y
    los dos caminos por los que vuelve la plata (art. 2.2.2.51.10).

Dataclasses inmutables — el paquete no depende de pydantic (el router FastAPI
mantiene sus modelos de borde y los traduce; M3 generará schemas LLM de estos
mismos campos).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from konvi_domain.events import DomainEvent

# ── Máquina de estados del reclamo (canon de dominio) ────────────────────────
CLAIM_STATUSES = frozenset({
    "open", "investigating", "resolved", "refunded", "rejected", "cancelled",
})
# Terminales: el ticket ya está cerrado. Reabrir = transición especial.
CLAIM_TERMINAL_STATUSES = frozenset({"resolved", "refunded", "rejected", "cancelled"})
# Terminales que un OWNER puede reabrir (decisión F2 — Opción B):
#   'rejected'/'cancelled' reversibles · 'refunded' NUNCA (ya movió dinero) ·
#   'resolved' se maneja como reclamo nuevo (cierre positivo).
CLAIM_REOPENABLE_STATUSES = frozenset({"rejected", "cancelled"})

# Vocabulario cerrado de `reason` (decisión founder 2026-08-25 #3).
CLAIM_REASONS = frozenset({"defective", "wrong_item", "missing_parts", "delayed", "other"})

# Máximo del detalle libre — mismo límite que el free-text del bot
# (CreateClaimArgs.reason max_length=500).
REASON_DETAIL_MAX_LENGTH = 500

# ── Reversión del pago (Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51) ───────
CAUSALES_REVERSION = frozenset({
    "fraude",
    "operacion_no_solicitada",
    "producto_no_recibido",
    "producto_no_corresponde",
    "producto_defectuoso",
})
VIAS_REVERSION = frozenset({"reembolso_directo", "reversion_emisor"})

# Transiciones que disparan la notificación WhatsApp al cliente (BLOQUE F-5).
CLAIM_OUTCOME_STATUSES = frozenset({"resolved", "rejected"})


@dataclass(frozen=True)
class ClaimCreateInput:
    """Entrada de `claims.create` — campos de negocio del ClaimCreate del borde
    + `reason_detail` (decisión founder #3). La validación de forma (min_length,
    ge, max_length) la hace el modelo pydantic del router."""

    order_id: str
    reason: str
    customer_id: Optional[str] = None
    reason_detail: Optional[str] = None
    requested_amount: Optional[float] = None
    resolution_notes: Optional[str] = None


@dataclass
class ClaimCreateResult:
    """Resultado de `claims.create`.

    `created=False` → la dedup (un reclamo abierto/investigating ya existe para
    ese pedido+cliente) devolvió el EXISTENTE sin insertar (patrón adopt-winner
    de orders.create): el adaptador responde 200 + `deduplicated: true`.
    """

    claim: dict[str, Any]
    created: bool = True
    http_status: int = 201
    events: tuple[DomainEvent, ...] = ()

    def body(self) -> dict[str, Any]:
        """Shape de la respuesta REST heredada (compatibilidad total)."""
        b: dict[str, Any] = dict(self.claim)
        if not self.created:
            b["deduplicated"] = True
        return b


@dataclass(frozen=True)
class ClaimTransitionInput:
    """Entrada de `claims.transition` (absorbe PATCH y POST /resolve)."""

    status: Optional[str] = None
    resolution_notes: Optional[str] = None
    # BLOQUE G-2 — monto REAL reembolsado (obligatorio al pasar a 'refunded';
    # write-once; el KPI net-revenue resta ESTE, no requested_amount).
    refunded_amount: Optional[float] = None


@dataclass(frozen=True)
class ReversionInput:
    """Entrada de `claims.register_reversion` — la queja del consumidor con su
    causal declarada (art. 2.2.2.51.4). `razones` va en sus palabras, no se
    resume; `instrumento` es un DESCRIPTOR, nunca un PAN (obligación PCI que
    este sistema no asume)."""

    causal: str
    razones: str
    valor: float
    instrumento: Optional[str] = None
    es_parcial: bool = False
    items: Optional[list] = None
    bien_a_disposicion: bool = False
    canal: str = "inbox"
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    meta_message_id: Optional[str] = None

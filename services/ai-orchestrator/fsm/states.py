"""Estados canónicos del FSM conversacional.

Rev. 104 (F1-2) — extraído de orchestrator.py.

Los estados modelan la posición del cliente en el flow de compra/atención.
Son una enum-like (str constants) para retrocompatibilidad con código que
hace `==`/`in` checks contra strings.

Categorías:
  • **Sin compra activa**: CATALOG_MODE.
  • **Recolección pre-checkout**: NEEDS_SHIPPING_CITY → AWAITING_CARRIER_SELECTION.
  • **Recolección PII**: NEEDS_CONSENT → NEEDS_EMAIL → NEEDS_NAME →
    NEEDS_DOCUMENT → NEEDS_DIRECTION → READY_FOR_SUMMARY.
  • **Confirmación**: AWAITING_ORDER_CONFIRMATION (post-resumen).

Tipo: literal str (no Enum) para compat 100% con `if state == "X"` legacy.
"""
from __future__ import annotations

from typing import Literal


# ─── Catálogo ────────────────────────────────────────────────────────────────
CATALOG_MODE: Literal["CATALOG_MODE"] = "CATALOG_MODE"

# ─── Pre-checkout ────────────────────────────────────────────────────────────
NEEDS_SHIPPING_CITY: Literal["NEEDS_SHIPPING_CITY"] = "NEEDS_SHIPPING_CITY"
AWAITING_CARRIER_SELECTION: Literal["AWAITING_CARRIER_SELECTION"] = "AWAITING_CARRIER_SELECTION"

# ─── Recolección PII (orden FSM canónico rev. 68) ───────────────────────────
NEEDS_CONSENT: Literal["NEEDS_CONSENT"] = "NEEDS_CONSENT"
NEEDS_EMAIL: Literal["NEEDS_EMAIL"] = "NEEDS_EMAIL"
NEEDS_NAME: Literal["NEEDS_NAME"] = "NEEDS_NAME"
NEEDS_DOCUMENT: Literal["NEEDS_DOCUMENT"] = "NEEDS_DOCUMENT"
NEEDS_DIRECTION: Literal["NEEDS_DIRECTION"] = "NEEDS_DIRECTION"

# ─── Resumen + confirmación ──────────────────────────────────────────────────
READY_FOR_SUMMARY: Literal["READY_FOR_SUMMARY"] = "READY_FOR_SUMMARY"
AWAITING_ORDER_CONFIRMATION: Literal["AWAITING_ORDER_CONFIRMATION"] = "AWAITING_ORDER_CONFIRMATION"


# ─── Sets agrupados (útiles para guards/dispatchers) ────────────────────────

PII_COLLECTION_STATES: frozenset[str] = frozenset({
    NEEDS_CONSENT, NEEDS_EMAIL, NEEDS_NAME,
    NEEDS_DOCUMENT, NEEDS_DIRECTION,
})

PRE_CHECKOUT_STATES: frozenset[str] = frozenset({
    NEEDS_SHIPPING_CITY, AWAITING_CARRIER_SELECTION,
})

CHECKOUT_STATES: frozenset[str] = frozenset({
    READY_FOR_SUMMARY, AWAITING_ORDER_CONFIRMATION,
})

ALL_STATES: frozenset[str] = (
    PII_COLLECTION_STATES
    | PRE_CHECKOUT_STATES
    | CHECKOUT_STATES
    | {CATALOG_MODE}
)

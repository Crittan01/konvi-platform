"""FSM package — estados + resolver determinístico (rev. 104, F1-2).

Exports públicos para que el orchestrator y otros consumidores puedan
importar desde `fsm` directamente sin conocer la estructura interna.
"""
from . import states
from .states import (
    CATALOG_MODE,
    NEEDS_SHIPPING_CITY, AWAITING_CARRIER_SELECTION,
    NEEDS_CONSENT, NEEDS_EMAIL, NEEDS_NAME, NEEDS_DOCUMENT, NEEDS_DIRECTION,
    READY_FOR_SUMMARY, AWAITING_ORDER_CONFIRMATION,
    PII_COLLECTION_STATES, PRE_CHECKOUT_STATES, CHECKOUT_STATES, ALL_STATES,
)
from .resolver import (
    determine_transactional_state,
    resolve_display_state,
    _has_real_address_data,
)
from .address import (
    has_real_address_data,
    missing_address_fields,
    normalize_building_type,
)

__all__ = [
    "states",
    # State constants
    "CATALOG_MODE",
    "NEEDS_SHIPPING_CITY", "AWAITING_CARRIER_SELECTION",
    "NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME", "NEEDS_DOCUMENT", "NEEDS_DIRECTION",
    "READY_FOR_SUMMARY", "AWAITING_ORDER_CONFIRMATION",
    # State sets
    "PII_COLLECTION_STATES", "PRE_CHECKOUT_STATES", "CHECKOUT_STATES", "ALL_STATES",
    # Resolver functions
    "determine_transactional_state", "resolve_display_state",
    "_has_real_address_data",
    # Address validators
    "has_real_address_data", "missing_address_fields", "normalize_building_type",
]

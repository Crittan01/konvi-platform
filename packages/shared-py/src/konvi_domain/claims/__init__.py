"""Dominio reclamos — service + contrato (Track 5 M2.4)."""
from konvi_domain.claims.contract import CLAIMS_CONTRACT
from konvi_domain.claims.models import (
    CAUSALES_REVERSION,
    CLAIM_OUTCOME_STATUSES,
    CLAIM_REASONS,
    CLAIM_REOPENABLE_STATUSES,
    CLAIM_STATUSES,
    CLAIM_TERMINAL_STATUSES,
    REASON_DETAIL_MAX_LENGTH,
    VIAS_REVERSION,
    ClaimCreateInput,
    ClaimCreateResult,
    ClaimTransitionInput,
    ReversionInput,
)
from konvi_domain.claims.reversion import (
    read_reversion,
    register_reversion,
    register_reversion_movement,
)
from konvi_domain.claims.service import (
    CLAIM_LIST_SELECT,
    ClaimPorts,
    create_claim,
    get_claim,
    list_claims,
    list_claims_by_contact,
    transition_claim,
)

__all__ = [
    "CLAIMS_CONTRACT",
    "CLAIM_STATUSES",
    "CLAIM_TERMINAL_STATUSES",
    "CLAIM_REOPENABLE_STATUSES",
    "CLAIM_REASONS",
    "CLAIM_OUTCOME_STATUSES",
    "REASON_DETAIL_MAX_LENGTH",
    "CAUSALES_REVERSION",
    "VIAS_REVERSION",
    "CLAIM_LIST_SELECT",
    "ClaimCreateInput",
    "ClaimCreateResult",
    "ClaimTransitionInput",
    "ReversionInput",
    "ClaimPorts",
    "create_claim",
    "get_claim",
    "list_claims",
    "list_claims_by_contact",
    "transition_claim",
    "read_reversion",
    "register_reversion",
    "register_reversion_movement",
]

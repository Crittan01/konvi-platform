"""Invariants Python — guardrails NO delegables al LLM.

ADR-0018. Cada invariant es una función pura que valida el outbound
candidato del LLM contra el estado real del cart/DB y retorna:
  • OK → outbound se envía tal cual.
  • REWRITE → outbound se reescribe a texto determinístico seguro.
  • BLOCK → outbound se rechaza, fallback a CTA neutral.
"""
from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
    Invariant,
    apply_invariants,
)
from agentic.invariants.cart_state import CartStateInvariant
from agentic.invariants.consent_required import ConsentRequiredInvariant
from agentic.invariants.empty_promise import EmptyPromiseInvariant
from agentic.invariants.no_emoji import NoDecorativeEmojiInvariant
from agentic.invariants.passive_closing import PassiveClosingInvariant
from agentic.invariants.pii_coherence import PIICoherenceInvariant
from agentic.invariants.post_tool_coherence import PostToolCoherenceInvariant
from agentic.invariants.summary_coherence import SummaryCoherenceInvariant
from agentic.invariants.payment_method_explicit import PaymentMethodExplicitInvariant
from agentic.invariants.payment_mode_coherence import PaymentModeCoherenceInvariant
from agentic.invariants.category_completeness import CategoryCompletenessInvariant
from agentic.invariants.cart_add_pricing import CartAddPricingInvariant

__all__ = [
    "InvariantOutcome",
    "InvariantResult",
    "Invariant",
    "apply_invariants",
    "CartStateInvariant",
    "ConsentRequiredInvariant",
    "EmptyPromiseInvariant",
    "NoDecorativeEmojiInvariant",
    "PassiveClosingInvariant",
    "PaymentMethodExplicitInvariant",
    "PaymentModeCoherenceInvariant",
    "CategoryCompletenessInvariant",
    "CartAddPricingInvariant",
    "PIICoherenceInvariant",
    "PostToolCoherenceInvariant",
    "SummaryCoherenceInvariant",
]

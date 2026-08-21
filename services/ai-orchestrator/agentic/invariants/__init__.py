"""Invariants Python — guardrails NO delegables al LLM.

ADR-0018. Cada invariant es una función pura que valida el outbound
candidato del LLM contra el estado real del cart/DB y retorna:
  • OK → outbound se envía tal cual.
  • REWRITE → outbound se reescribe a texto determinístico seguro.
  • BLOCK → outbound se rechaza, fallback a CTA neutral.

Rev. 108 consolidación (founder 2026-05-27):
  • cart_render_coherence (consolida cart_state + cart_add_pricing +
    category_completeness — 3 invariants relacionados con cart/catalog
    rendering).
  • payment_coherence (consolida payment_method_explicit +
    payment_mode_coherence — 2 invariants sobre payment_method).
  De 14 invariants → 9. Reducción ~25% LOC sin perder coverage.
"""
from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
    Invariant,
    apply_invariants,
)
from agentic.invariants.cart_render_coherence import CartRenderCoherenceInvariant
from agentic.invariants.consent_required import ConsentRequiredInvariant
from agentic.invariants.empty_promise import EmptyPromiseInvariant
from agentic.invariants.fake_escalation import FakeEscalationInvariant
from agentic.invariants.no_emoji import NoDecorativeEmojiInvariant
from agentic.invariants.no_internals_exposure import NoInternalsExposureInvariant
from agentic.invariants.passive_closing import PassiveClosingInvariant
from agentic.invariants.payment_coherence import PaymentCoherenceInvariant
from agentic.invariants.payment_truth import PaymentTruthInvariant
from agentic.invariants.pii_coherence import PIICoherenceInvariant
from agentic.invariants.pii_save_truthfulness import PIISaveTruthfulnessInvariant
from agentic.invariants.post_tool_coherence import PostToolCoherenceInvariant
from agentic.invariants.requote_pending_summary import (
    RequotePendingSummaryInvariant,
)
from agentic.invariants.summary_coherence import SummaryCoherenceInvariant
from agentic.invariants.tool_code_leak import ToolCodeLeakInvariant
from agentic.invariants.variant_availability_assertion import (
    VariantAvailabilityAssertionInvariant,
)

__all__ = [
    "InvariantOutcome",
    "InvariantResult",
    "Invariant",
    "apply_invariants",
    "CartRenderCoherenceInvariant",
    "ConsentRequiredInvariant",
    "EmptyPromiseInvariant",
    "FakeEscalationInvariant",
    "NoDecorativeEmojiInvariant",
    "NoInternalsExposureInvariant",
    "PassiveClosingInvariant",
    "PaymentCoherenceInvariant",
    "PIICoherenceInvariant",
    "PIISaveTruthfulnessInvariant",
    "PostToolCoherenceInvariant",
    "RequotePendingSummaryInvariant",
    "SummaryCoherenceInvariant",
    "ToolCodeLeakInvariant",
    "VariantAvailabilityAssertionInvariant",
]

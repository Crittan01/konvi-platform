"""Canonical conversation and message-processing contract for the orchestrator."""

from typing import Final

CONVERSATION_STATUS_BOT_ACTIVE: Final[str] = "bot_active"
CONVERSATION_STATUS_HUMAN_TAKEOVER: Final[str] = "human_takeover"
CONVERSATION_STATUS_CLOSED: Final[str] = "closed"

PROCESSING_STATUS_PENDING: Final[str] = "pending"
PROCESSING_STATUS_PROCESSING: Final[str] = "processing"
PROCESSING_STATUS_PROCESSED: Final[str] = "processed"
PROCESSING_STATUS_SKIPPED: Final[str] = "skipped"
PROCESSING_STATUS_FAILED: Final[str] = "failed"

SKIP_REASON_HUMAN_TAKEOVER: Final[str] = "human_takeover_active"
SKIP_REASON_CLOSED: Final[str] = "closed_conversation"
SKIP_REASON_NON_TEXT: Final[str] = "non_text_requires_human"
SKIP_REASON_GUARDRAIL: Final[str] = "guardrail_blocked"

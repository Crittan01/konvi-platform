"""Canonical conversation and message-processing contract."""

from typing import Final

CONVERSATION_STATUSES: Final[set[str]] = {"bot_active", "human_takeover", "closed"}
DEFAULT_CONVERSATION_STATUS: Final[str] = "bot_active"

PROCESSING_STATUSES: Final[set[str]] = {"pending", "processed", "skipped", "failed"}

SKIP_REASON_HUMAN_TAKEOVER: Final[str] = "human_takeover_active"
SKIP_REASON_CLOSED: Final[str] = "closed_conversation"
SKIP_REASON_NON_TEXT: Final[str] = "non_text_requires_human"

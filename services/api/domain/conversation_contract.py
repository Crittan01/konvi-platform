"""Canonical conversation and message-processing contract."""

from typing import Final

# Rev. 105 Sem 4 H.4.1 — agrega 'opted_out' (cliente revocó consent vía
# STOP keyword en WhatsApp; conversación queda flagged opt-out pero NO
# bloqueada permanentemente — operador puede reactivar manual a bot_active).
CONVERSATION_STATUSES: Final[set[str]] = {
    "bot_active",
    "human_takeover",
    "closed",
    "opted_out",
}
DEFAULT_CONVERSATION_STATUS: Final[str] = "bot_active"

PROCESSING_STATUSES: Final[set[str]] = {"pending", "processed", "skipped", "failed"}

SKIP_REASON_HUMAN_TAKEOVER: Final[str] = "human_takeover_active"
SKIP_REASON_CLOSED: Final[str] = "closed_conversation"
SKIP_REASON_NON_TEXT: Final[str] = "non_text_requires_human"
SKIP_REASON_OPTED_OUT: Final[str] = "opted_out_conversation"

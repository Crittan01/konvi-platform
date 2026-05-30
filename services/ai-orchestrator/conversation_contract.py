"""Canonical conversation and message-processing contract for the orchestrator."""

from typing import Final

CONVERSATION_STATUS_BOT_ACTIVE: Final[str] = "bot_active"
CONVERSATION_STATUS_HUMAN_TAKEOVER: Final[str] = "human_takeover"
CONVERSATION_STATUS_CLOSED: Final[str] = "closed"
# Rev. 105 Sem 4 H.4.1 — cliente revocó consent vía STOP keyword (Habeas Data
# Ley 1581 ART. 9 + Meta Business Policy). Orchestrator skipea inbound mientras
# esté opted_out — operador puede reactivar manual (UI Inbox botón "Reactivar
# bot") cambiando status a bot_active. consent_revoked_at se mantiene
# independiente del status (filtra outbound proactivo / HSM templates).
CONVERSATION_STATUS_OPTED_OUT: Final[str] = "opted_out"

PROCESSING_STATUS_PENDING: Final[str] = "pending"
PROCESSING_STATUS_PROCESSING: Final[str] = "processing"
PROCESSING_STATUS_PROCESSED: Final[str] = "processed"
PROCESSING_STATUS_SKIPPED: Final[str] = "skipped"
PROCESSING_STATUS_FAILED: Final[str] = "failed"

SKIP_REASON_HUMAN_TAKEOVER: Final[str] = "human_takeover_active"
SKIP_REASON_CLOSED: Final[str] = "closed_conversation"
SKIP_REASON_NON_TEXT: Final[str] = "non_text_requires_human"
SKIP_REASON_GUARDRAIL: Final[str] = "guardrail_blocked"
SKIP_REASON_OPTED_OUT: Final[str] = "opted_out_conversation"

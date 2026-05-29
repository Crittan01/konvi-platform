"""ChannelAdapter — interface base del Channel Registry pluggable.

Rev. 109 backlog #3 (Plan I.3) — define el contrato que CUALQUIER canal
(WhatsApp, MeLi, Telegram, Web, Messenger, Instagram, SMS, etc.) debe
implementar para integrarse al orchestrator.

Diseño:
  • Protocol (typing.Protocol) — duck-typed. Cualquier clase con los
    métodos siguientes puede registrarse, sin herencia explícita.
  • Métodos minimal viable:
      parse_inbound(payload) → InboundMessage
      send_outbound(...)     → bool (success)
      verify_signature(...)  → bool (security)
      compliance_check(...)  → ComplianceVerdict (Habeas Data, Meta Policy)
  • Sin lógica de DB: el adapter es PURE I/O al canal externo. La DB
    es responsabilidad del caller (orchestrator).

Por qué Protocol vs ABC:
  • Adapters viven en módulos separados (e.g. channels/whatsapp.py).
  • Algunos ya existen como clases concretas (whatsapp_sender.py legacy).
  • Protocol permite "wrap" sin tocar código existente — backward-compat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


# ─── Data types ─────────────────────────────────────────────────────────────


@dataclass
class InboundMessage:
    """Normalización canónica del mensaje recibido en cualquier canal."""
    channel: str                   # 'whatsapp' | 'meli' | 'web' | ...
    tenant_id: str
    external_message_id: str       # ID en el canal origen (idempotency)
    sender_id: str                  # phone (WA), user_id (MeLi), session_id (web)
    sender_name: Optional[str] = None
    content_type: str = "text"      # text | image | audio | video | document
    content: str = ""               # texto inline o caption
    media_url: Optional[str] = None
    media_mime: Optional[str] = None
    received_at_iso: Optional[str] = None
    raw_payload: Optional[dict] = None  # acceso al payload original si el adapter lo necesita


@dataclass
class OutboundResult:
    """Resultado de send_outbound."""
    ok: bool
    external_message_id: Optional[str] = None  # ID en el canal (para tracking)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_after_seconds: Optional[int] = None  # 429 / rate limit


@dataclass
class ComplianceVerdict:
    """Resultado de compliance_check. Bloquea outbound si NO ok."""
    ok: bool
    reason_code: Optional[str] = None
    # Ej: 'meta_24h_window_closed', 'opt_out_active', 'meta_policy_violation'
    user_message: Optional[str] = None  # opcional para responder al cliente
    metadata: dict = field(default_factory=dict)


# ─── Protocol (interface) ───────────────────────────────────────────────────


@runtime_checkable
class ChannelAdapter(Protocol):
    """Contrato que CUALQUIER canal debe implementar.

    Métodos abstract (cada adapter implementa específico):

      • channel_name() → str
          Identificador canónico del canal ('whatsapp', 'meli', ...).

      • parse_inbound(payload: dict) → InboundMessage
          Convierte el payload nativo del canal a la forma canónica.

      • send_outbound(tenant_id, recipient, text=None, media_url=None,
                      content_type='text', ...) → OutboundResult
          Envía un mensaje al canal. Mapea a la API REST/SDK del canal.

      • verify_signature(headers: dict, raw_body: bytes,
                         tenant_id: str) → bool
          Valida HMAC/firma del webhook entrante. Security gate.

      • compliance_check(tenant_id, recipient_id,
                        message_kind='outbound') → ComplianceVerdict
          Verifica gates pre-envío: ventana 24h Meta, opt-out STOP,
          Meta Business Policy, etc.
    """

    def channel_name(self) -> str: ...

    def parse_inbound(self, payload: dict) -> InboundMessage: ...

    async def send_outbound(
        self,
        *,
        tenant_id: str,
        recipient: str,
        text: Optional[str] = None,
        media_url: Optional[str] = None,
        content_type: str = "text",
        supabase: Any = None,
    ) -> OutboundResult: ...

    def verify_signature(
        self, *, headers: dict, raw_body: bytes, tenant_id: str,
    ) -> bool: ...

    async def compliance_check(
        self,
        *,
        tenant_id: str,
        recipient_id: str,
        message_kind: str = "outbound",
        supabase: Any = None,
    ) -> ComplianceVerdict: ...

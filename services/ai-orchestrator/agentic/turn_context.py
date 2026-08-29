"""TurnContext — B-2 Fase 0 (2026-08-28; formulación `bot-dispatcher-reengineering`
validada por founder).

UNA sola lectura por entidad al inicio del turno (conversación, contacto,
history, cart), compartida por los bloques del dispatcher. Antes de este
módulo cada bloque hacía su propio `supabase.table(...)` (INV-B §2, medido:
`conversations` ×7, `messages` ×5-6, `contacts` ×2 y el lookup del cart
copiado inline ×9 por turno).

Contrato v0 (SIN cambio de comportamiento):

  • conv/contact/history se leen UNA vez al inicio del turno y no cambian
    salvo mutación conocida (el consent block actualiza `ctx.contact` en el
    sitio, igual que hacía con la variable local `contact`).
  • `cart` es REFRESCABLE: las mutaciones inline del dispatcher pasan por
    `update_cart_fields` (caché coherente sin re-leer, equivalente al
    read-fresco que hacía el bloque siguiente); las mutaciones externas al
    ctx (tools del loop LLM) se cubren con `get_cart(refresh=True)`.
  • Lo que exige verdad POST-mutación al FINAL del turno sigue leyendo fresco
    FUERA del ctx (su extracción es Fase 1-2 del plan B-2): el embudo de
    envío (`_send_outbound_text`), los gates de `dispatch_message`, el
    race-gate de operador y los invariants del pipeline.
  • Los lookups con filtro divergente del canónico [open, checkout] NO se
    migran en v0 (son scope de sus handlers, Fase 2-3): el `cart_has_items`
    del shipping intent y el abandon-check del cancel usan solo
    `status='open'`; el recipient intent usa `get_cart_with_items` (shape con
    items) y puede CREAR el cart — por eso tras su mutación se llama
    `refresh_cart()`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# SELECT canónico de la conversación del turno: status + agentic_state (los
# consume el resolver de estado / badge) + customer_phone (contacto + envío).
_CONV_SELECT = "status, agentic_state, customer_phone"
# Defensa espejo del resolver de estado: si la columna agentic_state aún no
# existe en este ambiente (migración pendiente), reintenta sin ella.
_CONV_SELECT_FALLBACK = "status, customer_phone"

# SELECT canónico del cart del turno: superset de lo que consumen el resolver
# de estado (vía build_context_from_records) y los lookups inline del
# dispatcher que SÍ comparten el filtro canónico [open, checkout]
# (payment-availability, COD intent, cupón, COD post-LLM).
_CART_SELECT = (
    # Columnas del resolver de estado (test J-3 exige requires_requote en el
    # SELECT canónico — ver tests/agentic/test_j3_fsm_wiring.py).
    "id, status, payment_method, shipping_cents, shipping_meta, "
    "converted_order_id, requires_requote, "
    # Columnas del bloque de cupón (totales + cupón aplicado).
    "subtotal_cents, total_cents, coupon_id, coupon_code, discount_cents"
)


@dataclass
class TurnContext:
    """Snapshot del inicio del turno + acceso refrescable al cart.

    Los campos `conversation`/`contact`/`history` son los MISMOS dicts/listas
    que antes producían los helpers sueltos (idéntica forma, idéntico contenido
    — los bloques consumidores no distinguen la fuente).
    """

    supabase: Any
    tenant_id: str
    conversation_id: str
    message_id: str
    conversation: dict = field(default_factory=dict)
    # False cuando la conversación NO existe en DB (el resolver de estado
    # preserva el comportamiento de hoy ante ese caso: retorna None → el turno
    # cae al prompt monolito V2).
    conversation_found: bool = False
    customer_phone: Optional[str] = None
    history: list = field(default_factory=list)
    contact_id: Optional[str] = None
    contact: dict = field(default_factory=dict)
    _cart: Optional[dict] = field(default=None, repr=False)
    _cart_loaded: bool = field(default=False, repr=False)
    _contact_loaded: bool = field(default=False, repr=False)
    _history_loaded: bool = field(default=False, repr=False)

    # ── Carga del turno en DOS tiempos (B-2 Fase 1) ─────────────────────────
    #
    # El ctx nace en `dispatch_message` (ANTES de los gates) con SOLO la
    # lectura de la conversación (`for_gates` — 1 query, la misma que el skip
    # gate ya hacía): los gates legales la comparten en vez de re-leer.
    # El path agentic completa la carga con `ensure_core()` (upsert contact +
    # fetch contact + history). `load()` = for_gates + ensure_core (compat con
    # el call site de Fase 0).

    @classmethod
    def for_gates(
        cls,
        supabase: Any,
        *,
        tenant_id: str,
        conversation_id: str,
        message_id: str,
    ) -> "TurnContext":
        """Crea el ctx con la conversación leída (1 query — compartida por los
        gates y el path agentic). Sync: los gates son síncronos."""
        ctx = cls(
            supabase=supabase, tenant_id=tenant_id,
            conversation_id=conversation_id, message_id=message_id,
        )
        ctx._read_conversation()
        return ctx

    def _read_conversation(self) -> None:
        """Lee la conversación del turno (status + agentic_state + phone) UNA
        vez, con defensa espejo del resolver de estado (fallback sin
        agentic_state si la columna aún no existe en este ambiente)."""
        try:
            res = (
                self.supabase.table("conversations")
                .select(_CONV_SELECT)
                .eq("id", self.conversation_id)
                .eq("tenant_id", self.tenant_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            self.conversation = rows[0] if rows else {}
            self.conversation_found = bool(rows)
        except Exception:
            try:
                res = (
                    self.supabase.table("conversations")
                    .select(_CONV_SELECT_FALLBACK)
                    .eq("id", self.conversation_id)
                    .eq("tenant_id", self.tenant_id)
                    .limit(1)
                    .execute()
                )
                rows = res.data or []
                self.conversation = rows[0] if rows else {}
                self.conversation_found = bool(rows)
            except Exception as exc:
                # Fail-open como los gates de hoy: sin conv row el turno sigue
                # (el resolver de estado degradará a None → monolito V2).
                logger.warning(
                    "[TURN_CONTEXT] fallo leyendo conversations conv=%s: %s",
                    self.conversation_id[:8], exc,
                )
                self.conversation = {}
                self.conversation_found = False
        # Misma normalización que `_get_conversation_customer_phone`.
        _phone_raw = self.conversation.get("customer_phone")
        self.customer_phone = (
            str(_phone_raw).strip() or None if _phone_raw is not None else None
        )

    async def ensure_core(self) -> "TurnContext":
        """Completa la carga del path agentic: upsert de contacto heredado
        (write incondicional — paridad con el flujo previo) → fetch del
        contacto → history. Idempotente: si un gate ya cargó el contacto, no
        re-lee salvo que el upsert pudo crearlo (contacto vacío previo)."""
        from orchestrator import (
            _fetch_contact_for_phone,
            _get_conversation_history,
        )

        # Upsert de contacto heredado (rev. 108 — paridad V1): crea el contact
        # si no existe para que record_consent/save_pii no fallen con
        # NO_CONTACT. consent_given=False default — consent explícito después.
        if self.customer_phone:
            try:
                self.supabase.table("contacts").upsert(
                    {
                        "tenant_id": self.tenant_id,
                        "phone": self.customer_phone,
                        "shipping_phone": self.customer_phone,
                        "consent_given": False,
                    },
                    on_conflict="tenant_id,phone",
                    ignore_duplicates=True,
                ).execute()
            except Exception as exc:
                logger.warning(
                    "[AGENTIC_DISPATCH] contact upsert falló phone=%s: %s",
                    self.customer_phone, exc,
                )

        # Contacto (misma lectura de siempre, vía helper canónico). Si un gate
        # ya lo cargó vacío (no existía) y el upsert pudo crearlo, re-leer.
        if self.customer_phone and (
            not self._contact_loaded or not self.contact
        ):
            self.contact_id, self.contact = _fetch_contact_for_phone(
                self.supabase, self.tenant_id, self.customer_phone,
            )
            self._contact_loaded = True

        # History (últimos CONVERSATION_HISTORY_LIMIT, orden cronológico;
        # incluye content_type desde B-2 Fase 0 para derivar el recent-10 del
        # image-request sin una segunda lectura).
        if not self._history_loaded:
            self.history = await _get_conversation_history(
                self.supabase, self.tenant_id, self.conversation_id,
            )
            self._history_loaded = True
        return self

    @classmethod
    async def load(
        cls,
        supabase: Any,
        *,
        tenant_id: str,
        conversation_id: str,
        message_id: str,
    ) -> "TurnContext":
        """Carga completa (conv + contact + history) — = for_gates +
        ensure_core. Compat con el call site original de Fase 0."""
        ctx = cls.for_gates(
            supabase, tenant_id=tenant_id, conversation_id=conversation_id,
            message_id=message_id,
        )
        return await ctx.ensure_core()

    # ── Cart del turno (refrescable) ────────────────────────────────────────

    def get_cart(self, *, refresh: bool = False) -> Optional[dict]:
        """Cart open/checkout más reciente + `items_count` + derivaciones del
        resolver (`carrier_code`, `payment_link`) — UNA lectura por turno,
        salvo refresh explícito tras mutaciones externas al ctx (loop LLM).

        Las excepciones de lectura PROPAGAN (los bloques consumidores ya tienen
        su try/except — paridad con el read inline de hoy; en la resolución de
        estado el caller lo envuelve para degradar a monolito V2).
        """
        if self._cart_loaded and not refresh:
            return self._cart
        self._cart = self._fetch_cart()
        self._cart_loaded = True
        return self._cart

    def refresh_cart(self) -> Optional[dict]:
        """Re-lee el cart (tras mutaciones que el ctx no vio pasar)."""
        return self.get_cart(refresh=True)

    def update_cart_fields(self, cart_id: str, fields: dict) -> None:
        """UPDATE inline del dispatcher + coherencia de caché en el sitio.

        El snapshot del turno refleja la mutación SIN re-leer (equivalente al
        read-fresco que hacía el bloque siguiente tras la mutación previa).
        Lanza igual que el update inline de hoy (el caller conserva su
        try/except).
        """
        (
            self.supabase.table("conversation_carts")
            .update(fields)
            .eq("id", cart_id)
            .eq("tenant_id", self.tenant_id)
            .execute()
        )
        if self._cart is not None and self._cart.get("id") == cart_id:
            self._cart.update(fields)

    def _fetch_cart(self) -> Optional[dict]:
        row = (
            self.supabase.table("conversation_carts")
            .select(_CART_SELECT)
            .eq("conversation_id", self.conversation_id)
            .eq("tenant_id", self.tenant_id)
            .in_("status", ["open", "checkout"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        cart = (row.data or [None])[0]
        if not cart:
            return None
        # Derivaciones del resolver de estado (misma lógica que el bloque
        # inline previo en `_resolve_and_persist_agentic_state`).
        _meta = cart.get("shipping_meta") or {}
        cart["carrier_code"] = _meta.get("carrier") or None
        cart["payment_link"] = None
        _items_count_row = (
            self.supabase.table("conversation_cart_items")
            .select("id", count="exact", head=True)
            .eq("cart_id", cart["id"])
            .eq("tenant_id", self.tenant_id)
            .execute()
        )
        cart["items_count"] = int(getattr(_items_count_row, "count", 0) or 0)
        if cart.get("status") == "checkout" and cart.get("converted_order_id"):
            cart["payment_link"] = "checkout"
        return cart

    # ── Derivados del history (sin re-lectura) ──────────────────────────────

    def last_bot_outbound(self) -> str:
        """Último outbound del bot según el history del turno (ventana de 25).

        Sustituye la lectura dedicada `messages ... direction=outbound limit 1`
        de los bloques consent/carrier: mismo resultado mientras el último
        outbound esté dentro de la ventana — garantía práctica en el path
        agentic, donde todo turno servido termina en outbound (los estados de
        silencio — takeover/closed/opted_out/cortesía — ni siquiera llegan
        aquí: los gates de `dispatch_message` los cortan antes).
        """
        for msg in reversed(self.history or []):
            if isinstance(msg, dict) and msg.get("direction") == "outbound":
                return str(msg.get("content") or "")
        return ""

    def recent_messages_desc(self, limit: int = 10) -> list:
        """Los N mensajes más recientes en orden DESC (más nuevo primero).

        Derivados del history del turno (misma ventana) — sustituye la lectura
        incondicional de `messages` que el image-request hacía en TODO turno de
        texto (INV-B §2: lectura #3 de messages, hoy antes de cualquier regex
        barata).
        """
        return [
            m for m in reversed(self.history or []) if isinstance(m, dict)
        ][:limit]

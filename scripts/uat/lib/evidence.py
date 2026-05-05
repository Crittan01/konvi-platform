"""Plantilla de evidencia para UAT controlado uno-a-uno.

Captura un snapshot completo del estado tras correr un escenario:
  • Transcript turn-by-turn (inbound + outbound) con timestamps.
  • Cart-as-SoT real (cart row + items + cart_events).
  • Orders con order_items + payments.
  • Audit trail Habeas Data (contact_data_audit).
  • Contact final state (consent, name, email, doc, address, shipping_phone).
  • review_queue rows si los hay.
  • Métricas: turns, elapsed, latencias por turno (best-effort).

Uso desde un escenario o desde análisis post-corrida:
    from lib.evidence import capture_evidence
    ev = capture_evidence(phone="...", tenant_id="...")
    print(ev.markdown_summary())  # tabla resumida
    ev.write_json("/tmp/uat_S01_new.json")  # snapshot completo
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from supabase import Client


@dataclass
class TurnEvidence:
    seq: int
    timestamp: str
    direction: str          # 'inbound' | 'outbound'
    content_type: str
    content: str
    media_url: Optional[str] = None
    meta_message_id: Optional[str] = None
    processing_status: Optional[str] = None


@dataclass
class CartEvidence:
    cart_id: Optional[str] = None
    status: Optional[str] = None
    version: Optional[int] = None
    subtotal_cents: int = 0
    shipping_cents: int = 0
    total_cents: int = 0
    requires_requote: bool = False
    shipping_meta: dict = field(default_factory=dict)
    items: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


@dataclass
class OrderEvidence:
    id: str
    status: str
    total_amount: float
    shipping_cost: float
    notes: str
    items: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)


@dataclass
class ContactEvidence:
    id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    phone: Optional[str] = None
    shipping_phone: Optional[str] = None
    address: dict = field(default_factory=dict)
    consent_given: bool = False
    consent_source: Optional[str] = None
    consent_at: Optional[str] = None
    consent_revoked_at: Optional[str] = None


@dataclass
class ScenarioEvidence:
    """Snapshot completo del estado post-escenario."""
    captured_at: str
    phone: str
    tenant_id: str
    conversation_id: Optional[str] = None
    conversation_status: Optional[str] = None
    turns: list[TurnEvidence] = field(default_factory=list)
    cart: CartEvidence = field(default_factory=CartEvidence)
    orders: list[OrderEvidence] = field(default_factory=list)
    contact: ContactEvidence = field(default_factory=ContactEvidence)
    audit_log: list[dict] = field(default_factory=list)
    review_queue: list[dict] = field(default_factory=list)

    def markdown_summary(self) -> str:
        """Resumen humano-legible (≤30 líneas) para revisar a ojo."""
        lines = []
        lines.append(f"## Evidencia · phone={self.phone} · {self.captured_at}")
        lines.append("")
        lines.append(f"- Conv: `{(self.conversation_id or '')[:8]}` status={self.conversation_status}")
        lines.append(f"- Turns: {len(self.turns)} ({sum(1 for t in self.turns if t.direction == 'inbound')} inb / {sum(1 for t in self.turns if t.direction == 'outbound')} out)")
        lines.append("")
        lines.append("### Contact")
        c = self.contact
        lines.append(f"- name={c.name!r} consent={c.consent_given} email={c.email}")
        lines.append(f"- doc={c.document_type} {c.document_number} phone={c.phone} ship_phone={c.shipping_phone}")
        if c.address:
            lines.append(f"- address: {c.address.get('street')} — {c.address.get('city')} ({c.address.get('building_type')})")
        lines.append("")
        lines.append(f"### Cart `{(self.cart.cart_id or '')[:8]}` status={self.cart.status}")
        lines.append(f"- subtotal={self.cart.subtotal_cents/100:,.0f} ship={self.cart.shipping_cents/100:,.0f} total={self.cart.total_cents/100:,.0f} requires_requote={self.cart.requires_requote}")
        for it in self.cart.items:
            lines.append(f"  - {it.get('quantity')}x prod={(it.get('product_id') or '')[:8]} var={(it.get('variation_id') or '')[:8]} unit={(it.get('unit_price_cents') or 0)/100:,.0f}")
        if self.cart.events:
            lines.append(f"- {len(self.cart.events)} cart_events: {[e.get('event_type') for e in self.cart.events]}")
        lines.append("")
        lines.append(f"### Orders ({len(self.orders)})")
        for o in self.orders:
            lines.append(f"- order={o.id[:8]} status={o.status} total={o.total_amount} ship={o.shipping_cost} ({len(o.items)} items, {len(o.payments)} payments)")
            for it in o.items:
                lines.append(f"  - {it.get('quantity')}x {it.get('title','?')[:40]} @ {it.get('unit_price','?')}")
            for p in o.payments:
                lines.append(f"  - payment status={p.get('status')} wompi={p.get('wompi_status')} amount_cents={p.get('amount_in_cents')}")
        lines.append("")
        if self.audit_log:
            lines.append(f"### Audit log ({len(self.audit_log)})")
            for a in self.audit_log[:8]:
                lines.append(f"  - {a.get('event','?')} src={a.get('source','?')} at={(a.get('created_at') or '')[:19]}")
        if self.review_queue:
            lines.append(f"### review_queue ({len(self.review_queue)})")
            for r in self.review_queue[:5]:
                lines.append(f"  - id={(r.get('id') or '')[:8]} fsm_state={r.get('fsm_state')}")
        lines.append("")
        lines.append("### Transcript")
        for t in self.turns:
            arrow = "→" if t.direction == "outbound" else "←"
            preview = (t.content or "").replace("\n", " ⏎ ")[:140]
            lines.append(f"- T{t.seq:02d} {t.timestamp[11:19]} {arrow} {t.direction[:3]}: {preview}")
        return "\n".join(lines)

    def write_json(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")


def _to_int(v, default=0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def capture_evidence(
    *, phone: str, tenant_id: str, supabase: Optional[Client] = None,
) -> ScenarioEvidence:
    """Construye ScenarioEvidence consultando todas las tablas relevantes.

    Idempotente: solo lee. NO modifica nada.
    """
    if supabase is None:
        import sys
        sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/scripts/uat")
        from e2e_chat import _supabase  # type: ignore
        supabase = _supabase()

    ev = ScenarioEvidence(
        captured_at=datetime.utcnow().isoformat() + "Z",
        phone=phone,
        tenant_id=tenant_id,
    )

    # 1. Find current conversation (most recent for this phone/tenant)
    convs = (
        supabase.table("conversations")
        .select("id, status, customer_phone, created_at")
        .eq("customer_phone", phone)
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if convs.data:
        conv = convs.data[0]
        ev.conversation_id = conv["id"]
        ev.conversation_status = conv["status"]

        # 2. Messages (transcript)
        msgs = (
            supabase.table("messages")
            .select(
                "direction, content, content_type, media_url, "
                "meta_message_id, processing_status, created_at"
            )
            .eq("conversation_id", ev.conversation_id)
            .order("created_at", desc=False)
            .execute()
        )
        for i, m in enumerate(msgs.data or []):
            ev.turns.append(TurnEvidence(
                seq=i,
                timestamp=m.get("created_at") or "",
                direction=str(m.get("direction") or ""),
                content_type=str(m.get("content_type") or ""),
                content=str(m.get("content") or ""),
                media_url=m.get("media_url"),
                meta_message_id=m.get("meta_message_id"),
                processing_status=m.get("processing_status"),
            ))

        # 3. Cart (open or most recent)
        carts = (
            supabase.table("conversation_carts")
            .select("*")
            .eq("conversation_id", ev.conversation_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if carts.data:
            c = carts.data[0]
            ev.cart.cart_id = c["id"]
            ev.cart.status = c.get("status")
            ev.cart.version = c.get("version")
            ev.cart.subtotal_cents = _to_int(c.get("subtotal_cents"))
            ev.cart.shipping_cents = _to_int(c.get("shipping_cents"))
            ev.cart.total_cents = _to_int(c.get("total_cents"))
            ev.cart.requires_requote = bool(c.get("requires_requote"))
            ev.cart.shipping_meta = c.get("shipping_meta") or {}

            # cart items
            items = (
                supabase.table("conversation_cart_items")
                .select("variation_id, product_id, quantity, unit_price_cents, created_at")
                .eq("cart_id", ev.cart.cart_id)
                .order("created_at")
                .execute()
            )
            ev.cart.items = items.data or []

            # cart events (auditoría de mutaciones)
            events = (
                supabase.table("cart_events")
                .select("event_type, event_payload, triggered_by, correlation_id, created_at")
                .eq("cart_id", ev.cart.cart_id)
                .order("created_at")
                .execute()
            )
            ev.cart.events = events.data or []

    # 4. Contact
    digits = phone.lstrip("+")
    contacts = (
        supabase.table("contacts")
        .select("*")
        .eq("tenant_id", tenant_id)
        .or_(f"phone.eq.{digits},phone.eq.+{digits}")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if contacts.data:
        c = contacts.data[0]
        ev.contact = ContactEvidence(
            id=c.get("id"),
            name=c.get("name"),
            email=c.get("email"),
            document_type=c.get("document_type"),
            document_number=c.get("document_number"),
            phone=c.get("phone"),
            shipping_phone=c.get("shipping_phone"),
            address=c.get("address") or {},
            consent_given=bool(c.get("consent_given")),
            consent_source=c.get("consent_source"),
            consent_at=c.get("consent_at"),
            consent_revoked_at=c.get("consent_revoked_at"),
        )

        # 5. Orders (linked to this contact)
        orders_res = (
            supabase.table("orders")
            .select("*")
            .eq("contact_id", ev.contact.id)
            .order("created_at", desc=True)
            .execute()
        )
        for o in (orders_res.data or []):
            order_ev = OrderEvidence(
                id=o["id"],
                status=str(o.get("status") or ""),
                total_amount=float(o.get("total_amount") or 0),
                shipping_cost=float(o.get("shipping_cost") or 0),
                notes=str(o.get("notes") or ""),
            )
            items = (
                supabase.table("order_items")
                .select("title, quantity, unit_price, product_id, variation_id")
                .eq("order_id", o["id"])
                .execute()
            )
            order_ev.items = items.data or []
            payments = (
                supabase.table("payments")
                .select("status, wompi_status, amount_in_cents, wompi_link_id, wompi_txn_id, checkout_url")
                .eq("order_id", o["id"])
                .execute()
            )
            order_ev.payments = payments.data or []
            ev.orders.append(order_ev)

        # 6. Audit log
        try:
            audit = (
                supabase.table("contact_data_audit")
                .select("event, source, created_at, before_data, after_data")
                .eq("contact_id", ev.contact.id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            ev.audit_log = audit.data or []
        except Exception:
            pass

    # 7. review_queue
    if ev.conversation_id:
        try:
            rq = (
                supabase.table("review_queue")
                .select("*")
                .eq("conversation_id", ev.conversation_id)
                .execute()
            )
            ev.review_queue = rq.data or []
        except Exception:
            pass

    return ev


__all__ = ["ScenarioEvidence", "capture_evidence"]

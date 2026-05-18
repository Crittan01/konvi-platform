"""Vacía la conversación de un teléfono específico, COHERENTEMENTE.

Sem 7 F2 cierre — testing tool actualizado para no dejar datos huérfanos
en DB (orders/carts/payments/shipments). Antes el wipe sólo borraba
`conversations` (CASCADE → messages + reads), dejando orders pendientes
sin conv asociada, lo cual confundía al bot en pruebas posteriores
("hay orden pendiente pero no carrito, no entiendo").

Uso típico:
    python3.11 scripts/wipe_conversation.py --phone +573125835649 --yes

Opciones:
    --phone <num>       Teléfono en formato E.164 (default: +573125835649).
    --tenant-id <uuid>  Restringe a un tenant. Si se omite, opera sobre TODAS
                        las conversaciones del número (todos los tenants).
    --keep-conversation Borra solo messages + conversation_reads + cart + items,
                        conserva el row de conversations (resetea status a
                        bot_active). Orders/payments/shipments se borran igual
                        para coherencia.
    --yes               Salta la confirmación interactiva.

Lee credenciales Supabase desde `.env` en la raíz del repo.
Requiere SUPABASE_SERVICE_ROLE_KEY (RLS bypass).

Recursos borrados por conversación (full_delete):
    1. payments        (donde conversation_id matche)
    2. shipments       (donde conversation_id matche, vía orders)
    3. cart_events     (vía conversation_carts.id)
    4. conversation_cart_items (vía conversation_carts.id)
    5. conversation_carts (donde conversation_id matche)
    6. order_items     (vía orders.id)
    7. orders          (donde conversation_id matche)
    8. messages        (CASCADE desde conversations)
    9. conversation_reads (CASCADE desde conversations)
    10. conversations  (la última)

NOTA: este script es testing-only. NO usar en producción real — borra
órdenes y pagos sin preservar audit. Si necesitás cancelar una orden en
producción, usá un endpoint de cancelación que respete lifecycle.

Multi-tenant safety: si NO se pasa --tenant-id, el script lista todas las
conversaciones encontradas para el número y exige confirmación explícita.
"""
import argparse
import os
import sys
from typing import Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
ENV_PATH = os.path.join(REPO_ROOT, ".env")


def _load_env() -> dict:
    creds: dict = {}
    if not os.path.exists(ENV_PATH):
        print(f"ERROR: no encontré {ENV_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds


def _phone_variants(raw: str) -> list[str]:
    """Genera variantes razonables del teléfono para cubrir cómo lo guarda
    Meta vs cómo lo persisten distintos paths del backend.
    """
    digits = "".join(c for c in raw if c.isdigit())
    plus = f"+{digits}"
    space57 = f"+57 {digits[2:]}" if digits.startswith("57") else plus
    out = [raw, plus, digits, space57]
    seen = set()
    deduped = []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped


def _find_conversations(supabase, phone: str, tenant_id: Optional[str]) -> list[dict]:
    variants = _phone_variants(phone)
    q = supabase.table("conversations").select("id, tenant_id, customer_phone, status, last_interaction_at, created_at")
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    or_clause = ",".join(f"customer_phone.eq.{v}" for v in variants)
    if hasattr(q, "or_"):
        q = q.or_(or_clause)
    res = q.order("created_at", desc=True).execute()
    return list(res.data or [])


def _count_table(supabase, table: str, column: str, value: str) -> int:
    res = (
        supabase.table(table)
        .select("id" if table not in {"conversation_reads"} else "user_id", count="exact", head=True)
        .eq(column, value)
        .execute()
    )
    return int(getattr(res, "count", None) or 0)


def _collect_conv_resources(supabase, conversation_id: str) -> dict:
    """Lee IDs de orders y carts para esta conv — necesarios para borrar
    hijos (order_items, cart_items, shipments) ANTES de los padres.
    """
    orders_res = (
        supabase.table("orders")
        .select("id")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    order_ids = [r["id"] for r in (orders_res.data or [])]

    carts_res = (
        supabase.table("conversation_carts")
        .select("id")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    cart_ids = [r["id"] for r in (carts_res.data or [])]

    return {"order_ids": order_ids, "cart_ids": cart_ids}


def _safe_delete(supabase, table: str, column: str, value, *, in_list: bool = False) -> int:
    """Intenta DELETE. Si la tabla no existe o falla, retorna 0 silencioso.
    Útil cuando una migración aún no creó la tabla en este ambiente."""
    try:
        q = supabase.table(table).delete()
        if in_list:
            if not value:
                return 0
            q = q.in_(column, value)
        else:
            q = q.eq(column, value)
        res = q.execute()
        return len(res.data or [])
    except Exception as exc:
        # Tabla puede no existir aún (migración pendiente) — log debug
        print(f"    [skip] {table}.{column}: {exc}", file=sys.stderr)
        return 0


def _wipe_one(supabase, conv: dict, *, keep_conversation: bool) -> dict:
    """Borra COHERENTEMENTE todos los recursos de una conversación.

    Orden (hijos antes que padres) para no depender de FKs CASCADE:
      1. payments (FK orders)
      2. shipments (FK orders)
      3. cart_events (FK conversation_carts)
      4. conversation_cart_items (FK conversation_carts)
      5. conversation_carts (FK conversations)
      6. order_items (FK orders)
      7. orders (FK conversations)
      8. messages + conversation_reads (FK conversations, CASCADE OK)
      9. conversations (la última)
    """
    cid = conv["id"]
    summary = {"conversation_id": cid, "tenant_id": conv["tenant_id"]}
    res = _collect_conv_resources(supabase, cid)
    order_ids = res["order_ids"]
    cart_ids = res["cart_ids"]

    # ── 1-2. payments + shipments (dependen de orders) ─────────────────
    summary["payments_deleted"] = _safe_delete(
        supabase, "payments", "order_id", order_ids, in_list=True,
    ) if order_ids else 0
    summary["shipments_deleted"] = _safe_delete(
        supabase, "shipments", "order_id", order_ids, in_list=True,
    ) if order_ids else 0

    # ── 3-4. cart_events + cart_items (dependen de conversation_carts) ─
    summary["cart_events_deleted"] = _safe_delete(
        supabase, "cart_events", "cart_id", cart_ids, in_list=True,
    ) if cart_ids else 0
    summary["cart_items_deleted"] = _safe_delete(
        supabase, "conversation_cart_items", "cart_id", cart_ids, in_list=True,
    ) if cart_ids else 0

    # ── 5. conversation_carts ──────────────────────────────────────────
    summary["carts_deleted"] = _safe_delete(
        supabase, "conversation_carts", "conversation_id", cid,
    )

    # ── 6. order_items (FK orders) ──────────────────────────────────────
    summary["order_items_deleted"] = _safe_delete(
        supabase, "order_items", "order_id", order_ids, in_list=True,
    ) if order_ids else 0

    # ── 7. orders ──────────────────────────────────────────────────────
    summary["orders_deleted"] = _safe_delete(
        supabase, "orders", "conversation_id", cid,
    )

    if keep_conversation:
        # Limpiar messages + reads, mantener conversation con status reset.
        msg_del = supabase.table("messages").delete().eq("conversation_id", cid).execute()
        reads_del = supabase.table("conversation_reads").delete().eq("conversation_id", cid).execute()
        upd = (
            supabase.table("conversations")
            .update({"status": "bot_active", "last_interaction_at": None})
            .eq("id", cid)
            .execute()
        )
        summary["mode"] = "keep_conversation"
        summary["messages_deleted"] = len(msg_del.data or [])
        summary["reads_deleted"] = len(reads_del.data or [])
        summary["state_reset"] = bool(upd.data)
    else:
        # Borrar la conversation entera. CASCADE FK limpia messages + reads.
        cdel = supabase.table("conversations").delete().eq("id", cid).execute()
        summary["mode"] = "full_delete"
        summary["conversations_deleted"] = len(cdel.data or [])
    return summary


def main():
    ap = argparse.ArgumentParser(description="Vacía la conversación de un teléfono coherentemente.")
    ap.add_argument("--phone", default="+573125835649")
    ap.add_argument("--tenant-id", default=None)
    ap.add_argument("--keep-conversation", action="store_true",
                    help="Conserva la conversation; limpia el resto (cart/orders/etc).")
    ap.add_argument("--yes", action="store_true", help="Salta confirmación interactiva.")
    args = ap.parse_args()

    creds = _load_env()
    url = creds.get("NEXT_PUBLIC_SUPABASE_URL")
    key = creds.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERROR: falta NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en .env",
              file=sys.stderr)
        sys.exit(1)

    from supabase import create_client
    supabase = create_client(url, key)

    convs = _find_conversations(supabase, args.phone, args.tenant_id)
    if not convs:
        scope = f"tenant {args.tenant_id}" if args.tenant_id else "todos los tenants"
        print(f"No hay conversaciones para {args.phone} en {scope}. Nada que hacer.")
        return

    print(f"\nConversaciones encontradas para {args.phone}"
          f"{' (tenant ' + args.tenant_id + ')' if args.tenant_id else ''}:\n")
    rows = []
    for c in convs:
        msgs = _count_table(supabase, "messages", "conversation_id", c["id"])
        reads = _count_table(supabase, "conversation_reads", "conversation_id", c["id"])
        carts = _count_table(supabase, "conversation_carts", "conversation_id", c["id"])
        orders = _count_table(supabase, "orders", "conversation_id", c["id"])
        rows.append((c, msgs, reads, carts, orders))
        print(
            f"  - conv={c['id'][:8]} tenant={c['tenant_id'][:8]} "
            f"phone={c.get('customer_phone')!r} status={c.get('status')}"
        )
        print(
            f"    msgs={msgs} reads={reads} carts={carts} orders={orders} "
            f"last_interaction={c.get('last_interaction_at')}"
        )

    mode = "keep_conversation" if args.keep_conversation else "full_delete"
    print(f"\nModo: {mode}")
    if mode == "full_delete":
        print(
            "Acción: DELETE coherente — payments + shipments + cart_events + "
            "cart_items + conversation_carts + order_items + orders + "
            "conversations (CASCADE messages + reads)."
        )
    else:
        print(
            "Acción: DELETE coherente — payments + shipments + cart_events + "
            "cart_items + conversation_carts + order_items + orders + "
            "messages + conversation_reads + UPDATE conversations "
            "status='bot_active'."
        )

    if not args.yes:
        ans = input("\n¿Continuar? [y/N] ").strip().lower()
        if ans not in {"y", "yes", "s", "si", "sí"}:
            print("Cancelado.")
            return

    print("\nEjecutando...")
    for c, _, _, _, _ in rows:
        try:
            r = _wipe_one(supabase, c, keep_conversation=args.keep_conversation)
            print(f"  OK conv={r['conversation_id'][:8]} → {r}")
        except Exception as exc:
            print(f"  ERROR conv={c['id'][:8]}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()

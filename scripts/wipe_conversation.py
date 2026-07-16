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


def _resolve_contact_id_for_phone(
    supabase, tenant_id: str, customer_phone: Optional[str],
) -> Optional[str]:
    """Lookup contact_id desde customer_phone — usado para encontrar
    huérfanos del contact tras borrar la conv específica.
    """
    if not customer_phone:
        return None
    variants = _phone_variants(customer_phone)
    try:
        q = (
            supabase.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
        )
        or_clause = ",".join(f"phone.eq.{v}" for v in variants)
        if hasattr(q, "or_"):
            q = q.or_(or_clause)
        res = q.limit(1).execute()
        rows = res.data or []
        return rows[0]["id"] if rows else None
    except Exception as exc:
        print(f"    [skip] contact lookup falló: {exc}", file=sys.stderr)
        return None


def _wipe_contact_orphans(
    supabase, tenant_id: str, contact_id: str, valid_conv_ids: set[str],
) -> dict:
    """Sem 7 F2 cierre — borra recursos huérfanos del contact: orders/carts
    cuya `conversation_id` ya NO existe en `conversations` (porque fueron
    borradas por wipes anteriores con script viejo que no las limpiaba).

    Sin esto, el bot al detectar cart_retake del contact ve órdenes
    cancelled huérfanas y dice "tenías Jabón Coco $18.000" persistente
    aún tras wipe.

    valid_conv_ids: set de conversation_ids que SIGUEN existiendo (no se
    deben tocar sus orders/carts).
    """
    summary: dict = {"orphan_orders_deleted": 0, "orphan_carts_deleted": 0}

    # 1. Identificar orders del contact con conversation_id no-válido (huérfano).
    try:
        orders_res = (
            supabase.table("orders")
            .select("id, conversation_id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .execute()
        )
        all_orders = orders_res.data or []
    except Exception as exc:
        print(f"    [skip] orphan orders lookup falló: {exc}", file=sys.stderr)
        all_orders = []

    orphan_order_ids = [
        o["id"] for o in all_orders
        if (o.get("conversation_id") not in valid_conv_ids)
    ]

    if orphan_order_ids:
        # Borrar dependientes hijos (payments + shipments + order_items) primero.
        _safe_delete(supabase, "payments", "order_id", orphan_order_ids, in_list=True)
        _safe_delete(supabase, "shipments", "order_id", orphan_order_ids, in_list=True)
        _safe_delete(supabase, "order_items", "order_id", orphan_order_ids, in_list=True)
        summary["orphan_orders_deleted"] = _safe_delete(
            supabase, "orders", "id", orphan_order_ids, in_list=True,
        )

    # 2. Identificar conversation_carts huérfanos del contact (mismo criterio).
    try:
        carts_res = (
            supabase.table("conversation_carts")
            .select("id, conversation_id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .execute()
        )
        all_carts = carts_res.data or []
    except Exception as exc:
        print(f"    [skip] orphan carts lookup falló: {exc}", file=sys.stderr)
        all_carts = []

    orphan_cart_ids = [
        c["id"] for c in all_carts
        if (c.get("conversation_id") not in valid_conv_ids)
    ]

    if orphan_cart_ids:
        # Borrar dependientes (cart_events + cart_items) primero.
        _safe_delete(supabase, "cart_events", "cart_id", orphan_cart_ids, in_list=True)
        _safe_delete(supabase, "conversation_cart_items", "cart_id", orphan_cart_ids, in_list=True)
        summary["orphan_carts_deleted"] = _safe_delete(
            supabase, "conversation_carts", "id", orphan_cart_ids, in_list=True,
        )

    return summary


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
      10. Sem 7 F2 cierre — orphan cleanup del contact: orders/carts del
          mismo contact cuya conversation_id ya no existe (huérfanos de
          wipes anteriores con script viejo). Sin esto, bot detecta
          órdenes históricas y dice "tenías X producto" persistente.
    """
    cid = conv["id"]
    tenant_id = conv["tenant_id"]
    summary = {"conversation_id": cid, "tenant_id": tenant_id}
    # Resolver contact_id ANTES de borrar la conv (necesario para orphan
    # cleanup post-delete).
    contact_id = _resolve_contact_id_for_phone(
        supabase, tenant_id, conv.get("customer_phone"),
    )
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

    # ── 10. Orphan cleanup del contact (Sem 7 F2 cierre). ─────────────
    # Tras borrar la conv, hay orders/carts del MISMO contact cuya
    # conversation_id ya no existe (huérfanos de wipes anteriores con
    # script viejo). Los identificamos y borramos para que el bot no
    # detecte cart histórico inexistente.
    if contact_id:
        try:
            remaining_convs_res = (
                supabase.table("conversations")
                .select("id")
                .eq("tenant_id", tenant_id)
                .execute()
            )
            valid_conv_ids = {
                r["id"] for r in (remaining_convs_res.data or [])
                if r.get("id")
            }
            orphan_summary = _wipe_contact_orphans(
                supabase, tenant_id, contact_id, valid_conv_ids,
            )
            summary.update(orphan_summary)
        except Exception as exc:
            print(f"    [skip] orphan cleanup falló: {exc}", file=sys.stderr)
    return summary


def main():
    ap = argparse.ArgumentParser(description="Vacía la conversación de un teléfono coherentemente.")
    ap.add_argument("--phone", default="+573125835649")
    ap.add_argument("--tenant-id", default=None)
    ap.add_argument("--keep-conversation", action="store_true",
                    help="Conserva la conversation; limpia el resto (cart/orders/etc).")
    ap.add_argument("--purge-contact", action="store_true",
                    help=("HARD-DELETE en cascade: borra contact + conversations + "
                          "carts + orders + payments + shipments + messages. "
                          "Usa el helper compartido `lib.contact_cleanup.purge_contact_completely`. "
                          "Para reset total durante testing."))
    ap.add_argument("--yes", action="store_true", help="Salta confirmación interactiva.")
    args = ap.parse_args()

    creds = _load_env()
    # D.4 cutover dev/prod: rechaza correr este wipe testing-only contra prod
    # salvo override explícito KONVI_ALLOW_PROD=1 (ver scripts/_env_guard.py).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _env_guard import assert_not_prod
    assert_not_prod(creds, action="wipe_conversation")
    url = creds.get("NEXT_PUBLIC_SUPABASE_URL")
    # A0.2c: SUPABASE_SECRET_KEY canónico con fallback legacy SERVICE_ROLE_KEY.
    key = creds.get("SUPABASE_SECRET_KEY") or creds.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERROR: falta NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY legacy) en .env",
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
    if args.purge_contact:
        # Sem 7 F2 cierre 2026-05-19 — usar helper compartido para purge total
        # del contact (lo mismo que invoca el endpoint API y, vía éste, el UI
        # delete físico desde el Tenant Console).
        # Path setup para import desde services/api/lib.
        sys.path.insert(
            0,
            str(Path(__file__).resolve().parents[1] / "services/api"),
        )
        from lib.contact_cleanup import purge_contact_completely

        # Resolver contact_ids únicos desde las conversations encontradas.
        contact_ids_done: set[str] = set()
        for c, _, _, _, _ in rows:
            tenant_id = c["tenant_id"]
            contact_id = _resolve_contact_id_for_phone(
                supabase, tenant_id, c.get("customer_phone"),
            )
            if not contact_id or contact_id in contact_ids_done:
                continue
            try:
                r = purge_contact_completely(supabase, tenant_id, contact_id)
                print(f"  OK contact={contact_id[:8]} tenant={tenant_id[:8]} → {r}")
                contact_ids_done.add(contact_id)
            except Exception as exc:
                print(f"  ERROR contact={contact_id[:8]}: {exc}", file=sys.stderr)
    else:
        for c, _, _, _, _ in rows:
            try:
                r = _wipe_one(supabase, c, keep_conversation=args.keep_conversation)
                print(f"  OK conv={r['conversation_id'][:8]} → {r}")
            except Exception as exc:
                print(f"  ERROR conv={c['id'][:8]}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()

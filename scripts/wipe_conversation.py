"""Vacía la conversación de un teléfono específico.

Uso típico:
    python3.11 scripts/wipe_conversation.py --phone +573125835649

Opciones:
    --phone <num>       Teléfono en formato E.164 (default: +573125835649).
    --tenant-id <uuid>  Restringe a un tenant. Si se omite, opera sobre TODAS
                        las conversaciones del número (todos los tenants).
    --keep-conversation Borra solo messages + conversation_reads, conserva
                        el row de conversations (resetea status a bot_active).
    --yes               Salta la confirmación interactiva.

Lee credenciales Supabase desde `.env` en la raíz del repo.
Requiere SUPABASE_SERVICE_ROLE_KEY (RLS bypass).

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


def _count_messages(supabase, conversation_id: str) -> int:
    res = (
        supabase.table("messages")
        .select("id", count="exact")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    return int(getattr(res, "count", None) or len(res.data or []))


def _count_reads(supabase, conversation_id: str) -> int:
    res = (
        supabase.table("conversation_reads")
        .select("user_id", count="exact")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    return int(getattr(res, "count", None) or len(res.data or []))


def _wipe_one(supabase, conv: dict, *, keep_conversation: bool) -> dict:
    cid = conv["id"]
    summary = {"conversation_id": cid, "tenant_id": conv["tenant_id"]}

    if keep_conversation:
        # Borrar mensajes + reads. Mantener conversation y resetear estado.
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
        # Borrar la conversation entera. CASCADE limpia messages + reads.
        cdel = supabase.table("conversations").delete().eq("id", cid).execute()
        summary["mode"] = "full_delete"
        summary["conversations_deleted"] = len(cdel.data or [])
    return summary


def main():
    ap = argparse.ArgumentParser(description="Vacía la conversación de un teléfono.")
    ap.add_argument("--phone", default="+573125835649")
    ap.add_argument("--tenant-id", default=None)
    ap.add_argument("--keep-conversation", action="store_true",
                    help="Conserva la conversation; solo limpia messages + reads + reset status.")
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
        msgs = _count_messages(supabase, c["id"])
        reads = _count_reads(supabase, c["id"])
        rows.append((c, msgs, reads))
        print(
            f"  - conv={c['id'][:8]} tenant={c['tenant_id'][:8]} "
            f"phone={c.get('customer_phone')!r} status={c.get('status')} "
            f"mensajes={msgs} reads={reads} last_interaction={c.get('last_interaction_at')}"
        )

    mode = "keep_conversation" if args.keep_conversation else "full_delete"
    print(f"\nModo: {mode}")
    if mode == "full_delete":
        print("Acción: DELETE conversations (CASCADE borra messages + reads).")
    else:
        print("Acción: DELETE messages + DELETE conversation_reads + UPDATE status='bot_active'.")

    if not args.yes:
        ans = input("\n¿Continuar? [y/N] ").strip().lower()
        if ans not in {"y", "yes", "s", "si", "sí"}:
            print("Cancelado.")
            return

    print("\nEjecutando...")
    for c, _, _ in rows:
        try:
            r = _wipe_one(supabase, c, keep_conversation=args.keep_conversation)
            print(f"  OK conv={r['conversation_id'][:8]} → {r}")
        except Exception as exc:
            print(f"  ERROR conv={c['id'][:8]}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()

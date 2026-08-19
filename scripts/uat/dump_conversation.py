"""Vuelca la conversación de un teléfono a un archivo de log para UAT/post-mortem.

Uso típico:
    python3.11 scripts/uat/dump_conversation.py --phone +573125835649

Salida por defecto:
    scripts/uat/logs/conversation_<phone>_<YYYYMMDD-HHMMSS>.log

Opciones:
    --phone <num>       Teléfono E.164 (default: +573125835649).
    --tenant-id <uuid>  Restringe a un tenant específico.
    --output <path>     Ruta del archivo de salida. Si no se pasa, se genera
                        automáticamente bajo scripts/uat/logs/.
    --limit <n>         Máximo de mensajes a volcar por conversación (default 500).

Lee Supabase con service_role desde `.env` raíz del repo. Imprime también
en stdout para inspección rápida.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
ENV_PATH = os.path.join(REPO_ROOT, ".env.local")
DEFAULT_LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")


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


def _safe_phone_for_filename(phone: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in phone).strip("_") or "unknown"


def _find_conversations(supabase, phone: str, tenant_id: Optional[str]) -> list[dict]:
    variants = _phone_variants(phone)
    q = supabase.table("conversations").select(
        "id, tenant_id, customer_phone, status, last_interaction_at, "
        "created_at, archived_at"
    )
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    or_clause = ",".join(f"customer_phone.eq.{v}" for v in variants)
    if hasattr(q, "or_"):
        q = q.or_(or_clause)
    res = q.order("created_at", desc=False).execute()
    return list(res.data or [])


def _fetch_messages(supabase, conversation_id: str, limit: int) -> list[dict]:
    res = (
        supabase.table("messages")
        .select(
            "id, direction, content_type, content, media_url, meta_message_id, "
            "processing_status, processed, processed_at, created_at"
        )
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return list(res.data or [])


def _fetch_contact(supabase, tenant_id: str, phone: str) -> Optional[dict]:
    variants = _phone_variants(phone)
    q = supabase.table("contacts").select(
        "id, name, email, phone, shipping_phone, document_type, document_number, "
        "address, consent_given, consent_revoked_at"
    ).eq("tenant_id", tenant_id)
    or_clause = ",".join(f"phone.eq.{v}" for v in variants)
    if hasattr(q, "or_"):
        q = q.or_(or_clause)
    res = q.limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


def _format_message(msg: dict) -> str:
    ts = msg.get("created_at", "")
    direction = (msg.get("direction") or "?").upper().ljust(8)
    ctype = (msg.get("content_type") or "?").ljust(8)
    pstatus = msg.get("processing_status") or "—"
    body = (msg.get("content") or "").rstrip()
    media = msg.get("media_url")
    meta_id = msg.get("meta_message_id") or ""
    head = f"[{ts}] {direction} {ctype} status={pstatus}"
    if meta_id:
        head += f" meta_id={meta_id}"
    parts = [head]
    if body:
        # Indenta el body para legibilidad.
        parts.extend(f"    {line}" for line in body.splitlines() or [body])
    if media:
        parts.append(f"    [media] {media}")
    return "\n".join(parts)


def _render_dump(phone: str, conv: dict, contact: Optional[dict], messages: list[dict]) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"CONVERSACIÓN — {phone}")
    lines.append("=" * 78)
    lines.append(f"  conv_id          : {conv.get('id')}")
    lines.append(f"  tenant_id        : {conv.get('tenant_id')}")
    lines.append(f"  customer_phone   : {conv.get('customer_phone')}")
    lines.append(f"  status           : {conv.get('status')}")
    lines.append(f"  last_interaction : {conv.get('last_interaction_at')}")
    lines.append(f"  archived_at      : {conv.get('archived_at')}")
    lines.append(f"  created_at       : {conv.get('created_at')}")
    if contact:
        lines.append("")
        lines.append("CONTACTO")
        lines.append("-" * 78)
        lines.append(f"  contact_id       : {contact.get('id')}")
        lines.append(f"  name             : {contact.get('name')}")
        lines.append(f"  email            : {contact.get('email')}")
        lines.append(f"  phone (WhatsApp) : {contact.get('phone')}")
        ship = contact.get("shipping_phone")
        if ship:
            lines.append(f"  shipping_phone   : {ship}")
        doc_type = contact.get("document_type")
        doc_num = contact.get("document_number")
        if doc_type or doc_num:
            lines.append(f"  document         : {doc_type} {doc_num}")
        addr = contact.get("address")
        if addr:
            lines.append(f"  address          : {addr}")
        lines.append(f"  consent_given    : {contact.get('consent_given')}")
        revoked = contact.get("consent_revoked_at")
        if revoked:
            lines.append(f"  consent_revoked  : {revoked}")
    lines.append("")
    lines.append(f"MENSAJES ({len(messages)})")
    lines.append("-" * 78)
    if not messages:
        lines.append("  (sin mensajes)")
    else:
        for m in messages:
            lines.append(_format_message(m))
            lines.append("")
    lines.append("=" * 78)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Vuelca conversación a archivo log.")
    ap.add_argument("--phone", default="+573125835649")
    ap.add_argument("--tenant-id", default=None)
    ap.add_argument("--output", default=None,
                    help="Archivo de salida. Default: scripts/uat/logs/conversation_<phone>_<ts>.log")
    ap.add_argument("--limit", type=int, default=500,
                    help="Máximo de mensajes por conversación (default 500).")
    args = ap.parse_args()

    creds = _load_env()
    url = creds.get("NEXT_PUBLIC_SUPABASE_URL")
    key = creds.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        print("ERROR: falta NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY en .env",
              file=sys.stderr)
        sys.exit(1)

    from supabase import create_client
    supabase = create_client(url, key)

    convs = _find_conversations(supabase, args.phone, args.tenant_id)
    if not convs:
        scope = f"tenant {args.tenant_id}" if args.tenant_id else "todos los tenants"
        print(f"No hay conversaciones para {args.phone} en {scope}.")
        return

    if args.output:
        out_path = args.output
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    else:
        os.makedirs(DEFAULT_LOGS_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        fname = f"conversation_{_safe_phone_for_filename(args.phone)}_{ts}.log"
        out_path = os.path.join(DEFAULT_LOGS_DIR, fname)

    blocks: list[str] = []
    blocks.append(
        f"# Dump generado {datetime.now(timezone.utc).isoformat()}\n"
        f"# Teléfono: {args.phone}\n"
        f"# Conversaciones encontradas: {len(convs)}\n"
        f"# Tenant filter: {args.tenant_id or '(todos)'}\n"
    )
    for conv in convs:
        contact = _fetch_contact(supabase, conv["tenant_id"], args.phone)
        msgs = _fetch_messages(supabase, conv["id"], args.limit)
        blocks.append(_render_dump(args.phone, conv, contact, msgs))

    content = "\n\n".join(blocks)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    # También por stdout.
    print(content)
    print(f"\n→ Archivo: {out_path}")


if __name__ == "__main__":
    main()

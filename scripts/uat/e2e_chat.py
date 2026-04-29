"""Helper E2E — envía mensaje inbound al webhook real del connector y muestra
el último outbound del bot.

Uso:
  python3.11 scripts/uat/e2e_chat.py send "Hola, qué tal"
  python3.11 scripts/uat/e2e_chat.py state                  # último estado
  python3.11 scripts/uat/e2e_chat.py wait 12                # espera N seg + tail
  python3.11 scripts/uat/e2e_chat.py reset --hard           # wipe conv + delete contact + orders

Default: número +573125835649, tenant KAIU. Override con --phone / --tenant-id.

POST al webhook local con firma HMAC válida calculada con META_APP_SECRET.
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
ENV_PATH = os.path.join(REPO_ROOT, ".env")

DEFAULT_PHONE = "+573125835649"
DEFAULT_TENANT_ID = "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9"
DEFAULT_META_WABA_ID = "2159052118202272"
DEFAULT_DEST_PHONE_ID = "990364080831295"
WEBHOOK_URL = "http://localhost:8000/api/v1/whatsapp/webhook"


def _load_env() -> dict:
    creds: dict = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds


def _hmac_signature(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_meta_payload(*, customer_phone: str, text: str, meta_waba_id: str,
                        dest_phone_id: str) -> dict:
    """Payload Meta-shaped equivalente al que Meta envía al webhook."""
    digits = customer_phone.lstrip("+")
    msg_id = f"wamid.test_{uuid.uuid4().hex[:16]}"
    ts = str(int(time.time()))
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": meta_waba_id,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "573000000000",
                        "phone_number_id": dest_phone_id,
                    },
                    "contacts": [{
                        "profile": {"name": "UAT Tester"},
                        "wa_id": digits,
                    }],
                    "messages": [{
                        "from": digits,
                        "id": msg_id,
                        "timestamp": ts,
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
            }],
        }],
    }


def _supabase():
    creds = _load_env()
    from supabase import create_client
    url = creds.get("NEXT_PUBLIC_SUPABASE_URL")
    key = creds.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERROR: faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en .env",
              file=sys.stderr)
        sys.exit(1)
    return create_client(url, key)


def _phone_norm(raw: str) -> str:
    return raw.lstrip("+").replace(" ", "").replace("-", "")


def _find_conversation(sb, tenant_id: str, phone: str) -> Optional[dict]:
    norm = _phone_norm(phone)
    res = (
        sb.table("conversations")
        .select("id, status, last_interaction_at, archived_at, created_at, customer_phone")
        .eq("tenant_id", tenant_id)
        .eq("customer_phone", norm)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def _last_messages(sb, conversation_id: str, limit: int = 8) -> list[dict]:
    res = (
        sb.table("messages")
        .select("id, direction, content_type, content, processing_status, processed, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data or []))


def _print_messages(msgs: list[dict]):
    for m in msgs:
        ts = (m.get("created_at") or "")[:19]
        direction = (m.get("direction") or "?").upper().ljust(8)
        ctype = (m.get("content_type") or "?").ljust(7)
        ps = m.get("processing_status") or "—"
        body = (m.get("content") or "").strip()
        print(f"  [{ts}] {direction} {ctype} {ps}")
        for line in body.splitlines() or [""]:
            print(f"      {line}")


def cmd_send(args):
    creds = _load_env()
    secret = creds.get("META_APP_SECRET", "")
    if not secret:
        print("ERROR: META_APP_SECRET vacío en .env", file=sys.stderr)
        sys.exit(1)

    payload = _build_meta_payload(
        customer_phone=args.phone,
        text=args.text,
        meta_waba_id=args.meta_waba_id,
        dest_phone_id=args.dest_phone_id,
    )
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _hmac_signature(body, secret)

    import urllib.request
    req = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": sig,
            "User-Agent": "uat-e2e-harness",
        },
    )
    sent_at = datetime.now(timezone.utc).isoformat()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body_resp = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"ERROR webhook POST: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f">>> [{sent_at}] INBOUND enviado: {args.text!r}")
    print(f"    HTTP {status} {body_resp.strip()}")

    if args.wait > 0:
        print(f"\n... esperando {args.wait}s a que el worker procese ...")
        time.sleep(args.wait)
        cmd_state(args)


def cmd_state(args):
    sb = _supabase()
    conv = _find_conversation(sb, args.tenant_id, args.phone)
    if not conv:
        print(f"(sin conversación para {args.phone} / tenant {args.tenant_id[:8]})")
        return
    print(f"\n=== Conversación {conv['id'][:8]} | status={conv['status']} | "
          f"last_interaction={conv.get('last_interaction_at')} ===")
    msgs = _last_messages(sb, conv["id"], args.tail)
    _print_messages(msgs)


def cmd_wait(args):
    if args.seconds > 0:
        print(f"... esperando {args.seconds}s ...")
        time.sleep(args.seconds)
    cmd_state(args)


def cmd_reset(args):
    sb = _supabase()
    norm = _phone_norm(args.phone)
    conv = _find_conversation(sb, args.tenant_id, args.phone)
    if conv:
        sb.table("conversations").delete().eq("id", conv["id"]).execute()
        print(f"  conv {conv['id'][:8]} eliminada (CASCADE → messages + reads)")
    else:
        print("  (no había conversación)")

    if args.hard:
        # Buscar contacto.
        c_res = (
            sb.table("contacts")
            .select("id, name, email")
            .eq("tenant_id", args.tenant_id)
            .or_(f"phone.eq.{norm},phone.eq.+{norm}")
            .execute()
        )
        contacts = c_res.data or []
        for c in contacts:
            # Eliminar orders del contacto primero (CASCADE de order_items).
            sb.table("orders").delete().eq("tenant_id", args.tenant_id).eq("contact_id", c["id"]).execute()
            sb.table("contacts").delete().eq("id", c["id"]).execute()
            print(f"  contact {c['id'][:8]} ({c.get('name')}) + orders eliminados")
    print("  reset OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default=DEFAULT_PHONE)
    ap.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    ap.add_argument("--meta-waba-id", default=DEFAULT_META_WABA_ID)
    ap.add_argument("--dest-phone-id", default=DEFAULT_DEST_PHONE_ID)
    ap.add_argument("--url", default=WEBHOOK_URL)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send")
    p_send.add_argument("text")
    p_send.add_argument("--wait", type=int, default=12)
    p_send.add_argument("--tail", type=int, default=6)

    p_state = sub.add_parser("state")
    p_state.add_argument("--tail", type=int, default=10)

    p_wait = sub.add_parser("wait")
    p_wait.add_argument("seconds", type=int)
    p_wait.add_argument("--tail", type=int, default=6)

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("--hard", action="store_true",
                         help="También elimina el contacto y sus orders")

    args = ap.parse_args()
    {"send": cmd_send, "state": cmd_state, "wait": cmd_wait, "reset": cmd_reset}[args.cmd](args)


if __name__ == "__main__":
    main()

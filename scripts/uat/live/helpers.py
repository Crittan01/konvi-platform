"""Helpers para validación LIVE — conversación dialógica turn-a-turn.

Sustituye el patrón `scripts/uat/scenarios/sXX_*.py` (eliminado rev. 107
2026-05-24) — esos escenarios eran ESTÁTICOS con respuestas pre-escritas
y daban PASS aunque el bot generara texto incoherente.

Filosofía live:
  • Inserta mensaje inbound directo en DB (lo que el connector haría tras
    recibir un WhatsApp).
  • Espera al orchestrator polling-based → outbound queda persistido en DB.
  • LEE la respuesta REAL del bot.
  • Formula el siguiente mensaje del cliente EN BASE a lo que el bot
    acaba de decir — como humano respondería.
  • Itera turn-a-turn evaluando coherencia global.

NUNCA usar como guion estático — los escenarios `live/objectives.md` son
referencia del OBJETIVO a probar (S14 = "cambio ciudad mid-flow", etc.),
nunca scripts.

Uso típico (interactivo desde shell del agente):
    from scripts.uat.live import helpers
    helpers.reset_known_customer()      # cliente conocido completo Bogotá
    conv = helpers.ensure_conv()
    helpers.turn(conv, "Hola")           # imprime bot reply
    helpers.turn(conv, "Quiero 2 jabones de coco 100g")
    helpers.diagnose(conv)               # muestra tool_calls + invariants
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

# El script asume cwd dentro del repo (o lo cambia).
_REPO = Path(__file__).resolve().parents[3]
os.chdir(str(_REPO))

# Cargar env desde apps/web/.env.local si no está ya seteado.
for envfile in (Path("apps/web/.env.local"),):
    if not envfile.exists():
        continue
    for line in envfile.read_text().splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ.setdefault(k, v)

from supabase import create_client

SB = create_client(
    os.environ["NEXT_PUBLIC_SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)

# Defaults founder KAIU — sobrescribibles por env.
TENANT_ID = os.environ.get(
    "UAT_LIVE_TENANT_ID", "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9",
)
TEST_PHONE = os.environ.get("UAT_LIVE_PHONE", "573125835649")


# ────────────────────────────────────────────────────────────────────
# Contact + conversation lifecycle
# ────────────────────────────────────────────────────────────────────

def ensure_contact() -> str:
    existing = SB.table("contacts").select("id").eq(
        "phone", TEST_PHONE,
    ).eq("tenant_id", TENANT_ID).limit(1).execute().data
    if existing:
        return existing[0]["id"]
    new_id = str(uuid.uuid4())
    SB.table("contacts").insert({
        "id": new_id,
        "tenant_id": TENANT_ID,
        "phone": TEST_PHONE,
        "consent_given": False,
    }).execute()
    print(f"[setup] created contact {new_id[:8]} for {TEST_PHONE}")
    return new_id


def ensure_conv() -> str:
    """Reusa conv bot_active o crea nueva."""
    ensure_contact()
    existing = SB.table("conversations").select("id").eq(
        "customer_phone", TEST_PHONE,
    ).eq("tenant_id", TENANT_ID).eq("status", "bot_active").limit(1).execute().data
    if existing:
        return existing[0]["id"]
    new_id = str(uuid.uuid4())
    SB.table("conversations").insert({
        "id": new_id,
        "tenant_id": TENANT_ID,
        "customer_phone": TEST_PHONE,
        "status": "bot_active",
    }).execute()
    return new_id


def close_active_convs() -> int:
    """Cierra cualquier conv abierta para limpiar estado entre tests."""
    rows = SB.table("conversations").select("id, status").eq(
        "customer_phone", TEST_PHONE,
    ).eq("tenant_id", TENANT_ID).execute().data or []
    count = 0
    for c in rows:
        if c.get("status") in ("bot_active", "human_takeover", "abandoned"):
            SB.table("conversations").update({"status": "closed"}).eq(
                "id", c["id"],
            ).execute()
            count += 1
    return count


def reset_new_customer() -> str:
    """Cliente NUEVO — sin consent, sin PII. Retorna conv_id fresca."""
    close_active_convs()
    contact = SB.table("contacts").select("id").eq(
        "phone", TEST_PHONE,
    ).eq("tenant_id", TENANT_ID).execute().data
    if contact:
        SB.table("contacts").update({
            "consent_given": False,
            "consent_given_at": None,
            "consent_source": None,
            "name": None,
            "email": None,
            "document_type": None,
            "document_number": None,
            "shipping_phone": None,
            "address": None,
        }).eq("id", contact[0]["id"]).execute()
    conv_id = ensure_conv()
    print(f"[reset] cliente NUEVO — conv {conv_id} bot_active")
    return conv_id


def reset_known_customer(
    *,
    name: str = "Cristian García",
    email: str = "crittan01@gmail.com",
    document_type: str = "CC",
    document_number: str = "1023456789",
    city: str = "Bogotá",
    state: str = "Cundinamarca",
    address_line: str = "Calle 100 #50-25",
) -> str:
    """Cliente CONOCIDO completo — consent + PII + address. Retorna conv_id."""
    close_active_convs()
    contact = SB.table("contacts").select("id").eq(
        "phone", TEST_PHONE,
    ).eq("tenant_id", TENANT_ID).execute().data
    if not contact:
        ensure_contact()
        contact = SB.table("contacts").select("id").eq(
            "phone", TEST_PHONE,
        ).eq("tenant_id", TENANT_ID).execute().data
    address_jsonb = {
        "line1": address_line, "city": city, "state": state, "country": "CO",
    }
    SB.table("contacts").update({
        "consent_given": True,
        "consent_given_at": "2026-05-01T00:00:00Z",
        "consent_source": "whatsapp",
        "name": name,
        "email": email,
        "document_type": document_type,
        "document_number": document_number,
        "shipping_phone": TEST_PHONE,
        "address": address_jsonb,
    }).eq("id", contact[0]["id"]).execute()
    conv_id = ensure_conv()
    print(f"[reset] cliente CONOCIDO ({name} / {city}) — conv {conv_id} bot_active")
    return conv_id


# ────────────────────────────────────────────────────────────────────
# Turn primitives
# ────────────────────────────────────────────────────────────────────

def send_inbound(conv_id: str, text: str) -> str:
    """Inserta inbound y retorna message_id."""
    msg_id = str(uuid.uuid4())
    SB.table("messages").insert({
        "id": msg_id,
        "tenant_id": TENANT_ID,
        "conversation_id": conv_id,
        "direction": "inbound",
        "content": text,
        "content_type": "text",
        "processing_status": "pending",
    }).execute()
    return msg_id


def wait_outbound(
    conv_id: str, since_iso: str, timeout_s: int = 90,
) -> dict | None:
    """Espera outbound nuevo después de `since_iso`. Retorna msg dict o None."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        msgs = SB.table("messages").select(
            "id, content, created_at, processing_status",
        ).eq("conversation_id", conv_id).eq(
            "direction", "outbound",
        ).gt("created_at", since_iso).order(
            "created_at", desc=False,
        ).limit(1).execute().data or []
        if msgs:
            return msgs[0]
        time.sleep(2)
    return None


def turn(conv_id: str, text: str, *, timeout_s: int = 90) -> str | None:
    """Envía un turn del cliente y imprime+retorna la respuesta del bot.

    Esta es la primitiva canónica para conversación dialógica live. El
    agente lee el output, evalúa coherencia, y formula el siguiente turn.
    """
    print(f"\n>>> CLIENTE: {text}\n")
    since = now_iso()
    send_inbound(conv_id, text)
    out = wait_outbound(conv_id, since, timeout_s=timeout_s)
    if not out:
        print(f"⚠️  TIMEOUT — bot no respondió en {timeout_s}s")
        return None
    body = out["content"]
    print(f"<<< BOT ({len(body)} chars):\n{body}\n")
    return body


# ────────────────────────────────────────────────────────────────────
# Diagnose / inspection helpers
# ────────────────────────────────────────────────────────────────────

def get_audit(conv_id: str, since_iso: str | None = None) -> list[dict]:
    """Lee agentic_shadow_log para inspección."""
    q = SB.table("agentic_shadow_log").select(
        "created_at, inbound_text, agentic_outbound, final_text, "
        "invariant_outcome, invariant_name, tool_call_log, "
        "tool_calls_executed, finish_reason, truncated, error, elapsed_seconds",
    ).eq("conversation_id", conv_id)
    if since_iso:
        q = q.gte("created_at", since_iso)
    return q.order("created_at", desc=False).execute().data or []


def diagnose(conv_id: str, last_n: int = 1) -> None:
    """Imprime estado interno de los últimos N turns: tool calls, invariantes,
    finish_reason. Útil para post-mortem cuando el bot responde raro.
    """
    import json
    logs = SB.table("agentic_shadow_log").select("*").eq(
        "conversation_id", conv_id,
    ).order("created_at", desc=True).limit(last_n).execute().data or []

    for log in reversed(logs):
        print(f"\n─── turn {log['created_at']} ───")
        print(f"  inbound:   {(log['inbound_text'] or '')[:120]!r}")
        print(f"  invariant: {log['invariant_outcome']} / {log['invariant_name']}")
        print(f"  finish:    {log['finish_reason']}  elapsed={log['elapsed_seconds']}s")
        tcl = log.get("tool_call_log") or []
        if isinstance(tcl, str):
            tcl = json.loads(tcl)
        print(f"  tools:     {len(tcl)}")
        for t in tcl:
            args = t.get("args") or {}
            res = t.get("result") or {}
            err = res.get("error") if isinstance(res, dict) else None
            tag = f"ERR={err}" if err else "OK"
            args_short = {k: (v[:30] if isinstance(v, str) else v)
                          for k, v in list(args.items())[:4]}
            print(f"    - {t.get('tool')} {args_short} → {tag}")
        agentic = log.get("agentic_outbound") or ""
        final = log.get("final_text") or ""
        if agentic and agentic != final:
            print(f"  agentic ≠ final (invariant rewrote)")
            print(f"  agentic:   {agentic[:200]!r}")
            print(f"  final:     {final[:200]!r}")


def cart_state(conv_id: str) -> dict:
    """Estado del cart real: items + subtotal + shipping."""
    cart = SB.table("conversation_carts").select("*").eq(
        "conversation_id", conv_id,
    ).eq("status", "open").limit(1).execute().data
    if not cart:
        return {"items": [], "subtotal": 0, "shipping": 0}
    cart = cart[0]
    items = SB.table("conversation_cart_items").select("*").eq(
        "cart_id", cart["id"],
    ).execute().data or []
    return {
        "cart_id": cart["id"],
        "items": items,
        "subtotal_cents": cart.get("subtotal_cents", 0),
        "shipping_cents": cart.get("shipping_cents", 0),
        "total_cents": cart.get("total_cents", 0),
    }


def cleanup_conv(conv_id: str) -> None:
    """CASCADE elimina messages + cart + audit."""
    SB.table("conversations").delete().eq("id", conv_id).execute()


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

#!/usr/bin/env python3.11
"""S16 — Wompi APPROVED simulation (sandbox webhook), self-contained.

OBJETIVO: validar end-to-end la transición real `pending_payment → confirmed`
disparada por un evento Wompi APPROVED firmado, incluyendo:
  • Webhook acepta firma sha256 (rev. 103 — properties relativas a `data`).
  • Status de `orders` transiciona pending_payment → confirmed.
  • `stock_movements` recibe fila con `reason='sale'` y `delta` negativo
    (decrement real, no idempotente sobre orden ya confirmed).
  • `payments.status` actualiza a APPROVED.

ESTRATEGIA — SELF-CONTAINED (rev. auditoría):
  Insertamos sintéticamente un contact + order + order_items + payment con
  `wompi_link_id` ficticio. Firmamos el evento APPROVED con ese link_id +
  events_key real del tenant. Posteamos al endpoint canónico. Verificamos
  todas las mutaciones esperadas.

  Razón: el flujo `S15 → S16` encadenado falla porque Wompi sandbox
  auto-confirma rápido cuando el link es real, dejando la orden ya en
  `confirmed` antes de que S16 corra. Self-contained garantiza una orden
  fresca en `pending_payment` para testear la transición real.

PASS:
  • Webhook responde 200/202.
  • Orden transiciona pending_payment → confirmed.
  • stock_movements registra delta negativo con reason='sale'.
  • payments.status='APPROVED'.

FAIL:
  • Cualquiera de las anteriores rota.

SKIP:
  • Webhook inaccesible.
  • Sin events_key configurado.
  • Sin product_variations con stock disponible para insertar order_item.
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, hard_reset, hash_phone, now_iso, run_one,
)
import e2e_chat  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

# Locked-mode: server-side, sin LLM. mode=known no aplica.
SUPPORTED_MODES = ("new",)

WEBHOOK_URL = "http://localhost:8001/api/v1/webhooks/wompi"
WAIT_AFTER_WEBHOOK_S = 8


def _pick_variation_with_stock(sb, tenant_id: str) -> dict | None:
    """Devuelve la primera variation con stock_quantity>0 del tenant."""
    res = (
        sb.table("product_variations")
        .select("id, product_id, stock_quantity")
        .gt("stock_quantity", 0)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    var = res.data[0]
    prod = (
        sb.table("products").select("id, title, tenant_id")
        .eq("id", var["product_id"]).limit(1).execute()
    )
    if not prod.data or prod.data[0].get("tenant_id") != tenant_id:
        return None
    var["product_title"] = prod.data[0].get("title", "Producto")
    return var


def _seed_pending_order(
    sb, *, tenant_id: str, phone: str,
) -> tuple[str | None, str | None, str | None, dict | None]:
    """Crea contact + order pending_payment + order_item + payment.

    Devuelve (contact_id, order_id, plink_id, variation_dict) o None en falla.
    """
    digits = phone.lstrip("+")
    # 1) Contact (canon: digits sin '+').
    cres = sb.table("contacts").upsert({
        "tenant_id": tenant_id,
        "phone": digits,
        "shipping_phone": digits,
        "name": "S16 Sim Buyer",
        "email": "s16@uat.local",
        "consent_given": False,
    }, on_conflict="tenant_id,phone").execute()
    if not cres.data:
        return None, None, None, None
    contact_id = cres.data[0]["id"]

    # 2) Variation con stock.
    var = _pick_variation_with_stock(sb, tenant_id)
    if not var:
        return contact_id, None, None, None

    # 3) Order pending_payment.
    unit_price = 18000  # COP de referencia
    quantity = 1
    shipping = 7000
    total = unit_price * quantity + shipping
    ores = sb.table("orders").insert({
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "status": "pending_payment",
        "total_amount": total,
        "shipping_cost": shipping,
        "notes": "S16 self-contained APPROVED simulation",
    }).execute()
    if not ores.data:
        return contact_id, None, None, var
    order_id = ores.data[0]["id"]

    # 4) Order item.
    sb.table("order_items").insert({
        "order_id": order_id,
        "tenant_id": tenant_id,
        "product_id": var["product_id"],
        "variation_id": var["id"],
        "title": var.get("product_title", "Producto"),
        "unit_price": unit_price,
        "quantity": quantity,
    }).execute()

    # 5) Payment con wompi_link_id sintético.
    plink_id = f"s16_test_{uuid.uuid4().hex[:8]}"
    sb.table("payments").insert({
        "tenant_id": tenant_id,
        "order_id": order_id,
        "provider": "wompi",
        "wompi_link_id": plink_id,
        "checkout_url": f"https://checkout.wompi.co/l/{plink_id}",
        "amount_in_cents": total * 100,
        "currency": "COP",
        "status": "PENDING",
    }).execute()

    return contact_id, order_id, plink_id, var


def _post_approved_webhook(payload: dict) -> tuple[bool, int | None]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        WEBHOOK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return (r.status in (200, 202)), r.status
    except Exception:
        return False, None


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    sb = e2e_chat._supabase()

    # 0) events_key del tenant (rev. 103: per-tenant en Vault).
    try:
        from integrations.wompi_client import get_tenant_wompi_creds  # type: ignore
    except Exception as exc:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            f"No pude importar wompi_client: {exc}")
    _, events_key, _env = get_tenant_wompi_creds(sb, tenant_id)
    if not events_key:
        creds = e2e_chat._load_env()
        events_key = (creds.get("WOMPI_EVENTS_KEY")
                      or creds.get("WOMPI_TEST_EVENTS_KEY", ""))
    if not events_key:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            "Sin events_key — ni en tenant_integrations ni en .env")

    # 1) Seed orden sintética pending_payment.
    contact_id, order_id, plink_id, var = _seed_pending_order(
        sb, tenant_id=tenant_id, phone=phone,
    )
    if not order_id or not plink_id:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            "No se pudo seedear orden pending_payment "
            f"(contact={contact_id is not None}, var={var is not None})")

    # 2) Capturar stock pre-webhook.
    pre_var = sb.table("product_variations").select("stock_quantity").eq(
        "id", var["id"]
    ).limit(1).execute()
    pre_stock = (pre_var.data[0].get("stock_quantity") or 0) if pre_var.data else 0

    # 3) Construir + firmar payload APPROVED.
    try:
        from helpers.wompi_payload_builder import WompiPayloadBuilder  # type: ignore
    except Exception as exc:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            f"No pude importar WompiPayloadBuilder: {exc}",
            evidence={"order_id": order_id})
    txn_id = f"sim_{uuid.uuid4().hex[:8]}"
    payload = (WompiPayloadBuilder(events_key=events_key)
        .with_approved_txn(payment_link_id=plink_id, txn_id=txn_id)
        .build())

    # 4) POST al webhook.
    posted_ok, posted_status = _post_approved_webhook(payload)
    if not posted_ok:
        return ScenarioResult(16, "Wompi APPROVED simulation", FAIL,
            f"Webhook no aceptó payload firmado (status={posted_status!r})",
            evidence={"order_id": order_id, "plink_id": plink_id})

    # 5) Esperar procesamiento async.
    time.sleep(WAIT_AFTER_WEBHOOK_S)

    # 6) Verificar mutaciones esperadas.
    refreshed = sb.table("orders").select("status, updated_at").eq(
        "id", order_id
    ).limit(1).execute()
    new_status = (refreshed.data[0].get("status") if refreshed.data else None)

    movements = sb.table("stock_movements").select("delta, reason, new_stock").eq(
        "order_id", order_id
    ).execute()
    sale_movement = next(
        (m for m in (movements.data or [])
         if (m.get("delta") or 0) < 0 and m.get("reason") == "sale"),
        None,
    )

    payment = sb.table("payments").select("status, wompi_status, wompi_txn_id").eq(
        "order_id", order_id
    ).limit(1).execute()
    pay_status = payment.data[0].get("status") if payment.data else None
    pay_wstatus = payment.data[0].get("wompi_status") if payment.data else None

    post_var = sb.table("product_variations").select("stock_quantity").eq(
        "id", var["id"]
    ).limit(1).execute()
    post_stock = (post_var.data[0].get("stock_quantity") or 0) if post_var.data else 0

    evidence = {
        "order_id": order_id,
        "plink_id": plink_id,
        "txn_id": txn_id,
        "webhook_status": posted_status,
        "order_status_after": new_status,
        "payment_status_after": pay_status,
        "wompi_status_after": pay_wstatus,
        "stock_pre": pre_stock,
        "stock_post": post_stock,
        "sale_movement": sale_movement,
    }

    fails: list[str] = []
    if new_status != "confirmed":
        fails.append(f"orders.status={new_status!r} (esperado 'confirmed')")
    if not sale_movement:
        fails.append("stock_movements sin fila reason='sale' delta<0 para esta orden")
    elif post_stock != pre_stock - 1:
        fails.append(
            f"stock no decrementó: pre={pre_stock} post={post_stock} (esperado {pre_stock - 1})"
        )
    # Estricto: payments DEBE actualizarse a APPROVED tras webhook (rev. 103
    # contract de auditabilidad). status 'PENDING' o wompi_status null
    # significa que el webhook handler no completó el ciclo.
    if (pay_status or "").upper() != "APPROVED":
        fails.append(
            f"payments.status={pay_status!r} (esperado 'APPROVED' tras webhook)"
        )
    if (pay_wstatus or "").upper() != "APPROVED":
        fails.append(
            f"payments.wompi_status={pay_wstatus!r} (esperado 'APPROVED')"
        )

    if fails:
        return ScenarioResult(16, "Wompi APPROVED simulation", FAIL,
            "; ".join(fails), evidence=evidence)
    return ScenarioResult(16, "Wompi APPROVED simulation", PASS,
        f"Transición real pending→confirmed + stock_decrement (delta=-1) + "
        f"payments.wompi_status=APPROVED (txn={txn_id})",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))

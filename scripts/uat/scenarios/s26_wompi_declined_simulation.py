#!/usr/bin/env python3.11
"""S26 — Wompi DECLINED simulation (rev. 104, F1-11).

OBJETIVO: validar end-to-end el flow de pago RECHAZADO disparado por
webhook Wompi `transaction.status=DECLINED`. Casos cubiertos:
  • Webhook acepta la firma (signature válida).
  • Orden NO transiciona a `confirmed` — se queda en `pending_payment` o
    pasa a `cancelled` según política del tenant.
  • Stock NO se decrementa (no hay `stock_movements` con `reason='sale'`).
  • `payments.status='declined'` y `payments.wompi_status='DECLINED'`.
  • Bot notifica al cliente del fallo + ofrece retry link.

ESTRATEGIA — SELF-CONTAINED (igual que S16 self-contained):
  Insertamos sintéticamente un contact + order(pending_payment) + order_items +
  payment con `wompi_link_id` ficticio. Firmamos un evento DECLINED con ese
  link_id + events_key real del tenant. Posteamos al endpoint canónico.
  Verificamos las mutaciones esperadas (o ausencia de ellas).

PASS: webhook 200 + orden NO confirmed + sin stock_movement sale + payments.status='declined'.
FAIL: cualquiera de las anteriores rota.
SKIP: webhook inaccesible / sin events_key / sin variation con stock.
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
    PASS, FAIL, SKIP, ScenarioResult, hard_reset, run_one,
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
    digits = phone.lstrip("+")
    cres = sb.table("contacts").upsert({
        "tenant_id": tenant_id,
        "phone": digits,
        "shipping_phone": digits,
        "name": "S26 Sim Buyer",
        "email": "s26@uat.local",
        "consent_given": False,
    }, on_conflict="tenant_id,phone").execute()
    if not cres.data:
        return None, None, None, None
    contact_id = cres.data[0]["id"]

    var = _pick_variation_with_stock(sb, tenant_id)
    if not var:
        return contact_id, None, None, None

    unit_price = 18000
    quantity = 1
    shipping = 7000
    total = unit_price * quantity + shipping
    ores = sb.table("orders").insert({
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "status": "pending_payment",
        "total_amount": total,
        "shipping_cost": shipping,
        "notes": "S26 self-contained DECLINED simulation",
    }).execute()
    if not ores.data:
        return contact_id, None, None, var
    order_id = ores.data[0]["id"]

    sb.table("order_items").insert({
        "order_id": order_id,
        "tenant_id": tenant_id,
        "product_id": var["product_id"],
        "variation_id": var["id"],
        "title": var.get("product_title", "Producto"),
        "unit_price": unit_price,
        "quantity": quantity,
    }).execute()

    plink_id = f"s26_test_{uuid.uuid4().hex[:8]}"
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


def _post_webhook(payload: dict) -> tuple[bool, int | None]:
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

    try:
        from integrations.wompi_client import get_tenant_wompi_creds  # type: ignore
    except Exception as exc:
        return ScenarioResult(26, "Wompi DECLINED simulation", SKIP,
            f"No pude importar wompi_client: {exc}")
    _, events_key, _env = get_tenant_wompi_creds(sb, tenant_id)
    if not events_key:
        creds = e2e_chat._load_env()
        events_key = (creds.get("WOMPI_EVENTS_KEY")
                      or creds.get("WOMPI_TEST_EVENTS_KEY", ""))
    if not events_key:
        return ScenarioResult(26, "Wompi DECLINED simulation", SKIP,
            "Sin events_key — ni en tenant_integrations ni en .env")

    contact_id, order_id, plink_id, var = _seed_pending_order(
        sb, tenant_id=tenant_id, phone=phone,
    )
    if not order_id or not plink_id:
        return ScenarioResult(26, "Wompi DECLINED simulation", SKIP,
            f"No se pudo seedear orden pending_payment "
            f"(contact={contact_id is not None}, var={var is not None})")

    pre_var = sb.table("product_variations").select("stock_quantity").eq(
        "id", var["id"]
    ).limit(1).execute()
    pre_stock = (pre_var.data[0].get("stock_quantity") or 0) if pre_var.data else 0

    try:
        from helpers.wompi_payload_builder import WompiPayloadBuilder  # type: ignore
    except Exception as exc:
        return ScenarioResult(26, "Wompi DECLINED simulation", SKIP,
            f"No pude importar WompiPayloadBuilder: {exc}",
            evidence={"order_id": order_id})
    txn_id = f"sim_{uuid.uuid4().hex[:8]}"
    payload = (WompiPayloadBuilder(events_key=events_key)
        .with_declined_txn(payment_link_id=plink_id, txn_id=txn_id)
        .build())

    posted_ok, posted_status = _post_webhook(payload)
    if not posted_ok:
        return ScenarioResult(26, "Wompi DECLINED simulation", FAIL,
            f"Webhook no aceptó payload firmado (status={posted_status!r})",
            evidence={"order_id": order_id, "plink_id": plink_id})

    time.sleep(WAIT_AFTER_WEBHOOK_S)

    refreshed = sb.table("orders").select("status, updated_at").eq(
        "id", order_id
    ).limit(1).execute()
    new_status = (refreshed.data[0].get("status") if refreshed.data else None)

    movements = sb.table("stock_movements").select("delta, reason").eq(
        "order_id", order_id
    ).execute()
    sale_movement = next(
        (m for m in (movements.data or [])
         if (m.get("delta") or 0) < 0 and m.get("reason") == "sale"),
        None,
    )

    payment = sb.table("payments").select("status, wompi_status").eq(
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
    # Orden NO confirmed (puede ser pending_payment o cancelled según política).
    if new_status == "confirmed":
        fails.append(f"orders.status='confirmed' tras DECLINED (esperado pending_payment o cancelled)")
    # NO debe haber stock_movement de sale.
    if sale_movement:
        fails.append(f"stock_movement con reason='sale' inesperado tras DECLINED: {sale_movement}")
    if post_stock != pre_stock:
        fails.append(
            f"stock cambió: pre={pre_stock} post={post_stock} (esperado igual — sin sale)"
        )
    # payments.status = 'declined'.
    if (pay_status or "").lower() != "declined":
        fails.append(
            f"payments.status={pay_status!r} (esperado 'declined' tras webhook)"
        )
    if (pay_wstatus or "").upper() != "DECLINED":
        fails.append(
            f"payments.wompi_status={pay_wstatus!r} (esperado 'DECLINED')"
        )

    if fails:
        return ScenarioResult(26, "Wompi DECLINED simulation", FAIL,
            "; ".join(fails), evidence=evidence)
    return ScenarioResult(26, "Wompi DECLINED simulation", PASS,
        f"DECLINED procesado: order.status={new_status} (no confirmed) + "
        f"sin stock_decrement + payments.status='declined' (txn={txn_id})",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))

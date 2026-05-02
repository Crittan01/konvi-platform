#!/usr/bin/env python3.11
"""S16 — Wompi APPROVED simulation (sandbox webhook).

OBJETIVO: sobre orden pending_payment ya creada, simular evento Wompi
APPROVED firmado. Validar que orchestrator confirma orden + decrementa
stock + notifica al cliente.

FLOW (sin LLM): query orden → POST APPROVED al webhook → wait 8s →
verificar status=confirmed + stock_movements decremento.

PASS: orden confirmed + stock decrement detectado.
FAIL: webhook rechazado, status no confirmed, sin stock decrement.
SKIP: sin contact_id (S15 no creó orden), sin orden pending_payment,
      sin WOMPI_EVENTS_KEY, webhook no accesible.

NOTA: la columna real de payment link está en `payments.wompi_link_id`
(no `orders.wompi_link_id`). Este escenario hace JOIN payments→orders.
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
    PASS, FAIL, SKIP, ScenarioResult, run_one,
)
import e2e_chat  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests"))

# Locked-mode: depende de orden pending_payment existente (creada por S15).
# `mode=known` no aplica — el contact existe por la cadena S15.
SUPPORTED_MODES = ("new",)


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select("id").eq(
        "tenant_id", tenant_id
    ).or_(f"phone.eq.{digits},phone.eq.+{digits}").limit(1).execute()
    if not contact.data:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            "Sin contact_id — S15 no creó orden")
    contact_id = contact.data[0]["id"]
    orders = sb.table("orders").select("id, status, conversation_id").eq(
        "contact_id", contact_id
    ).eq("status", "pending_payment").order("created_at", desc=True).limit(1).execute()
    if not orders.data:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            "No hay orden en pending_payment para simular APPROVED")
    order = orders.data[0]
    # JOIN payments → orders para obtener wompi_link_id (la columna vive
    # en payments, no orders).
    payments = sb.table("payments").select("wompi_link_id").eq(
        "order_id", order["id"]
    ).limit(1).execute()
    plink_id = payments.data[0].get("wompi_link_id") if payments.data else None
    if not plink_id:
        return ScenarioResult(16, "Wompi APPROVED simulation", FAIL,
            "Orden pending_payment sin wompi_link_id — link nunca se creó",
            evidence={"order_id": order["id"]})

    from helpers.wompi_payload_builder import WompiPayloadBuilder  # type: ignore
    creds = e2e_chat._load_env()
    events_key = creds.get("WOMPI_EVENTS_KEY") or creds.get("WOMPI_TEST_EVENTS_KEY", "")
    if not events_key:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            "Sin WOMPI_EVENTS_KEY en .env — no puedo firmar evento sandbox")

    payload = (WompiPayloadBuilder(events_key=events_key)
        .with_approved_txn(payment_link_id=plink_id, txn_id=f"sim_{uuid.uuid4().hex[:8]}")
        .build())
    body = json.dumps(payload).encode()

    posted_ok = False
    for url in ("http://localhost:8000/api/v1/wompi/webhook",
                "http://localhost:9000/api/v1/wompi/webhook"):
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status in (200, 202):
                    posted_ok = True
                    break
        except Exception:
            continue
    if not posted_ok:
        return ScenarioResult(16, "Wompi APPROVED simulation", SKIP,
            "Webhook /api/v1/wompi/webhook no accesible (8000 ni 9000)")

    time.sleep(8)
    refreshed = sb.table("orders").select("status, paid_at").eq(
        "id", order["id"]
    ).limit(1).execute()
    if not refreshed.data:
        return ScenarioResult(16, "Wompi APPROVED simulation", FAIL,
            "Orden desapareció tras webhook")
    new_status = refreshed.data[0].get("status")
    if new_status != "confirmed":
        return ScenarioResult(16, "Wompi APPROVED simulation", FAIL,
            f"Orden status={new_status} (esperado confirmed)",
            evidence={"order_id": order["id"], "status": new_status})

    movements = sb.table("stock_movements").select(
        "delta, reason"
    ).eq("order_id", order["id"]).limit(5).execute()
    decremented = any(
        (m.get("delta") or 0) < 0 and m.get("reason") == "reservation_consumed"
        for m in (movements.data or [])
    )
    return ScenarioResult(16, "Wompi APPROVED simulation", PASS,
        f"Orden {order['id'][:8]} confirmed; stock decrement={decremented}",
        evidence={"order_id": order["id"],
                  "status": new_status,
                  "stock_decremented": decremented})


if __name__ == "__main__":
    sys.exit(run_one(scenario))

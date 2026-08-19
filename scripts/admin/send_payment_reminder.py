#!/usr/bin/env python3.11
"""Disparar payment_reminder_v1 para una orden específica
(Sem 7 F2 item 6.a / 2026-05-17).

Demo + utilidad operativa: dado un order_id, lee los datos de la orden
+ envía el template `payment_reminder_v1` al cliente. Útil para:

  - Operación manual mientras no esté el cron automático (item 6.b)
  - Smoke verification que el flow E2E funciona
  - Soporte: founder/CS dispara reminder manual a cliente VIP

Pre-requisitos:
  - .env con NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY
  - Template `payment_reminder_v1` en estado APPROVED
  - Orden con status=pending_payment + customer_phone

Uso:
  python3.11 scripts/admin/send_payment_reminder.py \\
    --tenant-id 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9 \\
    --order-id ord_xxx

  python3.11 scripts/admin/send_payment_reminder.py \\
    --tenant-id ... --order-id ... --dry-run   # NO envía, sólo imprime
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("send_reminder")


def _load_env():
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _format_pesos(amount: float | int | None) -> str:
    """Formatea un monto en PESOS → '$87.500'.

    orders.total_amount ya está en PESOS (NO en centavos), igual que lo trata
    worker.py._try_send_payment_reminder_hsm (`pesos = int(total_amount)`). El
    formato replica el del cron: sin sufijo ' COP' (P5, UX limpio) para que el
    template payment_reminder_v1 muestre el MISMO texto lo dispare el cron o este
    trigger manual. Antes esta función dividía //100 tratando pesos como centavos
    → mostraba $875 en vez de $87.500.
    """
    try:
        pesos = int(amount or 0)
    except (TypeError, ValueError):
        pesos = 0
    # Punto cada 3 dígitos (formato CO).
    s = f"{pesos:,}".replace(",", ".")
    return f"${s}"


async def main():
    _load_env()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--order-id", required=True)
    p.add_argument("--dry-run", action="store_true",
                   help="NO envía, sólo imprime payload")
    p.add_argument("--checkout-url-override",
                   help="Override URL pago (si no, intenta payments.checkout_url)")
    args = p.parse_args()

    from supabase import create_client  # type: ignore
    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["SUPABASE_SECRET_KEY"],
    )

    # 1. Lookup orden — ESQUEMA REAL (rev. D-F7):
    #    orders NO tiene customer_name / customer_phone / order_number. El teléfono
    #    vive en conversations.customer_phone, el nombre en contacts.name y el link
    #    de pago en payments.checkout_url. Se replica la hidratación de
    #    worker.py._try_send_payment_reminder_hsm (fuente probada). Antes el SELECT
    #    referenciaba columnas inexistentes → PostgREST 400 y el trigger fallaba SIEMPRE.
    res = (
        sb.table("orders")
        .select("id, tenant_id, conversation_id, contact_id, total_amount, "
                "status, conversations(customer_phone)")
        .eq("id", args.order_id)
        .eq("tenant_id", args.tenant_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        logger.error("[ERROR] orden %s no encontrada para tenant %s",
                     args.order_id, args.tenant_id)
        sys.exit(2)
    order = rows[0]

    conv = order.get("conversations") or {}
    if isinstance(conv, list):  # PostgREST puede devolver el embed como lista
        conv = conv[0] if conv else {}
    customer_phone = (conv.get("customer_phone") if isinstance(conv, dict) else "") or ""
    total_amount = order.get("total_amount") or 0
    status = order.get("status")
    # order_number: orders NO tiene la columna → id corto (igual que worker.py).
    order_number = str(order["id"])[:8].upper()

    # Nombre del cliente vía contacts.name (columna real; first_name/full_name NO
    # existen — ver worker.py F44). Se respeta el soft opt-out (consent_revoked_at):
    # enviar un HSM proactivo a quien revocó consentimiento viola Ley 1581 Art.9 +
    # Meta Policy, lo dispare el cron o un operador.
    customer_name = "cliente"
    contact_id = order.get("contact_id")
    if contact_id:
        contact_res = (
            sb.table("contacts")
            .select("name, consent_revoked_at")
            .eq("id", contact_id)
            .eq("tenant_id", args.tenant_id)
            .limit(1)
            .execute()
        )
        contact_rows = contact_res.data or []
        if contact_rows:
            if contact_rows[0].get("consent_revoked_at"):
                logger.error(
                    "[ERROR] contacto con soft opt-out (consent_revoked_at) — "
                    "NO se envía HSM proactivo (Ley 1581 Art.9 + Meta Policy). "
                    "Igual que el cron, el trigger manual respeta el opt-out."
                )
                sys.exit(8)
            full = (contact_rows[0].get("name") or "").strip()
            if full:
                customer_name = full

    if status not in ("pending_payment", "pending"):
        logger.warning(
            "[WARN] orden status=%s (no pending_payment). ¿Seguir? Continuando...",
            status,
        )

    if not customer_phone:
        logger.error("[ERROR] conversación de la orden sin customer_phone")
        sys.exit(3)

    # 2. Resolver checkout URL (Wompi) — payments.checkout_url filtrado por tenant
    #    (ADR-0025: service_role exige filtro explícito por tenant), el más reciente.
    checkout_url = args.checkout_url_override
    if not checkout_url:
        pay_res = (
            sb.table("payments")
            .select("checkout_url, created_at")
            .eq("order_id", args.order_id)
            .eq("tenant_id", args.tenant_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        pay_rows = pay_res.data or []
        if pay_rows:
            checkout_url = (pay_rows[0].get("checkout_url") or "").strip()
    if not checkout_url:
        logger.error(
            "[ERROR] no se pudo resolver checkout URL desde payments.checkout_url. "
            "Pasa --checkout-url-override manualmente"
        )
        sys.exit(4)

    # 3. Build params del template POSITIONAL (mismo orden que worker.py:
    #    [nombre, order_number, total, checkout_url]).
    body_params = [
        customer_name.split(" ")[0],  # primer nombre
        order_number,
        _format_pesos(total_amount),
        checkout_url,
    ]

    logger.info("[REMINDER] tenant=%s order=%s to_phone=%s",
                args.tenant_id, order_number, customer_phone)
    logger.info("[REMINDER] body_params=%s", body_params)

    if args.dry_run:
        logger.info("[DRY-RUN] template=payment_reminder_v1 — NO se envía")
        sys.exit(0)

    # 4. Llamar send_whatsapp_template
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))
    from whatsapp_sender import (  # type: ignore
        send_whatsapp_template,
        TEMPLATE_ERR_TEMPLATE_NOT_APPROVED,
        TEMPLATE_ERR_TEMPLATE_NOT_FOUND,
    )

    msg_id, err = await send_whatsapp_template(
        tenant_id=args.tenant_id,
        supabase=sb,
        to_phone=customer_phone,
        template_name="payment_reminder_v1",
        language="es_CO",
        body_params=body_params,
    )

    if err == TEMPLATE_ERR_TEMPLATE_NOT_APPROVED:
        logger.error(
            "[ERROR] template payment_reminder_v1 NO está APPROVED. "
            "Primero correr: scripts/admin/submit_template_to_meta.py + "
            "esperar review Meta (~15min-48h)"
        )
        sys.exit(5)
    if err == TEMPLATE_ERR_TEMPLATE_NOT_FOUND:
        logger.error(
            "[ERROR] template payment_reminder_v1 no existe en DB. "
            "Aplicar migración 20260523000000_seed_kaiu_templates.sql"
        )
        sys.exit(6)
    if err:
        logger.error("[ERROR] send_whatsapp_template falló: %s", err)
        sys.exit(7)

    logger.info("[REMINDER] ✓ enviado meta_message_id=%s", msg_id)
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())

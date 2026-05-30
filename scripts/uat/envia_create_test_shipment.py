#!/usr/bin/env python3.11
"""Genera shipment de TEST en sandbox Envia para H.2.2 Fase A.

Fase A requiere un tracking_number real en sandbox para invocar
/ship/webhooktest/ (Envia rechaza tracking sintético con
"Undefined property: stdClass::$carrier").

Este script:
1. Cotiza un envío Bogotá → Medellín en sandbox (rate)
2. Genera label en sandbox (no debita real, "sandbox labels are not valid
   for carrier pickup" per dossier sec. 2.3)
3. Inserta shipment en DB con tracking_number obtenido
4. Imprime tracking_number + envia_shipment_id para usar en webhooktest

Uso:
  python3.11 scripts/uat/envia_create_test_shipment.py \\
    --tenant-id 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("envia_create_test")


def _load_env():
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    if env_path.exists():
        with env_path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "services" / "api"))

    from supabase import create_client
    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    # Resolver origin del tenant.
    tenant_res = sb.table("tenants").select("shipping_origin").eq(
        "id", args.tenant_id).single().execute()
    origin_db = (tenant_res.data or {}).get("shipping_origin") or {}

    # Resolver token Envia.
    creds_res = sb.table("tenant_integrations").select("credentials").eq(
        "tenant_id", args.tenant_id).eq("provider", "envia").single().execute()
    creds = (creds_res.data or {}).get("credentials") or {}
    api_token = creds.get("api_token")
    if not api_token:
        from vault_helper import VaultHelper, resolve_secret
        api_token = resolve_secret(VaultHelper(sb), creds, "api_token")
    if not api_token:
        logger.error("[ERROR] api_token Envia no encontrado")
        sys.exit(1)

    # Construir origin per Envia schema CO (ver shipping.py:459-469).
    # CRÍTICO Colombia: Envia espera city = postalCode = DANE 8 dígitos
    # (NO el nombre legible de la ciudad). Bogotá DANE8=11001000.
    # Medellín DANE8=05001000.
    origin = {
        "name": origin_db.get("name") or "KAIU Test",
        "company": origin_db.get("company") or "KAIU",
        "phone": origin_db.get("phone") or "3000000000",
        "email": "test@kaiu.test",
        "street": origin_db.get("street") or "Calle 100",
        "number": "1",
        "city": "11001000",
        "state": "DC",
        "country": "CO",
        "postalCode": "11001000",
    }

    # Destino fijo Medellín para test.
    destination = {
        "name": "Cliente Test",
        "company": "Cliente Test",
        "phone": "3000000001",
        "email": "destino@test.com",
        "street": "Calle 50",
        "number": "10",
        "city": "05001000",
        "state": "ANT",
        "country": "CO",
        "postalCode": "05001000",
    }

    package = {
        "weight": 1.0,
        "dimensions": {"length": 20, "width": 15, "height": 10},
        "content": "Test fase A H.2.2",
        "amount": 1,
        "type": "box",
        "insuranceAmount": 0,
        "declaredValue": 50000,
        "lengthUnit": "CM",
        "weightUnit": "KG",
    }

    base_url = "https://api-test.envia.com"

    # 1. Cotizar (probamos varios carriers comunes).
    rate_payload = {
        "origin": origin,
        "destination": destination,
        "packages": [package],
        "shipment": {"carrier": "fedex", "type": 1},
        "settings": {"currency": "COP"},
    }
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

    import httpx
    logger.info("=" * 70)
    logger.info("[1/2] Cotizando Bogotá → Medellín con FedEx (sandbox)")
    with httpx.Client(timeout=30.0) as client:
        rate_resp = client.post(f"{base_url}/ship/rate/", json=rate_payload, headers=headers)
        logger.info("  HTTP %d", rate_resp.status_code)
        rate_body = rate_resp.json()

    if rate_body.get("meta") == "error":
        logger.error("  rate error: %s", json.dumps(rate_body, indent=2)[:1000])
        # Probar con otro carrier.
        for try_carrier in ("interrapidisimo", "servientrega", "envia"):
            rate_payload["shipment"]["carrier"] = try_carrier
            with httpx.Client(timeout=30.0) as client:
                rate_resp = client.post(f"{base_url}/ship/rate/", json=rate_payload, headers=headers)
                rate_body = rate_resp.json()
            if rate_body.get("meta") != "error":
                logger.info("  fallback OK con carrier=%s", try_carrier)
                break

    rate_data = rate_body.get("data") or []
    if not rate_data:
        logger.error("[ERROR] sin tarifas. Body: %s", json.dumps(rate_body, indent=2)[:1500])
        sys.exit(1)

    selected = rate_data[0] if isinstance(rate_data, list) else rate_data
    carrier = selected.get("carrier") or rate_payload["shipment"]["carrier"]
    service = selected.get("service") or selected.get("serviceDescription") or "ground"
    logger.info("  Tarifa seleccionada: carrier=%s service=%s precio=%s",
                carrier, service, selected.get("totalPrice"))

    # 2. Generar label.
    gen_payload = {
        "origin": origin,
        "destination": destination,
        "packages": [package],
        "shipment": {"carrier": carrier, "service": service, "type": 1},
        "settings": {"currency": "COP", "printFormat": "PDF", "printSize": "STOCK_4X6"},
    }
    logger.info("[2/2] Generando label sandbox carrier=%s", carrier)
    with httpx.Client(timeout=30.0) as client:
        gen_resp = client.post(f"{base_url}/ship/generate/", json=gen_payload, headers=headers)
        logger.info("  HTTP %d", gen_resp.status_code)
        gen_body = gen_resp.json()

    if gen_body.get("meta") == "error":
        logger.error("[ERROR] label error: %s", json.dumps(gen_body, indent=2)[:2000])
        sys.exit(2)

    data = gen_body.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    tracking_number = data.get("trackingNumber") or ""
    envia_shipment_id = data.get("shipmentId") or data.get("id") or ""
    label_url = data.get("label") or ""

    logger.info("=" * 70)
    logger.info("[OK] Label generada en sandbox")
    logger.info("  Tracking number:    %s", tracking_number)
    logger.info("  Envia shipment ID:  %s", envia_shipment_id)
    logger.info("  Label URL:          %s", label_url)
    logger.info("=" * 70)

    if not tracking_number:
        logger.error("[ERROR] response sin trackingNumber. Full body:")
        logger.info(json.dumps(gen_body, indent=2)[:2000])
        sys.exit(3)

    # 3. Insertar en DB para que el dispatch helper lo encuentre.
    insert_res = sb.table("shipments").insert({
        "tenant_id": args.tenant_id,
        "tracking_number": tracking_number,
        "envia_shipment_id": envia_shipment_id,
        "carrier": carrier,
        "service": service,
        "status": "labeled",
        "label_url": label_url,
        "origin_address": origin,
        "destination_address": destination,
        "parcels": [package],
        "selected_rate": selected,
    }).execute()
    inserted = insert_res.data or []
    if inserted:
        logger.info("[OK] Shipment row insertada: id=%s", inserted[0].get("id"))
    else:
        logger.warning("[WARN] insert sin data — el dispatch helper igual usa tracking_number directo")

    logger.info("\nSiguiente paso:")
    logger.info("python3.11 scripts/uat/envia_webhook_test_dispatch.py "
                f"--tenant-id {args.tenant_id} --tracking-number {tracking_number}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3.11
"""Investigación empírica — qué carriers CO soportan/requieren `envia_insurance`.

Itera ENVIA_CARRIERS_CO y para cada carrier hace 3 cotizaciones:

  A) baseline_low      — sin additional_services, declaredValue bajo (50k COP)
  B) with_insurance    — additional_services=["envia_insurance"], declaredValue=100k COP
  C) baseline_high     — sin additional_services, declaredValue ALTO (3M COP)
                         → para detectar el caso Coordinadora "rechaza sin seguro"

Categorías derivadas:
  - required        → A FAIL && B OK (provider exige insurance)
  - supported       → A OK  && B OK (acepta con o sin)
  - not_supported   → B FAIL (provider rechaza el additional_service)

Salida: docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07.json
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("insurance_test")

CARRIERS = [
    "servientrega",
    "coordinadora",
    "interRapidisimo",
    "envia",
    "tcc",
    "deprisa",
    "mensajerosUrbanos",
    "noventa9Minutos",
    "fedex",
    "dhl",
]

BASE_URL = "https://api-test.envia.com"

ORIGIN = {
    "name": "Test Origin", "company": "Test", "phone": "3000000000",
    "email": "smoke@test.test", "street": "Calle 100", "number": "1",
    "city": "11001000", "state": "DC", "country": "CO", "postalCode": "11001000",
}
DESTINATION = {
    "name": "Test Dest", "company": "Test", "phone": "3000000001",
    "email": "destino@test.test", "street": "Calle 50", "number": "10",
    "city": "05001000", "state": "ANT", "country": "CO", "postalCode": "05001000",
}
PACKAGE_BASE = {
    "weight": 1.0,
    "dimensions": {"length": 20, "width": 15, "height": 10},
    "content": "insurance test",
    "amount": 1, "type": "box",
    "lengthUnit": "CM", "weightUnit": "KG",
}


def _load_env():
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _resolve_token(supabase, tenant_id: str) -> str:
    res = (
        supabase.table("tenant_integrations")
        .select("credentials")
        .eq("tenant_id", tenant_id)
        .eq("provider", "envia")
        .single().execute()
    )
    creds = (res.data or {}).get("credentials") or {}
    token = creds.get("api_token")
    if not token:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))
        from vault_helper import VaultHelper, resolve_secret  # type: ignore
        token = resolve_secret(VaultHelper(supabase), creds, "api_token")
    if not token:
        raise RuntimeError("api_token Envia no encontrado para tenant")
    return token


def _quote(client: httpx.Client, headers: dict, carrier: str,
           declared_value: int, with_insurance: bool) -> dict:
    pkg = dict(PACKAGE_BASE)
    pkg["insuranceAmount"] = 0
    pkg["declaredValue"] = declared_value
    if with_insurance:
        pkg["additional_services"] = ["envia_insurance"]
    payload = {
        "origin": ORIGIN, "destination": DESTINATION,
        "packages": [pkg],
        "shipment": {"carrier": carrier, "type": 1},
        "settings": {"currency": "COP"},
    }
    try:
        resp = client.post(f"{BASE_URL}/ship/rate/", json=payload, headers=headers, timeout=20.0)
        body = resp.json()
    except httpx.TimeoutException:
        return {"ok": False, "error_code": "timeout", "error_msg": "request timed out"}
    except Exception as e:
        return {"ok": False, "error_code": "exception", "error_msg": str(e)[:200]}

    if resp.status_code >= 400:
        return {"ok": False, "error_code": resp.status_code, "error_msg": str(body)[:200]}
    if isinstance(body, dict) and body.get("meta") == "error":
        err = body.get("error", {})
        return {
            "ok": False,
            "error_code": err.get("code") if isinstance(err, dict) else None,
            "error_msg": (err.get("message") if isinstance(err, dict) else str(err))[:200],
        }
    data = body.get("data") if isinstance(body, dict) else None
    if not data or (isinstance(data, list) and len(data) == 0):
        # Algunos carriers responden con code/message a nivel raíz cuando no hay tarifa.
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("message") if isinstance(body, dict) else None
        return {"ok": False, "error_code": code, "error_msg": (msg or "no data")[:200]}
    first = data[0] if isinstance(data, list) else data
    return {
        "ok": True,
        "totalPrice": first.get("totalPrice"),
        "service": first.get("service"),
        "additional_services": first.get("additionalServices") or first.get("additional_services"),
    }


def main():
    _load_env()
    if len(sys.argv) < 2:
        print("Uso: test_envia_insurance_carriers_CO.py <tenant_id>")
        sys.exit(1)
    tenant_id = sys.argv[1]

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "services" / "api"))
    from supabase import create_client  # type: ignore

    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )
    api_token = _resolve_token(sb, tenant_id)
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

    logger.info("=" * 78)
    logger.info("Insurance per-carrier — sandbox Envia (tenant %s)", tenant_id)
    logger.info("=" * 78)
    logger.info(f"{'carrier':<22} {'baseline_low':<14} {'with_insurance':<16} {'baseline_high':<16} category")
    logger.info("-" * 78)

    results = []
    with httpx.Client(timeout=20.0) as client:
        for carrier in CARRIERS:
            r_low = _quote(client, headers, carrier, declared_value=50_000, with_insurance=False)
            time.sleep(0.4)
            r_ins = _quote(client, headers, carrier, declared_value=100_000, with_insurance=True)
            time.sleep(0.4)
            r_high = _quote(client, headers, carrier, declared_value=3_000_000, with_insurance=False)
            time.sleep(0.4)

            # Categorización
            if not r_ins["ok"]:
                category = "not_supported"
            elif r_low["ok"] and r_ins["ok"]:
                # Si baseline_high falla pero baseline_low OK + with_insurance OK
                # ⇒ provider exige insurance para valores altos.
                if r_low["ok"] and not r_high["ok"]:
                    category = "required_high_value"
                else:
                    category = "supported"
            elif not r_low["ok"] and r_ins["ok"]:
                category = "required"
            else:
                category = "unknown"

            row = {
                "carrier": carrier,
                "category": category,
                "baseline_low_50k": r_low,
                "with_insurance_100k": r_ins,
                "baseline_high_3M": r_high,
            }
            results.append(row)
            logger.info(
                f"{carrier:<22} "
                f"{'OK' if r_low['ok'] else 'FAIL':<14} "
                f"{'OK' if r_ins['ok'] else 'FAIL':<16} "
                f"{'OK' if r_high['ok'] else 'FAIL':<16} "
                f"{category}"
            )

    out = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "method": "POST /ship/rate/ con 3 escenarios (baseline_low, with_insurance, baseline_high) per carrier",
        "tenant_id": tenant_id,
        "endpoint": BASE_URL,
        "package_base": PACKAGE_BASE,
        "origin_city": ORIGIN["city"],
        "destination_city": DESTINATION["city"],
        "results": results,
    }
    out_path = (
        Path(__file__).resolve().parents[2]
        / "docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07.json"
    )
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    logger.info("")
    logger.info("Resultado escrito en: %s", out_path)


if __name__ == "__main__":
    main()

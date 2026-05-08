#!/usr/bin/env python3.11
"""V3 — Investigación empírica insurance contra PRODUCCIÓN Envia.

ALCANCE LIMITADO: solo los 5 carriers que NO se pudieron certificar
en sandbox (coordinadora, interRapidisimo, envia, tcc, deprisa).
Total = 15 requests (5 carriers × 3 escenarios).

SEGURIDAD:
  - POST /ship/rate/ es free (NO genera label, NO cobra).
  - Token tomado de .env ENVIA_API_KEY (configurado por founder).
  - NO se llama /ship/generate/ ni nada que cobre.

Salida: docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-PROD.json
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
logger = logging.getLogger("insurance_prod")

# Solo carriers no certificables en sandbox.
CARRIERS_TO_TEST = [
    "coordinadora",
    "interRapidisimo",
    "envia",
    "tcc",
    "deprisa",
]

# Multi-ruta para maximizar chance de respuesta.
ROUTES = [
    {"label": "BOG→MDE", "origin": {"city": "11001000", "state": "DC"},
     "destination": {"city": "05001000", "state": "ANT"}},
    {"label": "BOG→BOG", "origin": {"city": "11001000", "state": "DC"},
     "destination": {"city": "11001000", "state": "DC"}},
    {"label": "BOG→CLO", "origin": {"city": "11001000", "state": "DC"},
     "destination": {"city": "76001000", "state": "VAC"}},
]

BASE_URL = "https://api.envia.com"  # PROD

PACKAGE_BASE = {
    "weight": 1.0,
    "dimensions": {"length": 20, "width": 15, "height": 10},
    "content": "research test - rate only - no label",
    "amount": 1, "type": "box",
    "lengthUnit": "CM", "weightUnit": "KG",
}


def _addr(city: str, state: str, name: str) -> dict:
    return {
        "name": name, "company": name, "phone": "3000000000",
        "email": "research@test.test", "street": "Calle 1", "number": "1",
        "city": city, "state": state, "country": "CO", "postalCode": city,
    }


def _load_env():
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _quote(client, headers, carrier, route, declared_value, with_insurance) -> dict:
    pkg = dict(PACKAGE_BASE)
    pkg["insuranceAmount"] = 0
    pkg["declaredValue"] = declared_value
    if with_insurance:
        pkg["additional_services"] = ["envia_insurance"]
    payload = {
        "origin": _addr(**route["origin"], name="Origen"),
        "destination": _addr(**route["destination"], name="Destino"),
        "packages": [pkg],
        "shipment": {"carrier": carrier, "type": 1},
        "settings": {"currency": "COP"},
    }
    try:
        resp = client.post(f"{BASE_URL}/ship/rate/", json=payload, headers=headers, timeout=20.0)
        body = resp.json()
    except httpx.TimeoutException:
        return {"ok": False, "error_code": "timeout", "error_msg": "timed out"}
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
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("message") if isinstance(body, dict) else None
        return {"ok": False, "error_code": code, "error_msg": (msg or "no data")[:200]}
    first = data[0] if isinstance(data, list) else data
    return {
        "ok": True,
        "totalPrice": first.get("totalPrice"),
        "service": first.get("service"),
    }


def _resolve_prod_token(supabase, tenant_id: str) -> str:
    """Lee api_token de tenant_integrations.credentials del tenant indicado.
    El founder lo configuró aquí; NO viene de .env."""
    res = (
        supabase.table("tenant_integrations")
        .select("credentials, status, meta")
        .eq("tenant_id", tenant_id)
        .eq("provider", "envia")
        .single().execute()
    )
    row = res.data or {}
    creds = row.get("credentials") or {}
    status = row.get("status") or "?"
    meta = row.get("meta") or {}
    logger.info("[DB] tenant_integrations envia: status=%s sandbox_flag=%s", status, meta.get("sandbox"))
    token = creds.get("api_token")
    if not token:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))
        from vault_helper import VaultHelper, resolve_secret  # type: ignore
        token = resolve_secret(VaultHelper(supabase), creds, "api_token")
    if not token:
        raise RuntimeError("api_token Envia no encontrado en DB")
    return token


def main():
    _load_env()
    if len(sys.argv) < 2:
        print("Uso: test_envia_insurance_carriers_CO_PROD.py <tenant_id>")
        sys.exit(1)
    tenant_id = sys.argv[1]

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "services" / "api"))
    from supabase import create_client  # type: ignore

    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )
    api_token = _resolve_prod_token(sb, tenant_id)
    logger.info("[DB] api_token len=%d preview=%s...", len(api_token), api_token[:8])
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

    logger.info("=" * 90)
    logger.info("Insurance per-carrier — PRODUCCIÓN Envia (rate only, NO label)")
    logger.info("Endpoint: %s", BASE_URL)
    logger.info("Carriers a probar: %s", ", ".join(CARRIERS_TO_TEST))
    logger.info("=" * 90)

    results = []
    with httpx.Client(timeout=20.0) as client:
        for carrier in CARRIERS_TO_TEST:
            logger.info("\n=== %s ===", carrier)
            working_route = None
            route_attempts = []
            for route in ROUTES:
                r = _quote(client, headers, carrier, route, declared_value=50_000, with_insurance=False)
                route_attempts.append({"route": route["label"], "result": r})
                logger.info("  %s baseline_low: %s — %s",
                            route["label"],
                            "OK" if r["ok"] else "FAIL",
                            r.get("totalPrice") if r["ok"] else r.get("error_msg", "")[:80])
                if r["ok"]:
                    working_route = route
                    break
                time.sleep(0.4)

            if not working_route:
                results.append({
                    "carrier": carrier,
                    "category": "not_certifiable_in_prod",
                    "route_attempts": route_attempts,
                })
                continue

            time.sleep(0.4)
            r_ins = _quote(client, headers, carrier, working_route,
                           declared_value=100_000, with_insurance=True)
            time.sleep(0.4)
            r_high = _quote(client, headers, carrier, working_route,
                            declared_value=3_000_000, with_insurance=False)
            time.sleep(0.4)
            r_high_ins = _quote(client, headers, carrier, working_route,
                                declared_value=3_000_000, with_insurance=True)

            logger.info("  %s with_insurance_100k: %s — %s",
                        working_route["label"],
                        "OK" if r_ins["ok"] else "FAIL",
                        r_ins.get("totalPrice") if r_ins["ok"] else r_ins.get("error_msg", "")[:80])
            logger.info("  %s baseline_high_3M:    %s — %s",
                        working_route["label"],
                        "OK" if r_high["ok"] else "FAIL",
                        r_high.get("totalPrice") if r_high["ok"] else r_high.get("error_msg", "")[:80])
            logger.info("  %s high_with_ins_3M:    %s — %s",
                        working_route["label"],
                        "OK" if r_high_ins["ok"] else "FAIL",
                        r_high_ins.get("totalPrice") if r_high_ins["ok"] else r_high_ins.get("error_msg", "")[:80])

            r_low = route_attempts[-1]["result"]
            if not r_ins["ok"]:
                category = "not_supported_insurance"
            elif r_low["ok"] and not r_high["ok"] and r_high_ins["ok"]:
                category = "required_insurance_for_high_value"
            elif r_low["ok"] and r_ins["ok"]:
                price_diff = (r_ins.get("totalPrice", 0) - r_low.get("totalPrice", 0))
                category = "supported_with_premium" if price_diff > 0 else "supported"
            else:
                category = "unknown"

            results.append({
                "carrier": carrier,
                "category": category,
                "working_route": working_route["label"],
                "baseline_low_50k": r_low,
                "with_insurance_100k": r_ins,
                "baseline_high_3M": r_high,
                "high_with_insurance_3M": r_high_ins,
                "price_premium_for_insurance": (
                    r_ins.get("totalPrice", 0) - r_low.get("totalPrice", 0)
                    if r_low.get("ok") and r_ins.get("ok") else None
                ),
            })

    out = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "method": "POST /ship/rate/ PRODUCCIÓN — escenarios baseline/insurance/high_value",
        "endpoint": BASE_URL,
        "carriers_tested": CARRIERS_TO_TEST,
        "routes_tried": [r["label"] for r in ROUTES],
        "results": results,
    }
    out_path = (
        Path(__file__).resolve().parents[2]
        / "docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-PROD.json"
    )
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    logger.info("\n" + "=" * 90)
    logger.info("RESUMEN PROD")
    logger.info("=" * 90)
    for r in results:
        logger.info(f"  {r['carrier']:<22} → {r['category']}"
                    + (f" (route={r.get('working_route')})" if r.get('working_route') else "")
                    + (f" Δ=${r.get('price_premium_for_insurance')}" if r.get('price_premium_for_insurance') is not None else ""))
    logger.info("\nResultado: %s", out_path)


if __name__ == "__main__":
    main()

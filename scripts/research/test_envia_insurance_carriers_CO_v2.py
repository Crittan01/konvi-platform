#!/usr/bin/env python3.11
"""V2 — Investigación empírica insurance per carrier — MULTIPLES RUTAS.

Variante de v1 con rutas alternativas para sortear "Service Unavailable" en
sandbox. Por cada carrier, prueba 4 rutas hasta encontrar una que responda;
luego en esa ruta repite el set [baseline / with_insurance / high_value].

Salida: docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-v2.json
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
logger = logging.getLogger("insurance_v2")

CARRIERS = [
    "servientrega", "coordinadora", "interRapidisimo", "envia",
    "tcc", "deprisa", "mensajerosUrbanos", "noventa9Minutos",
    "fedex", "dhl",
]

# Rutas a probar en orden — prioriza local Bogotá para last-mile.
ROUTES = [
    {  # Bogotá → Medellín (lo que probamos en v1)
        "label": "BOG→MDE",
        "origin": {"city": "11001000", "state": "DC"},
        "destination": {"city": "05001000", "state": "ANT"},
    },
    {  # Bogotá → Bogotá (local)
        "label": "BOG→BOG",
        "origin": {"city": "11001000", "state": "DC"},
        "destination": {"city": "11001000", "state": "DC"},
    },
    {  # Bogotá → Cali
        "label": "BOG→CLO",
        "origin": {"city": "11001000", "state": "DC"},
        "destination": {"city": "76001000", "state": "VAC"},
    },
    {  # Medellín → Bogotá
        "label": "MDE→BOG",
        "origin": {"city": "05001000", "state": "ANT"},
        "destination": {"city": "11001000", "state": "DC"},
    },
]

BASE_URL = "https://api-test.envia.com"

PACKAGE_BASE = {
    "weight": 1.0,
    "dimensions": {"length": 20, "width": 15, "height": 10},
    "content": "insurance test v2",
    "amount": 1, "type": "box",
    "lengthUnit": "CM", "weightUnit": "KG",
}


def _addr(city: str, state: str, name: str) -> dict:
    return {
        "name": name, "company": name, "phone": "3000000000",
        "email": "smoke@test.test", "street": "Calle 1", "number": "1",
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


def _quote(client: httpx.Client, headers: dict, carrier: str, route: dict,
           declared_value: int, with_insurance: bool) -> dict:
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
        print("Uso: test_envia_insurance_carriers_CO_v2.py <tenant_id>")
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

    logger.info("=" * 90)
    logger.info("Insurance per-carrier — sandbox (multi-route) — tenant %s", tenant_id)
    logger.info("=" * 90)

    results = []
    with httpx.Client(timeout=20.0) as client:
        for carrier in CARRIERS:
            logger.info("\n=== %s ===", carrier)
            # Buscar la PRIMERA ruta que responde con baseline OK
            working_route = None
            route_attempts = []
            for route in ROUTES:
                r = _quote(client, headers, carrier, route, declared_value=50_000, with_insurance=False)
                route_attempts.append({"route": route["label"], "result": r})
                logger.info("  %s baseline_low: %s — %s",
                            route["label"],
                            "OK" if r["ok"] else "FAIL",
                            r.get("totalPrice") if r["ok"] else r.get("error_msg", "")[:60])
                if r["ok"]:
                    working_route = route
                    break
                time.sleep(0.3)

            if not working_route:
                results.append({
                    "carrier": carrier,
                    "category": "not_certifiable_in_sandbox",
                    "route_attempts": route_attempts,
                    "with_insurance_100k": None,
                    "baseline_high_3M": None,
                })
                continue

            # Hacemos with_insurance + baseline_high en la ruta que funcionó
            time.sleep(0.4)
            r_ins = _quote(client, headers, carrier, working_route,
                           declared_value=100_000, with_insurance=True)
            time.sleep(0.4)
            r_high = _quote(client, headers, carrier, working_route,
                            declared_value=3_000_000, with_insurance=False)

            logger.info("  %s with_insurance_100k: %s — %s",
                        working_route["label"],
                        "OK" if r_ins["ok"] else "FAIL",
                        r_ins.get("totalPrice") if r_ins["ok"] else r_ins.get("error_msg", "")[:60])
            logger.info("  %s baseline_high_3M:   %s — %s",
                        working_route["label"],
                        "OK" if r_high["ok"] else "FAIL",
                        r_high.get("totalPrice") if r_high["ok"] else r_high.get("error_msg", "")[:60])

            # Categorización
            r_low = route_attempts[-1]["result"]  # the working one
            if not r_ins["ok"]:
                category = "not_supported_insurance"
            elif r_low["ok"] and not r_high["ok"]:
                category = "required_insurance_for_high_value"
            else:
                # comparar precios para detectar si insurance cobra prima
                price_low = r_low.get("totalPrice")
                price_ins = r_ins.get("totalPrice")
                price_diff = (price_ins - price_low) if (price_low and price_ins) else 0
                category = "supported"
                if price_diff > 0:
                    category = "supported_with_premium"

            results.append({
                "carrier": carrier,
                "category": category,
                "working_route": working_route["label"],
                "route_attempts_baseline": route_attempts,
                "baseline_low_50k": r_low,
                "with_insurance_100k": r_ins,
                "baseline_high_3M": r_high,
                "price_premium_for_insurance": (
                    r_ins.get("totalPrice") - r_low.get("totalPrice")
                    if r_low.get("ok") and r_ins.get("ok") else None
                ),
            })

    out = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "method": "POST /ship/rate/ multi-route — encontrar primera ruta OK por carrier",
        "tenant_id": tenant_id,
        "endpoint": BASE_URL,
        "routes_tried": [r["label"] for r in ROUTES],
        "results": results,
    }
    out_path = (
        Path(__file__).resolve().parents[2]
        / "docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-v2.json"
    )
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    # Resumen final
    logger.info("\n" + "=" * 90)
    logger.info("RESUMEN")
    logger.info("=" * 90)
    for r in results:
        logger.info(f"  {r['carrier']:<22} → {r['category']}"
                    + (f" (route={r.get('working_route')})" if r.get('working_route') else "")
                    + (f" Δ=${r.get('price_premium_for_insurance')}" if r.get('price_premium_for_insurance') else ""))
    logger.info("\nResultado escrito en: %s", out_path)


if __name__ == "__main__":
    main()

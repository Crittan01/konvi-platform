#!/usr/bin/env python3.11
"""H.2.8 — Smoke E2E sandbox Envia (rev. 105 Sem 5).

Ejecuta secuencia COMPLETA contra Envia sandbox para verificar que
el cliente local + nuestros endpoints + el provider responden coherentes:

  1. /ship/rate/         — cotización Bogotá → Medellín FedEx
  2. /ship/generate/     — generar label sandbox + obtener trackingNumber
  3. /ship/generaltrack/ — consultar tracking
  4. /ship/cancel/       — cancelar (Envia sandbox lo permite)

Reporta paridad de campos esperados en cada response. Si algún paso
falla, imprime detalle + sale con exit_code=1 (utilizable en CI).

Pre-requisitos:
  - Tenant con integración Envia conectada (api_token Vault).
  - VM con acceso outbound a api-test.envia.com.
  - .env con NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.

Uso:
  python3.11 scripts/uat/smoke_envia_sandbox.py \
      --tenant-id 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9

Salida:
  ✅ Cada paso PASS con tiempo response.
  ❌ Detalle + body si alguno falla.
  Exit code: 0 si todos PASS, 1 si alguno FAIL.

NO consume label real productivo — todo en sandbox. NO crea filas en
shipments table (smoke puro a la API Envia).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("smoke_envia")


def _load_env():
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
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
        .single()
        .execute()
    )
    creds = (res.data or {}).get("credentials") or {}
    token = creds.get("api_token")
    if not token:
        # Vault fallback.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api"))
        from vault_helper import VaultHelper, resolve_secret
        token = resolve_secret(VaultHelper(supabase), creds, "api_token")
    if not token:
        logger.error("[ERROR] api_token Envia no encontrado")
        sys.exit(1)
    return token


def _format_step(label: str, ok: bool, ms: float, detail: str = "") -> str:
    icon = "✅" if ok else "❌"
    msg = f"  {icon} {label:30s} {ms:6.0f}ms"
    if detail:
        msg += f" — {detail}"
    return msg


def _validate_keys(label: str, body: dict, required: list[str]) -> tuple[bool, str]:
    """Verifica que body['data'] (o body directo si no tiene 'data')
    contiene los keys required. Retorna (ok, missing_str)."""
    if not isinstance(body, dict):
        return False, f"body no es dict: {type(body).__name__}"
    if body.get("meta") == "error":
        return False, f"meta=error code={body.get('error', {}).get('code')}"
    data = body.get("data")
    if isinstance(data, list):
        if not data:
            return False, "data=[] vacío"
        first = data[0] if isinstance(data[0], dict) else None
    elif isinstance(data, dict):
        first = data
    else:
        first = body  # legacy: keys top-level
    if first is None:
        return False, "no se pudo extraer first row de data"
    missing = [k for k in required if k not in first]
    if missing:
        return False, f"missing keys: {missing}"
    return True, "ok"


def main():
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--carrier", default="fedex",
        help="Carrier para cotizar (default fedex; ajustar según Envia sandbox)",
    )
    parser.add_argument(
        "--no-cancel", action="store_true",
        help="Skip cancel step (deja label sandbox en Envia)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "services" / "api"))

    from supabase import create_client
    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    api_token = _resolve_token(sb, args.tenant_id)

    # Origin per shipping_origin del tenant (más realista) o fallback.
    tenant = (
        sb.table("tenants").select("shipping_origin").eq("id", args.tenant_id).single().execute()
    ).data or {}
    origin_db = tenant.get("shipping_origin") or {}

    origin = {
        "name": origin_db.get("name") or "Smoke Test",
        "company": origin_db.get("company") or "Test",
        "phone": origin_db.get("phone") or "3000000000",
        "email": "smoke@test.test",
        "street": origin_db.get("street") or "Calle 100",
        "number": "1",
        "city": "11001000",
        "state": "DC",
        "country": "CO",
        "postalCode": "11001000",
    }
    destination = {
        "name": "Cliente Smoke",
        "company": "Cliente Smoke",
        "phone": "3000000001",
        "email": "destino@test.test",
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
        "content": "H.2.8 smoke test",
        "amount": 1,
        "type": "box",
        "insuranceAmount": 0,
        "declaredValue": 50000,
        "lengthUnit": "CM",
        "weightUnit": "KG",
    }

    base_url = "https://api-test.envia.com"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    import httpx
    results: list[tuple[str, bool, float, str]] = []
    summary: dict[str, Any] = {
        "tenant_id": args.tenant_id,
        "carrier_tested": args.carrier,
    }

    logger.info("=" * 70)
    logger.info("[H.2.8 SMOKE Envia sandbox] tenant=%s carrier=%s",
                args.tenant_id, args.carrier)
    logger.info("=" * 70)

    # ── 1. Rate ────────────────────────────────────────────────────────────
    rate_payload = {
        "origin": origin,
        "destination": destination,
        "packages": [package],
        "shipment": {"carrier": args.carrier, "type": 1},
        "settings": {"currency": "COP"},
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{base_url}/ship/rate/", json=rate_payload, headers=headers)
            ms = (time.time() - t0) * 1000
            body = resp.json()
            ok, detail = _validate_keys("rate", body, ["totalPrice"])
            if ok:
                rate = body["data"][0] if isinstance(body.get("data"), list) else body["data"]
                detail = f"price={rate.get('totalPrice')} service={rate.get('service')}"
                summary["rate"] = {"price": rate.get("totalPrice"), "service": rate.get("service")}
            results.append(("rate", ok, ms, detail))
    except Exception as e:
        results.append(("rate", False, (time.time() - t0) * 1000, f"exception: {e}"))

    # ── 2. Generate label (solo si rate ok) ────────────────────────────────
    tracking_number: str | None = None
    if results[-1][1]:
        gen_payload = {
            "origin": origin,
            "destination": destination,
            "packages": [package],
            "shipment": {
                "carrier": args.carrier,
                "service": summary["rate"].get("service") or "ground",
                "type": 1,
            },
            "settings": {"currency": "COP", "printFormat": "PDF", "printSize": "STOCK_4X6"},
        }
        t0 = time.time()
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{base_url}/ship/generate/", json=gen_payload, headers=headers)
                ms = (time.time() - t0) * 1000
                body = resp.json()
                ok, detail = _validate_keys("generate", body, ["trackingNumber"])
                if ok:
                    data = body["data"] if isinstance(body.get("data"), dict) else body["data"][0]
                    tracking_number = data.get("trackingNumber")
                    detail = f"tracking={tracking_number}"
                    summary["generate"] = {"tracking": tracking_number}
                results.append(("generate", ok, ms, detail))
        except Exception as e:
            results.append(("generate", False, (time.time() - t0) * 1000, f"exception: {e}"))
    else:
        results.append(("generate", False, 0, "skip — rate falló"))

    # ── 3. Tracking ────────────────────────────────────────────────────────
    if tracking_number:
        track_payload = {"trackingNumbers": [tracking_number], "carrier": args.carrier}
        t0 = time.time()
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(f"{base_url}/ship/generaltrack/", json=track_payload, headers=headers)
                ms = (time.time() - t0) * 1000
                body = resp.json()
                ok, detail = _validate_keys("tracking", body, ["content"])
                if ok:
                    data = body["data"] if isinstance(body.get("data"), dict) else body["data"][0]
                    status = data.get("content", {}).get("status")
                    detail = f"status={status}"
                    summary["track"] = {"status": status}
                results.append(("tracking", ok, ms, detail))
        except Exception as e:
            results.append(("tracking", False, (time.time() - t0) * 1000, f"exception: {e}"))
    else:
        results.append(("tracking", False, 0, "skip — sin tracking_number"))

    # ── 4. Cancel ──────────────────────────────────────────────────────────
    if tracking_number and not args.no_cancel:
        # Envia /ship/cancel/ — cuerpo simple {trackingNumber, carrier}.
        cancel_payload = {"trackingNumber": tracking_number, "carrier": args.carrier}
        t0 = time.time()
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(f"{base_url}/ship/cancel/", json=cancel_payload, headers=headers)
                ms = (time.time() - t0) * 1000
                body = resp.json()
                # cancel puede retornar meta=success o data dict — flexible.
                if isinstance(body, dict) and body.get("meta") == "error":
                    err = body.get("error", {})
                    results.append(("cancel", False, ms,
                                    f"error code={err.get('code')} msg={err.get('message')}"))
                else:
                    results.append(("cancel", True, ms, "cancelled OK"))
                    summary["cancel"] = {"status": "ok"}
        except Exception as e:
            results.append(("cancel", False, (time.time() - t0) * 1000, f"exception: {e}"))
    elif args.no_cancel:
        results.append(("cancel", True, 0, "skip --no-cancel"))
    else:
        results.append(("cancel", False, 0, "skip — sin tracking"))

    # ── Reporte ────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("Resultados:")
    for label, ok, ms, detail in results:
        logger.info(_format_step(label, ok, ms, detail))

    all_ok = all(r[1] for r in results)
    total_ms = sum(r[2] for r in results)
    logger.info("")
    logger.info("=" * 70)
    if all_ok:
        logger.info(f"[OK] Smoke E2E PASS — total {total_ms:.0f}ms")
    else:
        logger.error(f"[FAIL] Smoke E2E con errores — total {total_ms:.0f}ms")
        logger.info(json.dumps(summary, indent=2, default=str)[:1500])
    logger.info("=" * 70)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

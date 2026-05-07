#!/usr/bin/env python3.11
"""Helper UAT — H.2.2 Fase A descubrimiento empírico de payloads Envia.

Invoca POST /ship/webhooktest/ (dossier sec. L.7b) para cada uno de los 5
tipos de webhook Envia, lo cual fuerza al servidor de Envia a enviar un
sample payload a nuestro endpoint capture. Permite descubrir el schema
real de cada tipo SIN esperar un envío real productivo.

Pre-requisito antes de ejecutar:
1. Stack local con make restart (orchestrator/api levantados)
2. Webhook capture endpoint registrado y accesible vía ngrok
3. URL del webhook copiada al panel Envia para los 5 tipos

Uso:
  python3.11 scripts/uat/envia_webhook_test_dispatch.py \\
    --tenant-id 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9 \\
    --tracking-number TEST-TRK-001

Si no se pasa --tracking-number, intenta usar el último shipment.tracking_number
del tenant.

Doc: https://docs.envia.com/docs/webhooks (sec. Test Webhook).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("envia_webhook_test")


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
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v)


def main():
    _load_env()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="UUID del tenant")
    parser.add_argument("--tracking-number", default=None,
                        help="Tracking number sandbox a probar (default: último del tenant)")
    parser.add_argument("--webhook-url", default=None,
                        help="URL del webhook receiver (default: lee de panel Envia)")
    parser.add_argument("--sandbox", action="store_true", default=True,
                        help="Usar sandbox Envia (default true)")
    args = parser.parse_args()

    # Cargar repo paths.
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "services" / "api"))

    from supabase import create_client
    sb = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    # Resolver tracking_number si no se pasó.
    tracking_number = args.tracking_number
    if not tracking_number:
        res = (
            sb.table("shipments")
            .select("tracking_number, created_at, status")
            .eq("tenant_id", args.tenant_id)
            .not_.is_("tracking_number", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.error(
                "[ERROR] No hay shipments con tracking_number para tenant %s. "
                "Generar uno primero con EnviaClient.generate_label() o pasar "
                "--tracking-number explícito.",
                args.tenant_id,
            )
            sys.exit(1)
        tracking_number = rows[0]["tracking_number"]
        logger.info(
            "[INFO] Usando último shipment del tenant: tracking=%s status=%s",
            tracking_number, rows[0].get("status"),
        )

    # Resolver webhook_url. NOTA: idealmente Envia ya lo tiene registrado en
    # panel; este endpoint solo dispara el envío al URL ya registrado para
    # cada type. Si Envia requiere webhook_url en body del test, lo pasamos.
    webhook_url = args.webhook_url
    if not webhook_url:
        # Default ngrok current — el founder puede override.
        webhook_url = (
            "https://francesco-unoiled-damion.ngrok-free.dev"
            "/api/v1/webhooks/envia/"
            f"{args.tenant_id}"
            "/wFLtYAt6z0gGhkvCNJyDN0-bfBlAQ5VatbYoTHcxN14"
        )

    # Cargar token Envia del tenant.
    creds_res = (
        sb.table("tenant_integrations")
        .select("credentials, status, meta")
        .eq("tenant_id", args.tenant_id)
        .eq("provider", "envia")
        .single()
        .execute()
    )
    if not creds_res.data:
        logger.error(
            "[ERROR] tenant %s no tiene integración Envia configurada. "
            "Settings → Integraciones → Envia primero.",
            args.tenant_id,
        )
        sys.exit(1)
    creds = (creds_res.data or {}).get("credentials") or {}
    api_token = creds.get("api_token")
    if not api_token:
        # fallback: vault helper
        try:
            from vault_helper import VaultHelper, resolve_secret
            api_token = resolve_secret(VaultHelper(sb), creds, "api_token")
        except Exception as e:
            logger.error("[ERROR] no se pudo resolver api_token Envia: %s", e)
            sys.exit(1)
    if not api_token:
        logger.error("[ERROR] api_token Envia no encontrado en tenant_integrations.credentials")
        sys.exit(1)

    # Endpoint Envia /ship/webhooktest/ (sandbox vs prod).
    base_url = "https://api-test.envia.com" if args.sandbox else "https://api.envia.com"
    url = f"{base_url}/ship/webhooktest/"

    import httpx
    payload = {
        "tracking_number": tracking_number,
        "webhook_url": webhook_url,
    }
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    logger.info("=" * 70)
    logger.info("[ENVIA TEST WEBHOOK] Disparando webhook test")
    logger.info("  Endpoint:  %s", url)
    logger.info("  Tracking:  %s", tracking_number)
    logger.info("  Target:    %s", webhook_url)
    logger.info("  Tenant:    %s", args.tenant_id)
    logger.info("=" * 70)

    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(url, headers=headers, json=payload)
            logger.info("[RESPUESTA] HTTP %d", r.status_code)
            try:
                body = r.json()
                import json as _json
                logger.info("[BODY]\n%s", _json.dumps(body, indent=2, ensure_ascii=False))
            except Exception:
                logger.info("[BODY raw] %s", r.text[:1000])
    except Exception as e:
        logger.error("[ERROR] request falló: %s", e)
        sys.exit(2)

    logger.info("=" * 70)
    logger.info("[INSTRUCCIONES] Verifica logs API + tabla envia_webhook_capture_log:")
    logger.info("  1. Logs:    docker logs (o tail -f /home/ansible/commerce-ops-local/logs/api.log) | grep ENVIA_WH")
    logger.info("  2. SQL:     SELECT * FROM envia_webhook_capture_log ORDER BY received_at DESC LIMIT 10;")
    logger.info("  3. Si Envia dispara webhook(s), verás filas insertadas con")
    logger.info("     headers_json + parsed_body + inferred_type capturados.")


if __name__ == "__main__":
    main()

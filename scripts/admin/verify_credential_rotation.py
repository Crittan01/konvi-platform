#!/usr/bin/env python3.11
"""Verificación post-rotación de credenciales — Runbook credential-rotation.md §3.

Corre los healthchecks live que prueban que cada credencial rotada quedó
operativa, y emite evidencia (tabla + exit code) para archivar en la fila B2
de docs/PLAN.md. Solo lectura: ningún check tiene efectos laterales.

Uso:
    python3.11 scripts/admin/verify_credential_rotation.py
    python3.11 scripts/admin/verify_credential_rotation.py \
        --internal-secret <nuevo> --tenant-id <uuid tenant real>

Checks core (sin flags): web /login, api /health + /health/ready (lee DB con
SUPABASE_SECRET_KEY), connector /health + /api/v1/whatsapp/health/metrics
(contadores hmac_ok/vault — Meta App Secret + Vault), orchestrator /health
(200 = worker vivo; 503 si heartbeat >120s).

Checks con --internal-secret (+ --tenant-id): prueban el secret NUEVO en los
dos validadores: orchestrator /agentic/metrics (200) y api dual-auth
GET /api/v1/orders/<uuid-nil> (≠400/401 = secret aceptado; 404 esperado).

Exit code: 0 = todo verde, 1 = algún check falló.
"""
import argparse
import sys
import uuid

import httpx

PROD = {
    "web": "https://konvi-web.onrender.com",
    "api": "https://konvi-api.onrender.com",
    "connector": "https://konvi-connector.onrender.com",
    "orchestrator": "https://konvi-orchestrator.onrender.com",
}
TIMEOUT = httpx.Timeout(15.0, connect=10.0)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}: {detail}")


def get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    return client.get(url, timeout=TIMEOUT, follow_redirects=False, **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--internal-secret", default="", help="Nuevo INTERNAL_SERVICE_SECRET (activa checks dual-auth)")
    ap.add_argument("--tenant-id", default="", help="UUID de tenant real (requerido por /agentic/metrics)")
    for svc in PROD:
        ap.add_argument(f"--{svc}-url", default=PROD[svc], help=f"Override URL {svc}")
    args = ap.parse_args()
    base = {svc: getattr(args, f"{svc}_url").rstrip("/") for svc in PROD}

    with httpx.Client() as c:
        # ── Web ────────────────────────────────────────────────────────────
        try:
            r = get(c, f"{base['web']}/login")
            check("web /login", r.status_code in (200, 307, 308), f"HTTP {r.status_code}")
        except Exception as exc:
            check("web /login", False, f"sin respuesta: {exc}")

        # ── API: liveness + readiness (esta última valida SUPABASE_SECRET_KEY
        # contra la DB — es la prueba de la rotación de la key de Supabase) ──
        for path in ("/health", "/health/ready"):
            try:
                r = get(c, f"{base['api']}{path}")
                check(f"api {path}", r.status_code == 200, f"HTTP {r.status_code}")
            except Exception as exc:
                check(f"api {path}", False, f"sin respuesta: {exc}")

        # ── Connector: metrics público (contadores HMAC Meta + Vault) ──────
        try:
            r = get(c, f"{base['connector']}/health")
            check("connector /health", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as exc:
            check("connector /health", False, f"sin respuesta: {exc}")
        try:
            r = get(c, f"{base['connector']}/api/v1/whatsapp/health/metrics")
            ok = r.status_code == 200
            detail = f"HTTP {r.status_code}"
            if ok:
                body = r.json()
                detail += f" — snapshot: {str(body)[:160]}"
            check("connector /api/v1/whatsapp/health/metrics", ok, detail)
        except Exception as exc:
            check("connector metrics", False, f"sin respuesta: {exc}")

        # ── Orchestrator: /health 200 = worker con heartbeat <120s ─────────
        try:
            r = get(c, f"{base['orchestrator']}/health")
            check("orchestrator /health (worker vivo)", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as exc:
            check("orchestrator /health", False, f"sin respuesta: {exc}")

        # ── Checks dual-auth del INTERNAL_SERVICE_SECRET nuevo ─────────────
        if args.internal_secret:
            h = {"X-Internal-Service-Secret": args.internal_secret}
            if args.tenant_id:
                try:
                    r = get(c, f"{base['orchestrator']}/agentic/metrics",
                            params={"tenant_id": args.tenant_id}, headers=h)
                    check("orchestrator /agentic/metrics (secret nuevo)", r.status_code == 200,
                          f"HTTP {r.status_code}")
                except Exception as exc:
                    check("orchestrator /agentic/metrics", False, f"sin respuesta: {exc}")
            else:
                print("  ⏭️  /agentic/metrics omitido (falta --tenant-id)")
            try:
                hdrs = {**h, "X-Tenant-Id": args.tenant_id or str(uuid.uuid4())}
                r = get(c, f"{base['api']}/api/v1/orders/{uuid.UUID(int=0)}", headers=hdrs)
                # Secret aceptado → no puede ser 400 (missing tenant) ni 401.
                # Con tenant real + uuid-nil esperado 404; secret malo → 401.
                check("api dual-auth orders (secret nuevo)", r.status_code not in (400, 401),
                      f"HTTP {r.status_code} (401/400 = secret RECHAZADO; 404/200 = aceptado)")
            except Exception as exc:
                check("api dual-auth orders", False, f"sin respuesta: {exc}")
        else:
            print("  ⏭️  checks dual-auth omitidos (sin --internal-secret)")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'='*52}\n{len(results) - len(failed)}/{len(results)} checks verdes"
          + (f" — FALLAN: {', '.join(failed)}" if failed else " — TODO VERDE"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

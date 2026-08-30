#!/usr/bin/env python3.11
"""T4-01 — verificación empírica de spoofing de cf-connecting-ip contra konvi-api en Render.

RESULTADO (verificado 2026-08-30, cierre auditoría OWASP Y3 — canario corrido contra prod):
  A) POST sin headers de IP                    → 403
  B) cf-connecting-ip: 1.2.3.4 (random)        → 403
  C) cf-connecting-ip: 54.88.218.97 (allowlist MeLi) → 403  ← el bypass NO funciona
  D) X-Forwarded-For leftmost con IP MeLi      → 403
  Logs de app: `meli_webhook.rejected_origin ip=<IP REAL del cliente>` — el edge de
  Cloudflare QUE FRONTEA Render (`server: cloudflare` presente también en
  konvi-api.onrender.com) SOBRESCRIBE cf-connecting-ip con la IP real del cliente.
  No existe ruta al origen que no pase por el edge CF → el allowlist de IP es sólido
  con TRUSTED_CLIENT_IP_HEADER=cf-connecting-ip (seteada en Render) + el fail-closed
  de _verify_meli_origin (503 si falta la config en producción).
  Por eso el "edge-proof header" quedó DECIDIDO-NO-IMPLEMENTAR: evidencia de que el
  residual no existe (ver docs/auditoria_seguridad_cierre_2026-08-29.md §Y3).

Subcomandos: precheck | activate | wait | test | logs | cleanup | wait2
  - `test` NO requiere credenciales (solo sondas HTTP al webhook).
  - precheck/activate/wait/logs/cleanup/wait2 usan RENDER_API_KEY (la lee de
    .env.prd-backup o .env.prod SIN imprimirla).
Enmascara la IP pública propia (primeros 2 octetos visibles). No toca git ni docs/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_CANDIDATES = (".env.prd-backup", ".env.prod")
API = "https://api.render.com/v1"
SID = "srv-d8e9mk4m0tmc73elvmeg"  # konvi-api
BASE = "https://konvi-api.onrender.com"
WEBHOOK = f"{BASE}/api/v1/meli/webhook"
CANARY_KEY = "XFF_CANARY"
STATE = os.path.join(ROOT, "scratch", ".t4_01_state.json")

_KEY_CACHE: str | None = None


def api_key() -> str:
    """Lazy: solo los subcomandos que hablan con la Render API la necesitan."""
    global _KEY_CACHE
    if _KEY_CACHE:
        return _KEY_CACHE
    for name in ENV_CANDIDATES:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("RENDER_API_KEY="):
                    _KEY_CACHE = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return _KEY_CACHE
    sys.exit(f"RENDER_API_KEY no encontrada en {' ni '.join(ENV_CANDIDATES)}")


def mask(text: str) -> str:
    """Enmascara la IP pública propia (primeros 2 octetos)."""
    ip = STATE_D.get("my_ip", "")
    if ip:
        parts = ip.split(".")
        text = text.replace(ip, f"{parts[0]}.{parts[1]}.x.x")
    return text


def api(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read().decode()
            return res.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:500]
        return e.code, raw


def save_state(**kw) -> None:
    STATE_D.update(kw)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(STATE_D, fh, indent=2)


def load_state() -> dict:
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


STATE_D = load_state()


def my_public_ip() -> str:
    if STATE_D.get("my_ip"):
        return STATE_D["my_ip"]
    with urllib.request.urlopen("https://ifconfig.me", timeout=15) as res:
        ip = res.read().decode().strip()
    save_state(my_ip=ip)
    return ip


def latest_deploy() -> dict:
    code, data = api("GET", f"/services/{SID}/deploys?limit=1")
    if code != 200 or not data:
        sys.exit(f"deploys: HTTP {code}: {mask(str(data))}")
    return data[0]["deploy"]


def get_owner_id() -> str:
    if STATE_D.get("owner_id"):
        return STATE_D["owner_id"]
    code, data = api("GET", f"/services/{SID}")
    if code == 200 and isinstance(data, dict):
        oid = data.get("ownerId")
        if oid:
            save_state(owner_id=oid)
            return oid
    code, owners = api("GET", "/owners?limit=20")
    if code != 200:
        sys.exit(f"owners: HTTP {code}")
    for item in owners:
        oid = item["owner"]["id"]
        c2, svcs = api("GET", f"/services?ownerId={oid}&limit=50")
        if c2 == 200 and any(s["service"]["id"] == SID for s in svcs):
            save_state(owner_id=oid)
            return oid
    sys.exit("ownerId no localizado")


def health() -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=30) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # timeout/conn — servicio aún caído
        return 0, str(e)


def cmd_precheck() -> None:
    code, svc = api("GET", f"/services/{SID}")
    if code != 200:
        sys.exit(f"service: HTTP {code}: {mask(str(svc))}")
    print(f"servicio: {svc.get('name')} tipo={svc.get('type')} suspended={svc.get('suspended')}")
    print(f"ownerId: {get_owner_id()}")
    code, var = api("GET", f"/services/{SID}/env-vars/{CANARY_KEY}")
    if code == 200 and isinstance(var, dict):
        ev = var.get("envVar", var)
        print(f"{CANARY_KEY} preexistente: value={ev.get('value')!r} → cleanup restaurará este valor")
        save_state(preexisting=ev.get("value"))
    else:
        print(f"{CANARY_KEY} no existe (HTTP {code}) → cleanup la BORRARÁ")
        save_state(preexisting=None)
    d = latest_deploy()
    print(f"deploy actual: {d['id']} status={d['status']} createdAt={d['createdAt']}")
    save_state(deploy_before=d["id"])
    ip = my_public_ip()
    print(f"IP pública propia: {ip.split('.')[0]}.{ip.split('.')[1]}.x.x (enmascarada)")
    print(f"health: {health()}")


def cmd_activate() -> None:
    save_state(activate_ts=time.time())
    code, data = api("PUT", f"/services/{SID}/env-vars/{CANARY_KEY}", {"value": "1"})
    print(f"PUT env-vars/{CANARY_KEY}=1 → HTTP {code}: {mask(str(data))[:200]}")
    if code not in (200, 201):
        sys.exit("fallo al activar canario")
    d = latest_deploy()
    print(f"deploy tras PUT: {d['id']} status={d['status']} createdAt={d['createdAt']}")
    if d["id"] != STATE_D.get("deploy_before"):
        print("→ el cambio de env var DISPARÓ un redeploy nuevo")
        save_state(deploy_after=d["id"])
    else:
        print("→ aún no aparece deploy nuevo; 'wait' lo detectará")


def cmd_wait() -> None:
    """Espera a que un deploy posterior a `deploy_before` quede live y health dé 200."""
    d0 = STATE_D.get("deploy_before")
    deadline = time.time() + 1500
    target = None
    while time.time() < deadline:
        d = latest_deploy()
        print(f"[{now_iso()}] deploy {d['id']} status={d['status']}", flush=True)
        if d["id"] != d0 and d["status"] == "live":
            target = d["id"]
            break
        if d["id"] != d0 and d["status"] in ("build_failed", "update_failed", "canceled"):
            sys.exit(f"deploy {d['id']} falló: {d['status']}")
        time.sleep(20)
    if not target:
        sys.exit("timeout esperando deploy live")
    save_state(deploy_after=target)
    # health hasta 200 (cold start post-deploy)
    while time.time() < deadline:
        code, body = health()
        if code == 200:
            print(f"health 200: {body}")
            return
        print(f"[{now_iso()}] health {code} — reintentando", flush=True)
        time.sleep(10)
    sys.exit("timeout esperando health 200")


def post_probe(spoof: str | None, xff: str | None = None) -> tuple[int, str]:
    body = json.dumps({"topic": "xff_canary_probe"}).encode()  # sin resource/user_id → no-op
    headers = {"Content-Type": "application/json", "User-Agent": "t4-01-canary-probe"}
    if spoof:
        headers["cf-connecting-ip"] = spoof
    if xff:
        headers["X-Forwarded-For"] = xff
    req = urllib.request.Request(WEBHOOK, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def cmd_test() -> None:
    """Sondas de spoofing. TODO debe dar 403; cualquier 2xx = bypass del allowlist."""
    ip = my_public_ip()
    save_state(test_ts=time.time())
    print(f"IP real del cliente: {ip.split('.')[0]}.{ip.split('.')[1]}.x.x (enmascarada)")
    print(f"test_ts (epoch UTC): {STATE_D['test_ts']:.0f} = {now_iso()}")
    failures = 0

    def check(label: str, code: int, body: str) -> None:
        nonlocal failures
        ok = code == 403
        failures += 0 if ok else 1
        print(f"{label} → HTTP {code} {mask(body)}  {'✅' if ok else '🔴 BYPASS!'}")

    check("A) normal                          ", *post_probe(None))
    time.sleep(2)
    check("B) cf-connecting-ip: 1.2.3.4        ", *post_probe("1.2.3.4"))
    time.sleep(2)
    check("C) cf-connecting-ip: 54.88.218.97 MeLi", *post_probe("54.88.218.97"))
    time.sleep(2)
    check("D) XFF leftmost: 54.88.218.97 MeLi   ", *post_probe(None, xff="54.88.218.97"))
    if failures:
        sys.exit(f"🔴 {failures} sonda(s) NO rechazadas — allowlist vulnerable")
    print("✅ 4/4 rechazadas — allowlist sólido (topología Render=Cloudflare verificada)")


def cmd_logs() -> None:
    oid = get_owner_id()
    fmt = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start = fmt(STATE_D.get("test_ts", time.time()) - 300)
    end = fmt(time.time() + 60)
    # type=app: logs de aplicación (logger.info del canario)
    path = (f"/logs?ownerId={oid}&resource={SID}&startTime={start}&endTime={end}"
            f"&direction=forward&limit=500&type=app")
    code, data = api("GET", path)
    if code != 200:
        print(f"logs con type=app → HTTP {code}; reintentando sin filtro type")
        path = (f"/logs?ownerId={oid}&resource={SID}&startTime={start}&endTime={end}"
                f"&direction=forward&limit=500")
        code, data = api("GET", path)
        if code != 200:
            sys.exit(f"logs: HTTP {code}: {mask(str(data))[:300]}")
    logs = data.get("logs", []) if isinstance(data, dict) else []
    print(f"total líneas app en ventana: {len(logs)} hasMore={data.get('hasMore')}")
    hits = []
    for entry in logs:
        msg = entry.get("message", "")
        if "XFF_CANARY" in msg or "meli_webhook" in msg or "Webhook MeLi" in msg:
            ts = entry.get("timestamp", "")
            msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).rstrip()
            hits.append(f"{ts} {mask(msg)}")
    if not hits:
        print("NO se encontraron líneas del canario en la ventana.")
        print("Muestra de las últimas 10 líneas app:")
        for entry in logs[-10:]:
            msg = re.sub(r"\x1b\[[0-9;]*m", "", entry.get("message", "")).rstrip()
            print(f"  {entry.get('timestamp','')} {mask(msg)[:220]}")
    else:
        print(f"--- {len(hits)} líneas relevantes ---")
        for h in hits:
            print(h)
    print("Lo que prueba: `rejected_origin ip=` debe mostrar tu IP REAL, no la spoofeada.")


def cmd_cleanup() -> None:
    pre = STATE_D.get("preexisting")
    if pre is None:
        code, data = api("DELETE", f"/services/{SID}/env-vars/{CANARY_KEY}")
        print(f"DELETE env-vars/{CANARY_KEY} → HTTP {code}")
    else:
        code, data = api("PUT", f"/services/{SID}/env-vars/{CANARY_KEY}", {"value": pre})
        print(f"PUT env-vars/{CANARY_KEY}={pre!r} (restaurar) → HTTP {code}")
    if code not in (200, 201, 204):
        sys.exit(f"fallo cleanup: {mask(str(data))[:200]}")
    d0 = latest_deploy()["id"]
    print(f"deploy más reciente tras cleanup: {d0} — 'wait2' confirmará cuando quede live")


def cmd_wait2() -> None:
    """Espera al deploy disparado por el cleanup."""
    deadline = time.time() + 1500
    seen = set()
    while time.time() < deadline:
        d = latest_deploy()
        seen.add(d["id"])
        print(f"[{now_iso()}] deploy {d['id']} status={d['status']}", flush=True)
        if d["status"] == "live" and d["id"] not in (STATE_D.get("deploy_after"),):
            break
        if d["status"] in ("build_failed", "update_failed", "canceled"):
            sys.exit(f"deploy cleanup falló: {d['status']}")
        time.sleep(20)
    else:
        sys.exit("timeout esperando deploy cleanup")
    while time.time() < deadline:
        code, body = health()
        if code == 200:
            print(f"health final: {code} {body}")
            return
        time.sleep(10)
    sys.exit("timeout esperando health final")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


if __name__ == "__main__":
    cmds = {
        "precheck": cmd_precheck, "activate": cmd_activate, "wait": cmd_wait,
        "test": cmd_test, "logs": cmd_logs, "cleanup": cmd_cleanup, "wait2": cmd_wait2,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(f"uso: {sys.argv[0]} {{'|'.join(cmds)}}")
    cmds[sys.argv[1]]()

"""UAT: simula un webhook `transaction.updated` de Wompi FIRMADO correctamente.

Reproduce el algoritmo oficial de firma (SHA256 simple, no HMAC):
  concat(valores de signature.properties) + str(timestamp) + events_key → SHA256 upper
tal como lo valida `services/api/integrations/wompi_client.py::verify_event_signature`.

Permite ejercitar los caminos APPROVED / DECLINED / VOIDED y el rechazo por firma
inválida, sin depender de que Wompi entregue el webhook al sandbox local.

Guardado fail-closed.
Uso:
  python3.11 scripts/uat/_send_wompi_webhook.py APPROVED
  python3.11 scripts/uat/_send_wompi_webhook.py DECLINED
  python3.11 scripts/uat/_send_wompi_webhook.py APPROVED --bad-signature
  python3.11 scripts/uat/_send_wompi_webhook.py APPROVED --replay   # mismo checksum (idempotencia)
"""
from __future__ import annotations

import hashlib
import os
import json
import sys
import urllib.request
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, f"{REPO}/scripts")

creds: dict[str, str] = {}
with open(f"{REPO}/.env") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402

print(f"env_guard: {classify(creds)}")
assert_safe_target(creds, action="send_wompi_webhook (UAT)")

STATUS = (sys.argv[1] if len(sys.argv) > 1 else "APPROVED").upper()
BAD_SIG = "--bad-signature" in sys.argv
REPLAY = "--replay" in sys.argv
# Monto manipulado (webhook fraudulento): la firma se calcula sobre el monto FALSO,
# así que es criptográficamente válida — sólo el guard de monto puede detenerlo.
AMOUNT_OVERRIDE = next(
    (int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--amount=")), None
)
API_URL = os.environ.get("API_URL") or creds.get("API_URL", "http://localhost:8001")
# La `events_key` es POR TENANT y vive en Vault: es la que usa el API para verificar
# (wompi_webhook.py -> get_tenant_wompi_creds). Firmar con la del .env producía un
# `firma_invalida` que el API —correctamente— responde con 200 sin aplicar nada, y desde
# afuera parecía que el webhook se había perdido. Se lee de la MISMA fuente que el API.
def _events_key_del_tenant(tenant_id: str) -> str:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "wompi_client", f"{REPO}/services/api/integrations/wompi_client.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, f"{REPO}/services/api")
    spec.loader.exec_module(mod)
    from supabase import create_client as _cc
    _sb = _cc(creds["NEXT_PUBLIC_SUPABASE_URL"],
              creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"])
    _, ek, _env = mod.get_tenant_wompi_creds(_sb, tenant_id, raise_on_error=True)
    if not ek:
        sys.exit("ERROR: el tenant no tiene events_key configurada en Vault")
    return ek


from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"],
)
# El tenant de DEV quedó hardcodeado aquí y ese proyecto ya no existe: hoy el único
# entorno es konvi-prod. Se parametriza en vez de cambiar la constante, para que el script
# sirva igual el día que vuelva a haber más de un tenant.
TENANT = next(
    (a.split("=", 1)[1] for a in sys.argv if a.startswith("--tenant-id=")),
    "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9",
)

pay = (
    sb.table("payments")
    .select("order_id, wompi_link_id, amount_in_cents, status")
    .eq("tenant_id", TENANT).order("created_at", desc=True).limit(1).execute().data
)
if not pay:
    sys.exit("ERROR: no hay fila `payments` — generá primero el link de pago")
pay = pay[0]
print(f"payments: link={pay['wompi_link_id']} monto={pay['amount_in_cents']} status={pay['status']}")

# `timestamp` fijo en modo --replay para reproducir EXACTAMENTE el mismo checksum
# (así se prueba el dedup por checksum, no un evento nuevo).
timestamp = 1_800_000_000 if REPLAY else 1_800_000_000 + len(STATUS) + (AMOUNT_OVERRIDE or 0) % 97
txn_id = f"uat-txn-{pay['wompi_link_id']}-{STATUS.lower()}" + (f"-amt{AMOUNT_OVERRIDE}" if AMOUNT_OVERRIDE is not None else "")

txn = {
    "id": txn_id,
    "amount_in_cents": AMOUNT_OVERRIDE if AMOUNT_OVERRIDE is not None else pay["amount_in_cents"],
    "reference": str(pay["order_id"]),
    "customer_email": "camila.uat@konvi-qa.test",
    "currency": "COP",
    "payment_method_type": "CARD",
    "status": STATUS,
    "payment_link_id": pay["wompi_link_id"],
}
properties = ["transaction.id", "transaction.status", "transaction.amount_in_cents"]

data = {"transaction": txn}


def _traverse(root, dotted: str) -> str:
    cur = root
    for key in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key, "")
        else:
            return ""
    return "" if cur is None else str(cur)


EVENTS_KEY = _events_key_del_tenant(TENANT)
concat = "".join(_traverse(data, p) for p in properties) + str(timestamp) + EVENTS_KEY
checksum = hashlib.sha256(concat.encode()).hexdigest().upper()
if BAD_SIG:
    checksum = "0" * 64  # firma deliberadamente inválida

payload = {
    "event": "transaction.updated",
    "data": data,
    "environment": "test",
    "signature": {"properties": properties, "checksum": checksum},
    "timestamp": timestamp,
    "sent_at": "2026-07-20T13:00:00.000Z",
}

url = f"{API_URL}/api/v1/webhooks/wompi"
req = urllib.request.Request(
    url, data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
with urllib.request.urlopen(req, timeout=30) as r:
    print(f"POST {url} → HTTP {r.status} {r.read().decode()[:120]}")
print(f"enviado status={STATUS} bad_signature={BAD_SIG} replay={REPLAY} checksum={checksum[:12]}…")

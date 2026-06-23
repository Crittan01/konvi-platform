"""UAT helper script — webhook end-to-end persistence smoke test.

[LEGACY per ADR-0023 Model B — Rev. 110 2026-06-22]
Este script usa META_APP_SECRET del .env (modelo global pre-Model B).
Funcionalmente sólo válido contra Konvi Dev tenant (self-tenant). Para
validación per-tenant moderna ver tests/test_meta_hmac_model_b.py
y scripts/uat/e2e_chat.py.

Mantenido para UAT manual de Konvi Dev únicamente.
"""
import sys
import os
import hmac
import hashlib
import json
from fastapi.testclient import TestClient

env_path = "/home/ansible/workspaces/konvi-platform/.env"
try:
    with open(env_path, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k,v = line.strip().split("=",1)
                os.environ[k] = v.strip("\"").strip("'")
except Exception as e:
    print(f"Error reading .env: {e}")

sys.path.append("/home/ansible/workspaces/konvi-platform/services/connector-whatsapp")

from fastapi import FastAPI
from routers.webhook import router

APP_SECRET = os.environ.get("META_APP_SECRET", "")

app = FastAPI()
app.include_router(router)
client = TestClient(app)

print("=== INICIANDO E2E DB PERSISTENCE TEST ===")

meta_payload = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "123456789_WABA",
        "changes": [{
            "value": {
                "metadata": {
                    "display_phone_number": "15551234567",
                    "phone_number_id": "15557654321"
                },
                "messages": [{
                    "from": "5215551234567",
                    "id": "wamid.HBgLNTIxNTU1MT...==",
                    "type": "text",
                    "text": {"body": "¡Hola, me gustaría comprar un producto de prueba!"}
                }]
            }
        }]
    }]
}

payload_bytes = json.dumps(meta_payload).encode('utf-8')

real_hmac = hmac.new(
    key=APP_SECRET.encode("utf-8"),
    msg=payload_bytes,
    digestmod=hashlib.sha256
).hexdigest()

print("Enviando Webhook...")
res = client.post(
    "/webhook",
    content=payload_bytes,
    headers={"X-Hub-Signature-256": f"sha256={real_hmac}"}
)

if res.status_code == 200:
    print("✓ FastAPI Gateway retornó 200 FastPath OK")
    print("✓ Background Task de Supabase-py acaba de culminar. ¡Revisa tu tabla de Mensajes en Supabase!")
else:
    print(f"✖ Fallo. Status code: {res.status_code} - {res.text}")
    sys.exit(1)

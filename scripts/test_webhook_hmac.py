import sys
import os
import hmac
import hashlib
from fastapi.testclient import TestClient

# Carga manual del env para el test (DEBE OCURRIR ANTES DE ROUATERS)
env_path = "/home/ansible/workspaces/commerce-ops-platform/.env"
try:
    with open(env_path, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k,v = line.strip().split("=",1)
                os.environ[k] = v.strip("\"").strip("'")
except Exception as e:
    print(f"Error reading .env: {e}")

sys.path.append("/home/ansible/workspaces/commerce-ops-platform/services/connector-whatsapp")

from fastapi import FastAPI
from routers.webhook import router

APP_SECRET = os.environ.get("META_APP_SECRET", "")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")

app = FastAPI()
app.include_router(router)

client = TestClient(app)

print("=== INICIANDO TEST UNITARIO CORE WEBHOOK ===")

print("\n1. Test GET (Meta Challenge Handshake)...")
res_get = client.get(f"/webhook?hub.mode=subscribe&hub.verify_token={VERIFY_TOKEN}&hub.challenge=CHALLENGE_ACCEPTED")
if res_get.status_code == 200 and res_get.text == "CHALLENGE_ACCEPTED":
    print("✓ GET Subscripción de Meta exitosa")
else:
    print(f"✖ GET Falló: {res_get.status_code} - {res_get.text}")
    sys.exit(1)

print("\n2. Test POST (Ataque Malicioso - Bot / Hacker)...")
payload = b'{"object": "whatsapp_business_account", "entry": []}'
res_hack = client.post(
    "/webhook",
    content=payload,
    headers={"X-Hub-Signature-256": "sha256=123totallyfakehash"}
)
if res_hack.status_code == 403:
    print(f"✓ Hack rechazado con éxito: 403 Forbidden")
else:
    print(f"✖ ADVERTENCIA CRÍTICA: Hack pasó! Status code {res_hack.status_code} - {res_hack.text}")
    sys.exit(1)

print("\n3. Test POST (Mensaje Oficial Validado)...")
# Calculamos la firma matemáticamente precisa como si fueramos los servidores de Meta
real_hmac = hmac.new(
    key=APP_SECRET.encode("utf-8"),
    msg=payload,
    digestmod=hashlib.sha256
).hexdigest()

res_ok = client.post(
    "/webhook",
    content=payload,
    headers={"X-Hub-Signature-256": f"sha256={real_hmac}"}
)
if res_ok.status_code == 200:
    print("✓ Payload de WhatsApp oficial recibido, parseado, y devuelto 200 OK")
else:
    print(f"✖ Validación falló para firma real: {res_ok.status_code} - {res_ok.text}")
    sys.exit(1)

print("\n=== TODOS LOS TESTS ESTRICTOS PASADOS EXITOSAMENTE ===")

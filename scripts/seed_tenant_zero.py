import sys
from supabase import create_client, Client

env_path = "/home/ansible/workspaces/konvi-platform/.env"
creds = {}
try:
    with open(env_path, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                creds[k] = v.strip("\"").strip("'")
except Exception as e:
    print(f"Error reading .env: {e}")
    sys.exit(1)

URL = creds.get("NEXT_PUBLIC_SUPABASE_URL")
# IMPORTANTE: Usamos la KEY de Servicio, no la anónima, porque RLS rechaza writes anonímos
KEY = creds.get("SUPABASE_SERVICE_ROLE_KEY")

if not URL or not KEY:
    print("Faltan las variables maestras URL o KEY de servicio.")
    sys.exit(1)

# Guard fail-closed (segregación DEV/PROD): este script es TESTING-ONLY (crea un tenant
# y user de prueba). Aborta si el destino Supabase NO es un dev reconocido — deny-by-default
# sobre URL + DATABASE_URL + SUPABASE_PROJECT_REF. Override auditable: KONVI_ALLOW_PROD=1.
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _env_guard import assert_safe_target  # noqa: E402
assert_safe_target(creds, action="seed_tenant_zero (crea tenant/user de prueba)")

supabase: Client = create_client(URL, KEY)

ADMIN_EMAIL = "admin@commerce.local"
ADMIN_PASS = "SuperSecurePassword123!"

try:
    print(f"1. Creando o Recuperando Auth User: {ADMIN_EMAIL}...")
    try:
        user_resp = supabase.auth.admin.create_user({
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASS,
            "email_confirm": True
        })
        user_id = user_resp.user.id
        print(f"User recién creado con ID: {user_id}")
    except Exception as e:
        if "already" in str(e).lower() or "User already exists" in str(e):
            print("Usuario ya existía, recuperando UID...")
            users = supabase.auth.admin.list_users()
            user_id = next(u.id for u in users if u.email == ADMIN_EMAIL)
            print(f"User recuperado con ID: {user_id}")
        else:
            raise e

    print("2. Creando el Tenant Semilla...")
    tenant_resp = supabase.table("tenants").insert({
        "name": "Matriz Commerce Dev"
    }).execute()
    tenant_id = tenant_resp.data[0]["id"]
    print(f"Tenant creado con ID: {tenant_id}")

    print("3. Acoplando Usuario al Tenant (Auth Claims Trigger se activará)...")
    link_resp = supabase.table("tenant_users").insert({
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": "owner"
    }).execute()
    print("Vinculación exitosa!")
    
    print("\n================== CREACION EXITOSA ==================")
    print(f"EMAIL LOGIN: {ADMIN_EMAIL}")
    print(f"PASSWORD: {ADMIN_PASS}")
    print("Tenant ID Semilla:", tenant_id)
    print("Por favor documenta estas credenciales transitoriamente.")

except Exception as e:
    print(f"Error drástico en inyección: {e}")
    sys.exit(1)

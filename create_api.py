import os

base_dir = "/home/ansible/workspaces/commerce-ops-platform/services/api"
deps_dir = os.path.join(base_dir, "dependencies")
routers_dir = os.path.join(base_dir, "routers")

os.makedirs(deps_dir, exist_ok=True)
os.makedirs(routers_dir, exist_ok=True)

files = {
    "requirements.txt": """fastapi==0.109.2
uvicorn==0.27.1
pydantic==2.6.1
supabase==2.3.4
""",
    "README.md": """# API Core Síncrona (Backoffice)
El cerebro HTTP clásico de la aplicación. 
- Sirve al Frontend React.
- Mantiene dependencias estrictas de JWT validando Row Level Security dictados en Supabase.
""",
    "main.py": """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import products, conversations
from dependencies.auth import get_current_tenant

app = FastAPI(title="Commerce Ops Core API", description="Síncrona REST")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Ajustar a dominio en produccion
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router, prefix="/api/v1/products")
app.include_router(conversations.router, prefix="/api/v1/conversations")

@app.get("/health")
def health_check():
    return {"status": "ok"}
""",
    "dependencies/auth.py": """from fastapi import Request, HTTPException, Depends
from typing import Optional

async def get_current_tenant(request: Request) -> str:
    \"\"\"
    Middleware de Dependencia.
    Obliga a extraer el JWT del header Authorization,
    valida contra la clave secreta de JWT (o mock actual) y abstrae el
    tenant_id para setearlo en el Contexto de BD (Set app.current_tenant_id).
    \"\"\"
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth_header.split(" ")[1]
    
    # IMPORTANTE: Aquí se debe utilizar Supabase Client o libreria pyjwt para 
    # descifrar el secure-token y obtener el claim inyectado.
    # pseudo_claims = jwt.decode(token, SUPABASE_JWT_SECRET...)
    # tenant_id = pseudo_claims.get("app_metadata", {}).get("tenant_id")
    
    tenant_id = "mock-tenant-id-pending-validation"
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context missing")
        
    return tenant_id
""",
    "routers/__init__.py": "",
    "dependencies/__init__.py": "",
    "routers/products.py": """from fastapi import APIRouter, Depends
from dependencies.auth import get_current_tenant

router = APIRouter(tags=["Products"])

@router.get("/")
def get_products(tenant_id: str = Depends(get_current_tenant)):
    \"\"\"
    Retorna los productos filtrados universalmente bajo el `tenant_id`.
    La BBDD rechazará la request internamente vía RLS si este controller no le envía
    el contexto usando el RPC asigando en `packages/db`.
    \"\"\"
    return {"message": "Listado de Productos Seguros", "tenant": tenant_id}
""",
    "routers/conversations.py": """from fastapi import APIRouter, Depends
from dependencies.auth import get_current_tenant

router = APIRouter(tags=["Conversations"])

@router.get("/")
def get_inbox_threads(tenant_id: str = Depends(get_current_tenant)):
    \"\"\"
    Visualizará los últimos hilos del Inbox del Agent,
    filtrando estricatamente por el Auth Claim inyectado.
    \"\"\"
    return {"message": "Listado de Conversaciones (Inbox)", "tenant": tenant_id}
"""
}

for filepath, content in files.items():
    full_path = os.path.join(base_dir, filepath)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\\n")
    print("Created:", full_path)

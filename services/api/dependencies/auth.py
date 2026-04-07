from fastapi import Request, HTTPException, Depends
from typing import Optional

async def get_current_tenant(request: Request) -> str:
    """
    Middleware de Dependencia.
    Obliga a extraer el JWT del header Authorization,
    valida contra la clave secreta de JWT (o mock actual) y abstrae el
    tenant_id para setearlo en el Contexto de BD (Set app.current_tenant_id).
    """
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

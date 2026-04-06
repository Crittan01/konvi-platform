from fastapi import APIRouter, Depends
from dependencies.auth import get_current_tenant

router = APIRouter(tags=["Products"])

@router.get("/")
def get_products(tenant_id: str = Depends(get_current_tenant)):
    """
    Retorna los productos filtrados universalmente bajo el `tenant_id`.
    La BBDD rechazará la request internamente vía RLS si este controller no le envía
    el contexto usando el RPC asigando en `packages/db`.
    """
    return {"message": "Listado de Productos Seguros", "tenant": tenant_id}\n
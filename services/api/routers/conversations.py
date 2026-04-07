from fastapi import APIRouter, Depends
from dependencies.auth import get_current_tenant

router = APIRouter(tags=["Conversations"])

@router.get("/")
def get_inbox_threads(tenant_id: str = Depends(get_current_tenant)):
    """
    Visualizará los últimos hilos del Inbox del Agent,
    filtrando estricatamente por el Auth Claim inyectado.
    """
    return {"message": "Listado de Conversaciones (Inbox)", "tenant": tenant_id}

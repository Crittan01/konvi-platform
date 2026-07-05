"""
Router de indexación batch de Knowledge Base — espejo de /api/ai/index-pending.

F-transversales (drift D3): consolida el cómputo de embeddings en el servicio
`api` para poder retirar GEMINI_API_KEY del web. ADITIVO: el endpoint web sigue
funcionando hasta el cutover del founder.

Endpoint:
  POST /api/v1/ai/index-pending — genera embeddings de todos los docs KB activos
                                  del tenant que aún no tienen embedding.

Paridad con el web:
  • Solo roles de escritura (owner/manager) — un operator no dispara embeds
    facturables masivos.
  • Rate-limit por tenant+user+IP (6/h por defecto) — cada corrida es costosa.
  • Deja un evento en audit_log (best-effort): quién indexó cuántos docs y con
    qué versión de modelo.
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Request
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from dependencies.embeddings import embed_kb_document, get_embedding_model_version
from dependencies.security import RateLimitRule, build_rate_limit_dependency

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai_index"])

# 6/h como el web. include_user_id: por-usuario dentro del tenant.
RL_AI_INDEX = build_rate_limit_dependency(
    RateLimitRule(
        bucket="ai.index_pending",
        limit=int(os.getenv("API_RATE_LIMIT_AI_INDEX_PER_HOUR", "6")),
        window_seconds=3600,
    ),
    include_user_id=True,
)


def _embedding_to_pgvector(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def _actor_from_jwt(request: Request) -> tuple[Optional[str], Optional[str]]:
    """user_id (sub) + email del JWT, best-effort (no levanta si faltan)."""
    try:
        from dependencies.auth import _extract_jwt_payload
        payload = _extract_jwt_payload(request)
        return payload.get("sub"), payload.get("email")
    except Exception:  # noqa: BLE001
        return None, None


@router.post("/index-pending", response_model=dict, dependencies=[Depends(RL_AI_INDEX)])
async def index_pending_kb_docs(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    pending_res = (
        supabase.table("kb_documents")
        .select("id, title, content")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .is_("embedding", None)
        .execute()
    )
    pending = pending_res.data or []
    if not pending:
        return {"indexed": 0, "total": 0}

    model_version = get_embedding_model_version()
    indexed = 0
    for doc in pending:
        vec = embed_kb_document(doc.get("title") or "", doc.get("content") or "")
        if not vec:
            continue
        supabase.table("kb_documents").update({
            "embedding": _embedding_to_pgvector(vec),
            "embedding_model_version": model_version,
        }).eq("id", doc["id"]).eq("tenant_id", tenant_id).execute()
        indexed += 1

    # Audit trail best-effort (no rompe la respuesta si falla).
    try:
        user_id, user_email = _actor_from_jwt(request)
        supabase.table("audit_log").insert({  # tenant_filter:exempt:payload_includes_tenant_id
            "tenant_id":   tenant_id,
            "user_id":     user_id,
            "user_email":  user_email,
            "action":      "kb_doc.indexed_batch",
            "entity_type": "kb_doc",
            "entity_id":   None,
            "payload":     {"indexed": indexed, "total": len(pending), "model_version": model_version},
        }).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AI_INDEX] audit_log insert falló tenant=%s: %s", tenant_id[:8], exc)

    return {"indexed": indexed, "total": len(pending)}

"""
Router de Knowledge Base — CRUD con embedding server-side.

Rev. 72 — cierra el drift D3 (GEMINI_API_KEY ya no se expone al frontend).

Endpoints:
  GET    /api/v1/knowledge-base/             — listar docs                     [todos]
  POST   /api/v1/knowledge-base/             — crear doc + embed síncrono      [owner, manager]
  GET    /api/v1/knowledge-base/{id}         — detalle (sin retornar embedding completo)
  PATCH  /api/v1/knowledge-base/{id}         — actualizar; re-embed si cambia
                                                title o content                [owner, manager]
  DELETE /api/v1/knowledge-base/{id}         — soft-delete (is_active=false)   [owner, manager]
  POST   /api/v1/knowledge-base/{id}/reindex — fuerza re-embed                  [owner, manager]

Categorías canónicas (CHECK constraint en DB rev. 71):
  faq, negocio, politicas, productos, envios, pagos.

Si el embedding falla (Gemini down, modelo no disponible), el doc se persiste
con embedding=NULL. La página `/dashboard/knowledge-base` muestra banner
"indexing pending" para ese doc; el operador puede llamar `/{id}/reindex`.

MAX por tenant: 30 docs (alineado con frontend MAX_DOCS).
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.embeddings import embed_kb_document, get_embedding_model_version
from dependencies.security import RL_WRITE_DEFAULT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["KnowledgeBase"])

VALID_CATEGORIES = {"faq", "negocio", "politicas", "productos", "envios", "pagos"}
MAX_DOCS_PER_TENANT = 30
MAX_TITLE = 120
MAX_CONTENT = 3000


# ─── Modelos ─────────────────────────────────────────────────────────────────

class KbDocCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE)
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT)
    category: str = Field(default="faq")


class KbDocPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=MAX_TITLE)
    content: Optional[str] = Field(default=None, min_length=1, max_length=MAX_CONTENT)
    category: Optional[str] = None
    is_active: Optional[bool] = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_category(category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"Categoría inválida '{category}'. Válidas: {sorted(VALID_CATEGORIES)}",
        )


def _embedding_to_pgvector(values: list[float]) -> str:
    """Formato esperado por pgvector: '[0.1,0.2,...]' como text."""
    return "[" + ",".join(str(v) for v in values) + "]"


def _strip_embedding(row: dict) -> dict:
    """Quita el embedding del payload retornado al cliente (es ruido — 3072 floats)."""
    if isinstance(row, dict) and "embedding" in row:
        clean = dict(row)
        clean["has_embedding"] = clean.get("embedding") is not None
        clean.pop("embedding", None)
        return clean
    return row


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
def list_kb_docs(
    category: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    q = (
        supabase.table("kb_documents")
        .select("id, title, content, category, is_active, created_at, updated_at, embedding")
        .eq("tenant_id", tenant_id)
    )
    if category:
        _validate_category(category)
        q = q.eq("category", category)
    if is_active is not None:
        q = q.eq("is_active", is_active)
    res = q.order("updated_at", desc=True).limit(limit).execute()
    return [_strip_embedding(r) for r in (res.data or [])]


@router.post("/", response_model=dict, status_code=201, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="kb_doc", action="created")
async def create_kb_doc(
    body: KbDocCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    _validate_category(body.category)

    # Cap por tenant — cuenta SOLO docs activos. El cap acota el corpus RAG activo
    # (los inactivos no participan en match_kb_documents ni consumen espacio útil),
    # así desactivar/eliminar libera cupo de forma reversible sin borrar datos.
    # NOTA founder (pd[0]): la alternativa es hard-delete real; ver needs_founder.
    count_res = (
        supabase.table("kb_documents")
        .select("id", count="exact")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .execute()
    )
    if (count_res.count or 0) >= MAX_DOCS_PER_TENANT:
        raise HTTPException(
            status_code=409,
            detail=f"Límite de {MAX_DOCS_PER_TENANT} documentos activos alcanzado. "
                   f"Desactiva o elimina alguno para agregar nuevos.",
        )

    # Embedding síncrono. Si falla, persistimos con NULL → banner "pending" en UI.
    vec = embed_kb_document(body.title, body.content)
    payload: dict = {
        "tenant_id": tenant_id,
        "title":     body.title.strip(),
        "content":   body.content.strip(),
        "category":  body.category,
        "is_active": True,
    }
    if vec:
        payload["embedding"] = _embedding_to_pgvector(vec)
        # Versiona el modelo usado → permite detectar embeddings obsoletos y
        # disparar re-index masivo cuando se cambia de modelo (migración 20260527010000).
        payload["embedding_model_version"] = get_embedding_model_version()

    res = (
        supabase.table("kb_documents")  # tenant_filter:exempt:payload_includes_tenant_id
        .insert(payload)   # F18: insert ya retorna representation; .select().single() no existe en postgrest 2.28.3 → 500 en toda escritura
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="No fue posible crear el documento KB")
    return _strip_embedding(res.data[0])


@router.get("/{doc_id}", response_model=dict)
def get_kb_doc(
    doc_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    res = (
        supabase.table("kb_documents")
        .select("id, title, content, category, is_active, created_at, updated_at, embedding")
        .eq("id", doc_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Documento KB no encontrado")
    return _strip_embedding(res.data)


@router.patch("/{doc_id}", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="kb_doc", action="updated")
async def patch_kb_doc(
    doc_id: str,
    patch: KbDocPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    update: dict = {}
    if patch.title is not None:
        update["title"] = patch.title.strip()
    if patch.content is not None:
        update["content"] = patch.content.strip()
    if patch.category is not None:
        _validate_category(patch.category)
        update["category"] = patch.category
    if patch.is_active is not None:
        update["is_active"] = patch.is_active

    if not update:
        raise HTTPException(status_code=422, detail="Sin campos a actualizar")

    # Si cambió title o content, re-embed. Necesitamos el doc actual para componer.
    if "title" in update or "content" in update:
        cur_res = (
            supabase.table("kb_documents")
            .select("title, content")
            .eq("id", doc_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not cur_res or not cur_res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
            raise HTTPException(status_code=404, detail="Documento KB no encontrado")
        new_title = update.get("title", cur_res.data["title"])
        new_content = update.get("content", cur_res.data["content"])
        vec = embed_kb_document(new_title, new_content)
        update["embedding"] = _embedding_to_pgvector(vec) if vec else None
        # NULL cuando el embed falló (doc queda "por preparar"); versión conocida si ok.
        update["embedding_model_version"] = get_embedding_model_version() if vec else None

    res = (
        supabase.table("kb_documents")
        .update(update)
        .eq("id", doc_id)
        .eq("tenant_id", tenant_id)   # F18: update ya retorna representation; sin .select().single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Documento KB no encontrado")
    return _strip_embedding(res.data[0])


@router.delete("/{doc_id}", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="kb_doc", action="deleted")
async def delete_kb_doc(
    doc_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Soft-delete: marca is_active=False y limpia embedding (ahorra storage)."""
    res = (
        supabase.table("kb_documents")
        .update({"is_active": False, "embedding": None})
        .eq("id", doc_id)
        .eq("tenant_id", tenant_id)   # F18: update ya retorna representation
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Documento KB no encontrado")
    return res.data[0]


@router.post("/{doc_id}/reindex", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="kb_doc", action="updated")
async def reindex_kb_doc(
    doc_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Fuerza re-embed del doc. Útil cuando el embedding inicial falló."""
    cur = (
        supabase.table("kb_documents")
        .select("title, content")
        .eq("id", doc_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not cur or not cur.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Documento KB no encontrado")

    vec = embed_kb_document(cur.data["title"], cur.data["content"])
    if not vec:
        raise HTTPException(
            status_code=502,
            detail="Embedding service no disponible. Reintenta en unos minutos.",
        )

    res = (
        supabase.table("kb_documents")
        .update({
            "embedding": _embedding_to_pgvector(vec),
            "embedding_model_version": get_embedding_model_version(),
        })
        .eq("id", doc_id)
        .eq("tenant_id", tenant_id)   # F18: update ya retorna representation
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Documento KB no encontrado")
    return _strip_embedding({**res.data[0], "indexed": True})

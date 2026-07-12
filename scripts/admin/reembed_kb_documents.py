"""Re-embebe kb_documents con el modelo de embedding VIGENTE.

CONTEXTO (Fase 6 audit 2026-07-03): gemini-embedding-001 se retira (doc oficial) y su
fallback histórico text-embedding-004 ya está apagado. El default del código cambió a
gemini-embedding-2 (services/ai-orchestrator/llm_embed.py). Un modelo de embedding
distinto produce un espacio vectorial DISTINTO: los vectores viejos (embedding-001)
son incompatibles con queries de embedding-2 → la búsqueda semántica (RAG) del bot
devuelve basura hasta re-embeber TODOS los kb_documents con el modelo nuevo.

SECUENCIA CRÍTICA: correr este script INMEDIATAMENTE después de desplegar el cambio de
modelo (o antes, si el deploy no ha ocurrido, sabiendo que quedará consistente al
desplegar). Mientras docs y queries usen modelos distintos, el RAG está degradado.

Requiere env:
  NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY)
  GEMINI_API_KEY  (para llamar al modelo de embedding)
  Opcional: GEMINI_EMBEDDING_MODEL (default gemini-embedding-2), GEMINI_EMBEDDING_DIM (3072).

Uso:
  python3.11 scripts/admin/reembed_kb_documents.py --dry-run        # cuenta, no embebe
  python3.11 scripts/admin/reembed_kb_documents.py --yes            # re-embebe TODOS
  python3.11 scripts/admin/reembed_kb_documents.py --tenant <uuid> --yes
  python3.11 scripts/admin/reembed_kb_documents.py --yes --sleep 0.5 --limit 500
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# El helper de embedding + el formateador pgvector viven en services/api.
_API = os.path.join(os.path.dirname(__file__), "..", "..", "services", "api")
sys.path.insert(0, os.path.abspath(_API))

from supabase import create_client  # noqa: E402
from dependencies.embeddings import embed_kb_document  # noqa: E402
from lib.llm_embed import (  # noqa: E402
    GEMINI_EMBEDDING_MODEL, EMBEDDING_DIM, get_embedding_model_version,
)


def _pgvector(values: list[float]) -> str:
    """Formato pgvector: '[0.1,0.2,...]'. (Espejo de knowledge_base._embedding_to_pgvector.)"""
    return "[" + ",".join(str(v) for v in values) + "]"


def _client():
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Falta NEXT_PUBLIC_SUPABASE_URL y/o SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-embebe kb_documents con el modelo vigente.")
    ap.add_argument("--tenant", default=None, help="Limitar a un tenant_id (default: todos)")
    ap.add_argument("--limit", type=int, default=100000, help="Tope de documentos a procesar")
    ap.add_argument("--sleep", type=float, default=0.3, help="Pausa entre embeds (rate-limit)")
    ap.add_argument("--dry-run", action="store_true", help="Solo contar, no embeber")
    ap.add_argument("--yes", action="store_true", help="Confirmar ejecución real")
    args = ap.parse_args()

    if not args.dry_run and not args.yes and not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("Falta GEMINI_API_KEY (necesaria para embeber).")

    sb = _client()
    q = sb.table("kb_documents").select("id, tenant_id, title, content, is_active")
    if args.tenant:
        q = q.eq("tenant_id", args.tenant)
    rows = (q.limit(args.limit).execute().data) or []

    print(f"Modelo vigente: {GEMINI_EMBEDDING_MODEL} (dim {EMBEDDING_DIM})")
    print(f"kb_documents a procesar: {len(rows)}"
          + (f" (tenant {args.tenant})" if args.tenant else " (todos los tenants)"))

    if args.dry_run or not args.yes:
        print("DRY-RUN (o falta --yes): no se re-embebió nada. Reejecutar con --yes para aplicar.")
        return 0

    ok = failed = skipped = 0
    for i, r in enumerate(rows, 1):
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not title and not content:
            skipped += 1
            continue
        vec = embed_kb_document(title, content)
        if not vec:
            failed += 1
            print(f"  [{i}/{len(rows)}] FALLO embed doc={r['id']} tenant={r.get('tenant_id')}")
            continue
        # BLOQUE G-3 (fix): estampar también embedding_model_version. Antes el
        # re-embed dejaba la versión stale/NULL → el audit de drift + el guard de
        # query-time (match_kb_documents) no podían confiar en la columna, y un
        # re-embed no "sanaba" el registro de versión. Ahora queda coherente.
        sb.table("kb_documents").update({
            "embedding": _pgvector(vec),
            "embedding_model_version": get_embedding_model_version(),
        }).eq("id", r["id"]).eq("tenant_id", r["tenant_id"]).execute()
        ok += 1
        if i % 25 == 0:
            print(f"  ... {i}/{len(rows)} (ok={ok} fail={failed})")
        time.sleep(max(0.0, args.sleep))

    print(f"\nRE-EMBED COMPLETO: ok={ok} failed={failed} skipped={skipped} de {len(rows)}")
    if failed:
        print("HAY FALLOS: reejecutar el script re-procesa (idempotente); revisar rate-limit / GEMINI_API_KEY.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

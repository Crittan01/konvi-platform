-- BLOQUE G-3 — guard de drift de embedding en el RAG del bot.
--
-- Problema (audit Fase 6 + revisión): un kb_document embebido con un modelo de
-- embedding DISTINTO al de la query vive en un espacio vectorial incompatible →
-- la búsqueda semántica devuelve BASURA, sin detección. `match_kb_documents`
-- (20260427010000) filtra por tenant/activo/umbral pero NO por versión de modelo.
--
-- Fix: un OVERLOAD de 5 args que además filtra por `embedding_model_version`. Es
-- ADITIVO — el de 4 args queda intacto (cero riesgo para cualquier caller no
-- migrado). Los callers (kb_tool del bot + ai_preview) pasan la versión vigente
-- (get_embedding_model_version()). Tolera `embedding_model_version IS NULL`
-- (docs legacy sin versión) para NO romper el RAG hasta el re-embed; excluye solo
-- versiones KNOWN-distintas → fail-safe ante un futuro cambio de modelo.
--
-- ⚠️ INTERVENCION HUMANA REQUERIDA (no opcional): este guard es fail-open en NULL,
-- así que NO protege los docs actuales (en prod: 9 docs con versión NULL, posiblemente
-- embebidos con el modelo retirado gemini-embedding-001 → RAG degradado HOY). El fix
-- REAL del estado de datos es correr el re-embed:
--   RESPONSABLE: founder (service-role).
--   PASOS: python3.11 scripts/admin/reembed_kb_documents.py --yes  (o --tenant <uuid>).
--   INSUMOS: SUPABASE_SECRET_KEY + GEMINI_API_KEY.
--   CRITERIO DE EXITO: SELECT count(*) FROM kb_documents WHERE embedding IS NOT NULL
--     AND embedding_model_version IS NULL  →  0.
-- El script ya fue corregido (BLOQUE G-3) para estampar embedding_model_version.
-- Deadline externo: gemini-embedding-001 se retira 2026-07-14.

CREATE OR REPLACE FUNCTION match_kb_documents (
  query_embedding extensions.vector(3072),
  match_threshold float,
  match_count      int,
  t_id             uuid,
  p_model_version  text
)
RETURNS TABLE (
  id         uuid,
  title      text,
  content    text,
  category   text,
  similarity float
)
LANGUAGE sql STABLE
AS $$
  SELECT
    kb.id,
    kb.title,
    kb.content,
    kb.category,
    1 - (kb.embedding <=> query_embedding) AS similarity
  FROM kb_documents kb
  WHERE
    kb.tenant_id  = t_id
    AND kb.embedding IS NOT NULL
    AND kb.is_active  = true
    -- Guard de drift: incluye la versión vigente + los legacy sin versión (NULL);
    -- excluye docs con una versión de modelo KNOWN-distinta (espacio incompatible).
    AND (
      p_model_version IS NULL
      OR kb.embedding_model_version IS NULL
      OR kb.embedding_model_version = p_model_version
    )
    AND 1 - (kb.embedding <=> query_embedding) > match_threshold
  ORDER BY kb.embedding <=> query_embedding
  LIMIT match_count;
$$;

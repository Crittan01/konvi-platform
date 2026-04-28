-- Corrige dimensiones de embeddings: vector(768) → vector(3072)
--
-- Diagnóstico:
--   gemini-embedding-001 (modelo usado en web service y orquestador) retorna 3072 dims por defecto.
--   La columna era vector(768), causando que todos los inserts de embeddings fallaran silenciosamente.
--   Resultado: RAG nunca funcionó — el sistema usaba fallback (top-3 por categoría) siempre.
--
-- No hay datos que migrar: embedding IS NULL en todos los docs existentes.

ALTER TABLE public.kb_documents
  ALTER COLUMN embedding TYPE extensions.vector(3072)
  USING NULL;  -- todos son NULL, cast trivial

-- Actualizar la función match_kb_documents para aceptar vector(3072)
CREATE OR REPLACE FUNCTION match_kb_documents (
  query_embedding extensions.vector(3072),
  match_threshold float,
  match_count      int,
  t_id             uuid
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
    AND 1 - (kb.embedding <=> query_embedding) > match_threshold
  ORDER BY kb.embedding <=> query_embedding
  LIMIT match_count;
$$;

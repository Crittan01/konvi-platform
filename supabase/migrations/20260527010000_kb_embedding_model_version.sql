-- Rev. 106 — versionado del modelo embedding en kb_documents.
--
-- Permite detectar cuando el modelo cambia (e.g. swap futuro a
-- voyage-multilingual-3 o text-embedding-005) y disparar re-index
-- masivo de docs obsoletos. Sin esta columna, un cambio de modelo
-- deja embeddings cacheados en DB que ya no son semánticamente
-- coherentes con el modelo actual → similarity scores erróneos.
--
-- Formato del valor: "{model}:{dim}" — e.g. "gemini-embedding-001:3072".
-- Resuelto por `llm_embed.get_embedding_model_version()`.
--
-- Migración aditiva, sin breaking change. Docs existentes quedan con
-- embedding_model_version=NULL → se interpretan como "modelo desconocido"
-- y deben re-indexarse en el próximo full-reindex (manual o cron).

ALTER TABLE public.kb_documents
    ADD COLUMN IF NOT EXISTS embedding_model_version TEXT;

CREATE INDEX IF NOT EXISTS kb_documents_embedding_model_version_idx
    ON public.kb_documents (tenant_id, embedding_model_version)
    WHERE embedding IS NOT NULL;

COMMENT ON COLUMN public.kb_documents.embedding_model_version IS
    'Identificador del modelo embedding usado para indexar este doc '
    '(formato "model:dim"). NULL = modelo legacy/desconocido, debe '
    're-indexarse. Resuelto por llm_embed.get_embedding_model_version().';

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- Modify kb_documents
ALTER TABLE public.kb_documents ADD COLUMN IF NOT EXISTS embedding extensions.vector(768);

-- Create AI Agents table
CREATE TABLE IF NOT EXISTS public.ai_agents (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id uuid REFERENCES public.tenants(id) ON DELETE CASCADE NOT NULL,
    name text NOT NULL DEFAULT 'Vendedor Oficial',
    role_description text NOT NULL DEFAULT 'Eres el principal agente conversacional. Debes asistir al cliente cordialmente.',
    strict_guardrails boolean NOT NULL DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ai_agents_tenant_id_unique ON public.ai_agents (tenant_id);

-- Protect with RLS
ALTER TABLE public.ai_agents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants can manage their own AI agent" ON public.ai_agents FOR ALL USING (
    tenant_id IN (
        SELECT tu.tenant_id FROM public.tenant_users tu 
        WHERE tu.user_id = auth.uid()
    )
);

-- RPC for RAG (Cosine Similarity search)
CREATE OR REPLACE FUNCTION match_kb_documents (
  query_embedding extensions.vector(768),
  match_threshold float,
  match_count int,
  t_id uuid
)
RETURNS TABLE (
  id uuid,
  title text,
  content text,
  category text,
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
  FROM public.kb_documents kb
  WHERE kb.tenant_id = t_id
    AND kb.embedding IS NOT NULL
    AND kb.is_active = true
    AND 1 - (kb.embedding <=> query_embedding) > match_threshold
  ORDER BY kb.embedding <=> query_embedding
  LIMIT match_count;
$$;

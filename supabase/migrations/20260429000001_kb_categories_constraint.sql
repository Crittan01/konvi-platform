-- Rev. 68 — Knowledge Base: 6 categorías canónicas con CHECK constraint
--
-- Razón: hoy `kb_documents.category` es TEXT libre con default 'general'. El
-- usuario puede meter cualquier valor (riesgo de inconsistencia + UX confusa).
-- Además "General" funcionaba como cajón de sastre que confundía al tenant.
--
-- Decisión rev. 68: 6 categorías canónicas con guía clara del placeholder UI:
--   faq, negocio, politicas, productos, envios, pagos
--
-- Migración de valores existentes:
--   'general' → 'faq'  (cajón natural; el tenant puede recategorizar después)
--   'envios', 'pagos' → ya válidos si alguien los puso a mano
--   Cualquier otro valor desconocido → 'faq' (no perder docs por valor inválido)

-- 1) Default nuevo: 'faq' en lugar de 'general'.
ALTER TABLE public.kb_documents
  ALTER COLUMN category SET DEFAULT 'faq';

-- 2) Migrar valores existentes.
-- 'general' → 'faq'.
UPDATE public.kb_documents
   SET category = 'faq'
 WHERE category = 'general';

-- Cualquier valor fuera del nuevo enum → 'faq' (preservar el documento).
UPDATE public.kb_documents
   SET category = 'faq'
 WHERE category NOT IN ('faq', 'negocio', 'politicas', 'productos', 'envios', 'pagos');

-- 3) Drop constraint legacy si existe (idempotencia).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'kb_documents_category_check'
  ) THEN
    ALTER TABLE public.kb_documents DROP CONSTRAINT kb_documents_category_check;
  END IF;
END$$;

-- 4) Aplicar CHECK constraint con los 6 valores canónicos rev. 68.
ALTER TABLE public.kb_documents
  ADD CONSTRAINT kb_documents_category_check
  CHECK (category IN ('faq', 'negocio', 'politicas', 'productos', 'envios', 'pagos'));

COMMENT ON COLUMN public.kb_documents.category IS
  'Categoría canónica rev. 68. Valores: faq, negocio, politicas, productos, envios, pagos. Cada categoría tiene placeholder específico en UI; ver knowledge-base/page.tsx CATEGORY_GUIDES.';

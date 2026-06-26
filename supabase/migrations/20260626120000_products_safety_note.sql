-- A11 2026-06-26 — Nota de seguridad por producto (render garantizado).
--
-- Contexto: productos con riesgo de uso (aceites esenciales: no aplicar directo
-- en piel, diluir; concentrados; etc.) requieren una advertencia de uso seguro
-- que el bot SIEMPRE muestre. La descripción libre puede truncarse en el
-- contexto del LLM (~200 chars) y perder la advertencia. Un campo dedicado se
-- renderiza completo y con marcador ⚠️.
--
-- Aditivo, nullable: no rompe nada existente. El tenant lo puebla on-demand
-- solo para productos que lo ameriten (mayoría queda NULL = sin nota).

ALTER TABLE public.products
  ADD COLUMN IF NOT EXISTS safety_note TEXT;

COMMENT ON COLUMN public.products.safety_note IS
  'Advertencia de uso seguro mostrada SIEMPRE por el bot (ej. "Diluir antes de '
  'usar, no aplicar directo en piel"). NULL = sin advertencia. Render garantizado '
  '(no truncado) en el contexto del LLM con marcador ⚠️.';

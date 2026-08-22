-- =============================================================================
-- B-1 / Memoria conversacional — conversations.conversation_summary
-- Fecha: 2026-08-22 · Origen: auditoría bot 2026-08-21 (amnesia estructural:
-- ventana de 25 mensajes SIN resumen → el bot "olvida" lo hablado antes)
-- Tests: tests/agentic/test_b1_conversation_summary.py
--
-- Resumen rodante de la conversación para el LLM: cubre lo que quedó FUERA de
-- la ventana de 25 mensajes (la ventana cruda se mantiene intacta — varios
-- componentes determinísticos la leen). Se regenera con histeresis (>ventana
-- mensajes y >=K nuevos) y se inyecta como primer content de la ventana Gemini
-- (NUNCA en el system prompt — preserva el prefijo estable de caching, Track 6).
--
-- La verdad transaccional (montos, estados) NO vive aquí: el resumidor está
-- instruido para omitir cifras — el dinero sale de los bloques determinísticos
-- del carrito (ADR-0026) y los invariants validan contra DB, no contra history.
-- Hereda la RLS de conversations (aislamiento por tenant) — no requiere grants
-- nuevos (los writers/lectores son servicios con service_role).
-- =============================================================================

ALTER TABLE public.conversations
  ADD COLUMN IF NOT EXISTS conversation_summary JSONB;

COMMENT ON COLUMN public.conversations.conversation_summary IS
  'B-1: resumen rodante de la conversación para el LLM (memoria fuera de la ventana de 25 mensajes). '
  'Shape: {text, covers_until_created_at, updated_at, message_count}. '
  'Se regenera post-turn con histeresis y se inyecta como primer content de la ventana Gemini.';

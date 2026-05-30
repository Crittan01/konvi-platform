-- =============================================================================
-- Rev. 105 (Sem 4, H.4.1 follow-up) — Agrega 'opted_out' al CHECK constraint
-- de conversations.status.
--
-- Disparador: UAT founder 2026-05-06 reveló bug: H.4.1 STOP detector
-- intentaba setear status='opted_out' pero CHECK constraint solo aceptaba
-- {'bot_active', 'human_takeover', 'closed'}. UPDATE fallaba silently
-- (logged en orchestrator.log) — flow funcional sigue OK gracias al
-- try-except envolvente, pero el status no se persistía.
--
-- Fix: drop + recreate CHECK incluyendo 'opted_out'. Migración aditiva,
-- no rompe filas existentes (todas tienen status ∈ {bot_active|human_takeover|closed}).
-- =============================================================================

-- Drop el constraint anterior.
ALTER TABLE public.conversations
    DROP CONSTRAINT IF EXISTS conversations_status_check;

-- Recrear con 'opted_out' agregado.
ALTER TABLE public.conversations
    ADD CONSTRAINT conversations_status_check
    CHECK (status = ANY (ARRAY[
        'bot_active'::text,
        'human_takeover'::text,
        'closed'::text,
        'opted_out'::text
    ]));

COMMENT ON CONSTRAINT conversations_status_check ON public.conversations IS
    'Estados canónicos de conversación. bot_active=bot procesa normal; '
    'human_takeover=operador interviene; closed=cerrada manual; '
    'opted_out=cliente revocó consent vía STOP keyword (rev. 105 H.4.1, '
    'no bloquea conversación futura — si cliente vuelve a escribir, '
    'orchestrator vuelve a bot_active).';

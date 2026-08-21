-- B6 (auditoría money-path 2026-08-21) — confirmación en dos turnos para cancelar
-- una orden PAGADA desde el bot.
--
-- Hallazgo: el intent de cancelación ejecutaba `cancel_order` directo (incl.
-- auto-void de CARD) con UN solo mensaje del cliente. Un malentendido del
-- detector o un arrepentimiento mal expresado disparaba un void de dinero real
-- sin confirmación.
--
-- Fix: si la orden está pagada (confirmed/processing/shipped o payment approved),
-- el bot primero PREGUNTA y persiste aquí el estado pendiente; solo ejecuta si el
-- siguiente mensaje del cliente confirma afirmativamente (TTL 30 min).
-- Órdenes pending_payment siguen cancelando en 1 turno (no hay dinero en juego).
--
-- Payload JSONB: {"order_id", "short_id", "total_amount", "created_at"}.
-- NULL = no hay confirmación pendiente. El dispatcher lo limpia al confirmar,
-- negar, expirar o cuando el cliente cambia de tema.
--
-- Forward-only. Idempotente (IF NOT EXISTS).

BEGIN;

ALTER TABLE public.conversations
    ADD COLUMN IF NOT EXISTS pending_cancel_confirmation JSONB;

COMMENT ON COLUMN public.conversations.pending_cancel_confirmation IS
    'B6: cancelación de orden PAGADA pendiente de confirmación (dos turnos). '
    'JSONB {order_id, short_id, total_amount, created_at} o NULL. '
    'Lo gestiona services/ai-orchestrator/agentic/cancel_intent_resolver.py + dispatcher.';

COMMIT;

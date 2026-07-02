-- F6 (roadmap producción) — SLA de human_takeover: ancla temporal que NO se renueva con inbounds.
--
-- BUG: worker.py filtra candidatos del SLA por `status='human_takeover' AND last_interaction_at < cutoff`.
-- last_interaction_at se renueva cada vez que el cliente escribe → una conversación escalada donde el cliente
-- sigue escribiendo nunca cae bajo el cutoff → el SLA jamás dispara (el operador nunca es alertado).
--
-- FIX (verificado adversarialmente, 20 agentes): estampar `human_takeover_at` en la TRANSICIÓN a
-- human_takeover con un TRIGGER BEFORE UPDATE. Cubre los 15 puntos de entrada (helper + ~10 updates directos
-- inline en orchestrator/dispatcher/escalation/degraded/fake_escalation + el PATCH del operador vía API) SIN
-- tocar Python — un solo punto de verdad, idempotente (no re-estampa si ya estaba en takeover; limpia al salir).
-- Precedente exacto: enqueue_human_takeover_notification (20260420000003) dispara en la misma transición.
-- Rechazado el fix per-site ('human_takeover_at': now() inline): now() no está en scope (NameError) y parchear
-- 1 de 15 sitios dejaría NULL en los otros 14 → SLA roto para esos paths.

ALTER TABLE public.conversations
  ADD COLUMN IF NOT EXISTS human_takeover_at TIMESTAMPTZ;

-- Índice parcial: el cron filtra status='human_takeover' AND human_takeover_at < cutoff.
CREATE INDEX IF NOT EXISTS idx_conversations_human_takeover_at
  ON public.conversations (human_takeover_at)
  WHERE status = 'human_takeover';

-- Trigger: estampa NOW() al ENTRAR a human_takeover; limpia a NULL al SALIR (return-to-bot / closed).
-- Solo un BEFORE trigger puede modificar NEW.* y persistirlo. El de notificación (AFTER) es independiente.
CREATE OR REPLACE FUNCTION public.stamp_human_takeover_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.status = 'human_takeover' AND OLD.status IS DISTINCT FROM 'human_takeover' THEN
    NEW.human_takeover_at := NOW();       -- entrada real (no re-estampa si ya estaba en takeover)
  ELSIF NEW.status IS DISTINCT FROM 'human_takeover' AND OLD.status = 'human_takeover' THEN
    NEW.human_takeover_at := NULL;        -- salida: la próxima escalación vuelve a estampar
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS conversations_stamp_human_takeover_at ON public.conversations;
CREATE TRIGGER conversations_stamp_human_takeover_at
  BEFORE UPDATE OF status ON public.conversations
  FOR EACH ROW
  EXECUTE FUNCTION public.stamp_human_takeover_at();

-- Backfill (ÚLTIMO, tras el trigger, para cubrir cualquier transición durante la migración): valor más fiel =
-- created_at del último escalation_audit (instante real de escalación); fallbacks last_interaction_at → created_at
-- para no dejar NULL (un NULL se auto-excluiría del filtro '<' del worker → perdería cobertura).
UPDATE public.conversations c
SET human_takeover_at = COALESCE(
      (SELECT max(m.created_at) FROM public.messages m
        WHERE m.conversation_id = c.id AND m.content_type = 'escalation_audit'),
      c.last_interaction_at,
      c.created_at
    )
WHERE c.status = 'human_takeover' AND c.human_takeover_at IS NULL;

COMMENT ON COLUMN public.conversations.human_takeover_at IS
  'F6 SLA: instante de ENTRADA a human_takeover (estampado por trigger stamp_human_takeover_at). NO se renueva '
  'con inbounds del cliente (a diferencia de last_interaction_at). El cron SLA del worker lo usa como ancla.';

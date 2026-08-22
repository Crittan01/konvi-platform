-- =============================================================================
-- Track 6 / Meta — estados de template HSM vigentes en la doc oficial
-- Fecha: 2026-08-22 · Origen: matriz Track 6 (fetch live 2026-08-22,
-- developers.facebook.com/.../webhooks/reference/message_template_status_update)
--
-- Meta hoy emite eventos de estado que nuestro CHECK constraint rechazaba:
-- ARCHIVED, UNARCHIVED, DELETED, IN_APPEAL, LOCKED, REINSTATED, PENDING_DELETION
-- (el propio código lo advertía: "CHECK constraint DB rechazará",
-- connector template_events.py). Un template archivado/eliminado/reintegrado por
-- Meta llegaba con HMAC OK y el UPDATE reventaba → drift de estado silencioso.
--
-- Semántica (doc oficial):
--   REINSTATED / UNARCHIVED → el template vuelve a ser ENVIABLE (Meta lo restaura)
--   ARCHIVED / DELETED / PENDING_DELETION / LOCKED → terminal/no enviable
--   IN_APPEAL → en apelación, no enviable hasta resolución
-- El set de enviables vive en código (SENDABLE_STATUSES, template_events.py /
-- whatsapp_templates.py); la columna guarda el valor CRUDO de Meta (verdad forense).
-- =============================================================================

ALTER TABLE public.whatsapp_templates DROP CONSTRAINT chk_whatsapp_templates_status;

ALTER TABLE public.whatsapp_templates ADD CONSTRAINT chk_whatsapp_templates_status
  CHECK (status = ANY (ARRAY[
    'LOCAL_DRAFT'::text,    -- Konvi-only: aún no submitted a Meta
    'PENDING'::text, 'APPROVED'::text, 'REJECTED'::text, 'PAUSED'::text,
    'DISABLED'::text, 'FLAGGED'::text, 'LIMIT_EXCEEDED'::text,
    -- Track 6 (2026-08-22): estados vigentes en la doc oficial de Meta
    'ARCHIVED'::text, 'UNARCHIVED'::text, 'DELETED'::text, 'IN_APPEAL'::text,
    'LOCKED'::text, 'REINSTATED'::text, 'PENDING_DELETION'::text
  ]));

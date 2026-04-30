-- ============================================================================
-- Rev. 71 — DROP columnas legacy de tenants
-- ============================================================================
-- INTERVENCION HUMANA REQUERIDA: aplicar manualmente con
--   supabase db query --linked -f supabase/migrations/20260501000000_drop_legacy_tenant_columns.sql
--
-- Justificación:
--
-- 1. business_hours TEXT — Reemplazada por support_schedule JSONB (rev. 65).
--    El orchestrator deriva el horario textual ("Lun a Vie de 09:00 a 18:00")
--    desde support_schedule en _format_support_schedule_text(). El UI ya no
--    expone input para este campo (saveHorario eliminada).
--
-- 2. cutoff_message TEXT — Columna huérfana: existía en la API pero NO en el
--    UI del Tenant Console. El orchestrator la inyectaba al system prompt si
--    estaba poblada, pero ningún tenant podía hacerlo. Si un tenant necesita
--    comunicar política de cut-off al bot, debe escribirla en
--    knowledge_base.category='envios'.
--
-- 3. dispatch_lead_time TEXT — Mismo caso que cutoff_message: huérfana en UI.
--    El tiempo de despacho debe documentarse en KB envios o se infiere del
--    carrier (Envia retorna ETA dinámico por cotización).
--
-- BACKFILL DE SEGURIDAD: si algún tenant tiene business_hours poblado pero
-- support_schedule NULL, exporta primero los valores antes de aplicar:
--   SELECT id, business_hours, cutoff_message, dispatch_lead_time
--   FROM tenants
--   WHERE business_hours IS NOT NULL
--      OR cutoff_message IS NOT NULL
--      OR dispatch_lead_time IS NOT NULL;
-- ============================================================================

ALTER TABLE tenants DROP COLUMN IF EXISTS business_hours;
ALTER TABLE tenants DROP COLUMN IF EXISTS cutoff_message;
ALTER TABLE tenants DROP COLUMN IF EXISTS dispatch_lead_time;

COMMENT ON COLUMN tenants.support_schedule IS
  'Horario estructurado: {days:[0-6], open:"HH:MM", close:"HH:MM"}. '
  'Fuente única para horario textual del bot (rev. 71).';

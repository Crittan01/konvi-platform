-- =============================================================================
-- Decisión F2 (Habeas Data Ley 1581 Art. 9) — Módulo Contactos.
--
-- Permitir registrar un RESUMEN de acceso de consola al LISTADO de contactos
-- (lectura RSC del listado de PII), que no corresponde a un contact_id único.
-- El resumen se inserta con purpose='contact_list_view' y contact_id=NULL.
--
-- Antes contact_id era NOT NULL, lo que impedía el resumen de lista. Los
-- accesos por-contacto (create/update/inbox) siguen poblando contact_id.
--
-- Idempotente: DROP NOT NULL es no-op si la columna ya es nullable.
-- NO aplicar automáticamente — el código degrada seguro si aún no está aplicada
-- (el insert falla con NOT NULL y se ignora best-effort, sin romper el render).
-- =============================================================================

ALTER TABLE public.pii_access_log
    ALTER COLUMN contact_id DROP NOT NULL;

COMMENT ON COLUMN public.pii_access_log.contact_id IS
    'Contacto leído. NULL cuando el evento es un resumen de acceso a un listado (purpose=contact_list_view).';

-- =============================================================================
-- F4 · Decisión "Retención y archivado de audit_log".
--
-- Recomendación aprobada: 24 meses en caliente + archivado a Storage, integrado
-- al módulo de retención existente (retention_policies / fn_apply_retention,
-- rev. 95). Hoy audit_log NO tiene política y crece sin cota por tenant.
--
-- Esta migración deja el ANDAMIAJE forward-compatible en el lugar canónico:
--   1. Extiende el CHECK de entity para reconocer 'audit_log'.
--   2. Inserta la política default (24 meses = 730 días) DESHABILITADA.
--
-- Se deja DESHABILITADA y SIN branch en fn_apply_retention a propósito: la
-- recomendación es ARCHIVAR (no borrar) el audit_log — un hard_delete perdería
-- datos con valor de defensa legal. Habilitar la retención requiere primero el
-- worker de archivado a Storage (external_blocked) + firma del founder sobre la
-- ventana exacta. Mientras tanto esta fila es inerte (enabled=FALSE, no cron).
--
-- Idempotente. NO aplicar automáticamente.
-- =============================================================================

-- 1) Reconocer 'audit_log' como entidad válida de retención.
ALTER TABLE public.retention_policies
    DROP CONSTRAINT IF EXISTS retention_policies_entity_check;

ALTER TABLE public.retention_policies
    ADD CONSTRAINT retention_policies_entity_check CHECK (entity IN (
        'conversations', 'messages', 'contacts_inactive', 'pii_access_log', 'audit_log'
    ));

-- 2) Política default declarada pero inerte (enabled=FALSE) hasta el worker de
--    archivado + firma del founder. 730 días = 24 meses en caliente.
INSERT INTO public.retention_policies (tenant_id, entity, ttl_days, action, enabled)
VALUES (NULL, 'audit_log', 730, 'hard_delete', FALSE)
ON CONFLICT (tenant_id, entity) DO NOTHING;

COMMENT ON CONSTRAINT retention_policies_entity_check ON public.retention_policies IS
    'F4 — incluye audit_log (retención 24m, pendiente worker de archivado a Storage).';

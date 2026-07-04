-- F7 — Offboarding erasure completeness: user_dismissed_alerts huérfano.
--
-- Gap (audit F7 offboarding, sev low pero contradice "erasure 100% completa"):
-- public.user_dismissed_alerts.tenant_id es UUID NOT NULL SIN FK a tenants
-- (migration 20260430000001). Al hard-delete de un tenant, el CASCADE de
-- tenants NO alcanza esta tabla → quedan filas huérfanas con tenant_id de una
-- cuenta ya "eliminada permanentemente". Bajo contenido PII (alert_key +
-- user_id) pero incompatible con Habeas Data Ley 1581 Art. 16.
--
-- Fix: limpiar huérfanos existentes y añadir FK ON DELETE CASCADE para que el
-- borrado del tenant arrastre estas filas de forma automática y verificable.
--
-- NO se auto-aplica (política F7: migraciones nuevas se crean, el founder las
-- revisa/aplica sobre el remote productivo — el ledger tiene drift).
--
-- NOTA (fuera de esta migración): rate_limit_windows (20260425000000) embebe
-- el tenant_id dentro de window_key TEXT y NO puede recibir un FK. Sus filas
-- expiran solas (expires_at + índice de limpieza), por lo que no persisten
-- indefinidamente; una purga explícita por tenant en el worker de hard-delete
-- sería el cierre completo (cambio en services/worker, fuera de scope F7 API).

BEGIN;

-- 1. Eliminar filas cuyo tenant ya no existe (pre-condición para poder crear
--    la FK sin violación de integridad).
DELETE FROM public.user_dismissed_alerts uda
WHERE NOT EXISTS (
    SELECT 1 FROM public.tenants t WHERE t.id = uda.tenant_id
);

-- 2. Añadir la FK con CASCADE (idempotente: solo si aún no existe).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_name = 'user_dismissed_alerts_tenant_id_fkey'
          AND table_name = 'user_dismissed_alerts'
    ) THEN
        ALTER TABLE public.user_dismissed_alerts
            ADD CONSTRAINT user_dismissed_alerts_tenant_id_fkey
            FOREIGN KEY (tenant_id)
            REFERENCES public.tenants(id)
            ON DELETE CASCADE;
    END IF;
END$$;

COMMIT;

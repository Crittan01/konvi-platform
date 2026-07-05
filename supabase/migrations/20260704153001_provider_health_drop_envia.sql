-- Housekeeping F6: limpiar 'envia' del CHECK de `tenant_provider_health`.
--
-- Contexto: el CHECK original (20260619000000) admite 'envia', un provider muerto
-- tras ADR-0019 (el shipping activo es Aveonline). El health del canal MeLi ya
-- emite 'meli' como workaround. Opción de menor riesgo (business_call A): quitar
-- 'envia' y CONSERVAR 'meli' (migrar a 'mercadolibre' end-to-end tocaría UI +
-- datos sin valor de negocio proporcional al riesgo).
--
-- INTERVENCION HUMANA REQUERIDA: aplicar en ventana de mantenimiento verificando
-- drift del ledger (feedback_supabase_migrations). Idempotente (DROP IF EXISTS +
-- re-ADD en el mismo bloque).

DO $$
BEGIN
    -- Sanear filas huérfanas 'envia' si existieran (defensivo; no debería haber
    -- ninguna post ADR-0019). Sin esto, el nuevo CHECK fallaría al agregarse.
    DELETE FROM public.tenant_provider_health WHERE provider = 'envia';

    ALTER TABLE public.tenant_provider_health
        DROP CONSTRAINT IF EXISTS tenant_provider_health_provider_valid;

    ALTER TABLE public.tenant_provider_health
        ADD CONSTRAINT tenant_provider_health_provider_valid
        CHECK (provider IN ('whatsapp', 'wompi', 'meli', 'telegram', 'aveonline'));
END $$;

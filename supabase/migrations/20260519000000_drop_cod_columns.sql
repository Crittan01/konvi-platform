-- =============================================================================
-- DROP COD-related columns and capabilities (rev. 105 H.2.4 paused 2026-05-07)
-- Fecha: 2026-05-07
-- Disparador: founder aplicó regla "NO suposiciones — solo lo certificable"
-- y pausó H.2.4 (Cash on Delivery). Decisión: limpiar código + DB de
-- TODO lo asociado a COD para evitar deriva (Plan A.0.1: nada que NO sea
-- certificado debe estar en producción).
--
-- VERIFICACIÓN PRE-MIGRATION (ejecutado 2026-05-07):
--   tenant_carriers WHERE supports_cod=true → 0 filas
--   tenant_provider_capabilities WHERE capability='cod' → 0 filas
--   → Safe to drop sin pérdida de datos.
--
-- REVERSIBILIDAD: cuando se reanude H.2.4 (post KYC Ecart Pay Colombia +
-- certificación V.1+V.4), volver a aplicar la column en una nueva
-- migration. La definición original está en
-- supabase/migrations/20260517000000_tenant_carriers.sql:42-44.
-- =============================================================================

-- 1. Drop column tenant_carriers.supports_cod
ALTER TABLE public.tenant_carriers
    DROP COLUMN IF EXISTS supports_cod;

-- 2. Cleanup capabilities matrix — eliminar rows con capability='cod'
--    si existieran (verificación pre-migration: 0 rows en remote).
DELETE FROM public.tenant_provider_capabilities
    WHERE provider = 'envia' AND capability = 'cod';

-- Comentario actualizado en tabla.
COMMENT ON COLUMN public.tenant_carriers.supports_insurance IS
    'Capability per-carrier per-tenant: declaredValue (H.2.5).
     Coordinadora EXIGE este flag siempre.';

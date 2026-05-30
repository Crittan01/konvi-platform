-- =============================================================================
-- Drop tenant_carriers.supports_insurance (rev. 105 Sem 5 H.2.5 v2 — 2026-05-08).
--
-- Motivación basada en evidencia documental + empírica:
--   * Catálogo oficial Envia (`GET https://queries-test.envia.com/additional-services`)
--     muestra `envia_insurance` (id=125, "Seguro Envía") como servicio del carrier
--     PROPIO Envia, NO universal.
--   * Test prod 2026-05-07: pasar `additional_services:["envia_insurance"]` a
--     Coordinadora con declaredValue=$3M COP retorna "Bad Gateway".
--   * Coordinadora aplica prima automática sobre `declaredValue` sin necesidad de
--     additional_service ($50k→$17.270 vs $3M→$18.850, Δ +$1.580 observado).
--
-- Conclusión: `supports_insurance` per-tenant per-carrier era abstracción errada.
-- La realidad es:
--   1. `declaredValue` se envía SIEMPRE en cada package (no es opt-in tenant).
--   2. `additional_services:["envia_insurance"]` se agrega SOLO cuando carrier="envia".
--   3. Carriers (Coordinadora, FedEx, DHL, etc.) usan su política interna sobre
--      declaredValue automáticamente.
--
-- Rollback no necesario — column era flag opt-in con default false; ningún tenant
-- en producción la activó (verificado 2026-05-08 vía SELECT count(*) WHERE
-- supports_insurance=true → 0).
--
-- Evidencia persistida:
--   docs/research/empirical-evidence/envia-additional-services-queries-api-2026-05-08.json
--   docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-PROD.json
--   docs/research/envia-dossier-2026-05-05.md sec. 2.5 (corregida 2026-05-08)
-- =============================================================================

ALTER TABLE public.tenant_carriers
    DROP COLUMN IF EXISTS supports_insurance;

-- Capability "insurance" en tenant_provider_capabilities también pierde sentido
-- (era el toggle global per-tenant). El concepto se mueve al código.
DELETE FROM public.tenant_provider_capabilities
    WHERE provider = 'envia' AND capability = 'insurance';

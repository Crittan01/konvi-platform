-- =============================================================================
-- Rev. 108 — tenant_carriers.cod_override (3-state override layer).
-- Fecha: 2026-05-26
--
-- Contexto: la tabla `aveonline_carrier_capabilities` define defaults
-- canónicos. Un tenant puede tener acuerdos comerciales especiales con
-- un carrier (ej. acuerdo Aveonline+tenant para habilitar COD con
-- 99MINUTOS pese a que canon dice "NO supports_cod"), o querer
-- deshabilitar COD para un carrier que sí lo soporta.
--
-- Esta columna provee un override 3-estado:
--   • NULL              → usar canonical default
--                         (aveonline_carrier_capabilities.supports_cod)
--   • 'force_enable'    → tenant tiene acuerdo especial, habilita COD
--                         pese al canon
--   • 'force_disable'   → tenant NO quiere COD con este carrier
--                         (riesgo operativo propio)
--
-- Lookup efectivo (servicio app):
--   effective_supports_cod = COALESCE(
--     CASE cod_override
--       WHEN 'force_enable'  THEN true
--       WHEN 'force_disable' THEN false
--       ELSE NULL
--     END,
--     aveonline_carrier_capabilities.supports_cod
--   )
--
-- La columna existente `tenant_carriers.supports_cod` (rev. 108
-- 20260530) queda como **deprecated** — usar `cod_override` en su
-- lugar. NO se dropea por backwards-compat con código existente; el
-- servicio de lookup `get_effective_carrier_capability()` ignora la
-- columna legacy y prefiere `cod_override + canonical`.
-- =============================================================================

ALTER TABLE public.tenant_carriers
    ADD COLUMN IF NOT EXISTS cod_override TEXT
    CHECK (cod_override IS NULL OR cod_override IN ('force_enable', 'force_disable'));

COMMENT ON COLUMN public.tenant_carriers.cod_override IS
    'Override 3-estado sobre canonical aveonline_carrier_capabilities.
     supports_cod. NULL = usar canon. force_enable = acuerdo especial
     tenant. force_disable = tenant deshabilita COD pese al canon.';

-- Force PostgREST schema cache reload.
NOTIFY pgrst, 'reload schema';

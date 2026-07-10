-- =============================================================================
-- BLOQUE B (item 3) — Activación de guías reales Aveonline PER-TENANT (dinero real).
--
-- HALLAZGO (audit + verificado en HEAD): la decisión real/simulado se resolvía con la
-- env var GLOBAL de plataforma `AVEONLINE_GENERATE_REAL_GUIDES` (wompi_webhook.py:1608).
-- Ponerla en "true" a nivel Render facturaba guías REALES para TODOS los tenants con
-- provider aveonline a la vez — dinero real sin control per-tenant.
--
-- FIX: la activación de guías reales es PER-TENANT. Una guía se genera real solo si se
-- cumplen AMBOS (AND lógico, fail-safe):
--   (1) master de plataforma: AVEONLINE_GENERATE_REAL_GUIDES=true (kill-switch global), Y
--   (2) este tenant tiene real_guides_enabled=true (activación explícita founder).
-- Default false → todos los tenants existentes quedan en SIMULADO (no facturan) tras aplicar.
-- La activación por-tenant es una acción founder deliberada (deja dinero real en juego).
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con protocolo seguro + migration repair. Idempotente.
-- =============================================================================

ALTER TABLE public.tenant_shipping_provider_config
    ADD COLUMN IF NOT EXISTS real_guides_enabled BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.tenant_shipping_provider_config.real_guides_enabled IS
    'BLOQUE B — guías reales facturables para este tenant SOLO si (real_guides_enabled=true Y master AVEONLINE_GENERATE_REAL_GUIDES=true). Default false = simulado. Activación founder por-tenant (dinero real).';

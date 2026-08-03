-- Corrección auditoría 2026-08-02 — ghost tables recreadas fuera de cadena + hardening F12 pendiente.
-- Autorizado explícitamente por el founder (flips de producción aprobados en esta iniciativa).
--
-- 1. Ghost tables: attribute_values + category_attributes fueron dropeadas por
--    20260702200000_f7_drop_dead_schema.sql (ledger la registra aplicada) pero reaparecieron en prod
--    recreadas manualmente fuera de la cadena de migraciones. Ninguna migración posterior ni código
--    las referencia. Evidencia pre-vuelo 2026-08-02 (db query --linked):
--      - count(*) = 0 en ambas tablas.
--      - 0 vistas/reglas dependientes (pg_depend/pg_rewrite).
--      - 0 FKs entrantes externas; la única FK es interna del par
--        (attribute_values.category_attribute_id → category_attributes.id, ON DELETE CASCADE):
--        drop la hija primero, mismo orden que F7.
-- 2. Hardening F12 pendiente: 20260703110000 aplicó el patrón REVOKE solo a meli_webhook_dedup.
--    Estas 4 tablas de infra (solo las toca service_role vía RPCs SECURITY DEFINER / workers) tienen
--    RLS sin policies (deny-all) PERO conservan GRANT de tabla a anon/authenticated incl. TRUNCATE
--    (verificado en information_schema.role_table_grants el 2026-08-02). REVOKE cierra el vector;
--    GRANT explícito a service_role es idempotente (ya tenía ALL implícito) y fija el contrato.

DROP TABLE IF EXISTS public.attribute_values;
DROP TABLE IF EXISTS public.category_attributes;

-- ── F12: REVOKE en tablas de infra deny-all (mismo patrón que meli_webhook_dedup) ──
REVOKE ALL ON public.wompi_webhook_inbox FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.wompi_webhook_inbox TO service_role;

REVOKE ALL ON public.whatsapp_webhook_inbox FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.whatsapp_webhook_inbox TO service_role;

REVOKE ALL ON public.provider_health_alert_dedup FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.provider_health_alert_dedup TO service_role;

REVOKE ALL ON public.rate_limit_windows FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.rate_limit_windows TO service_role;

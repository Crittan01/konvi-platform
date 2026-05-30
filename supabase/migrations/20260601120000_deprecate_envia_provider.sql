-- Migration: deprecate envia provider (rev. 109, ADR-0019)
-- Fecha: 2026-05-30
-- Branch origen: feat/remove-envia-pivot-aveonline
--
-- Contexto:
--   Pivote completo Envia → Aveonline. Esta migration limpia las rows
--   residuales de tenant_integrations / tenant_carriers / tenant_provider_capabilities
--   con provider='envia' y endurece constraints para que `aveonline` sea
--   el único provider shipping aceptado en runtime.
--
-- Migration aplicable:
--   - Solo si tenant_shipping_provider_config existe con CHECK constraint
--     que aceptaba 'envia' Y/O 'aveonline'.
--   - Las migrations Envia históricas (fase9_schema_core, shipments,
--     envia_webhook_capture_log) permanecen en supabase/migrations/ INTACTAS
--     para integridad del ledger.
--
-- INTERVENCION HUMANA REQUERIDA antes de aplicar:
--   1. Backup tablas afectadas: tenant_integrations, tenant_carriers,
--      tenant_provider_capabilities, shipments (especialmente shipment 171494 KAIU).
--   2. Verificar 0 shipments activos con provider='envia':
--        SELECT count(*) FROM shipments
--        WHERE provider='envia' AND status IN ('quoted', 'labeled', 'picked_up', 'in_transit');
--   3. Aplicar protocolo seguro per memoria feedback_supabase_migrations.md.
--
-- Vault cleanup (manual fuera de SQL):
--   Tras esta migration, ejecutar scripts/admin/cleanup_envia_vault_secrets.py
--   para limpiar secrets `<tenant_id>/envia/api_token` huérfanos en
--   Supabase Vault (no se eliminan automáticamente via DELETE de
--   tenant_integrations).

BEGIN;

-- ─────────────────────────────────────────────────────────────────────
-- 1. Limpiar rows tenant_carriers con provider='envia'
-- ─────────────────────────────────────────────────────────────────────
-- Decisión técnica (founder 2026-05-30): DELETE clean + auto-seed defaults
-- Aveonline. Los carriers preferidos del tenant se reconfiguran desde
-- el Tenant Console post-migration.
DELETE FROM tenant_carriers WHERE provider = 'envia';

-- ─────────────────────────────────────────────────────────────────────
-- 2. Limpiar capabilities Envia residuales
-- ─────────────────────────────────────────────────────────────────────
DELETE FROM tenant_provider_capabilities WHERE provider = 'envia';

-- ─────────────────────────────────────────────────────────────────────
-- 3. Limpiar tenant_integrations Envia (disconnect + clear credentials)
-- ─────────────────────────────────────────────────────────────────────
-- NOTA: Vault secrets quedan huérfanos hasta correr cleanup script.
DELETE FROM tenant_integrations WHERE provider = 'envia';

-- ─────────────────────────────────────────────────────────────────────
-- 4. Preservar shipment legacy 171494 (KAIU): mantener tracking_number/url,
--    eliminar columna envia_shipment_id si existe.
-- ─────────────────────────────────────────────────────────────────────
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='shipments' AND column_name='envia_shipment_id'
  ) THEN
    ALTER TABLE shipments DROP COLUMN envia_shipment_id;
  END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────
-- 5. Endurecer constraint tenant_shipping_provider_config.active_provider
--    para aceptar SOLO 'aveonline'. Cuando se agregue Courier N+1 ver ADR-0023:
--    nueva migration que ALTER CONSTRAINT añadiendo el nuevo enum value.
-- ─────────────────────────────────────────────────────────────────────
DO $$
DECLARE
  cons_name text;
BEGIN
  SELECT conname INTO cons_name
  FROM pg_constraint
  WHERE conrelid = 'tenant_shipping_provider_config'::regclass
    AND contype = 'c'
    AND pg_get_constraintdef(oid) ILIKE '%active_provider%';

  IF cons_name IS NOT NULL THEN
    EXECUTE format(
      'ALTER TABLE tenant_shipping_provider_config DROP CONSTRAINT %I',
      cons_name
    );
  END IF;
END $$;

ALTER TABLE tenant_shipping_provider_config
  ADD CONSTRAINT tenant_shipping_provider_config_active_provider_check
  CHECK (active_provider IN ('aveonline'));

-- ─────────────────────────────────────────────────────────────────────
-- 6. Update rows tenant_shipping_provider_config existentes con
--    active_provider='envia' → 'aveonline' (defensa adicional).
-- ─────────────────────────────────────────────────────────────────────
-- NOTA: este UPDATE corre ANTES del nuevo constraint check porque DDL
-- en BEGIN-COMMIT se evalúa al COMMIT, no inmediatamente.
UPDATE tenant_shipping_provider_config
SET active_provider = 'aveonline'
WHERE active_provider = 'envia';

COMMIT;

-- ─────────────────────────────────────────────────────────────────────
-- Verificación post-migration (queries de smoke):
-- ─────────────────────────────────────────────────────────────────────
--
-- SELECT COUNT(*) FROM tenant_integrations           WHERE provider='envia'; -- esperado: 0
-- SELECT COUNT(*) FROM tenant_carriers               WHERE provider='envia'; -- esperado: 0
-- SELECT COUNT(*) FROM tenant_provider_capabilities  WHERE provider='envia'; -- esperado: 0
-- SELECT COUNT(*) FROM tenant_shipping_provider_config WHERE active_provider='envia'; -- esperado: 0
-- SELECT column_name FROM information_schema.columns
--   WHERE table_name='shipments' AND column_name='envia_shipment_id'; -- esperado: 0 rows
--
-- INTERVENCION HUMANA pendiente post-migration:
--   1. Ejecutar scripts/admin/cleanup_envia_vault_secrets.py
--   2. Founder confirmar rotación ENVIA_API_KEY local si fue productivo
--   3. Re-seedear carriers preferidos Aveonline desde Tenant Console

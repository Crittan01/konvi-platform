-- 20260622_whatsapp_model_b_backfill_konvi_dev.sql
-- Phase 1 ADR-0023 — Backfill Konvi Dev tenant (6115474f) con campos Model B
-- IDEMPOTENTE: jsonb merge `||`, NOT (credentials ? 'verify_token') guard
-- NO afecta runtime actual (connector sigue leyendo META_APP_SECRET env hasta Phase 3 deploy)

BEGIN;

UPDATE public.tenant_integrations
SET credentials = credentials
  || jsonb_build_object(
       'verify_token', 'konvi-dev-direct-2026',
       'integration_role', 'tenant_internal',
       'integration_type', 'direct_provider',
       'webhook_url_path_segment', 'konvi-dev'
     )
WHERE tenant_id = '6115474f-7046-44a8-88ad-182dbf7626a6'
  AND provider = 'whatsapp'
  AND NOT (credentials ? 'verify_token');

-- NOTA: app_secret_secret_id se setea desde scripts/admin/seed_konvi_dev_app_secret_vault.py
-- (requiere acceso a META_APP_SECRET env-var + Vault RPC).

COMMIT;

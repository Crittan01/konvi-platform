-- A11 audit (WH-01 / Ola 3) — UNIQUE en tenants.meta_waba_id.
--
-- HALLAZGO: la resolución de tenant por meta_waba_id en el connector
-- (services/db_persistence.py `_resolve_tenant_by_waba`, services/template_events.py)
-- tomaba `res.data[0]` sobre `tenants` filtrando por meta_waba_id SIN garantía de
-- unicidad. Si dos tenants compartieran el mismo WABA ID (config errónea), la
-- resolución sería ambigua → cross-talk (mensajes de un tenant persistidos bajo
-- otro). En Model B (ADR-0023, Direct Provider per-tenant) cada tenant trae su
-- propia Meta App + WABA → meta_waba_id DEBE ser único.
--
-- El fix de código (mismo PR) ya usa el tenant HMAC-verificado del path como
-- autoridad (no re-resuelve por el waba del payload). Este índice lo garantiza
-- a nivel DB e impide configurar 2 tenants con la misma WABA.
--
-- Pre-check 2026-06-25 (remote): sin UNIQUE existente + 0 duplicados no-NULL.
-- Índice PARCIAL: excluye NULL y '' (tenants sin WhatsApp configurado pueden
-- coexistir sin WABA). ADR-0025 (aislamiento multi-tenant).

CREATE UNIQUE INDEX IF NOT EXISTS uniq_tenants_meta_waba_id
  ON public.tenants (meta_waba_id)
  WHERE meta_waba_id IS NOT NULL AND meta_waba_id <> '';

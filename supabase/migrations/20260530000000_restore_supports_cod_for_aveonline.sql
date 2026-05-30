-- =============================================================================
-- Rev. 108 — Restore tenant_carriers.supports_cod (drop'd in 20260519).
-- Fecha: 2026-05-26
--
-- Contexto: la migración 20260519000000_drop_cod_columns.sql dropeó
-- `supports_cod` cuando H.2.4 (COD vía Envia + Ecart Pay) fue pausado
-- por el founder en mayo 2026. Rev. 108 reactiva COD pero vía Aveonline
-- (no Envia): Aveonline tiene COD nativo desde día 1 sin requerir KYC
-- Ecart Pay separado — el contrato Aveonline incluye recaudo + liquidación.
--
-- Decisión arquitectónica:
--   • Columna restaurada idempotentemente (IF NOT EXISTS) — soporta
--     re-aplicar la migración sin error si ya existe (ej. rollback ledger).
--   • Sin DEFAULT explícito en re-creación → false implícito (Postgres).
--   • Comentario actualizado para reflejar que aplica a provider='aveonline'
--     (Envia COD sigue pausado per Plan A.0.1).
--   • Aveonline COD per-carrier confirmado en dossier §7.2 (TCC/Domina 4-6d,
--     Servientrega/Envia/etc 7-11d, comisión desde 2.40%).
--
-- Reversibilidad: si se quiere pausar Aveonline COD también, usar
-- `ALTER TABLE tenant_carriers DROP COLUMN IF EXISTS supports_cod` —
-- la app maneja el caso vía `.select("..., supports_cod")` con default
-- False en CarrierPreference dataclass.
--
-- Cierre del bug operativo: pre-fix, PostgREST schema cache fallaba con
-- "Could not find the 'supports_cod' column" porque ni la columna ni
-- ningún tenant tenía la fila. Post-fix, schema cache se recarga al
-- agregar columna y PostgREST la expone.
-- =============================================================================

ALTER TABLE public.tenant_carriers
    ADD COLUMN IF NOT EXISTS supports_cod BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.tenant_carriers.supports_cod IS
    'Capability per-carrier per-tenant: el tenant acepta recaudo
     contraentrega (COD) en este carrier. Aplica solo a provider=
     ''aveonline'' (rev. 108). Envia COD sigue pausado per Plan A.0.1.
     Restaurado por migración 20260530000000_restore_supports_cod_for_aveonline.';

-- Forzar refresh del PostgREST schema cache. Sin esto, el siguiente
-- INSERT/SELECT con `supports_cod` retorna PGRST204 hasta que PostgREST
-- recargue (típicamente ~10 min auto, o reload manual).
NOTIFY pgrst, 'reload schema';

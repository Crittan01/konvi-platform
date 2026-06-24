-- ============================================================
-- A4 finiquito — CHECK constraint en claims.status (alineación API↔UI↔tool)
-- Fecha: 2026-06-24
-- Branch: feat/A6-A7-quality-first-rev111
-- ============================================================
--
-- Audit §3 BUG#2 (CRITICAL): el status de reclamos estaba desalineado entre capas.
--   - API router VALID_STATUSES = {open, in_progress, resolved, closed, cancelled}
--   - UI claims-manager botones envían {investigating, refunded, rejected}
--   - DB SIN CHECK constraint (aceptaba cualquier string)
-- Resultado: PATCH /api/v1/claims/{id} con investigating/refunded/rejected → 422.
-- Los 3 botones del detalle (Investigando, Reembolsar, Rechazar) NO funcionaban.
--
-- Fix: vocabulario canónico unificado = la nomenclatura de la UI (operator-facing,
-- claim-specific) + cancelled para retiros:
--   open · investigating · resolved · refunded · rejected · cancelled
-- Aplicado en: services/api/routers/claims.py VALID_STATUSES +
-- services/ai-orchestrator/agentic/tools/claims.py _VALID_STATUSES + este CHECK
-- (defensa en profundidad — la DB rechaza valores fuera del set aunque un cliente
-- API externo los intente).
--
-- SEGURO: 0 claims en la DB al aplicar (verificado 2026-06-24) → ninguna fila
-- existente viola el CHECK. El tool agentic crea claims con status='open' (válido).
--
-- INTERVENCION HUMANA: aplicar a prod vía protocolo seguro (pre-check 0 filas
-- violatorias → supabase db query --linked -f → migration repair).
-- ============================================================

ALTER TABLE public.claims
    DROP CONSTRAINT IF EXISTS claims_status_check;

ALTER TABLE public.claims
    ADD CONSTRAINT claims_status_check
    CHECK (status IN (
        'open', 'investigating', 'resolved', 'refunded', 'rejected', 'cancelled'
    ));

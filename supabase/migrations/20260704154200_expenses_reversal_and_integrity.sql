-- Migration: 20260704154200_expenses_reversal_and_integrity.sql
-- Goal (F4 — Integridad del registro de gastos): convertir `expenses` en un
-- libro contable confiable para el P&L del tenant.
--
-- Cambios (todos idempotentes, NO aplicada por el agente — la aplica el founder
-- coordinando con el endpoint de la API, ver "INTERVENCION HUMANA REQUERIDA"):
--
--   1) Índice (tenant_id, expense_date) para la agregación del P&L a escala.
--   2) Reverso contable auditado: columnas reversed_at / reversed_by /
--      reversal_reason. Un gasto errado NO se borra (se preserva el trail); se
--      marca como anulado y el P&L lo excluye. La corrección se hace registrando
--      un gasto nuevo con el monto correcto.
--   3) Cierre del bypass RLS: hoy la policy es `FOR ALL USING (tenant = GUC)`,
--      lo que permite a un cliente PostgREST autenticado mutar gastos sin pasar
--      por RBAC ni audit. Se reduce a SELECT (lectura por tenant); las escrituras
--      quedan SOLO para service_role (que bypassa RLS) vía services/api, donde
--      viven el RBAC owner-only, el audit y la validación enum→422.
--
-- ============================================================================
-- INTERVENCION HUMANA REQUERIDA
--   RESPONSABLE: founder / backend
--   PASOS:
--     (a) Desplegar en services/api el endpoint POST /api/v1/expenses/{id}/reverse
--         (RBAC owner-only + audit) y migrar la escritura de POST /api/v1/expenses
--         a service_role con filtro explícito .eq("tenant_id", tid) (ADR-0025)
--         ANTES o junto con esta migración. Si se aplica esta migración sin ese
--         cambio, las inserciones que usen el JWT del usuario (rol authenticated)
--         dejarán de funcionar porque ya no habrá policy de INSERT.
--     (b) Aplicar esta migración al remote (ledger tiene drift — ver
--         feedback_supabase_migrations).
--   CRITERIO DE EXITO: registrar y anular un gasto desde la UI de Finanzas deja
--     trail (reversed_by/at/reason), el P&L excluye el anulado, y un INSERT/UPDATE
--     directo por PostgREST con JWT de usuario es rechazado por RLS.
-- ============================================================================

-- 1) Índice para la agregación del P&L acotada por ventana ---------------------
CREATE INDEX IF NOT EXISTS idx_expenses_tenant_date
    ON public.expenses (tenant_id, expense_date DESC);

-- 2) Reverso contable auditado (soft-void, preserva trail) ---------------------
ALTER TABLE public.expenses
    ADD COLUMN IF NOT EXISTS reversed_at     timestamp with time zone,
    ADD COLUMN IF NOT EXISTS reversed_by     uuid,
    ADD COLUMN IF NOT EXISTS reversal_reason text;

-- Coherencia del trail: si está anulado, exige quién y por qué (y viceversa).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'expenses_reversal_trail_ck'
    ) THEN
        ALTER TABLE public.expenses
            ADD CONSTRAINT expenses_reversal_trail_ck CHECK (
                (reversed_at IS NULL AND reversed_by IS NULL AND reversal_reason IS NULL)
                OR
                (reversed_at IS NOT NULL AND reversed_by IS NOT NULL
                 AND reversal_reason IS NOT NULL AND length(btrim(reversal_reason)) >= 3)
            );
    END IF;
END $$;

-- Índice parcial: el P&L solo suma gastos vigentes (no anulados).
CREATE INDEX IF NOT EXISTS idx_expenses_active_tenant_date
    ON public.expenses (tenant_id, expense_date DESC)
    WHERE reversed_at IS NULL;

-- 3) Cierre del bypass FOR ALL: lectura por tenant, escritura solo service_role -
DROP POLICY IF EXISTS "Tenants can manage their expenses" ON public.expenses;
DROP POLICY IF EXISTS "Tenants can read their expenses"   ON public.expenses;
CREATE POLICY "Tenants can read their expenses"
    ON public.expenses FOR SELECT
    USING (tenant_id = public.app_current_tenant());
-- Sin policy de INSERT/UPDATE/DELETE: el rol authenticated no puede escribir.
-- service_role bypassa RLS → las mutaciones pasan obligatoriamente por la API.

-- =============================================================================
-- BLOQUE 0 · Seguridad P1 (2026-07-10) — RLS read-only en suppliers / purchase_orders
-- / purchase_order_items (cierre del bypass FOR ALL).
--
-- HALLAZGO (auditoría FASE 0, verificado en HEAD): las 3 tablas conservan policy
-- `FOR ALL` con solo tenant-scoping (20260413000000_purchases_and_finance.sql:24-59);
-- 20260702120000_f0_rls_with_check.sql solo añadió WITH CHECK (bloquea cross-tenant
-- pero deja la escritura within-tenant abierta al rol `authenticated`). Es decir: un
-- miembro puede INSERT/UPDATE/DELETE directo por PostgREST, saltándose el RBAC
-- owner-only, el @audit_log y la lógica WAC/stock que viven en services/api/routers/
-- purchases.py. Mismo bypass que ya se cerró en `expenses` (20260704154200 §3).
--
-- FIX (espejo de expenses): lectura por tenant, escritura SOLO service_role (la API).
--   El frontend LEE estas tablas directo (SELECT, purchases/page.tsx) → se conserva;
--   ESCRIBE vía /api/v1/purchases (server actions → API con service_role) → intacto.
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con protocolo seguro + migration repair. Idempotente.
-- =============================================================================

-- ── suppliers ───────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenants can manage their suppliers" ON public.suppliers;
DROP POLICY IF EXISTS "Tenants can read their suppliers"   ON public.suppliers;
CREATE POLICY "Tenants can read their suppliers"
    ON public.suppliers FOR SELECT
    USING (tenant_id = public.app_current_tenant());

-- ── purchase_orders ─────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenants can manage their POs"  ON public.purchase_orders;
DROP POLICY IF EXISTS "Tenants can read their POs"    ON public.purchase_orders;
CREATE POLICY "Tenants can read their POs"
    ON public.purchase_orders FOR SELECT
    USING (tenant_id = public.app_current_tenant());

-- ── purchase_order_items (tiene tenant_id propio → scoping directo) ──────────
DROP POLICY IF EXISTS "Tenants can manage their PO items" ON public.purchase_order_items;
DROP POLICY IF EXISTS "Tenants can read their PO items"   ON public.purchase_order_items;
CREATE POLICY "Tenants can read their PO items"
    ON public.purchase_order_items FOR SELECT
    USING (tenant_id = public.app_current_tenant());

-- Sin policy INSERT/UPDATE/DELETE para `authenticated`: las mutaciones pasan
-- obligatoriamente por services/api (service_role bypassa RLS) con RBAC + audit.

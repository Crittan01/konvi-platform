-- =============================================================================
-- BLOQUE F (F-1/F-2) — datos financieros OWNER-ONLY a nivel RLS (decisión founder 2026-07-11:
-- "finanzas = solo owner, más restrictivo").
--
-- HALLAZGO (audit §I/Compras+Finanzas, verificado en HEAD): el frontend LEE suppliers /
-- purchase_orders / purchase_order_items / expenses DIRECTO por RLS (purchases/page.tsx,
-- finance/page.tsx) — no vía la API. La policy SELECT era solo TENANT-scoped
-- (tenant_id = app_current_tenant()), así que un manager/operator con sesión válida podía leer
-- COSTOS, MÁRGENES y GASTOS vía PostgREST. El guard de rol vivía solo en el frontend/API, y
-- "el frontend no es seguridad" (CLAUDE.md) → exposición real de datos financieros.
--
-- FIX: añadir el check de OWNER a la policy SELECT (patrón de
-- 20260704156000_f6_payment_methods_closure_fix.sql: `(auth.jwt() -> 'app_metadata' ->> 'role')`).
-- Las escrituras ya son service_role-only (API con RBAC owner + audit_log). El API GET de
-- purchases y el POST de expenses también pasaron a owner-only en este bloque (F-1/F-2 code).
--
-- Sin lecturas no-owner legítimas que romper: purchases/page.tsx y finance/page.tsx son (o pasan
-- a ser) owner-only; el orchestrator/worker usa service_role (bypassa RLS). Idempotente.
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con protocolo seguro + migration repair.
-- =============================================================================

-- ── suppliers ───────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenants can read their suppliers" ON public.suppliers;
CREATE POLICY "Owners can read their suppliers"
    ON public.suppliers FOR SELECT
    USING (
        tenant_id = public.app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

-- ── purchase_orders ─────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenants can read their POs" ON public.purchase_orders;
CREATE POLICY "Owners can read their POs"
    ON public.purchase_orders FOR SELECT
    USING (
        tenant_id = public.app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

-- ── purchase_order_items ────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenants can read their PO items" ON public.purchase_order_items;
CREATE POLICY "Owners can read their PO items"
    ON public.purchase_order_items FOR SELECT
    USING (
        tenant_id = public.app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

-- ── expenses ────────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "Tenants can read their expenses" ON public.expenses;
CREATE POLICY "Owners can read their expenses"
    ON public.expenses FOR SELECT
    USING (
        tenant_id = public.app_current_tenant()
        AND (auth.jwt() -> 'app_metadata' ->> 'role') = 'owner'
    );

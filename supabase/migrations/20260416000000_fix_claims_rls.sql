-- Fix: claims RLS usaba current_setting() directo en lugar de app_current_tenant()
-- Impacto: frontend JWT no puede leer/escribir claims (0 filas devueltas)
-- Solución: reemplazar policies para usar app_current_tenant() consistente con el resto del esquema

DROP POLICY IF EXISTS "Tenants can view own claims"   ON public.claims;
DROP POLICY IF EXISTS "Tenants can insert own claims" ON public.claims;
DROP POLICY IF EXISTS "Tenants can update own claims" ON public.claims;
DROP POLICY IF EXISTS "Tenants can delete own claims" ON public.claims;

CREATE POLICY "Tenant Isolation" ON public.claims
  FOR ALL
  TO authenticated
  USING  (tenant_id = app_current_tenant())
  WITH CHECK (tenant_id = app_current_tenant());

-- Habilitar RLS en todas las tablas
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_variations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;

-- Utility Function para determinar el tenant
CREATE OR REPLACE FUNCTION app_current_tenant()
RETURNS UUID
LANGUAGE sql STABLE
AS $$
  -- Retorna el claim del token JWT (para clientes frontales web)
  -- O retorna el setting de la variable (para workers / API enviando contexto)
  SELECT COALESCE(
    NULLIF(current_setting('app.current_tenant_id', true), '')::uuid,
    (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );
$$;

-- RLS para Tenants (solo el propio tenant)
CREATE POLICY "Tenant Isolation" ON public.tenants
  FOR ALL USING (id = app_current_tenant());

-- RLS Genérico para entidades hijas (Products, Variations, Conversations, Messages)
-- La regla es universal: la columna tenant_id debe coindidir con el tenant autenticado.
CREATE POLICY "Tenant Isolation" ON public.products FOR ALL USING (tenant_id = app_current_tenant());
CREATE POLICY "Tenant Isolation" ON public.product_variations FOR ALL USING (tenant_id = app_current_tenant());
CREATE POLICY "Tenant Isolation" ON public.conversations FOR ALL USING (tenant_id = app_current_tenant());
CREATE POLICY "Tenant Isolation" ON public.messages FOR ALL USING (tenant_id = app_current_tenant());\n
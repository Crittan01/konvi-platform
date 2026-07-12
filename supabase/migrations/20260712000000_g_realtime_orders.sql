-- BLOQUE G-1 — habilita Supabase Realtime para `orders`.
--
-- El dashboard (apps/web/app/dashboard/dashboard-client.tsx) YA se suscribe a
-- `orders` vía postgres_changes con filtro `tenant_id=eq.${tenantId}`, pero la
-- tabla NUNCA se agregó a la publication `supabase_realtime` → los eventos de
-- pedidos no llegaban al cliente: las cards/KPIs del home solo se refrescaban al
-- recargar la página (sin polling fallback). Esto lo arregla.
--
-- REPLICA IDENTITY FULL: necesario para que el filtro por columna
-- (`tenant_id=eq.xxx`) funcione en UPDATE/DELETE — mismo patrón y misma razón
-- documentada que conversations/messages (20260417000000_enable_realtime.sql).
-- Además, en DELETE expone la fila OLD completa → la RLS de orders puede evaluar
-- `tenant_id` y el evento queda tenant-scoped (fail-closed), sin fuga cross-tenant.
--
-- Seguridad multi-tenant: la RLS de `orders` ("Tenant Isolation", FOR ALL USING
-- tenant_id = app_current_tenant(), 20260409220000) ya scopea por tenant; Realtime
-- autoriza cada evento bajo el JWT del cliente conectado. El filtro cliente-side
-- es defensa en profundidad, no el borde de seguridad (ADR-0025).
--
-- Idempotente: ADD TABLE se guarda con pg_publication_tables; REPLICA IDENTITY es
-- no-op si ya está en FULL.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime'
      AND schemaname = 'public'
      AND tablename = 'orders'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.orders;
  END IF;
END $$;

ALTER TABLE public.orders REPLICA IDENTITY FULL;

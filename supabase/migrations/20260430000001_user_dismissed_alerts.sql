-- Rev. 69 — Persistencia de alertas dismissed por usuario
--
-- Razón: la migración rev. 68 movió docs `kb_documents.category='general'`
-- a `'faq'`. Necesitamos un banner one-time en `/dashboard/knowledge-base`
-- que avise al operador del cambio. Para que sea persistente (no se vuelva
-- a mostrar tras reload), guardamos qué alertas dismissed cada usuario.
--
-- Patrón: tabla compuesta (user_id, tenant_id, alert_key) con RLS estricto.

CREATE TABLE IF NOT EXISTS public.user_dismissed_alerts (
  user_id      UUID NOT NULL,
  tenant_id    UUID NOT NULL,
  alert_key    TEXT NOT NULL,
  dismissed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, tenant_id, alert_key)
);

ALTER TABLE public.user_dismissed_alerts ENABLE ROW LEVEL SECURITY;

-- RLS: cada usuario solo lee/escribe sus propios dismissals dentro de su tenant.
DROP POLICY IF EXISTS "user reads own dismissed alerts" ON public.user_dismissed_alerts;
CREATE POLICY "user reads own dismissed alerts"
  ON public.user_dismissed_alerts
  FOR SELECT
  USING (
    user_id = auth.uid()
    AND tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );

DROP POLICY IF EXISTS "user upserts own dismissed alerts" ON public.user_dismissed_alerts;
CREATE POLICY "user upserts own dismissed alerts"
  ON public.user_dismissed_alerts
  FOR INSERT
  WITH CHECK (
    user_id = auth.uid()
    AND tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );

DROP POLICY IF EXISTS "user updates own dismissed alerts" ON public.user_dismissed_alerts;
CREATE POLICY "user updates own dismissed alerts"
  ON public.user_dismissed_alerts
  FOR UPDATE
  USING (
    user_id = auth.uid()
    AND tenant_id = (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );

COMMENT ON TABLE public.user_dismissed_alerts IS
  'Persiste qué alertas one-time dismissed cada usuario (ej. banner KB rev. 68 migración general→faq).';

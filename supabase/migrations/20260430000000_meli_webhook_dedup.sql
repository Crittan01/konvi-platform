-- Rev. 69 — Idempotencia distribuida para webhooks MeLi
--
-- Razón: rev. 66 puso dedup in-memory por (application_id, resource, sent)
-- con TTL 300s. En Render Starter+ con 2+ réplicas, cada réplica tiene su
-- propio dict — un evento puede procesarse 2 veces. A escala produc esto =
-- doble llamada a MeLi API + doble UPDATE de stock.
--
-- Solución: mover dedup a Supabase via RPC atómica (mismo patrón que
-- rate_limit_hit en migración 20260425000000). Funciona cross-réplica.
-- Fallback in-memory en código si la RPC falla (compatibilidad rev. 68).

CREATE TABLE IF NOT EXISTS public.meli_webhook_dedup (
  dedup_key     TEXT PRIMARY KEY,                  -- "{application_id}|{resource}|{sent}"
  hit_count     INTEGER NOT NULL DEFAULT 1,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meli_webhook_dedup_expires_at
  ON public.meli_webhook_dedup (expires_at);

-- RPC atómica: INSERT con ON CONFLICT.
-- Retorna TRUE si la clave ya existía (evento duplicado), FALSE si fue insertada por primera vez.
CREATE OR REPLACE FUNCTION public.meli_webhook_seen(
  p_application_id TEXT,
  p_resource       TEXT,
  p_sent           TEXT,
  p_ttl_seconds    INTEGER DEFAULT 300
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_key     TEXT;
  v_already BOOLEAN;
BEGIN
  v_key := COALESCE(p_application_id, '') || '|' ||
           COALESCE(p_resource, '')        || '|' ||
           COALESCE(p_sent, '');

  -- Si los 3 campos están vacíos, NO dedup (caller debe procesar normalmente).
  IF v_key = '||' THEN
    RETURN FALSE;
  END IF;

  INSERT INTO public.meli_webhook_dedup (dedup_key, expires_at)
  VALUES (v_key, NOW() + (p_ttl_seconds || ' seconds')::INTERVAL)
  ON CONFLICT (dedup_key) DO UPDATE
    SET hit_count = public.meli_webhook_dedup.hit_count + 1
  RETURNING (xmax > 0) INTO v_already;  -- xmax > 0 indica UPDATE (ya existía)

  RETURN COALESCE(v_already, FALSE);
END;
$$;

-- Cleanup helper. El worker lo llama periódicamente igual que con rate_limit_windows.
CREATE OR REPLACE FUNCTION public.cleanup_expired_meli_webhook_dedup()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM public.meli_webhook_dedup WHERE expires_at < NOW();
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;

COMMENT ON TABLE public.meli_webhook_dedup IS
  'Idempotencia distribuida para webhooks MeLi (rev. 69). Reemplaza el dict in-memory de meli_webhook.py.';

COMMENT ON FUNCTION public.meli_webhook_seen IS
  'Atómica cross-réplica. Retorna TRUE si (app_id|resource|sent) ya fue visto en la ventana TTL.';

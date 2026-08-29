-- ============================================================================
-- OWASP audit PROD 2026-08-23 — fixes de base de datos.
-- Cubre: YELLOW-5, YELLOW-11, YELLOW-12 (parcial), YELLOW-14, GREEN-30, GREEN-31.
-- Forward-only e idempotente (IF EXISTS / DO blocks): prod puede diferir levemente.
-- ============================================================================

-- ── YELLOW-5a · payments_safe: cerrar DML a través de la vista ───────────────
-- La vista es auto-updatable y corre como su owner (postgres, BYPASSRLS):
-- authenticated podía INSERT/UPDATE/DELETE sobre payments bypaseando RLS y la
-- policy RESTRICTIVE owner-only (track9_payments_select_owner). Nadie escribe
-- por la vista (frontend: solo SELECT en orders/[id]/page.tsx) → se revoca DML.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname = 'payments_safe' AND c.relkind = 'v'
  ) THEN
    EXECUTE 'REVOKE INSERT, UPDATE, DELETE ON public.payments_safe FROM authenticated';
    EXECUTE 'REVOKE INSERT, UPDATE, DELETE ON public.payments_safe FROM anon';
    EXECUTE 'REVOKE INSERT, UPDATE, DELETE ON public.payments_safe FROM PUBLIC';
  END IF;
END $$;

-- NO APLICADO A PROPÓSITO: ALTER VIEW public.payments_safe SET (security_invoker = true);
-- El carácter SECURITY DEFINER de la vista es deliberado desde Track 9 A7
-- (20260822120100_track9_a_altos.sql): la tabla payments es owner-only vía policy
-- RESTRICTIVE track9_payments_select_owner, y la vista existe precisamente para que
-- CUALQUIER miembro lea los pagos de su tenant en orders/[id] (proyección sin PII,
-- con security_barrier + WHERE tenant_id = app_current_tenant()). Con
-- security_invoker=true el invoker quedaría sujeto al RLS de payments y un
-- operator/manager dejaría de ver pagos en la página de pedido → regresión funcional.
-- El riesgo residual de lectura queda acotado por YELLOW-5b (el tenant ya no lo puede
-- sobreescribir un GUC en sesiones autenticadas) y por el REVOKE de DML de arriba.

-- ── YELLOW-5b · app_current_tenant(): JWT-first, GUC solo para workers ───────
-- Antes: COALESCE(GUC, JWT) — el GUC app.current_tenant_id ganaba al JWT incluso
-- en sesiones de usuario autenticado. Ahora: si hay usuario (auth.uid() NOT NULL)
-- la identidad la manda el JWT (app_metadata.tenant_id, emitido por
-- custom_access_token_hook); el GUC solo aplica en sesiones SIN JWT (workers,
-- scripts, harness dbharness). Verificado en repo: ningún servicio setea el GUC en
-- runtime (get_current_tenant es JWT-only), así que el comportamiento efectivo de
-- prod no cambia; solo se cierra la vía de suplantación por GUC residual.
CREATE OR REPLACE FUNCTION public.app_current_tenant()
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path = public, extensions, pg_catalog
AS $function$
  -- Claim JWT (app_metadata.tenant_id) para usuarios web autenticados.
  -- GUC app.current_tenant_id solo para workers / sesiones sin JWT (service_role,
  -- scripts, tests dbharness).
  SELECT CASE
    WHEN auth.uid() IS NOT NULL
      THEN (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    ELSE NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
  END
$function$;

-- ── YELLOW-11 · search_path fijo en funciones de public ──────────────────────
-- 35 funciones en local nacían sin proconfig (search_path mutable → secuestro de
-- esquema en funciones SECURITY DEFINER / triggers). Se fija a
-- 'public, extensions, pg_catalog' en TODA función de public que no tenga
-- search_path ya configurado (las que lo tienen —p.ej. 'public, pgmq'— se respetan).
-- Se excluyen funciones pertenecientes a extensiones (pg_depend deptype 'e').
DO $$
DECLARE
  fn record;
  n_fixed integer := 0;
BEGIN
  FOR fn IN
    SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.prokind = 'f'
      AND (
        p.proconfig IS NULL
        OR NOT EXISTS (
          SELECT 1 FROM unnest(p.proconfig) AS c WHERE c LIKE 'search_path=%'
        )
      )
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend d
        WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
      )
  LOOP
    EXECUTE format(
      'ALTER FUNCTION public.%I(%s) SET search_path = public, extensions, pg_catalog',
      fn.proname, fn.args
    );
    n_fixed := n_fixed + 1;
  END LOOP;
  RAISE NOTICE 'YELLOW-11: search_path fijado en % funciones', n_fixed;
END $$;

-- ── YELLOW-12 · bucket tenant-media público — PARCIAL ────────────────────────
-- NO se pasa a privado en esta migración: el frontend renderiza imágenes vía URL
-- PÚBLICA (catalog/_components/image-upload-box.tsx, gallery-picker-modal.tsx,
-- media/media-client.tsx, settings/logo-upload.tsx usan getPublicUrl) y el flujo
-- send-image de WhatsApp necesita una URL públicamente descargable (image_link —
-- app/api/conversations/[conversationId]/send-image/route.ts). Pasar el bucket a
-- privado rompe el catálogo y los adjuntos salientes hasta migrar el frontend a
-- signed URLs.
-- PENDIENTE migración frontend a signed URLs; entonces ejecutar:
-- UPDATE storage.buckets SET public = false WHERE name = 'tenant-media';

-- ── YELLOW-14 · grants DML amplios ───────────────────────────────────────────
-- anon: verificado que NADA no-autenticado escribe vía PostgREST (el frontend solo
-- escribe con sesión authenticated desde el dashboard; los servicios usan
-- service_role). Se revoca DML de anon en todo el schema.
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM anon;
-- Causa raíz para tablas FUTURAS (mismo patrón que 20260822120300_track9_b_bajos):
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE INSERT, UPDATE, DELETE ON TABLES FROM anon;

-- audit_log conserva su estado append-only para anon (antes: INSERT+SELECT; el
-- REVOKE de arriba solo quita DML, y aquí se restituye el INSERT deliberado).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'audit_log'
  ) THEN
    EXECUTE 'GRANT INSERT ON public.audit_log TO anon';
  END IF;
END $$;

-- authenticated: el frontend SÍ escribe tablas de negocio directo vía PostgREST
-- (ai_agents, whatsapp_templates, tenant_users, tenant_integrations, tenants,
-- notification_settings, conversation_reads, audit_log...) → NO se revoca DML en
-- tablas de negocio. Solo en tablas service-only (escritura real: service_role):
DO $$
DECLARE
  t text;
  service_only constant text[] := ARRAY[
    'wompi_webhook_inbox', 'whatsapp_webhook_inbox', 'meli_webhook_dedup',
    'webhook_events_seen', 'rate_limit_windows', 'tenant_usage_events',
    'api_security_events', 'agentic_shadow_log', 'outbound_idempotency_cache'
  ];
BEGIN
  FOREACH t IN ARRAY service_only LOOP
    IF EXISTS (
      SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = t
    ) THEN
      EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON public.%I FROM authenticated', t);
      EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON public.%I FROM anon', t);
    END IF;
  END LOOP;
END $$;

-- ── GREEN-30 · tablas service-only con RLS sin policies (deny-all deliberado) ─
DO $$
DECLARE
  t text;
  deny_all constant text[] := ARRAY[
    'bot_source_log', 'meli_webhook_dedup', 'mfa_recovery_codes',
    'provider_health_alert_dedup', 'rate_limit_windows',
    'whatsapp_webhook_inbox', 'wompi_webhook_inbox'
  ];
BEGIN
  FOREACH t IN ARRAY deny_all LOOP
    IF EXISTS (
      SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = t
    ) THEN
      EXECUTE format(
        'COMMENT ON TABLE public.%I IS %L', t,
        'service-only: RLS sin políticas a propósito (deny-all a API). Acceso vía service_role.'
      );
    END IF;
  END LOOP;
END $$;

-- ── GREEN-31 · secreto legacy de Vault fuera de convención ───────────────────
-- El consumo de secretos en services es por secret_id (UUID en
-- tenant_integrations.credentials.app_secret_secret_id), no por nombre; ningún
-- código referencia 'whatsapp_app_secret_kaiu'. Se copia al nombre convencional
-- '<tenant_uuid>/whatsapp/app_secret_legacy' SOLO si el legacy existe (prod) y el
-- destino no. El tenant destino se deriva del secreto convencional ya existente.
DO $$
DECLARE
  v_tenant text;
BEGIN
  IF to_regclass('vault.secrets') IS NOT NULL
     AND EXISTS (SELECT 1 FROM vault.secrets WHERE name LIKE 'whatsapp_app_secret_kaiu%')
  THEN
    SELECT split_part(name, '/', 1) INTO v_tenant
    FROM vault.secrets
    WHERE name LIKE '%/whatsapp/app_secret'
    ORDER BY created_at
    LIMIT 1;

    IF v_tenant IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM vault.secrets
      WHERE name = v_tenant || '/whatsapp/app_secret_legacy'
    ) THEN
      -- vault.create_secret es la API soportada (SECURITY DEFINER): un INSERT
      -- directo a vault.secrets falla en cloud con 42501 (_crypto_aead_det_*),
      -- detectado en el smoke BEGIN/ROLLBACK contra PRD 2026-08-29.
      PERFORM vault.create_secret(
        d.decrypted_secret,
        v_tenant || '/whatsapp/app_secret_legacy',
        'Copia convencional del legacy ' || d.name || ' (GREEN-31)'
      )
      FROM vault.decrypted_secrets d
      WHERE d.name LIKE 'whatsapp_app_secret_kaiu%'
      ORDER BY d.created_at
      LIMIT 1;
      RAISE NOTICE 'GREEN-31: legacy copiado a %/whatsapp/app_secret_legacy', v_tenant;
    END IF;
  END IF;
END $$;

-- PENDIENTE (ejecutar solo tras confirmar que ningún lector usa el nombre legacy):
-- DELETE FROM vault.secrets WHERE name LIKE 'whatsapp_app_secret_kaiu%';

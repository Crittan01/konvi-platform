-- ============================================================================
-- schema_baseline.sql — SCHEMA CANÓNICO (replay-desde-cero de las migraciones).
-- Generado por: bash scripts/schema_drift_check.sh --update
-- NO editar a mano. Regenerar tras cualquier migración que cambie el schema.
-- El gate anti-drift (W8 cierre #4) compara el replay contra este archivo.
-- ============================================================================



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE EXTENSION IF NOT EXISTS "pg_net" WITH SCHEMA "extensions";






COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgmq";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "vector" WITH SCHEMA "extensions";






CREATE TYPE "public"."order_cancellation_actor" AS ENUM (
    'customer',
    'operator',
    'system_auto',
    'system_fraud'
);


ALTER TYPE "public"."order_cancellation_actor" OWNER TO "postgres";


CREATE TYPE "public"."order_cancellation_status" AS ENUM (
    'pending',
    'completed',
    'partial_failure',
    'failed',
    'reversed'
);


ALTER TYPE "public"."order_cancellation_status" OWNER TO "postgres";


CREATE TYPE "public"."refund_method_enum" AS ENUM (
    'wompi_void_auto',
    'wompi_dashboard_manual',
    'cod_not_collected',
    'no_refund_no_payment'
);


ALTER TYPE "public"."refund_method_enum" OWNER TO "postgres";


CREATE TYPE "public"."rma_status_enum" AS ENUM (
    'pending_return',
    'return_in_transit',
    'received_inspection',
    'approved_refunding',
    'refund_completed',
    'rejected_product_damaged',
    'rejected_out_of_window',
    'rejected_excluded_product',
    'cancelled_by_customer'
);


ALTER TYPE "public"."rma_status_enum" OWNER TO "postgres";


CREATE TYPE "public"."stock_reservation_status" AS ENUM (
    'active',
    'consumed',
    'released',
    'expired'
);


ALTER TYPE "public"."stock_reservation_status" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."_ai_agents_fallback_roles_valid"("roles" "jsonb") RETURNS boolean
    LANGUAGE "plpgsql" IMMUTABLE
    AS $$
DECLARE
    elem TEXT;
BEGIN
    IF jsonb_typeof(roles) <> 'array' THEN
        RETURN FALSE;
    END IF;
    FOR elem IN SELECT jsonb_array_elements_text(roles)
    LOOP
        IF elem NOT IN ('sales', 'support', 'marketing', 'claims', 'custom') THEN
            RETURN FALSE;
        END IF;
    END LOOP;
    RETURN TRUE;
END;
$$;


ALTER FUNCTION "public"."_ai_agents_fallback_roles_valid"("roles" "jsonb") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."_touch_conversation_notes_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."_touch_conversation_notes_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."ack_human_takeover_notification"("p_msg_id" bigint) RETURNS boolean
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pgmq'
    AS $$
  SELECT pgmq.delete('human_takeover_notifications', p_msg_id);
$$;


ALTER FUNCTION "public"."ack_human_takeover_notification"("p_msg_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."ack_whatsapp_outbound_message"("p_msg_id" bigint) RETURNS boolean
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pgmq'
    AS $$
  SELECT pgmq.delete('whatsapp_outbound_messages', p_msg_id);
$$;


ALTER FUNCTION "public"."ack_whatsapp_outbound_message"("p_msg_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."add_member_to_tenant"("p_user_id" "uuid", "p_tenant_id" "uuid", "p_role" "text") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  IF p_role NOT IN ('owner', 'manager', 'operator') THEN
    RAISE EXCEPTION 'Rol inválido: %', p_role;
  END IF;

  -- Single-tenant (ADR-0030): si el usuario ya pertenece a OTRO negocio, no se
  -- le puede agregar aquí. unique_violation (23505) para que el caller lo
  -- distinga de un fallo genérico.
  IF EXISTS (
    SELECT 1 FROM public.tenant_users
    WHERE user_id = p_user_id
      AND tenant_id <> p_tenant_id
  ) THEN
    RAISE EXCEPTION 'user_already_member_of_another_tenant'
      USING ERRCODE = 'unique_violation';
  END IF;

  INSERT INTO public.tenant_users (user_id, tenant_id, role)
  VALUES (p_user_id, p_tenant_id, p_role)
  ON CONFLICT (tenant_id, user_id) DO UPDATE
    SET role = EXCLUDED.role;
END;
$$;


ALTER FUNCTION "public"."add_member_to_tenant"("p_user_id" "uuid", "p_tenant_id" "uuid", "p_role" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."add_member_to_tenant"("p_user_id" "uuid", "p_tenant_id" "uuid", "p_role" "text") IS 'Inserta o actualiza un miembro en un tenant (roles: owner, manager, operator). ADR-0030: rechaza usuarios que ya pertenecen a otro tenant (single-tenant membership).';



CREATE OR REPLACE FUNCTION "public"."ai_insights_set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."ai_insights_set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."app_current_role"() RETURNS "text"
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
  SELECT COALESCE(
    NULLIF(current_setting('app.current_role', true), ''),
    (
      SELECT tu.role
      FROM public.tenant_users tu
      WHERE tu.user_id  = auth.uid()
        AND tu.tenant_id = public.app_current_tenant()
        AND tu.status    = 'active'
      LIMIT 1
    )
  );
$$;


ALTER FUNCTION "public"."app_current_role"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."app_current_role"() IS 'Rol del usuario actual (owner|manager|operator) leído FRESCO de tenant_users para el tenant activo. SECURITY DEFINER para evitar recursión de RLS; solo devuelve el rol del propio auth.uid(). Devuelve NULL para service_role (que además bypassea RLS) y para sesiones sin membresía activa.';



CREATE OR REPLACE FUNCTION "public"."app_current_tenant"() RETURNS "uuid"
    LANGUAGE "sql" STABLE
    AS $$
  -- Retorna el claim del token JWT (para clientes frontales web)
  -- O retorna el setting de la variable (para workers / API enviando contexto)
  SELECT COALESCE(
    NULLIF(current_setting('app.current_tenant_id', true), '')::uuid,
    (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );
$$;


ALTER FUNCTION "public"."app_current_tenant"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."assign_purchase_order_number"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  v_next bigint;
BEGIN
  -- Respeta un número provisto explícitamente (migraciones/imports); solo asigna
  -- cuando viene NULL (caso normal del backend, que no lo envía).
  IF NEW.po_number IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF NEW.tenant_id IS NULL THEN
    RETURN NEW; -- otras constraints lo rechazarán; no numeramos sin tenant.
  END IF;

  -- Serializa inserts concurrentes del MISMO tenant (evita colisión del MAX+1).
  -- La key del lock es estable por tenant; distintos tenants no se bloquean.
  PERFORM pg_advisory_xact_lock(hashtext('purchase_orders_seq:' || NEW.tenant_id::text));

  SELECT COALESCE(MAX(po_number), 0) + 1
    INTO v_next
  FROM public.purchase_orders
  WHERE tenant_id = NEW.tenant_id;

  NEW.po_number := v_next;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."assign_purchase_order_number"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cart_add_item"("p_tenant_id" "uuid", "p_cart_id" "uuid", "p_product_id" "uuid", "p_variation_id" "uuid", "p_quantity" integer, "p_unit_price_cents" bigint, "p_expected_version" integer DEFAULT NULL::integer) RETURNS TABLE("out_cart_id" "uuid", "out_new_version" integer, "out_subtotal_cents" bigint, "out_total_cents" bigint)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_cart conversation_carts%ROWTYPE;
BEGIN
    IF p_quantity IS NULL OR p_quantity < 1 THEN
        RAISE EXCEPTION 'cart_add_item: quantity must be >= 1';
    END IF;

    SELECT * INTO v_cart
    FROM public.conversation_carts
    WHERE id = p_cart_id AND tenant_id = p_tenant_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'cart_add_item: cart % not found for tenant %', p_cart_id, p_tenant_id;
    END IF;

    IF v_cart.status <> 'open' THEN
        RAISE EXCEPTION 'cart_add_item: cart % is not open (status=%)', p_cart_id, v_cart.status;
    END IF;

    IF p_expected_version IS NOT NULL AND v_cart.version <> p_expected_version THEN
        RAISE EXCEPTION 'cart_add_item: version mismatch (expected %, got %)',
            p_expected_version, v_cart.version
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO public.conversation_cart_items AS i (
        tenant_id, cart_id, product_id, variation_id, quantity, unit_price_cents
    )
    VALUES (
        p_tenant_id, p_cart_id, p_product_id, p_variation_id, p_quantity, p_unit_price_cents
    )
    ON CONFLICT (cart_id, variation_id) DO UPDATE
    SET
        quantity = i.quantity + EXCLUDED.quantity,
        unit_price_cents = EXCLUDED.unit_price_cents,
        updated_at = NOW();

    UPDATE public.conversation_carts c
    SET
        subtotal_cents = COALESCE((
            SELECT SUM(it.quantity * it.unit_price_cents)::BIGINT
            FROM public.conversation_cart_items it
            WHERE it.cart_id = c.id
        ), 0),
        total_cents = COALESCE((
            SELECT SUM(it.quantity * it.unit_price_cents)::BIGINT
            FROM public.conversation_cart_items it
            WHERE it.cart_id = c.id
        ), 0) + COALESCE(c.shipping_cents, 0),
        version = c.version + 1,
        last_activity_at = NOW()
    WHERE c.id = p_cart_id AND c.tenant_id = p_tenant_id
    RETURNING c.id, c.version, c.subtotal_cents, c.total_cents
    INTO out_cart_id, out_new_version, out_subtotal_cents, out_total_cents;

    RETURN NEXT;
END;
$$;


ALTER FUNCTION "public"."cart_add_item"("p_tenant_id" "uuid", "p_cart_id" "uuid", "p_product_id" "uuid", "p_variation_id" "uuid", "p_quantity" integer, "p_unit_price_cents" bigint, "p_expected_version" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."cart_add_item"("p_tenant_id" "uuid", "p_cart_id" "uuid", "p_product_id" "uuid", "p_variation_id" "uuid", "p_quantity" integer, "p_unit_price_cents" bigint, "p_expected_version" integer) IS 'Atómico: upsert (cart_id, variation_id), recálculo de totales y bump de version. OUT params con prefijo out_ para evitar ambigüedad con columnas de tablas.';



CREATE OR REPLACE FUNCTION "public"."claim_wompi_inbox_batch"("p_limit" integer DEFAULT 20, "p_min_age_seconds" integer DEFAULT 120, "p_max_attempts" integer DEFAULT 5, "p_lease_seconds" integer DEFAULT 300) RETURNS TABLE("checksum" "text", "raw_payload" "jsonb", "attempts" integer)
    LANGUAGE "sql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    UPDATE public.wompi_webhook_inbox AS w
    SET attempts = w.attempts + 1,
        claimed_at = now()
    WHERE w.checksum IN (
        SELECT c.checksum
        FROM public.wompi_webhook_inbox AS c
        WHERE c.processed_at IS NULL
          AND c.received_at < now() - make_interval(secs => p_min_age_seconds)
          AND c.attempts < p_max_attempts
          -- Lease: no re-reclamar dentro de p_lease_seconds del último claim.
          AND (c.claimed_at IS NULL
               OR c.claimed_at < now() - make_interval(secs => p_lease_seconds))
        ORDER BY c.received_at
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING w.checksum, w.raw_payload, w.attempts;
$$;


ALTER FUNCTION "public"."claim_wompi_inbox_batch"("p_limit" integer, "p_min_age_seconds" integer, "p_max_attempts" integer, "p_lease_seconds" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_bot_source_log"("retention_days" integer DEFAULT 30) RETURNS integer
    LANGUAGE "plpgsql"
    AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM bot_source_log
  WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_bot_source_log"("retention_days" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_idempotency_keys"("p_limit" integer DEFAULT 5000) RETURNS bigint
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_deleted BIGINT := 0;
BEGIN
  WITH doomed AS (
    SELECT id
    FROM public.idempotency_keys
    WHERE expires_at < NOW()
    ORDER BY expires_at ASC
    LIMIT GREATEST(1, p_limit)
  ),
  del AS (
    DELETE FROM public.idempotency_keys k
    USING doomed d
    WHERE k.id = d.id
    RETURNING k.id
  )
  SELECT COUNT(*) INTO v_deleted FROM del;

  RETURN COALESCE(v_deleted, 0);
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_idempotency_keys"("p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_meli_webhook_dedup"() RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM public.meli_webhook_dedup WHERE expires_at < NOW();
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_meli_webhook_dedup"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_rate_limit_windows"("p_limit" integer DEFAULT 5000) RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    WITH deleted AS (
        DELETE FROM public.rate_limit_windows
        WHERE expires_at < NOW()
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_deleted FROM deleted;
    RETURN v_deleted;
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_rate_limit_windows"("p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_wompi_inbox"("p_processed_retention_days" integer DEFAULT 7, "p_deadletter_retention_days" integer DEFAULT 30) RETURNS integer
    LANGUAGE "sql"
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    WITH del AS (
        DELETE FROM public.wompi_webhook_inbox
        WHERE (processed_at IS NOT NULL
               AND processed_at < now() - make_interval(days => p_processed_retention_days))
           OR (processed_at IS NULL
               AND received_at < now() - make_interval(days => p_deadletter_retention_days))
        RETURNING 1
    )
    SELECT count(*)::INT FROM del;
$$;


ALTER FUNCTION "public"."cleanup_wompi_inbox"("p_processed_retention_days" integer, "p_deadletter_retention_days" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."consent_audit_log_block_modify"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    RAISE EXCEPTION 'consent_audit_log es append-only (Ley 1581 Art. 9)';
END;
$$;


ALTER FUNCTION "public"."consent_audit_log_block_modify"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."consume_tenant_capability"("p_tenant_id" "uuid", "p_capability_key" "text", "p_units" integer DEFAULT 1, "p_metadata" "jsonb" DEFAULT '{}'::"jsonb") RETURNS TABLE("allowed" boolean, "plan_code" "text", "enabled" boolean, "limit_value" bigint, "period" "text", "used" bigint, "remaining" bigint, "reset_at" timestamp with time zone, "reason" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_now TIMESTAMPTZ := NOW();
  v_plan_code TEXT;
  v_enabled BOOLEAN := TRUE;
  v_limit BIGINT := NULL;
  v_period TEXT := 'none';
  v_period_start TIMESTAMPTZ;
  v_period_end TIMESTAMPTZ;
  v_current_usage BIGINT := 0;
  v_next_usage BIGINT := 0;
BEGIN
  IF p_units IS NULL OR p_units < 1 THEN
    p_units := 1;
  END IF;

  INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status, started_at)
  VALUES (p_tenant_id, 'basic', 'active', NOW())
  ON CONFLICT (tenant_id) DO NOTHING;

  SELECT ts.plan_code
  INTO v_plan_code
  FROM public.tenant_subscriptions ts
  WHERE ts.tenant_id = p_tenant_id
  LIMIT 1;

  IF v_plan_code IS NULL THEN
    v_plan_code := 'basic';
  END IF;

  SELECT pc.enabled, pc.limit_value, pc.period
  INTO v_enabled, v_limit, v_period
  FROM public.plan_capabilities pc
  WHERE pc.plan_code = v_plan_code
    AND pc.capability_key = p_capability_key
  LIMIT 1;

  IF NOT FOUND THEN
    -- Fail-open controlado: capability no configurada no bloquea operación.
    v_enabled := TRUE;
    v_limit := NULL;
    v_period := 'none';
  END IF;

  IF COALESCE(v_enabled, TRUE) = FALSE THEN
    RETURN QUERY
    SELECT FALSE, v_plan_code, FALSE, v_limit, v_period, 0::BIGINT, 0::BIGINT, NULL::TIMESTAMPTZ, 'feature_disabled';
    RETURN;
  END IF;

  IF v_period = 'month' THEN
    v_period_start := date_trunc('month', v_now);
    v_period_end := v_period_start + INTERVAL '1 month';
  ELSIF v_period = 'day' THEN
    v_period_start := date_trunc('day', v_now);
    v_period_end := v_period_start + INTERVAL '1 day';
  ELSIF v_period = 'minute' THEN
    v_period_start := date_trunc('minute', v_now);
    v_period_end := v_period_start + INTERVAL '1 minute';
  ELSE
    -- 'none': telemetría mensual para observabilidad
    v_period_start := date_trunc('month', v_now);
    v_period_end := v_period_start + INTERVAL '1 month';
  END IF;

  SELECT uc.usage_count
  INTO v_current_usage
  FROM public.tenant_usage_counters uc
  WHERE uc.tenant_id = p_tenant_id
    AND uc.capability_key = p_capability_key
    AND uc.period_start = v_period_start
    AND uc.period_end = v_period_end
  LIMIT 1;

  v_current_usage := COALESCE(v_current_usage, 0);
  v_next_usage := v_current_usage + p_units;

  IF v_limit IS NOT NULL AND v_period <> 'none' AND v_next_usage > v_limit THEN
    RETURN QUERY
    SELECT
      FALSE,
      v_plan_code,
      TRUE,
      v_limit,
      v_period,
      v_current_usage,
      GREATEST(v_limit - v_current_usage, 0),
      v_period_end,
      'quota_exceeded';
    RETURN;
  END IF;

  INSERT INTO public.tenant_usage_counters (
    tenant_id,
    capability_key,
    period_start,
    period_end,
    usage_count
  )
  VALUES (
    p_tenant_id,
    p_capability_key,
    v_period_start,
    v_period_end,
    p_units
  )
  ON CONFLICT (tenant_id, capability_key, period_start, period_end)
  DO UPDATE SET
    usage_count = public.tenant_usage_counters.usage_count + EXCLUDED.usage_count,
    updated_at = NOW()
  RETURNING usage_count INTO v_next_usage;

  INSERT INTO public.tenant_usage_events (tenant_id, capability_key, units, metadata)
  VALUES (p_tenant_id, p_capability_key, p_units, COALESCE(p_metadata, '{}'::jsonb));

  RETURN QUERY
  SELECT
    TRUE,
    v_plan_code,
    TRUE,
    v_limit,
    v_period,
    v_next_usage,
    CASE WHEN v_limit IS NULL THEN NULL ELSE GREATEST(v_limit - v_next_usage, 0) END,
    v_period_end,
    NULL::TEXT;
END;
$$;


ALTER FUNCTION "public"."consume_tenant_capability"("p_tenant_id" "uuid", "p_capability_key" "text", "p_units" integer, "p_metadata" "jsonb") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."contacts_default_shipping_phone"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    IF NEW.shipping_phone IS NULL OR btrim(NEW.shipping_phone) = '' THEN
        NEW.shipping_phone := NEW.phone;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."contacts_default_shipping_phone"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."coupon_increment_redemption"("p_coupon_id" "uuid", "p_tenant_id" "uuid") RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_count integer;
BEGIN
  UPDATE public.coupons
     SET redemptions_count = redemptions_count + 1,
         updated_at = now()
   WHERE id = p_coupon_id
     AND tenant_id = p_tenant_id
     AND (max_redemptions IS NULL OR redemptions_count < max_redemptions)
  RETURNING redemptions_count INTO v_count;

  RETURN v_count;  -- NULL si no hubo fila que actualizar
END;
$$;


ALTER FUNCTION "public"."coupon_increment_redemption"("p_coupon_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."coupon_increment_redemption"("p_coupon_id" "uuid", "p_tenant_id" "uuid") IS 'Incrementa coupons.redemptions_count de forma atómica respetando max_redemptions. Devuelve el nuevo contador o NULL si no incrementó. Solo service_role.';



CREATE OR REPLACE FUNCTION "public"."custom_access_token_hook"("event" "jsonb") RETURNS "jsonb"
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public', 'auth'
    AS $$
DECLARE
  v_tenant_id  text;
  v_role       text;
  v_claims     jsonb;
  v_app_meta   jsonb;
BEGIN
  -- Estado actual del miembro ACTIVO. ORDER BY determinista: con single-tenant
  -- hay a lo sumo 1 fila activa; el ORDER BY garantiza elección estable incluso
  -- si (transitoriamente, pre-UNIQUE) existieran varias — prioriza owner, luego
  -- la membresía más antigua, luego tenant_id, para un resultado reproducible.
  SELECT
    tu.tenant_id::text,
    tu.role
  INTO v_tenant_id, v_role
  FROM public.tenant_users tu
  WHERE tu.user_id = (event->>'user_id')::uuid
    AND tu.status  = 'active'
  ORDER BY
    CASE tu.role
      WHEN 'owner'    THEN 0
      WHEN 'manager'  THEN 1
      WHEN 'operator' THEN 2
      ELSE 3
    END,
    tu.created_at ASC,
    tu.tenant_id ASC
  LIMIT 1;

  v_claims   := event->'claims';
  v_app_meta := COALESCE(v_claims->'app_metadata', '{}'::jsonb);

  IF v_tenant_id IS NOT NULL THEN
    v_app_meta := v_app_meta
      || jsonb_build_object('tenant_id', v_tenant_id)
      || jsonb_build_object('role',      v_role);
  ELSE
    v_app_meta := v_app_meta - 'tenant_id' - 'role';
  END IF;

  v_claims := jsonb_set(v_claims, '{app_metadata}', v_app_meta);
  RETURN jsonb_set(event, '{claims}', v_claims);
END;
$$;


ALTER FUNCTION "public"."custom_access_token_hook"("event" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."custom_access_token_hook"("event" "jsonb") IS 'Hook activo desde 2026-04-26. Reemplaza trigger on_tenant_assignment.';



CREATE OR REPLACE FUNCTION "public"."dequeue_human_takeover_notifications"("p_vt" integer DEFAULT 90, "p_qty" integer DEFAULT 20) RETURNS TABLE("msg_id" bigint, "read_ct" integer, "enqueued_at" timestamp with time zone, "vt" timestamp with time zone, "message" "jsonb")
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pgmq'
    AS $$
  SELECT
    q.msg_id,
    q.read_ct,
    q.enqueued_at,
    q.vt,
    q.message
  FROM pgmq.read(
    'human_takeover_notifications',
    GREATEST(1, p_vt),
    GREATEST(1, p_qty)
  ) AS q;
$$;


ALTER FUNCTION "public"."dequeue_human_takeover_notifications"("p_vt" integer, "p_qty" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."dequeue_whatsapp_outbound_messages"("p_vt" integer DEFAULT 90, "p_qty" integer DEFAULT 20) RETURNS TABLE("msg_id" bigint, "read_ct" integer, "enqueued_at" timestamp with time zone, "vt" timestamp with time zone, "message" "jsonb")
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pgmq'
    AS $$
  SELECT
    q.msg_id,
    q.read_ct,
    q.enqueued_at,
    q.vt,
    q.message
  FROM pgmq.read(
    'whatsapp_outbound_messages',
    GREATEST(1, p_vt),
    GREATEST(1, p_qty)
  ) AS q;
$$;


ALTER FUNCTION "public"."dequeue_whatsapp_outbound_messages"("p_vt" integer, "p_qty" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enqueue_human_takeover_notification"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pgmq'
    AS $$
DECLARE
  payload JSONB;
BEGIN
  IF NEW.tenant_id IS NULL THEN
    RETURN NEW;
  END IF;

  IF NEW.status = 'human_takeover'
     AND OLD.status IS DISTINCT FROM NEW.status THEN
    payload := jsonb_build_object(
      'event_type', 'conversation.human_takeover',
      'tenant_id', NEW.tenant_id,
      'conversation_id', NEW.id,
      'customer_phone', NEW.customer_phone,
      'previous_status', OLD.status,
      'new_status', NEW.status,
      'triggered_at', NOW()
    );

    PERFORM pgmq.send('human_takeover_notifications', payload);
  END IF;

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."enqueue_human_takeover_notification"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."enqueue_whatsapp_outbound_message"("p_message" "jsonb", "p_delay" integer DEFAULT 0) RETURNS bigint
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pgmq'
    AS $$
  SELECT COALESCE(
    (SELECT msg_id
     FROM pgmq.send(
       'whatsapp_outbound_messages',
       p_message,
       GREATEST(0, p_delay)
     ) AS msg_id
     LIMIT 1),
    0
  );
$$;


ALTER FUNCTION "public"."enqueue_whatsapp_outbound_message"("p_message" "jsonb", "p_delay" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."es_mensaje_de_evidencia"("p_conversation_id" "uuid", "p_tenant_id" "uuid") RETURNS boolean
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.orders o
         WHERE o.conversation_id = p_conversation_id
           AND o.tenant_id = p_tenant_id
           AND (
                o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
             OR EXISTS (SELECT 1 FROM public.payments p
                         WHERE p.order_id = o.id AND p.status = 'approved')
             OR EXISTS (SELECT 1 FROM public.order_receipts r
                         WHERE r.order_id = o.id)
           )
    );
$$;


ALTER FUNCTION "public"."es_mensaje_de_evidencia"("p_conversation_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."es_mensaje_de_evidencia"("p_conversation_id" "uuid", "p_tenant_id" "uuid") IS 'True si la conversación sostiene una relación comercial REAL: un pedido que llegó a ejecutarse, que se pagó, o que produjo comprobante. Un carrito abandonado en pending_payment y luego cancelado NO cuenta — retenerlo 10 años sería sobre-retención contra Ley 1581 art. 4 lit. d).';



CREATE OR REPLACE FUNCTION "public"."fn_apply_retention"("p_entity" "text", "p_dry_run" boolean DEFAULT true) RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_total_count   INTEGER := 0;
    v_count         INTEGER;
    v_default_ttl   INTEGER;
    v_default_act   TEXT;
    v_eff_ttl       INTEGER;
    v_eff_act       TEXT;
    v_ttl_evidencia INTEGER;
    r_tenant        RECORD;
BEGIN
    SELECT ttl_days, action
      INTO v_default_ttl, v_default_act
      FROM public.retention_policies
     WHERE tenant_id IS NULL AND entity = p_entity AND enabled = TRUE
     LIMIT 1;

    IF v_default_ttl IS NULL THEN
        RAISE NOTICE 'No default policy for entity=%; skipping.', p_entity;
        RETURN 0;
    END IF;

    -- Plazo de conservación de la PRUEBA. Si la política no está, se usa el legal: nunca
    -- se borra evidencia por falta de configuración.
    SELECT COALESCE((
        SELECT ttl_days FROM public.retention_policies
         WHERE tenant_id IS NULL AND entity = 'messages_evidencia' AND enabled = TRUE
         LIMIT 1
    ), 3653) INTO v_ttl_evidencia;

    FOR r_tenant IN
        SELECT id AS tenant_id FROM public.tenants
    LOOP
        SELECT ttl_days, action
          INTO v_eff_ttl, v_eff_act
          FROM public.retention_policies
         WHERE tenant_id = r_tenant.tenant_id
           AND entity = p_entity
           AND enabled = TRUE
         LIMIT 1;

        IF v_eff_ttl IS NULL THEN
            v_eff_ttl := v_default_ttl;
            v_eff_act := v_default_act;
        END IF;

        v_count := 0;

        -- ── messages: DOS pasadas SARGABLES, no un CASE por fila ────────────
        IF p_entity = 'messages' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.messages m
                 WHERE m.tenant_id = r_tenant.tenant_id
                   AND (
                        m.created_at < NOW() - make_interval(days => v_ttl_evidencia)
                     OR (m.created_at < NOW() - make_interval(days => v_eff_ttl)
                         AND NOT EXISTS (
                             SELECT 1 FROM public.orders o
                              WHERE o.conversation_id = m.conversation_id
                                AND o.tenant_id = m.tenant_id
                                AND (o.status IN ('confirmed','processing','shipped','delivered')
                                  OR EXISTS (SELECT 1 FROM public.payments p
                                              WHERE p.order_id = o.id AND p.status = 'approved')
                                  OR EXISTS (SELECT 1 FROM public.order_receipts r
                                              WHERE r.order_id = o.id))))
                   );
            ELSE
                -- Pasada A: lo vencido a TTL corto que NO sostiene relación comercial.
                -- El EXISTS va inline para que el planner pueda hacer anti-join en vez de
                -- llamar a una función no inlineable una vez por fila.
                WITH del AS (
                    DELETE FROM public.messages m
                     WHERE m.tenant_id = r_tenant.tenant_id
                       AND m.created_at < NOW() - make_interval(days => v_eff_ttl)
                       AND NOT EXISTS (
                           SELECT 1 FROM public.orders o
                            WHERE o.conversation_id = m.conversation_id
                              AND o.tenant_id = m.tenant_id
                              AND (o.status IN ('confirmed','processing','shipped','delivered')
                                OR EXISTS (SELECT 1 FROM public.payments p
                                            WHERE p.order_id = o.id AND p.status = 'approved')
                                OR EXISTS (SELECT 1 FROM public.order_receipts r
                                            WHERE r.order_id = o.id)))
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;

                -- Pasada B: lo vencido al plazo legal de conservación, sea lo que sea.
                -- Un mensaje sin conversación (`conversation_id IS NULL`) cae acá y no en
                -- la pasada A: el NOT EXISTS con NULL no lo alcanzaría, así que sin esta
                -- pasada viviría para siempre.
                WITH del2 AS (
                    DELETE FROM public.messages m
                     WHERE m.tenant_id = r_tenant.tenant_id
                       AND m.created_at < NOW() - make_interval(days => v_ttl_evidencia)
                     RETURNING 1
                )
                SELECT v_count + COUNT(*) INTO v_count FROM del2;
            END IF;

        -- ── conversations: soft_delete (set archived_at) ────────────────────
        ELSIF p_entity = 'conversations' AND v_eff_act = 'soft_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.conversations
                 WHERE tenant_id = r_tenant.tenant_id
                   AND last_interaction_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                   AND archived_at IS NULL;
            ELSE
                WITH upd AS (
                    UPDATE public.conversations
                       SET archived_at = NOW()
                     WHERE tenant_id = r_tenant.tenant_id
                       AND last_interaction_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                       AND archived_at IS NULL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM upd;
            END IF;

        -- ── contacts_inactive: soft_delete por updated_at sin consent ───────
        ELSIF p_entity = 'contacts_inactive' AND v_eff_act = 'soft_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.contacts
                 WHERE tenant_id = r_tenant.tenant_id
                   AND COALESCE(updated_at, created_at) < NOW() - (v_eff_ttl || ' days')::INTERVAL
                   AND deleted_at IS NULL
                   AND consent_given = FALSE;
            ELSE
                WITH upd AS (
                    UPDATE public.contacts
                       SET deleted_at = NOW()
                     WHERE tenant_id = r_tenant.tenant_id
                       AND COALESCE(updated_at, created_at) < NOW() - (v_eff_ttl || ' days')::INTERVAL
                       AND deleted_at IS NULL
                       AND consent_given = FALSE
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM upd;
            END IF;

        -- ── pii_access_log: hard_delete ─────────────────────────────────────
        ELSIF p_entity = 'pii_access_log' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.pii_access_log
                 WHERE tenant_id = r_tenant.tenant_id
                   AND accessed_at < NOW() - (v_eff_ttl || ' days')::INTERVAL;
            ELSE
                WITH del AS (
                    DELETE FROM public.pii_access_log
                     WHERE tenant_id = r_tenant.tenant_id
                       AND accessed_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;
            END IF;

        -- ── audit_log: hard_delete (M6) ─────────────────────────────────────
        -- Evidencia Habeas Data append-only: SOLO aplica si la política está
        -- enabled=TRUE (guard de los dos niveles de arriba). Hoy está FALSE —
        -- rama dormida hasta el worker de archivado a Storage + firma del
        -- founder (20260704154100). Lo que se cierra acá es la habilitación
        -- ficticia: quien la habilite obtiene borrado real, no silencio.
        ELSIF p_entity = 'audit_log' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.audit_log
                 WHERE tenant_id = r_tenant.tenant_id
                   AND created_at < NOW() - (v_eff_ttl || ' days')::INTERVAL;
            ELSE
                WITH del AS (
                    DELETE FROM public.audit_log
                     WHERE tenant_id = r_tenant.tenant_id
                       AND created_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;
            END IF;

        ELSE
            CONTINUE;
        END IF;

        v_total_count := v_total_count + v_count;
    END LOOP;

    RETURN v_total_count;
END;
$$;


ALTER FUNCTION "public"."fn_apply_retention"("p_entity" "text", "p_dry_run" boolean) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_apply_retention"("p_entity" "text", "p_dry_run" boolean) IS 'Barrido de retención. SOLO service_role: recorre todos los tenants y borra sin validar pertenencia, así que un GRANT a authenticated es borrado cross-tenant. Lo tenía hasta el 2026-07-27 por privilegios por defecto del esquema.';



CREATE OR REPLACE FUNCTION "public"."fn_block_legal_acceptance_modify"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    RAISE EXCEPTION 'tenant_legal_acceptance es append-only (TG_OP=%)', TG_OP;
END;
$$;


ALTER FUNCTION "public"."fn_block_legal_acceptance_modify"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_cancel_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    was_in_progress BOOLEAN := FALSE;
    deleted         TIMESTAMPTZ;
BEGIN
    SELECT (deletion_requested_at IS NOT NULL), deleted_at
      INTO was_in_progress, deleted
      FROM public.tenants
     WHERE id = p_tenant_id
       FOR UPDATE;

    IF NOT was_in_progress THEN
        RETURN FALSE;
    END IF;

    -- NO se puede cancelar si ya fue hard-deleted.
    IF deleted IS NOT NULL THEN
        RAISE EXCEPTION
            'Tenant % ya fue hard-deleted, no es cancelable',
            p_tenant_id
            USING ERRCODE = '40000';
    END IF;

    UPDATE public.tenants
       SET deletion_requested_at  = NULL,
           deletion_scheduled_for = NULL,
           deletion_requested_by  = NULL,
           deletion_reason        = NULL
     WHERE id = p_tenant_id;

    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'cancelled', p_actor_user_id, p_actor_email, p_actor_ip,
        jsonb_build_object('cancelled_at', NOW())
    );

    -- NOTA: las credenciales tenant_integrations + tenant_payment_methods
    -- quedan disconnected/inactive. El owner debe re-conectarlas vía UI
    -- normal (consciente decision para evitar replay attack: si el secret
    -- ya estuvo "out" durante el grace period, mejor rotar).
    RETURN TRUE;
END;
$$;


ALTER FUNCTION "public"."fn_cancel_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_cancel_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet") IS 'Revierte soft-delete dentro del grace period. NO restaura credenciales (consciente: forzar re-connect mitiga replay si el secret estuvo "out").';



CREATE OR REPLACE FUNCTION "public"."fn_claim_health_alert"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_status" "text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_prev   TEXT;
    v_should BOOLEAN;
BEGIN
    SELECT last_status INTO v_prev
      FROM public.provider_health_alert_dedup
     WHERE tenant_id = p_tenant_id
       AND provider  = p_provider
       AND metric    = p_metric
       FOR UPDATE;

    v_should := (v_prev IS NULL OR v_prev IN ('healthy', 'unknown'))
                AND p_status IN ('warning', 'critical');

    INSERT INTO public.provider_health_alert_dedup (
        tenant_id, provider, metric, last_status, alerted_at, updated_at
    ) VALUES (
        p_tenant_id, p_provider, p_metric, p_status,
        CASE WHEN v_should THEN NOW() ELSE NULL END,
        NOW()
    )
    ON CONFLICT (tenant_id, provider, metric) DO UPDATE
       SET last_status = EXCLUDED.last_status,
           alerted_at  = CASE
                             WHEN v_should THEN NOW()
                             ELSE public.provider_health_alert_dedup.alerted_at
                         END,
           updated_at  = NOW();

    RETURN v_should;
END;
$$;


ALTER FUNCTION "public"."fn_claim_health_alert"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_status" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_claim_health_alert"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_status" "text") IS 'F7 — claim atómico de alerta de salud. TRUE si el worker debe alertar (transición good→bad no notificada). Persiste el último status observado para no re-spamear tras restart. SECURITY DEFINER, solo service_role.';



CREATE OR REPLACE FUNCTION "public"."fn_cleanup_webhook_secrets"() RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    cleaned_count INTEGER := 0;
BEGIN
    -- NULL out previous_secret_hash + grace_period_until donde el grace
    -- ya expiró. NO borra la fila — el secret actual sigue activo.
    UPDATE public.tenant_webhook_secrets
       SET previous_secret_hash = NULL,
           grace_period_until   = NULL,
           updated_at           = NOW()
     WHERE grace_period_until IS NOT NULL
       AND grace_period_until  < NOW();

    GET DIAGNOSTICS cleaned_count = ROW_COUNT;
    RETURN cleaned_count;
END;
$$;


ALTER FUNCTION "public"."fn_cleanup_webhook_secrets"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_cleanup_webhook_secrets"() IS 'F.10 cierre: limpia grace period expirados en tenant_webhook_secrets. Invocada hourly desde services/ai-orchestrator/worker.py. Retorna cantidad de filas limpiadas (para métrica/log).';



CREATE OR REPLACE FUNCTION "public"."fn_consume_mfa_recovery_code"("p_user_id" "uuid", "p_code_hash" "text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    matched_id BIGINT;
BEGIN
    -- IMPORTANTE: el caller (backend Python) hace bcrypt-compare del
    -- plaintext contra TODOS los hashes del user. Si encuentra match,
    -- invoca esta función con el hash matched para marcarlo used.
    -- Esto evita hacer bcrypt-compare server-side dentro de plpgsql.
    SELECT id INTO matched_id
      FROM public.mfa_recovery_codes
     WHERE user_id   = p_user_id
       AND code_hash = p_code_hash
       AND used_at IS NULL
       FOR UPDATE;

    IF matched_id IS NULL THEN
        RETURN FALSE;
    END IF;

    UPDATE public.mfa_recovery_codes
       SET used_at = NOW()
     WHERE id = matched_id;

    RETURN TRUE;
END;
$$;


ALTER FUNCTION "public"."fn_consume_mfa_recovery_code"("p_user_id" "uuid", "p_code_hash" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_consume_mfa_recovery_code"("p_user_id" "uuid", "p_code_hash" "text") IS 'Marca un recovery code como usado. Atomic (FOR UPDATE lock previene doble consume). El bcrypt-compare lo hace el caller; esta función solo marca el hash matched como consumed.';



CREATE OR REPLACE FUNCTION "public"."fn_detect_health_degradations"("p_window_minutes" integer DEFAULT 10) RETURNS TABLE("tenant_id" "uuid", "provider" "text", "metric" "text", "value" "text", "status" "text", "detail" "jsonb")
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
    -- Métricas WARNING/CRITICAL observadas dentro de la ventana (transición reciente).
    -- El worker compara con el snapshot previo en memoria; este RPC es helper
    -- para queries globales del founder (Platform Console futuro).
    SELECT
        tenant_id, provider, metric, value, status, detail
      FROM public.tenant_provider_health
     WHERE status IN ('warning', 'critical')
       AND updated_at > NOW() - (p_window_minutes || ' minutes')::INTERVAL
     ORDER BY status DESC, observed_at DESC;
$$;


ALTER FUNCTION "public"."fn_detect_health_degradations"("p_window_minutes" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_detect_health_degradations"("p_window_minutes" integer) IS 'Helper Platform Console — listar todas las degradations recientes cross-tenant. Hoy NO usado (Tenant Console solo ve su propio data).';



CREATE OR REPLACE FUNCTION "public"."fn_document_hash"("p_doc" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    AS $$
    SELECT CASE
        WHEN p_doc IS NULL OR LENGTH(TRIM(p_doc)) = 0 THEN NULL
        ELSE encode(
            digest(
                upper(regexp_replace(p_doc, '[\s\-\.]', '', 'g')),
                'sha256'
            ),
            'hex'
        )
    END;
$$;


ALTER FUNCTION "public"."fn_document_hash"("p_doc" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_document_last4"("p_doc" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    AS $$
    SELECT CASE
        WHEN p_doc IS NULL THEN NULL
        ELSE right(regexp_replace(p_doc, '[\s\-\.]', '', 'g'), 4)
    END;
$$;


ALTER FUNCTION "public"."fn_document_last4"("p_doc" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_expire_abandoned_carts"() RETURNS integer
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  WITH upd AS (
    UPDATE public.conversation_carts
       SET status = 'abandoned',
           updated_at = NOW()
     WHERE status IN ('open', 'checkout')
       AND updated_at < NOW() - INTERVAL '7 days'
     RETURNING 1
  )
  SELECT COUNT(*)::INT FROM upd;
$$;


ALTER FUNCTION "public"."fn_expire_abandoned_carts"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_expire_stock_reservations"() RETURNS integer
    LANGUAGE "sql"
    AS $$
  WITH upd AS (
    UPDATE public.stock_reservations
       SET status = 'expired', released_at = NOW(), updated_at = NOW()
     WHERE status = 'active' AND expires_at <= NOW()
     RETURNING 1
  )
  SELECT COUNT(*)::INT FROM upd;
$$;


ALTER FUNCTION "public"."fn_expire_stock_reservations"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_expire_stock_reservations"() IS 'Barrido periódico (pg_cron cada 60s recomendado). Marca como expired las reservas con TTL vencido. SELECT cron.schedule(''expire_stock_reservations'', ''* * * * *'', $$SELECT public.fn_expire_stock_reservations();$$);';



CREATE OR REPLACE FUNCTION "public"."fn_hard_delete_tenant"("p_tenant_id" "uuid", "p_archive_path" "text", "p_evidence" "jsonb" DEFAULT '{}'::"jsonb") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    sched            TIMESTAMPTZ;
    already          TIMESTAMPTZ;
    v_storage_purged INTEGER := 0;
BEGIN
    -- Lock fila + validar que es elegible.
    SELECT deletion_scheduled_for, deleted_at
      INTO sched, already
      FROM public.tenants
     WHERE id = p_tenant_id
       FOR UPDATE;

    IF sched IS NULL THEN
        RAISE EXCEPTION
            'Tenant % NO tiene deletion_scheduled_for — no es elegible para hard-delete',
            p_tenant_id
            USING ERRCODE = '40000';
    END IF;

    IF already IS NOT NULL THEN
        -- Ya fue hard-deleted antes (idempotencia: cron pudo re-invocar).
        RETURN FALSE;
    END IF;

    IF sched > NOW() THEN
        RAISE EXCEPTION
            'Tenant % todavía en grace period (scheduled_for=%, NOW=%)',
            p_tenant_id, sched, NOW()
            USING ERRCODE = '40000';
    END IF;

    -- 1. Log evento 'archived' ANTES de borrar.
    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'archived', NULL, 'cron@worker', NULL,
        jsonb_build_object(
            'archive_path', p_archive_path,
            'archived_at', NOW()
        )
    );

    -- 2. Marcar deleted_at PRIMERO (audit trail incluso si cascade falla).
    --    NOTA: tenants es la fila principal — el CASCADE limpia ~50 tablas hijas.
    UPDATE public.tenants
       SET deleted_at = NOW()
     WHERE id = p_tenant_id;

    -- 3. Log evento 'hard_deleted' ANTES del DELETE — el log sobrevive
    --    porque tenant_offboarding_log NO tiene FK CASCADE a tenants.
    --    (Se re-loguea el conteo de storage tras la purga en el paso 3.5).
    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'hard_deleted', NULL, 'cron@worker', NULL,
        jsonb_build_object(
            'archive_path', p_archive_path,
            'evidence', p_evidence,
            'deleted_at', NOW()
        )
    );

    -- 3.5. Purga de objetos de Storage con PII del tenant (bucket tenant-media
    --      y cualquier otro bucket per-tenant). El CASCADE de tenants NO alcanza
    --      storage.objects → sin esto la PII de clientes queda en Storage.
    --      Best-effort: si algo falla, se registra pero NO se aborta el delete
    --      (compliance Art. 16 prioriza que el borrado del tenant se complete).
    BEGIN
        v_storage_purged := public.fn_purge_tenant_storage_objects(
            p_tenant_id, ARRAY['tenant-media']::TEXT[]
        );
        PERFORM public.fn_log_tenant_offboarding_event(
            p_tenant_id, 'hard_deleted', NULL, 'cron@worker', NULL,
            jsonb_build_object(
                'storage_objects_purged', v_storage_purged,
                'storage_buckets', ARRAY['tenant-media'],
                'note', 'purga DB de storage.objects; blob físico via admin script'
            )
        );
    EXCEPTION WHEN OTHERS THEN
        PERFORM public.fn_log_tenant_offboarding_event(
            p_tenant_id, 'hard_deleted', NULL, 'cron@worker', NULL,
            jsonb_build_object(
                'storage_purge_error', SQLERRM,
                'note', 'purga de Storage falló; requiere purga manual via admin script'
            )
        );
    END;

    -- 4. DELETE FROM tenants — CASCADE limpia todo lo que tenga FK ON DELETE CASCADE.
    --    Lo que NO tiene CASCADE (tenant_offboarding_log) sobrevive intencionalmente.
    DELETE FROM public.tenants WHERE id = p_tenant_id;

    RETURN TRUE;
END;
$$;


ALTER FUNCTION "public"."fn_hard_delete_tenant"("p_tenant_id" "uuid", "p_archive_path" "text", "p_evidence" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_hard_delete_tenant"("p_tenant_id" "uuid", "p_archive_path" "text", "p_evidence" "jsonb") IS 'J.2.4.4 Fase 2 + F6 — Hard-delete atómico del tenant. Pre-condición: caller (worker) debe haber subido snapshot del audit_log/consent/legal a Storage bucket "offboarding-archive" ANTES de invocar. Purga storage.objects con PII del tenant (fn_purge_tenant_storage_objects, best-effort) antes del DELETE. Logs "archived" + "hard_deleted" en tenant_offboarding_log (sobrevive CASCADE). Idempotente: si ya fue deleted, retorna FALSE sin error.';



CREATE OR REPLACE FUNCTION "public"."fn_list_tenants_pending_hard_delete"("p_limit" integer DEFAULT 50) RETURNS TABLE("tenant_id" "uuid", "deletion_scheduled_for" timestamp with time zone, "deletion_requested_at" timestamp with time zone, "grace_period_days" integer)
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
    SELECT
        t.id AS tenant_id,
        t.deletion_scheduled_for,
        t.deletion_requested_at,
        EXTRACT(DAY FROM (t.deletion_scheduled_for - t.deletion_requested_at))::INTEGER
            AS grace_period_days
      FROM public.tenants t
     WHERE t.deletion_scheduled_for IS NOT NULL
       AND t.deletion_scheduled_for <= NOW()
       AND t.deleted_at IS NULL
     ORDER BY t.deletion_scheduled_for ASC
     LIMIT p_limit;
$$;


ALTER FUNCTION "public"."fn_list_tenants_pending_hard_delete"("p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_list_tenants_pending_hard_delete"("p_limit" integer) IS 'F.10 + J.2.4.4 Fase 2 — invocado hourly por worker. Lista tenants cuyo grace period venció (deletion_scheduled_for <= NOW()) y aún no fueron hard-deleted. Worker hace snapshot + invoca fn_hard_delete_tenant.';



CREATE OR REPLACE FUNCTION "public"."fn_log_tenant_offboarding_event"("p_tenant_id" "uuid", "p_event" "text", "p_actor_user_id" "uuid" DEFAULT NULL::"uuid", "p_actor_email" "text" DEFAULT NULL::"text", "p_actor_ip" "inet" DEFAULT NULL::"inet", "p_evidence" "jsonb" DEFAULT '{}'::"jsonb") RETURNS bigint
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    new_log_id BIGINT;
BEGIN
    INSERT INTO public.tenant_offboarding_log (
        tenant_id, event, actor_user_id, actor_email, actor_ip, evidence
    ) VALUES (
        p_tenant_id, p_event, p_actor_user_id, p_actor_email, p_actor_ip, p_evidence
    )
    RETURNING id INTO new_log_id;

    RETURN new_log_id;
END;
$$;


ALTER FUNCTION "public"."fn_log_tenant_offboarding_event"("p_tenant_id" "uuid", "p_event" "text", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_evidence" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_log_tenant_offboarding_event"("p_tenant_id" "uuid", "p_event" "text", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_evidence" "jsonb") IS 'Helper atómico para insertar evento de offboarding. SECURITY DEFINER porque el cron job y endpoints owner-only deben poder escribir sin estar bajo RLS authenticated.';



CREATE OR REPLACE FUNCTION "public"."fn_purge_orphan_shipment_quotes"("p_retention_days" integer DEFAULT 30) RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    WITH purged AS (
        DELETE FROM public.shipments
        WHERE status = 'quoted'
          AND selected_rate IS NULL
          AND created_at < NOW() - (p_retention_days || ' days')::interval
        RETURNING id
    )
    SELECT COUNT(*) INTO v_deleted FROM purged;

    RAISE NOTICE 'fn_purge_orphan_shipment_quotes: % filas eliminadas (retención % días)',
        v_deleted, p_retention_days;
    RETURN v_deleted;
END;
$$;


ALTER FUNCTION "public"."fn_purge_orphan_shipment_quotes"("p_retention_days" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_purge_orphan_shipment_quotes"("p_retention_days" integer) IS 'Mantenimiento: elimina cotizaciones huérfanas (quoted + selected_rate NULL + > N días). Cross-tenant, SECURITY DEFINER. Agendada vía pg_cron. Espejo del endpoint manual DELETE /shipping/orphans.';



CREATE OR REPLACE FUNCTION "public"."fn_purge_tenant_storage_objects"("p_tenant_id" "uuid", "p_bucket_ids" "text"[] DEFAULT ARRAY['tenant-media'::"text"]) RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_deleted INTEGER := 0;
    v_buckets TEXT[];
BEGIN
    IF p_tenant_id IS NULL THEN
        RAISE EXCEPTION 'p_tenant_id es obligatorio' USING ERRCODE = '40000';
    END IF;

    -- Degrada seguro si Storage no está instalado en este entorno.
    IF to_regclass('storage.objects') IS NULL THEN
        RETURN 0;
    END IF;

    -- Default + exclusión defensiva del bucket de archivo legal (nunca purgarlo).
    v_buckets := COALESCE(p_bucket_ids, ARRAY['tenant-media']::TEXT[]);
    v_buckets := ARRAY(
        SELECT DISTINCT b
          FROM unnest(v_buckets) AS b
         WHERE b IS NOT NULL
           AND b <> 'offboarding-archive'
    );

    IF array_length(v_buckets, 1) IS NULL THEN
        RETURN 0;
    END IF;

    -- El trigger storage.protect_delete exige storage.allow_delete_query='true'
    -- en la sesión (protección anti-borrado-accidental de Supabase, verificado
    -- en prod 2026-08-14). La RPC es la vía autorizada de erasure → lo fija
    -- LOCAL a su transacción (se revierte al commit; sin efecto fuera).
    PERFORM set_config('storage.allow_delete_query', 'true', true);

    -- Borra AMBOS prefijos del tenant (G8a): '{tenant_id}/%' (media library,
    -- logo) e 'inbox-attachments/{tenant_id}/%' (adjuntos de conversación).
    -- El '/' evita colisión con otro tenant cuyo id sea prefijo de éste.
    DELETE FROM storage.objects o
     WHERE o.bucket_id = ANY(v_buckets)
       AND (
             o.name LIKE (p_tenant_id::TEXT || '/%')
          OR o.name LIKE ('inbox-attachments/' || p_tenant_id::TEXT || '/%')
       );

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;


ALTER FUNCTION "public"."fn_purge_tenant_storage_objects"("p_tenant_id" "uuid", "p_bucket_ids" "text"[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_purge_tenant_storage_objects"("p_tenant_id" "uuid", "p_bucket_ids" "text"[]) IS 'F6 erasure + G8a — borra filas de storage.objects con name "{tenant_id}/%" o "inbox-attachments/{tenant_id}/%" en los buckets dados (default tenant-media). Excluye offboarding-archive. Degrada seguro sin schema storage. La purga FÍSICA del blob la completa scripts/admin/purge_tenant_storage.py. Idempotente.';



CREATE OR REPLACE FUNCTION "public"."fn_record_shipment_tracking_event"("p_tenant_id" "uuid", "p_shipment_id" "uuid", "p_order_id" "uuid", "p_provider" "text", "p_external_event_id" "text", "p_raw_status" "text", "p_raw_estado_id" integer, "p_internal_status" "text", "p_description" "text", "p_occurred_at" timestamp with time zone, "p_raw" "jsonb") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
DECLARE
    v_inserted INTEGER;
BEGIN
    INSERT INTO public.shipment_tracking_events (
        tenant_id, shipment_id, order_id, provider,
        external_event_id, raw_status, raw_estado_id,
        internal_status, description, occurred_at, raw
    ) VALUES (
        p_tenant_id, p_shipment_id, p_order_id, p_provider,
        p_external_event_id, p_raw_status, p_raw_estado_id,
        p_internal_status, p_description, p_occurred_at,
        COALESCE(p_raw, '{}'::jsonb)
    )
    ON CONFLICT (provider, external_event_id) DO NOTHING;

    GET DIAGNOSTICS v_inserted = ROW_COUNT;

    -- Si insertó (evento nuevo) Y no es terminal → actualizar shipments.status.
    -- ADR-0038: guard monotónico por occurred_at — NO aplicar un evento MÁS VIEJO
    -- que el que fijó el status actual (out-of-order / POSTs concurrentes). También
    -- sella status_occurred_at para la próxima comparación.
    IF v_inserted = 1 AND p_shipment_id IS NOT NULL THEN
        UPDATE public.shipments
        SET status = p_internal_status,
            -- GREATEST (review HIGH): NO bajar/borrar el sello. Un evento con
            -- p_occurred_at NULL no debe wipear status_occurred_at (GREATEST ignora
            -- NULLs en Postgres) — de lo contrario re-abriría la regresión que este
            -- guard cierra (el siguiente evento viejo pasaría el guard NULL).
            status_occurred_at = GREATEST(status_occurred_at, p_occurred_at),
            updated_at = NOW()
        WHERE id = p_shipment_id
          AND tenant_id = p_tenant_id
          AND status NOT IN ('delivered', 'returned', 'cancelled')
          AND (
            status_occurred_at IS NULL
            OR p_occurred_at IS NULL
            OR p_occurred_at >= status_occurred_at
          );
    END IF;

    RETURN (v_inserted = 1);
END;
$$;


ALTER FUNCTION "public"."fn_record_shipment_tracking_event"("p_tenant_id" "uuid", "p_shipment_id" "uuid", "p_order_id" "uuid", "p_provider" "text", "p_external_event_id" "text", "p_raw_status" "text", "p_raw_estado_id" integer, "p_internal_status" "text", "p_description" "text", "p_occurred_at" timestamp with time zone, "p_raw" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_record_shipment_tracking_event"("p_tenant_id" "uuid", "p_shipment_id" "uuid", "p_order_id" "uuid", "p_provider" "text", "p_external_event_id" "text", "p_raw_status" "text", "p_raw_estado_id" integer, "p_internal_status" "text", "p_description" "text", "p_occurred_at" timestamp with time zone, "p_raw" "jsonb") IS 'Atómico: dedup + insert evento + actualizar shipments.status si nuevo evento y shipment no en terminal. Retorna TRUE si insertado, FALSE si duplicado. Idempotente, at-least-once safe.';



CREATE OR REPLACE FUNCTION "public"."fn_regenerate_mfa_recovery_codes"("p_user_id" "uuid", "p_code_hashes" "text"[]) RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    inserted_count INTEGER := 0;
BEGIN
    -- Borrar codes anteriores (usados o no).
    DELETE FROM public.mfa_recovery_codes WHERE user_id = p_user_id;

    -- Insertar nuevos.
    INSERT INTO public.mfa_recovery_codes (user_id, code_hash)
    SELECT p_user_id, unnest(p_code_hashes);

    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RETURN inserted_count;
END;
$$;


ALTER FUNCTION "public"."fn_regenerate_mfa_recovery_codes"("p_user_id" "uuid", "p_code_hashes" "text"[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_regenerate_mfa_recovery_codes"("p_user_id" "uuid", "p_code_hashes" "text"[]) IS 'Regenera recovery codes del usuario: borra previos + inserta nuevos. Caller debe bcrypt-hashear los plaintexts antes de pasar el array.';



CREATE OR REPLACE FUNCTION "public"."fn_request_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_reason" "text", "p_grace_period_days" integer DEFAULT 30) RETURNS timestamp with time zone
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    scheduled_for TIMESTAMPTZ;
    existing      TIMESTAMPTZ;
BEGIN
    -- Bloqueo de fila para evitar race.
    SELECT deletion_requested_at INTO existing
      FROM public.tenants
     WHERE id = p_tenant_id
       FOR UPDATE;

    IF existing IS NOT NULL THEN
        RAISE EXCEPTION
            'Tenant % ya tiene offboarding en curso desde %',
            p_tenant_id, existing
            USING ERRCODE = '40000'; -- transaction integrity
    END IF;

    scheduled_for := NOW() + (p_grace_period_days || ' days')::INTERVAL;

    UPDATE public.tenants
       SET deletion_requested_at  = NOW(),
           deletion_scheduled_for = scheduled_for,
           deletion_requested_by  = p_actor_user_id,
           deletion_reason        = p_reason
     WHERE id = p_tenant_id;

    -- Invalidar credenciales sensibles inmediatamente (NO esperar al hard-delete).
    -- Si el owner cancela, el flujo de re-credentialing lo manejará la UI.
    UPDATE public.tenant_integrations
       SET status = 'disconnected'
     WHERE tenant_id = p_tenant_id
       AND status   = 'connected';

    -- FIX F6: la columna canónica es `enabled` (NO is_active). El typo original
    -- abortaba la RPC con 42703 y el cierre de cuenta nunca completaba.
    UPDATE public.tenant_payment_methods
       SET enabled = FALSE
     WHERE tenant_id = p_tenant_id
       AND enabled = TRUE;

    -- Log evento.
    PERFORM public.fn_log_tenant_offboarding_event(
        p_tenant_id, 'requested', p_actor_user_id, p_actor_email, p_actor_ip,
        jsonb_build_object(
            'reason', p_reason,
            'scheduled_for', scheduled_for,
            'grace_period_days', p_grace_period_days
        )
    );

    RETURN scheduled_for;
END;
$$;


ALTER FUNCTION "public"."fn_request_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_reason" "text", "p_grace_period_days" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_request_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_reason" "text", "p_grace_period_days" integer) IS 'Soft-delete del tenant + invalidación de credenciales sensibles + log evento. Atómico (FOR UPDATE row lock). Levanta SQLSTATE 40000 si ya hay offboarding en curso. F6 2026-07-04: fix columna enabled (era is_active → 42703).';



CREATE OR REPLACE FUNCTION "public"."fn_sync_document_derived"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    IF NEW.document_number IS NULL THEN
        NEW.document_number_hash  := NULL;
        NEW.document_number_last4 := NULL;
    ELSE
        NEW.document_number_hash  := public.fn_document_hash(NEW.document_number);
        NEW.document_number_last4 := public.fn_document_last4(NEW.document_number);
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."fn_sync_document_derived"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fn_upsert_provider_health"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_value" "text", "p_threshold" "text" DEFAULT NULL::"text", "p_status" "text" DEFAULT 'unknown'::"text", "p_detail" "jsonb" DEFAULT '{}'::"jsonb") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
    INSERT INTO public.tenant_provider_health (
        tenant_id, provider, metric, value, threshold, status, detail,
        observed_at, updated_at
    ) VALUES (
        p_tenant_id, p_provider, p_metric, p_value, p_threshold, p_status, p_detail,
        NOW(), NOW()
    )
    ON CONFLICT (tenant_id, provider, metric)
    DO UPDATE
       SET value       = EXCLUDED.value,
           threshold   = EXCLUDED.threshold,
           status      = EXCLUDED.status,
           detail      = EXCLUDED.detail,
           observed_at = NOW(),
           updated_at  = NOW();
END;
$$;


ALTER FUNCTION "public"."fn_upsert_provider_health"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_value" "text", "p_threshold" "text", "p_status" "text", "p_detail" "jsonb") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_upsert_provider_health"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_value" "text", "p_threshold" "text", "p_status" "text", "p_detail" "jsonb") IS 'J.2.11 — cron worker invoca esta función para registrar/actualizar métricas de salud por (tenant, provider, metric). Status determina semáforo UI.';



CREATE OR REPLACE FUNCTION "public"."fn_variation_available_stock"("p_variation_id" "uuid") RETURNS integer
    LANGUAGE "sql" STABLE
    AS $$
  SELECT GREATEST(
    COALESCE(pv.stock_quantity, 0)
    - COALESCE((
        SELECT SUM(sr.qty)
        FROM public.stock_reservations sr
        WHERE sr.variation_id = pv.id
          AND sr.status = 'active'
          AND sr.expires_at > NOW()
      ), 0),
    0
  )::INTEGER
  FROM public.product_variations pv
  WHERE pv.id = p_variation_id;
$$;


ALTER FUNCTION "public"."fn_variation_available_stock"("p_variation_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."fn_variation_available_stock"("p_variation_id" "uuid") IS 'Stock disponible = stock_quantity - SUM(active_reservations.qty con TTL vivo). Filtro defensivo expires_at > NOW() asegura correctness aún sin cleanup periódico.';



CREATE OR REPLACE FUNCTION "public"."get_aveonline_credentials"("p_tenant_id" "uuid") RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'vault', 'pg_catalog'
    AS $$
DECLARE
    v_creds   JSONB;
    v_secret  TEXT;
    v_pass_id UUID;
BEGIN
    -- Fail-closed: `anon` NUNCA lee credenciales, aunque alguien re-otorgue el EXECUTE.
    IF auth.role() = 'anon' THEN
        RETURN NULL;
    END IF;

    -- Verificación tenant_users (solo authenticated del tenant vía API).
    -- service_role bypasa porque maneja todos los tenants.
    -- Track9/A9: owner/manager + status='active' (antes: cualquier miembro, incluso
    -- desactivado, leía usuario+password del carrier).
    IF auth.uid() IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = p_tenant_id AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN NULL;
        END IF;
    END IF;

    SELECT credentials INTO v_creds
    FROM public.tenant_integrations
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline'
      AND status = 'connected'
    LIMIT 1;

    IF v_creds IS NULL THEN
        RETURN NULL;
    END IF;

    -- Resolver password desde Vault (si está almacenado).
    v_pass_id := NULLIF(v_creds->>'password_secret_id', '')::uuid;
    IF v_pass_id IS NOT NULL THEN
        SELECT decrypted_secret INTO v_secret
        FROM vault.decrypted_secrets WHERE id = v_pass_id;
        IF v_secret IS NOT NULL THEN
            v_creds := v_creds || jsonb_build_object('password', v_secret);
        END IF;
    END IF;

    RETURN v_creds;
END;
$$;


ALTER FUNCTION "public"."get_aveonline_credentials"("p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_aveonline_credentials"("p_tenant_id" "uuid") IS 'Devuelve credenciales Aveonline del tenant (password resuelto desde Vault). anon SIN acceso (revocado + fail-closed). authenticated: solo miembros del tenant. service_role: acceso backend.';



CREATE OR REPLACE FUNCTION "public"."get_tenant_plan_capabilities"("p_tenant_id" "uuid") RETURNS TABLE("plan_code" "text", "capability_key" "text", "enabled" boolean, "limit_value" bigint, "period" "text", "used" bigint, "remaining" bigint, "reset_at" timestamp with time zone)
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
  WITH subscription AS (
    SELECT
      COALESCE(
        (SELECT ts.plan_code FROM public.tenant_subscriptions ts WHERE ts.tenant_id = p_tenant_id LIMIT 1),
        'basic'
      ) AS plan_code
  ),
  caps AS (
    SELECT
      s.plan_code,
      pc.capability_key,
      pc.enabled,
      pc.limit_value,
      pc.period,
      CASE
        WHEN pc.period = 'month' THEN date_trunc('month', NOW())
        WHEN pc.period = 'day' THEN date_trunc('day', NOW())
        WHEN pc.period = 'minute' THEN date_trunc('minute', NOW())
        ELSE date_trunc('month', NOW())
      END AS period_start,
      CASE
        WHEN pc.period = 'month' THEN date_trunc('month', NOW()) + INTERVAL '1 month'
        WHEN pc.period = 'day' THEN date_trunc('day', NOW()) + INTERVAL '1 day'
        WHEN pc.period = 'minute' THEN date_trunc('minute', NOW()) + INTERVAL '1 minute'
        ELSE date_trunc('month', NOW()) + INTERVAL '1 month'
      END AS period_end
    FROM subscription s
    JOIN public.plan_capabilities pc ON pc.plan_code = s.plan_code
  )
  SELECT
    c.plan_code,
    c.capability_key,
    c.enabled,
    c.limit_value,
    c.period,
    COALESCE(uc.usage_count, 0) AS used,
    CASE WHEN c.limit_value IS NULL THEN NULL ELSE GREATEST(c.limit_value - COALESCE(uc.usage_count, 0), 0) END AS remaining,
    c.period_end AS reset_at
  FROM caps c
  LEFT JOIN public.tenant_usage_counters uc
    ON uc.tenant_id = p_tenant_id
    AND uc.capability_key = c.capability_key
    AND uc.period_start = c.period_start
    AND uc.period_end = c.period_end
  ORDER BY c.capability_key ASC;
$$;


ALTER FUNCTION "public"."get_tenant_plan_capabilities"("p_tenant_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_tenant_team"() RETURNS TABLE("user_id" "uuid", "email" "text", "role" "text", "status" "text", "joined_at" timestamp with time zone, "confirmed" boolean)
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public', 'auth'
    AS $$
    SELECT
        tu.user_id,
        u.email,
        tu.role,
        tu.status,
        tu.created_at  AS joined_at,
        (u.email_confirmed_at IS NOT NULL) AS confirmed
    FROM public.tenant_users tu
    JOIN auth.users u ON u.id = tu.user_id
    WHERE tu.tenant_id = (
        (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
    )
    ORDER BY tu.created_at ASC;
$$;


ALTER FUNCTION "public"."get_tenant_team"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."log_audit_export"("p_row_count" integer, "p_filters" "jsonb" DEFAULT '{}'::"jsonb", "p_ip" "text" DEFAULT NULL::"text", "p_user_agent" "text" DEFAULT NULL::"text") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_tenant  UUID := app_current_tenant();
    v_uid     UUID := auth.uid();
    v_email   TEXT := auth.jwt() ->> 'email';
BEGIN
    -- Sin tenant resoluble no hay contexto seguro: no-op (evita filas huérfanas).
    IF v_tenant IS NULL THEN
        RETURN;
    END IF;

    -- ── Traza de acceso a PII (compliance Habeas Data Art. 9) ────────────────
    BEGIN
        INSERT INTO public.pii_access_log (
            tenant_id, contact_id, accessed_by, actor_user_id,
            purpose, fields_accessed, ip_address, user_agent
        ) VALUES (
            v_tenant,
            NULL,                                    -- export masivo: no ligado a 1 contacto
            'user:' || COALESCE(v_email, v_uid::text, 'unknown'),
            v_uid,
            'data_export',
            ARRAY['audit_events']::text[],
            p_ip,
            p_user_agent
        );
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'log_audit_export: pii_access_log insert skipped (%).', SQLERRM;
    END;

    -- ── Evento en el registro de cambios (self-audit del export) ─────────────
    BEGIN
        INSERT INTO public.audit_log (
            tenant_id, user_id, user_email, action, entity_type, entity_id, payload
        ) VALUES (
            v_tenant,
            v_uid,
            v_email,
            'exported',
            'audit_log',
            NULL,
            jsonb_build_object('row_count', p_row_count, 'filters', COALESCE(p_filters, '{}'::jsonb))
        );
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'log_audit_export: audit_log insert skipped (%).', SQLERRM;
    END;
END;
$$;


ALTER FUNCTION "public"."log_audit_export"("p_row_count" integer, "p_filters" "jsonb", "p_ip" "text", "p_user_agent" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."log_audit_export"("p_row_count" integer, "p_filters" "jsonb", "p_ip" "text", "p_user_agent" "text") IS 'F4 — Registra un export CSV de auditoría en pii_access_log (data_export) + audit_log (exported). SECURITY DEFINER: deriva tenant/actor del JWT. Best-effort.';



CREATE OR REPLACE FUNCTION "public"."match_kb_documents"("query_embedding" "extensions"."vector", "match_threshold" double precision, "match_count" integer, "t_id" "uuid", "p_model_version" "text") RETURNS TABLE("id" "uuid", "title" "text", "content" "text", "category" "text", "similarity" double precision)
    LANGUAGE "sql" STABLE
    AS $$
  SELECT
    kb.id,
    kb.title,
    kb.content,
    kb.category,
    1 - (kb.embedding <=> query_embedding) AS similarity
  FROM kb_documents kb
  WHERE
    kb.tenant_id  = t_id
    AND kb.embedding IS NOT NULL
    AND kb.is_active  = true
    -- Guard de drift: incluye la versión vigente + los legacy sin versión (NULL);
    -- excluye docs con una versión de modelo KNOWN-distinta (espacio incompatible).
    AND (
      p_model_version IS NULL
      OR kb.embedding_model_version IS NULL
      OR kb.embedding_model_version = p_model_version
    )
    AND 1 - (kb.embedding <=> query_embedding) > match_threshold
  ORDER BY kb.embedding <=> query_embedding
  LIMIT match_count;
$$;


ALTER FUNCTION "public"."match_kb_documents"("query_embedding" "extensions"."vector", "match_threshold" double precision, "match_count" integer, "t_id" "uuid", "p_model_version" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."meli_webhook_seen"("p_application_id" "text", "p_resource" "text", "p_sent" "text", "p_ttl_seconds" integer DEFAULT 300) RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
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


ALTER FUNCTION "public"."meli_webhook_seen"("p_application_id" "text", "p_resource" "text", "p_sent" "text", "p_ttl_seconds" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."meli_webhook_seen"("p_application_id" "text", "p_resource" "text", "p_sent" "text", "p_ttl_seconds" integer) IS 'Atómica cross-réplica. Retorna TRUE si (app_id|resource|sent) ya fue visto en la ventana TTL.';



CREATE OR REPLACE FUNCTION "public"."metrics_orders_summary"("p_from" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_to" timestamp with time zone DEFAULT NULL::timestamp with time zone) RETURNS TABLE("orders_total" bigint, "orders_non_cancelled" bigint, "orders_cancelled" bigint, "gross_sales" numeric, "recognized_revenue" numeric, "delivered_revenue" numeric, "by_status" "jsonb")
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_tenant uuid;
BEGIN
  v_tenant := (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid;
  IF v_tenant IS NULL THEN
    RETURN; -- sin contexto de tenant → vacío (el cliente cae a fallback)
  END IF;

  RETURN QUERY
  WITH o AS (
    SELECT status::text AS status, COALESCE(total_amount, 0)::numeric AS amt
    FROM public.orders
    WHERE tenant_id = v_tenant
      AND (p_from IS NULL OR created_at >= p_from)
      AND (p_to   IS NULL OR created_at <  p_to)
  ),
  bs AS (
    SELECT jsonb_object_agg(status, c) AS js
    FROM (SELECT status, COUNT(*) AS c FROM o GROUP BY status) g
  )
  SELECT
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE status <> 'cancelled')::bigint,
    COUNT(*) FILTER (WHERE status = 'cancelled')::bigint,
    COALESCE(SUM(amt) FILTER (WHERE status <> 'cancelled'), 0)::numeric,
    COALESCE(SUM(amt) FILTER (WHERE status IN ('confirmed', 'processing', 'shipped', 'delivered')), 0)::numeric,
    COALESCE(SUM(amt) FILTER (WHERE status = 'delivered'), 0)::numeric,
    COALESCE((SELECT js FROM bs), '{}'::jsonb)
  FROM o;
END;
$$;


ALTER FUNCTION "public"."metrics_orders_summary"("p_from" timestamp with time zone, "p_to" timestamp with time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."metrics_orders_summary"("p_from" timestamp with time zone, "p_to" timestamp with time zone) IS 'Agregación exacta de pedidos por ventana [p_from, p_to) para un tenant (derivado del JWT). Evita el cap de 1000 filas de PostgREST en el cálculo de ingresos. recognized_revenue = confirmed+ (canónico, = Finanzas). F4.';



CREATE OR REPLACE FUNCTION "public"."metrics_orders_timeseries"("p_from" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_to" timestamp with time zone DEFAULT NULL::timestamp with time zone, "p_bucket" "text" DEFAULT 'month'::"text") RETURNS TABLE("bucket_start" timestamp with time zone, "orders_total" bigint, "orders_non_cancelled" bigint, "recognized_revenue" numeric, "gross_sales" numeric)
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_tenant uuid;
  v_bucket text;
BEGIN
  v_tenant := (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid;
  IF v_tenant IS NULL THEN
    RETURN; -- sin contexto de tenant → vacío (el cliente cae a fallback)
  END IF;

  -- Lista blanca: date_trunc solo admite estos campos; evita inyección vía p_bucket.
  v_bucket := lower(coalesce(p_bucket, 'month'));
  IF v_bucket NOT IN ('day', 'week', 'month') THEN
    v_bucket := 'month';
  END IF;

  RETURN QUERY
  WITH o AS (
    SELECT
      -- Trunca en hora Colombia y reconvierte a timestamptz para que el bucket
      -- represente el inicio real del día/semana/mes local (no UTC).
      (date_trunc(v_bucket, (created_at AT TIME ZONE 'America/Bogota'))
        AT TIME ZONE 'America/Bogota') AS bstart,
      status::text                     AS status,
      COALESCE(total_amount, 0)::numeric AS amt
    FROM public.orders
    WHERE tenant_id = v_tenant
      AND (p_from IS NULL OR created_at >= p_from)
      AND (p_to   IS NULL OR created_at <  p_to)
  )
  SELECT
    o.bstart,
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE o.status <> 'cancelled')::bigint,
    COALESCE(SUM(o.amt) FILTER (
      WHERE o.status IN ('confirmed', 'processing', 'shipped', 'delivered')), 0)::numeric,
    COALESCE(SUM(o.amt) FILTER (WHERE o.status <> 'cancelled'), 0)::numeric
  FROM o
  GROUP BY o.bstart
  ORDER BY o.bstart;
END;
$$;


ALTER FUNCTION "public"."metrics_orders_timeseries"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_bucket" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."metrics_orders_timeseries"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_bucket" "text") IS 'Serie temporal exacta de pedidos por bucket (day/week/month) en hora Colombia para un tenant (derivado del JWT). Habilita la tendencia MoM a escala sin el cap de 1000 filas de PostgREST. recognized_revenue = confirmed+ (= Finanzas). Complementa metrics_orders_summary (punto único). F-transversales.';



CREATE OR REPLACE FUNCTION "public"."outbound_idempotency_cleanup"() RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM public.outbound_idempotency_cache
    WHERE expires_at < NOW();
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;


ALTER FUNCTION "public"."outbound_idempotency_cleanup"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."outbound_idempotency_cleanup"() IS 'Cron daily. Borra entries con expires_at < NOW(). Retorna count borrado.';



CREATE OR REPLACE FUNCTION "public"."outbound_idempotency_lookup"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text") RETURNS TABLE("response_status" integer, "response_body" "jsonb", "response_headers" "jsonb", "created_at" timestamp with time zone)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
BEGIN
    RETURN QUERY
    SELECT c.response_status, c.response_body, c.response_headers, c.created_at
    FROM public.outbound_idempotency_cache c
    WHERE c.provider = p_provider
      AND c.tenant_id = p_tenant_id
      AND c.request_hash = p_request_hash
      AND c.expires_at > NOW()
    LIMIT 1;
END;
$$;


ALTER FUNCTION "public"."outbound_idempotency_lookup"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."outbound_idempotency_lookup"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text") IS 'Pre-POST lookup. Retorna fila si hash ya cacheado y vigente; vacío si miss.';



CREATE OR REPLACE FUNCTION "public"."outbound_idempotency_register"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text", "p_status" integer, "p_body" "jsonb", "p_headers" "jsonb", "p_ttl_seconds" integer DEFAULT 86400) RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
DECLARE
    v_inserted INTEGER;
BEGIN
    INSERT INTO public.outbound_idempotency_cache (
        provider, tenant_id, request_hash, response_status,
        response_body, response_headers, expires_at
    ) VALUES (
        p_provider, p_tenant_id, p_request_hash, p_status,
        p_body, p_headers, NOW() + (p_ttl_seconds || ' seconds')::INTERVAL
    )
    ON CONFLICT (provider, tenant_id, request_hash) DO NOTHING;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    RETURN (v_inserted > 0);
END;
$$;


ALTER FUNCTION "public"."outbound_idempotency_register"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text", "p_status" integer, "p_body" "jsonb", "p_headers" "jsonb", "p_ttl_seconds" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."outbound_idempotency_register"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text", "p_status" integer, "p_body" "jsonb", "p_headers" "jsonb", "p_ttl_seconds" integer) IS 'Post-POST insert. ON CONFLICT DO NOTHING evita race conditions. Retorna TRUE si insertado, FALSE si ya existía (concurrencia).';



CREATE OR REPLACE FUNCTION "public"."pgsec_create_secret"("p_secret" "text", "p_name" "text", "p_description" "text" DEFAULT ''::"text") RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vault', 'public', 'pg_catalog'
    AS $$
DECLARE
    v_owner uuid;
BEGIN
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(p_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: status='active' — un miembro desactivado NO puede crear secretos
        -- (su JWT sigue vivo vía refresh; el status solo se respeta si se filtra aquí).
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RAISE EXCEPTION 'tenant_ownership_violation: % no autorizado para %', auth.uid(), p_name;
        END IF;
    END IF;
    RETURN vault.create_secret(p_secret, p_name, p_description);
END;
$$;


ALTER FUNCTION "public"."pgsec_create_secret"("p_secret" "text", "p_name" "text", "p_description" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."pgsec_delete_secret"("p_id" "uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vault', 'public', 'pg_catalog'
    AS $$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN;
    END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active'.
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN;
        END IF;
    END IF;
    DELETE FROM vault.secrets WHERE id = p_id;
END;
$$;


ALTER FUNCTION "public"."pgsec_delete_secret"("p_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."pgsec_list_secrets_by_name_pattern"("p_pattern" "text") RETURNS TABLE("id" "uuid", "name" "text")
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'vault', 'pg_catalog'
    AS $$
    SELECT id, name FROM vault.secrets WHERE name LIKE p_pattern;
$$;


ALTER FUNCTION "public"."pgsec_list_secrets_by_name_pattern"("p_pattern" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."pgsec_read_secret"("p_id" "uuid") RETURNS "text"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vault', 'public', 'pg_catalog'
    AS $$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    -- Fail-closed: `anon` NUNCA puede leer secretos, aunque alguien re-otorgue el EXECUTE.
    IF auth.role() = 'anon' THEN
        RETURN NULL;
    END IF;

    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN NULL;
    END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active' (W1 sigue: NO operator).
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN NULL;
        END IF;
    END IF;
    RETURN (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = p_id);
END;
$$;


ALTER FUNCTION "public"."pgsec_read_secret"("p_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."pgsec_read_secret"("p_id" "uuid") IS 'Lee un secreto de Vault. anon SIN acceso (revocado + fail-closed). authenticated: solo owner/manager del tenant dueño del secreto. service_role: acceso backend.';



CREATE OR REPLACE FUNCTION "public"."pgsec_update_secret"("p_id" "uuid", "p_secret" "text") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vault', 'public', 'pg_catalog'
    AS $$
DECLARE
    v_name  text;
    v_owner uuid;
BEGIN
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN
        RETURN;
    END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active'.
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RETURN;
        END IF;
    END IF;
    PERFORM vault.update_secret(p_id, p_secret);
END;
$$;


ALTER FUNCTION "public"."pgsec_update_secret"("p_id" "uuid", "p_secret" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."pgsec_upsert_secret"("p_name" "text", "p_secret" "text", "p_description" "text" DEFAULT ''::"text") RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'vault', 'public', 'pg_catalog'
    AS $$
DECLARE
    v_id    uuid;
    v_owner uuid;
BEGIN
    IF auth.uid() IS NOT NULL THEN
        BEGIN
            v_owner := split_part(p_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN
            v_owner := NULL;
        END;
        -- Track9/A9: + status='active'.
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
              AND role IN ('owner', 'manager')
              AND status = 'active'
        ) THEN
            RAISE EXCEPTION 'tenant_ownership_violation: % no autorizado para %', auth.uid(), p_name;
        END IF;
    END IF;
    SELECT id INTO v_id FROM vault.secrets WHERE name = p_name LIMIT 1;
    IF v_id IS NOT NULL THEN
        PERFORM vault.update_secret(v_id, p_secret);
        RETURN v_id;
    ELSE
        RETURN vault.create_secret(p_secret, p_name, p_description);
    END IF;
END;
$$;


ALTER FUNCTION "public"."pgsec_upsert_secret"("p_name" "text", "p_secret" "text", "p_description" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."pii_access_log_block_modify"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    -- Track9/M13: la retención y los admins SÍ pueden purgar (la ley MANDA suprimir
    -- PII vencida); el bloqueo es para roles de cliente vía PostgREST.
    IF current_user IN ('service_role', 'postgres', 'supabase_admin', 'supabase_storage_admin') THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'pii_access_log es append-only (Ley 1581 Art. 9)';
END;
$$;


ALTER FUNCTION "public"."pii_access_log_block_modify"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."provision_tenant"("p_tenant_name" "text", "p_owner_user_id" "uuid", "p_plan_code" "text" DEFAULT 'basic'::"text", "p_actor_user_id" "uuid" DEFAULT NULL::"uuid") RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_tenant_id uuid;
  v_actor_email text;
BEGIN
  IF p_tenant_name IS NULL OR length(btrim(p_tenant_name)) = 0 THEN
    RAISE EXCEPTION 'provision_tenant: p_tenant_name requerido';
  END IF;
  IF p_owner_user_id IS NULL THEN
    RAISE EXCEPTION 'provision_tenant: p_owner_user_id requerido (crea el usuario auth primero)';
  END IF;

  INSERT INTO public.tenants (name)
  VALUES (btrim(p_tenant_name))
  RETURNING id INTO v_tenant_id;

  INSERT INTO public.tenant_users (user_id, tenant_id, role, status)
  VALUES (p_owner_user_id, v_tenant_id, 'owner', 'active');

  -- FIX: el trigger trg_seed_tenant_subscription_default ya insertó una fila 'basic' al crear el
  -- tenant. ON CONFLICT DO UPDATE hace que el plan elegido por el RPC prevalezca (antes: duplicate).
  INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status)
  VALUES (v_tenant_id, COALESCE(NULLIF(btrim(p_plan_code), ''), 'basic'), 'active')
  ON CONFLICT (tenant_id) DO UPDATE
    SET plan_code = EXCLUDED.plan_code,
        status = EXCLUDED.status;

  -- F5 decisión #1: nacer agentic. Row dedicado provider='agentic' (mismo patrón
  -- whatsapp/wompi/aveonline) leído por dispatcher.is_tenant_agentic_enabled.
  INSERT INTO public.tenant_integrations (tenant_id, provider, status, meta)
  VALUES (v_tenant_id, 'agentic', 'connected', jsonb_build_object('agentic_enabled', true))
  ON CONFLICT (tenant_id, provider) DO NOTHING;

  -- Audit trail atómico. actor = quien invoca (service_role vía script); snapshot de email si se conoce.
  IF p_actor_user_id IS NOT NULL THEN
    SELECT email INTO v_actor_email FROM auth.users WHERE id = p_actor_user_id;
  END IF;
  INSERT INTO public.audit_log (tenant_id, user_id, user_email, action, entity_type, entity_id, payload)
  VALUES (
    v_tenant_id, p_actor_user_id, v_actor_email, 'tenant.provisioned', 'tenant', v_tenant_id::text,
    jsonb_build_object(
      'owner_user_id', p_owner_user_id,
      'plan_code', COALESCE(NULLIF(btrim(p_plan_code), ''), 'basic'),
      'tenant_name', btrim(p_tenant_name),
      'agentic_enabled', true,
      'via', 'provision_tenant_rpc'
    )
  );

  RETURN v_tenant_id;
END;
$$;


ALTER FUNCTION "public"."provision_tenant"("p_tenant_name" "text", "p_owner_user_id" "uuid", "p_plan_code" "text", "p_actor_user_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."provision_tenant"("p_tenant_name" "text", "p_owner_user_id" "uuid", "p_plan_code" "text", "p_actor_user_id" "uuid") IS 'F3+F5: crea tenant + primer owner + subscripción + row tenant_integrations provider=agentic (agentic_enabled=true → nace en bot agentic, no legacy V1) + fila audit_log, todo en 1 transacción. Solo service_role (onboarding admin, no signup público). El usuario auth del owner debe existir antes (p_owner_user_id).';



CREATE OR REPLACE FUNCTION "public"."rate_limit_hit"("p_key" "text", "p_limit" integer, "p_window_seconds" integer) RETURNS TABLE("allowed" boolean, "remaining" integer, "reset_in" integer)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_window_start  BIGINT;
    v_window_key    TEXT;
    v_expires_at    TIMESTAMPTZ;
    v_count         INTEGER;
BEGIN
    v_window_start := (FLOOR(EXTRACT(EPOCH FROM NOW()) / p_window_seconds)::BIGINT) * p_window_seconds;
    v_window_key   := p_key || ':' || v_window_start::TEXT;
    v_expires_at   := TO_TIMESTAMP(v_window_start + p_window_seconds);

    INSERT INTO public.rate_limit_windows (window_key, count, expires_at)
    VALUES (v_window_key, 1, v_expires_at)
    ON CONFLICT (window_key)
    DO UPDATE SET count = rate_limit_windows.count + 1
    RETURNING rate_limit_windows.count INTO v_count;

    RETURN QUERY SELECT
        (v_count <= p_limit)                                            AS allowed,
        GREATEST(0, p_limit - v_count)                                  AS remaining,
        -- Rev. 103 — cast explícito a INTEGER. La aritmética BIGINT+INT
        -- producía BIGINT y el RETURN QUERY rechazaba por mismatch.
        GREATEST(
            0,
            (v_window_start + p_window_seconds - EXTRACT(EPOCH FROM NOW())::BIGINT)::INTEGER
        )                                                               AS reset_in;
END;
$$;


ALTER FUNCTION "public"."rate_limit_hit"("p_key" "text", "p_limit" integer, "p_window_seconds" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."reject_audit_log_mutation"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
    -- audit_log es append-only para los miembros del tenant. auth.role() lee el
    -- claim 'role' del JWT: 'authenticated'/'anon' = miembro → siempre rechazado.
    -- service_role / pg_cron / postgres (retención) → auth.role() NULL o 'service_role'
    -- → permitido (la retención necesita DELETE de filas fuera de ventana).
    IF COALESCE(auth.role(), '') IN ('authenticated', 'anon') THEN
        RAISE EXCEPTION 'audit_log es append-only: % no permitido para miembros', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END;
$$;


ALTER FUNCTION "public"."reject_audit_log_mutation"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."reject_audit_log_mutation"() IS 'BLOQUE 0 — audit_log append-only: rechaza UPDATE/DELETE de miembros (auth.role authenticated/anon). service_role/retención permitidos.';



CREATE OR REPLACE FUNCTION "public"."reversion_procede"("p_order_id" "uuid", "p_tenant_id" "uuid") RETURNS "text"
    LANGUAGE "plpgsql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_metodo TEXT;
BEGIN
    SELECT o.payment_method INTO v_metodo
      FROM public.orders o
     WHERE o.id = p_order_id AND o.tenant_id = p_tenant_id;

    IF NOT FOUND THEN
        RETURN 'pedido_inexistente';
    END IF;

    -- Art. 2.2.2.51.1: "no procede cuando hayan sido realizados por medio de canales
    -- presenciales". Contra entrega en efectivo es presencial — no hay instrumento de
    -- pago electrónico que reversar. El camino ahí es el reembolso comercial, y decirle
    -- otra cosa al comprador sería prometerle un derecho que no tiene.
    -- El CHECK de `orders` hoy solo admite 'credit' y 'cod'. Los sinónimos se dejan
    -- porque un canal nuevo (Nequi, transferencia) entrará por acá antes de que nadie se
    -- acuerde de esta función, y el modo seguro de fallar es NO radicar.
    IF COALESCE(v_metodo, '') IN ('cod', 'cash', 'efectivo') THEN
        RETURN 'pago_no_electronico';
    END IF;

    -- Sin forma de pago registrada no se puede afirmar que fue electrónico. Se prefiere
    -- no radicar a radicar sobre un supuesto: la constancia afirma hechos.
    IF COALESCE(btrim(v_metodo), '') = '' THEN
        RETURN 'forma_de_pago_desconocida';
    END IF;

    RETURN 'procede';
END;
$$;


ALTER FUNCTION "public"."reversion_procede"("p_order_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."reversion_procede"("p_order_id" "uuid", "p_tenant_id" "uuid") IS 'Devuelve "procede" o el motivo por el que no. Decreto 1074 art. 2.2.2.51.1: la reversión no aplica a pagos por canales presenciales (contra entrega en efectivo).';



CREATE OR REPLACE FUNCTION "public"."rpc_dashboard_revenue"() RETURNS TABLE("revenue_today" numeric, "revenue_month" numeric)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public'
    AS $$
  WITH b AS (
    SELECT
      timezone('America/Bogota', date_trunc('day',   timezone('America/Bogota', now()))) AS day_start,
      timezone('America/Bogota', date_trunc('month', timezone('America/Bogota', now()))) AS month_start
  ),
  tid AS (SELECT public.app_current_tenant() AS t),
  gross AS (
    SELECT
      COALESCE(SUM(o.total_amount) FILTER (WHERE o.created_at >= b.day_start),   0) AS today,
      COALESCE(SUM(o.total_amount) FILTER (WHERE o.created_at >= b.month_start), 0) AS month
    FROM b, tid, public.orders o
    WHERE o.tenant_id = tid.t
      AND o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
      AND o.created_at >= b.month_start
  ),
  claim_refunds AS (
    SELECT
      COALESCE(SUM(c.refunded_amount) FILTER (WHERE c.refunded_at >= b.day_start),   0) AS today,
      COALESCE(SUM(c.refunded_amount) FILTER (WHERE c.refunded_at >= b.month_start), 0) AS month
    FROM b, tid, public.claims c
    JOIN public.orders o
      ON o.id = c.order_id
     AND o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
    WHERE c.tenant_id = tid.t
      AND c.status = 'refunded'
      AND c.refunded_amount IS NOT NULL
      AND c.refunded_at >= b.month_start
  ),
  rma_refunds AS (
    SELECT
      COALESCE(SUM(r.refund_amount_cents) FILTER (WHERE r.refund_completed_at >= b.day_start),   0) / 100.0 AS today,
      COALESCE(SUM(r.refund_amount_cents) FILTER (WHERE r.refund_completed_at >= b.month_start), 0) / 100.0 AS month
    FROM b, tid, public.rma_requests r
    JOIN public.orders o
      ON o.id = r.order_id
     AND o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
    WHERE r.tenant_id = tid.t
      AND r.refund_completed_at IS NOT NULL
      AND r.refund_completed_at >= b.month_start
  )
  SELECT
    -- ROUND a 2 decimales: el /100.0 de RMA introduce precisión numérica larga.
    ROUND((gross.today - claim_refunds.today - rma_refunds.today)::numeric, 2)  AS revenue_today,
    ROUND((gross.month - claim_refunds.month - rma_refunds.month)::numeric, 2)  AS revenue_month
  FROM gross, claim_refunds, rma_refunds;
$$;


ALTER FUNCTION "public"."rpc_dashboard_revenue"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rpc_find_constancias_por_entregar"("p_csw_hours" integer DEFAULT 24, "p_limit" integer DEFAULT 50) RETURNS TABLE("reversal_id" "uuid", "tenant_id" "uuid", "conversation_id" "uuid", "radicado" "text", "constancia" "jsonb", "dentro_de_csw" boolean)
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT r.id, r.tenant_id, r.conversation_id, r.radicado, r.constancia,
           EXISTS (
               SELECT 1 FROM public.messages m
                WHERE m.conversation_id = r.conversation_id
                  AND m.tenant_id = r.tenant_id
                  AND m.direction = 'inbound'
                  AND m.created_at >= NOW() - make_interval(hours => p_csw_hours)
           )
      FROM public.payment_reversal_requests r
     WHERE r.constancia_emitida_at IS NOT NULL
       AND r.constancia_entregada_at IS NULL
       AND r.constancia_entrega_fallida IS NULL
       AND r.conversation_id IS NOT NULL
     ORDER BY r.constancia_emitida_at
     LIMIT GREATEST(p_limit, 1);
$$;


ALTER FUNCTION "public"."rpc_find_constancias_por_entregar"("p_csw_hours" integer, "p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rpc_find_dobles_pagos_sin_avisar"("p_limit" integer DEFAULT 50) RETURNS TABLE("reversal_id" "uuid", "tenant_id" "uuid", "radicado" "text", "reembolso" numeric, "reversion" numeric)
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT r.id, r.tenant_id, r.radicado, r.reembolso_directo_valor, r.reversion_valor
      FROM public.payment_reversal_requests r
     WHERE r.doble_pago_detectado_at IS NOT NULL
       AND r.doble_pago_avisado_at IS NULL
     ORDER BY r.doble_pago_detectado_at
     LIMIT GREATEST(p_limit, 1);
$$;


ALTER FUNCTION "public"."rpc_find_dobles_pagos_sin_avisar"("p_limit" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rpc_find_incoherent_orders"("p_window_hours" integer DEFAULT 48, "p_limit" integer DEFAULT 50) RETURNS TABLE("order_id" "uuid", "tenant_id" "uuid", "status" "text", "total_registrado" numeric, "total_calculado" numeric, "diferencia" numeric)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT o.id, o.tenant_id, o.status, m.total_registrado, m.total_calculado, m.diferencia
    FROM public.orders o
    CROSS JOIN LATERAL public.rpc_order_money(o.id, o.tenant_id) m
    WHERE o.status NOT IN ('cancelled', 'pending')
      AND o.created_at >= NOW() - make_interval(hours => p_window_hours)
      AND NOT m.coherente
    ORDER BY ABS(m.diferencia) DESC
    LIMIT GREATEST(1, p_limit);
$$;


ALTER FUNCTION "public"."rpc_find_incoherent_orders"("p_window_hours" integer, "p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_find_incoherent_orders"("p_window_hours" integer, "p_limit" integer) IS 'Pedidos recientes cuyas cifras no cuadran consigo mismas. Cross-tenant por diseño (lo corre un cron sin JWT) — de ahí que solo service_role la ejecute.';



CREATE OR REPLACE FUNCTION "public"."rpc_find_orders_pending_acceptance"("p_min_age_minutes" integer DEFAULT 5, "p_window_days" integer DEFAULT 30, "p_limit" integer DEFAULT 100) RETURNS TABLE("order_id" "uuid", "tenant_id" "uuid")
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT o.id, o.tenant_id
      FROM public.orders o
     WHERE o.accepted_at IS NULL
       AND o.conversation_id IS NOT NULL
       AND o.created_at <= NOW() - make_interval(mins => GREATEST(p_min_age_minutes, 0))
       -- La ventana evita reintentar por siempre los que nunca se van a poder estampar
       -- (un pedido viejo cuya conversación ya se borró bajo el régimen anterior).
       AND o.created_at >= NOW() - make_interval(days => GREATEST(p_window_days, 1))
     ORDER BY o.created_at
     LIMIT GREATEST(p_limit, 1);
$$;


ALTER FUNCTION "public"."rpc_find_orders_pending_acceptance"("p_min_age_minutes" integer, "p_window_days" integer, "p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_find_orders_pending_acceptance"("p_min_age_minutes" integer, "p_window_days" integer, "p_limit" integer) IS 'Pedidos cuya aceptación aún no quedó registrada. Lo consume el worker.';



CREATE OR REPLACE FUNCTION "public"."rpc_find_orders_pending_receipt"("p_min_age_minutes" integer DEFAULT 10, "p_window_hours" integer DEFAULT 72, "p_limit" integer DEFAULT 50) RETURNS TABLE("order_id" "uuid", "tenant_id" "uuid", "confirmado_hace_min" integer)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT o.id, o.tenant_id,
           (EXTRACT(EPOCH FROM (NOW() - o.created_at)) / 60)::INT
    FROM public.orders o
    WHERE o.status IN ('confirmed', 'processing', 'shipped', 'delivered')
      -- Margen para que los `order_items` ya estén escritos (ver cabecera).
      AND o.created_at <= NOW() - make_interval(mins => p_min_age_minutes)
      -- Cota inferior: no reprocesar el histórico entero en cada barrido. Un
      -- pedido más viejo que la ventana ya no se documenta automáticamente.
      AND o.created_at >= NOW() - make_interval(hours => p_window_hours)
      AND NOT EXISTS (
            SELECT 1 FROM public.order_receipts r
            WHERE r.order_id = o.id AND r.tenant_id = o.tenant_id
      )
    ORDER BY o.created_at ASC
    LIMIT GREATEST(1, p_limit);
$$;


ALTER FUNCTION "public"."rpc_find_orders_pending_receipt"("p_min_age_minutes" integer, "p_window_hours" integer, "p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_find_orders_pending_receipt"("p_min_age_minutes" integer, "p_window_hours" integer, "p_limit" integer) IS 'Pedidos confirmados que todavía no tienen comprobante. Cross-tenant por diseño (lo corre un cron sin JWT). La emisión es diferida y no un trigger porque en contra entrega el pedido nace confirmado ANTES de que existan sus order_items.';



CREATE OR REPLACE FUNCTION "public"."rpc_find_receipts_pending_ack"("p_csw_hours" integer DEFAULT 24, "p_limit" integer DEFAULT 50) RETURNS TABLE("receipt_id" "uuid", "tenant_id" "uuid", "order_id" "uuid", "conversation_id" "uuid", "numero" "text", "total" numeric, "forma_pago" "text", "dentro_de_csw" boolean)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT r.id, r.tenant_id, r.order_id, o.conversation_id, r.numero,
           (r.snapshot->'totales'->>'total')::NUMERIC,
           r.snapshot->'pedido'->>'forma_pago',
           -- Fuera de la ventana de servicio de Meta solo se puede escribir con
           -- plantilla aprobada, y las plantillas están diferidas (ADR-0040 §4).
           -- Se marca en vez de intentar y fallar con un error opaco de Meta.
           EXISTS (
               SELECT 1 FROM public.messages m
               WHERE m.conversation_id = o.conversation_id
                 AND m.direction = 'inbound'
                 AND m.created_at >= NOW() - make_interval(hours => p_csw_hours)
           )
    FROM public.order_receipts r
    JOIN public.orders o ON o.id = r.order_id AND o.tenant_id = r.tenant_id
    WHERE r.ack_sent_at IS NULL
      AND r.voided_at IS NULL          -- un comprobante anulado no se remite
      AND r.ack_skipped_reason IS NULL -- ya se decidió que no se podía
      AND o.conversation_id IS NOT NULL
    ORDER BY r.issued_at ASC
    LIMIT GREATEST(1, p_limit);
$$;


ALTER FUNCTION "public"."rpc_find_receipts_pending_ack"("p_csw_hours" integer, "p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_find_receipts_pending_ack"("p_csw_hours" integer, "p_limit" integer) IS 'Comprobantes emitidos cuyo acuse todavía no le llegó al comprador. Excluye los anulados: remitir un documento que ya no es cierto sería peor que no remitirlo.';



CREATE OR REPLACE FUNCTION "public"."rpc_find_receipts_pending_email"("p_limit" integer DEFAULT 50) RETURNS TABLE("receipt_id" "uuid", "tenant_id" "uuid", "numero" "text", "snapshot" "jsonb", "email" "text")
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT r.id, r.tenant_id, r.numero, r.snapshot,
           NULLIF(trim(c.email), '')
    FROM public.order_receipts r
    JOIN public.orders   o ON o.id = r.order_id AND o.tenant_id = r.tenant_id
    LEFT JOIN public.contacts c ON c.id = o.contact_id AND c.tenant_id = r.tenant_id
    WHERE r.email_sent_at IS NULL
      AND r.email_skipped_reason IS NULL
      -- Un comprobante anulado no se remite: mandar un documento que ya no es
      -- cierto sería peor que no mandarlo.
      AND r.voided_at IS NULL
      -- A propósito NO se filtra por el estado del acuse de WhatsApp: los dos
      -- canales son independientes, y los que WhatsApp no alcanzó son justamente
      -- los que más necesitan el correo.
    ORDER BY r.issued_at ASC
    LIMIT GREATEST(1, p_limit);
$$;


ALTER FUNCTION "public"."rpc_find_receipts_pending_email"("p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_find_receipts_pending_email"("p_limit" integer) IS 'Comprobantes cuyo detalle completo todavía no salió por correo. Devuelve el email en NULL cuando el comprador no tiene: el caller lo marca como saltado con motivo, en vez de dejarlo pendiente para siempre.';



CREATE OR REPLACE FUNCTION "public"."rpc_find_receipts_to_void"("p_limit" integer DEFAULT 50) RETURNS TABLE("order_id" "uuid", "tenant_id" "uuid", "numero" "text", "estado_pedido" "text")
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT r.order_id, r.tenant_id, r.numero, o.status
    FROM public.order_receipts r
    JOIN public.orders o ON o.id = r.order_id AND o.tenant_id = r.tenant_id
    WHERE r.voided_at IS NULL AND o.status = 'cancelled'
    ORDER BY r.issued_at ASC
    LIMIT GREATEST(1, p_limit);
$$;


ALTER FUNCTION "public"."rpc_find_receipts_to_void"("p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_find_receipts_to_void"("p_limit" integer) IS 'Comprobantes vivos sobre pedidos cancelados: la red que atrapa lo que el trigger no cubrió (filas anteriores a él, o una anulación que falló).';



CREATE OR REPLACE FUNCTION "public"."rpc_find_silent_conversations"("p_silence_minutes" integer DEFAULT 10, "p_window_hours" integer DEFAULT 24, "p_limit" integer DEFAULT 25) RETURNS TABLE("conversation_id" "uuid", "tenant_id" "uuid", "customer_phone" "text", "last_inbound_at" timestamp with time zone, "silence_minutes" integer)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    WITH last_inbound AS (
        -- Último inbound por conversación, ya en estado terminal. Si sigue en
        -- 'pending'/'processing' es trabajo de _reclaim_stale_inbound, no de
        -- este detector: alertar ahí sería competir con el reintento en curso.
        SELECT DISTINCT ON (m.conversation_id)
               m.conversation_id,
               m.tenant_id,
               m.created_at
        FROM public.messages m
        WHERE m.direction = 'inbound'
          AND m.processing_status IN ('processed', 'failed')
          -- Cota superior: fuera de la ventana de servicio de Meta ya no
          -- podríamos responder free-form, así que alertar no sirve de nada.
          AND m.created_at >= NOW() - make_interval(hours => p_window_hours)
          AND m.created_at <= NOW() - make_interval(mins  => p_silence_minutes)
        ORDER BY m.conversation_id, m.created_at DESC
    )
    SELECT li.conversation_id,
           li.tenant_id,
           c.customer_phone,
           li.created_at,
           (EXTRACT(EPOCH FROM (NOW() - li.created_at)) / 60)::INT
    FROM last_inbound li
    JOIN public.conversations c ON c.id = li.conversation_id
    WHERE
        -- human_takeover ya lo vigila el tracker de SLA; en closed/opted_out el
        -- silencio es correcto (el cliente pidió la baja o la conv se archivó).
        c.status NOT IN ('human_takeover', 'closed', 'opted_out')
      AND NOT EXISTS (
            SELECT 1
            FROM public.messages o
            WHERE o.conversation_id = li.conversation_id
              AND o.direction = 'outbound'
              AND o.created_at >= li.created_at
              AND o.content_type NOT LIKE '%audit%'
              AND (
                    o.meta_message_id IS NOT NULL
                 OR o.processing_status IN ('pending', 'processing')
              )
        )
        -- Idempotencia: una alerta por episodio de silencio. Sin esto el
        -- barrido re-alertaría cada 5 min sobre la misma conversación durante
        -- 24h y el ruido enterraría los casos nuevos.
      AND NOT EXISTS (
            SELECT 1
            FROM public.messages a
            WHERE a.conversation_id = li.conversation_id
              AND a.content_type = 'silent_conversation_audit'
              AND a.created_at >= li.created_at
        )
    ORDER BY li.created_at ASC
    LIMIT GREATEST(1, p_limit);
$$;


ALTER FUNCTION "public"."rpc_find_silent_conversations"("p_silence_minutes" integer, "p_window_hours" integer, "p_limit" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_find_silent_conversations"("p_silence_minutes" integer, "p_window_hours" integer, "p_limit" integer) IS 'Conversaciones donde el cliente escribió y no le llegó respuesta. Detecta el síntoma, no la causa: cubre los seis caminos conocidos de mensaje perdido y los que aparezcan después. La consume el worker (_detect_silent_conversations_if_due) para escalar a un humano.';



CREATE OR REPLACE FUNCTION "public"."rpc_issue_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid") RETURNS TABLE("receipt_id" "uuid", "numero" "text", "ya_existia" boolean, "motivo" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_existente public.order_receipts%ROWTYPE;
    v_orden     RECORD;
    v_money     RECORD;
    v_snapshot  JSONB;
    v_seq       BIGINT;
    v_numero    TEXT;
    v_id        UUID;
BEGIN
    -- Idempotente: reemitir devuelve el mismo documento, no uno nuevo. Un
    -- reintento del webhook no puede generarle dos comprobantes al comprador.
    SELECT * INTO v_existente FROM public.order_receipts
     WHERE tenant_id = p_tenant_id AND order_id = p_order_id;
    IF FOUND THEN
        RETURN QUERY SELECT v_existente.id, v_existente.numero, true, NULL::TEXT;
        RETURN;
    END IF;

    SELECT o.id, o.status, o.created_at, o.payment_method, o.contact_id, o.conversation_id,
           o.accepted_at, o.accepted_message_id, o.accepted_meta_message_id
      INTO v_orden
      FROM public.orders o
     WHERE o.id = p_order_id AND o.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'pedido_inexistente'::TEXT;
        RETURN;
    END IF;

    -- LA GUARDA. Si las cifras del pedido no cuadran consigo mismas, NO se emite
    -- documento. Ley 1480 art. 26: ante dos precios el consumidor solo debe el
    -- menor — documentar una contradicción es peor que no documentar (ADR-0040 §2).
    SELECT * INTO v_money FROM public.rpc_order_money(p_order_id, p_tenant_id);
    IF NOT v_money.coherente THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'cifras_incoherentes'::TEXT;
        RETURN;
    END IF;

    -- Consecutivo denso por tenant. El lock serializa solo la emisión de
    -- comprobantes del MISMO tenant, no el INSERT de pedidos.
    PERFORM pg_advisory_xact_lock(hashtext('order_receipts:' || p_tenant_id::text));
    SELECT COALESCE(MAX(numero_seq), 0) + 1 INTO v_seq
      FROM public.order_receipts WHERE tenant_id = p_tenant_id;
    v_numero := 'CP-' || LPAD(v_seq::text, 6, '0');

    v_snapshot := jsonb_build_object(
        -- v2: el documento ahora dice CUÁL manifestación del comprador lo originó.
        'version', 2,
        'emitido_at', NOW(),
        'pedido', jsonb_build_object(
            'id', v_orden.id,
            'estado', v_orden.status,
            'fecha', v_orden.created_at,
            'forma_pago', COALESCE(v_orden.payment_method, 'no_especificada')
        ),
        'vendedor', public.tenant_seller_identity(p_tenant_id),
        'comprador', (
            SELECT jsonb_strip_nulls(jsonb_build_object(
                'nombre', NULLIF(trim(c.name), ''),
                'telefono', NULLIF(trim(c.phone), ''),
                'email', NULLIF(trim(c.email), '')
            )) FROM public.contacts c WHERE c.id = v_orden.contact_id
        ),
        'items', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'titulo', oi.title,
                'cantidad', oi.quantity,
                'precio_unitario', oi.unit_price,
                'total_linea', ROUND(oi.unit_price * oi.quantity, 2)
            ) ORDER BY oi.created_at)
            FROM public.order_items oi
            WHERE oi.order_id = p_order_id AND oi.tenant_id = p_tenant_id
        ), '[]'::jsonb),
        'totales', jsonb_build_object(
            'subtotal', v_money.subtotal,
            -- El APLICADO, no el nominal: es lo que hace que las cuentas del
            -- documento cierren solas en vez de contradecirse.
            'descuento', v_money.descuento_aplicado,
            'envio', v_money.envio,
            'total', v_money.total_calculado,
            'moneda', 'COP'
        )
    );

    -- La aceptación, dentro del propio documento. Ley 1480 art. 50 lit. d) exige que sea
    -- "verificable por la autoridad competente", y un comprobante que no dice a qué
    -- manifestación del comprador corresponde obliga a ir a buscarla aparte — al historial
    -- de WhatsApp, que es justo lo que se estaba borrando. El id de Meta se incluye porque
    -- es atestación de un TERCERO: no depende de esta base.
    --
    -- Se CONCATENA en vez de armarse dentro del objeto: una clave presente con valor null
    -- insinúa que falta algo. Si el pedido no tiene aceptación registrada —creado por un
    -- operador, o anterior a este registro— la clave simplemente no existe.
    IF v_orden.accepted_at IS NOT NULL THEN
        v_snapshot := v_snapshot || jsonb_build_object(
            'aceptacion', jsonb_strip_nulls(jsonb_build_object(
                'fecha', v_orden.accepted_at,
                'mensaje_id', v_orden.accepted_message_id,
                'meta_message_id', v_orden.accepted_meta_message_id
            ))
        );
    END IF;

    INSERT INTO public.order_receipts
        (tenant_id, order_id, numero_seq, numero, snapshot, content_hash)
    VALUES
        (p_tenant_id, p_order_id, v_seq, v_numero, v_snapshot,
         encode(sha256(v_snapshot::text::bytea), 'hex'))
    RETURNING id INTO v_id;

    RETURN QUERY SELECT v_id, v_numero, false, NULL::TEXT;
END;
$$;


ALTER FUNCTION "public"."rpc_issue_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_issue_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid") IS 'Emite el comprobante de un pedido, idempotente por (tenant_id, order_id). NO emite si las cifras del pedido no cuadran (Ley 1480 art. 26): devuelve motivo=cifras_incoherentes. El consecutivo es del comprobante, no del pedido.';



CREATE OR REPLACE FUNCTION "public"."rpc_mark_constancia_entregada"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_fallida" "text" DEFAULT NULL::"text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_n INTEGER;
BEGIN
    UPDATE public.payment_reversal_requests
       SET constancia_entregada_at = CASE WHEN p_fallida IS NULL THEN NOW() END,
           constancia_entrega_fallida = p_fallida
     WHERE id = p_reversal_id
       AND tenant_id = p_tenant_id
       AND constancia_entregada_at IS NULL
       AND constancia_entrega_fallida IS NULL;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;


ALTER FUNCTION "public"."rpc_mark_constancia_entregada"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_fallida" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rpc_mark_doble_pago_avisado"("p_reversal_id" "uuid", "p_tenant_id" "uuid") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_n INTEGER;
BEGIN
    UPDATE public.payment_reversal_requests
       SET doble_pago_avisado_at = NOW()
     WHERE id = p_reversal_id AND tenant_id = p_tenant_id
       AND doble_pago_detectado_at IS NOT NULL
       AND doble_pago_avisado_at IS NULL;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;


ALTER FUNCTION "public"."rpc_mark_doble_pago_avisado"("p_reversal_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rpc_mark_receipt_ack"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_channel" "text", "p_skipped" "text" DEFAULT NULL::"text") RETURNS boolean
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    UPDATE public.order_receipts
       SET ack_sent_at = CASE WHEN p_skipped IS NULL THEN NOW() ELSE NULL END,
           ack_channel = CASE WHEN p_skipped IS NULL THEN p_channel ELSE NULL END,
           ack_skipped_reason = left(p_skipped, 200)
     WHERE id = p_receipt_id AND tenant_id = p_tenant_id
       AND ack_sent_at IS NULL       -- nadie recibe dos acuses
    RETURNING true;
$$;


ALTER FUNCTION "public"."rpc_mark_receipt_ack"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_channel" "text", "p_skipped" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_mark_receipt_ack"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_channel" "text", "p_skipped" "text") IS 'Registra que el acuse salió (o por qué no). El guard ack_sent_at IS NULL es la idempotencia: un reintento del barrido no le manda dos acuses al mismo comprador.';



CREATE OR REPLACE FUNCTION "public"."rpc_mark_receipt_email"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_email" "text" DEFAULT NULL::"text", "p_skipped" "text" DEFAULT NULL::"text") RETURNS boolean
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    UPDATE public.order_receipts
       SET email_sent_at = CASE WHEN p_skipped IS NULL THEN NOW() ELSE NULL END,
           email_to      = CASE WHEN p_skipped IS NULL THEN left(p_email, 320) ELSE NULL END,
           email_skipped_reason = left(p_skipped, 200)
     WHERE id = p_receipt_id AND tenant_id = p_tenant_id
       AND email_sent_at IS NULL     -- nadie recibe dos veces el mismo comprobante
    RETURNING true;
$$;


ALTER FUNCTION "public"."rpc_mark_receipt_email"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_email" "text", "p_skipped" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_mark_receipt_email"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_email" "text", "p_skipped" "text") IS 'Registra que el correo salió (o por qué no). El guard email_sent_at IS NULL es la idempotencia: un reintento del barrido no le manda dos veces el mismo documento.';



CREATE OR REPLACE FUNCTION "public"."rpc_meli_note_refresh_failure"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text" DEFAULT 'mercadolibre'::"text", "p_max_fails" integer DEFAULT 3) RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_count INTEGER;
BEGIN
  -- Incrementa SOLO si seguimos siendo el holder (fencing) → un stale/retomado no cuenta.
  UPDATE public.tenant_integrations
     SET refresh_fail_count = refresh_fail_count + 1
   WHERE tenant_id = p_tenant_id
     AND provider  = p_provider
     AND refresh_lease_token = p_lease_token
  RETURNING refresh_fail_count INTO v_count;

  IF v_count IS NULL THEN
    RETURN FALSE;  -- no somos el holder (lease retomado) → no acumular ni marcar
  END IF;

  -- Marcar 'error' SOLO tras N fallos CONSECUTIVOS (un 400 falso aislado no acumula: el ÉXITO
  -- de un refresh resetea el contador). Fenced por el token también en el marcado.
  IF v_count >= GREATEST(1, p_max_fails) THEN
    UPDATE public.tenant_integrations
       SET status = 'error'
     WHERE tenant_id = p_tenant_id
       AND provider  = p_provider
       AND refresh_lease_token = p_lease_token;
    RETURN TRUE;
  END IF;
  RETURN FALSE;
END;
$$;


ALTER FUNCTION "public"."rpc_meli_note_refresh_failure"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text", "p_max_fails" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_meli_note_refresh_failure"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text", "p_max_fails" integer) IS 'ML reliability — cuenta fallos de refresh CONSECUTIVOS (fenced por el token). Marca status=error solo al alcanzar el umbral → un 400 falso de un perdedor concurrente no marca (el éxito resetea el contador). Surfacing seguro del 401-loop.';



CREATE OR REPLACE FUNCTION "public"."rpc_meli_release_refresh_lease"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text" DEFAULT 'mercadolibre'::"text") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  UPDATE public.tenant_integrations
     SET refresh_lease_until = NULL, refresh_lease_token = NULL
   WHERE tenant_id = p_tenant_id
     AND provider  = p_provider
     AND refresh_lease_token = p_lease_token;  -- solo si SEGUIMOS siendo el holder
END;
$$;


ALTER FUNCTION "public"."rpc_meli_release_refresh_lease"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_meli_release_refresh_lease"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text") IS 'ML reliability — libera el lease SOLO si el fencing token coincide (compare-and-set). Un holder cuyo lease expiró y fue retomado NO clobbea al holder actual.';



CREATE OR REPLACE FUNCTION "public"."rpc_meli_try_refresh_lease"("p_tenant_id" "uuid", "p_provider" "text" DEFAULT 'mercadolibre'::"text", "p_ttl_seconds" integer DEFAULT 90) RETURNS "uuid"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_token UUID := gen_random_uuid();
  v_got   UUID;
BEGIN
  UPDATE public.tenant_integrations
     SET refresh_lease_until = NOW() + make_interval(secs => GREATEST(1, p_ttl_seconds)),
         refresh_lease_token = v_token
   WHERE tenant_id = p_tenant_id
     AND provider  = p_provider
     AND (refresh_lease_until IS NULL OR refresh_lease_until < NOW())
  RETURNING refresh_lease_token INTO v_got;
  RETURN v_got;  -- = v_token si actualizó (ganamos); NULL si el WHERE no matcheó (perdimos)
END;
$$;


ALTER FUNCTION "public"."rpc_meli_try_refresh_lease"("p_tenant_id" "uuid", "p_provider" "text", "p_ttl_seconds" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_meli_try_refresh_lease"("p_tenant_id" "uuid", "p_provider" "text", "p_ttl_seconds" integer) IS 'ML reliability — single-flight del refresh de token: UPDATE condicional atómico. Devuelve un fencing token (uuid) si este caller ganó el lease, NULL si otro lo tiene. TTL evita deadlock si el holder crashea.';



CREATE OR REPLACE FUNCTION "public"."rpc_order_money"("p_order_id" "uuid", "p_tenant_id" "uuid") RETURNS TABLE("subtotal" numeric, "descuento_nominal" numeric, "descuento_aplicado" numeric, "envio" numeric, "total_calculado" numeric, "total_registrado" numeric, "coherente" boolean, "diferencia" numeric)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    WITH o AS (
        SELECT ord.id,
               COALESCE(ord.shipping_cost, 0)   AS envio,
               COALESCE(ord.discount_amount, 0) AS descuento,
               COALESCE(ord.total_amount, 0)    AS total
        FROM public.orders ord
        WHERE ord.id = p_order_id AND ord.tenant_id = p_tenant_id
    ),
    items AS (
        SELECT COALESCE(SUM(oi.unit_price * oi.quantity), 0) AS subtotal
        FROM public.order_items oi
        WHERE oi.order_id = p_order_id AND oi.tenant_id = p_tenant_id
    ),
    calc AS (
        SELECT i.subtotal,
               o.descuento AS descuento_nominal,
               -- Tope real: no se puede descontar más de lo que hay que pagar.
               LEAST(o.descuento, i.subtotal + o.envio) AS descuento_aplicado,
               o.envio,
               o.total AS total_registrado
        FROM o CROSS JOIN items i
    )
    SELECT ROUND(c.subtotal, 2),
           ROUND(c.descuento_nominal, 2),
           ROUND(c.descuento_aplicado, 2),
           ROUND(c.envio, 2),
           ROUND(c.subtotal + c.envio - c.descuento_aplicado, 2),
           ROUND(c.total_registrado, 2),
           -- Tolerancia de UN CENTAVO. Los totales son numeric(10,2) pero se
           -- construyen en float en Python, y el peso colombiano no circula en
           -- centavos: un centavo es ruido de redondeo, no un error de dinero.
           -- Un error real es de miles (el de #175 era de 8.000). Un peso entero
           -- sí se marca: ahí la aritmética ya no cierra.
           ABS((c.subtotal + c.envio - c.descuento_aplicado) - c.total_registrado) <= 0.01,
           ROUND((c.subtotal + c.envio - c.descuento_aplicado) - c.total_registrado, 2)
    FROM calc c;
$$;


ALTER FUNCTION "public"."rpc_order_money"("p_order_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_order_money"("p_order_id" "uuid", "p_tenant_id" "uuid") IS 'Cifras de un pedido calculadas desde la fuente de verdad (order_items) y si cuadran con orders.total_amount. `descuento_aplicado` es el efectivo (tope subtotal+envío); imprimir ése y no el nominal es lo que evita un documento que se contradice. Guarda previa a emitir cualquier comprobante (Ley 1480 art. 26).';



CREATE OR REPLACE FUNCTION "public"."rpc_registrar_movimiento_reversion"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_via" "text", "p_valor" numeric) RETURNS TABLE("doble_pago" boolean, "motivo" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_fila RECORD;
    v_doble BOOLEAN := false;
BEGIN
    SELECT * INTO v_fila
      FROM public.payment_reversal_requests
     WHERE id = p_reversal_id AND tenant_id = p_tenant_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'reversion_inexistente'::TEXT;
        RETURN;
    END IF;
    IF p_via NOT IN ('reembolso_directo', 'reversion_emisor') THEN
        RETURN QUERY SELECT false, 'via_desconocida'::TEXT;
        RETURN;
    END IF;

    IF p_via = 'reembolso_directo' THEN
        UPDATE public.payment_reversal_requests
           SET reembolso_directo_at = COALESCE(reembolso_directo_at, NOW()),
               reembolso_directo_valor = COALESCE(reembolso_directo_valor, p_valor)
         WHERE id = p_reversal_id;
    ELSE
        UPDATE public.payment_reversal_requests
           SET reversion_confirmada_at = COALESCE(reversion_confirmada_at, NOW()),
               reversion_valor = COALESCE(reversion_valor, p_valor)
         WHERE id = p_reversal_id;
    END IF;

    -- Art. 2.2.2.51.10: la norma contempla expresamente que el dinero salga por los
    -- dos caminos. Es real —el operador reembolsa mientras el banco reversa en
    -- paralelo— y hoy sería invisible porque nadie mira las dos cosas al tiempo.
    SELECT (reembolso_directo_at IS NOT NULL AND reversion_confirmada_at IS NOT NULL)
      INTO v_doble
      FROM public.payment_reversal_requests WHERE id = p_reversal_id;

    UPDATE public.payment_reversal_requests
       SET doble_pago_detectado_at = CASE
               WHEN v_doble THEN COALESCE(doble_pago_detectado_at, NOW())
               ELSE doble_pago_detectado_at END,
           estado = CASE WHEN estado IN ('presentada','notificada') THEN 'resuelta'
                         ELSE estado END
     WHERE id = p_reversal_id;

    RETURN QUERY SELECT v_doble, NULL::TEXT;
END;
$$;


ALTER FUNCTION "public"."rpc_registrar_movimiento_reversion"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_via" "text", "p_valor" numeric) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_registrar_movimiento_reversion"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_via" "text", "p_valor" numeric) IS 'Registra por cuál de los dos caminos volvió el dinero y marca la colisión cuando volvió por los dos (Decreto 1074 art. 2.2.2.51.10). No se puede reclamar lo que no se sabe que se pagó.';



CREATE OR REPLACE FUNCTION "public"."rpc_registrar_reversion"("p_claim_id" "uuid", "p_tenant_id" "uuid", "p_causal" "text", "p_razones" "text", "p_valor" numeric, "p_instrumento" "text" DEFAULT NULL::"text", "p_es_parcial" boolean DEFAULT false, "p_items" "jsonb" DEFAULT NULL::"jsonb", "p_bien_a_disposicion" boolean DEFAULT false, "p_canal" "text" DEFAULT 'whatsapp'::"text", "p_conversation_id" "uuid" DEFAULT NULL::"uuid", "p_message_id" "uuid" DEFAULT NULL::"uuid", "p_meta_message_id" "text" DEFAULT NULL::"text") RETURNS TABLE("id" "uuid", "radicado" "text", "ya_existia" boolean, "motivo" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_claim      RECORD;
    v_existente  RECORD;
    v_procede    TEXT;
    v_radicado   TEXT;
    v_constancia JSONB;
    v_id         UUID;
    v_total      NUMERIC;
    v_ya_radicado NUMERIC;
BEGIN
    SELECT c.id, c.order_id, c.ticket_number, c.customer_id
      INTO v_claim
      FROM public.claims c
     WHERE c.id = p_claim_id AND c.tenant_id = p_tenant_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'reclamo_inexistente'::TEXT;
        RETURN;
    END IF;
    IF v_claim.order_id IS NULL THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'reclamo_sin_pedido'::TEXT;
        RETURN;
    END IF;

    SELECT r.id, r.radicado INTO v_existente
      FROM public.payment_reversal_requests r
     WHERE r.claim_id = p_claim_id AND r.tenant_id = p_tenant_id;
    IF FOUND THEN
        RETURN QUERY SELECT v_existente.id, v_existente.radicado, true, NULL::TEXT;
        RETURN;
    END IF;

    v_procede := public.reversion_procede(v_claim.order_id, p_tenant_id);
    IF v_procede <> 'procede' THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, v_procede;
        RETURN;
    END IF;

    SELECT o.total_amount INTO v_total
      FROM public.orders o WHERE o.id = v_claim.order_id AND o.tenant_id = p_tenant_id;

    -- Lo ya radicado sobre ESTE pedido, por cualquier otro reclamo. `FOR UPDATE` no sirve
    -- sobre un agregado: se serializa por el pedido para que dos radicaciones simultáneas
    -- no lean ambas el mismo total previo.
    PERFORM pg_advisory_xact_lock(hashtextextended(v_claim.order_id::text, 0));

    SELECT COALESCE(SUM(r.valor), 0) INTO v_ya_radicado
      FROM public.payment_reversal_requests r
     WHERE r.order_id = v_claim.order_id
       AND r.tenant_id = p_tenant_id
       AND r.estado <> 'desistida';

    IF v_total IS NOT NULL AND (v_ya_radicado + p_valor) > v_total THEN
        RETURN QUERY SELECT NULL::UUID, NULL::TEXT, false, 'valor_excede_el_pedido'::TEXT;
        RETURN;
    END IF;

    v_radicado := 'RV-' || LPAD(COALESCE(v_claim.ticket_number, 0)::text, 6, '0');

    INSERT INTO public.payment_reversal_requests (
        tenant_id, claim_id, order_id, radicado, causal, razones, valor,
        es_parcial, items_json, instrumento, canal, bien_a_disposicion,
        conversation_id, message_id, meta_message_id
    ) VALUES (
        p_tenant_id, p_claim_id, v_claim.order_id, v_radicado, p_causal, p_razones,
        p_valor, p_es_parcial, p_items, p_instrumento, p_canal, p_bien_a_disposicion,
        p_conversation_id, p_message_id, p_meta_message_id
    ) RETURNING payment_reversal_requests.id INTO v_id;

    v_constancia := jsonb_build_object(
        'version', 1,
        'radicado', v_radicado,
        'presentada_at', NOW(),
        'presentada_co', to_char(NOW() AT TIME ZONE 'America/Bogota',
                                 'DD/MM/YYYY HH24:MI') || ' (hora Colombia)',
        'causal', p_causal,
        'razones', p_razones,
        'valor', p_valor,
        'es_parcial', p_es_parcial,
        'moneda', 'COP',
        'canal', p_canal,
        'instrumento', p_instrumento,
        'bien_a_disposicion', p_bien_a_disposicion,
        -- La identificación de la operación la exige el art. 2.2.2.51.7 num. 4 como
        -- contenido de la notificación al emisor: número, fecha y hora. El comprador no
        -- puede armarla si nosotros no se la damos.
        'operacion', (
            SELECT jsonb_strip_nulls(jsonb_build_object(
                'pedido', o.id,
                'fecha', o.created_at,
                'fecha_co', to_char(o.created_at AT TIME ZONE 'America/Bogota',
                                    'DD/MM/YYYY HH24:MI') || ' (hora Colombia)',
                'total', o.total_amount,
                'referencia_pago', (SELECT pm.wompi_link_id FROM public.payments pm
                                     WHERE pm.order_id = o.id ORDER BY pm.created_at DESC LIMIT 1)
            )) FROM public.orders o WHERE o.id = v_claim.order_id
        ),
        'pedido', jsonb_build_object('id', v_claim.order_id, 'reclamo', v_claim.ticket_number),
        'vendedor', public.tenant_seller_identity(p_tenant_id),
        'fundamento', 'Ley 1480 de 2011 art. 51; Decreto 1074 de 2015 art. 2.2.2.51.4'
    );

    UPDATE public.payment_reversal_requests
       SET constancia = v_constancia,
           constancia_hash = encode(sha256(v_constancia::text::bytea), 'hex'),
           constancia_emitida_at = NOW()
     WHERE payment_reversal_requests.id = v_id;

    RETURN QUERY SELECT v_id, v_radicado, false, NULL::TEXT;
END;
$$;


ALTER FUNCTION "public"."rpc_registrar_reversion"("p_claim_id" "uuid", "p_tenant_id" "uuid", "p_causal" "text", "p_razones" "text", "p_valor" numeric, "p_instrumento" "text", "p_es_parcial" boolean, "p_items" "jsonb", "p_bien_a_disposicion" boolean, "p_canal" "text", "p_conversation_id" "uuid", "p_message_id" "uuid", "p_meta_message_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_registrar_reversion"("p_claim_id" "uuid", "p_tenant_id" "uuid", "p_causal" "text", "p_razones" "text", "p_valor" numeric, "p_instrumento" "text", "p_es_parcial" boolean, "p_items" "jsonb", "p_bien_a_disposicion" boolean, "p_canal" "text", "p_conversation_id" "uuid", "p_message_id" "uuid", "p_meta_message_id" "text") IS 'Radica la queja de reversión y emite su constancia en el MISMO acto: el art. 2.2.2.51.4 no condiciona la constancia a nada, y "radicada sin constancia" es justamente el incumplimiento. Idempotente por reclamo.';



CREATE OR REPLACE FUNCTION "public"."rpc_stamp_order_acceptance"("p_order_id" "uuid", "p_tenant_id" "uuid") RETURNS TABLE("estampado" boolean, "motivo" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_orden      RECORD;
    v_msg        RECORD;
    v_ultimo_bot TIMESTAMPTZ;
BEGIN
    SELECT o.id, o.conversation_id, o.created_at, o.accepted_at
      INTO v_orden
      FROM public.orders o
     WHERE o.id = p_order_id AND o.tenant_id = p_tenant_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'pedido_inexistente'::TEXT;
        RETURN;
    END IF;
    IF v_orden.accepted_at IS NOT NULL THEN
        RETURN QUERY SELECT false, 'ya_estampada'::TEXT;
        RETURN;
    END IF;
    IF v_orden.conversation_id IS NULL THEN
        RETURN QUERY SELECT false, 'sin_conversacion'::TEXT;
        RETURN;
    END IF;

    -- La última respuesta del bot anterior al pedido abre el turno vigente. Lo que el
    -- cliente escribió DESPUÉS de esa respuesta y ANTES del pedido es ese turno.
    SELECT MAX(m.created_at) INTO v_ultimo_bot
      FROM public.messages m
     WHERE m.conversation_id = v_orden.conversation_id
       AND m.tenant_id = p_tenant_id
       AND m.direction = 'outbound'
       AND m.created_at < v_orden.created_at;

    SELECT m.id, m.created_at, m.meta_message_id
      INTO v_msg
      FROM public.messages m
     WHERE m.conversation_id = v_orden.conversation_id
       AND m.tenant_id = p_tenant_id
       AND m.direction = 'inbound'
       AND m.created_at <= v_orden.created_at
       -- Del turno vigente. Sin respuesta previa del bot (el cliente abrió y compró de
       -- una), no hay turno anterior que excluir.
       AND (v_ultimo_bot IS NULL OR m.created_at > v_ultimo_bot)
       -- Proximidad: una aceptación y su pedido están a segundos, no a horas.
       AND m.created_at >= v_orden.created_at - INTERVAL '30 minutes'
       -- Un mensaje prueba UN pedido.
       AND NOT EXISTS (
           SELECT 1 FROM public.orders o2
            WHERE o2.tenant_id = p_tenant_id
              AND o2.accepted_message_id = m.id
              AND o2.id <> p_order_id
       )
     -- ASCENDENTE: el PRIMERO del turno, que es donde está la manifestación.
     ORDER BY m.created_at ASC
     LIMIT 1;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'sin_mensaje_del_cliente'::TEXT;
        RETURN;
    END IF;

    UPDATE public.orders
       SET accepted_at = v_msg.created_at,
           accepted_message_id = v_msg.id,
           accepted_meta_message_id = v_msg.meta_message_id,
           accepted_source = 'inferida'
     WHERE id = p_order_id AND tenant_id = p_tenant_id
       AND accepted_at IS NULL;

    RETURN QUERY SELECT true, NULL::TEXT;
END;
$$;


ALTER FUNCTION "public"."rpc_stamp_order_acceptance"("p_order_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_stamp_order_acceptance"("p_order_id" "uuid", "p_tenant_id" "uuid") IS 'Registra el PRIMER mensaje del cliente en el turno sobre el que el bot actuó — no el último, que puede ser algo que llegó mientras se armaba el pedido. Nunca reutiliza un mensaje que ya prueba otro pedido.';



CREATE OR REPLACE FUNCTION "public"."rpc_stock_decrement"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text" DEFAULT 'sale'::"text") RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_current   INTEGER;
  v_new       INTEGER;
  v_mov_id    UUID;
BEGIN
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'rpc_stock_decrement: qty_must_be_positive';
  END IF;
  -- La idempotencia depende del índice parcial WHERE order_id IS NOT NULL: con order_id NULL
  -- el ON CONFLICT no arbitra y cada reintento re-decrementaría. Exigir order_id explícitamente.
  IF p_order_id IS NULL THEN
    RAISE EXCEPTION 'rpc_stock_decrement: order_id_required_for_idempotency';
  END IF;

  -- Lock de la variante (serializa decrementos concurrentes de la misma variante).
  SELECT stock_quantity INTO v_current
    FROM public.product_variations
   WHERE id = p_variation_id AND tenant_id = p_tenant_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_decrement: variation_not_found_or_cross_tenant';
  END IF;

  -- CHECK product_variations_stock_nonneg (20260702150000) prohíbe stock < 0: un v_new
  -- negativo haría fallar el UPDATE y ROLLBACK de toda la RPC (movement no persiste, stock
  -- intacto → revendible sin auditoría). Se clampa a 0; el delta registrado es el cambio REAL
  -- aplicado (v_new - v_current) para que el ledger sea consistente (new_stock = old + delta).
  -- El over-sell (order_items.qty > stock disponible) queda visible al comparar la orden vs el
  -- movimiento; el operador lo gestiona (backorder).
  v_new := GREATEST(0, v_current - p_qty);

  -- GUARD de idempotencia: el movement es la fuente de verdad de "ya se decrementó esto".
  -- Si (order_id, variation_id, reason) ya existe → DO NOTHING → v_mov_id NULL → no-op total.
  INSERT INTO public.stock_movements (tenant_id, variation_id, order_id, delta, new_stock, reason)
  VALUES (p_tenant_id, p_variation_id, p_order_id, v_new - v_current, v_new, p_reason)
  ON CONFLICT (order_id, variation_id, reason) WHERE order_id IS NOT NULL
  DO NOTHING
  RETURNING id INTO v_mov_id;

  IF v_mov_id IS NULL THEN
    -- Decremento ya aplicado antes (retry Wompi tardío / webhook duplicado / reconcile) → NO tocar stock.
    RETURN v_current;
  END IF;

  UPDATE public.product_variations
     SET stock_quantity = v_new, updated_at = NOW()
   WHERE id = p_variation_id AND tenant_id = p_tenant_id;

  RETURN v_new;
END;
$$;


ALTER FUNCTION "public"."rpc_stock_decrement"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_stock_decrement"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") IS 'BLOQUE C item 4 — decremento atómico e idempotente. INSERT movement (ON CONFLICT order_id,variation_id,reason DO NOTHING) como guard: retry/duplicado = no-op. Solo decrementa stock si el movement es nuevo. Retorna new_stock.';



CREATE OR REPLACE FUNCTION "public"."rpc_stock_reservation_consume"("p_reservation_id" "uuid", "p_order_id" "uuid", "p_tenant_id" "uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  r RECORD;
  v_new_stock INTEGER;
BEGIN
  SELECT * INTO r FROM public.stock_reservations
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id AND status = 'active'
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_reservation_consume: reservation_not_active_or_missing_or_cross_tenant';
  END IF;

  UPDATE public.product_variations
     SET stock_quantity = stock_quantity - r.qty,
         updated_at = NOW()
   WHERE id = r.variation_id AND tenant_id = p_tenant_id
   RETURNING stock_quantity INTO v_new_stock;

  -- ON CONFLICT ACUMULATIVO: si este pedido ya consumió otra reserva de la MISMA variación,
  -- se suma el delta a la fila existente del ledger en vez de reventar. Antes, esta colisión
  -- abortaba la transacción y el descuento de stock se perdía → sobreventa silenciosa.
  -- El índice objetivo es PARCIAL, así que el predicado va en la inferencia del ON CONFLICT.
  INSERT INTO public.stock_movements (tenant_id, variation_id, delta, new_stock, reason, order_id)
  VALUES (p_tenant_id, r.variation_id, -r.qty, v_new_stock, 'reservation_consumed', p_order_id)
  ON CONFLICT (order_id, variation_id, reason) WHERE order_id IS NOT NULL
  DO UPDATE SET
    delta     = stock_movements.delta - r.qty,
    new_stock = v_new_stock;

  UPDATE public.stock_reservations
     SET status = 'consumed', consumed_at = NOW(), order_id = p_order_id, updated_at = NOW()
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id;
END;
$$;


ALTER FUNCTION "public"."rpc_stock_reservation_consume"("p_reservation_id" "uuid", "p_order_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_stock_reservation_consume"("p_reservation_id" "uuid", "p_order_id" "uuid", "p_tenant_id" "uuid") IS 'Consume una reserva (scopeada por tenant): descuenta stock y asienta en el ledger. El INSERT es ACUMULATIVO por (order_id, variation_id, reason): un pedido puede consumir VARIAS reservas de la misma variación ("agregame 2 más") y antes la 2ª colisionaba con el índice único, abortaba la transacción y perdía el descuento → sobreventa silenciosa.';



CREATE OR REPLACE FUNCTION "public"."rpc_stock_reservation_extend"("p_reservation_id" "uuid", "p_new_ttl_min" integer, "p_tenant_id" "uuid") RETURNS timestamp with time zone
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_new TIMESTAMPTZ := NOW() + make_interval(mins => p_new_ttl_min);
BEGIN
  UPDATE public.stock_reservations
     SET expires_at = v_new, updated_at = NOW()
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id AND status = 'active';

  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_reservation_extend: reservation_not_active_or_cross_tenant';
  END IF;
  RETURN v_new;
END;
$$;


ALTER FUNCTION "public"."rpc_stock_reservation_extend"("p_reservation_id" "uuid", "p_new_ttl_min" integer, "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_stock_reservation_extend"("p_reservation_id" "uuid", "p_new_ttl_min" integer, "p_tenant_id" "uuid") IS 'A11 IDOR fix: extiende TTL exigiendo tenant del caller. Reemplaza a la firma (UUID,INTEGER) en fase contract.';



CREATE OR REPLACE FUNCTION "public"."rpc_stock_reservation_release"("p_reservation_id" "uuid", "p_tenant_id" "uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  UPDATE public.stock_reservations
     SET status = 'released', released_at = NOW(), updated_at = NOW()
   WHERE id = p_reservation_id AND tenant_id = p_tenant_id AND status = 'active';
END;
$$;


ALTER FUNCTION "public"."rpc_stock_reservation_release"("p_reservation_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_stock_reservation_release"("p_reservation_id" "uuid", "p_tenant_id" "uuid") IS 'A11 IDOR fix: libera reserva exigiendo tenant del caller. Reemplaza a la firma (UUID) en fase contract.';



CREATE OR REPLACE FUNCTION "public"."rpc_stock_reservation_release_by_conversation"("p_conversation_id" "uuid") RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_count INTEGER;
BEGIN
  WITH upd AS (
    UPDATE public.stock_reservations
       SET status = 'released',
           released_at = NOW(),
           updated_at = NOW()
     WHERE conversation_id = p_conversation_id
       AND status = 'active'
     RETURNING 1
  )
  SELECT COUNT(*)::INT INTO v_count FROM upd;
  RETURN v_count;
END;
$$;


ALTER FUNCTION "public"."rpc_stock_reservation_release_by_conversation"("p_conversation_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rpc_stock_reserve"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_cart_id" "uuid", "p_conversation_id" "uuid", "p_ttl_minutes" integer DEFAULT 35) RETURNS TABLE("out_reservation_id" "uuid", "out_expires_at" timestamp with time zone, "out_available_after" integer)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_current_stock INTEGER;
  v_reserved      INTEGER;
  v_available     INTEGER;
  v_res_id        UUID;
  v_expires       TIMESTAMPTZ;
BEGIN
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'rpc_stock_reserve: qty must be > 0';
  END IF;

  -- FOR NO KEY UPDATE — bloqueo más débil que FOR UPDATE, suficiente porque
  -- NO modificamos PK/FK de product_variations (solo leemos stock_quantity).
  -- Ref: https://www.postgresql.org/docs/current/explicit-locking.html §13.3.2
  SELECT pv.stock_quantity INTO v_current_stock
  FROM public.product_variations pv
  WHERE pv.id = p_variation_id AND pv.tenant_id = p_tenant_id
  FOR NO KEY UPDATE;

  IF v_current_stock IS NULL THEN
    RAISE EXCEPTION 'rpc_stock_reserve: variation_not_found';
  END IF;

  SELECT COALESCE(SUM(qty), 0) INTO v_reserved
  FROM public.stock_reservations
  WHERE variation_id = p_variation_id
    AND status = 'active'
    AND expires_at > NOW();

  v_available := v_current_stock - v_reserved;

  IF v_available < p_qty THEN
    RAISE EXCEPTION 'rpc_stock_reserve: insufficient_stock'
      USING ERRCODE = 'P0001',
            DETAIL = format('available=%s requested=%s', v_available, p_qty);
  END IF;

  v_expires := NOW() + make_interval(mins => p_ttl_minutes);

  INSERT INTO public.stock_reservations
    (tenant_id, variation_id, cart_id, conversation_id, qty, expires_at)
  VALUES
    (p_tenant_id, p_variation_id, p_cart_id, p_conversation_id, p_qty, v_expires)
  RETURNING id INTO v_res_id;

  RETURN QUERY SELECT v_res_id, v_expires, (v_available - p_qty);
END;
$$;


ALTER FUNCTION "public"."rpc_stock_reserve"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_cart_id" "uuid", "p_conversation_id" "uuid", "p_ttl_minutes" integer) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_stock_reserve"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_cart_id" "uuid", "p_conversation_id" "uuid", "p_ttl_minutes" integer) IS 'Atómico: SELECT FOR NO KEY UPDATE + check de disponibilidad + INSERT reserva. Levanta SQLSTATE P0001 con DETAIL si stock insuficiente.';



CREATE OR REPLACE FUNCTION "public"."rpc_stock_restore"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text" DEFAULT 'cancellation_restore'::"text") RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
  v_current   INTEGER;
  v_new       INTEGER;
  v_mov_id    UUID;
BEGIN
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'rpc_stock_restore: qty_must_be_positive';
  END IF;
  IF p_order_id IS NULL THEN
    RAISE EXCEPTION 'rpc_stock_restore: order_id_required_for_idempotency';
  END IF;

  SELECT stock_quantity INTO v_current
    FROM public.product_variations
   WHERE id = p_variation_id AND tenant_id = p_tenant_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'rpc_stock_restore: variation_not_found_or_cross_tenant';
  END IF;

  v_new := v_current + p_qty;

  -- Mismo guard idempotente: una reposición para (order,variante,razón) se aplica UNA vez.
  INSERT INTO public.stock_movements (tenant_id, variation_id, order_id, delta, new_stock, reason)
  VALUES (p_tenant_id, p_variation_id, p_order_id, p_qty, v_new, p_reason)
  ON CONFLICT (order_id, variation_id, reason) WHERE order_id IS NOT NULL
  DO NOTHING
  RETURNING id INTO v_mov_id;

  IF v_mov_id IS NULL THEN
    RETURN v_current;  -- reposición ya aplicada → no-op
  END IF;

  UPDATE public.product_variations
     SET stock_quantity = v_new, updated_at = NOW()
   WHERE id = p_variation_id AND tenant_id = p_tenant_id;

  RETURN v_new;
END;
$$;


ALTER FUNCTION "public"."rpc_stock_restore"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_stock_restore"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") IS 'BLOQUE C item 4 — reposición atómica e idempotente de stock (cancelación). Espejo de rpc_stock_decrement. Retorna new_stock.';



CREATE OR REPLACE FUNCTION "public"."rpc_void_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid", "p_reason" "text") RETURNS TABLE("receipt_id" "uuid", "numero" "text", "anulado" boolean)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
DECLARE
    v public.order_receipts%ROWTYPE;
BEGIN
    -- Solo el primer motivo se conserva: si un pedido se cancela y después se
    -- reembolsa, lo que anuló el comprobante fue la cancelación.
    UPDATE public.order_receipts
       SET voided_at = NOW(), void_reason = left(COALESCE(p_reason, 'sin_motivo'), 500)
     WHERE tenant_id = p_tenant_id AND order_id = p_order_id AND voided_at IS NULL
    RETURNING * INTO v;

    IF FOUND THEN
        RETURN QUERY SELECT v.id, v.numero, true;
        RETURN;
    END IF;

    SELECT * INTO v FROM public.order_receipts
     WHERE tenant_id = p_tenant_id AND order_id = p_order_id;
    RETURN QUERY SELECT v.id, v.numero, false;   -- no existía, o ya estaba anulado
END;
$$;


ALTER FUNCTION "public"."rpc_void_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid", "p_reason" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."rpc_void_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid", "p_reason" "text") IS 'Anula el comprobante de un pedido cancelado o reembolsado. Sin esto el comprador se queda con un documento que afirma una compra que ya no existe. Idempotente: conserva el motivo de la PRIMERA anulación.';



CREATE OR REPLACE FUNCTION "public"."seed_tenant_subscription_default"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  INSERT INTO public.tenant_subscriptions (tenant_id, plan_code, status, started_at)
  VALUES (NEW.id, 'basic', 'active', NOW())
  ON CONFLICT (tenant_id) DO NOTHING;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."seed_tenant_subscription_default"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_claim_ticket_number"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  SELECT COALESCE(MAX(ticket_number), 0) + 1
    INTO NEW.ticket_number
    FROM public.claims
   WHERE tenant_id = NEW.tenant_id;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."set_claim_ticket_number"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."stamp_human_takeover_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  IF NEW.status = 'human_takeover' AND OLD.status IS DISTINCT FROM 'human_takeover' THEN
    NEW.human_takeover_at := NOW();       -- entrada real (no re-estampa si ya estaba en takeover)
  ELSIF NEW.status IS DISTINCT FROM 'human_takeover' AND OLD.status = 'human_takeover' THEN
    NEW.human_takeover_at := NULL;        -- salida: la próxima escalación vuelve a estampar
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."stamp_human_takeover_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."sync_conversation_last_interaction"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  UPDATE public.conversations c
  SET last_interaction_at = GREATEST(c.last_interaction_at, NEW.created_at)
  WHERE c.id = NEW.conversation_id;

  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."sync_conversation_last_interaction"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."sync_conversation_last_interaction"() IS 'Updates conversations.last_interaction_at when a new message is inserted.';



CREATE OR REPLACE FUNCTION "public"."sync_tenant_stamp_to_auth"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'auth'
    AS $$
DECLARE
  v_user_id   uuid;
  v_tenant_id text;
  v_role      text;
BEGIN
  -- Usuario afectado: NEW en insert/update, OLD en delete.
  v_user_id := COALESCE(NEW.user_id, OLD.user_id);
  IF v_user_id IS NULL THEN
    RETURN COALESCE(NEW, OLD);
  END IF;

  -- Membresía ACTIVA actual — determinística (prioriza owner, luego la más antigua),
  -- idéntica a custom_access_token_hook para que stamp y token coincidan.
  SELECT tu.tenant_id::text, tu.role
  INTO v_tenant_id, v_role
  FROM public.tenant_users tu
  WHERE tu.user_id = v_user_id
    AND tu.status  = 'active'
  ORDER BY
    CASE tu.role WHEN 'owner' THEN 0 WHEN 'manager' THEN 1 WHEN 'operator' THEN 2 ELSE 3 END,
    tu.created_at ASC,
    tu.tenant_id ASC
  LIMIT 1;

  IF v_tenant_id IS NOT NULL THEN
    UPDATE auth.users
    SET raw_app_meta_data = COALESCE(raw_app_meta_data, '{}'::jsonb)
      || jsonb_build_object('tenant_id', v_tenant_id, 'role', v_role)
    WHERE id = v_user_id;
  ELSE
    -- Sin membresía activa (removido/inactivado): limpia el stamp → el dashboard deja de
    -- resolver el tenant viejo (cierra el hueco de acceso residual).
    UPDATE auth.users
    SET raw_app_meta_data = (COALESCE(raw_app_meta_data, '{}'::jsonb) - 'tenant_id' - 'role')
    WHERE id = v_user_id;
  END IF;

  -- Reasignación de membresía a otro usuario (OLD.user_id != NEW.user_id) es un caso que
  -- no ocurre en el flujo real; si algún día se hace, re-evaluar OLD.user_id aparte.
  RETURN COALESCE(NEW, OLD);
END;
$$;


ALTER FUNCTION "public"."sync_tenant_stamp_to_auth"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."sync_tenant_stamp_to_auth"() IS 'Mantiene auth.users.raw_app_meta_data.tenant_id/role en sync con la membresía activa de tenant_users (fix drift del stamp que lee el dashboard). Espeja custom_access_token_hook.';



CREATE OR REPLACE FUNCTION "public"."tenant_carriers_set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tenant_carriers_set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tenant_provider_capabilities_set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tenant_provider_capabilities_set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tenant_provider_identity_set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tenant_provider_identity_set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tenant_seller_identity"("p_tenant_id" "uuid") RETURNS "jsonb"
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    WITH t AS (
        SELECT
            NULLIF(trim(tn.razon_social), '')            AS razon_social,
            NULLIF(trim(tn.name), '')                    AS nombre_comercial,
            NULLIF(trim(tn.doc_tipo), '')                AS doc_tipo,
            COALESCE(NULLIF(trim(tn.doc_numero), ''),
                     NULLIF(trim(tn.nit), ''))           AS doc_numero,
            NULLIF(trim(tn.doc_dv), '')                  AS doc_dv,
            NULLIF(trim(tn.tipo_persona), '')            AS tipo_persona,
            NULLIF(trim(tn.regimen_iva), '')             AS regimen_iva,
            NULLIF(trim(tn.domicilio_direccion), '')     AS calle,
            NULLIF(trim(tn.domicilio_ciudad), '')        AS ciudad,
            NULLIF(trim(tn.domicilio_departamento), '')  AS depto,
            CASE upper(NULLIF(trim(tn.domicilio_pais), ''))
                WHEN 'CO' THEN 'Colombia'
                ELSE NULLIF(trim(tn.domicilio_pais), '')
            END                                          AS pais,
            NULLIF(trim(tn.email_contacto), '')          AS email,
            NULLIF(trim(tn.email_habeas_data), '')       AS email_habeas_data
        FROM public.tenants tn
        WHERE tn.id = p_tenant_id
    ),
    partes AS (
        -- Tramos en orden, ya sin los ausentes.
        SELECT t.*, ARRAY(
            SELECT x FROM unnest(ARRAY[t.calle, t.ciudad, t.depto, t.pais]) WITH ORDINALITY AS u(x, n)
             WHERE x IS NOT NULL ORDER BY n
        ) AS tramos
        FROM t
    ),
    direccion AS (
        SELECT p.*, (
            SELECT string_agg(x, ', ' ORDER BY n)
            FROM (
                SELECT x, n,
                       -- Compara contra el tramo ANTERIOR, sin tildes ni mayúsculas.
                       lag(translate(lower(x),
                           'áàäâéèëêíìïîóòöôúùüûñ',
                           'aaaaeeeeiiiioooouuuun')) OVER (ORDER BY n) AS previo_norm,
                       translate(lower(x),
                           'áàäâéèëêíìïîóòöôúùüûñ',
                           'aaaaeeeeiiiioooouuuun') AS norm
                FROM unnest(p.tramos) WITH ORDINALITY AS u(x, n)
            ) s
            WHERE previo_norm IS DISTINCT FROM norm
        ) AS direccion_texto
        FROM partes p
    ),
    calc AS (
        SELECT
            COALESCE(d.razon_social, d.nombre_comercial) AS nombre,
            CASE WHEN d.doc_numero IS NULL THEN NULL
                 WHEN d.doc_dv IS NULL THEN COALESCE(d.doc_tipo,'NIT') || ' ' || d.doc_numero
                 ELSE COALESCE(d.doc_tipo,'NIT') || ' ' || d.doc_numero || '-' || d.doc_dv
            END AS documento,
            -- Sin calle ni ciudad no hay dirección de notificación judicial.
            CASE WHEN d.calle IS NULL AND d.ciudad IS NULL THEN NULL
                 ELSE d.direccion_texto END AS direccion,
            d.email, d.email_habeas_data, d.tipo_persona, d.regimen_iva,
            (d.razon_social IS NULL AND d.nombre_comercial IS NOT NULL) AS usa_nombre_comercial
        FROM direccion d
    )
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'nombre',       c.nombre,
        'documento',    c.documento,
        'direccion',    c.direccion,
        'email',        c.email,
        'tipo_persona', c.tipo_persona,
        'regimen_iva',  c.regimen_iva,
        'email_habeas_data', c.email_habeas_data
    )) || jsonb_build_object(
        'usa_nombre_comercial', COALESCE(c.usa_nombre_comercial, false),
        'completa', (c.nombre IS NOT NULL AND c.documento IS NOT NULL
                     AND c.direccion IS NOT NULL AND c.email IS NOT NULL),
        'faltantes', ARRAY(
            SELECT x FROM unnest(ARRAY[
                CASE WHEN c.nombre    IS NULL THEN 'razón social o nombre' END,
                CASE WHEN c.documento IS NULL THEN 'NIT o documento de identidad' END,
                CASE WHEN c.direccion IS NULL THEN 'dirección de notificación judicial' END,
                CASE WHEN c.email     IS NULL THEN 'correo de contacto' END
            ]) x WHERE x IS NOT NULL)
    )
    FROM calc c;
$$;


ALTER FUNCTION "public"."tenant_seller_identity"("p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."tenant_seller_identity"("p_tenant_id" "uuid") IS 'Identidad del vendedor para el comprobante (Ley 1480 art. 50 lit. a), con la cascada de degradación: razón social→nombre comercial, doc_numero→nit legado. Un campo ausente queda NULL para que el renderizador omita la línea entera. `faltantes` alimenta el aviso de la consola.';



CREATE OR REPLACE FUNCTION "public"."tenant_shipping_provider_config_set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tenant_shipping_provider_config_set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tenant_webhook_secrets_set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tenant_webhook_secrets_set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_aveonline_carrier_capabilities_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_aveonline_carrier_capabilities_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_coupons_set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_coupons_set_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_release_coupon_on_cart_terminal"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    -- Solo actuar en transición A → terminal, no en updates noop.
    IF NEW.status IN ('cancelled', 'abandoned')
       AND (OLD.status IS NULL OR OLD.status NOT IN ('cancelled', 'abandoned')) THEN

        UPDATE public.coupon_redemptions
        SET status         = 'revoked',
            revoked_at     = NOW(),
            revoked_reason = 'cart_' || NEW.status
        WHERE cart_id = NEW.id
          AND status  = 'applied';

    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_release_coupon_on_cart_terminal"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."tg_release_coupon_on_cart_terminal"() IS 'ADR-0015 D8: revoca redemptions ''applied'' automáticamente cuando cart
pasa a cancelled/abandoned. Atomic; cubre todos los call-sites cross-service.';



CREATE OR REPLACE FUNCTION "public"."tg_tenant_payment_methods_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_tenant_payment_methods_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tg_whatsapp_templates_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."tg_whatsapp_templates_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."tiene_consentimiento_comercial"("p_contact_id" "uuid", "p_tenant_id" "uuid") RETURNS boolean
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
    SELECT COALESCE((
        SELECT c.consent_comercial_at IS NOT NULL
           AND c.consent_comercial_revoked_at IS NULL
           -- Revocar el consentimiento de Habeas Data revoca TODO: no tendría sentido
           -- seguir mandándole publicidad a quien pidió que no lo contactemos más.
           AND c.consent_revoked_at IS NULL
        FROM public.contacts c
        WHERE c.id = p_contact_id AND c.tenant_id = p_tenant_id
    ), false);
$$;


ALTER FUNCTION "public"."tiene_consentimiento_comercial"("p_contact_id" "uuid", "p_tenant_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."tiene_consentimiento_comercial"("p_contact_id" "uuid", "p_tenant_id" "uuid") IS 'Fail-closed: sin fila, sin consentimiento explícito, o con Habeas Data revocado, devuelve false. Ley 2300 art. 5 par. 2.';



CREATE OR REPLACE FUNCTION "public"."touch_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."touch_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."track9_revoke_public_on_new_function"() RETURNS "event_trigger"
    LANGUAGE "plpgsql"
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
DECLARE
  v_cmd RECORD;
BEGIN
  -- Solo funciones del schema public creadas a partir de esta migración. CREATE OR
  -- REPLACE preserva los ACL existentes y vuelve a disparar el tag: el REVOKE de
  -- PUBLIC es idempotente y es exactamente la propiedad que se quiere mantener.
  FOR v_cmd IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP
    IF v_cmd.schema_name = 'public' AND v_cmd.object_type = 'function' THEN
      EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', v_cmd.object_identity);
    END IF;
  END LOOP;
END;
$$;


ALTER FUNCTION "public"."track9_revoke_public_on_new_function"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."trg_void_receipt_on_cancel"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_temp'
    AS $$
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM 'cancelled' THEN
        -- Best-effort a propósito: que falle la anulación del documento NO puede
        -- impedir que se cancele el pedido. Queda el WARNING y el barrido de
        -- consistencia lo levanta después.
        BEGIN
            PERFORM public.rpc_void_receipt(NEW.id, NEW.tenant_id, 'pedido cancelado');
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING '[COMPROBANTE] no pude anular el de order=% : %', NEW.id, SQLERRM;
        END;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."trg_void_receipt_on_cancel"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."trg_void_receipt_on_cancel"() IS 'Anula el comprobante cuando el pedido se cancela, venga la cancelación de donde venga. Es trigger y no barrido porque acá no hay dependencia de orden de INSERT, y porque cada minuto de demora es un comprador con un documento que ya no es cierto.';



CREATE OR REPLACE FUNCTION "public"."update_claims_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_claims_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_idempotency_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_idempotency_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_kb_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;


ALTER FUNCTION "public"."update_kb_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_marketplace_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_marketplace_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_order_tracking_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_order_tracking_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."upsert_aveonline_idagente"("p_tenant_id" "uuid", "p_idagente" "text") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
BEGIN
    UPDATE public.tenant_integrations
    SET credentials = credentials
        || jsonb_build_object('idagente', p_idagente)
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline';
END;
$$;


ALTER FUNCTION "public"."upsert_aveonline_idagente"("p_tenant_id" "uuid", "p_idagente" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."upsert_aveonline_idagente"("p_tenant_id" "uuid", "p_idagente" "text") IS 'Persiste el idagente Aveonline auto-resuelto (listarAgentes → principal) en tenant_integrations.credentials.idagente. Merge jsonb atómico — preserva jwt_token y demás campos. Best-effort desde AveonlineClient.';



CREATE OR REPLACE FUNCTION "public"."upsert_aveonline_jwt"("p_tenant_id" "uuid", "p_jwt_token" "text", "p_jwt_expires_at" timestamp with time zone) RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public', 'pg_catalog'
    AS $$
BEGIN
    UPDATE public.tenant_integrations
    SET credentials = credentials
        || jsonb_build_object(
            'jwt_token', p_jwt_token,
            'jwt_expires_at', p_jwt_expires_at
        )
    WHERE tenant_id = p_tenant_id
      AND provider = 'aveonline';
END;
$$;


ALTER FUNCTION "public"."upsert_aveonline_jwt"("p_tenant_id" "uuid", "p_jwt_token" "text", "p_jwt_expires_at" timestamp with time zone) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."upsert_aveonline_jwt"("p_tenant_id" "uuid", "p_jwt_token" "text", "p_jwt_expires_at" timestamp with time zone) IS 'Actualiza JWT cacheado del tenant tras refresh exitoso del client. Idempotente — solo escribe los 2 campos JWT, preserva resto de credentials (usuario, password_secret_id, empresa_id, etc.).';



CREATE OR REPLACE FUNCTION "public"."webhook_event_check_or_register"("p_integration" "text", "p_event_uid" "text", "p_tenant_id" "uuid" DEFAULT NULL::"uuid", "p_event_type" "text" DEFAULT NULL::"text", "p_correlation_id" "text" DEFAULT NULL::"text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
DECLARE
    v_inserted_rows INTEGER;
BEGIN
    INSERT INTO public.webhook_events_seen (
        integration, event_uid, tenant_id, event_type, correlation_id
    ) VALUES (
        p_integration, p_event_uid, p_tenant_id, p_event_type, p_correlation_id
    )
    ON CONFLICT (integration, event_uid) DO NOTHING;

    -- Si la fila NO se insertó (ROW_COUNT=0), el evento ya existía → duplicado.
    GET DIAGNOSTICS v_inserted_rows = ROW_COUNT;
    RETURN (v_inserted_rows = 0);
END;
$$;


ALTER FUNCTION "public"."webhook_event_check_or_register"("p_integration" "text", "p_event_uid" "text", "p_tenant_id" "uuid", "p_event_type" "text", "p_correlation_id" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."webhook_event_check_or_register"("p_integration" "text", "p_event_uid" "text", "p_tenant_id" "uuid", "p_event_type" "text", "p_correlation_id" "text") IS 'INSERT ON CONFLICT atómico. Retorna TRUE si evento ya existía (skip), FALSE si insert OK (procesar). Patrón at-least-once safe.';



CREATE OR REPLACE FUNCTION "public"."webhook_event_mark_processed"("p_integration" "text", "p_event_uid" "text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
    UPDATE public.webhook_events_seen
    SET processed_at = NOW()
    WHERE integration = p_integration
      AND event_uid = p_event_uid
      AND processed_at IS NULL;
    RETURN FOUND;
END;
$$;


ALTER FUNCTION "public"."webhook_event_mark_processed"("p_integration" "text", "p_event_uid" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."webhook_event_mark_processed"("p_integration" "text", "p_event_uid" "text") IS 'Marca processed_at=NOW si el evento existe y aún no procesado. Idempotente: re-llamar con mismo evento es no-op.';


SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."agentic_shadow_log" (
    "id" bigint NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "message_id" "uuid",
    "inbound_text" "text",
    "agentic_outbound" "text",
    "tool_calls_executed" integer DEFAULT 0,
    "tool_call_log" "jsonb",
    "truncated" boolean DEFAULT false,
    "truncated_reason" "text",
    "error" "text",
    "elapsed_seconds" numeric(10,3),
    "mode" "text" DEFAULT 'shadow'::"text" NOT NULL,
    "finish_reason" "text",
    "invariant_outcome" "text",
    "invariant_name" "text",
    "final_text" "text",
    "system_prompt_chars" integer,
    "history_turns" integer,
    "total_tokens" integer,
    "prompt_tokens" integer,
    "cached_tokens" integer,
    "thoughts_tokens" integer,
    CONSTRAINT "agentic_shadow_log_mode_check" CHECK (("mode" = ANY (ARRAY['shadow'::"text", 'cutover'::"text"])))
);


ALTER TABLE "public"."agentic_shadow_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."agentic_shadow_log" IS 'ADR-0018 Fase B: log silencioso del agentic orchestrator en shadow mode. Permite comparar respuestas legacy vs agentic sobre tráfico real sin impactar al cliente. Retention 90d.';



COMMENT ON COLUMN "public"."agentic_shadow_log"."agentic_outbound" IS 'Texto que el agentic HABRÍA enviado al cliente. Legacy es quien realmente respondió mientras shadow mode esté activo.';



COMMENT ON COLUMN "public"."agentic_shadow_log"."mode" IS 'rev. 107: distingue audit shadow (legacy responde, agentic loggea) vs cutover (agentic responde al cliente). Permite mezclar ambos modes en una sola tabla y query por mode.';



COMMENT ON COLUMN "public"."agentic_shadow_log"."finish_reason" IS 'rev. 107: último finish_reason de Gemini (STOP/MAX_TOKENS/SAFETY/etc.). Crítico para diagnosticar empty_output sin depender de logs stdout.';



COMMENT ON COLUMN "public"."agentic_shadow_log"."final_text" IS 'rev. 107: texto enviado al cliente post-invariants. Si difiere de agentic_outbound, un invariant reescribió la salida del LLM.';



COMMENT ON COLUMN "public"."agentic_shadow_log"."total_tokens" IS 'F5: tokens Gemini consumidos por el turn agentic (prompt + candidates + tools, via usage_metadata.total_token_count sumado sobre el loop multi-tool). NULL en filas previas a esta migración. Insumo de costo LLM por tenant.';



COMMENT ON COLUMN "public"."agentic_shadow_log"."cached_tokens" IS 'Track 6: usage_metadata.cached_content_token_count acumulado del turn. Si es 0 de forma sostenida con prefijo estable → flash-lite no participa en implicit caching → evaluar explicit caching (CachedContent) con el gate empírico documentado en la matriz Track 6 (mínimo de tokens no publicado en la guía vigente).';



CREATE SEQUENCE IF NOT EXISTS "public"."agentic_shadow_log_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."agentic_shadow_log_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."agentic_shadow_log_id_seq" OWNED BY "public"."agentic_shadow_log"."id";



CREATE TABLE IF NOT EXISTS "public"."ai_agents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "name" "text" DEFAULT 'Vendedor Oficial'::"text" NOT NULL,
    "role_description" "text" DEFAULT 'Eres el principal agente conversacional. Debes asistir al cliente cordialmente.'::"text" NOT NULL,
    "strict_guardrails" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "role" "text" DEFAULT 'sales'::"text" NOT NULL,
    "is_default" boolean DEFAULT true NOT NULL,
    "tools_allowed" "jsonb",
    "fsm_states_allowed" "jsonb",
    "fallback_for_roles" "jsonb" DEFAULT '["sales", "support", "marketing", "claims"]'::"jsonb" NOT NULL,
    CONSTRAINT "ai_agents_fallback_roles_valid" CHECK ("public"."_ai_agents_fallback_roles_valid"("fallback_for_roles"))
);


ALTER TABLE "public"."ai_agents" OWNER TO "postgres";


COMMENT ON TABLE "public"."ai_agents" IS 'Comportamiento del bot per tenant. La IDENTIDAD del negocio (pitch, tono, filosofía) vive en tenants.* — única fuente de verdad. Aquí solo cómo se llama el agente, su rol funcional, prompt maestro, y guardrails.';



COMMENT ON COLUMN "public"."ai_agents"."role" IS 'sales | support | marketing | claims — útil para router pre-LLM futuro.';



COMMENT ON COLUMN "public"."ai_agents"."is_default" IS 'Solo 1 agente por tenant puede ser default. Si tenant tiene >1 agente, router pre-LLM elige según intent del cliente.';



COMMENT ON COLUMN "public"."ai_agents"."fallback_for_roles" IS 'Roles que este agente cubre como fallback cuando no existe agente especialista. Solo aplica a is_default=true. Roles NO marcados → handoff humano. Default: 4 roles (backward-compat pre-rev109).';



CREATE TABLE IF NOT EXISTS "public"."ai_insights" (
    "tenant_id" "uuid" NOT NULL,
    "module" "text" NOT NULL,
    "result" "jsonb" NOT NULL,
    "tokens_used" integer,
    "generated_by" "uuid",
    "generated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "ai_insights_module_check" CHECK (("module" = ANY (ARRAY['inventory'::"text", 'orders'::"text", 'contacts'::"text", 'metrics'::"text"])))
);


ALTER TABLE "public"."ai_insights" OWNER TO "postgres";


COMMENT ON TABLE "public"."ai_insights" IS 'Cache del último análisis IA (Gemini) por tenant y módulo. Decisión F4: persistencia para evitar regenerar/gastar tokens al navegar. Upsert on (tenant_id, module). RLS por tenant (ADR-0025).';



CREATE TABLE IF NOT EXISTS "public"."api_security_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "event_type" "text" NOT NULL,
    "endpoint" "text" NOT NULL,
    "request_method" "text" NOT NULL,
    "status_code" integer NOT NULL,
    "detail" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."api_security_events" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."audit_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "user_id" "uuid",
    "user_email" "text",
    "action" "text" NOT NULL,
    "entity_type" "text" NOT NULL,
    "entity_id" "text",
    "payload" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."audit_log" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."aveonline_carrier_capabilities" (
    "carrier_name" "text" NOT NULL,
    "carrier_id" "text",
    "supports_cod" boolean DEFAULT false NOT NULL,
    "cod_min_recaudo_cop" integer,
    "cod_min_recaudo_heavy_cop" integer,
    "cod_weight_threshold_kg" numeric,
    "cod_commission_pct" numeric,
    "cod_liquidation_days_range" "text",
    "cod_liquidation_weekday" "text",
    "charges_return_fee" boolean DEFAULT false NOT NULL,
    "max_weight_kg" numeric,
    "max_dim_cm" integer,
    "factor_volumetrico" integer,
    "valor_declarado_min_cop" integer DEFAULT 10000 NOT NULL,
    "valor_declarado_max_cop" integer,
    "fuente_doc_url" "text",
    "last_verified_date" "date" DEFAULT CURRENT_DATE NOT NULL,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."aveonline_carrier_capabilities" OWNER TO "postgres";


COMMENT ON TABLE "public"."aveonline_carrier_capabilities" IS 'Canonical carrier capability matrix para provider Aveonline.
     Datos curados desde docs/research/aveonline-dossier.md.
     Refresh trimestral per changelog-watch.md. Platform-level (NOT
     per-tenant): tenants heredan defaults, overrideables vía
     tenant_carriers.cod_override.';



CREATE TABLE IF NOT EXISTS "public"."billing_plans" (
    "plan_code" "text" NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "is_active" boolean DEFAULT true NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "billing_plans_plan_code_check" CHECK (("plan_code" = ANY (ARRAY['basic'::"text", 'pro'::"text", 'enterprise'::"text"])))
);


ALTER TABLE "public"."billing_plans" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."bot_source_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "message_id" "uuid",
    "fsm_state" "text",
    "injected_catalog" boolean DEFAULT false NOT NULL,
    "injected_kb" boolean DEFAULT false NOT NULL,
    "injected_store_info" boolean DEFAULT false NOT NULL,
    "injected_business_identity" boolean DEFAULT false NOT NULL,
    "injected_customer_context" boolean DEFAULT false NOT NULL,
    "injected_cart_recovery" boolean DEFAULT false NOT NULL,
    "injected_after_hours" boolean DEFAULT false NOT NULL,
    "kb_categories_used" "text"[] DEFAULT ARRAY[]::"text"[] NOT NULL,
    "kb_missing_categories" "text"[] DEFAULT ARRAY[]::"text"[] NOT NULL,
    "kb_docs_count" integer DEFAULT 0 NOT NULL,
    "catalog_products_count" integer DEFAULT 0 NOT NULL,
    "prompt_chars" integer DEFAULT 0 NOT NULL,
    "intent_detected" "text",
    "requires_human" boolean DEFAULT false NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."bot_source_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."bot_source_log" IS 'Rev. 71 — Trazabilidad por mensaje: qué fuentes consumió el bot. Append-only, TTL 30d, RLS por tenant. Sin PII.';



CREATE TABLE IF NOT EXISTS "public"."cart_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "cart_id" "uuid" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "event_type" "text" NOT NULL,
    "event_payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "triggered_by" "text",
    "correlation_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."cart_events" OWNER TO "postgres";


COMMENT ON TABLE "public"."cart_events" IS 'Append-only log de mutaciones del cart. Rev. 104 F1-6. Eventos canónicos: item_added, item_proposed, item_removed, qty_changed, shipping_quoted, shipping_invalidated, carrier_selected, city_changed, consent_recorded, summary_rendered, payment_link_created, order_confirmed, coupon_applied (futuro F4).';



COMMENT ON COLUMN "public"."cart_events"."event_type" IS 'Snake_case canónico. Lista enumerada en `services/ai-orchestrator/cart/events.py`.';



COMMENT ON COLUMN "public"."cart_events"."triggered_by" IS 'bot | webhook | human_takeover | cron | system';



COMMENT ON COLUMN "public"."cart_events"."correlation_id" IS 'message_id (uuid) cuando el evento responde a un inbound del cliente.';



CREATE TABLE IF NOT EXISTS "public"."claims" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "customer_id" "uuid",
    "status" "text" DEFAULT 'open'::"text" NOT NULL,
    "reason" "text" NOT NULL,
    "requested_amount" numeric,
    "resolution_notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "ticket_number" integer,
    "refunded_amount" numeric,
    "refunded_at" timestamp with time zone,
    CONSTRAINT "claims_status_check" CHECK (("status" = ANY (ARRAY['open'::"text", 'investigating'::"text", 'resolved'::"text", 'refunded'::"text", 'rejected'::"text", 'cancelled'::"text"])))
);


ALTER TABLE "public"."claims" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."compliance_enforcement_log" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid",
    "decorator" "text" NOT NULL,
    "target_function" "text" NOT NULL,
    "outcome" "text" NOT NULL,
    "blocked_reason" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "request_id" "text",
    "evaluated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "compliance_enforcement_log_outcome_chk" CHECK (("outcome" = ANY (ARRAY['allowed'::"text", 'blocked'::"text"])))
);


ALTER TABLE "public"."compliance_enforcement_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."compliance_enforcement_log" IS 'Audit append-only de hits a decoradores compliance. Rev. 105 Sem 2 F.9 (MA-7). Habeas Data Ley 1581 ART. 17 — retención 7 años. Cada call a función decorada genera 1 row con outcome=allowed|blocked + metadata.';



COMMENT ON COLUMN "public"."compliance_enforcement_log"."decorator" IS 'snake_case canonical. Lista en services/api/lib/compliance/decorators.py.';



COMMENT ON COLUMN "public"."compliance_enforcement_log"."outcome" IS 'allowed = decorator dejó pasar la call. blocked = levantó ComplianceViolationError; función no se ejecutó.';



CREATE SEQUENCE IF NOT EXISTS "public"."compliance_enforcement_log_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."compliance_enforcement_log_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."compliance_enforcement_log_id_seq" OWNED BY "public"."compliance_enforcement_log"."id";



CREATE TABLE IF NOT EXISTS "public"."consent_audit_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "contact_id" "uuid",
    "phone_hash" "text",
    "event" "text" NOT NULL,
    "source" "text" NOT NULL,
    "conversation_id" "uuid",
    "actor_user_id" "uuid",
    "actor_email" "text",
    "evidence" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "occurred_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "consent_audit_log_event_check" CHECK (("event" = ANY (ARRAY['granted'::"text", 'revoked'::"text", 'rectified'::"text", 'export_request'::"text", 'portability'::"text", 'pii_access'::"text", 'deleted'::"text", 'purged'::"text", 'data_rights_request'::"text", 'minor_detected'::"text"]))),
    CONSTRAINT "consent_audit_log_source_check" CHECK (("source" = ANY (ARRAY['whatsapp'::"text", 'tenant_console'::"text", 'api'::"text", 'system'::"text"])))
);


ALTER TABLE "public"."consent_audit_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."consent_audit_log" IS 'Habeas Data Ley 1581 Art. 9: registro inmutable de eventos de consent. Append-only por triggers.';



COMMENT ON CONSTRAINT "consent_audit_log_event_check" ON "public"."consent_audit_log" IS 'Eventos válidos del ciclo de vida del consent + solicitudes Habeas Data. F6 2026-07-02 añade ''data_rights_request'' (DSR detectado por el bot) y ''minor_detected'' (Decreto 1377 Art. 7) para completar el paper-trail Ley 1581 del canal agéntico.';



CREATE TABLE IF NOT EXISTS "public"."contacts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "phone" "text" NOT NULL,
    "name" "text",
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "consent_given" boolean DEFAULT false NOT NULL,
    "consent_date" timestamp with time zone,
    "address" "jsonb",
    "consent_source" "text",
    "consent_notice_version" "text",
    "consent_evidence" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "consent_actor_email" "text",
    "consent_revoked_at" timestamp with time zone,
    "consent_revoked_reason" "text",
    "consent_given_at" timestamp with time zone,
    "consent_channel" "text" DEFAULT 'manual'::"text",
    "consent_text_version" "text",
    "deleted_at" timestamp with time zone,
    "email" "text",
    "document_type" "text",
    "document_number" "text",
    "document_number_hash" "text",
    "document_number_last4" "text",
    "shipping_phone" "text",
    "consent_comercial_at" timestamp with time zone,
    "consent_comercial_revoked_at" timestamp with time zone,
    "consent_comercial_fuente" "text",
    CONSTRAINT "contacts_consent_source_check" CHECK ((("consent_source" IS NULL) OR ("consent_source" = ANY (ARRAY['manual_console'::"text", 'whatsapp'::"text", 'web_form'::"text", 'phone_call'::"text", 'in_person'::"text", 'import'::"text", 'other'::"text", 'marketplace_meli'::"text"])))),
    CONSTRAINT "contacts_document_number_last4_check" CHECK ((("document_number_last4" IS NULL) OR ("length"("document_number_last4") <= 4))),
    CONSTRAINT "contacts_document_type_check" CHECK ((("document_type" IS NULL) OR ("document_type" = ANY (ARRAY['CC'::"text", 'CE'::"text", 'NIT'::"text", 'PP'::"text", 'TI'::"text", 'OTHER'::"text"]))))
);


ALTER TABLE "public"."contacts" OWNER TO "postgres";


COMMENT ON COLUMN "public"."contacts"."address" IS 'Schema canónico contacts.address rev. 110 (A2 finiquito 2026-06-23):
{
  "street": "Calle 10 #5-23",                -- REQUIRED
  "city": "Bogotá",                          -- REQUIRED
  "building_type": "casa|edificio|conjunto|oficina",  -- REQUIRED
  "neighborhood": "Chapinero",               -- requerido residencial
  "state": "Cundinamarca",                   -- requerido shipping/integraciones
  "dane_code": "11001000",                   -- requerido shipping Aveonline
  "country": "CO",                           -- default CO
  "apartment": "401",                        -- requerido edificio/conjunto/oficina
  "tower": "Torre 3",                        -- requerido conjunto
  "floor": "5",                              -- opcional
  "complex_name": "Torres del Parque",       -- opcional
  "reference": "Frente al parque",           -- opcional
  "company_name": "Acme S.A.S."              -- solo si building_type=oficina
}
Source: services/ai-orchestrator/agentic/tools/contact.py::SaveAddressArgs
Migration original: supabase/migrations/20260429000000_contacts_document_and_address.sql';



COMMENT ON COLUMN "public"."contacts"."document_type" IS 'Tipo de documento de identidad. Valores Wompi customer_data.legal_id_type para Colombia: CC, CE, NIT, PP, TI, OTHER.';



COMMENT ON COLUMN "public"."contacts"."document_number" IS 'Número de documento sin formato (sin puntos ni espacios). Validación por tipo en aplicación.';



COMMENT ON COLUMN "public"."contacts"."document_number_hash" IS 'Rev. 96 — sha256 normalizado de document_number. Para lookup sin exponer plaintext.';



COMMENT ON COLUMN "public"."contacts"."document_number_last4" IS 'Rev. 96 — últimos 4 chars de document_number. Visible en Inbox/UI sin exponer doc completo.';



COMMENT ON COLUMN "public"."contacts"."shipping_phone" IS 'Rev. 103: Phone alternativo para envío (transportadora). Si null, usar contacts.phone. NO cambia el handle WhatsApp ni el titular pago.';



COMMENT ON COLUMN "public"."contacts"."consent_comercial_at" IS 'Cuándo el titular aceptó EXPLÍCITAMENTE recibir comunicaciones comerciales. Distinto de consent_given (Habeas Data transaccional): Ley 2300 art. 5 par. 2 prohíbe que el mensaje comercial sea obligatorio al momento de la transacción. NULL = no hay consentimiento comercial y no se le puede escribir con ese fin.';



COMMENT ON COLUMN "public"."contacts"."consent_comercial_fuente" IS 'Cómo se obtuvo: la norma exige que sea explícito, así que hay que poder demostrar de dónde salió (p. ej. "respondio_SI_a_opt_in", "formulario_web").';



COMMENT ON CONSTRAINT "contacts_consent_source_check" ON "public"."contacts" IS 'Fuentes canónicas de autorización. Rev. 103 añade ''marketplace_meli'' para contacts importados desde webhook MeLi. Solo escrito por backend.';



CREATE TABLE IF NOT EXISTS "public"."conversation_cart_items" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "cart_id" "uuid" NOT NULL,
    "product_id" "uuid" NOT NULL,
    "variation_id" "uuid" NOT NULL,
    "quantity" integer NOT NULL,
    "unit_price_cents" bigint NOT NULL,
    "meta" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "conversation_cart_items_quantity_check" CHECK (("quantity" > 0)),
    CONSTRAINT "conversation_cart_items_unit_price_cents_check" CHECK (("unit_price_cents" >= 0))
);

ALTER TABLE ONLY "public"."conversation_cart_items" REPLICA IDENTITY FULL;


ALTER TABLE "public"."conversation_cart_items" OWNER TO "postgres";


COMMENT ON TABLE "public"."conversation_cart_items" IS 'Items del carrito. UNIQUE (cart_id, variation_id) garantiza idempotencia: agregar la misma variante dos veces SUMA quantity, no crea fila duplicada.';



CREATE TABLE IF NOT EXISTS "public"."conversation_carts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "contact_id" "uuid",
    "status" "text" DEFAULT 'open'::"text" NOT NULL,
    "version" integer DEFAULT 1 NOT NULL,
    "shipping_meta" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "subtotal_cents" bigint DEFAULT 0 NOT NULL,
    "shipping_cents" bigint DEFAULT 0 NOT NULL,
    "total_cents" bigint DEFAULT 0 NOT NULL,
    "currency" character(3) DEFAULT 'COP'::"bpchar" NOT NULL,
    "converted_order_id" "uuid",
    "last_activity_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "requires_requote" boolean DEFAULT false NOT NULL,
    "coupon_id" "uuid",
    "coupon_code" "text",
    "discount_cents" bigint DEFAULT 0 NOT NULL,
    "abandoned_reminder_sent_at" timestamp with time zone,
    "payment_method" "text" DEFAULT 'credit'::"text",
    CONSTRAINT "conversation_carts_discount_cents_check" CHECK (("discount_cents" >= 0)),
    CONSTRAINT "conversation_carts_payment_method_check" CHECK (("payment_method" = ANY (ARRAY['credit'::"text", 'cod'::"text"]))),
    CONSTRAINT "conversation_carts_shipping_cents_check" CHECK (("shipping_cents" >= 0)),
    CONSTRAINT "conversation_carts_status_check" CHECK (("status" = ANY (ARRAY['open'::"text", 'checkout'::"text", 'converted'::"text", 'abandoned'::"text", 'cancelled'::"text"]))),
    CONSTRAINT "conversation_carts_subtotal_cents_check" CHECK (("subtotal_cents" >= 0)),
    CONSTRAINT "conversation_carts_total_cents_check" CHECK (("total_cents" >= 0)),
    CONSTRAINT "conversation_carts_version_check" CHECK (("version" > 0))
);

ALTER TABLE ONLY "public"."conversation_carts" REPLICA IDENTITY FULL;


ALTER TABLE "public"."conversation_carts" OWNER TO "postgres";


COMMENT ON TABLE "public"."conversation_carts" IS 'Carrito conversacional persistido. FSM: open → checkout → converted | abandoned | cancelled. UNIQUE parcial garantiza un carrito open por conversación. Locking optimista vía columna version.';



COMMENT ON COLUMN "public"."conversation_carts"."version" IS 'Optimistic lock counter. Toda actualización debe incluir WHERE version = :v_actual y SET version = version + 1. RPC cart_add_item lo bumpea automáticamente.';



COMMENT ON COLUMN "public"."conversation_carts"."shipping_meta" IS 'JSONB con address_line, city, dane_code, carrier, rate_id, shipping_cost_cents. La forma se documenta en .context/06-contracts.md.';



COMMENT ON COLUMN "public"."conversation_carts"."requires_requote" IS 'Rev. 80: flag activado cuando los items cambian post-cotización. El bot debe re-cotizar antes del resumen.';



COMMENT ON COLUMN "public"."conversation_carts"."discount_cents" IS 'Snapshot del descuento aplicado por cupón activo. Para free_shipping puede mutar con re-cotización shipping (ADR-0015 D2).';



COMMENT ON COLUMN "public"."conversation_carts"."abandoned_reminder_sent_at" IS 'Idempotencia cron cart_abandoned_24h. NULL = pendiente; timestamp = enviado. Se setea cuando cron dispara HSM marketing cart_abandoned_24h_v1 a un cliente cuyo carrito tiene >24h sin actividad y status=open/abandoned. Patrón consistente con orders.payment_reminder_sent_at (F1).';



COMMENT ON COLUMN "public"."conversation_carts"."payment_method" IS 'Intent de modalidad pago del cliente: credit=Wompi (default),
     cod=contraentrega. Marcado por cod_intent_resolver pre-LLM cuando
     el cliente lo solicita explícitamente. Se copia a orders.payment_method
     al cierre del cart.';



CREATE TABLE IF NOT EXISTS "public"."conversation_notes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "author_user_id" "uuid" NOT NULL,
    "content" "text" NOT NULL,
    "is_pinned" boolean DEFAULT false NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "deleted_at" timestamp with time zone,
    CONSTRAINT "conversation_notes_content_check" CHECK ((("length"(TRIM(BOTH FROM "content")) >= 1) AND ("length"("content") <= 2000)))
);


ALTER TABLE "public"."conversation_notes" OWNER TO "postgres";


COMMENT ON TABLE "public"."conversation_notes" IS 'Notas privadas del operador per conversación (no enviadas al cliente). Rev. 109 founder 2026-05-29 — P0-1 backlog. Append-only effective via soft delete; pin para nota crítica.';



CREATE TABLE IF NOT EXISTS "public"."conversation_reads" (
    "tenant_id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "last_read_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."conversation_reads" OWNER TO "postgres";


COMMENT ON TABLE "public"."conversation_reads" IS 'Marca de lectura por operador y conversación. Permite badge unread sin estado global por conversación.';



CREATE TABLE IF NOT EXISTS "public"."conversations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "customer_phone" "text" NOT NULL,
    "status" "text" DEFAULT 'bot_active'::"text" NOT NULL,
    "last_interaction_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "archived_at" timestamp with time zone,
    "agentic_state" "text",
    "channel" "text" DEFAULT 'whatsapp'::"text" NOT NULL,
    "human_takeover_at" timestamp with time zone,
    "contact_name" "text",
    "pending_cancel_confirmation" "jsonb",
    "conversation_summary" "jsonb",
    CONSTRAINT "conversations_agentic_state_chk" CHECK ((("agentic_state" IS NULL) OR ("agentic_state" = ANY (ARRAY['GREETING'::"text", 'EXPLORING'::"text", 'CART_BUILDING'::"text", 'PII_COLLECTION'::"text", 'SHIPPING_QUOTE'::"text", 'CARRIER_SELECTION'::"text", 'PAYMENT'::"text", 'POST_PAYMENT'::"text", 'HUMAN_HANDOFF'::"text"])))),
    CONSTRAINT "conversations_status_check" CHECK (("status" = ANY (ARRAY['bot_active'::"text", 'human_takeover'::"text", 'closed'::"text", 'opted_out'::"text"])))
);

ALTER TABLE ONLY "public"."conversations" REPLICA IDENTITY FULL;


ALTER TABLE "public"."conversations" OWNER TO "postgres";


COMMENT ON COLUMN "public"."conversations"."status" IS 'Canonical statuses: bot_active | human_takeover | closed';



COMMENT ON COLUMN "public"."conversations"."archived_at" IS 'Marca de archivado. NULL = activa o cerrada reciente; not null = oculta del Inbox por defecto.';



COMMENT ON COLUMN "public"."conversations"."agentic_state" IS 'Rev.109 — Estado del state machine agentic. Derivado por resolver, no por LLM.';



COMMENT ON COLUMN "public"."conversations"."channel" IS 'Canal de origen. Default ''whatsapp''. Valores canónicos: whatsapp, meli, telegram, web, messenger, instagram, sms. Channel Registry pluggable usa este valor para ramificar adapter.';



COMMENT ON COLUMN "public"."conversations"."human_takeover_at" IS 'F6 SLA: instante de ENTRADA a human_takeover (estampado por trigger stamp_human_takeover_at). NO se renueva con inbounds del cliente (a diferencia de last_interaction_at). El cron SLA del worker lo usa como ancla.';



COMMENT ON COLUMN "public"."conversations"."contact_name" IS 'Denormalizado sólo-display del nombre del contacto (Meta profile.name). Poblado por el connector en el write-path del inbound. NULL = no capturado. F2 2026-07-04.';



COMMENT ON COLUMN "public"."conversations"."pending_cancel_confirmation" IS 'B6: cancelación de orden PAGADA pendiente de confirmación (dos turnos). JSONB {order_id, short_id, total_amount, created_at} o NULL. Lo gestiona services/ai-orchestrator/agentic/cancel_intent_resolver.py + dispatcher.';



COMMENT ON COLUMN "public"."conversations"."conversation_summary" IS 'B-1: resumen rodante de la conversación para el LLM (memoria fuera de la ventana de 25 mensajes). Shape: {text, covers_until_created_at, updated_at, message_count}. Se regenera post-turn con histeresis y se inyecta como primer content de la ventana Gemini.';



COMMENT ON CONSTRAINT "conversations_status_check" ON "public"."conversations" IS 'Estados canónicos de conversación. bot_active=bot procesa normal; human_takeover=operador interviene; closed=cerrada manual; opted_out=cliente revocó consent vía STOP keyword (rev. 105 H.4.1, no bloquea conversación futura — si cliente vuelve a escribir, orchestrator vuelve a bot_active).';



CREATE TABLE IF NOT EXISTS "public"."coupon_redemptions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "coupon_id" "uuid" NOT NULL,
    "cart_id" "uuid",
    "contact_id" "uuid",
    "order_id" "uuid",
    "discount_applied_cents" bigint NOT NULL,
    "status" "text" DEFAULT 'applied'::"text" NOT NULL,
    "applied_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "consumed_at" timestamp with time zone,
    "revoked_at" timestamp with time zone,
    "revoked_reason" "text",
    CONSTRAINT "coupon_redemptions_check" CHECK (((("status" = 'applied'::"text") AND ("consumed_at" IS NULL) AND ("revoked_at" IS NULL)) OR (("status" = 'consumed'::"text") AND ("consumed_at" IS NOT NULL) AND ("revoked_at" IS NULL)) OR (("status" = 'revoked'::"text") AND ("revoked_at" IS NOT NULL) AND ("consumed_at" IS NULL)))),
    CONSTRAINT "coupon_redemptions_discount_applied_cents_check" CHECK (("discount_applied_cents" >= 0)),
    CONSTRAINT "coupon_redemptions_status_check" CHECK (("status" = ANY (ARRAY['applied'::"text", 'consumed'::"text", 'revoked'::"text"])))
);


ALTER TABLE "public"."coupon_redemptions" OWNER TO "postgres";


COMMENT ON TABLE "public"."coupon_redemptions" IS 'Audit append-only de aplicaciones/consumos/revocaciones. ADR-0015. Habeas Data: nunca hard-delete; status FSM transitions only.';



CREATE TABLE IF NOT EXISTS "public"."coupons" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "code" "text" NOT NULL,
    "description" "text",
    "discount_type" "text" NOT NULL,
    "discount_value" integer NOT NULL,
    "min_subtotal_cents" bigint DEFAULT 0 NOT NULL,
    "max_redemptions" integer,
    "redemptions_count" integer DEFAULT 0 NOT NULL,
    "valid_from" timestamp with time zone,
    "valid_until" timestamp with time zone,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "is_customer_visible" boolean DEFAULT true NOT NULL,
    CONSTRAINT "coupons_check" CHECK ((("valid_until" IS NULL) OR ("valid_from" IS NULL) OR ("valid_until" > "valid_from"))),
    CONSTRAINT "coupons_check1" CHECK (((("discount_type" = 'percent'::"text") AND ("discount_value" <= 100)) OR ("discount_type" = ANY (ARRAY['fixed_amount'::"text", 'free_shipping'::"text"])))),
    CONSTRAINT "coupons_check2" CHECK ((("max_redemptions" IS NULL) OR ("redemptions_count" <= "max_redemptions"))),
    CONSTRAINT "coupons_discount_type_check" CHECK (("discount_type" = ANY (ARRAY['percent'::"text", 'fixed_amount'::"text", 'free_shipping'::"text"]))),
    CONSTRAINT "coupons_discount_value_check" CHECK (("discount_value" >= 0)),
    CONSTRAINT "coupons_max_redemptions_check" CHECK ((("max_redemptions" IS NULL) OR ("max_redemptions" > 0))),
    CONSTRAINT "coupons_min_subtotal_cents_check" CHECK (("min_subtotal_cents" >= 0)),
    CONSTRAINT "coupons_redemptions_count_check" CHECK (("redemptions_count" >= 0))
);


ALTER TABLE "public"."coupons" OWNER TO "postgres";


COMMENT ON TABLE "public"."coupons" IS 'Catálogo de cupones per tenant. ADR-0015. discount_type=(percent|fixed_amount|free_shipping). redemptions_count se incrementa SOLO en orden APPROVED (D5).';



COMMENT ON COLUMN "public"."coupons"."is_customer_visible" IS 'Si true, el bot puede mencionar el cupón proactivamente al cliente. Si false, es interno/targeted: NO se anuncia, pero se aplica cuando el cliente provee el código exacto.';



CREATE TABLE IF NOT EXISTS "public"."credential_access_log" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "credential_name" "text" NOT NULL,
    "accessed_by_service" "text" NOT NULL,
    "cache_hit" boolean DEFAULT false NOT NULL,
    "request_id" "text",
    "accessed_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."credential_access_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."credential_access_log" IS 'Audit append-only de accesos a credenciales per-tenant. Rev. 105 Sem 2 F.11 (MA-3). Habeas Data Ley 1581 ART. 17 — retención 7 años. NO contiene plaintext de credenciales; solo metadata de acceso.';



COMMENT ON COLUMN "public"."credential_access_log"."cache_hit" IS 'true si el read salió de cache in-memory facade (TTL 5min). Útil para monitorear hit rate y detectar accesos anormales tras invalidación.';



CREATE SEQUENCE IF NOT EXISTS "public"."credential_access_log_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."credential_access_log_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."credential_access_log_id_seq" OWNED BY "public"."credential_access_log"."id";



CREATE TABLE IF NOT EXISTS "public"."email_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "svix_id" "text" NOT NULL,
    "tenant_id" "uuid",
    "order_id" "uuid",
    "email_id" "text",
    "event_type" "text" NOT NULL,
    "recipient" "text",
    "payload" "jsonb" NOT NULL,
    "occurred_at" timestamp with time zone,
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."email_events" OWNER TO "postgres";


COMMENT ON TABLE "public"."email_events" IS 'Track 6: inbox durable de eventos del webhook Resend (firma svix verificada). Dedup por svix_id (entrega at-least-once). Alimenta analítica de entregabilidad/reputación y la supresión local: los senders consultan el último suppression.added/removed del destinatario antes de enviar (lib/email_suppression.py).';



CREATE TABLE IF NOT EXISTS "public"."expenses" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "category" "text" NOT NULL,
    "description" "text" NOT NULL,
    "amount" numeric(10,2) NOT NULL,
    "expense_date" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "reversed_at" timestamp with time zone,
    "reversed_by" "uuid",
    "reversal_reason" "text",
    CONSTRAINT "expenses_amount_check" CHECK (("amount" > (0)::numeric)),
    CONSTRAINT "expenses_category_check" CHECK (("category" = ANY (ARRAY['payroll'::"text", 'marketing'::"text", 'software'::"text", 'logistics'::"text", 'other'::"text"]))),
    CONSTRAINT "expenses_reversal_trail_ck" CHECK (((("reversed_at" IS NULL) AND ("reversed_by" IS NULL) AND ("reversal_reason" IS NULL)) OR (("reversed_at" IS NOT NULL) AND ("reversed_by" IS NOT NULL) AND ("reversal_reason" IS NOT NULL) AND ("length"("btrim"("reversal_reason")) >= 3))))
);


ALTER TABLE "public"."expenses" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."idempotency_keys" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "idempotency_key" "text" NOT NULL,
    "request_method" "text" NOT NULL,
    "request_path" "text" NOT NULL,
    "request_hash" "text" NOT NULL,
    "response_status" integer,
    "response_body" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expires_at" timestamp with time zone DEFAULT ("now"() + '24:00:00'::interval) NOT NULL
);


ALTER TABLE "public"."idempotency_keys" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."integration_oauth_states" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "nonce_hash" "text" NOT NULL,
    "expires_at" timestamp with time zone NOT NULL,
    "consumed_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "integration_oauth_states_provider_check" CHECK (("provider" = 'mercadolibre'::"text"))
);


ALTER TABLE "public"."integration_oauth_states" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."kb_documents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "title" "text" NOT NULL,
    "content" "text" NOT NULL,
    "category" "text" DEFAULT 'faq'::"text" NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "embedding" "extensions"."vector"(3072),
    "embedding_model_version" "text",
    CONSTRAINT "kb_documents_category_check" CHECK (("category" = ANY (ARRAY['faq'::"text", 'negocio'::"text", 'politicas'::"text", 'productos'::"text", 'envios'::"text", 'pagos'::"text"])))
);


ALTER TABLE "public"."kb_documents" OWNER TO "postgres";


COMMENT ON COLUMN "public"."kb_documents"."category" IS 'Categoría canónica rev. 68. Valores: faq, negocio, politicas, productos, envios, pagos. Cada categoría tiene placeholder específico en UI; ver knowledge-base/page.tsx CATEGORY_GUIDES.';



COMMENT ON COLUMN "public"."kb_documents"."embedding_model_version" IS 'Identificador del modelo embedding usado para indexar este doc (formato "model:dim"). NULL = modelo legacy/desconocido, debe re-indexarse. Resuelto por llm_embed.get_embedding_model_version().';



CREATE TABLE IF NOT EXISTS "public"."marketplace_listings" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "variation_id" "uuid" NOT NULL,
    "external_id" "text" NOT NULL,
    "provider" "text" DEFAULT 'mercadolibre'::"text" NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "external_price" numeric,
    "external_url" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "meli_variation_id" bigint,
    "meli_title" "text",
    "meli_thumbnail" "text",
    "meli_condition" "text",
    "meli_category_id" "text",
    "meli_attributes" "jsonb",
    "synced_at" timestamp with time zone
);


ALTER TABLE "public"."marketplace_listings" OWNER TO "postgres";


COMMENT ON COLUMN "public"."marketplace_listings"."meli_variation_id" IS 'ID de variación MeLi (variations[].id). NULL para items sin variaciones propias en MeLi.';



CREATE TABLE IF NOT EXISTS "public"."meli_webhook_dedup" (
    "dedup_key" "text" NOT NULL,
    "hit_count" integer DEFAULT 1 NOT NULL,
    "first_seen_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expires_at" timestamp with time zone NOT NULL
);


ALTER TABLE "public"."meli_webhook_dedup" OWNER TO "postgres";


COMMENT ON TABLE "public"."meli_webhook_dedup" IS 'Idempotencia distribuida para webhooks MeLi (rev. 69). Reemplaza el dict in-memory de meli_webhook.py.';



CREATE TABLE IF NOT EXISTS "public"."messages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "direction" "text" NOT NULL,
    "content_type" "text" DEFAULT 'text'::"text" NOT NULL,
    "content" "text",
    "media_url" "text",
    "meta_message_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "processed" boolean DEFAULT false NOT NULL,
    "processed_at" timestamp with time zone,
    "processing_status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "skip_reason" "text",
    "last_error" "text",
    "processing_attempts" integer DEFAULT 0 NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "media_id" "text",
    "media_mime" "text",
    "delivery_status" "text",
    "delivered_at" timestamp with time zone,
    "read_at" timestamp with time zone,
    "failed_at" timestamp with time zone,
    "delivery_error" "jsonb",
    "pricing_category" "text",
    "pricing_billable" boolean,
    CONSTRAINT "messages_delivery_status_check" CHECK ((("delivery_status" IS NULL) OR ("delivery_status" = ANY (ARRAY['sent'::"text", 'delivered'::"text", 'read'::"text", 'failed'::"text"])))),
    CONSTRAINT "messages_processing_status_check" CHECK (("processing_status" = ANY (ARRAY['pending'::"text", 'processing'::"text", 'processed'::"text", 'skipped'::"text", 'failed'::"text", 'ack_pending'::"text"])))
);

ALTER TABLE ONLY "public"."messages" REPLICA IDENTITY FULL;


ALTER TABLE "public"."messages" OWNER TO "postgres";


COMMENT ON COLUMN "public"."messages"."processed" IS 'Flag que el AI Orchestrator setea a TRUE tras enviar la respuesta de WhatsApp';



COMMENT ON COLUMN "public"."messages"."processed_at" IS 'Timestamp UTC en que el Orchestrator procesó este mensaje';



COMMENT ON COLUMN "public"."messages"."processing_status" IS 'Explicit orchestration outcome: pending | processing | processed | skipped | failed';



COMMENT ON COLUMN "public"."messages"."skip_reason" IS 'Reason when processing_status=skipped (e.g. human_takeover_active, closed_conversation, non_text_requires_human)';



COMMENT ON COLUMN "public"."messages"."last_error" IS 'Last orchestration error when processing_status=failed or pending retry';



COMMENT ON COLUMN "public"."messages"."processing_attempts" IS 'Number of orchestration attempts for this inbound message';



COMMENT ON COLUMN "public"."messages"."payload" IS 'Payload contextual del mensaje (context.id/from, interactive/button data, timestamp).';



COMMENT ON COLUMN "public"."messages"."media_id" IS 'Meta media_id permanente. Usado por orquestador multimodal para descarga fresca.';



COMMENT ON COLUMN "public"."messages"."media_mime" IS 'MIME type del media (audio/ogg, image/jpeg, etc).';



COMMENT ON COLUMN "public"."messages"."delivery_status" IS 'Estado de entrega REAL reportado por Meta (value.statuses[].status): sent | delivered | read | failed. NULL = inbound o outbound histórico sin receipt. Distinto de processing_status (lado orquestador).';



COMMENT ON COLUMN "public"."messages"."delivery_error" IS 'errors[] de Meta cuando delivery_status=failed: [{code,title,message}]. Diagnóstico de rechazos asíncronos (número bloqueado, ventana 24h cerrada, plantilla pausada).';



COMMENT ON COLUMN "public"."messages"."pricing_category" IS 'pricing.category de Meta (utility|marketing|authentication|service) — insight de billing por conversación.';



COMMENT ON CONSTRAINT "messages_processing_status_check" ON "public"."messages" IS 'Estados de procesamiento. ack_pending = enviado a Meta pero DB UPDATE falló (requiere reconciliación).';



CREATE TABLE IF NOT EXISTS "public"."mfa_recovery_codes" (
    "id" bigint NOT NULL,
    "user_id" "uuid" NOT NULL,
    "code_hash" "text" NOT NULL,
    "used_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."mfa_recovery_codes" OWNER TO "postgres";


COMMENT ON TABLE "public"."mfa_recovery_codes" IS 'J.2.4.3 — códigos de recuperación MFA TOTP (8 por usuario por enrollment). Bcrypt hashed. Single-use: tras consume, used_at marca momento. NUNCA almacenar plaintext.';



CREATE SEQUENCE IF NOT EXISTS "public"."mfa_recovery_codes_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."mfa_recovery_codes_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."mfa_recovery_codes_id_seq" OWNED BY "public"."mfa_recovery_codes"."id";



CREATE TABLE IF NOT EXISTS "public"."notification_settings" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "channel" "text" NOT NULL,
    "enabled" boolean DEFAULT false NOT NULL,
    "config" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."notification_settings" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."order_cancellations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "conversation_id" "uuid",
    "cancelled_by_actor" "public"."order_cancellation_actor" NOT NULL,
    "cancelled_by_user_id" "uuid",
    "status" "public"."order_cancellation_status" DEFAULT 'pending'::"public"."order_cancellation_status" NOT NULL,
    "reason_code" "text" NOT NULL,
    "reason_text" "text",
    "items_cancelled_json" "jsonb",
    "amount_refunded_cents" bigint DEFAULT 0 NOT NULL,
    "refund_method" "public"."refund_method_enum",
    "refund_txn_id" "text",
    "refund_status" "text" DEFAULT 'not_applicable'::"text" NOT NULL,
    "refund_completed_at" timestamp with time zone,
    "shipping_cancelled" boolean DEFAULT false NOT NULL,
    "shipping_cancel_method" "text",
    "shipping_cancel_tracking" "text",
    "stock_restored" boolean DEFAULT false NOT NULL,
    "stock_restore_method" "text",
    "customer_notified_email" boolean DEFAULT false NOT NULL,
    "customer_notified_whatsapp" boolean DEFAULT false NOT NULL,
    "operator_notified_telegram" boolean DEFAULT false NOT NULL,
    "escalated_to_operator" boolean DEFAULT false NOT NULL,
    "escalation_reason" "text",
    "ip_address" "inet",
    "user_agent" "text",
    "legal_basis" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "completed_at" timestamp with time zone,
    CONSTRAINT "order_cancellations_check" CHECK (((("status" = 'completed'::"public"."order_cancellation_status") AND ("completed_at" IS NOT NULL)) OR ("status" <> 'completed'::"public"."order_cancellation_status")))
);

ALTER TABLE ONLY "public"."order_cancellations" REPLICA IDENTITY FULL;


ALTER TABLE "public"."order_cancellations" OWNER TO "postgres";


COMMENT ON TABLE "public"."order_cancellations" IS 'Audit append-only de cancelaciones de orden PRE-entrega. Cumple Ley 1480 Art. 47 + SIC compliance. Inmutable post-completed (los UPDATEs solo extienden campos no-críticos).';



CREATE TABLE IF NOT EXISTS "public"."order_items" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "order_id" "uuid" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "product_id" "uuid",
    "variation_id" "uuid",
    "title" "text" NOT NULL,
    "unit_price" numeric(10,2) NOT NULL,
    "quantity" integer DEFAULT 1 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "unit_cost" numeric(10,2) DEFAULT 0.00,
    CONSTRAINT "order_items_quantity_check" CHECK (("quantity" > 0))
);


ALTER TABLE "public"."order_items" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."order_receipts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "numero_seq" bigint NOT NULL,
    "numero" "text" NOT NULL,
    "snapshot" "jsonb" NOT NULL,
    "content_hash" "text" NOT NULL,
    "issued_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "voided_at" timestamp with time zone,
    "void_reason" "text",
    "ack_sent_at" timestamp with time zone,
    "ack_channel" "text",
    "ack_skipped_reason" "text",
    "email_sent_at" timestamp with time zone,
    "email_to" "text",
    "email_skipped_reason" "text"
);


ALTER TABLE "public"."order_receipts" OWNER TO "postgres";


COMMENT ON TABLE "public"."order_receipts" IS 'Comprobante de compra NO FISCAL (ADR-0040). `snapshot` congela el estado del mundo al emitir — vendedor incluido — porque un comprobante no puede cambiar porque el tenant editó su perfil después. NO es factura electrónica DIAN.';



COMMENT ON COLUMN "public"."order_receipts"."numero" IS 'Consecutivo POR TENANT del comprobante, no del pedido: el bot cancela y recrea la orden pending_payment al cambiar el carrito, así que numerar allí dejaría huecos en pedidos que nunca existieron comercialmente.';



COMMENT ON COLUMN "public"."order_receipts"."ack_sent_at" IS 'Cuándo se le remitió el acuse al comprador (Ley 1480 art. 50 lit. d). NULL = todavía no salió. Es la idempotencia del envío: nadie recibe dos acuses.';



COMMENT ON COLUMN "public"."order_receipts"."ack_skipped_reason" IS 'Por qué no se pudo remitir. Sin esto, un acuse que nunca sale es indistinguible de uno pendiente — y el plazo legal corre igual.';



COMMENT ON COLUMN "public"."order_receipts"."email_sent_at" IS 'Cuándo salió el correo con el detalle completo. Independiente de ack_sent_at: son dos canales y un comprobante puede haber llegado por uno y no por el otro.';



COMMENT ON COLUMN "public"."order_receipts"."email_skipped_reason" IS 'Por qué no se pudo enviar (típicamente: el comprador no tiene correo). Sin esto, un correo que nunca sale es indistinguible de uno pendiente.';



CREATE TABLE IF NOT EXISTS "public"."order_tracking" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "external_id" "text",
    "status" "text",
    "tracking_number" "text",
    "tracking_url" "text",
    "carrier" "text",
    "estimated_delivery" "date",
    "raw" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."order_tracking" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."orders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "contact_id" "uuid",
    "conversation_id" "uuid",
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "total_amount" numeric(10,2) DEFAULT 0 NOT NULL,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "shipping_cost" numeric(10,2) DEFAULT 0 NOT NULL,
    "payment_reminder_sent_at" timestamp with time zone,
    "payment_method" "text" DEFAULT 'credit'::"text",
    "cancelled_at" timestamp with time zone,
    "cancelled_by_actor" "public"."order_cancellation_actor",
    "cancellation_id" "uuid",
    "discount_amount" numeric(10,2) DEFAULT 0 NOT NULL,
    "source" "text",
    "external_order_id" "text",
    "accepted_at" timestamp with time zone,
    "accepted_message_id" "uuid",
    "accepted_meta_message_id" "text",
    "accepted_source" "text",
    "paid_no_guide_alerted_at" timestamp with time zone,
    CONSTRAINT "orders_payment_method_check" CHECK (("payment_method" = ANY (ARRAY['credit'::"text", 'cod'::"text"])))
);

ALTER TABLE ONLY "public"."orders" REPLICA IDENTITY FULL;


ALTER TABLE "public"."orders" OWNER TO "postgres";


COMMENT ON COLUMN "public"."orders"."status" IS 'Estados válidos: pending | pending_payment | confirmed | processing | shipped | delivered | cancelled';



COMMENT ON COLUMN "public"."orders"."payment_reminder_sent_at" IS 'Rev. 103 — timestamp del recordatorio de pago enviado por WhatsApp (solo si CSW abierta). Idempotencia: NULL = no enviado, set = enviado.';



COMMENT ON COLUMN "public"."orders"."payment_method" IS 'Modalidad de pago: credit=Wompi anticipado (default), cod=contraentrega
     (courier recauda al entregar). Rev. 108 Fase B. Determina ramificación
     del flujo en payment_link_tool + _generate_shipping_guide.';



COMMENT ON COLUMN "public"."orders"."discount_amount" IS 'F1: descuento del cupón snapshoteado en la orden (moneda, numeric(10,2), consistente con total_amount/shipping_cost). total_amount = max(0, subtotal_productos - discount_amount) + shipping_cost. El cobro Wompi usa total_amount.';



COMMENT ON COLUMN "public"."orders"."source" IS 'Canal de origen del pedido: NULL = nativo (bot/manual), ''mercadolibre'' = MeLi. Base para futuros marketplaces.';



COMMENT ON COLUMN "public"."orders"."external_order_id" IS 'ID del pedido en el sistema externo (ej. order_id de Mercado Libre). Identidad estable del canal.';



COMMENT ON COLUMN "public"."orders"."accepted_at" IS 'Cuándo el consumidor manifestó su voluntad de contratar (Ley 1480 art. 50 lit. d). Antes solo existía como texto libre dentro de la conversación — y la conversación se borraba a los 180 días.';



COMMENT ON COLUMN "public"."orders"."accepted_meta_message_id" IS 'El id que le asignó META a ese mensaje. Es atestación de un TERCERO: la fecha y el contenido no dependen solo de nuestra base, que es lo que la norma pide al exigir que la aceptación sea "verificable por la autoridad competente".';



COMMENT ON COLUMN "public"."orders"."accepted_source" IS '"inferida" = la dedujo el barrido de respaldo por posición en el turno. Se registra para que nadie lea el campo como si fuera una manifestación capturada en vivo.';



COMMENT ON COLUMN "public"."orders"."paid_no_guide_alerted_at" IS 'B4: timestamp de la alerta Telegram "pagado sin guía" enviada por el reconciliador del worker (services/ai-orchestrator/worker.py). NULL = no alertada.';



CREATE TABLE IF NOT EXISTS "public"."outbound_idempotency_cache" (
    "id" bigint NOT NULL,
    "provider" "text" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "request_hash" "text" NOT NULL,
    "response_status" integer NOT NULL,
    "response_body" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "response_headers" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expires_at" timestamp with time zone NOT NULL
);


ALTER TABLE "public"."outbound_idempotency_cache" OWNER TO "postgres";


COMMENT ON TABLE "public"."outbound_idempotency_cache" IS 'Cache de responses outbound POST per (provider, tenant, request_hash). Rev. 105 Sem 2 F.2 (MA-1). Evita doble efecto en retries cuando provider completó pero cliente HTTP timeout. TTL típico 24h; cleanup pg_cron diario.';



CREATE SEQUENCE IF NOT EXISTS "public"."outbound_idempotency_cache_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."outbound_idempotency_cache_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."outbound_idempotency_cache_id_seq" OWNED BY "public"."outbound_idempotency_cache"."id";



CREATE TABLE IF NOT EXISTS "public"."payment_reversal_requests" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "claim_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "radicado" "text" NOT NULL,
    "causal" "text" NOT NULL,
    "razones" "text" NOT NULL,
    "valor" numeric(14,2) NOT NULL,
    "es_parcial" boolean DEFAULT false NOT NULL,
    "items_json" "jsonb",
    "instrumento" "text",
    "presentada_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "canal" "text" DEFAULT 'whatsapp'::"text" NOT NULL,
    "conversation_id" "uuid",
    "message_id" "uuid",
    "meta_message_id" "text",
    "constancia" "jsonb",
    "constancia_hash" "text",
    "constancia_emitida_at" timestamp with time zone,
    "constancia_entregada_at" timestamp with time zone,
    "constancia_entrega_fallida" "text",
    "bien_a_disposicion" boolean DEFAULT false NOT NULL,
    "reembolso_directo_at" timestamp with time zone,
    "reembolso_directo_valor" numeric(14,2),
    "reversion_confirmada_at" timestamp with time zone,
    "reversion_valor" numeric(14,2),
    "doble_pago_detectado_at" timestamp with time zone,
    "doble_pago_avisado_at" timestamp with time zone,
    "estado" "text" DEFAULT 'presentada'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "payment_reversal_requests_causal_check" CHECK (("causal" = ANY (ARRAY['fraude'::"text", 'operacion_no_solicitada'::"text", 'producto_no_recibido'::"text", 'producto_no_corresponde'::"text", 'producto_defectuoso'::"text"]))),
    CONSTRAINT "payment_reversal_requests_estado_check" CHECK (("estado" = ANY (ARRAY['presentada'::"text", 'notificada'::"text", 'resuelta'::"text", 'controvertida'::"text", 'desistida'::"text"]))),
    CONSTRAINT "payment_reversal_requests_razones_check" CHECK (("length"("btrim"("razones")) >= 3)),
    CONSTRAINT "payment_reversal_requests_valor_check" CHECK (("valor" > (0)::numeric))
);


ALTER TABLE "public"."payment_reversal_requests" OWNER TO "postgres";


COMMENT ON TABLE "public"."payment_reversal_requests" IS 'Solicitudes de reversión del pago (Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51). Figura DISTINTA del reembolso comercial: acá el dinero lo devuelve el emisor del instrumento de pago, no el comerciante. Nuestra obligación es emitir la constancia.';



COMMENT ON COLUMN "public"."payment_reversal_requests"."instrumento" IS 'Descriptor del medio de pago (p. ej. "Visa terminada en 4242"), NUNCA el número completo: guardar un PAN crearía una obligación PCI que este sistema no asume.';



COMMENT ON COLUMN "public"."payment_reversal_requests"."doble_pago_detectado_at" IS 'Cuándo se detectó que el dinero salió por los DOS caminos a la vez (art. 2.2.2.51.10). No se puede reclamar lo que no se sabe que se pagó.';



CREATE TABLE IF NOT EXISTS "public"."payments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "provider" "text" DEFAULT 'wompi'::"text" NOT NULL,
    "wompi_link_id" "text",
    "wompi_txn_id" "text",
    "checkout_url" "text",
    "amount_in_cents" bigint NOT NULL,
    "currency" "text" DEFAULT 'COP'::"text" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "wompi_status" "text",
    "raw_webhook" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."payments" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."payments_safe" WITH ("security_barrier"='true') AS
 SELECT "id",
    "tenant_id",
    "order_id",
    "provider",
    "checkout_url",
    "amount_in_cents",
    "currency",
    "status",
    "wompi_status",
    "created_at",
    "updated_at"
   FROM "public"."payments"
  WHERE ("tenant_id" = "public"."app_current_tenant"());


ALTER VIEW "public"."payments_safe" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."pii_access_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "contact_id" "uuid",
    "accessed_by" "text" NOT NULL,
    "actor_user_id" "uuid",
    "purpose" "text" NOT NULL,
    "fields_accessed" "text"[] NOT NULL,
    "ip_address" "text",
    "user_agent" "text",
    "accessed_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."pii_access_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."pii_access_log" IS 'Habeas Data Ley 1581 Art. 9: log de accesos explícitos a PII de contacts. Append-only.';



COMMENT ON COLUMN "public"."pii_access_log"."contact_id" IS 'Contacto leído. NULL cuando el evento es un resumen de acceso a un listado (purpose=contact_list_view).';



CREATE TABLE IF NOT EXISTS "public"."plan_capabilities" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "plan_code" "text" NOT NULL,
    "capability_key" "text" NOT NULL,
    "enabled" boolean DEFAULT true NOT NULL,
    "limit_value" bigint,
    "period" "text" DEFAULT 'none'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "plan_capabilities_period_check" CHECK (("period" = ANY (ARRAY['none'::"text", 'minute'::"text", 'day'::"text", 'month'::"text"])))
);


ALTER TABLE "public"."plan_capabilities" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."platform_categories" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "parent_id" "uuid",
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "gid" "text",
    "full_path" "text",
    "google_category_id" "text",
    "taxonomy_version" "text"
);


ALTER TABLE "public"."platform_categories" OWNER TO "postgres";


COMMENT ON COLUMN "public"."platform_categories"."gid" IS 'ADR-0029 D1: identidad estable de la Shopify Standard Product Taxonomy. Es la clave de negocio, no el UUID aleatorio.';



CREATE TABLE IF NOT EXISTS "public"."product_attribute_definitions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "product_category_id" "uuid",
    "code" "text" NOT NULL,
    "label" "text" NOT NULL,
    "type" "text" NOT NULL,
    "unit" "text",
    "is_required" boolean DEFAULT false NOT NULL,
    "is_variant_axis" boolean DEFAULT false NOT NULL,
    "allowed_values" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "localizable" boolean DEFAULT false NOT NULL,
    "sort_order" integer DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "product_attribute_definitions_type_check" CHECK (("type" = ANY (ARRAY['select'::"text", 'metric'::"text", 'number'::"text", 'boolean'::"text", 'text'::"text"])))
);


ALTER TABLE "public"."product_attribute_definitions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."product_categories" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "display_label" "text",
    "sort_order" integer DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "platform_category_id" "uuid",
    "parent_id" "uuid"
);


ALTER TABLE "public"."product_categories" OWNER TO "postgres";


COMMENT ON TABLE "public"."product_categories" IS 'ADR-0027 Pieza 1: categorías de catálogo POR TENANT (data-driven). Reemplaza la heurística "primera palabra del título". Consumida por el índice de categorías, list_catalog, search_products y el invariant de completitud (CASE D).';



COMMENT ON COLUMN "public"."product_categories"."parent_id" IS 'F2: categoría PADRE (jerarquía 2 niveles Categoría›Subcategoría). NULL = raíz (categoría de vertical). Los productos cuelgan de subcategorías (hojas). Self-FK ON DELETE SET NULL.';



CREATE TABLE IF NOT EXISTS "public"."product_variations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "product_id" "uuid" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "external_variation_id" "text",
    "attributes" "jsonb",
    "stock_quantity" integer DEFAULT 0 NOT NULL,
    "price" numeric(10,2) NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "sku" "text" NOT NULL,
    "compare_at_price" numeric(10,2),
    "weight_kg" numeric(6,3),
    "length_cm" numeric(6,2),
    "width_cm" numeric(6,2),
    "height_cm" numeric(6,2),
    "image_url" "text",
    "cost_price" numeric(10,2) DEFAULT 0.00,
    CONSTRAINT "product_variations_stock_nonneg" CHECK (("stock_quantity" >= 0))
);


ALTER TABLE "public"."product_variations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."products" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "external_reference_id" "text",
    "title" "text" NOT NULL,
    "description" "text",
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "platform_category_id" "uuid",
    "cover_image_url" "text",
    "retracto_excluded" boolean DEFAULT false NOT NULL,
    "retracto_excluded_reason" "text",
    "safety_note" "text",
    "category_id" "uuid",
    "attributes" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL
);


ALTER TABLE "public"."products" OWNER TO "postgres";


COMMENT ON COLUMN "public"."products"."retracto_excluded" IS 'Si TRUE, el producto NO aplica retracto Art. 47 Ley 1480. Tenant decide según su vertical (cosmética abierta, software descargable, perecederos, etc.). Campo multi-tenant agnóstico.';



COMMENT ON COLUMN "public"."products"."retracto_excluded_reason" IS 'Razón legal libre que el bot cita cuando rechaza retracto. Ejemplo: "cosmética uso íntimo (Art. 47 parágrafo)" o "software descargado".';



COMMENT ON COLUMN "public"."products"."safety_note" IS 'Advertencia de uso seguro mostrada SIEMPRE por el bot (ej. "Diluir antes de usar, no aplicar directo en piel"). NULL = sin advertencia. Render garantizado (no truncado) en el contexto del LLM con marcador ⚠️.';



COMMENT ON COLUMN "public"."products"."category_id" IS 'ADR-0027 Pieza 1: categoría del producto (FK a product_categories, per-tenant). NULL → fallback título-head con log.warning durante el backfill (NO permanente).';



COMMENT ON COLUMN "public"."products"."attributes" IS 'ADR-0029 F2: valores de atributos PRODUCT-LEVEL (no-variante) del contrato de la categoría, ej. {"Ingrediente activo":"Bakuchiol","FPS":"50"}. El bot los cita como HECHOS estructurados (D4). Validados contra product_attribute_definitions por la API. Los variant-axis viven en product_variations.attributes.';



CREATE TABLE IF NOT EXISTS "public"."provider_health_alert_dedup" (
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "metric" "text" NOT NULL,
    "last_status" "text",
    "alerted_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."provider_health_alert_dedup" OWNER TO "postgres";


COMMENT ON TABLE "public"."provider_health_alert_dedup" IS 'F7 — estado persistente de dedup de alertas de salud por (tenant,provider,metric). Evita re-spam de Telegram tras restart del worker. Separada de tenant_provider_health (que el prune borra) para no perder el estado.';



CREATE TABLE IF NOT EXISTS "public"."purchase_order_items" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "po_id" "uuid" NOT NULL,
    "variation_id" "uuid" NOT NULL,
    "quantity" integer NOT NULL,
    "unit_cost" numeric(10,2) DEFAULT 0.00 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    CONSTRAINT "purchase_order_items_quantity_check" CHECK (("quantity" > 0))
);


ALTER TABLE "public"."purchase_order_items" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."purchase_orders" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "supplier_id" "uuid" NOT NULL,
    "status" "text" DEFAULT 'ordered'::"text" NOT NULL,
    "expected_date" timestamp with time zone,
    "total_amount" numeric(10,2) DEFAULT 0.00,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "po_number" bigint,
    CONSTRAINT "purchase_orders_status_check" CHECK (("status" = ANY (ARRAY['ordered'::"text", 'received'::"text", 'cancelled'::"text"])))
);


ALTER TABLE "public"."purchase_orders" OWNER TO "postgres";


COMMENT ON COLUMN "public"."purchase_orders"."po_number" IS 'Número humano consecutivo POR TENANT (OC-001, OC-002, …). Asignado por el trigger assign_purchase_order_number bajo advisory lock. UI lo formatea; cae al prefijo UUID si la columna no está poblada. F-transversales.';



CREATE TABLE IF NOT EXISTS "public"."rate_limit_windows" (
    "window_key" "text" NOT NULL,
    "count" integer DEFAULT 1 NOT NULL,
    "expires_at" timestamp with time zone NOT NULL
);


ALTER TABLE "public"."rate_limit_windows" OWNER TO "postgres";


COMMENT ON TABLE "public"."rate_limit_windows" IS 'Ventanas de rate limiting distribuido. Reemplaza el contador in-memory del API Gateway.';



CREATE TABLE IF NOT EXISTS "public"."retention_policies" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid",
    "entity" "text" NOT NULL,
    "ttl_days" integer NOT NULL,
    "action" "text" NOT NULL,
    "enabled" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "retention_policies_action_check" CHECK (("action" = ANY (ARRAY['archive'::"text", 'soft_delete'::"text", 'hard_delete'::"text", 'anonymize'::"text"]))),
    CONSTRAINT "retention_policies_entity_check" CHECK (("entity" = ANY (ARRAY['conversations'::"text", 'messages'::"text", 'contacts_inactive'::"text", 'pii_access_log'::"text", 'audit_log'::"text", 'messages_evidencia'::"text"]))),
    CONSTRAINT "retention_policies_ttl_days_check" CHECK ((("ttl_days" >= 1) AND ("ttl_days" <= 3660)))
);


ALTER TABLE "public"."retention_policies" OWNER TO "postgres";


COMMENT ON TABLE "public"."retention_policies" IS 'Rev. 95 — Políticas de retención por entidad (Habeas Data Art. 4d/Art. 16). tenant_id NULL = default global; tenant_id no nulo = override per-tenant.';



CREATE TABLE IF NOT EXISTS "public"."review_queue" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "last_message_id" "uuid",
    "fsm_state" "text",
    "reason" "text" NOT NULL,
    "error_chain" "text",
    "prompt_snapshot" "text",
    "priority" smallint DEFAULT 1 NOT NULL,
    "resolved" boolean DEFAULT false NOT NULL,
    "resolved_at" timestamp with time zone,
    "resolved_by" "text",
    "resolution_note" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."review_queue" OWNER TO "postgres";


COMMENT ON TABLE "public"."review_queue" IS 'Cola de conversaciones que requieren revisión humana (LLM degraded / invariant block / escalation manual). Rev. 104 F1-10.';



COMMENT ON COLUMN "public"."review_queue"."reason" IS 'llm_degraded | invariant_block | manual_escalation';



COMMENT ON COLUMN "public"."review_queue"."priority" IS '1=normal · 2=alta · 3=crítica (ej. mental_health_crisis)';



CREATE TABLE IF NOT EXISTS "public"."rma_requests" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "order_id" "uuid" NOT NULL,
    "conversation_id" "uuid",
    "contact_id" "uuid",
    "status" "public"."rma_status_enum" DEFAULT 'pending_return'::"public"."rma_status_enum" NOT NULL,
    "delivered_at" timestamp with time zone NOT NULL,
    "retracto_deadline" timestamp with time zone NOT NULL,
    "initiated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "initiated_by_actor" "public"."order_cancellation_actor" NOT NULL,
    "initiated_by_user_id" "uuid",
    "reason_code" "text" NOT NULL,
    "reason_text" "text",
    "items_json" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "refund_amount_cents" bigint DEFAULT 0 NOT NULL,
    "refund_method" "public"."refund_method_enum",
    "refund_legal_deadline" timestamp with time zone NOT NULL,
    "refund_completed_at" timestamp with time zone,
    "refund_txn_id" "text",
    "return_label_url" "text",
    "return_carrier" "text",
    "return_tracking" "text",
    "return_paid_by" "text" DEFAULT 'customer'::"text" NOT NULL,
    "product_received_at" timestamp with time zone,
    "product_condition" "text",
    "inspected_by_user_id" "uuid",
    "inspection_notes" "text",
    "customer_notified_email" boolean DEFAULT false NOT NULL,
    "customer_notified_whatsapp" boolean DEFAULT false NOT NULL,
    "operator_notified_telegram" boolean DEFAULT false NOT NULL,
    "legal_basis" "text" DEFAULT 'ley_1480_art_47'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);

ALTER TABLE ONLY "public"."rma_requests" REPLICA IDENTITY FULL;


ALTER TABLE "public"."rma_requests" OWNER TO "postgres";


COMMENT ON TABLE "public"."rma_requests" IS 'Retracto post-entrega bajo Ley 1480 Art. 47 (5 días hábiles desde entrega, refund 30 días calendario máximo). Multi-step lifecycle: pending_return → return_in_transit → received_inspection → approved_refunding → refund_completed. Posibles rejected paths cuando producto no aplica retracto.';



CREATE TABLE IF NOT EXISTS "public"."shipment_tracking_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "shipment_id" "uuid",
    "order_id" "uuid",
    "provider" "text" NOT NULL,
    "external_event_id" "text" NOT NULL,
    "raw_status" "text",
    "raw_estado_id" integer,
    "internal_status" "text" NOT NULL,
    "description" "text",
    "occurred_at" timestamp with time zone,
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "raw" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL
);


ALTER TABLE "public"."shipment_tracking_events" OWNER TO "postgres";


COMMENT ON TABLE "public"."shipment_tracking_events" IS 'Bitácora append-only de cambios físicos del envío reportados por courier webhook. Dedup por (provider, external_event_id). Rev. 108 — diseño cross-provider (Aveonline + Envia + MeLi).';



COMMENT ON COLUMN "public"."shipment_tracking_events"."external_event_id" IS 'Identificador único del evento del provider. Garantiza idempotencia at-least-once. Aveonline composite: guia|estado_id|fecha.';



COMMENT ON COLUMN "public"."shipment_tracking_events"."internal_status" IS 'Mapping canónico cross-provider: in_transit|delivered|exception|returned|cancelled|pending. Provider raw values mapeados en application layer.';



CREATE TABLE IF NOT EXISTS "public"."shipments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "order_id" "uuid",
    "status" "text" DEFAULT 'quoted'::"text" NOT NULL,
    "carrier" "text",
    "service" "text",
    "origin_address" "jsonb" NOT NULL,
    "destination_address" "jsonb" NOT NULL,
    "parcels" "jsonb" NOT NULL,
    "quote_response" "jsonb",
    "selected_rate" "jsonb",
    "label_url" "text",
    "tracking_number" "text",
    "tracking_url" "text",
    "estimated_delivery" "date",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "status_occurred_at" timestamp with time zone
);


ALTER TABLE "public"."shipments" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."stock_movements" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "product_id" "uuid",
    "variation_id" "uuid" NOT NULL,
    "delta" integer NOT NULL,
    "new_stock" integer NOT NULL,
    "reason" "text",
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "order_id" "uuid"
);


ALTER TABLE "public"."stock_movements" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."stock_reservations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "variation_id" "uuid" NOT NULL,
    "warehouse_id" "uuid",
    "cart_id" "uuid",
    "conversation_id" "uuid",
    "order_id" "uuid",
    "qty" integer NOT NULL,
    "status" "public"."stock_reservation_status" DEFAULT 'active'::"public"."stock_reservation_status" NOT NULL,
    "expires_at" timestamp with time zone NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "consumed_at" timestamp with time zone,
    "released_at" timestamp with time zone,
    CONSTRAINT "stock_reservations_check" CHECK (((("status" = 'consumed'::"public"."stock_reservation_status") AND ("consumed_at" IS NOT NULL)) OR (("status" = ANY (ARRAY['released'::"public"."stock_reservation_status", 'expired'::"public"."stock_reservation_status"])) AND ("released_at" IS NOT NULL)) OR (("status" = 'active'::"public"."stock_reservation_status") AND ("consumed_at" IS NULL) AND ("released_at" IS NULL)))),
    CONSTRAINT "stock_reservations_qty_check" CHECK (("qty" > 0))
);

ALTER TABLE ONLY "public"."stock_reservations" REPLICA IDENTITY FULL;


ALTER TABLE "public"."stock_reservations" OWNER TO "postgres";


COMMENT ON TABLE "public"."stock_reservations" IS 'Soft-reserve de inventario (Stripe Checkout pattern). Reserva temporal al confirmar intención de compra (post-quote_shipping). TTL 35 min alineado con PENDING_PAYMENT_TTL_MINUTES. Estados: active → (consumed | released | expired). El cálculo de stock disponible se hace via fn_variation_available_stock().';



CREATE TABLE IF NOT EXISTS "public"."suppliers" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "contact_email" "text",
    "phone" "text",
    "lead_time_days" integer DEFAULT 0,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL
);


ALTER TABLE "public"."suppliers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."telegram_alert_messages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "chat_id" "text" NOT NULL,
    "message_id" bigint NOT NULL,
    "alert_type" "text" DEFAULT 'takeover'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "resolved_at" timestamp with time zone
);


ALTER TABLE "public"."telegram_alert_messages" OWNER TO "postgres";


COMMENT ON TABLE "public"."telegram_alert_messages" IS 'Track 6: message_id de las alertas Telegram con inline keyboard (takeover). Permite editMessageReplyMarkup al resolver la conversación desde cualquier canal (el callback_query trae message_id, pero /resolver y la consola no). resolved_at NULL = alerta abierta.';



CREATE TABLE IF NOT EXISTS "public"."tenant_cancellation_policy" (
    "tenant_id" "uuid" NOT NULL,
    "allow_cancel_after_picked_up" boolean DEFAULT false NOT NULL,
    "auto_void_card_window_hours" integer DEFAULT 23 NOT NULL,
    "manual_refund_legal_days" integer DEFAULT 15 NOT NULL,
    "allow_partial_cancellation" boolean DEFAULT true NOT NULL,
    "enable_retracto_flow" boolean DEFAULT true NOT NULL,
    "retracto_window_business_days" integer DEFAULT 5 NOT NULL,
    "retracto_return_paid_by" "text" DEFAULT 'customer'::"text" NOT NULL,
    "retracto_excluded_product_ids" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "retracto_excluded_categories" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "high_value_escalation_threshold_cents" bigint DEFAULT 50000000 NOT NULL,
    "escalate_card_voids" boolean DEFAULT false NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "tenant_cancellation_policy_manual_refund_legal_days_check" CHECK ((("manual_refund_legal_days" >= 1) AND ("manual_refund_legal_days" <= 15))),
    CONSTRAINT "tenant_cancellation_policy_retracto_return_paid_by_check" CHECK (("retracto_return_paid_by" = ANY (ARRAY['customer'::"text", 'tenant'::"text"]))),
    CONSTRAINT "tenant_cancellation_policy_retracto_window_business_days_check" CHECK (("retracto_window_business_days" >= 5))
);


ALTER TABLE "public"."tenant_cancellation_policy" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_cancellation_policy" IS 'Política de cancelación + retracto configurable por tenant. Defaults cumplen Ley 1480. CHECK constraints garantizan que tenant NO puede ser más estricto que la ley (5 días hábiles retracto mín, 30 días refund máx).';



COMMENT ON COLUMN "public"."tenant_cancellation_policy"."manual_refund_legal_days" IS 'TECHO en días CALENDARIO para devolver el dinero. Ley 1480 art. 47 inc. final (mod. art. 3 Ley 2439 de 2024): en comercio electrónico no puede exceder 15. Se puede prometer menos, nunca más — al revés que retracto_window_business_days, que es un PISO.';



CREATE TABLE IF NOT EXISTS "public"."tenant_carriers" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "carrier_code" "text" NOT NULL,
    "enabled" boolean DEFAULT true NOT NULL,
    "display_label" "text",
    "priority" integer DEFAULT 100 NOT NULL,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "supports_cod" boolean DEFAULT false NOT NULL,
    "cod_override" "text",
    CONSTRAINT "tenant_carriers_cod_override_check" CHECK ((("cod_override" IS NULL) OR ("cod_override" = ANY (ARRAY['force_enable'::"text", 'force_disable'::"text"]))))
);


ALTER TABLE "public"."tenant_carriers" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_carriers" IS 'Sem 5 H.2.7. Preferencias de carriers por tenant per provider. Filtra resultados de quote — solo carriers enabled aparecen al cliente. Default open: tenant sin filas → todos los carriers globales de Envia. Tenant con ≥1 fila → solo enabled=true.';



COMMENT ON COLUMN "public"."tenant_carriers"."carrier_code" IS 'Identificador del carrier según Envia API. Case-insensitive en application layer (Envia mezcla camelCase y snake_case).';



COMMENT ON COLUMN "public"."tenant_carriers"."supports_cod" IS 'Capability per-carrier per-tenant: el tenant acepta recaudo
     contraentrega (COD) en este carrier. Aplica solo a provider=
     ''aveonline'' (rev. 108). Envia COD sigue pausado per Plan A.0.1.
     Restaurado por migración 20260530000000_restore_supports_cod_for_aveonline.';



COMMENT ON COLUMN "public"."tenant_carriers"."cod_override" IS 'Override 3-estado sobre canonical aveonline_carrier_capabilities.
     supports_cod. NULL = usar canon. force_enable = acuerdo especial
     tenant. force_disable = tenant deshabilita COD pese al canon.';



CREATE SEQUENCE IF NOT EXISTS "public"."tenant_carriers_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tenant_carriers_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tenant_carriers_id_seq" OWNED BY "public"."tenant_carriers"."id";



CREATE TABLE IF NOT EXISTS "public"."tenant_integrations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "status" "text" DEFAULT 'disconnected'::"text" NOT NULL,
    "credentials" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "meta" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "refresh_lease_until" timestamp with time zone,
    "refresh_lease_token" "uuid",
    "refresh_fail_count" integer DEFAULT 0 NOT NULL
);


ALTER TABLE "public"."tenant_integrations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tenant_legal_acceptance" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "document_id" "text" NOT NULL,
    "document_version" "text" NOT NULL,
    "accepted_by_user_id" "uuid",
    "accepted_by_email" "text",
    "ip_address" "inet",
    "user_agent" "text",
    "accepted_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."tenant_legal_acceptance" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_legal_acceptance" IS 'Rev. 99 — Click-wrap de DPA / Privacy Policy / Subprocessors. Append-only.';



CREATE TABLE IF NOT EXISTS "public"."tenant_offboarding_log" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "event" "text" NOT NULL,
    "actor_user_id" "uuid",
    "actor_email" "text",
    "actor_ip" "inet",
    "evidence" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "occurred_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "tenant_offboarding_log_event_valid" CHECK (("event" = ANY (ARRAY['requested'::"text", 'cancelled'::"text", 'exported'::"text", 'reminder_sent'::"text", 'hard_deleted'::"text", 'archived'::"text"])))
);


ALTER TABLE "public"."tenant_offboarding_log" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_offboarding_log" IS 'Append-only log de eventos del offboarding lifecycle. NO eliminar filas — sirve como evidencia forense post-hard-delete (retention 5y por Art. 22 Ley 1581). Sobrevive al borrado del tenant porque NO tiene FK CASCADE.';



CREATE SEQUENCE IF NOT EXISTS "public"."tenant_offboarding_log_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tenant_offboarding_log_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tenant_offboarding_log_id_seq" OWNED BY "public"."tenant_offboarding_log"."id";



CREATE TABLE IF NOT EXISTS "public"."tenant_payment_methods" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "method" "text" NOT NULL,
    "enabled" boolean DEFAULT true NOT NULL,
    "display_label" "text",
    "config_json" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "tenant_payment_methods_valid_method" CHECK (("method" = ANY (ARRAY['cod'::"text", 'online_wompi'::"text"])))
);


ALTER TABLE "public"."tenant_payment_methods" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_payment_methods" IS 'Métodos de pago habilitados per-tenant. Diseño modular simétrico a
     tenant_carriers. Whitelist constrained — extensión via migration.
     Lookup default-open: sin filas → todos enabled (backward compat).';



CREATE SEQUENCE IF NOT EXISTS "public"."tenant_payment_methods_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tenant_payment_methods_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tenant_payment_methods_id_seq" OWNED BY "public"."tenant_payment_methods"."id";



CREATE TABLE IF NOT EXISTS "public"."tenant_provider_capabilities" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "capability" "text" NOT NULL,
    "enabled" boolean DEFAULT false NOT NULL,
    "config" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."tenant_provider_capabilities" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_provider_capabilities" IS 'Matrix runtime per-tenant per-provider per-capability. Rev. 105 Sem 2 F.3. Reemplaza gradualmente capabilities hardcoded en tenant_integrations.meta. Permite enable/disable feature per-tenant sin código (UI Settings → Integraciones → Capabilities).';



COMMENT ON COLUMN "public"."tenant_provider_capabilities"."capability" IS 'snake_case namespace por provider. Ver lista canónica en lib services/api/lib/capabilities_matrix.py:CAPABILITIES_BY_PROVIDER.';



COMMENT ON COLUMN "public"."tenant_provider_capabilities"."config" IS 'Configuración específica per capability (carriers, fees, templates, tiers, etc.). Schema validado en application layer per capability.';



CREATE SEQUENCE IF NOT EXISTS "public"."tenant_provider_capabilities_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tenant_provider_capabilities_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tenant_provider_capabilities_id_seq" OWNED BY "public"."tenant_provider_capabilities"."id";



CREATE TABLE IF NOT EXISTS "public"."tenant_provider_health" (
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "metric" "text" NOT NULL,
    "value" "text",
    "threshold" "text",
    "status" "text" DEFAULT 'unknown'::"text" NOT NULL,
    "detail" "jsonb" DEFAULT '{}'::"jsonb",
    "observed_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "tenant_provider_health_provider_valid" CHECK (("provider" = ANY (ARRAY['whatsapp'::"text", 'wompi'::"text", 'meli'::"text", 'telegram'::"text", 'aveonline'::"text"]))),
    CONSTRAINT "tenant_provider_health_status_valid" CHECK (("status" = ANY (ARRAY['healthy'::"text", 'warning'::"text", 'critical'::"text", 'unknown'::"text"])))
);


ALTER TABLE "public"."tenant_provider_health" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_provider_health" IS 'Métricas de salud de las integraciones del tenant. Refrescada por cron cada 5min. UPSERT con PK (tenant, provider, metric) preserva única fila por métrica con última observación. Tenant ve via Settings → Salud.';



CREATE TABLE IF NOT EXISTS "public"."tenant_provider_identity" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "provider_internal_id" "text" NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "verified_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."tenant_provider_identity" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_provider_identity" IS 'Cross-mapping registry tenant ↔ proveedores externos. Rev. 105 Sem 2 F.12 (MA-10). UNIQUE(provider, provider_internal_id) impide cross-tenant identity collision. Resuelve estructuralmente el bug Telegram "primer tenant activo" + clase general de bugs multi-tenant cross-talk en webhooks/clientes outbound.';



COMMENT ON COLUMN "public"."tenant_provider_identity"."provider" IS 'Canónico snake_case: whatsapp | wompi | envia | meli | telegram | resend (futuros).';



COMMENT ON COLUMN "public"."tenant_provider_identity"."provider_internal_id" IS 'Identidad opaca del provider externo. Ejemplos: whatsapp=WABA phone_number_id, wompi=merchant_id, envia=account_id, meli=user_id, telegram=chat_id (operador) o bot_username, resend=verified_domain.';



COMMENT ON COLUMN "public"."tenant_provider_identity"."metadata" IS 'Metadata libre per provider: phone_number_id, bot_username, site_id, etc.';



CREATE SEQUENCE IF NOT EXISTS "public"."tenant_provider_identity_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tenant_provider_identity_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tenant_provider_identity_id_seq" OWNED BY "public"."tenant_provider_identity"."id";



CREATE TABLE IF NOT EXISTS "public"."tenant_shipping_provider_config" (
    "tenant_id" "uuid" NOT NULL,
    "active_provider" "text" DEFAULT 'envia'::"text" NOT NULL,
    "enabled_carriers" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "cod_enabled" boolean DEFAULT false NOT NULL,
    "insurance_strategy" "text" DEFAULT 'on_demand'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "real_guides_enabled" boolean DEFAULT false NOT NULL,
    CONSTRAINT "tenant_shipping_provider_config_active_provider_check" CHECK (("active_provider" = 'aveonline'::"text")),
    CONSTRAINT "tenant_shipping_provider_config_insurance_strategy_check" CHECK (("insurance_strategy" = ANY (ARRAY['always'::"text", 'on_demand'::"text", 'never'::"text"])))
);


ALTER TABLE "public"."tenant_shipping_provider_config" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_shipping_provider_config" IS 'Provider de despachos activo per-tenant. Single provider (sin fallback automático). Switcher en UI Tenant Console → Settings → Despachos. Decisión: ADR-0019 rev. 107.';



COMMENT ON COLUMN "public"."tenant_shipping_provider_config"."active_provider" IS 'Provider HOY usado para cotizar y generar guías nuevas. Cambiar al otro provider NO migra guías legacy — éstas siguen rastreándose en el provider original (read-only).';



COMMENT ON COLUMN "public"."tenant_shipping_provider_config"."real_guides_enabled" IS 'BLOQUE B — guías reales facturables para este tenant SOLO si (real_guides_enabled=true Y master AVEONLINE_GENERATE_REAL_GUIDES=true). Default false = simulado. Activación founder por-tenant (dinero real).';



CREATE TABLE IF NOT EXISTS "public"."tenant_subscriptions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "plan_code" "text" NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "started_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "ended_at" timestamp with time zone,
    "meta" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "tenant_subscriptions_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'trialing'::"text", 'past_due'::"text", 'canceled'::"text"])))
);


ALTER TABLE "public"."tenant_subscriptions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tenant_usage_counters" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "capability_key" "text" NOT NULL,
    "period_start" timestamp with time zone NOT NULL,
    "period_end" timestamp with time zone NOT NULL,
    "usage_count" bigint DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "tenant_usage_counters_usage_count_check" CHECK (("usage_count" >= 0))
);


ALTER TABLE "public"."tenant_usage_counters" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tenant_usage_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "capability_key" "text" NOT NULL,
    "units" integer DEFAULT 1 NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "tenant_usage_events_units_check" CHECK (("units" > 0))
);


ALTER TABLE "public"."tenant_usage_events" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tenant_users" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "role" "text" DEFAULT 'operator'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "inactivated_at" timestamp with time zone,
    "inactivated_reason" "text",
    "inactivated_by" "uuid",
    CONSTRAINT "tenant_users_role_check" CHECK (("role" = ANY (ARRAY['owner'::"text", 'manager'::"text", 'operator'::"text"]))),
    CONSTRAINT "tenant_users_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'inactive'::"text"])))
);


ALTER TABLE "public"."tenant_users" OWNER TO "postgres";


COMMENT ON COLUMN "public"."tenant_users"."status" IS 'active: acceso normal | inactive: suspendido temporalmente';



COMMENT ON COLUMN "public"."tenant_users"."inactivated_reason" IS 'Motivo de suspensión (ej: vacaciones, baja temporal). Opcional.';



CREATE TABLE IF NOT EXISTS "public"."tenant_webhook_secrets" (
    "id" bigint NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "integration" "text" NOT NULL,
    "secret_hash" "text" NOT NULL,
    "previous_secret_hash" "text",
    "grace_period_until" timestamp with time zone,
    "rotated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expires_at" timestamp with time zone NOT NULL,
    "audit_log" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."tenant_webhook_secrets" OWNER TO "postgres";


COMMENT ON TABLE "public"."tenant_webhook_secrets" IS 'Secretos de webhook per-tenant per-integration con rotación trimestral. Rev. 105 Sem 2 F.10 (MA-2). Secret plaintext NUNCA almacenado — solo bcrypt hash. Rotación retorna plaintext una vez para copiar al panel del provider, después se descarta. Grace period 7d permite migración sin downtime cuando tenant actualiza panel.';



COMMENT ON COLUMN "public"."tenant_webhook_secrets"."secret_hash" IS 'bcrypt(secret_plaintext). NUNCA plaintext aquí.';



COMMENT ON COLUMN "public"."tenant_webhook_secrets"."previous_secret_hash" IS 'Hash del secret anterior. Válido durante grace_period_until para evitar downtime de webhook delivery cuando tenant actualiza panel del provider.';



COMMENT ON COLUMN "public"."tenant_webhook_secrets"."audit_log" IS 'Append-only [{event, actor_id, reason, at}]. event ∈ created|rotated|revoked.';



CREATE SEQUENCE IF NOT EXISTS "public"."tenant_webhook_secrets_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tenant_webhook_secrets_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tenant_webhook_secrets_id_seq" OWNED BY "public"."tenant_webhook_secrets"."id";



CREATE TABLE IF NOT EXISTS "public"."tenants" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "meta_waba_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "shipping_origin" "jsonb",
    "logo_url" "text",
    "low_stock_threshold" integer DEFAULT 5 NOT NULL,
    "nit" "text",
    "email_contacto" "text",
    "telefono_contacto" "text",
    "store_type" "text" DEFAULT 'fisica'::"text" NOT NULL,
    "social_links" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "store_locations" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "mision" "text",
    "valores" "text",
    "tono_comunicacion" "text" DEFAULT 'amigable'::"text" NOT NULL,
    "support_schedule" "jsonb",
    "after_hours_message" "text",
    "vision" "text",
    "escalation_role" "text" DEFAULT 'especialista'::"text" NOT NULL,
    "business_pitch" "text",
    "product_groups" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "show_prices_in_catalog" boolean DEFAULT true NOT NULL,
    "deletion_requested_at" timestamp with time zone,
    "deletion_scheduled_for" timestamp with time zone,
    "deletion_requested_by" "uuid",
    "deletion_reason" "text",
    "deleted_at" timestamp with time zone,
    "tipo_persona" "text",
    "razon_social" "text",
    "doc_tipo" "text",
    "doc_numero" "text",
    "doc_dv" "text",
    "regimen_iva" "text",
    "domicilio_direccion" "text",
    "domicilio_ciudad" "text",
    "domicilio_departamento" "text",
    "domicilio_pais" "text" DEFAULT 'CO'::"text" NOT NULL,
    "email_habeas_data" "text",
    CONSTRAINT "tenants_doc_tipo_check" CHECK ((("doc_tipo" IS NULL) OR ("doc_tipo" = ANY (ARRAY['NIT'::"text", 'CC'::"text", 'CE'::"text", 'PAS'::"text"])))),
    CONSTRAINT "tenants_escalation_role_check" CHECK (("escalation_role" = ANY (ARRAY['asesor'::"text", 'especialista'::"text", 'consultor'::"text", 'agente'::"text"]))),
    CONSTRAINT "tenants_regimen_iva_check" CHECK ((("regimen_iva" IS NULL) OR ("regimen_iva" = ANY (ARRAY['responsable'::"text", 'no_responsable'::"text"])))),
    CONSTRAINT "tenants_store_type_check" CHECK (("store_type" = ANY (ARRAY['fisica'::"text", 'virtual'::"text", 'fisica_virtual'::"text"]))),
    CONSTRAINT "tenants_tipo_persona_check" CHECK ((("tipo_persona" IS NULL) OR ("tipo_persona" = ANY (ARRAY['natural'::"text", 'juridica'::"text"])))),
    CONSTRAINT "tenants_tono_comunicacion_check" CHECK (("tono_comunicacion" = ANY (ARRAY['formal'::"text", 'amigable'::"text", 'cercano'::"text", 'profesional'::"text", 'juvenil'::"text"])))
);


ALTER TABLE "public"."tenants" OWNER TO "postgres";


COMMENT ON COLUMN "public"."tenants"."shipping_origin" IS 'Dirección de origen para envíos Envia. Estructura: {name, company, street, city, state, postal_code, country, phone}';



COMMENT ON COLUMN "public"."tenants"."logo_url" IS 'URL del logo del tenant en Supabase Storage (bucket tenant-branding). Se muestra en el sidebar de la Tenant Console.';



COMMENT ON COLUMN "public"."tenants"."nit" IS 'LEGADO: identificador mezclado (NIT o CC). Reemplazado por doc_tipo + doc_numero + doc_dv. Se conserva porque lo consume el system prompt del bot; migrar consumidores y retirar.';



COMMENT ON COLUMN "public"."tenants"."email_contacto" IS 'Email de contacto del negocio';



COMMENT ON COLUMN "public"."tenants"."telefono_contacto" IS 'Teléfono de contacto del negocio';



COMMENT ON COLUMN "public"."tenants"."store_type" IS 'Tipo de operación: fisica | virtual | fisica_virtual';



COMMENT ON COLUMN "public"."tenants"."social_links" IS 'Links de redes sociales: {instagram, facebook, tiktok, youtube, website}';



COMMENT ON COLUMN "public"."tenants"."store_locations" IS 'Array de sedes físicas: [{name, city, state, street}]';



COMMENT ON COLUMN "public"."tenants"."mision" IS 'Propósito del negocio (max 280 chars). Se inyecta en el system prompt del bot.';



COMMENT ON COLUMN "public"."tenants"."valores" IS 'Valores de la marca (max 280 chars). Se inyecta en el system prompt del bot.';



COMMENT ON COLUMN "public"."tenants"."tono_comunicacion" IS 'Tono de comunicación del bot (rev. 69 NOT NULL). Valores: formal/profesional/amigable/cercano/juvenil. Default ''amigable''.';



COMMENT ON COLUMN "public"."tenants"."support_schedule" IS 'Horario estructurado: {days:[0-6], open:"HH:MM", close:"HH:MM"}. Fuente única para horario textual del bot (rev. 71).';



COMMENT ON COLUMN "public"."tenants"."after_hours_message" IS 'Mensaje que el bot envía cuando se solicita asesor fuera del horario de support_schedule.';



COMMENT ON COLUMN "public"."tenants"."vision" IS 'Visión del negocio (max 280 chars). Dónde quiere llegar la empresa. Opcional.';



COMMENT ON COLUMN "public"."tenants"."escalation_role" IS 'Rol del humano al que se escala (default ''especialista'' rev. 103). El bot dice "te conecto con un {escalation_role}". Configurable por tenant — vertical define término preferido (asesor/agente/experto/etc).';



COMMENT ON COLUMN "public"."tenants"."business_pitch" IS 'Sem 7 F2 cierre 2026-05-20 — frase corta (≤120 chars) que el bot menciona al saludar cliente nuevo. Ej KAIU: "Cosmética artesanal 100% natural". Si NULL, el bot omite la frase.';



COMMENT ON COLUMN "public"."tenants"."product_groups" IS 'Sem 7 F2 cierre 2026-05-20 — array de strings con las líneas de producto que el bot presenta. Si vacío, deriva del catálogo. NO son "categorías" formales — usa lenguaje natural del tenant.';



COMMENT ON COLUMN "public"."tenants"."show_prices_in_catalog" IS 'Sem 7 F2 cierre 2026-05-20 — si true, bot incluye precios en listados de catálogo. false para tenants premium/B2B custom.';



COMMENT ON COLUMN "public"."tenants"."deletion_requested_at" IS 'Cuando el owner solicitó offboarding. NULL = activo. Soft-delete arranca aquí.';



COMMENT ON COLUMN "public"."tenants"."deletion_scheduled_for" IS 'Cuando el cron hard-deletea el tenant (típico: requested_at + 30d).';



COMMENT ON COLUMN "public"."tenants"."deletion_requested_by" IS 'Usuario que originó el offboarding (auth.users.id).';



COMMENT ON COLUMN "public"."tenants"."deletion_reason" IS 'Razón textual del owner. Persistida para auditoría SIC.';



COMMENT ON COLUMN "public"."tenants"."deleted_at" IS 'Cuando el cron ejecutó hard-delete. NULL = aún recoverable.';



COMMENT ON COLUMN "public"."tenants"."tipo_persona" IS 'natural | juridica. Determina el documento aplicable y las obligaciones fiscales (la aplicabilidad la confirma el contador del tenant).';



COMMENT ON COLUMN "public"."tenants"."razon_social" IS 'Nombre LEGAL (razón social o nombres y apellidos). Distinto de `name`, que es la marca comercial.';



COMMENT ON COLUMN "public"."tenants"."doc_dv" IS 'Dígito de verificación del NIT. Solo aplica a doc_tipo = NIT.';



COMMENT ON COLUMN "public"."tenants"."regimen_iva" IS 'responsable | no_responsable (Art. 437 ET, umbral 3.500 UVT). Dato informativo: NO determina por sí solo la obligación de facturar.';



COMMENT ON COLUMN "public"."tenants"."email_habeas_data" IS 'Canal para que el titular ejerza derechos (Ley 1581). Puede diferir del email comercial.';



CREATE TABLE IF NOT EXISTS "public"."user_dismissed_alerts" (
    "user_id" "uuid" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "alert_key" "text" NOT NULL,
    "dismissed_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."user_dismissed_alerts" OWNER TO "postgres";


COMMENT ON TABLE "public"."user_dismissed_alerts" IS 'Persiste qué alertas one-time dismissed cada usuario (ej. banner KB rev. 68 migración general→faq).';



CREATE OR REPLACE VIEW "public"."vw_consent_events_unified" WITH ("security_invoker"='true') AS
 SELECT "cal"."id",
    "cal"."tenant_id",
    "cal"."contact_id",
    "cal"."phone_hash",
    "cal"."event" AS "event_kind",
    "cal"."source",
    "cal"."actor_email",
    "cal"."actor_user_id",
    "cal"."evidence",
    "cal"."occurred_at",
    "cal"."created_at",
    'consent_audit_log'::"text" AS "origin_table"
   FROM "public"."consent_audit_log" "cal"
UNION ALL
 SELECT "al"."id",
    "al"."tenant_id",
    ("al"."entity_id")::"uuid" AS "contact_id",
    NULL::"text" AS "phone_hash",
        CASE
            WHEN (("al"."action" ~~* '%consent_given%'::"text") OR ("al"."action" ~~* '%consent_granted%'::"text")) THEN 'granted'::"text"
            WHEN (("al"."action" ~~* '%consent_revok%'::"text") OR ("al"."action" ~~* '%revoked%'::"text")) THEN 'revoked'::"text"
            WHEN (("al"."action" ~~* '%rectif%'::"text") OR ("al"."action" ~~* '%updated%'::"text")) THEN 'rectified'::"text"
            ELSE "al"."action"
        END AS "event_kind",
    'tenant_console'::"text" AS "source",
    "al"."user_email" AS "actor_email",
    "al"."user_id" AS "actor_user_id",
    "al"."payload" AS "evidence",
    "al"."created_at" AS "occurred_at",
    "al"."created_at",
    'audit_log'::"text" AS "origin_table"
   FROM "public"."audit_log" "al"
  WHERE (("al"."entity_type" = 'contact'::"text") AND (("al"."action" ~~* '%consent%'::"text") OR ("al"."action" ~~* '%revok%'::"text") OR ("al"."action" ~~* '%rectif%'::"text") OR ("al"."action" = 'deleted'::"text")));


ALTER VIEW "public"."vw_consent_events_unified" OWNER TO "postgres";


COMMENT ON VIEW "public"."vw_consent_events_unified" IS 'Rev. 101 (F3) — Vista unificada eventos consent. Sem 5 H.fix-cve (rev. 105 2026-05-07): recreada con security_invoker=true para respetar RLS Tenant Isolation. Pre-fix bypassaba RLS al ejecutar como owner postgres (CVE Habeas Data potential).';



CREATE TABLE IF NOT EXISTS "public"."webhook_events_seen" (
    "id" bigint NOT NULL,
    "integration" "text" NOT NULL,
    "event_uid" "text" NOT NULL,
    "tenant_id" "uuid",
    "event_type" "text",
    "correlation_id" "text",
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "processed_at" timestamp with time zone,
    "raw_signature" "text"
);


ALTER TABLE "public"."webhook_events_seen" OWNER TO "postgres";


COMMENT ON TABLE "public"."webhook_events_seen" IS 'Dedup genérica para webhooks Rev. 105 Sem 2 F.4. UNIQUE(integration, event_uid). Reemplaza gradualmente wompi_events_seen + meli_webhook_dedup (esos siguen activos durante migración 30d post-deploy).';



CREATE SEQUENCE IF NOT EXISTS "public"."webhook_events_seen_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."webhook_events_seen_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."webhook_events_seen_id_seq" OWNED BY "public"."webhook_events_seen"."id";



CREATE TABLE IF NOT EXISTS "public"."whatsapp_templates" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "meta_template_id" "text",
    "waba_id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "language" "text" NOT NULL,
    "category" "text" NOT NULL,
    "components" "jsonb" NOT NULL,
    "parameter_format" "text" DEFAULT 'POSITIONAL'::"text" NOT NULL,
    "status" "text" DEFAULT 'LOCAL_DRAFT'::"text" NOT NULL,
    "status_reason" "text",
    "quality_rating" "text" DEFAULT 'UNKNOWN'::"text" NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "submitted_at" timestamp with time zone,
    "approved_at" timestamp with time zone,
    CONSTRAINT "chk_whatsapp_templates_category" CHECK (("category" = ANY (ARRAY['MARKETING'::"text", 'UTILITY'::"text", 'AUTHENTICATION'::"text"]))),
    CONSTRAINT "chk_whatsapp_templates_language_format" CHECK (("language" ~ '^[a-z]{2}(_[A-Z]{2})?$'::"text")),
    CONSTRAINT "chk_whatsapp_templates_name_format" CHECK (("name" ~ '^[a-z][a-z0-9_]{2,49}$'::"text")),
    CONSTRAINT "chk_whatsapp_templates_parameter_format" CHECK (("parameter_format" = ANY (ARRAY['POSITIONAL'::"text", 'NAMED'::"text"]))),
    CONSTRAINT "chk_whatsapp_templates_quality_rating" CHECK (("quality_rating" = ANY (ARRAY['GREEN'::"text", 'YELLOW'::"text", 'RED'::"text", 'UNKNOWN'::"text"]))),
    CONSTRAINT "chk_whatsapp_templates_status" CHECK (("status" = ANY (ARRAY['LOCAL_DRAFT'::"text", 'PENDING'::"text", 'APPROVED'::"text", 'REJECTED'::"text", 'PAUSED'::"text", 'DISABLED'::"text", 'FLAGGED'::"text", 'LIMIT_EXCEEDED'::"text", 'ARCHIVED'::"text", 'UNARCHIVED'::"text", 'DELETED'::"text", 'IN_APPEAL'::"text", 'LOCKED'::"text", 'REINSTATED'::"text", 'PENDING_DELETION'::"text"])))
);


ALTER TABLE "public"."whatsapp_templates" OWNER TO "postgres";


COMMENT ON TABLE "public"."whatsapp_templates" IS 'HSM templates per-tenant Meta WhatsApp Cloud API. Re-seed 2026-07-04: copy es-CO en TUTEO (alineado al tono del bot) + marca en FOOTER parametrizado desde tenants.name (antes KAIU hardcodeado en cart_abandoned). Re-escribe solo filas LOCAL_DRAFT; submit a Meta via scripts/admin/submit_template_to_meta.py.';



COMMENT ON COLUMN "public"."whatsapp_templates"."meta_template_id" IS 'ID retornado por Meta tras POST /{WABA_ID}/message_templates. NULL mientras el template esté en LOCAL_DRAFT (no submitted aún).';



COMMENT ON COLUMN "public"."whatsapp_templates"."components" IS 'Array JSONB con estructura Meta: HEADER (text/image/video/doc), BODY (texto con placeholders {{1}} o {{name}}), FOOTER (texto opcional), BUTTONS (QUICK_REPLY/URL/PHONE_NUMBER/COPY_CODE/OTP). Ver dossier docs/research/whatsapp-meta-dossier-2026-05-05.md sec. 4.5.';



COMMENT ON COLUMN "public"."whatsapp_templates"."parameter_format" IS 'POSITIONAL = placeholders {{1}}, {{2}} (default histórico). NAMED = placeholders {{customer_name}}, {{order_id}} (Meta v22+). Mutuamente excluyentes en mismo template.';



COMMENT ON CONSTRAINT "chk_whatsapp_templates_name_format" ON "public"."whatsapp_templates" IS 'Meta exige: lowercase + dígitos + underscores, 3-50 chars, debe empezar con letra. Ejemplos: payment_reminder_v1, order_shipped, cart_abandoned_24h.';



CREATE TABLE IF NOT EXISTS "public"."whatsapp_webhook_inbox" (
    "body_sha256" "text" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "raw_payload" "jsonb" NOT NULL,
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "processed_at" timestamp with time zone,
    "attempts" integer DEFAULT 0 NOT NULL,
    "claimed_at" timestamp with time zone,
    "last_error" "text"
);


ALTER TABLE "public"."whatsapp_webhook_inbox" OWNER TO "postgres";


COMMENT ON TABLE "public"."whatsapp_webhook_inbox" IS 'Inbox durable del webhook de WhatsApp: el payload (ya HMAC-verificado) se persiste ANTES del 200 a Meta. Como Meta no reintenta un 200, sin esto un crash entre el ACK y el procesamiento perdía el mensaje del cliente para siempre.';



COMMENT ON COLUMN "public"."whatsapp_webhook_inbox"."tenant_id" IS 'Tenant HMAC-verificado del path. El re-drive lo usa como autoridad en vez de re-resolver por el body (cierra cross-talk, A11/WH-01).';



CREATE TABLE IF NOT EXISTS "public"."wompi_events_seen" (
    "event_id" "text" NOT NULL,
    "tenant_id" "uuid" NOT NULL,
    "event_type" "text" NOT NULL,
    "transaction_id" "text",
    "reference" "text",
    "status" "text",
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "processed_at" timestamp with time zone
);


ALTER TABLE "public"."wompi_events_seen" OWNER TO "postgres";


COMMENT ON TABLE "public"."wompi_events_seen" IS 'Idempotencia de webhooks Wompi. Antes de procesar un evento, INSERT con ON CONFLICT DO NOTHING — si el insert falló (event_id ya existía), descartar como duplicado.';



CREATE TABLE IF NOT EXISTS "public"."wompi_webhook_inbox" (
    "checksum" "text" NOT NULL,
    "raw_payload" "jsonb" NOT NULL,
    "received_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "processed_at" timestamp with time zone,
    "attempts" integer DEFAULT 0 NOT NULL,
    "claimed_at" timestamp with time zone,
    "last_error" "text"
);


ALTER TABLE "public"."wompi_webhook_inbox" OWNER TO "postgres";


COMMENT ON TABLE "public"."wompi_webhook_inbox" IS 'W2 durabilidad Wompi: captura durable del payload crudo ANTES del 200 ACK; el worker reconcilia filas processed_at IS NULL re-POSTeando a /api/v1/webhooks/wompi. Idempotencia de dinero = wompi_events_seen (checksum) + guard estado terminal de la orden.';



ALTER TABLE ONLY "public"."agentic_shadow_log" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."agentic_shadow_log_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."compliance_enforcement_log" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."compliance_enforcement_log_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."credential_access_log" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."credential_access_log_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."mfa_recovery_codes" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."mfa_recovery_codes_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."outbound_idempotency_cache" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."outbound_idempotency_cache_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tenant_carriers" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tenant_carriers_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tenant_offboarding_log" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tenant_offboarding_log_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tenant_payment_methods" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tenant_payment_methods_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tenant_provider_capabilities" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tenant_provider_capabilities_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tenant_provider_identity" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tenant_provider_identity_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tenant_webhook_secrets" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tenant_webhook_secrets_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."webhook_events_seen" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."webhook_events_seen_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."agentic_shadow_log"
    ADD CONSTRAINT "agentic_shadow_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ai_agents"
    ADD CONSTRAINT "ai_agents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ai_insights"
    ADD CONSTRAINT "ai_insights_pkey" PRIMARY KEY ("tenant_id", "module");



ALTER TABLE ONLY "public"."api_security_events"
    ADD CONSTRAINT "api_security_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."audit_log"
    ADD CONSTRAINT "audit_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."aveonline_carrier_capabilities"
    ADD CONSTRAINT "aveonline_carrier_capabilities_pkey" PRIMARY KEY ("carrier_name");



ALTER TABLE ONLY "public"."billing_plans"
    ADD CONSTRAINT "billing_plans_pkey" PRIMARY KEY ("plan_code");



ALTER TABLE ONLY "public"."bot_source_log"
    ADD CONSTRAINT "bot_source_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."cart_events"
    ADD CONSTRAINT "cart_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."claims"
    ADD CONSTRAINT "claims_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."compliance_enforcement_log"
    ADD CONSTRAINT "compliance_enforcement_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."consent_audit_log"
    ADD CONSTRAINT "consent_audit_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."contacts"
    ADD CONSTRAINT "contacts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."contacts"
    ADD CONSTRAINT "contacts_tenant_id_phone_key" UNIQUE ("tenant_id", "phone");



ALTER TABLE ONLY "public"."conversation_cart_items"
    ADD CONSTRAINT "conversation_cart_items_cart_id_variation_id_key" UNIQUE ("cart_id", "variation_id");



ALTER TABLE ONLY "public"."conversation_cart_items"
    ADD CONSTRAINT "conversation_cart_items_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."conversation_carts"
    ADD CONSTRAINT "conversation_carts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."conversation_notes"
    ADD CONSTRAINT "conversation_notes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."conversation_reads"
    ADD CONSTRAINT "conversation_reads_pkey" PRIMARY KEY ("tenant_id", "user_id", "conversation_id");



ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."coupon_redemptions"
    ADD CONSTRAINT "coupon_redemptions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."coupons"
    ADD CONSTRAINT "coupons_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."credential_access_log"
    ADD CONSTRAINT "credential_access_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."email_events"
    ADD CONSTRAINT "email_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."email_events"
    ADD CONSTRAINT "email_events_svix_id_key" UNIQUE ("svix_id");



ALTER TABLE ONLY "public"."expenses"
    ADD CONSTRAINT "expenses_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."idempotency_keys"
    ADD CONSTRAINT "idempotency_keys_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."idempotency_keys"
    ADD CONSTRAINT "idempotency_keys_tenant_id_idempotency_key_request_method_r_key" UNIQUE ("tenant_id", "idempotency_key", "request_method", "request_path");



ALTER TABLE ONLY "public"."integration_oauth_states"
    ADD CONSTRAINT "integration_oauth_states_nonce_unique" UNIQUE ("provider", "nonce_hash");



ALTER TABLE ONLY "public"."integration_oauth_states"
    ADD CONSTRAINT "integration_oauth_states_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."kb_documents"
    ADD CONSTRAINT "kb_documents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."marketplace_listings"
    ADD CONSTRAINT "marketplace_listings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."marketplace_listings"
    ADD CONSTRAINT "marketplace_listings_tenant_id_provider_external_id_key" UNIQUE ("tenant_id", "provider", "external_id");



ALTER TABLE ONLY "public"."marketplace_listings"
    ADD CONSTRAINT "marketplace_listings_tenant_id_provider_variation_id_key" UNIQUE ("tenant_id", "provider", "variation_id");



ALTER TABLE ONLY "public"."meli_webhook_dedup"
    ADD CONSTRAINT "meli_webhook_dedup_pkey" PRIMARY KEY ("dedup_key");



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_meta_message_id_key" UNIQUE ("meta_message_id");



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mfa_recovery_codes"
    ADD CONSTRAINT "mfa_recovery_codes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notification_settings"
    ADD CONSTRAINT "notification_settings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notification_settings"
    ADD CONSTRAINT "notification_settings_tenant_id_channel_key" UNIQUE ("tenant_id", "channel");



ALTER TABLE ONLY "public"."order_cancellations"
    ADD CONSTRAINT "order_cancellations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."order_items"
    ADD CONSTRAINT "order_items_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."order_receipts"
    ADD CONSTRAINT "order_receipts_numero_unico" UNIQUE ("tenant_id", "numero_seq");



ALTER TABLE ONLY "public"."order_receipts"
    ADD CONSTRAINT "order_receipts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."order_receipts"
    ADD CONSTRAINT "order_receipts_uno_por_pedido" UNIQUE ("tenant_id", "order_id");



ALTER TABLE ONLY "public"."order_tracking"
    ADD CONSTRAINT "order_tracking_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_pkey" PRIMARY KEY ("id");



ALTER TABLE "public"."orders"
    ADD CONSTRAINT "orders_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'pending_payment'::"text", 'confirmed'::"text", 'processing'::"text", 'shipped'::"text", 'delivered'::"text", 'cancelled'::"text"]))) NOT VALID;



ALTER TABLE ONLY "public"."outbound_idempotency_cache"
    ADD CONSTRAINT "outbound_idempotency_cache_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."outbound_idempotency_cache"
    ADD CONSTRAINT "outbound_idempotency_cache_uniq" UNIQUE ("provider", "tenant_id", "request_hash");



ALTER TABLE ONLY "public"."payment_reversal_requests"
    ADD CONSTRAINT "payment_reversal_requests_claim_unico" UNIQUE ("claim_id");



ALTER TABLE ONLY "public"."payment_reversal_requests"
    ADD CONSTRAINT "payment_reversal_requests_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."payments"
    ADD CONSTRAINT "payments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pii_access_log"
    ADD CONSTRAINT "pii_access_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."plan_capabilities"
    ADD CONSTRAINT "plan_capabilities_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."plan_capabilities"
    ADD CONSTRAINT "plan_capabilities_plan_code_capability_key_key" UNIQUE ("plan_code", "capability_key");



ALTER TABLE ONLY "public"."platform_categories"
    ADD CONSTRAINT "platform_categories_name_key" UNIQUE ("name");



ALTER TABLE ONLY "public"."platform_categories"
    ADD CONSTRAINT "platform_categories_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."product_attribute_definitions"
    ADD CONSTRAINT "product_attribute_definitions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."product_attribute_definitions"
    ADD CONSTRAINT "product_attribute_definitions_tenant_id_product_category_id_key" UNIQUE ("tenant_id", "product_category_id", "code");



ALTER TABLE ONLY "public"."product_categories"
    ADD CONSTRAINT "product_categories_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."product_categories"
    ADD CONSTRAINT "product_categories_tenant_id_name_key" UNIQUE ("tenant_id", "name");



ALTER TABLE ONLY "public"."product_variations"
    ADD CONSTRAINT "product_variations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."products"
    ADD CONSTRAINT "products_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."provider_health_alert_dedup"
    ADD CONSTRAINT "provider_health_alert_dedup_pkey" PRIMARY KEY ("tenant_id", "provider", "metric");



ALTER TABLE ONLY "public"."purchase_order_items"
    ADD CONSTRAINT "purchase_order_items_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."purchase_orders"
    ADD CONSTRAINT "purchase_orders_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."rate_limit_windows"
    ADD CONSTRAINT "rate_limit_windows_pkey" PRIMARY KEY ("window_key");



ALTER TABLE ONLY "public"."retention_policies"
    ADD CONSTRAINT "retention_policies_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."retention_policies"
    ADD CONSTRAINT "retention_policies_tenant_id_entity_key" UNIQUE NULLS NOT DISTINCT ("tenant_id", "entity");



ALTER TABLE ONLY "public"."review_queue"
    ADD CONSTRAINT "review_queue_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."rma_requests"
    ADD CONSTRAINT "rma_requests_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."shipment_tracking_events"
    ADD CONSTRAINT "shipment_tracking_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."shipment_tracking_events"
    ADD CONSTRAINT "shipment_tracking_events_uniq" UNIQUE ("provider", "external_event_id");



ALTER TABLE ONLY "public"."shipments"
    ADD CONSTRAINT "shipments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."stock_movements"
    ADD CONSTRAINT "stock_movements_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."stock_reservations"
    ADD CONSTRAINT "stock_reservations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."suppliers"
    ADD CONSTRAINT "suppliers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."telegram_alert_messages"
    ADD CONSTRAINT "telegram_alert_messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_cancellation_policy"
    ADD CONSTRAINT "tenant_cancellation_policy_pkey" PRIMARY KEY ("tenant_id");



ALTER TABLE ONLY "public"."tenant_carriers"
    ADD CONSTRAINT "tenant_carriers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_carriers"
    ADD CONSTRAINT "tenant_carriers_uniq" UNIQUE ("tenant_id", "provider", "carrier_code");



ALTER TABLE ONLY "public"."tenant_integrations"
    ADD CONSTRAINT "tenant_integrations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_integrations"
    ADD CONSTRAINT "tenant_integrations_tenant_id_provider_key" UNIQUE ("tenant_id", "provider");



ALTER TABLE ONLY "public"."tenant_legal_acceptance"
    ADD CONSTRAINT "tenant_legal_acceptance_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_offboarding_log"
    ADD CONSTRAINT "tenant_offboarding_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_payment_methods"
    ADD CONSTRAINT "tenant_payment_methods_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_payment_methods"
    ADD CONSTRAINT "tenant_payment_methods_uniq" UNIQUE ("tenant_id", "method");



ALTER TABLE ONLY "public"."tenant_provider_capabilities"
    ADD CONSTRAINT "tenant_provider_capabilities_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_provider_capabilities"
    ADD CONSTRAINT "tenant_provider_capabilities_uniq" UNIQUE ("tenant_id", "provider", "capability");



ALTER TABLE ONLY "public"."tenant_provider_health"
    ADD CONSTRAINT "tenant_provider_health_pkey" PRIMARY KEY ("tenant_id", "provider", "metric");



ALTER TABLE ONLY "public"."tenant_provider_identity"
    ADD CONSTRAINT "tenant_provider_identity_external_uniq" UNIQUE ("provider", "provider_internal_id");



ALTER TABLE ONLY "public"."tenant_provider_identity"
    ADD CONSTRAINT "tenant_provider_identity_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_shipping_provider_config"
    ADD CONSTRAINT "tenant_shipping_provider_config_pkey" PRIMARY KEY ("tenant_id");



ALTER TABLE ONLY "public"."tenant_subscriptions"
    ADD CONSTRAINT "tenant_subscriptions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_subscriptions"
    ADD CONSTRAINT "tenant_subscriptions_tenant_id_key" UNIQUE ("tenant_id");



ALTER TABLE ONLY "public"."tenant_usage_counters"
    ADD CONSTRAINT "tenant_usage_counters_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_usage_counters"
    ADD CONSTRAINT "tenant_usage_counters_tenant_id_capability_key_period_start_key" UNIQUE ("tenant_id", "capability_key", "period_start", "period_end");



ALTER TABLE ONLY "public"."tenant_usage_events"
    ADD CONSTRAINT "tenant_usage_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_users"
    ADD CONSTRAINT "tenant_users_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_users"
    ADD CONSTRAINT "tenant_users_tenant_user_unique" UNIQUE ("tenant_id", "user_id");



ALTER TABLE ONLY "public"."tenant_users"
    ADD CONSTRAINT "tenant_users_user_id_tenant_id_key" UNIQUE ("user_id", "tenant_id");



ALTER TABLE ONLY "public"."tenant_users"
    ADD CONSTRAINT "tenant_users_user_id_unique" UNIQUE ("user_id");



ALTER TABLE ONLY "public"."tenant_webhook_secrets"
    ADD CONSTRAINT "tenant_webhook_secrets_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tenant_webhook_secrets"
    ADD CONSTRAINT "tenant_webhook_secrets_uniq" UNIQUE ("tenant_id", "integration");



ALTER TABLE ONLY "public"."tenants"
    ADD CONSTRAINT "tenants_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."product_variations"
    ADD CONSTRAINT "uc_tenant_sku" UNIQUE ("tenant_id", "sku");



ALTER TABLE ONLY "public"."whatsapp_templates"
    ADD CONSTRAINT "uq_whatsapp_templates_tenant_name_lang" UNIQUE ("tenant_id", "name", "language");



ALTER TABLE ONLY "public"."user_dismissed_alerts"
    ADD CONSTRAINT "user_dismissed_alerts_pkey" PRIMARY KEY ("user_id", "tenant_id", "alert_key");



ALTER TABLE ONLY "public"."webhook_events_seen"
    ADD CONSTRAINT "webhook_events_seen_integration_event_uniq" UNIQUE ("integration", "event_uid");



ALTER TABLE ONLY "public"."webhook_events_seen"
    ADD CONSTRAINT "webhook_events_seen_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."whatsapp_templates"
    ADD CONSTRAINT "whatsapp_templates_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."whatsapp_webhook_inbox"
    ADD CONSTRAINT "whatsapp_webhook_inbox_pkey" PRIMARY KEY ("body_sha256");



ALTER TABLE ONLY "public"."wompi_events_seen"
    ADD CONSTRAINT "wompi_events_seen_pkey" PRIMARY KEY ("event_id");



ALTER TABLE ONLY "public"."wompi_webhook_inbox"
    ADD CONSTRAINT "wompi_webhook_inbox_pkey" PRIMARY KEY ("checksum");



CREATE UNIQUE INDEX "ai_agents_tenant_default_unique" ON "public"."ai_agents" USING "btree" ("tenant_id") WHERE ("is_default" = true);



CREATE UNIQUE INDEX "ai_agents_tenant_role_unique" ON "public"."ai_agents" USING "btree" ("tenant_id", "role");



COMMENT ON INDEX "public"."ai_agents_tenant_role_unique" IS 'F5 ADR-0017 — 1 agente por rol por tenant. Cierra la carrera read-then-write del server action createAgent. Espejo del invariante de UI (takenRoles).';



CREATE INDEX "cart_events_cart_id_created_at_idx" ON "public"."cart_events" USING "btree" ("cart_id", "created_at");



CREATE INDEX "cart_events_tenant_recent_idx" ON "public"."cart_events" USING "btree" ("tenant_id", "created_at" DESC);



CREATE INDEX "cart_events_type_created_idx" ON "public"."cart_events" USING "btree" ("event_type", "created_at" DESC);



CREATE INDEX "compliance_enforcement_log_blocked_idx" ON "public"."compliance_enforcement_log" USING "btree" ("decorator", "evaluated_at" DESC) WHERE ("outcome" = 'blocked'::"text");



CREATE INDEX "compliance_enforcement_log_evaluated_at_idx" ON "public"."compliance_enforcement_log" USING "btree" ("evaluated_at" DESC);



CREATE INDEX "compliance_enforcement_log_tenant_dec_idx" ON "public"."compliance_enforcement_log" USING "btree" ("tenant_id", "decorator", "evaluated_at" DESC) WHERE ("tenant_id" IS NOT NULL);



CREATE INDEX "contacts_consent_idx" ON "public"."contacts" USING "btree" ("tenant_id", "consent_given");



CREATE INDEX "contacts_consent_revoked_idx" ON "public"."contacts" USING "btree" ("tenant_id", "consent_revoked_at");



CREATE INDEX "conversation_carts_abandoned_pending_idx" ON "public"."conversation_carts" USING "btree" ("tenant_id", "updated_at") WHERE (("abandoned_reminder_sent_at" IS NULL) AND ("status" = ANY (ARRAY['open'::"text", 'abandoned'::"text"])));



CREATE INDEX "conversation_notes_author_idx" ON "public"."conversation_notes" USING "btree" ("author_user_id", "created_at" DESC) WHERE ("deleted_at" IS NULL);



CREATE INDEX "conversation_notes_conv_idx" ON "public"."conversation_notes" USING "btree" ("conversation_id", "is_pinned" DESC, "created_at" DESC) WHERE ("deleted_at" IS NULL);



CREATE INDEX "conversations_tenant_channel_idx" ON "public"."conversations" USING "btree" ("tenant_id", "channel");



CREATE UNIQUE INDEX "conversations_tenant_phone_channel_uniq" ON "public"."conversations" USING "btree" ("tenant_id", "customer_phone", "channel");



COMMENT ON INDEX "public"."conversations_tenant_phone_channel_uniq" IS 'Impide conversaciones duplicadas para el mismo (tenant, teléfono, canal). Cierra la carrera del read-then-insert del connector cuando el cliente manda varios mensajes seguidos, que partía carrito/FSM/escalación en silencio.';



CREATE INDEX "credential_access_log_accessed_at_idx" ON "public"."credential_access_log" USING "btree" ("accessed_at" DESC);



CREATE INDEX "credential_access_log_service_idx" ON "public"."credential_access_log" USING "btree" ("accessed_by_service", "accessed_at" DESC);



CREATE INDEX "credential_access_log_tenant_provider_idx" ON "public"."credential_access_log" USING "btree" ("tenant_id", "provider", "credential_name", "accessed_at" DESC);



CREATE INDEX "idx_agentic_shadow_conversation" ON "public"."agentic_shadow_log" USING "btree" ("conversation_id", "created_at" DESC);



CREATE INDEX "idx_agentic_shadow_finish_reason" ON "public"."agentic_shadow_log" USING "btree" ("finish_reason") WHERE ("finish_reason" IS NOT NULL);



CREATE INDEX "idx_agentic_shadow_mode_created" ON "public"."agentic_shadow_log" USING "btree" ("mode", "created_at" DESC);



CREATE INDEX "idx_agentic_shadow_tenant_created" ON "public"."agentic_shadow_log" USING "btree" ("tenant_id", "created_at" DESC);



CREATE INDEX "idx_agentic_shadow_total_tokens" ON "public"."agentic_shadow_log" USING "btree" ("tenant_id", "created_at" DESC) WHERE ("total_tokens" IS NOT NULL);



CREATE INDEX "idx_api_security_events_tenant_created" ON "public"."api_security_events" USING "btree" ("tenant_id", "created_at" DESC);



CREATE INDEX "idx_api_security_events_tenant_endpoint" ON "public"."api_security_events" USING "btree" ("tenant_id", "endpoint", "status_code", "created_at" DESC);



CREATE INDEX "idx_api_security_events_type" ON "public"."api_security_events" USING "btree" ("event_type", "created_at" DESC);



CREATE INDEX "idx_audit_log_created" ON "public"."audit_log" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_audit_log_entity" ON "public"."audit_log" USING "btree" ("tenant_id", "entity_type");



CREATE INDEX "idx_audit_log_tenant" ON "public"."audit_log" USING "btree" ("tenant_id");



CREATE INDEX "idx_audit_log_tenant_created" ON "public"."audit_log" USING "btree" ("tenant_id", "created_at" DESC);



CREATE INDEX "idx_audit_log_user" ON "public"."audit_log" USING "btree" ("user_id");



CREATE INDEX "idx_bot_source_log_conversation" ON "public"."bot_source_log" USING "btree" ("conversation_id", "created_at" DESC);



CREATE INDEX "idx_bot_source_log_tenant_created" ON "public"."bot_source_log" USING "btree" ("tenant_id", "created_at" DESC);



CREATE INDEX "idx_cart_items_cart" ON "public"."conversation_cart_items" USING "btree" ("cart_id");



CREATE INDEX "idx_cart_items_tenant" ON "public"."conversation_cart_items" USING "btree" ("tenant_id");



CREATE INDEX "idx_claims_order_id" ON "public"."claims" USING "btree" ("order_id");



CREATE INDEX "idx_claims_status" ON "public"."claims" USING "btree" ("status");



CREATE INDEX "idx_claims_tenant_id" ON "public"."claims" USING "btree" ("tenant_id");



CREATE INDEX "idx_consent_audit_log_contact" ON "public"."consent_audit_log" USING "btree" ("contact_id", "occurred_at" DESC) WHERE ("contact_id" IS NOT NULL);



CREATE INDEX "idx_consent_audit_log_event" ON "public"."consent_audit_log" USING "btree" ("event", "occurred_at" DESC);



CREATE INDEX "idx_consent_audit_log_phone_hash" ON "public"."consent_audit_log" USING "btree" ("phone_hash") WHERE ("phone_hash" IS NOT NULL);



CREATE INDEX "idx_consent_audit_log_tenant" ON "public"."consent_audit_log" USING "btree" ("tenant_id", "occurred_at" DESC);



CREATE INDEX "idx_contacts_consent_comercial" ON "public"."contacts" USING "btree" ("tenant_id") WHERE (("consent_comercial_at" IS NOT NULL) AND ("consent_comercial_revoked_at" IS NULL));



CREATE INDEX "idx_contacts_deleted_at" ON "public"."contacts" USING "btree" ("tenant_id", "deleted_at") WHERE ("deleted_at" IS NOT NULL);



CREATE INDEX "idx_contacts_document_number_hash" ON "public"."contacts" USING "btree" ("tenant_id", "document_number_hash") WHERE ("document_number_hash" IS NOT NULL);



CREATE INDEX "idx_contacts_email" ON "public"."contacts" USING "btree" ("tenant_id", "email") WHERE ("email" IS NOT NULL);



CREATE INDEX "idx_contacts_phone" ON "public"."contacts" USING "btree" ("tenant_id", "phone");



CREATE INDEX "idx_contacts_tenant" ON "public"."contacts" USING "btree" ("tenant_id");



CREATE INDEX "idx_contacts_tenant_document" ON "public"."contacts" USING "btree" ("tenant_id", "document_type", "document_number") WHERE ("document_number" IS NOT NULL);



CREATE INDEX "idx_conversation_carts_contact" ON "public"."conversation_carts" USING "btree" ("tenant_id", "contact_id", "status");



CREATE INDEX "idx_conversation_carts_coupon" ON "public"."conversation_carts" USING "btree" ("coupon_id") WHERE ("coupon_id" IS NOT NULL);



CREATE INDEX "idx_conversation_carts_open_ttl" ON "public"."conversation_carts" USING "btree" ("last_activity_at") WHERE ("status" = 'open'::"text");



CREATE INDEX "idx_conversation_carts_tenant" ON "public"."conversation_carts" USING "btree" ("tenant_id");



CREATE INDEX "idx_conversation_reads_tenant_user" ON "public"."conversation_reads" USING "btree" ("tenant_id", "user_id");



CREATE INDEX "idx_conversations_agentic_state" ON "public"."conversations" USING "btree" ("tenant_id", "agentic_state") WHERE ("agentic_state" IS NOT NULL);



CREATE INDEX "idx_conversations_human_takeover_at" ON "public"."conversations" USING "btree" ("human_takeover_at") WHERE ("status" = 'human_takeover'::"text");



CREATE INDEX "idx_conversations_tenant_active_last_interaction" ON "public"."conversations" USING "btree" ("tenant_id", "last_interaction_at" DESC) WHERE ("archived_at" IS NULL);



CREATE INDEX "idx_conversations_tenant_last_interaction" ON "public"."conversations" USING "btree" ("tenant_id", "last_interaction_at" DESC);



CREATE INDEX "idx_conversations_tenant_phone" ON "public"."conversations" USING "btree" ("tenant_id", "customer_phone");



CREATE INDEX "idx_coupon_redemptions_cart" ON "public"."coupon_redemptions" USING "btree" ("cart_id", "status");



CREATE INDEX "idx_coupon_redemptions_contact" ON "public"."coupon_redemptions" USING "btree" ("contact_id") WHERE ("contact_id" IS NOT NULL);



CREATE INDEX "idx_coupon_redemptions_coupon" ON "public"."coupon_redemptions" USING "btree" ("coupon_id", "status");



CREATE INDEX "idx_coupon_redemptions_order" ON "public"."coupon_redemptions" USING "btree" ("order_id") WHERE ("order_id" IS NOT NULL);



CREATE INDEX "idx_coupon_redemptions_tenant" ON "public"."coupon_redemptions" USING "btree" ("tenant_id");



CREATE INDEX "idx_coupons_tenant_active" ON "public"."coupons" USING "btree" ("tenant_id", "is_active");



CREATE INDEX "idx_email_events_email_id" ON "public"."email_events" USING "btree" ("email_id") WHERE ("email_id" IS NOT NULL);



CREATE INDEX "idx_email_events_recipient_occurred" ON "public"."email_events" USING "btree" ("recipient", "occurred_at" DESC);



CREATE INDEX "idx_email_events_tenant_received" ON "public"."email_events" USING "btree" ("tenant_id", "received_at" DESC);



CREATE INDEX "idx_expenses_active_tenant_date" ON "public"."expenses" USING "btree" ("tenant_id", "expense_date" DESC) WHERE ("reversed_at" IS NULL);



CREATE INDEX "idx_expenses_tenant_date" ON "public"."expenses" USING "btree" ("tenant_id", "expense_date" DESC);



CREATE INDEX "idx_idempotency_keys_expires_at" ON "public"."idempotency_keys" USING "btree" ("expires_at");



CREATE INDEX "idx_idempotency_keys_tenant_created" ON "public"."idempotency_keys" USING "btree" ("tenant_id", "created_at" DESC);



CREATE INDEX "idx_integration_oauth_states_lookup" ON "public"."integration_oauth_states" USING "btree" ("provider", "tenant_id", "expires_at" DESC);



CREATE INDEX "idx_integration_oauth_states_unconsumed" ON "public"."integration_oauth_states" USING "btree" ("provider", "consumed_at", "expires_at" DESC) WHERE ("consumed_at" IS NULL);



CREATE INDEX "idx_kb_documents_active" ON "public"."kb_documents" USING "btree" ("tenant_id", "is_active");



CREATE INDEX "idx_kb_documents_tenant" ON "public"."kb_documents" USING "btree" ("tenant_id");



CREATE INDEX "idx_meli_webhook_dedup_expires_at" ON "public"."meli_webhook_dedup" USING "btree" ("expires_at");



CREATE INDEX "idx_messages_conversation_created" ON "public"."messages" USING "btree" ("conversation_id", "created_at" DESC);



CREATE INDEX "idx_messages_inbound_pending" ON "public"."messages" USING "btree" ("tenant_id", "created_at") WHERE (("direction" = 'inbound'::"text") AND ("processing_status" = ANY (ARRAY['pending'::"text", 'processing'::"text"])));



CREATE INDEX "idx_messages_meta_message_id" ON "public"."messages" USING "btree" ("meta_message_id") WHERE ("meta_message_id" IS NOT NULL);



CREATE INDEX "idx_messages_tenant_created" ON "public"."messages" USING "btree" ("tenant_id", "created_at");



CREATE INDEX "idx_order_cancellations_order" ON "public"."order_cancellations" USING "btree" ("order_id");



CREATE INDEX "idx_order_cancellations_refund_pending" ON "public"."order_cancellations" USING "btree" ("tenant_id", "refund_status") WHERE ("refund_status" = 'pending_manual'::"text");



CREATE INDEX "idx_order_cancellations_status" ON "public"."order_cancellations" USING "btree" ("tenant_id", "status") WHERE ("status" = ANY (ARRAY['pending'::"public"."order_cancellation_status", 'partial_failure'::"public"."order_cancellation_status"]));



CREATE INDEX "idx_order_cancellations_tenant" ON "public"."order_cancellations" USING "btree" ("tenant_id", "created_at" DESC);



CREATE INDEX "idx_order_items_order" ON "public"."order_items" USING "btree" ("order_id");



CREATE INDEX "idx_order_receipts_ack_pendiente" ON "public"."order_receipts" USING "btree" ("tenant_id", "issued_at") WHERE (("ack_sent_at" IS NULL) AND ("voided_at" IS NULL));



CREATE INDEX "idx_order_receipts_anulados" ON "public"."order_receipts" USING "btree" ("tenant_id", "voided_at") WHERE ("voided_at" IS NOT NULL);



CREATE INDEX "idx_order_receipts_email_pendiente" ON "public"."order_receipts" USING "btree" ("tenant_id", "issued_at") WHERE (("email_sent_at" IS NULL) AND ("email_skipped_reason" IS NULL) AND ("voided_at" IS NULL));



CREATE INDEX "idx_order_receipts_tenant_emitido" ON "public"."order_receipts" USING "btree" ("tenant_id", "issued_at" DESC);



CREATE UNIQUE INDEX "idx_order_tracking_external" ON "public"."order_tracking" USING "btree" ("tenant_id", "provider", "external_id") WHERE ("external_id" IS NOT NULL);



CREATE INDEX "idx_order_tracking_order" ON "public"."order_tracking" USING "btree" ("order_id");



CREATE INDEX "idx_order_tracking_tenant" ON "public"."order_tracking" USING "btree" ("tenant_id");



CREATE INDEX "idx_orders_cancelled" ON "public"."orders" USING "btree" ("tenant_id", "cancelled_at" DESC) WHERE ("cancelled_at" IS NOT NULL);



CREATE INDEX "idx_orders_contact" ON "public"."orders" USING "btree" ("contact_id");



CREATE INDEX "idx_orders_conversation_tenant" ON "public"."orders" USING "btree" ("conversation_id", "tenant_id") WHERE ("conversation_id" IS NOT NULL);



CREATE INDEX "idx_orders_evidencia" ON "public"."orders" USING "btree" ("conversation_id", "tenant_id") WHERE (("conversation_id" IS NOT NULL) AND ("status" = ANY (ARRAY['confirmed'::"text", 'processing'::"text", 'shipped'::"text", 'delivered'::"text"])));



CREATE INDEX "idx_orders_paid_created" ON "public"."orders" USING "btree" ("tenant_id", "created_at") WHERE ("status" = ANY (ARRAY['confirmed'::"text", 'processing'::"text", 'shipped'::"text", 'delivered'::"text"]));



CREATE INDEX "idx_orders_pending_payment_created" ON "public"."orders" USING "btree" ("created_at") WHERE ("status" = 'pending_payment'::"text");



CREATE INDEX "idx_orders_sin_aceptacion" ON "public"."orders" USING "btree" ("tenant_id", "created_at") WHERE ("accepted_at" IS NULL);



CREATE INDEX "idx_orders_status" ON "public"."orders" USING "btree" ("tenant_id", "status");



CREATE INDEX "idx_orders_tenant" ON "public"."orders" USING "btree" ("tenant_id");



CREATE INDEX "idx_payments_status" ON "public"."payments" USING "btree" ("tenant_id", "status");



CREATE INDEX "idx_payments_tenant_order" ON "public"."payments" USING "btree" ("tenant_id", "order_id");



CREATE INDEX "idx_payments_wompi_link" ON "public"."payments" USING "btree" ("wompi_link_id") WHERE ("wompi_link_id" IS NOT NULL);



CREATE INDEX "idx_payments_wompi_txn" ON "public"."payments" USING "btree" ("wompi_txn_id") WHERE ("wompi_txn_id" IS NOT NULL);



CREATE INDEX "idx_pii_access_log_actor" ON "public"."pii_access_log" USING "btree" ("accessed_by", "accessed_at" DESC);



CREATE INDEX "idx_pii_access_log_contact" ON "public"."pii_access_log" USING "btree" ("contact_id", "accessed_at" DESC);



CREATE INDEX "idx_pii_access_log_tenant" ON "public"."pii_access_log" USING "btree" ("tenant_id", "accessed_at" DESC);



CREATE INDEX "idx_plan_capabilities_plan_code" ON "public"."plan_capabilities" USING "btree" ("plan_code");



CREATE INDEX "idx_prod_attr_defs_tenant_cat" ON "public"."product_attribute_definitions" USING "btree" ("tenant_id", "product_category_id");



CREATE INDEX "idx_product_categories_parent" ON "public"."product_categories" USING "btree" ("tenant_id", "parent_id");



CREATE INDEX "idx_product_categories_tenant" ON "public"."product_categories" USING "btree" ("tenant_id", "sort_order");



CREATE INDEX "idx_product_variations_product" ON "public"."product_variations" USING "btree" ("product_id");



CREATE INDEX "idx_products_tenant_category_active" ON "public"."products" USING "btree" ("tenant_id", "category_id") WHERE ("status" = 'active'::"text");



CREATE INDEX "idx_retention_policies_tenant" ON "public"."retention_policies" USING "btree" ("tenant_id", "entity") WHERE ("enabled" = true);



CREATE INDEX "idx_reversal_constancia_sin_entregar" ON "public"."payment_reversal_requests" USING "btree" ("tenant_id", "constancia_emitida_at") WHERE (("constancia_emitida_at" IS NOT NULL) AND ("constancia_entregada_at" IS NULL));



CREATE INDEX "idx_reversal_doble_pago" ON "public"."payment_reversal_requests" USING "btree" ("tenant_id") WHERE ("doble_pago_detectado_at" IS NOT NULL);



CREATE INDEX "idx_reversal_order" ON "public"."payment_reversal_requests" USING "btree" ("order_id");



CREATE INDEX "idx_reversal_tenant_estado" ON "public"."payment_reversal_requests" USING "btree" ("tenant_id", "estado", "presentada_at" DESC);



CREATE INDEX "idx_rma_requests_deadline" ON "public"."rma_requests" USING "btree" ("refund_legal_deadline") WHERE ("status" <> ALL (ARRAY['refund_completed'::"public"."rma_status_enum", 'rejected_product_damaged'::"public"."rma_status_enum", 'rejected_out_of_window'::"public"."rma_status_enum", 'rejected_excluded_product'::"public"."rma_status_enum", 'cancelled_by_customer'::"public"."rma_status_enum"]));



CREATE INDEX "idx_rma_requests_order" ON "public"."rma_requests" USING "btree" ("order_id");



CREATE INDEX "idx_rma_requests_tenant_status" ON "public"."rma_requests" USING "btree" ("tenant_id", "status");



CREATE INDEX "idx_shipments_order" ON "public"."shipments" USING "btree" ("order_id");



CREATE INDEX "idx_shipments_status" ON "public"."shipments" USING "btree" ("tenant_id", "status");



CREATE INDEX "idx_shipments_tenant" ON "public"."shipments" USING "btree" ("tenant_id");



CREATE INDEX "idx_stock_movements_created" ON "public"."stock_movements" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_stock_movements_order" ON "public"."stock_movements" USING "btree" ("order_id") WHERE ("order_id" IS NOT NULL);



CREATE INDEX "idx_stock_movements_tenant" ON "public"."stock_movements" USING "btree" ("tenant_id");



CREATE INDEX "idx_stock_movements_variation" ON "public"."stock_movements" USING "btree" ("variation_id");



CREATE INDEX "idx_stock_res_active" ON "public"."stock_reservations" USING "btree" ("variation_id", "expires_at") WHERE ("status" = 'active'::"public"."stock_reservation_status");



CREATE INDEX "idx_stock_res_cart" ON "public"."stock_reservations" USING "btree" ("cart_id") WHERE ("cart_id" IS NOT NULL);



CREATE INDEX "idx_stock_res_expired_sweep" ON "public"."stock_reservations" USING "btree" ("expires_at") WHERE ("status" = 'active'::"public"."stock_reservation_status");



CREATE INDEX "idx_stock_res_order" ON "public"."stock_reservations" USING "btree" ("order_id") WHERE ("order_id" IS NOT NULL);



CREATE INDEX "idx_stock_res_tenant" ON "public"."stock_reservations" USING "btree" ("tenant_id");



CREATE INDEX "idx_suppliers_tenant_active" ON "public"."suppliers" USING "btree" ("tenant_id") WHERE "is_active";



CREATE INDEX "idx_telegram_alert_messages_conv_open" ON "public"."telegram_alert_messages" USING "btree" ("conversation_id") WHERE ("resolved_at" IS NULL);



CREATE INDEX "idx_tenant_integrations_tenant" ON "public"."tenant_integrations" USING "btree" ("tenant_id");



CREATE INDEX "idx_tenant_legal_acceptance_tenant" ON "public"."tenant_legal_acceptance" USING "btree" ("tenant_id", "document_id", "accepted_at" DESC);



CREATE INDEX "idx_tenant_subscriptions_plan_code" ON "public"."tenant_subscriptions" USING "btree" ("plan_code", "status");



CREATE INDEX "idx_tenant_usage_counters_lookup" ON "public"."tenant_usage_counters" USING "btree" ("tenant_id", "capability_key", "period_start" DESC);



CREATE INDEX "idx_tenant_usage_events_lookup" ON "public"."tenant_usage_events" USING "btree" ("tenant_id", "capability_key", "created_at" DESC);



CREATE INDEX "idx_tenant_users_tenant_id" ON "public"."tenant_users" USING "btree" ("tenant_id");



CREATE INDEX "idx_wa_inbox_processed" ON "public"."whatsapp_webhook_inbox" USING "btree" ("processed_at") WHERE ("processed_at" IS NOT NULL);



CREATE INDEX "idx_wa_inbox_unprocessed" ON "public"."whatsapp_webhook_inbox" USING "btree" ("received_at") WHERE ("processed_at" IS NULL);



CREATE INDEX "idx_whatsapp_templates_meta_id" ON "public"."whatsapp_templates" USING "btree" ("meta_template_id") WHERE ("meta_template_id" IS NOT NULL);



CREATE INDEX "idx_whatsapp_templates_status" ON "public"."whatsapp_templates" USING "btree" ("tenant_id", "status");



CREATE INDEX "idx_whatsapp_templates_tenant" ON "public"."whatsapp_templates" USING "btree" ("tenant_id");



CREATE INDEX "idx_whatsapp_templates_waba" ON "public"."whatsapp_templates" USING "btree" ("waba_id");



CREATE INDEX "idx_wompi_events_tenant_received" ON "public"."wompi_events_seen" USING "btree" ("tenant_id", "received_at" DESC);



CREATE INDEX "idx_wompi_events_transaction" ON "public"."wompi_events_seen" USING "btree" ("transaction_id") WHERE ("transaction_id" IS NOT NULL);



CREATE INDEX "idx_wompi_inbox_processed" ON "public"."wompi_webhook_inbox" USING "btree" ("processed_at") WHERE ("processed_at" IS NOT NULL);



CREATE INDEX "idx_wompi_inbox_unprocessed" ON "public"."wompi_webhook_inbox" USING "btree" ("received_at") WHERE ("processed_at" IS NULL);



CREATE INDEX "kb_documents_embedding_model_version_idx" ON "public"."kb_documents" USING "btree" ("tenant_id", "embedding_model_version") WHERE ("embedding" IS NOT NULL);



CREATE INDEX "mfa_recovery_codes_user_idx" ON "public"."mfa_recovery_codes" USING "btree" ("user_id", "used_at");



CREATE INDEX "orders_cod_pending_idx" ON "public"."orders" USING "btree" ("tenant_id", "created_at" DESC) WHERE ("payment_method" = 'cod'::"text");



CREATE INDEX "orders_tenant_external_order_idx" ON "public"."orders" USING "btree" ("tenant_id", "external_order_id") WHERE ("external_order_id" IS NOT NULL);



CREATE UNIQUE INDEX "orders_tenant_source_external_uq" ON "public"."orders" USING "btree" ("tenant_id", "source", "external_order_id") WHERE (("source" IS NOT NULL) AND ("external_order_id" IS NOT NULL));



CREATE INDEX "outbound_idempotency_cache_expires_idx" ON "public"."outbound_idempotency_cache" USING "btree" ("expires_at");



CREATE INDEX "outbound_idempotency_cache_lookup_idx" ON "public"."outbound_idempotency_cache" USING "btree" ("provider", "tenant_id", "request_hash");



CREATE INDEX "products_retracto_excluded_idx" ON "public"."products" USING "btree" ("tenant_id", "retracto_excluded") WHERE ("retracto_excluded" = true);



CREATE INDEX "rate_limit_windows_expires_idx" ON "public"."rate_limit_windows" USING "btree" ("expires_at");



CREATE INDEX "review_queue_conversation_idx" ON "public"."review_queue" USING "btree" ("conversation_id", "created_at" DESC);



CREATE INDEX "review_queue_tenant_open_idx" ON "public"."review_queue" USING "btree" ("tenant_id", "resolved", "priority" DESC, "created_at") WHERE ("resolved" = false);



CREATE INDEX "shipment_tracking_events_order_idx" ON "public"."shipment_tracking_events" USING "btree" ("order_id", "received_at" DESC) WHERE ("order_id" IS NOT NULL);



CREATE INDEX "shipment_tracking_events_shipment_idx" ON "public"."shipment_tracking_events" USING "btree" ("shipment_id", "received_at" DESC) WHERE ("shipment_id" IS NOT NULL);



CREATE INDEX "shipment_tracking_events_tenant_idx" ON "public"."shipment_tracking_events" USING "btree" ("tenant_id", "received_at" DESC);



CREATE UNIQUE INDEX "shipments_one_active_guide_per_order" ON "public"."shipments" USING "btree" ("tenant_id", "order_id") WHERE (("order_id" IS NOT NULL) AND ("status" = ANY (ARRAY['generating'::"text", 'labeled'::"text", 'simulated'::"text"])));



COMMENT ON INDEX "public"."shipments_one_active_guide_per_order" IS 'BLOQUE B item 5 — idempotencia guía: a lo sumo 1 guía activa/generada por (tenant,order). Soporta claim-before-bill (INSERT generating antes de facturar Aveonline). pending_generation queda fuera → permite retry.';



CREATE INDEX "tenant_carriers_lookup_idx" ON "public"."tenant_carriers" USING "btree" ("tenant_id", "provider", "enabled");



CREATE INDEX "tenant_carriers_priority_idx" ON "public"."tenant_carriers" USING "btree" ("tenant_id", "provider", "priority");



CREATE INDEX "tenant_offboarding_log_event_idx" ON "public"."tenant_offboarding_log" USING "btree" ("event", "occurred_at" DESC);



CREATE INDEX "tenant_offboarding_log_tenant_idx" ON "public"."tenant_offboarding_log" USING "btree" ("tenant_id", "occurred_at" DESC);



CREATE INDEX "tenant_payment_methods_lookup_idx" ON "public"."tenant_payment_methods" USING "btree" ("tenant_id", "method", "enabled");



CREATE INDEX "tenant_provider_capabilities_capability_idx" ON "public"."tenant_provider_capabilities" USING "btree" ("provider", "capability", "enabled");



CREATE INDEX "tenant_provider_capabilities_lookup_idx" ON "public"."tenant_provider_capabilities" USING "btree" ("tenant_id", "provider", "enabled");



CREATE INDEX "tenant_provider_health_status_idx" ON "public"."tenant_provider_health" USING "btree" ("status", "observed_at" DESC) WHERE ("status" = ANY (ARRAY['warning'::"text", 'critical'::"text"]));



CREATE INDEX "tenant_provider_health_tenant_idx" ON "public"."tenant_provider_health" USING "btree" ("tenant_id", "observed_at" DESC);



CREATE INDEX "tenant_provider_identity_provider_idx" ON "public"."tenant_provider_identity" USING "btree" ("provider", "verified_at");



CREATE INDEX "tenant_provider_identity_tenant_idx" ON "public"."tenant_provider_identity" USING "btree" ("tenant_id", "provider");



CREATE INDEX "tenant_shipping_provider_config_active_idx" ON "public"."tenant_shipping_provider_config" USING "btree" ("active_provider");



CREATE INDEX "tenant_webhook_secrets_expires_idx" ON "public"."tenant_webhook_secrets" USING "btree" ("expires_at");



CREATE INDEX "tenant_webhook_secrets_grace_idx" ON "public"."tenant_webhook_secrets" USING "btree" ("grace_period_until") WHERE ("grace_period_until" IS NOT NULL);



CREATE INDEX "tenant_webhook_secrets_tenant_idx" ON "public"."tenant_webhook_secrets" USING "btree" ("tenant_id");



CREATE INDEX "tenants_deletion_scheduled_idx" ON "public"."tenants" USING "btree" ("deletion_scheduled_for") WHERE (("deletion_scheduled_for" IS NOT NULL) AND ("deleted_at" IS NULL));



CREATE UNIQUE INDEX "uniq_conversation_carts_open" ON "public"."conversation_carts" USING "btree" ("conversation_id") WHERE ("status" = 'open'::"text");



CREATE UNIQUE INDEX "uniq_coupon_redemption_cart_applied" ON "public"."coupon_redemptions" USING "btree" ("cart_id") WHERE (("status" = 'applied'::"text") AND ("cart_id" IS NOT NULL));



CREATE UNIQUE INDEX "uniq_coupons_tenant_code" ON "public"."coupons" USING "btree" ("tenant_id", "code");



CREATE UNIQUE INDEX "uniq_tenants_meta_waba_id" ON "public"."tenants" USING "btree" ("meta_waba_id") WHERE (("meta_waba_id" IS NOT NULL) AND ("meta_waba_id" <> ''::"text"));



CREATE UNIQUE INDEX "uq_orders_accepted_message" ON "public"."orders" USING "btree" ("tenant_id", "accepted_message_id") WHERE ("accepted_message_id" IS NOT NULL);



CREATE UNIQUE INDEX "uq_orders_one_pending_payment_per_conversation" ON "public"."orders" USING "btree" ("tenant_id", "conversation_id") WHERE ("status" = 'pending_payment'::"text");



COMMENT ON INDEX "public"."uq_orders_one_pending_payment_per_conversation" IS 'B1: anti doble-cobro. Una conversación = una orden pending_payment activa. El insert perdedor (23505) adopta la orden ganadora (services/api/routers/orders.py create_order).';



CREATE UNIQUE INDEX "uq_payments_wompi_txn_id" ON "public"."payments" USING "btree" ("wompi_txn_id") WHERE ("wompi_txn_id" IS NOT NULL);



CREATE UNIQUE INDEX "uq_purchase_orders_tenant_po_number" ON "public"."purchase_orders" USING "btree" ("tenant_id", "po_number") WHERE ("po_number" IS NOT NULL);



CREATE UNIQUE INDEX "uq_stock_movements_order_variation_reason" ON "public"."stock_movements" USING "btree" ("order_id", "variation_id", "reason") WHERE ("order_id" IS NOT NULL);



CREATE UNIQUE INDEX "uq_telegram_alert_messages_msg" ON "public"."telegram_alert_messages" USING "btree" ("chat_id", "message_id");



CREATE UNIQUE INDEX "uq_tenant_legal_acceptance_version" ON "public"."tenant_legal_acceptance" USING "btree" ("tenant_id", "document_id", "document_version");



CREATE INDEX "webhook_events_seen_cleanup_idx" ON "public"."webhook_events_seen" USING "btree" ("received_at") WHERE ("processed_at" IS NOT NULL);



CREATE INDEX "webhook_events_seen_integration_received_idx" ON "public"."webhook_events_seen" USING "btree" ("integration", "received_at" DESC);



CREATE INDEX "webhook_events_seen_tenant_received_idx" ON "public"."webhook_events_seen" USING "btree" ("tenant_id", "received_at" DESC) WHERE ("tenant_id" IS NOT NULL);



CREATE OR REPLACE TRIGGER "ai_insights_updated_at_trg" BEFORE UPDATE ON "public"."ai_insights" FOR EACH ROW EXECUTE FUNCTION "public"."ai_insights_set_updated_at"();



CREATE OR REPLACE TRIGGER "aveonline_carrier_capabilities_updated_at" BEFORE UPDATE ON "public"."aveonline_carrier_capabilities" FOR EACH ROW EXECUTE FUNCTION "public"."tg_aveonline_carrier_capabilities_updated_at"();



CREATE OR REPLACE TRIGGER "consent_audit_log_no_delete" BEFORE DELETE ON "public"."consent_audit_log" FOR EACH ROW EXECUTE FUNCTION "public"."consent_audit_log_block_modify"();



CREATE OR REPLACE TRIGGER "consent_audit_log_no_update" BEFORE UPDATE ON "public"."consent_audit_log" FOR EACH ROW EXECUTE FUNCTION "public"."consent_audit_log_block_modify"();



CREATE OR REPLACE TRIGGER "conversations_human_takeover_queue_trigger" AFTER UPDATE OF "status" ON "public"."conversations" FOR EACH ROW EXECUTE FUNCTION "public"."enqueue_human_takeover_notification"();



CREATE OR REPLACE TRIGGER "conversations_stamp_human_takeover_at" BEFORE UPDATE OF "status" ON "public"."conversations" FOR EACH ROW EXECUTE FUNCTION "public"."stamp_human_takeover_at"();



CREATE OR REPLACE TRIGGER "coupons_updated_at" BEFORE UPDATE ON "public"."coupons" FOR EACH ROW EXECUTE FUNCTION "public"."tg_coupons_set_updated_at"();



CREATE OR REPLACE TRIGGER "kb_documents_updated_at" BEFORE UPDATE ON "public"."kb_documents" FOR EACH ROW EXECUTE FUNCTION "public"."update_kb_updated_at"();



CREATE OR REPLACE TRIGGER "orders_void_receipt_on_cancel" AFTER UPDATE OF "status" ON "public"."orders" FOR EACH ROW EXECUTE FUNCTION "public"."trg_void_receipt_on_cancel"();



CREATE OR REPLACE TRIGGER "pii_access_log_no_delete" BEFORE DELETE ON "public"."pii_access_log" FOR EACH ROW EXECUTE FUNCTION "public"."pii_access_log_block_modify"();



CREATE OR REPLACE TRIGGER "pii_access_log_no_update" BEFORE UPDATE ON "public"."pii_access_log" FOR EACH ROW EXECUTE FUNCTION "public"."pii_access_log_block_modify"();



CREATE OR REPLACE TRIGGER "release_coupon_on_cart_terminal" AFTER UPDATE OF "status" ON "public"."conversation_carts" FOR EACH ROW EXECUTE FUNCTION "public"."tg_release_coupon_on_cart_terminal"();



CREATE OR REPLACE TRIGGER "set_claims_updated_at" BEFORE UPDATE ON "public"."claims" FOR EACH ROW EXECUTE FUNCTION "public"."update_claims_updated_at"();



CREATE OR REPLACE TRIGGER "set_idempotency_keys_updated_at" BEFORE UPDATE ON "public"."idempotency_keys" FOR EACH ROW EXECUTE FUNCTION "public"."update_idempotency_updated_at"();



CREATE OR REPLACE TRIGGER "set_marketplace_listings_updated_at" BEFORE UPDATE ON "public"."marketplace_listings" FOR EACH ROW EXECUTE FUNCTION "public"."update_marketplace_updated_at"();



CREATE OR REPLACE TRIGGER "set_order_tracking_updated_at" BEFORE UPDATE ON "public"."order_tracking" FOR EACH ROW EXECUTE FUNCTION "public"."update_order_tracking_updated_at"();



CREATE OR REPLACE TRIGGER "tenant_carriers_updated_at_trg" BEFORE UPDATE ON "public"."tenant_carriers" FOR EACH ROW EXECUTE FUNCTION "public"."tenant_carriers_set_updated_at"();



CREATE OR REPLACE TRIGGER "tenant_payment_methods_updated_at" BEFORE UPDATE ON "public"."tenant_payment_methods" FOR EACH ROW EXECUTE FUNCTION "public"."tg_tenant_payment_methods_updated_at"();



CREATE OR REPLACE TRIGGER "tenant_provider_capabilities_updated_at_trg" BEFORE UPDATE ON "public"."tenant_provider_capabilities" FOR EACH ROW EXECUTE FUNCTION "public"."tenant_provider_capabilities_set_updated_at"();



CREATE OR REPLACE TRIGGER "tenant_provider_identity_updated_at_trg" BEFORE UPDATE ON "public"."tenant_provider_identity" FOR EACH ROW EXECUTE FUNCTION "public"."tenant_provider_identity_set_updated_at"();



CREATE OR REPLACE TRIGGER "tenant_webhook_secrets_updated_at_trg" BEFORE UPDATE ON "public"."tenant_webhook_secrets" FOR EACH ROW EXECUTE FUNCTION "public"."tenant_webhook_secrets_set_updated_at"();



CREATE OR REPLACE TRIGGER "trg_assign_purchase_order_number" BEFORE INSERT ON "public"."purchase_orders" FOR EACH ROW EXECUTE FUNCTION "public"."assign_purchase_order_number"();



CREATE OR REPLACE TRIGGER "trg_audit_log_append_only" BEFORE DELETE OR UPDATE ON "public"."audit_log" FOR EACH ROW EXECUTE FUNCTION "public"."reject_audit_log_mutation"();



CREATE OR REPLACE TRIGGER "trg_billing_plans_updated_at" BEFORE UPDATE ON "public"."billing_plans" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_block_legal_acceptance_delete" BEFORE DELETE ON "public"."tenant_legal_acceptance" FOR EACH ROW EXECUTE FUNCTION "public"."fn_block_legal_acceptance_modify"();



CREATE OR REPLACE TRIGGER "trg_block_legal_acceptance_update" BEFORE UPDATE ON "public"."tenant_legal_acceptance" FOR EACH ROW EXECUTE FUNCTION "public"."fn_block_legal_acceptance_modify"();



CREATE OR REPLACE TRIGGER "trg_cart_items_updated_at" BEFORE UPDATE ON "public"."conversation_cart_items" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_claim_ticket_number" BEFORE INSERT ON "public"."claims" FOR EACH ROW EXECUTE FUNCTION "public"."set_claim_ticket_number"();



CREATE OR REPLACE TRIGGER "trg_contacts_default_shipping_phone" BEFORE INSERT OR UPDATE OF "phone", "shipping_phone" ON "public"."contacts" FOR EACH ROW EXECUTE FUNCTION "public"."contacts_default_shipping_phone"();



COMMENT ON TRIGGER "trg_contacts_default_shipping_phone" ON "public"."contacts" IS 'Rev. 103 — shipping_phone defaultea a phone (WhatsApp) cuando viene NULL/empty.';



CREATE OR REPLACE TRIGGER "trg_conversation_carts_updated_at" BEFORE UPDATE ON "public"."conversation_carts" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_conversation_notes_updated_at" BEFORE UPDATE ON "public"."conversation_notes" FOR EACH ROW EXECUTE FUNCTION "public"."_touch_conversation_notes_updated_at"();



CREATE OR REPLACE TRIGGER "trg_order_cancellations_updated_at" BEFORE UPDATE ON "public"."order_cancellations" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_plan_capabilities_updated_at" BEFORE UPDATE ON "public"."plan_capabilities" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_reversal_updated_at" BEFORE UPDATE ON "public"."payment_reversal_requests" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_rma_requests_updated_at" BEFORE UPDATE ON "public"."rma_requests" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_seed_tenant_subscription_default" AFTER INSERT ON "public"."tenants" FOR EACH ROW EXECUTE FUNCTION "public"."seed_tenant_subscription_default"();



CREATE OR REPLACE TRIGGER "trg_stock_reservations_updated_at" BEFORE UPDATE ON "public"."stock_reservations" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_sync_conversation_last_interaction" AFTER INSERT ON "public"."messages" FOR EACH ROW EXECUTE FUNCTION "public"."sync_conversation_last_interaction"();



CREATE OR REPLACE TRIGGER "trg_sync_document_derived" BEFORE INSERT OR UPDATE OF "document_number" ON "public"."contacts" FOR EACH ROW EXECUTE FUNCTION "public"."fn_sync_document_derived"();



CREATE OR REPLACE TRIGGER "trg_sync_tenant_stamp" AFTER INSERT OR DELETE OR UPDATE ON "public"."tenant_users" FOR EACH ROW EXECUTE FUNCTION "public"."sync_tenant_stamp_to_auth"();



CREATE OR REPLACE TRIGGER "trg_tenant_cancellation_policy_updated_at" BEFORE UPDATE ON "public"."tenant_cancellation_policy" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_tenant_subscriptions_updated_at" BEFORE UPDATE ON "public"."tenant_subscriptions" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_tenant_usage_counters_updated_at" BEFORE UPDATE ON "public"."tenant_usage_counters" FOR EACH ROW EXECUTE FUNCTION "public"."touch_updated_at"();



CREATE OR REPLACE TRIGGER "trg_whatsapp_templates_updated_at" BEFORE UPDATE ON "public"."whatsapp_templates" FOR EACH ROW EXECUTE FUNCTION "public"."tg_whatsapp_templates_updated_at"();



CREATE OR REPLACE TRIGGER "tspc_set_updated_at" BEFORE UPDATE ON "public"."tenant_shipping_provider_config" FOR EACH ROW EXECUTE FUNCTION "public"."tenant_shipping_provider_config_set_updated_at"();



ALTER TABLE ONLY "public"."agentic_shadow_log"
    ADD CONSTRAINT "agentic_shadow_log_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."agentic_shadow_log"
    ADD CONSTRAINT "agentic_shadow_log_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ai_agents"
    ADD CONSTRAINT "ai_agents_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ai_insights"
    ADD CONSTRAINT "ai_insights_generated_by_fkey" FOREIGN KEY ("generated_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ai_insights"
    ADD CONSTRAINT "ai_insights_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."api_security_events"
    ADD CONSTRAINT "api_security_events_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."audit_log"
    ADD CONSTRAINT "audit_log_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."audit_log"
    ADD CONSTRAINT "audit_log_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."bot_source_log"
    ADD CONSTRAINT "bot_source_log_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."bot_source_log"
    ADD CONSTRAINT "bot_source_log_message_id_fkey" FOREIGN KEY ("message_id") REFERENCES "public"."messages"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."bot_source_log"
    ADD CONSTRAINT "bot_source_log_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."cart_events"
    ADD CONSTRAINT "cart_events_cart_id_fkey" FOREIGN KEY ("cart_id") REFERENCES "public"."conversation_carts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."cart_events"
    ADD CONSTRAINT "cart_events_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."claims"
    ADD CONSTRAINT "claims_customer_id_fkey" FOREIGN KEY ("customer_id") REFERENCES "public"."contacts"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."claims"
    ADD CONSTRAINT "claims_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."claims"
    ADD CONSTRAINT "claims_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."compliance_enforcement_log"
    ADD CONSTRAINT "compliance_enforcement_log_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."consent_audit_log"
    ADD CONSTRAINT "consent_audit_log_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."contacts"
    ADD CONSTRAINT "contacts_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversation_cart_items"
    ADD CONSTRAINT "conversation_cart_items_cart_id_fkey" FOREIGN KEY ("cart_id") REFERENCES "public"."conversation_carts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversation_cart_items"
    ADD CONSTRAINT "conversation_cart_items_product_id_fkey" FOREIGN KEY ("product_id") REFERENCES "public"."products"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."conversation_cart_items"
    ADD CONSTRAINT "conversation_cart_items_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversation_cart_items"
    ADD CONSTRAINT "conversation_cart_items_variation_id_fkey" FOREIGN KEY ("variation_id") REFERENCES "public"."product_variations"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."conversation_carts"
    ADD CONSTRAINT "conversation_carts_contact_id_fkey" FOREIGN KEY ("contact_id") REFERENCES "public"."contacts"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."conversation_carts"
    ADD CONSTRAINT "conversation_carts_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversation_carts"
    ADD CONSTRAINT "conversation_carts_converted_order_id_fkey" FOREIGN KEY ("converted_order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."conversation_carts"
    ADD CONSTRAINT "conversation_carts_coupon_id_fkey" FOREIGN KEY ("coupon_id") REFERENCES "public"."coupons"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."conversation_carts"
    ADD CONSTRAINT "conversation_carts_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversation_notes"
    ADD CONSTRAINT "conversation_notes_author_user_id_fkey" FOREIGN KEY ("author_user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."conversation_notes"
    ADD CONSTRAINT "conversation_notes_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversation_notes"
    ADD CONSTRAINT "conversation_notes_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversation_reads"
    ADD CONSTRAINT "conversation_reads_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coupon_redemptions"
    ADD CONSTRAINT "coupon_redemptions_cart_id_fkey" FOREIGN KEY ("cart_id") REFERENCES "public"."conversation_carts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coupon_redemptions"
    ADD CONSTRAINT "coupon_redemptions_contact_id_fkey" FOREIGN KEY ("contact_id") REFERENCES "public"."contacts"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."coupon_redemptions"
    ADD CONSTRAINT "coupon_redemptions_coupon_id_fkey" FOREIGN KEY ("coupon_id") REFERENCES "public"."coupons"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coupon_redemptions"
    ADD CONSTRAINT "coupon_redemptions_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."coupon_redemptions"
    ADD CONSTRAINT "coupon_redemptions_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coupons"
    ADD CONSTRAINT "coupons_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."coupons"
    ADD CONSTRAINT "coupons_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."credential_access_log"
    ADD CONSTRAINT "credential_access_log_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."email_events"
    ADD CONSTRAINT "email_events_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."expenses"
    ADD CONSTRAINT "expenses_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."idempotency_keys"
    ADD CONSTRAINT "idempotency_keys_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."integration_oauth_states"
    ADD CONSTRAINT "integration_oauth_states_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."kb_documents"
    ADD CONSTRAINT "kb_documents_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."marketplace_listings"
    ADD CONSTRAINT "marketplace_listings_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."marketplace_listings"
    ADD CONSTRAINT "marketplace_listings_variation_id_fkey" FOREIGN KEY ("variation_id") REFERENCES "public"."product_variations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."mfa_recovery_codes"
    ADD CONSTRAINT "mfa_recovery_codes_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."notification_settings"
    ADD CONSTRAINT "notification_settings_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_cancellations"
    ADD CONSTRAINT "order_cancellations_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."order_cancellations"
    ADD CONSTRAINT "order_cancellations_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_cancellations"
    ADD CONSTRAINT "order_cancellations_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_items"
    ADD CONSTRAINT "order_items_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_items"
    ADD CONSTRAINT "order_items_product_id_fkey" FOREIGN KEY ("product_id") REFERENCES "public"."products"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."order_items"
    ADD CONSTRAINT "order_items_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_items"
    ADD CONSTRAINT "order_items_variation_id_fkey" FOREIGN KEY ("variation_id") REFERENCES "public"."product_variations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."order_receipts"
    ADD CONSTRAINT "order_receipts_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_receipts"
    ADD CONSTRAINT "order_receipts_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_tracking"
    ADD CONSTRAINT "order_tracking_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."order_tracking"
    ADD CONSTRAINT "order_tracking_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_cancellation_id_fkey" FOREIGN KEY ("cancellation_id") REFERENCES "public"."order_cancellations"("id");



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_contact_id_fkey" FOREIGN KEY ("contact_id") REFERENCES "public"."contacts"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."outbound_idempotency_cache"
    ADD CONSTRAINT "outbound_idempotency_cache_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."payment_reversal_requests"
    ADD CONSTRAINT "payment_reversal_requests_claim_id_fkey" FOREIGN KEY ("claim_id") REFERENCES "public"."claims"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."payment_reversal_requests"
    ADD CONSTRAINT "payment_reversal_requests_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."payment_reversal_requests"
    ADD CONSTRAINT "payment_reversal_requests_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."payment_reversal_requests"
    ADD CONSTRAINT "payment_reversal_requests_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."payments"
    ADD CONSTRAINT "payments_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."payments"
    ADD CONSTRAINT "payments_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."pii_access_log"
    ADD CONSTRAINT "pii_access_log_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."plan_capabilities"
    ADD CONSTRAINT "plan_capabilities_plan_code_fkey" FOREIGN KEY ("plan_code") REFERENCES "public"."billing_plans"("plan_code") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."platform_categories"
    ADD CONSTRAINT "platform_categories_parent_id_fkey" FOREIGN KEY ("parent_id") REFERENCES "public"."platform_categories"("id");



ALTER TABLE ONLY "public"."product_attribute_definitions"
    ADD CONSTRAINT "product_attribute_definitions_product_category_id_fkey" FOREIGN KEY ("product_category_id") REFERENCES "public"."product_categories"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."product_attribute_definitions"
    ADD CONSTRAINT "product_attribute_definitions_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."product_categories"
    ADD CONSTRAINT "product_categories_parent_id_fkey" FOREIGN KEY ("parent_id") REFERENCES "public"."product_categories"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."product_categories"
    ADD CONSTRAINT "product_categories_platform_category_id_fkey" FOREIGN KEY ("platform_category_id") REFERENCES "public"."platform_categories"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."product_categories"
    ADD CONSTRAINT "product_categories_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."product_variations"
    ADD CONSTRAINT "product_variations_product_id_fkey" FOREIGN KEY ("product_id") REFERENCES "public"."products"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."product_variations"
    ADD CONSTRAINT "product_variations_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."products"
    ADD CONSTRAINT "products_category_id_fkey" FOREIGN KEY ("category_id") REFERENCES "public"."product_categories"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."products"
    ADD CONSTRAINT "products_platform_category_id_fkey" FOREIGN KEY ("platform_category_id") REFERENCES "public"."platform_categories"("id");



ALTER TABLE ONLY "public"."products"
    ADD CONSTRAINT "products_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."provider_health_alert_dedup"
    ADD CONSTRAINT "provider_health_alert_dedup_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."purchase_order_items"
    ADD CONSTRAINT "purchase_order_items_po_id_fkey" FOREIGN KEY ("po_id") REFERENCES "public"."purchase_orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."purchase_order_items"
    ADD CONSTRAINT "purchase_order_items_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."purchase_order_items"
    ADD CONSTRAINT "purchase_order_items_variation_id_fkey" FOREIGN KEY ("variation_id") REFERENCES "public"."product_variations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."purchase_orders"
    ADD CONSTRAINT "purchase_orders_supplier_id_fkey" FOREIGN KEY ("supplier_id") REFERENCES "public"."suppliers"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."purchase_orders"
    ADD CONSTRAINT "purchase_orders_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."retention_policies"
    ADD CONSTRAINT "retention_policies_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."review_queue"
    ADD CONSTRAINT "review_queue_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."review_queue"
    ADD CONSTRAINT "review_queue_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."rma_requests"
    ADD CONSTRAINT "rma_requests_contact_id_fkey" FOREIGN KEY ("contact_id") REFERENCES "public"."contacts"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."rma_requests"
    ADD CONSTRAINT "rma_requests_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."rma_requests"
    ADD CONSTRAINT "rma_requests_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."rma_requests"
    ADD CONSTRAINT "rma_requests_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."shipment_tracking_events"
    ADD CONSTRAINT "shipment_tracking_events_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."shipment_tracking_events"
    ADD CONSTRAINT "shipment_tracking_events_shipment_id_fkey" FOREIGN KEY ("shipment_id") REFERENCES "public"."shipments"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."shipment_tracking_events"
    ADD CONSTRAINT "shipment_tracking_events_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."shipments"
    ADD CONSTRAINT "shipments_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."shipments"
    ADD CONSTRAINT "shipments_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."stock_movements"
    ADD CONSTRAINT "stock_movements_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."stock_movements"
    ADD CONSTRAINT "stock_movements_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."stock_movements"
    ADD CONSTRAINT "stock_movements_product_id_fkey" FOREIGN KEY ("product_id") REFERENCES "public"."products"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."stock_movements"
    ADD CONSTRAINT "stock_movements_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."stock_movements"
    ADD CONSTRAINT "stock_movements_variation_id_fkey" FOREIGN KEY ("variation_id") REFERENCES "public"."product_variations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."stock_reservations"
    ADD CONSTRAINT "stock_reservations_cart_id_fkey" FOREIGN KEY ("cart_id") REFERENCES "public"."conversation_carts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."stock_reservations"
    ADD CONSTRAINT "stock_reservations_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."stock_reservations"
    ADD CONSTRAINT "stock_reservations_order_id_fkey" FOREIGN KEY ("order_id") REFERENCES "public"."orders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."stock_reservations"
    ADD CONSTRAINT "stock_reservations_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."stock_reservations"
    ADD CONSTRAINT "stock_reservations_variation_id_fkey" FOREIGN KEY ("variation_id") REFERENCES "public"."product_variations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."suppliers"
    ADD CONSTRAINT "suppliers_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."telegram_alert_messages"
    ADD CONSTRAINT "telegram_alert_messages_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_cancellation_policy"
    ADD CONSTRAINT "tenant_cancellation_policy_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_carriers"
    ADD CONSTRAINT "tenant_carriers_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_integrations"
    ADD CONSTRAINT "tenant_integrations_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_legal_acceptance"
    ADD CONSTRAINT "tenant_legal_acceptance_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_payment_methods"
    ADD CONSTRAINT "tenant_payment_methods_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_provider_capabilities"
    ADD CONSTRAINT "tenant_provider_capabilities_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_provider_health"
    ADD CONSTRAINT "tenant_provider_health_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_provider_identity"
    ADD CONSTRAINT "tenant_provider_identity_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_shipping_provider_config"
    ADD CONSTRAINT "tenant_shipping_provider_config_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_subscriptions"
    ADD CONSTRAINT "tenant_subscriptions_plan_code_fkey" FOREIGN KEY ("plan_code") REFERENCES "public"."billing_plans"("plan_code");



ALTER TABLE ONLY "public"."tenant_subscriptions"
    ADD CONSTRAINT "tenant_subscriptions_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_usage_counters"
    ADD CONSTRAINT "tenant_usage_counters_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_usage_events"
    ADD CONSTRAINT "tenant_usage_events_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_users"
    ADD CONSTRAINT "tenant_users_inactivated_by_fkey" FOREIGN KEY ("inactivated_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."tenant_users"
    ADD CONSTRAINT "tenant_users_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_users"
    ADD CONSTRAINT "tenant_users_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenant_webhook_secrets"
    ADD CONSTRAINT "tenant_webhook_secrets_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tenants"
    ADD CONSTRAINT "tenants_deletion_requested_by_fkey" FOREIGN KEY ("deletion_requested_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."user_dismissed_alerts"
    ADD CONSTRAINT "user_dismissed_alerts_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."webhook_events_seen"
    ADD CONSTRAINT "webhook_events_seen_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."whatsapp_templates"
    ADD CONSTRAINT "whatsapp_templates_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."whatsapp_templates"
    ADD CONSTRAINT "whatsapp_templates_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."wompi_events_seen"
    ADD CONSTRAINT "wompi_events_seen_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants"("id") ON DELETE CASCADE;



CREATE POLICY "Authenticated read billing_plans" ON "public"."billing_plans" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));



CREATE POLICY "Authenticated read plan_capabilities" ON "public"."plan_capabilities" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));



CREATE POLICY "Owners can read their PO items" ON "public"."purchase_order_items" FOR SELECT TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



CREATE POLICY "Owners can read their POs" ON "public"."purchase_orders" FOR SELECT TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



CREATE POLICY "Owners can read their expenses" ON "public"."expenses" FOR SELECT TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



CREATE POLICY "Owners can read their suppliers" ON "public"."suppliers" FOR SELECT TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



CREATE POLICY "Platform categories are read-only for tenants" ON "public"."platform_categories" TO "authenticated" USING (false) WITH CHECK (false);



CREATE POLICY "Platform categories are viewable by all authenticated users" ON "public"."platform_categories" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Tenant Isolation" ON "public"."api_security_events" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."claims" TO "authenticated" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."contacts" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."conversation_cart_items" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."conversation_carts" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."conversations" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."email_events" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."idempotency_keys" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."integration_oauth_states" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."messages" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."order_cancellations" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."order_items" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."order_receipts" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."order_tracking" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."orders" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."payment_reversal_requests" FOR SELECT USING (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."product_attribute_definitions" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."product_categories" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."product_variations" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."products" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."rma_requests" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."shipments" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."stock_reservations" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."telegram_alert_messages" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."tenant_cancellation_policy" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."tenant_subscriptions" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."tenant_usage_counters" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."tenant_usage_events" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation" ON "public"."wompi_events_seen" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation Coupon Redemptions" ON "public"."coupon_redemptions" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenant Isolation Coupons" ON "public"."coupons" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "Tenants can manage their own AI agent" ON "public"."ai_agents" TO "authenticated" USING (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text"))))) WITH CHECK (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text")))));



ALTER TABLE "public"."agentic_shadow_log" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "agentic_shadow_log_tenant_isolation" ON "public"."agentic_shadow_log" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."ai_agents" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."ai_insights" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."api_security_events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."audit_log" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "audit_log_insert_self_attribution" ON "public"."audit_log" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK ((("user_id" IS NULL) OR ("user_id" = ( SELECT "auth"."uid"() AS "uid"))));



COMMENT ON POLICY "audit_log_insert_self_attribution" ON "public"."audit_log" IS 'BLOQUE 0 — anti-forja: un miembro solo puede insertar entradas con user_id propio (auth.uid()) o NULL; no puede atribuir una acción a otro usuario. Escritura de servidor va por service_role (bypassa RLS).';



ALTER TABLE "public"."aveonline_carrier_capabilities" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "aveonline_carrier_capabilities_read_all" ON "public"."aveonline_carrier_capabilities" FOR SELECT USING ((("auth"."role"() = 'authenticated'::"text") OR ("auth"."role"() = 'service_role'::"text")));



CREATE POLICY "aveonline_carrier_capabilities_write_service" ON "public"."aveonline_carrier_capabilities" USING (("auth"."role"() = 'service_role'::"text")) WITH CHECK (("auth"."role"() = 'service_role'::"text"));



ALTER TABLE "public"."billing_plans" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."bot_source_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."cart_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "cart_events_tenant_select" ON "public"."cart_events" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."claims" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."compliance_enforcement_log" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "compliance_enforcement_log_tenant_select" ON "public"."compliance_enforcement_log" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."consent_audit_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."contacts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conversation_cart_items" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conversation_carts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conversation_notes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "conversation_notes_author_update" ON "public"."conversation_notes" FOR UPDATE TO "authenticated" USING ((("author_user_id" = "auth"."uid"()) OR (("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))))) WITH CHECK ((("tenant_id" = "public"."app_current_tenant"()) AND (("author_user_id" = "auth"."uid"()) OR ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])))));



CREATE POLICY "conversation_notes_tenant_insert" ON "public"."conversation_notes" FOR INSERT WITH CHECK ((("tenant_id" = ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid") AND ("author_user_id" = "auth"."uid"())));



CREATE POLICY "conversation_notes_tenant_read" ON "public"."conversation_notes" FOR SELECT USING (("tenant_id" = ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid"));



ALTER TABLE "public"."conversation_reads" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conversations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."coupon_redemptions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."coupons" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."credential_access_log" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "credential_access_log_tenant_select" ON "public"."credential_access_log" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."email_events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."expenses" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."idempotency_keys" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integration_oauth_states" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."kb_documents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "legal_acceptance_tenant_insert" ON "public"."tenant_legal_acceptance" FOR INSERT TO "authenticated" WITH CHECK (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text") AND ("tu"."role" = ANY (ARRAY['owner'::"text", 'manager'::"text"]))))));



CREATE POLICY "legal_acceptance_tenant_select" ON "public"."tenant_legal_acceptance" FOR SELECT TO "authenticated" USING (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text")))));



ALTER TABLE "public"."marketplace_listings" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."meli_webhook_dedup" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."messages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mfa_recovery_codes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notification_settings" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "notification_settings_select_member" ON "public"."notification_settings" FOR SELECT USING (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "notification_settings_write_privileged" ON "public"."notification_settings" TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])))) WITH CHECK ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))));



ALTER TABLE "public"."order_cancellations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."order_items" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."order_receipts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."order_tracking" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."orders" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."outbound_idempotency_cache" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "outbound_idempotency_cache_tenant_select" ON "public"."outbound_idempotency_cache" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."payment_reversal_requests" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."payments" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."pii_access_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."plan_capabilities" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."platform_categories" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."product_attribute_definitions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."product_categories" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."product_variations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."products" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."provider_health_alert_dedup" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."purchase_order_items" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."purchase_orders" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."rate_limit_windows" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "receipts_no_escritura_directa" ON "public"."order_receipts" AS RESTRICTIVE TO "authenticated" USING (true) WITH CHECK (false);



ALTER TABLE "public"."retention_policies" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "retention_policies_tenant_modify" ON "public"."retention_policies" TO "authenticated" USING (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text") AND ("tu"."role" = ANY (ARRAY['owner'::"text", 'manager'::"text"])))))) WITH CHECK (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text") AND ("tu"."role" = ANY (ARRAY['owner'::"text", 'manager'::"text"]))))));



CREATE POLICY "retention_policies_tenant_select" ON "public"."retention_policies" FOR SELECT TO "authenticated" USING ((("tenant_id" IS NULL) OR ("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text"))))));



CREATE POLICY "reversal_no_escritura_directa" ON "public"."payment_reversal_requests" AS RESTRICTIVE TO "authenticated" USING (true) WITH CHECK (false);



ALTER TABLE "public"."review_queue" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "review_queue_tenant_select" ON "public"."review_queue" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



CREATE POLICY "review_queue_tenant_update" ON "public"."review_queue" FOR UPDATE USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."rma_requests" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."shipment_tracking_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "shipment_tracking_events_tenant_isolation" ON "public"."shipment_tracking_events" FOR SELECT USING (("tenant_id" = "public"."app_current_tenant"()));



COMMENT ON POLICY "shipment_tracking_events_tenant_isolation" ON "public"."shipment_tracking_events" IS 'Tenant isolation usando app_current_tenant() — soporta workers (GUC) Y server components Next.js (JWT claim). Reemplaza current_setting() directo que rompía el timeline en la consola. INSERT sigue siendo service_role.';



ALTER TABLE "public"."shipments" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."stock_movements" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."stock_reservations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."suppliers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."telegram_alert_messages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tenant_cancellation_policy" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tenant_carriers" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_carriers_isolation" ON "public"."tenant_carriers" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



ALTER TABLE "public"."tenant_integrations" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_integrations_select_member" ON "public"."tenant_integrations" FOR SELECT USING (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "tenant_integrations_write_privileged" ON "public"."tenant_integrations" TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])))) WITH CHECK ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))));



CREATE POLICY "tenant_isolation_ai_insights" ON "public"."ai_insights" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "tenant_isolation_audit_log" ON "public"."audit_log" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "tenant_isolation_consent_audit_log" ON "public"."consent_audit_log" FOR SELECT TO "authenticated" USING (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text")))));



CREATE POLICY "tenant_isolation_kb_documents" ON "public"."kb_documents" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "tenant_isolation_marketplace" ON "public"."marketplace_listings" USING (("tenant_id" = ( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid" AS "uuid"))) WITH CHECK (("tenant_id" = ( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid" AS "uuid")));



CREATE POLICY "tenant_isolation_pii_access_log" ON "public"."pii_access_log" FOR SELECT TO "authenticated" USING (("tenant_id" IN ( SELECT "tu"."tenant_id"
   FROM "public"."tenant_users" "tu"
  WHERE (("tu"."user_id" = "auth"."uid"()) AND ("tu"."status" = 'active'::"text")))));



CREATE POLICY "tenant_isolation_stock_movements" ON "public"."stock_movements" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



ALTER TABLE "public"."tenant_legal_acceptance" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tenant_offboarding_log" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_offboarding_log_owner_select" ON "public"."tenant_offboarding_log" FOR SELECT TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



ALTER TABLE "public"."tenant_payment_methods" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_payment_methods_read_own" ON "public"."tenant_payment_methods" FOR SELECT USING ((("auth"."role"() = 'service_role'::"text") OR ("tenant_id" = (((("current_setting"('request.jwt.claims'::"text", true))::"jsonb" -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid")));



CREATE POLICY "tenant_payment_methods_write_owner" ON "public"."tenant_payment_methods" TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text"))) WITH CHECK ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



CREATE POLICY "tenant_payment_methods_write_service" ON "public"."tenant_payment_methods" USING (("auth"."role"() = 'service_role'::"text")) WITH CHECK (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "tenant_payments_select" ON "public"."payments" FOR SELECT USING (("tenant_id" = ( SELECT ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid" AS "uuid")));



ALTER TABLE "public"."tenant_provider_capabilities" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_provider_capabilities_tenant_iud" ON "public"."tenant_provider_capabilities" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



COMMENT ON POLICY "tenant_provider_capabilities_tenant_iud" ON "public"."tenant_provider_capabilities" IS 'Tenant Isolation FOR ALL. Reemplaza policy original FOR SELECT (2026-05-14) que bloqueaba server actions Next.js. Aislamiento garantizado por tenant_id = app_current_tenant() in USING+WITH CHECK.';



ALTER TABLE "public"."tenant_provider_health" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_provider_health_tenant_select" ON "public"."tenant_provider_health" FOR SELECT TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))));



ALTER TABLE "public"."tenant_provider_identity" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_provider_identity_tenant_select" ON "public"."tenant_provider_identity" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."tenant_shipping_provider_config" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tenant_subscriptions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tenant_usage_counters" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tenant_usage_events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tenant_users" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_users_delete_owner" ON "public"."tenant_users" FOR DELETE TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



CREATE POLICY "tenant_users_insert_owner" ON "public"."tenant_users" FOR INSERT TO "authenticated" WITH CHECK ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



CREATE POLICY "tenant_users_select_member" ON "public"."tenant_users" FOR SELECT USING (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "tenant_users_update_owner" ON "public"."tenant_users" FOR UPDATE TO "authenticated" USING ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text"))) WITH CHECK ((("tenant_id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = 'owner'::"text")));



ALTER TABLE "public"."tenant_webhook_secrets" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenant_webhook_secrets_tenant_select" ON "public"."tenant_webhook_secrets" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."tenants" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tenants_select_member" ON "public"."tenants" FOR SELECT USING (("id" = "public"."app_current_tenant"()));



CREATE POLICY "tenants_update_privileged" ON "public"."tenants" FOR UPDATE TO "authenticated" USING ((("id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])))) WITH CHECK ((("id" = "public"."app_current_tenant"()) AND ("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))));



CREATE POLICY "track9_asec_no_delete" ON "public"."api_security_events" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "track9_asec_no_insert" ON "public"."api_security_events" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "track9_asec_no_update" ON "public"."api_security_events" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "track9_cancellations_no_delete" ON "public"."order_cancellations" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "track9_cancellations_no_update" ON "public"."order_cancellations" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "track9_claims_no_delete" ON "public"."claims" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "track9_claims_update_privileged" ON "public"."claims" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))) WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_contacts_no_delete" ON "public"."contacts" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "track9_contacts_no_update" ON "public"."contacts" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "track9_conversations_no_delete" ON "public"."conversations" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "track9_conversations_no_update" ON "public"."conversations" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "track9_marketplace_listings_delete_privileged" ON "public"."marketplace_listings" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_marketplace_listings_update_privileged" ON "public"."marketplace_listings" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))) WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_marketplace_listings_write_privileged" ON "public"."marketplace_listings" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_messages_no_delete" ON "public"."messages" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "track9_messages_no_update" ON "public"."messages" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "track9_notification_settings_select_privileged" ON "public"."notification_settings" AS RESTRICTIVE FOR SELECT TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_order_tracking_delete_privileged" ON "public"."order_tracking" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_order_tracking_update_privileged" ON "public"."order_tracking" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))) WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_order_tracking_write_privileged" ON "public"."order_tracking" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_payments_select_owner" ON "public"."payments" AS RESTRICTIVE FOR SELECT TO "authenticated" USING (("public"."app_current_role"() = 'owner'::"text"));



CREATE POLICY "track9_rma_no_delete" ON "public"."rma_requests" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "track9_rma_update_privileged" ON "public"."rma_requests" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))) WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_shipments_delete_privileged" ON "public"."shipments" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_shipments_update_privileged" ON "public"."shipments" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))) WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_shipments_write_privileged" ON "public"."shipments" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_tcp_delete_privileged" ON "public"."tenant_cancellation_policy" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_tcp_insert_privileged" ON "public"."tenant_cancellation_policy" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_tcp_update_privileged" ON "public"."tenant_cancellation_policy" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))) WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_tspc_delete_privileged" ON "public"."tenant_shipping_provider_config" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_tspc_insert_privileged" ON "public"."tenant_shipping_provider_config" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "track9_tspc_update_privileged" ON "public"."tenant_shipping_provider_config" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"]))) WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "tspc_modify_own_tenant" ON "public"."tenant_shipping_provider_config" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



CREATE POLICY "tspc_select_own_tenant" ON "public"."tenant_shipping_provider_config" FOR SELECT USING (("tenant_id" = "public"."app_current_tenant"()));



COMMENT ON POLICY "tspc_select_own_tenant" ON "public"."tenant_shipping_provider_config" IS 'Tenant isolation usando app_current_tenant() — soporta workers (GUC) Y server components Next.js (JWT claim).';



CREATE POLICY "user reads own conversation_reads in tenant" ON "public"."conversation_reads" FOR SELECT USING ((("tenant_id" = ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid") AND ("user_id" = "auth"."uid"())));



CREATE POLICY "user reads own dismissed alerts" ON "public"."user_dismissed_alerts" FOR SELECT TO "authenticated" USING ((("user_id" = "auth"."uid"()) AND ("tenant_id" = "public"."app_current_tenant"())));



CREATE POLICY "user updates own conversation_reads in tenant" ON "public"."conversation_reads" FOR UPDATE USING ((("tenant_id" = ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid") AND ("user_id" = "auth"."uid"())));



CREATE POLICY "user updates own dismissed alerts" ON "public"."user_dismissed_alerts" FOR UPDATE TO "authenticated" USING ((("user_id" = "auth"."uid"()) AND ("tenant_id" = "public"."app_current_tenant"()))) WITH CHECK ((("user_id" = "auth"."uid"()) AND ("tenant_id" = "public"."app_current_tenant"())));



CREATE POLICY "user upserts own conversation_reads in tenant" ON "public"."conversation_reads" FOR INSERT WITH CHECK ((("tenant_id" = ((("auth"."jwt"() -> 'app_metadata'::"text") ->> 'tenant_id'::"text"))::"uuid") AND ("user_id" = "auth"."uid"())));



CREATE POLICY "user upserts own dismissed alerts" ON "public"."user_dismissed_alerts" FOR INSERT TO "authenticated" WITH CHECK ((("user_id" = "auth"."uid"()) AND ("tenant_id" = "public"."app_current_tenant"())));



ALTER TABLE "public"."user_dismissed_alerts" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "w2_money_no_delete" ON "public"."conversation_cart_items" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."conversation_carts" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."coupon_redemptions" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."coupons" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."order_items" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."orders" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."product_variations" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "w2_money_no_delete" ON "public"."products" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."stock_movements" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."stock_reservations" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_delete" ON "public"."tenant_subscriptions" AS RESTRICTIVE FOR DELETE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_insert" ON "public"."conversation_cart_items" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."conversation_carts" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."coupon_redemptions" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."coupons" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."order_items" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."orders" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."product_variations" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "w2_money_no_insert" ON "public"."products" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."stock_movements" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "w2_money_no_insert" ON "public"."stock_reservations" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_insert" ON "public"."tenant_subscriptions" AS RESTRICTIVE FOR INSERT TO "authenticated" WITH CHECK (false);



CREATE POLICY "w2_money_no_update" ON "public"."conversation_cart_items" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."conversation_carts" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."coupon_redemptions" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."coupons" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."order_items" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."orders" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



COMMENT ON POLICY "w2_money_no_update" ON "public"."orders" IS 'W2b: cierra la escritura directa por PostgREST a usuarios con sesión. Toda mutación de pedidos debe ir por services/api (service_role, que bypassea RLS) donde viven la FSM, el gate de rol, @audit_log y el step-up MFA.';



CREATE POLICY "w2_money_no_update" ON "public"."product_variations" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (("public"."app_current_role"() = ANY (ARRAY['owner'::"text", 'manager'::"text"])));



CREATE POLICY "w2_money_no_update" ON "public"."products" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."stock_movements" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."stock_reservations" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



CREATE POLICY "w2_money_no_update" ON "public"."tenant_subscriptions" AS RESTRICTIVE FOR UPDATE TO "authenticated" USING (false);



ALTER TABLE "public"."webhook_events_seen" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "webhook_events_seen_tenant_select" ON "public"."webhook_events_seen" FOR SELECT USING (("tenant_id" = ("current_setting"('app.current_tenant_id'::"text", true))::"uuid"));



ALTER TABLE "public"."whatsapp_templates" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "whatsapp_templates_tenant_iud" ON "public"."whatsapp_templates" USING (("tenant_id" = "public"."app_current_tenant"())) WITH CHECK (("tenant_id" = "public"."app_current_tenant"()));



ALTER TABLE "public"."whatsapp_webhook_inbox" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."wompi_events_seen" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."wompi_webhook_inbox" ENABLE ROW LEVEL SECURITY;




ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";


ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."conversation_cart_items";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."conversation_carts";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."conversations";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."messages";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."order_cancellations";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."orders";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."rma_requests";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."stock_reservations";






GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";





















































































































































































































































































































































































































































































































GRANT ALL ON FUNCTION "public"."_ai_agents_fallback_roles_valid"("roles" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."_ai_agents_fallback_roles_valid"("roles" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."_ai_agents_fallback_roles_valid"("roles" "jsonb") TO "service_role";



REVOKE ALL ON FUNCTION "public"."_touch_conversation_notes_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."_touch_conversation_notes_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."ack_human_takeover_notification"("p_msg_id" bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."ack_human_takeover_notification"("p_msg_id" bigint) TO "service_role";



REVOKE ALL ON FUNCTION "public"."ack_whatsapp_outbound_message"("p_msg_id" bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."ack_whatsapp_outbound_message"("p_msg_id" bigint) TO "service_role";



REVOKE ALL ON FUNCTION "public"."add_member_to_tenant"("p_user_id" "uuid", "p_tenant_id" "uuid", "p_role" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."add_member_to_tenant"("p_user_id" "uuid", "p_tenant_id" "uuid", "p_role" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."ai_insights_set_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."ai_insights_set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."app_current_role"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."app_current_role"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."app_current_role"() TO "service_role";



GRANT ALL ON FUNCTION "public"."app_current_tenant"() TO "anon";
GRANT ALL ON FUNCTION "public"."app_current_tenant"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."app_current_tenant"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."assign_purchase_order_number"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."assign_purchase_order_number"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."cart_add_item"("p_tenant_id" "uuid", "p_cart_id" "uuid", "p_product_id" "uuid", "p_variation_id" "uuid", "p_quantity" integer, "p_unit_price_cents" bigint, "p_expected_version" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."cart_add_item"("p_tenant_id" "uuid", "p_cart_id" "uuid", "p_product_id" "uuid", "p_variation_id" "uuid", "p_quantity" integer, "p_unit_price_cents" bigint, "p_expected_version" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."claim_wompi_inbox_batch"("p_limit" integer, "p_min_age_seconds" integer, "p_max_attempts" integer, "p_lease_seconds" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."claim_wompi_inbox_batch"("p_limit" integer, "p_min_age_seconds" integer, "p_max_attempts" integer, "p_lease_seconds" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."cleanup_expired_bot_source_log"("retention_days" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_expired_bot_source_log"("retention_days" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_expired_bot_source_log"("retention_days" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."cleanup_expired_idempotency_keys"("p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."cleanup_expired_idempotency_keys"("p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."cleanup_expired_meli_webhook_dedup"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."cleanup_expired_meli_webhook_dedup"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."cleanup_expired_rate_limit_windows"("p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."cleanup_expired_rate_limit_windows"("p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."cleanup_wompi_inbox"("p_processed_retention_days" integer, "p_deadletter_retention_days" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."cleanup_wompi_inbox"("p_processed_retention_days" integer, "p_deadletter_retention_days" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."consent_audit_log_block_modify"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."consent_audit_log_block_modify"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."consume_tenant_capability"("p_tenant_id" "uuid", "p_capability_key" "text", "p_units" integer, "p_metadata" "jsonb") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."consume_tenant_capability"("p_tenant_id" "uuid", "p_capability_key" "text", "p_units" integer, "p_metadata" "jsonb") TO "service_role";



REVOKE ALL ON FUNCTION "public"."contacts_default_shipping_phone"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."contacts_default_shipping_phone"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."coupon_increment_redemption"("p_coupon_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."coupon_increment_redemption"("p_coupon_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."custom_access_token_hook"("event" "jsonb") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."custom_access_token_hook"("event" "jsonb") TO "service_role";
GRANT ALL ON FUNCTION "public"."custom_access_token_hook"("event" "jsonb") TO "supabase_auth_admin";



REVOKE ALL ON FUNCTION "public"."dequeue_human_takeover_notifications"("p_vt" integer, "p_qty" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."dequeue_human_takeover_notifications"("p_vt" integer, "p_qty" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."dequeue_whatsapp_outbound_messages"("p_vt" integer, "p_qty" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."dequeue_whatsapp_outbound_messages"("p_vt" integer, "p_qty" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."enqueue_human_takeover_notification"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."enqueue_human_takeover_notification"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."enqueue_whatsapp_outbound_message"("p_message" "jsonb", "p_delay" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."enqueue_whatsapp_outbound_message"("p_message" "jsonb", "p_delay" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."es_mensaje_de_evidencia"("p_conversation_id" "uuid", "p_tenant_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."es_mensaje_de_evidencia"("p_conversation_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_apply_retention"("p_entity" "text", "p_dry_run" boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_apply_retention"("p_entity" "text", "p_dry_run" boolean) TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_block_legal_acceptance_modify"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_block_legal_acceptance_modify"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_cancel_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_cancel_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_claim_health_alert"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_status" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_claim_health_alert"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_status" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_cleanup_webhook_secrets"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_cleanup_webhook_secrets"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_consume_mfa_recovery_code"("p_user_id" "uuid", "p_code_hash" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_consume_mfa_recovery_code"("p_user_id" "uuid", "p_code_hash" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_detect_health_degradations"("p_window_minutes" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_detect_health_degradations"("p_window_minutes" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_document_hash"("p_doc" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."fn_document_hash"("p_doc" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_document_hash"("p_doc" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_document_last4"("p_doc" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."fn_document_last4"("p_doc" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_document_last4"("p_doc" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_expire_abandoned_carts"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_expire_abandoned_carts"() TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_expire_stock_reservations"() TO "anon";
GRANT ALL ON FUNCTION "public"."fn_expire_stock_reservations"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_expire_stock_reservations"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_hard_delete_tenant"("p_tenant_id" "uuid", "p_archive_path" "text", "p_evidence" "jsonb") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_hard_delete_tenant"("p_tenant_id" "uuid", "p_archive_path" "text", "p_evidence" "jsonb") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_list_tenants_pending_hard_delete"("p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_list_tenants_pending_hard_delete"("p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_log_tenant_offboarding_event"("p_tenant_id" "uuid", "p_event" "text", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_evidence" "jsonb") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_log_tenant_offboarding_event"("p_tenant_id" "uuid", "p_event" "text", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_evidence" "jsonb") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_purge_orphan_shipment_quotes"("p_retention_days" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_purge_orphan_shipment_quotes"("p_retention_days" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_purge_tenant_storage_objects"("p_tenant_id" "uuid", "p_bucket_ids" "text"[]) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_purge_tenant_storage_objects"("p_tenant_id" "uuid", "p_bucket_ids" "text"[]) TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_record_shipment_tracking_event"("p_tenant_id" "uuid", "p_shipment_id" "uuid", "p_order_id" "uuid", "p_provider" "text", "p_external_event_id" "text", "p_raw_status" "text", "p_raw_estado_id" integer, "p_internal_status" "text", "p_description" "text", "p_occurred_at" timestamp with time zone, "p_raw" "jsonb") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_record_shipment_tracking_event"("p_tenant_id" "uuid", "p_shipment_id" "uuid", "p_order_id" "uuid", "p_provider" "text", "p_external_event_id" "text", "p_raw_status" "text", "p_raw_estado_id" integer, "p_internal_status" "text", "p_description" "text", "p_occurred_at" timestamp with time zone, "p_raw" "jsonb") TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_regenerate_mfa_recovery_codes"("p_user_id" "uuid", "p_code_hashes" "text"[]) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_regenerate_mfa_recovery_codes"("p_user_id" "uuid", "p_code_hashes" "text"[]) TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_request_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_reason" "text", "p_grace_period_days" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_request_tenant_deletion"("p_tenant_id" "uuid", "p_actor_user_id" "uuid", "p_actor_email" "text", "p_actor_ip" "inet", "p_reason" "text", "p_grace_period_days" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_sync_document_derived"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_sync_document_derived"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."fn_upsert_provider_health"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_value" "text", "p_threshold" "text", "p_status" "text", "p_detail" "jsonb") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."fn_upsert_provider_health"("p_tenant_id" "uuid", "p_provider" "text", "p_metric" "text", "p_value" "text", "p_threshold" "text", "p_status" "text", "p_detail" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."fn_variation_available_stock"("p_variation_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."fn_variation_available_stock"("p_variation_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."fn_variation_available_stock"("p_variation_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."get_aveonline_credentials"("p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."get_aveonline_credentials"("p_tenant_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_aveonline_credentials"("p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."get_tenant_plan_capabilities"("p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."get_tenant_plan_capabilities"("p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."get_tenant_team"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."get_tenant_team"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_tenant_team"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."log_audit_export"("p_row_count" integer, "p_filters" "jsonb", "p_ip" "text", "p_user_agent" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."log_audit_export"("p_row_count" integer, "p_filters" "jsonb", "p_ip" "text", "p_user_agent" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."log_audit_export"("p_row_count" integer, "p_filters" "jsonb", "p_ip" "text", "p_user_agent" "text") TO "service_role";






REVOKE ALL ON FUNCTION "public"."meli_webhook_seen"("p_application_id" "text", "p_resource" "text", "p_sent" "text", "p_ttl_seconds" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."meli_webhook_seen"("p_application_id" "text", "p_resource" "text", "p_sent" "text", "p_ttl_seconds" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."metrics_orders_summary"("p_from" timestamp with time zone, "p_to" timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."metrics_orders_summary"("p_from" timestamp with time zone, "p_to" timestamp with time zone) TO "authenticated";
GRANT ALL ON FUNCTION "public"."metrics_orders_summary"("p_from" timestamp with time zone, "p_to" timestamp with time zone) TO "service_role";



REVOKE ALL ON FUNCTION "public"."metrics_orders_timeseries"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_bucket" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."metrics_orders_timeseries"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_bucket" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."metrics_orders_timeseries"("p_from" timestamp with time zone, "p_to" timestamp with time zone, "p_bucket" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."outbound_idempotency_cleanup"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."outbound_idempotency_cleanup"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."outbound_idempotency_lookup"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."outbound_idempotency_lookup"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."outbound_idempotency_register"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text", "p_status" integer, "p_body" "jsonb", "p_headers" "jsonb", "p_ttl_seconds" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."outbound_idempotency_register"("p_provider" "text", "p_tenant_id" "uuid", "p_request_hash" "text", "p_status" integer, "p_body" "jsonb", "p_headers" "jsonb", "p_ttl_seconds" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."pgsec_create_secret"("p_secret" "text", "p_name" "text", "p_description" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."pgsec_create_secret"("p_secret" "text", "p_name" "text", "p_description" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."pgsec_create_secret"("p_secret" "text", "p_name" "text", "p_description" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."pgsec_delete_secret"("p_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."pgsec_delete_secret"("p_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."pgsec_delete_secret"("p_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."pgsec_list_secrets_by_name_pattern"("p_pattern" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."pgsec_list_secrets_by_name_pattern"("p_pattern" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."pgsec_read_secret"("p_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."pgsec_read_secret"("p_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."pgsec_read_secret"("p_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."pgsec_update_secret"("p_id" "uuid", "p_secret" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."pgsec_update_secret"("p_id" "uuid", "p_secret" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."pgsec_update_secret"("p_id" "uuid", "p_secret" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."pgsec_upsert_secret"("p_name" "text", "p_secret" "text", "p_description" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."pgsec_upsert_secret"("p_name" "text", "p_secret" "text", "p_description" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."pgsec_upsert_secret"("p_name" "text", "p_secret" "text", "p_description" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."pii_access_log_block_modify"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."pii_access_log_block_modify"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."provision_tenant"("p_tenant_name" "text", "p_owner_user_id" "uuid", "p_plan_code" "text", "p_actor_user_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."provision_tenant"("p_tenant_name" "text", "p_owner_user_id" "uuid", "p_plan_code" "text", "p_actor_user_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rate_limit_hit"("p_key" "text", "p_limit" integer, "p_window_seconds" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rate_limit_hit"("p_key" "text", "p_limit" integer, "p_window_seconds" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."reject_audit_log_mutation"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."reject_audit_log_mutation"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."reversion_procede"("p_order_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."reversion_procede"("p_order_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_dashboard_revenue"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_dashboard_revenue"() TO "anon";
GRANT ALL ON FUNCTION "public"."rpc_dashboard_revenue"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."rpc_dashboard_revenue"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_constancias_por_entregar"("p_csw_hours" integer, "p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_constancias_por_entregar"("p_csw_hours" integer, "p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_dobles_pagos_sin_avisar"("p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_dobles_pagos_sin_avisar"("p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_incoherent_orders"("p_window_hours" integer, "p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_incoherent_orders"("p_window_hours" integer, "p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_orders_pending_acceptance"("p_min_age_minutes" integer, "p_window_days" integer, "p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_orders_pending_acceptance"("p_min_age_minutes" integer, "p_window_days" integer, "p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_orders_pending_receipt"("p_min_age_minutes" integer, "p_window_hours" integer, "p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_orders_pending_receipt"("p_min_age_minutes" integer, "p_window_hours" integer, "p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_receipts_pending_ack"("p_csw_hours" integer, "p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_receipts_pending_ack"("p_csw_hours" integer, "p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_receipts_pending_email"("p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_receipts_pending_email"("p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_receipts_to_void"("p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_receipts_to_void"("p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_find_silent_conversations"("p_silence_minutes" integer, "p_window_hours" integer, "p_limit" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_find_silent_conversations"("p_silence_minutes" integer, "p_window_hours" integer, "p_limit" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_issue_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_issue_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_mark_constancia_entregada"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_fallida" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_mark_constancia_entregada"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_fallida" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_mark_doble_pago_avisado"("p_reversal_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_mark_doble_pago_avisado"("p_reversal_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_mark_receipt_ack"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_channel" "text", "p_skipped" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_mark_receipt_ack"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_channel" "text", "p_skipped" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_mark_receipt_email"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_email" "text", "p_skipped" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_mark_receipt_email"("p_receipt_id" "uuid", "p_tenant_id" "uuid", "p_email" "text", "p_skipped" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_meli_note_refresh_failure"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text", "p_max_fails" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_meli_note_refresh_failure"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text", "p_max_fails" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_meli_release_refresh_lease"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_meli_release_refresh_lease"("p_tenant_id" "uuid", "p_lease_token" "uuid", "p_provider" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_meli_try_refresh_lease"("p_tenant_id" "uuid", "p_provider" "text", "p_ttl_seconds" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_meli_try_refresh_lease"("p_tenant_id" "uuid", "p_provider" "text", "p_ttl_seconds" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_order_money"("p_order_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_order_money"("p_order_id" "uuid", "p_tenant_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."rpc_order_money"("p_order_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_registrar_movimiento_reversion"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_via" "text", "p_valor" numeric) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_registrar_movimiento_reversion"("p_reversal_id" "uuid", "p_tenant_id" "uuid", "p_via" "text", "p_valor" numeric) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_registrar_reversion"("p_claim_id" "uuid", "p_tenant_id" "uuid", "p_causal" "text", "p_razones" "text", "p_valor" numeric, "p_instrumento" "text", "p_es_parcial" boolean, "p_items" "jsonb", "p_bien_a_disposicion" boolean, "p_canal" "text", "p_conversation_id" "uuid", "p_message_id" "uuid", "p_meta_message_id" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_registrar_reversion"("p_claim_id" "uuid", "p_tenant_id" "uuid", "p_causal" "text", "p_razones" "text", "p_valor" numeric, "p_instrumento" "text", "p_es_parcial" boolean, "p_items" "jsonb", "p_bien_a_disposicion" boolean, "p_canal" "text", "p_conversation_id" "uuid", "p_message_id" "uuid", "p_meta_message_id" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stamp_order_acceptance"("p_order_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stamp_order_acceptance"("p_order_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stock_decrement"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stock_decrement"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stock_reservation_consume"("p_reservation_id" "uuid", "p_order_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stock_reservation_consume"("p_reservation_id" "uuid", "p_order_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stock_reservation_extend"("p_reservation_id" "uuid", "p_new_ttl_min" integer, "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stock_reservation_extend"("p_reservation_id" "uuid", "p_new_ttl_min" integer, "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stock_reservation_release"("p_reservation_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stock_reservation_release"("p_reservation_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stock_reservation_release_by_conversation"("p_conversation_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stock_reservation_release_by_conversation"("p_conversation_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stock_reserve"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_cart_id" "uuid", "p_conversation_id" "uuid", "p_ttl_minutes" integer) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stock_reserve"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_cart_id" "uuid", "p_conversation_id" "uuid", "p_ttl_minutes" integer) TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_stock_restore"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_stock_restore"("p_tenant_id" "uuid", "p_variation_id" "uuid", "p_qty" integer, "p_order_id" "uuid", "p_reason" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."rpc_void_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid", "p_reason" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."rpc_void_receipt"("p_order_id" "uuid", "p_tenant_id" "uuid", "p_reason" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."seed_tenant_subscription_default"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."seed_tenant_subscription_default"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."set_claim_ticket_number"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."set_claim_ticket_number"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."stamp_human_takeover_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."stamp_human_takeover_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."sync_conversation_last_interaction"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."sync_conversation_last_interaction"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."sync_tenant_stamp_to_auth"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."sync_tenant_stamp_to_auth"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tenant_carriers_set_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tenant_carriers_set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tenant_provider_capabilities_set_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tenant_provider_capabilities_set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tenant_provider_identity_set_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tenant_provider_identity_set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tenant_seller_identity"("p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tenant_seller_identity"("p_tenant_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."tenant_seller_identity"("p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."tenant_shipping_provider_config_set_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tenant_shipping_provider_config_set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tenant_webhook_secrets_set_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tenant_webhook_secrets_set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tg_aveonline_carrier_capabilities_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tg_aveonline_carrier_capabilities_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tg_coupons_set_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tg_coupons_set_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tg_release_coupon_on_cart_terminal"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tg_release_coupon_on_cart_terminal"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tg_tenant_payment_methods_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tg_tenant_payment_methods_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tg_whatsapp_templates_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tg_whatsapp_templates_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."tiene_consentimiento_comercial"("p_contact_id" "uuid", "p_tenant_id" "uuid") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."tiene_consentimiento_comercial"("p_contact_id" "uuid", "p_tenant_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."tiene_consentimiento_comercial"("p_contact_id" "uuid", "p_tenant_id" "uuid") TO "service_role";



REVOKE ALL ON FUNCTION "public"."touch_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."touch_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."track9_revoke_public_on_new_function"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."trg_void_receipt_on_cancel"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."trg_void_receipt_on_cancel"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."update_claims_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."update_claims_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."update_idempotency_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."update_idempotency_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."update_kb_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."update_kb_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."update_marketplace_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."update_marketplace_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."update_order_tracking_updated_at"() FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."update_order_tracking_updated_at"() TO "service_role";



REVOKE ALL ON FUNCTION "public"."upsert_aveonline_idagente"("p_tenant_id" "uuid", "p_idagente" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."upsert_aveonline_idagente"("p_tenant_id" "uuid", "p_idagente" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."upsert_aveonline_jwt"("p_tenant_id" "uuid", "p_jwt_token" "text", "p_jwt_expires_at" timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."upsert_aveonline_jwt"("p_tenant_id" "uuid", "p_jwt_token" "text", "p_jwt_expires_at" timestamp with time zone) TO "service_role";



REVOKE ALL ON FUNCTION "public"."webhook_event_check_or_register"("p_integration" "text", "p_event_uid" "text", "p_tenant_id" "uuid", "p_event_type" "text", "p_correlation_id" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."webhook_event_check_or_register"("p_integration" "text", "p_event_uid" "text", "p_tenant_id" "uuid", "p_event_type" "text", "p_correlation_id" "text") TO "service_role";



REVOKE ALL ON FUNCTION "public"."webhook_event_mark_processed"("p_integration" "text", "p_event_uid" "text") FROM PUBLIC;
GRANT ALL ON FUNCTION "public"."webhook_event_mark_processed"("p_integration" "text", "p_event_uid" "text") TO "service_role";






























GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."agentic_shadow_log" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."agentic_shadow_log" TO "authenticated";
GRANT ALL ON TABLE "public"."agentic_shadow_log" TO "service_role";



GRANT ALL ON SEQUENCE "public"."agentic_shadow_log_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."agentic_shadow_log_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."agentic_shadow_log_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."ai_agents" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."ai_agents" TO "authenticated";
GRANT ALL ON TABLE "public"."ai_agents" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."ai_insights" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."ai_insights" TO "authenticated";
GRANT ALL ON TABLE "public"."ai_insights" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."api_security_events" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."api_security_events" TO "authenticated";
GRANT ALL ON TABLE "public"."api_security_events" TO "service_role";



GRANT SELECT,INSERT,MAINTAIN ON TABLE "public"."audit_log" TO "anon";
GRANT SELECT,INSERT,MAINTAIN ON TABLE "public"."audit_log" TO "authenticated";
GRANT ALL ON TABLE "public"."audit_log" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."aveonline_carrier_capabilities" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."aveonline_carrier_capabilities" TO "authenticated";
GRANT ALL ON TABLE "public"."aveonline_carrier_capabilities" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."billing_plans" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."billing_plans" TO "authenticated";
GRANT ALL ON TABLE "public"."billing_plans" TO "service_role";



GRANT ALL ON TABLE "public"."bot_source_log" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."cart_events" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."cart_events" TO "authenticated";
GRANT ALL ON TABLE "public"."cart_events" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."claims" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."claims" TO "authenticated";
GRANT ALL ON TABLE "public"."claims" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."compliance_enforcement_log" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."compliance_enforcement_log" TO "authenticated";
GRANT ALL ON TABLE "public"."compliance_enforcement_log" TO "service_role";



GRANT ALL ON SEQUENCE "public"."compliance_enforcement_log_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."compliance_enforcement_log_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."compliance_enforcement_log_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."consent_audit_log" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."contacts" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."contacts" TO "authenticated";
GRANT ALL ON TABLE "public"."contacts" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_cart_items" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_cart_items" TO "authenticated";
GRANT ALL ON TABLE "public"."conversation_cart_items" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_carts" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_carts" TO "authenticated";
GRANT ALL ON TABLE "public"."conversation_carts" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_notes" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_notes" TO "authenticated";
GRANT ALL ON TABLE "public"."conversation_notes" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_reads" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversation_reads" TO "authenticated";
GRANT ALL ON TABLE "public"."conversation_reads" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversations" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."conversations" TO "authenticated";
GRANT ALL ON TABLE "public"."conversations" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."coupon_redemptions" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."coupon_redemptions" TO "authenticated";
GRANT ALL ON TABLE "public"."coupon_redemptions" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."coupons" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."coupons" TO "authenticated";
GRANT ALL ON TABLE "public"."coupons" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."credential_access_log" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."credential_access_log" TO "authenticated";
GRANT ALL ON TABLE "public"."credential_access_log" TO "service_role";



GRANT ALL ON SEQUENCE "public"."credential_access_log_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."credential_access_log_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."credential_access_log_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."email_events" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."expenses" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."expenses" TO "authenticated";
GRANT ALL ON TABLE "public"."expenses" TO "service_role";



GRANT ALL ON TABLE "public"."idempotency_keys" TO "service_role";



GRANT ALL ON TABLE "public"."integration_oauth_states" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."kb_documents" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."kb_documents" TO "authenticated";
GRANT ALL ON TABLE "public"."kb_documents" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."marketplace_listings" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."marketplace_listings" TO "authenticated";
GRANT ALL ON TABLE "public"."marketplace_listings" TO "service_role";



GRANT ALL ON TABLE "public"."meli_webhook_dedup" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."messages" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."messages" TO "authenticated";
GRANT ALL ON TABLE "public"."messages" TO "service_role";



GRANT ALL ON TABLE "public"."mfa_recovery_codes" TO "service_role";



GRANT ALL ON SEQUENCE "public"."mfa_recovery_codes_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."mfa_recovery_codes_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."mfa_recovery_codes_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."notification_settings" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."notification_settings" TO "authenticated";
GRANT ALL ON TABLE "public"."notification_settings" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."order_cancellations" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."order_cancellations" TO "authenticated";
GRANT ALL ON TABLE "public"."order_cancellations" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."order_items" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."order_items" TO "authenticated";
GRANT ALL ON TABLE "public"."order_items" TO "service_role";



GRANT SELECT,MAINTAIN ON TABLE "public"."order_receipts" TO "authenticated";
GRANT ALL ON TABLE "public"."order_receipts" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."order_tracking" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."order_tracking" TO "authenticated";
GRANT ALL ON TABLE "public"."order_tracking" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."orders" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."orders" TO "authenticated";
GRANT ALL ON TABLE "public"."orders" TO "service_role";



GRANT ALL ON TABLE "public"."outbound_idempotency_cache" TO "service_role";



GRANT ALL ON SEQUENCE "public"."outbound_idempotency_cache_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."outbound_idempotency_cache_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."outbound_idempotency_cache_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."payment_reversal_requests" TO "service_role";
GRANT SELECT ON TABLE "public"."payment_reversal_requests" TO "authenticated";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."payments" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."payments" TO "authenticated";
GRANT ALL ON TABLE "public"."payments" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."payments_safe" TO "authenticated";
GRANT ALL ON TABLE "public"."payments_safe" TO "service_role";



GRANT ALL ON TABLE "public"."pii_access_log" TO "service_role";
GRANT SELECT ON TABLE "public"."pii_access_log" TO "authenticated";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."plan_capabilities" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."plan_capabilities" TO "authenticated";
GRANT ALL ON TABLE "public"."plan_capabilities" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."platform_categories" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."platform_categories" TO "authenticated";
GRANT ALL ON TABLE "public"."platform_categories" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."product_attribute_definitions" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."product_attribute_definitions" TO "authenticated";
GRANT ALL ON TABLE "public"."product_attribute_definitions" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."product_categories" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."product_categories" TO "authenticated";
GRANT ALL ON TABLE "public"."product_categories" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."product_variations" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."product_variations" TO "authenticated";
GRANT ALL ON TABLE "public"."product_variations" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."products" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."products" TO "authenticated";
GRANT ALL ON TABLE "public"."products" TO "service_role";



GRANT ALL ON TABLE "public"."provider_health_alert_dedup" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."purchase_order_items" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."purchase_order_items" TO "authenticated";
GRANT ALL ON TABLE "public"."purchase_order_items" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."purchase_orders" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."purchase_orders" TO "authenticated";
GRANT ALL ON TABLE "public"."purchase_orders" TO "service_role";



GRANT ALL ON TABLE "public"."rate_limit_windows" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."retention_policies" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."retention_policies" TO "authenticated";
GRANT ALL ON TABLE "public"."retention_policies" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."review_queue" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."review_queue" TO "authenticated";
GRANT ALL ON TABLE "public"."review_queue" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."rma_requests" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."rma_requests" TO "authenticated";
GRANT ALL ON TABLE "public"."rma_requests" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."shipment_tracking_events" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."shipment_tracking_events" TO "authenticated";
GRANT ALL ON TABLE "public"."shipment_tracking_events" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."shipments" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."shipments" TO "authenticated";
GRANT ALL ON TABLE "public"."shipments" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."stock_movements" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."stock_movements" TO "authenticated";
GRANT ALL ON TABLE "public"."stock_movements" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."stock_reservations" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."stock_reservations" TO "authenticated";
GRANT ALL ON TABLE "public"."stock_reservations" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."suppliers" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."suppliers" TO "authenticated";
GRANT ALL ON TABLE "public"."suppliers" TO "service_role";



GRANT ALL ON TABLE "public"."telegram_alert_messages" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_cancellation_policy" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_cancellation_policy" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_cancellation_policy" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_carriers" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_carriers" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_carriers" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tenant_carriers_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tenant_carriers_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tenant_carriers_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_integrations" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_integrations" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_integrations" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_legal_acceptance" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_legal_acceptance" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_legal_acceptance" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_offboarding_log" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_offboarding_log" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_offboarding_log" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tenant_offboarding_log_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tenant_offboarding_log_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tenant_offboarding_log_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_payment_methods" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_payment_methods" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_payment_methods" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tenant_payment_methods_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tenant_payment_methods_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tenant_payment_methods_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_provider_capabilities" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_provider_capabilities" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_provider_capabilities" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tenant_provider_capabilities_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tenant_provider_capabilities_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tenant_provider_capabilities_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_provider_health" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_provider_health" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_provider_health" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_provider_identity" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_provider_identity" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_provider_identity" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tenant_provider_identity_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tenant_provider_identity_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tenant_provider_identity_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_shipping_provider_config" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_shipping_provider_config" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_shipping_provider_config" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_subscriptions" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_subscriptions" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_subscriptions" TO "service_role";



GRANT ALL ON TABLE "public"."tenant_usage_counters" TO "service_role";



GRANT ALL ON TABLE "public"."tenant_usage_events" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_users" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_users" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_users" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_webhook_secrets" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenant_webhook_secrets" TO "authenticated";
GRANT ALL ON TABLE "public"."tenant_webhook_secrets" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tenant_webhook_secrets_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tenant_webhook_secrets_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tenant_webhook_secrets_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenants" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."tenants" TO "authenticated";
GRANT ALL ON TABLE "public"."tenants" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."user_dismissed_alerts" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."user_dismissed_alerts" TO "authenticated";
GRANT ALL ON TABLE "public"."user_dismissed_alerts" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."vw_consent_events_unified" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."vw_consent_events_unified" TO "authenticated";
GRANT ALL ON TABLE "public"."vw_consent_events_unified" TO "service_role";



GRANT ALL ON TABLE "public"."webhook_events_seen" TO "service_role";



GRANT ALL ON SEQUENCE "public"."webhook_events_seen_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."webhook_events_seen_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."webhook_events_seen_id_seq" TO "service_role";



GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."whatsapp_templates" TO "anon";
GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLE "public"."whatsapp_templates" TO "authenticated";
GRANT ALL ON TABLE "public"."whatsapp_templates" TO "service_role";



GRANT ALL ON TABLE "public"."whatsapp_webhook_inbox" TO "service_role";



GRANT ALL ON TABLE "public"."wompi_events_seen" TO "service_role";



GRANT ALL ON TABLE "public"."wompi_webhook_inbox" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT SELECT,INSERT,DELETE,MAINTAIN,UPDATE ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";




































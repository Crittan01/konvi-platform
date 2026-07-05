-- =============================================================================
-- Re-seed plantillas HSM KAIU: copy es-CO en TUTEO + marca parametrizada.
-- F7 (impl_templates_hsm decisión "Templates HSM multi-tenant: parametrizar
-- marca + copy es-CO consistente"). 2026-07-04.
--
-- MOTIVO (verificado):
--   1) El seed original (20260523000000_seed_kaiu_templates.sql) escribió el
--      body en VOSEO (podés / querés / dejaste / rastrealo acá). El bot habla
--      en TUTEO ("Tutea al cliente desde el inicio" — orchestrator.py:5587),
--      así que el proactivo HSM sonaba con otra voz que la conversación.
--   2) 'KAIU' estaba HARDCODEADO en el body de cart_abandoned_24h_v1
--      ("esperándote en KAIU"), lo que impide reutilizar la plantilla en otro
--      tenant. La marca se mueve a un FOOTER derivado de tenants.name
--      (parametrizado por-tenant, estático → sin variables de envío).
--
-- SEGURIDAD / DEGRADACIÓN:
--   - Sólo re-escribe filas en status='LOCAL_DRAFT' (WHERE en el DO UPDATE).
--     Una plantilla ya PENDING/APPROVED en Meta NO se toca: Meta es la fuente
--     de verdad de su copy y cambiarla acá desincronizaría DB↔Meta. Tras
--     aplicar, el founder re-submitea los drafts con submit_template_to_meta.py.
--   - Idempotente: re-aplicar produce el mismo estado (upsert determinista).
--   - NO cambia el CONTEO de parámetros del BODY (worker.py rellena posicional):
--       payment_reminder_v1  → 4 params {{1..4}}   (customer, order, total, url)
--       order_confirmation_v1→ 3 params {{1..3}}   (customer, order, total)
--       order_shipped_v1     → 4 params {{1..4}}   (customer, order, carrier, url)
--       cart_abandoned_24h_v1→ 3 params {{1..3}}   (customer, cart, discount)
--     El FOOTER es texto estático (sin {{}}) → whatsapp_sender no lo parametriza.
--
-- KAIU tenant_id: 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9
-- NO APLICAR automáticamente — coordinar con founder (re-submit posterior).
-- =============================================================================

DO $$
DECLARE
    v_tenant_id UUID := '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9'::uuid;
    v_waba_id   TEXT := '2159052118202272';
    -- Marca parametrizada: se lee de tenants.name (fallback 'KAIU' si el tenant
    -- no existe en este entorno). Vive en el FOOTER, no en el body.
    v_brand     TEXT;
    v_footer    JSONB;
BEGIN
  SELECT COALESCE(NULLIF(TRIM(t.name), ''), 'KAIU')
    INTO v_brand
    FROM public.tenants t
   WHERE t.id = v_tenant_id;
  IF v_brand IS NULL THEN
    v_brand := 'KAIU';
  END IF;
  -- FOOTER Meta: texto estático ≤ 60 chars. La marca del tenant va aquí.
  v_footer := jsonb_build_object('type', 'FOOTER', 'text', LEFT(v_brand, 60));

  -- 1. payment_reminder_v1 (UTILITY, 4 params) ------------------------------
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id, 'payment_reminder_v1', 'es_CO', 'UTILITY',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', 'Hola {{1}}, un recordatorio: tu pedido {{2}} por valor de ' ||
                '{{3}} sigue pendiente de pago. Puedes completar tu compra ' ||
                'aquí: {{4}}',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array(
              'Camila', 'KAIU-2026-0042', '$87.500 COP',
              'https://checkout.wompi.co/p/abc123'
            )
          )
        )
      ),
      v_footer
    ),
    'POSITIONAL', 'LOCAL_DRAFT', 'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO UPDATE
    SET components = EXCLUDED.components,
        category   = EXCLUDED.category,
        parameter_format = EXCLUDED.parameter_format,
        updated_at = NOW()
    WHERE public.whatsapp_templates.status = 'LOCAL_DRAFT';

  -- 2. order_confirmation_v1 (UTILITY, 3 params) ----------------------------
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id, 'order_confirmation_v1', 'es_CO', 'UTILITY',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', '¡Gracias por tu compra, {{1}}! Tu pedido {{2}} quedó ' ||
                'confirmado por {{3}}. Te avisamos apenas salga para envío.',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array('Camila', 'KAIU-2026-0042', '$87.500 COP')
          )
        )
      ),
      v_footer
    ),
    'POSITIONAL', 'LOCAL_DRAFT', 'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO UPDATE
    SET components = EXCLUDED.components,
        category   = EXCLUDED.category,
        parameter_format = EXCLUDED.parameter_format,
        updated_at = NOW()
    WHERE public.whatsapp_templates.status = 'LOCAL_DRAFT';

  -- 3. order_shipped_v1 (UTILITY, 4 params) ---------------------------------
  --    Ejemplo alineado a Aveonline (ADR-0019: proveedor de envío activo).
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id, 'order_shipped_v1', 'es_CO', 'UTILITY',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', '{{1}}, tu pedido {{2}} ya salió para envío con {{3}}. ' ||
                'Puedes rastrearlo aquí: {{4}}',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array(
              'Camila', 'KAIU-2026-0042', 'Aveonline',
              'https://www.aveonline.co/rastreo/AV123456789'
            )
          )
        )
      ),
      v_footer
    ),
    'POSITIONAL', 'LOCAL_DRAFT', 'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO UPDATE
    SET components = EXCLUDED.components,
        category   = EXCLUDED.category,
        parameter_format = EXCLUDED.parameter_format,
        updated_at = NOW()
    WHERE public.whatsapp_templates.status = 'LOCAL_DRAFT';

  -- 4. cart_abandoned_24h_v1 (MARKETING, 3 params) --------------------------
  --    Marca REMOVIDA del body ("en KAIU") → ahora en el FOOTER parametrizado.
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id, 'cart_abandoned_24h_v1', 'es_CO', 'MARKETING',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', 'Hola {{1}}, dejaste artículos en tu carrito: {{2}}. ' ||
                '¿Quieres terminar tu compra? Tenemos {{3}} de descuento ' ||
                'esperándote.',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array(
              'Camila', 'Jabón artesanal de coco x2', '10%'
            )
          )
        )
      ),
      v_footer
    ),
    'POSITIONAL', 'LOCAL_DRAFT', 'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO UPDATE
    SET components = EXCLUDED.components,
        category   = EXCLUDED.category,
        parameter_format = EXCLUDED.parameter_format,
        updated_at = NOW()
    WHERE public.whatsapp_templates.status = 'LOCAL_DRAFT';

END $$;

COMMENT ON TABLE public.whatsapp_templates IS
    'HSM templates per-tenant Meta WhatsApp Cloud API. Re-seed 2026-07-04: '
    'copy es-CO en TUTEO (alineado al tono del bot) + marca en FOOTER '
    'parametrizado desde tenants.name (antes KAIU hardcodeado en cart_abandoned). '
    'Re-escribe solo filas LOCAL_DRAFT; submit a Meta via '
    'scripts/admin/submit_template_to_meta.py.';

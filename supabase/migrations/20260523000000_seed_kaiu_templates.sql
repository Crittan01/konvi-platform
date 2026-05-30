-- =============================================================================
-- Seed 4 templates piloto KAIU (Sem 7 F2 item 6.a / 2026-05-17).
--
-- 4 templates en estado LOCAL_DRAFT para que KAIU pueda submitearlos a Meta
-- (review humana 15min-48h) y luego enviar mensajes proactivos fuera CSW:
--
--   1. payment_reminder_v1     UTILITY — recordatorio pago pendiente
--   2. order_confirmation_v1   UTILITY — confirmación tras pago
--   3. order_shipped_v1        UTILITY — notificación envío + tracking
--   4. cart_abandoned_24h_v1   MARKETING — recovery carrito 24h+
--
-- Status inicial: LOCAL_DRAFT (sin meta_template_id). Tras correr el script
-- scripts/admin/submit_template_to_meta.py, Konvi llama POST Meta y status
-- transiciona a PENDING. Tras review Meta envía webhook
-- message_template_status_update → status = APPROVED automático.
--
-- KAIU tenant_id hardcoded: 0fb0777e-f3e4-48c7-89bf-a25aa201c0c9
-- KAIU waba_id (de tenant_integrations.credentials): 2159052118202272
--
-- Idempotente: usa ON CONFLICT DO NOTHING (clave UNIQUE
-- tenant_id+name+language). Re-aplicar la migration no duplica.
--
-- Components estructura Meta v22:
--   - BODY con text + example.body_text (Meta exige example para approve)
--   - parameter_format POSITIONAL ({{1}}, {{2}}, etc.)
-- =============================================================================

DO $$
DECLARE
    v_tenant_id UUID := '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9'::uuid;
    v_waba_id   TEXT := '2159052118202272';
BEGIN

  -- 1. payment_reminder_v1 (UTILITY)
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id,
    'payment_reminder_v1',
    'es_CO',
    'UTILITY',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', 'Hola {{1}}, recordatorio amable: tu pedido {{2}} por ' ||
                'valor de {{3}} sigue pendiente de pago. Podés completar ' ||
                'tu compra acá: {{4}}',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array(
              'Camila', 'KAIU-2026-0042', '$87.500 COP',
              'https://checkout.wompi.co/p/abc123'
            )
          )
        )
      )
    ),
    'POSITIONAL',
    'LOCAL_DRAFT',
    'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO NOTHING;

  -- 2. order_confirmation_v1 (UTILITY)
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id,
    'order_confirmation_v1',
    'es_CO',
    'UTILITY',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', '¡Gracias por tu compra, {{1}}! Tu pedido {{2}} fue ' ||
                'confirmado por {{3}}. Te avisaremos cuando salga para envío.',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array('Camila', 'KAIU-2026-0042', '$87.500 COP')
          )
        )
      )
    ),
    'POSITIONAL',
    'LOCAL_DRAFT',
    'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO NOTHING;

  -- 3. order_shipped_v1 (UTILITY)
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id,
    'order_shipped_v1',
    'es_CO',
    'UTILITY',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', '{{1}}, tu pedido {{2}} ya salió para envío con {{3}}. ' ||
                'Podés rastrearlo acá: {{4}}',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array(
              'Camila', 'KAIU-2026-0042', 'Servientrega',
              'https://envia.com/tracking/SX123456789'
            )
          )
        )
      )
    ),
    'POSITIONAL',
    'LOCAL_DRAFT',
    'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO NOTHING;

  -- 4. cart_abandoned_24h_v1 (MARKETING — tier-paid + frequency cap)
  INSERT INTO public.whatsapp_templates (
    tenant_id, waba_id, name, language, category, components,
    parameter_format, status, quality_rating
  ) VALUES (
    v_tenant_id, v_waba_id,
    'cart_abandoned_24h_v1',
    'es_CO',
    'MARKETING',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'BODY',
        'text', 'Hola {{1}}, dejaste artículos en tu carrito: {{2}}. ' ||
                '¿Querés terminar tu compra? Tenemos {{3}} de descuento ' ||
                'esperándote en KAIU.',
        'example', jsonb_build_object(
          'body_text', jsonb_build_array(
            jsonb_build_array(
              'Camila', 'Jabón artesanal de coco x2', '10%'
            )
          )
        )
      )
    ),
    'POSITIONAL',
    'LOCAL_DRAFT',
    'UNKNOWN'
  )
  ON CONFLICT (tenant_id, name, language) DO NOTHING;

END $$;

COMMENT ON TABLE public.whatsapp_templates IS
    'HSM templates per-tenant Meta WhatsApp Cloud API. Sem 7 F2 (2026-05-17): '
    'sembrados 4 templates piloto KAIU (payment_reminder_v1, '
    'order_confirmation_v1, order_shipped_v1, cart_abandoned_24h_v1) en '
    'estado LOCAL_DRAFT. Submit a Meta via scripts/admin/submit_template_to_meta.py.';

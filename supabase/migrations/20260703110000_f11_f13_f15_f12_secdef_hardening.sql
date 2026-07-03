-- FASE 0 seguridad — hardening de funciones SECURITY DEFINER + RLS (audit F11, F13, F15, F12).
-- Firmas verificadas contra pg_proc de la DB viva (nada por supuesto). El único caller de todas estas
-- funciones es service_role (api/worker); anon/authenticated NUNCA las necesitan.
--
-- F11 (HIGH): los 3 helpers pgmq de la cola de salida WhatsApp son SECURITY DEFINER sin REVOKE → un
--   authenticated podía encolar {tenant_id: víctima, text: arbitrario} y hacer que el WhatsApp de otro
--   tenant enviara mensajes (impersonación/spam a su costa). REVOKE cierra el vector.
-- F13 (MED): dedup/rate-limit SECURITY DEFINER sin REVOKE → un authenticated podía pre-registrar
--   event_uids (descartar webhooks legítimos como "duplicados") o falsear el rate limiter.
-- F15 (LOW): SECURITY DEFINER sin SET search_path fijo → vector search_path (CVE-2018-1058, Supabase Advisor).
-- F12 (MED/IaC): meli_webhook_dedup es la ÚNICA tabla public sin RLS → INSERT/DELETE directo por
--   anon/authenticated vía PostgREST. La RPC meli_webhook_seen ya es SECURITY DEFINER (no requiere acceso
--   directo de authenticated).

-- ── F11: cola de salida WhatsApp (pgmq) ──────────────────────────────────────
REVOKE ALL ON FUNCTION public.enqueue_whatsapp_outbound_message(jsonb, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dequeue_whatsapp_outbound_messages(integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ack_whatsapp_outbound_message(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_whatsapp_outbound_message(jsonb, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.dequeue_whatsapp_outbound_messages(integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.ack_whatsapp_outbound_message(bigint) TO service_role;

-- ── F13: dedup de webhooks + rate limiter ────────────────────────────────────
REVOKE ALL ON FUNCTION public.webhook_event_check_or_register(text, text, uuid, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.webhook_event_mark_processed(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.meli_webhook_seen(text, text, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rate_limit_hit(text, integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cleanup_expired_meli_webhook_dedup() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.webhook_event_check_or_register(text, text, uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.webhook_event_mark_processed(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.meli_webhook_seen(text, text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.rate_limit_hit(text, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.cleanup_expired_meli_webhook_dedup() TO service_role;

-- ── F15: fijar search_path en las SECURITY DEFINER vivas que no lo tienen ─────
-- (add_member_to_tenant se fija en 20260703100000_f10. Las outbound_idempotency_* NO se tocan aquí:
--  son código muerto sin consumidores (audit F111) → se dropean en la fase de limpieza.)
ALTER FUNCTION public.webhook_event_check_or_register(text, text, uuid, text, text) SET search_path = public;
ALTER FUNCTION public.webhook_event_mark_processed(text, text) SET search_path = public;
ALTER FUNCTION public.meli_webhook_seen(text, text, text, integer) SET search_path = public;
ALTER FUNCTION public.rate_limit_hit(text, integer, integer) SET search_path = public;
ALTER FUNCTION public.cleanup_expired_meli_webhook_dedup() SET search_path = public;

-- ── F12: RLS + REVOKE en la única tabla public sin aislamiento ───────────────
ALTER TABLE public.meli_webhook_dedup ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.meli_webhook_dedup FROM anon, authenticated;

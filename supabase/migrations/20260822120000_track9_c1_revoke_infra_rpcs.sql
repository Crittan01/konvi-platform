-- =============================================================================
-- Track 9 / C1 (crítico) — REVOKE de RPCs de infraestructura a roles de cliente
-- Fecha: 2026-08-22 · Origen: PLAN-CIERRE §Track 9 (auditoría RLS/grants 2026-08-22)
--
-- Hallazgos (verificados con exploit ejecutado contra DB live, tests dbharness
-- test_track9_c1_infra_rpcs.py — los 5 ataques funcionaban antes del fix):
--
--   1. dequeue_human_takeover_notifications / ack_human_takeover_notification:
--      la cola pgmq de escalaciones es GLOBAL (sin filtro de tenant) y el payload
--      lleva customer_phone (PII). Cualquier `authenticated` podía leer PII de
--      clientes de TODOS los tenants y borrar mensajes (DoS de escalaciones).
--      Caller legítimo: el worker (service_role) — services/ai-orchestrator/worker.py.
--
--   2. upsert_aveonline_idagente (20260822020000): nació con GRANT a
--      authenticated + el default de Supabase la dejó ejecutable hasta por ANON
--      (sin login). Exploit verificado: `SET ROLE anon; SELECT upsert_...(...)`
--      pisó credentials.idagente ('6135' → '9999'). Callers legítimos:
--      AveonlineClient (api/orchestrator) con service_role.
--
-- Patrón (post-norma 20260725090000/20260727150000): REVOKE ALL de PUBLIC, anon
-- y authenticated (PUBLIC incluido: de ahí "re-nace" el grant si alguien re-crea
-- la función desde una versión vieja) + GRANT explícito solo a service_role.
-- Si alguna firma no existe, el REVOKE falla y la migración revienta (fail-loud:
-- preferimos eso a creer que cerramos algo que no existía).
-- =============================================================================

REVOKE ALL ON FUNCTION public.dequeue_human_takeover_notifications(integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ack_human_takeover_notification(bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.upsert_aveonline_idagente(uuid, text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.dequeue_human_takeover_notifications(integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.ack_human_takeover_notification(bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.upsert_aveonline_idagente(uuid, text) TO service_role;

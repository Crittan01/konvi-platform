-- =============================================================================
-- Stock Reservations — pg_cron schedule (rev. 109 cierre).
-- Fecha: 2026-06-05
--
-- La migration 20260502000000_stock_reservations.sql creó la función
-- `fn_expire_stock_reservations()` pero NO la scheduleó. Esta migration
-- completa el ciclo de vida agregando el cron job.
--
-- Frecuencia: cada minuto. Justification:
--   • TTL típico cart soft = 15 min (add_to_cart).
--   • TTL checkout hard = 35 min (post-generate_payment_link).
--   • Sin barrido frecuente, reservas vencidas siguen descontando del
--     stock available hasta el siguiente run.
--   • La función filtra por status='active' AND expires_at <= NOW() (index
--     idx_stock_res_expired_sweep), costo despreciable.
--
-- Defense in depth: aunque `fn_variation_available_stock()` ya filtra
-- defensivamente `expires_at > NOW()`, el barrido marca las filas con
-- status='expired' liberando indices y mejorando observability.
--
-- IDEMPOTENT: si el job ya existe, se elimina antes de re-crear.
-- =============================================================================

DO $$
BEGIN
  -- Limpiar schedule previo si existe (idempotente).
  PERFORM cron.unschedule(jobid)
  FROM cron.job
  WHERE jobname = 'expire_stock_reservations';

  PERFORM cron.schedule(
    'expire_stock_reservations',
    '* * * * *',  -- cada minuto.
    $cron$ SELECT public.fn_expire_stock_reservations(); $cron$
  );

  RAISE NOTICE 'Scheduled expire_stock_reservations cada minuto via pg_cron.';
EXCEPTION WHEN undefined_table THEN
  -- pg_cron no instalado (CI/local sin extension): la función queda creada
  -- y puede invocarse manualmente. El fallback aplicativo en worker.py
  -- también puede llamar fn_expire_stock_reservations periódicamente.
  RAISE NOTICE 'pg_cron no disponible; fn_expire_stock_reservations queda manual.';
END $$;

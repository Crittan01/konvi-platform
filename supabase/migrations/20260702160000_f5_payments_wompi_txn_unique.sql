-- F5 (roadmap producción) — no duplicar registros de pago por transacción Wompi.
--
-- El webhook Wompi puede reintentar; sin unicidad, una misma transacción podría insertar 2 filas en payments
-- (doble contabilidad / reconciliación ambigua). Índice UNIQUE PARCIAL: único cuando wompi_txn_id está presente,
-- permite múltiples NULL (intents pending sin txn aún). Verificado pre-aplicación: 0 wompi_txn_id duplicados.
-- Idempotente (IF NOT EXISTS).

CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_wompi_txn_id
  ON public.payments (wompi_txn_id)
  WHERE wompi_txn_id IS NOT NULL;

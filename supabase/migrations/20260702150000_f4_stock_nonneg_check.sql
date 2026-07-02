-- F4 (roadmap producción) — integridad de inventario: stock nunca negativo.
--
-- Defensa en profundidad: aunque el flujo de reserva/consumo debe impedirlo, un CHECK garantiza a nivel DB
-- que product_variations.stock_quantity >= 0 (ADR-0024 criterio binario). Verificado pre-aplicación: 0 filas
-- con stock < 0. Idempotente (guardado por existencia de constraint).

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'product_variations_stock_nonneg'
  ) THEN
    ALTER TABLE public.product_variations
      ADD CONSTRAINT product_variations_stock_nonneg CHECK (stock_quantity >= 0);
  END IF;
END $$;

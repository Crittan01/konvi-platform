-- Migration: 20260704153000_purchases_supplier_softdelete_fk_status.sql
-- Módulo Compras (F3). Idempotente. NO aplicada por el agente — aplicar en remote
-- tras revisión del founder (protocolo de migraciones con drift del ledger).
--
-- Tres cambios, todos degradables/seguros; el código de app ya funciona sin ellos:
--   1) suppliers.is_active  → soft-delete de proveedores (nunca hard-delete: el
--      proveedor está referenciado por purchase_orders y borrarlo destruye historial).
--   2) purchase_orders.supplier_id FK  CASCADE → RESTRICT: evita que un DELETE de
--      proveedor arrastre en cascada todo el historial de compras. El camino
--      sancionado es desactivar (is_active=false), no borrar.
--   3) purchase_orders.status CHECK podado a ('ordered','received','cancelled') +
--      default 'ordered': el backend nunca emite 'draft'/'in_transit' y la recepción
--      es todo-o-nada. Guardado: solo se aplica si no hay filas con esos estados,
--      para no romper datos legados.

-- ── 1) Soft-delete de proveedores ────────────────────────────────────────────
ALTER TABLE public.suppliers
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

-- Índice parcial para listar activos rápido (no crítico, barato).
CREATE INDEX IF NOT EXISTS idx_suppliers_tenant_active
  ON public.suppliers (tenant_id)
  WHERE is_active;

-- ── 2) FK supplier_id: CASCADE → RESTRICT ────────────────────────────────────
-- El nombre auto-generado del FK inline es purchase_orders_supplier_id_fkey.
-- Lo redefinimos por su definición real (descubierta en el catálogo) para ser
-- robustos ante nombres divergentes por drift.
DO $$
DECLARE
  con_name text;
BEGIN
  SELECT c.conname INTO con_name
  FROM pg_constraint c
  JOIN pg_class t   ON t.oid = c.conrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  WHERE n.nspname = 'public'
    AND t.relname = 'purchase_orders'
    AND c.contype = 'f'
    AND c.confdeltype = 'c'                       -- 'c' = ON DELETE CASCADE
    AND (SELECT array_agg(a.attname ORDER BY a.attnum)
         FROM unnest(c.conkey) k
         JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k)
        = ARRAY['supplier_id']
  LIMIT 1;

  IF con_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.purchase_orders DROP CONSTRAINT %I', con_name);
    ALTER TABLE public.purchase_orders
      ADD CONSTRAINT purchase_orders_supplier_id_fkey
      FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id) ON DELETE RESTRICT;
  END IF;
END $$;

-- ── 3) Poda del CHECK de status (guardada contra datos legados) ──────────────
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.purchase_orders
    WHERE status NOT IN ('ordered', 'received', 'cancelled')
  ) THEN
    ALTER TABLE public.purchase_orders
      DROP CONSTRAINT IF EXISTS purchase_orders_status_check;
    ALTER TABLE public.purchase_orders
      ADD CONSTRAINT purchase_orders_status_check
      CHECK (status IN ('ordered', 'received', 'cancelled'));
    ALTER TABLE public.purchase_orders
      ALTER COLUMN status SET DEFAULT 'ordered';
  ELSE
    RAISE NOTICE 'purchase_orders: filas con status legado (draft/in_transit) presentes; se omite el tightening del CHECK.';
  END IF;
END $$;

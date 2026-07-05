-- ─────────────────────────────────────────────────────────────────────────────
-- Migración: numeración humana consecutiva de órdenes de compra (OC-001) por
-- tenant. Módulo Compras (F-transversales 2026-07-04). Idempotente, no destructiva.
--
-- Problema: la consola muestra el prefijo del UUID de la OC ("OC 3F2A9B1C"), que
-- el operador no puede citar por teléfono/WhatsApp al proveedor. Numeración
-- consecutiva por-tenant (OC-001, OC-002, …) es ergonomía estándar de compras.
--
-- Estrategia:
--   1) purchase_orders.po_number bigint — secuencia consecutiva POR TENANT.
--   2) Backfill de filas existentes: row_number() por tenant ordenado por
--      created_at (empate → id) para preservar el orden histórico real.
--   3) Trigger BEFORE INSERT que asigna el siguiente número por tenant bajo un
--      advisory lock transaccional (serializa inserts concurrentes del MISMO
--      tenant; tenants distintos no se bloquean entre sí).
--   4) Índice único parcial (tenant_id, po_number).
--
-- Degradación segura: el backend NO envía po_number en el INSERT (lo asigna el
-- trigger) y la UI cae al prefijo UUID si la columna aún no existe. Aplicar la
-- migración solo AÑADE la numeración; nada se rompe si está pendiente.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── 1) Columna ────────────────────────────────────────────────────────────────
ALTER TABLE public.purchase_orders
  ADD COLUMN IF NOT EXISTS po_number bigint;

-- ── 2) Backfill idempotente (solo filas sin número) ──────────────────────────
-- Numera cada tenant desde 1 respetando el orden cronológico de creación.
WITH numbered AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY tenant_id
      ORDER BY created_at ASC, id ASC
    ) AS rn
  FROM public.purchase_orders
  WHERE po_number IS NULL
)
UPDATE public.purchase_orders po
SET po_number = n.rn
FROM numbered n
WHERE po.id = n.id
  AND po.po_number IS NULL;

-- ── 3) Trigger de asignación por-tenant ──────────────────────────────────────
CREATE OR REPLACE FUNCTION public.assign_purchase_order_number()
RETURNS TRIGGER
LANGUAGE plpgsql
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

DROP TRIGGER IF EXISTS trg_assign_purchase_order_number ON public.purchase_orders;
CREATE TRIGGER trg_assign_purchase_order_number
  BEFORE INSERT ON public.purchase_orders
  FOR EACH ROW
  EXECUTE FUNCTION public.assign_purchase_order_number();

-- ── 4) Unicidad por tenant ────────────────────────────────────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_orders_tenant_po_number
  ON public.purchase_orders (tenant_id, po_number)
  WHERE po_number IS NOT NULL;

COMMENT ON COLUMN public.purchase_orders.po_number IS
  'Número humano consecutivo POR TENANT (OC-001, OC-002, …). Asignado por el '
  'trigger assign_purchase_order_number bajo advisory lock. UI lo formatea; '
  'cae al prefijo UUID si la columna no está poblada. F-transversales.';

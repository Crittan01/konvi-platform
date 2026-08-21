-- B1 (auditoría money-path 2026-08-21) — carrera de órdenes duplicadas por conversación.
--
-- Hallazgo: `_find_pending_order` (services/ai-orchestrator/tools/payment_link_tool.py)
-- es read-then-act sin lock: dos turnos concurrentes de la MISMA conversación no ven
-- la orden del otro → ambos insertan `orders.status='pending_payment'` → 2 links Wompi
-- pagables → doble cobro al cliente.
--
-- Fix: índice único parcial a nivel DB (la capa de aplicación adopta la orden ganadora
-- al chocar con 23505 — patrón adopt-winner en services/api/routers/orders.py).
-- La unicidad es por (tenant_id, conversation_id) SOLO en estado pending_payment:
-- una vez confirmada/cancelada la conversación puede tener otras órdenes.
-- conversation_id NULL (pedidos manuales del Inbox) no participa: Postgres trata
-- los NULL como distintos entre sí en índices únicos.
--
-- Pre-paso defensivo: si la carrera ya dejó duplicados en prod, el CREATE UNIQUE
-- INDEX fallaría. Se conserva la orden más reciente por (tenant, conversación) y
-- se cancelan las demás (sus payments pendientes quedan voided para que el link
-- viejo deje de ser cobrable por esta vía; Wompi expira el link por TTL igualmente).
--
-- Forward-only. Idempotente (IF NOT EXISTS). Sin CONCURRENTLY a propósito: la
-- migración de Supabase corre en transacción y la tabla es pequeña.

BEGIN;

-- 1. Dedup defensivo pre-índice (no-op si no hay duplicados).
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY tenant_id, conversation_id
            ORDER BY created_at DESC, id DESC
        ) AS rn
    FROM public.orders
    WHERE status = 'pending_payment'
      AND conversation_id IS NOT NULL
)
UPDATE public.orders o
SET status     = 'cancelled',
    notes      = COALESCE(o.notes || ' ', '')
                 || '[dedup_pending_payment_20260821: cancelada por duplicado de carrera]',
    updated_at = NOW()
FROM ranked
WHERE o.id = ranked.id
  AND ranked.rn > 1;

-- 2. Anular los payments aún pendientes de las órdenes recién canceladas.
UPDATE public.payments p
SET status = 'voided'
WHERE p.status = 'pending'
  AND EXISTS (
      SELECT 1
      FROM public.orders o
      WHERE o.id = p.order_id
        AND o.tenant_id = p.tenant_id
        AND o.status = 'cancelled'
        AND o.notes LIKE '%[dedup_pending_payment_20260821:%'
  );

-- 3. La barrera real: una sola orden pending_payment por conversación.
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_one_pending_payment_per_conversation
    ON public.orders (tenant_id, conversation_id)
    WHERE status = 'pending_payment';

COMMENT ON INDEX public.uq_orders_one_pending_payment_per_conversation IS
    'B1: anti doble-cobro. Una conversación = una orden pending_payment activa. '
    'El insert perdedor (23505) adopta la orden ganadora (services/api/routers/orders.py create_order).';

COMMIT;

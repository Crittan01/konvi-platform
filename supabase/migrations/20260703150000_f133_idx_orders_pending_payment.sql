-- F133 (audit fullstack-review-2026-07-03 · MEDIUM) — índice parcial para los crons de pending_payment.
--
-- worker._send_payment_reminders_if_due (cada 60s) y _release_expired_pending_payment_orders (cada 600s)
-- filtran orders cross-tenant por status='pending_payment' + rango de created_at. El único índice existente
-- (idx_orders_status ON orders(tenant_id, status)) tiene tenant_id como columna líder, que NO aparece en el
-- predicado → Postgres hace sequential scan de toda la tabla orders cada 60s, para siempre (a 100k órdenes,
-- ~1440 seq scans/día para encontrar típicamente 0-5 filas). Precedente del propio repo: idx_conversations_
-- human_takeover_at y idx_conversation_carts_open_ttl son índices PARCIALES por status — mismo patrón.
--
-- Índice parcial (solo las filas pending_payment, típicamente pocas) ordenado por created_at para servir el
-- rango temporal de ambos crons. NOTA: para tabla grande + tráfico, aplicar como CREATE INDEX CONCURRENTLY.

CREATE INDEX IF NOT EXISTS idx_orders_pending_payment_created
  ON public.orders (created_at)
  WHERE status = 'pending_payment';

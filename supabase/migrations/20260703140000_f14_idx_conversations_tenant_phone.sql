-- F14 (audit fullstack-review-2026-07-03 · MEDIUM) — índice del hot-path inbound de WhatsApp.
--
-- En CADA mensaje entrante el connector ejecuta:
--   conversations WHERE tenant_id=X AND customer_phone=Y ORDER BY last_interaction_at DESC LIMIT 1
-- (services/connector-whatsapp/services/db_persistence.py). Los índices existentes sobre conversations
-- son (tenant_id, last_interaction_at DESC), (tenant_id, channel) y (agentic_state) — ninguno cubre
-- customer_phone → a medida que crece la tabla por tenant, este lookup caliente degrada a scan.
--
-- NOTA DE APLICACIÓN: en KAIU (single-tenant, tabla pequeña) el CREATE es instantáneo. Si en el futuro
-- la tabla es grande y hay tráfico de escritura, aplicar como
--   CREATE INDEX CONCURRENTLY ...   (fuera de transacción, evita el lock de escritura durante el build).

CREATE INDEX IF NOT EXISTS idx_conversations_tenant_phone
  ON public.conversations (tenant_id, customer_phone);

-- Rev. 109 punto #1 backlog — Retracto categories multi-tenant agnóstico.
--
-- PROBLEMA QUE RESUELVE:
-- ─────────────────────
-- Hoy `tenant_cancellation_policy.retracto_excluded_categories` define
-- conceptualmente qué categorías están excluidas del derecho de retracto
-- (Ley 1480 Art. 47 parágrafo), pero NO hay enforcement automático
-- porque `products` no tiene mapping al concepto de "excluido".
--
-- El bot escalaba SIEMPRE a humano (conservador correcto), pero ahora
-- queremos enforcement determinístico cuando el tenant configuró el flag
-- por producto.
--
-- DISEÑO MULTI-TENANT AGNÓSTICO:
-- ───────────────────────────────
-- En lugar de hardcodear taxonomía vertical-específica ("cosmetica_abierta",
-- "software_descargable", etc.), agregamos UN FLAG BOOLEAN por producto +
-- UN CAMPO TEXT con la razón legal. Cada tenant decide qué productos
-- marcar según su vertical:
--
--   KAIU (cosmética):  jabones abiertos → retracto_excluded=true
--                      reason='cosmética uso íntimo (Art. 47 parágrafo)'
--
--   Tienda Tech:       software descargable → retracto_excluded=true
--                      reason='software descargado/activado (Art. 47 parágrafo)'
--
--   Tienda Comida:     perecederos → retracto_excluded=true
--                      reason='producto perecedero (Art. 47 parágrafo)'
--
-- Por default todos los productos son retracto-eligible (campo NULL/false),
-- preservando seguridad legal: el cliente puede ejercer retracto a menos
-- que el tenant explícitamente marque el producto como excluido.
--
-- INTEGRACIÓN CANCEL PIPELINE:
-- ────────────────────────────
-- agentic/dispatcher.py retracto path llama lib/retracto.py
-- check_retracto_eligibility(order_id) → returns:
--   (eligible: bool, excluded_items: list[dict], reasons: list[str])
--
-- Si excluded_items NO vacío → mensaje cauteloso al cliente citando
-- razón legal específica + escala a operador.
-- Si vacío → bot procede con retracto flow normal (RMA + refund).

ALTER TABLE products
  ADD COLUMN IF NOT EXISTS retracto_excluded BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS retracto_excluded_reason TEXT;

-- Index parcial para queries del cancel pipeline (solo productos excluidos
-- son interesantes; productos eligibles son la mayoría).
CREATE INDEX IF NOT EXISTS products_retracto_excluded_idx
  ON products (tenant_id, retracto_excluded)
  WHERE retracto_excluded = TRUE;

COMMENT ON COLUMN products.retracto_excluded IS
  'Si TRUE, el producto NO aplica retracto Art. 47 Ley 1480. Tenant decide '
  'según su vertical (cosmética abierta, software descargable, perecederos, '
  'etc.). Campo multi-tenant agnóstico.';

COMMENT ON COLUMN products.retracto_excluded_reason IS
  'Razón legal libre que el bot cita cuando rechaza retracto. Ejemplo: '
  '"cosmética uso íntimo (Art. 47 parágrafo)" o "software descargado".';

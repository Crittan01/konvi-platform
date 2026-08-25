-- Track 5 · M2.4 — claims.reason_detail (decisión founder 2026-08-25 #3)
--
-- Vocabulario CERRADO en `reason` + detalle libre opcional en `reason_detail`:
-- recupera la analítica por causal (reason cerrado, espejo del REASON_MAP de la
-- UI) sin perder la expresividad del texto libre que el cliente le dicta al bot.
-- Nullable, sin backfill: los reclamos históricos conservan su reason (cerrado
-- vía API, libre vía bot) y el writer unificado (konvi_domain.claims) llena
-- reason_detail solo cuando el canal lo captura (trim, máx 500 — mismo límite
-- que el free-text del bot). La DB NO lleva CHECK de reason a propósito: el bot
-- congelado sigue escribiendo free-text hasta que adopte el contrato (B-2/M3).

ALTER TABLE public.claims ADD COLUMN IF NOT EXISTS reason_detail TEXT;

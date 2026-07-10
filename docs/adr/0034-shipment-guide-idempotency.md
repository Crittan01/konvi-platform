# ADR-0034 — BLOQUE B (item 5): Idempotencia de generación de guía (claim-before-bill)

- **Estado:** Aceptado (2026-07-10) — reforzado por revisión adversarial multi-agente (16 agentes).
- **Contexto:** `_generate_shipping_guide_async` (auto post-pago) llamaba a Aveonline `generate_guide`
  (que **factura dinero real** si `simulate=False`) y persistía el `shipment` DESPUÉS, sin ningún guard.
  Una 2ª invocación (webhook Wompi duplicado, retry, cron de reconciliación de item 4) facturaba OTRA
  guía → **cobro duplicado real**. No existía UNIQUE por orden. Verificado contra HEAD.

## Decisión

### Claim-before-bill + índice único parcial
Antes de facturar se INSERTA una fila `shipments` en estado **`generating`**. Un índice único parcial
`(tenant_id, order_id) WHERE status IN ('generating','labeled','simulated')` garantiza a lo sumo UNA guía
activa/generada por orden: el 2º INSERT concurrente/retry falla con `unique_violation` → esa invocación
**NO factura** (idempotente). El billing solo ocurre si el claim se ganó.

### Manejo de excepciones money-safe (distinguido por si hubo dinero en juego)
- **`simulate=True`** (guías reales OFF — estado por default): NO hubo cobro → el claim pasa a
  `pending_generation` (fuera del índice) → **reintento seguro**. Evita varar silenciosamente el caso común.
- **`simulate=False` + excepción/timeout**: la guía **pudo** facturarse (AMBIGUO, Aveonline no ofrece
  lookup confiable guía↔orden). Money-safe: el claim queda `generating` (en el índice → **bloquea
  auto-retry**) con el error en `quote_response` → **resolución manual del operador** (verificar en
  Aveonline) en vez de arriesgar doble cobro con un reintento ciego.
- **`not-ok` de Aveonline** (respondió error → definitivamente NO facturó): `pending_generation` (retry).
- **UPDATE final resiliente** (2 intentos): si una guía REAL se facturó pero el tracking no se persiste,
  se loguea a nivel `error` con el tracking (recuperable) — la guía existe en Aveonline aunque la DB falle.
- El estado `generating` se agregó al catálogo de badges del UI con un hint que advierte verificar en
  Aveonline antes de reintentar (no queda como estado crudo silencioso).

## Consecuencias
- **Positiva:** cierra el cobro duplicado real (objetivo del item, confirmado por la revisión adversarial).
  En el estado por default (guías simuladas) no hay varado silencioso ni dinero en juego.
- **Trade-off aceptado:** para guías REALES, un timeout ambiguo deja el claim `generating` requiriendo
  resolución manual — se prioriza *no duplicar cobro* sobre *evitar un varado raro y recuperable*.

## ⚠️ Follow-ups OBLIGATORIOS antes de activar guías reales por-tenant (real_guides_enabled=true)
Estos NO bloquean el estado actual (guías OFF) pero DEBEN cerrarse antes de que un tenant facture real:
1. **Superficie de resolución de `generating` atascado (guía real):** acción de operador para, tras
   verificar en Aveonline, (a) marcar `labeled` con el tracking real, o (b) descartar el claim y regenerar.
   Hoy la recuperación de un `generating` real es solo por logs/DB (el retry manual choca con el índice).
2. **Dedup pre-migración:** el índice único falla al aplicar si prod ya tiene filas duplicadas
   `(tenant_id, order_id)` en `('generating','labeled','simulated')` (bug previo pudo crear `simulated`
   duplicados). Deduplicar (conservar la más reciente con tracking) ANTES del `CREATE UNIQUE INDEX`.
3. **Ventana de doble cobro del dry-run:** el endpoint owner `guide-dry-run` con `simulate=False`
   (real_guides ON) factura una guía real y NO persiste `shipments` → el claim automático no la ve y el
   webhook factura una 2ª. Hacer que el dry-run participe del claim o persista una fila.

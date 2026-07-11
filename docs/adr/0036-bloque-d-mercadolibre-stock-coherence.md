# ADR-0036 — BLOQUE D (Mercado Libre): coherencia de stock cross-canal, cancelación y hardening del webhook

- **Estado:** Aceptado (2026-07-11). Reforzado por revisión adversarial en 2 pasadas (10 + N agentes). Continuación scopeada abajo (item 3-parte1, item 5).
- **Contexto:** Auditoría production-readiness §D (5 hallazgos). Verificados contra HEAD:
  1. **Oversell cross-canal:** una orden MeLi que transiciona a *paid* NO decrementaba stock salvo en la rama de orden nueva; la rama de orden existente no lo hacía → inventario fantasma, otros canales sobre-venden unidades ya vendidas en MeLi.
  2. **Sync zera variaciones no mapeadas:** `sync_meli_stock` ponía `available_quantity=0` a las variaciones MeLi distintas de la sincronizada (MeLi exige el array COMPLETO en el PUT) → una venta de OTRA variación dejaba sin stock las nativas/no mapeadas.
  3. **Webhook IPN sin autenticación robusta:** MeLi **no firma** los webhooks (ni HMAC ni JWT — única defensa documentada = IP allowlist); la IP se derivaba de `X-Forwarded-For[0]` (hop controlado por el cliente) y el `resource` del body iba directo a `GET {api}{resource}` con el token del seller sin validar.
  4. **Cancelación no repone stock** en los paths MeLi y consola → inventario inflado permanente.
  5. **Refund del comprador prometido no se ejecuta.**

## Decisión

Reutilizar el RPC atómico e idempotente de [ADR-0035] (`rpc_stock_decrement`/`rpc_stock_restore`,
guard por `(order_id, variation_id, reason)`) como base de la coherencia de stock del canal MeLi.

### Implementado (items 1, 2, 4, 3-parte2)
- **Item 1 — oversell.** `_process_order` decrementa vía `rpc_stock_decrement` (reason='sale',
  agregado por variación) tanto en orden nueva como existente. Tras la revisión adversarial el guard
  se **desacopló del `old_status`**: decrementa la PRIMERA vez que la orden se sabe pagada
  (`internal_status=='confirmed' and old_status!='cancelled'`), sea cual sea el estado previo —
  porque MeLi **no garantiza el orden de los webhooks** y un `shipments` puede mover la orden a
  `processing` (que no decrementa) ANTES de llegar el `paid`. La idempotencia del RPC hace que
  re-llamarlo sobre una orden ya decrementada sea no-op (no doble-decremento).
- **Status monotónico.** El UPDATE de status en `_process_order` pasó a ser **monotónico** vía
  `_STATUS_RANK` (constante de módulo, compartida con `_process_shipment`): un `orders_v2` tardío
  (MeLi mantiene `order.status='paid'` durante todo el fulfillment) ya NO regresa `shipped/delivered`
  → `confirmed`. `cancelled` es terminal.
- **Item 4 — reposición en cancelación.** Espejo `_restore_stock_for_meli_order` (webhook) +
  `_restore_stock_on_cancel` (consola/API `patch_order` →cancelled). Ambos leen los movimientos
  reales `'sale'`/`'reservation_consumed'` (repone SOLO lo realmente decrementado, respetando el
  clamp de over-sell) y usan **`reason='cancellation_refund'` — el MISMO** que el pipeline
  orchestrator (`order_cancellation.py`) → el idempotency key colisiona cross-path → dos caminos de
  cancelación (consola + webhook + orchestrator) reponen UNA sola vez. El set de estados
  restore-elegibles incluye `'delivered'` (una cancelación/devolución post-entrega también repone).
- **Item 2 — sync no zera.** Para variaciones MeLi no-target, `sync_meli_stock` escribe la **verdad
  de Supabase** (stock de la variación local mapeada, resuelto vía `marketplace_listings` →
  `product_variations`), no el eco del GET; variaciones MeLi sin mapeo local preservan el GET (mejor
  esfuerzo). Convergen a la verdad local en vez de cementar deriva o zerar.
- **Item 3-parte2 — validación de `resource`.** `_is_valid_resource` rechaza, ANTES del GET
  autenticado, cualquier `resource` cuyo path no sea `/orders//items//shipments` + un único segmento
  (prefijo estricto + sin `/`,`?`,`#` → bloquea path-traversal y cambio de endpoint, que es el vector
  SSRF real, sin fail-closed frágil sobre el formato del id).

### Remediación de la revisión adversarial (pasada 1 — 4 hallazgos reales)
- **A/B (MEDIUM):** decremento con guard `old_status in (pending,*)` demasiado estrecho → oversell si
  `shipments` adelantó la orden antes del `paid`. → desacople del `old_status` (arriba).
- **B (MEDIUM):** UPDATE de status incondicional regresaba `shipped/delivered`→`confirmed`. → guard
  monotónico `_STATUS_RANK` (arriba).
- **C (LOW):** `delivered`→`cancelled` no reponía. → `'delivered'` añadido al set restore-elegible.
- **D (MEDIUM):** eco del GET reintroducía lost-update entre syncs concurrentes del mismo item. →
  resolución del hermano desde Supabase (arriba); converge bajo la mayoría de interleavings.

### Remediación de la revisión adversarial (pasada 2 — 1 hallazgo real)
- **Twin zero-out (MEDIUM):** el fix D se aplicó solo al sync automático (`sync_meli_stock`); el
  gemelo manual (`sync_stock_from_supabase`, botón "sincronizar stock" de la consola) conservaba el
  `else 0` → zeraba variaciones nativas/no mapeadas al forzar sync. Fix incompleto (1 de 2 gemelos).
  → construcción del `variations_for_put` extraída a un helper ÚNICO `_resolve_variations_for_put`
  usado por AMBOS paths → no pueden divergir. Las otras 3 áreas (transiciones _process_order,
  console-restore, resource-regex) quedaron limpias en la pasada 2.

## Scopeado a continuación (NO implementado — requiere verificación/decisión)

- **Item 3-parte1 — hop `X-Forwarded-For`.** Derivar la IP real del hop del proxy de confianza en
  vez de `xff[0]` exige conocer el nº EXACTO de proxies confiables de Render (Cloudflare + LB de
  Render, feature-request oficial abierto "Send the correct X-Forwarded-For"). Un índice equivocado
  deja spoofable (`xff[0]`) o **rompe el webhook** (lee IP interna con `xff[-1]`). Mitigante inherente
  ya presente: el handler re-hace GET del recurso con el token del seller → un atacante que pase el
  allowlist solo puede disparar re-proceso de eventos REALES (replay idempotente + rate-limited), no
  inyectar data; el item 3-parte2 (validación de `resource`) cierra además el vector SSRF. Patrón
  `xff[0]` es **sistémico** (security.py, aveonline_webhook.py, tenant_offboarding.py) → el fix debe
  ser transversal. **INTERVENCIÓN HUMANA:** confirmar la topología de proxies del servicio `api` en
  Render antes de cambiar la extracción.
- **Item 5 — refund del comprador.** Los reembolsos MeLi son de **Mercado Pago** (API/webhook
  separados, tópico `payments`); MeLi ejecuta el reembolso al comprador automáticamente en la
  cancelación forzada. El "refund prometido" no corresponde a una acción que el código deba ejecutar
  sobre MeLi. El void/refund del cobro Wompi de órdenes nativas es aparte (BLOQUE A ya estableció que
  Wompi no permite pull sin `txn_id`). **VALIDAR EN DOC OFICIAL** Mercado Pago antes de integrar
  cualquier refund programático.
- **Sync single-flight.** La serialización cross-réplica del GET-modify-PUT de `sync_meli_stock`
  (advisory lock / single-flight por `external_id`) elimina el residual del race de item D — misma
  clase que el race de refresh token sin lock cross-réplica (audit §MeLi). Follow-up.

## Consecuencias
- Coherencia de inventario cross-canal (WhatsApp ↔ MeLi) sostenida por el mismo guard idempotente en
  los 3 orígenes de decremento/reposición (nativo, webhook MeLi, consola).
- Sin migración nueva (reutiliza el RPC de ADR-0035). Cambios code-only en `meli_webhook.py`,
  `marketplace.py`, `orders.py`.
- Referencias: [ADR-0035] (RPC stock), [ADR-0025] (aislamiento tenant), [ADR-0023] (Model B per-tenant).

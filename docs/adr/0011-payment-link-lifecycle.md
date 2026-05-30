# ADR-0011: Lifecycle del payment link Wompi (idempotencia + regeneración + cancelación)

## 1. Status

**Accepted** · 2026-05-05 (rev. 104)
Próxima revisión: cuando se introduzcan templates HSM (Fase 2) o cuando se
cambie el TTL contractual de Wompi.

## 2. Context

### Hechos detonantes

Sesión UAT 2026-05-05 sobre orden runtime `#3E10CB92` evidenció **dos smells
acoplados**:

1. **Idempotencia transaccional ausente**. El cliente confirmaba un pedido,
   recibía link Wompi, y al volver a decir *"Sigamos con la compra"* el bot
   creaba **una orden nueva con un link nuevo** (orden #1 quedaba zombie).
   Caso runtime previo (S06[new]): se observaron 2 órdenes (`#5B784CFB`,
   `#C9497EDD`) creadas por el mismo flujo conversacional.

2. **Race condition con el cron de cancelación**. Al regenerar el link tras
   los 30 min de TTL Wompi, el cron `_release_expired_pending_payment_orders`
   cancelaba la orden 34 segundos después (logs: `08:35:32` regeneró link,
   `08:36:06` cron canceló). Resultado: cliente con link Wompi vivo apuntando
   a orden `cancelled` → si pagaba, webhook llegaba a estado inconsistente.

### TTLs presentes en el sistema (pre-decisión)

| Constante | Valor | Ubicación | Propósito |
|---|---|---|---|
| `WOMPI_PAYMENT_LINK_TTL_MINUTES` | 30 min | `services/api/routers/orders.py` | Validez del checkout_url (campo `expires_at` enviado a Wompi). |
| `PENDING_PAYMENT_TTL_MINUTES` | 35 min | `services/ai-orchestrator/worker.py` | Cron cancela órdenes `pending_payment` con `created_at < NOW() - 35min`. |
| `PAYMENT_REMINDER_DELAY_MINUTES` | 25 min | `services/ai-orchestrator/worker.py` | Cron envía "Te queda 5 min" (recordatorio pre-expiración). |
| `PAYMENT_REMINDER_WINDOW_MINUTES` | 5 min | `services/ai-orchestrator/worker.py` | Ancho de la ventana del cron de recordatorio (`[delay, delay+window)`). |

### Constraints inmovibles

- **Plan A.0.1** (cart-as-SoT): una conversación + cart abierto = una orden
  activa. Múltiples órdenes por flujo violan el contrato.
- **Wompi API contractual**: el TTL del checkout_url se fija al crear el
  link y no se puede extender. Para "extender" hay que crear un nuevo link.
- **Webhook Wompi**: correlaciona pago entrante con orden vía
  `wompi_link_id` (no por `order_id`). Una orden puede tener múltiples
  `payments` rows; lo que importa es que cuando entra el webhook, la orden
  esté en estado `pending|pending_payment` para que el upsert funcione.

## 3. Decision

Se adopta un **lifecycle de tres ventanas** sobre la orden `pending_payment`,
enforced en dos puntos del código y un solo invariante temporal:

```
T=0 ────────── T=30 ────────── T=35 ─────────────────►
  link vivo   bucket(b)        cron cancela
  bucket(a)   regenera         si NO hay payment
  reusa       sobre misma      activo (≤ 35min)
              orden
```

**Regla 1 — `WOMPI_PAYMENT_LINK_TTL_MINUTES = 30`** (inmovible por contrato Wompi).

**Regla 2 — `PENDING_PAYMENT_TTL_MINUTES = WOMPI_PAYMENT_LINK_TTL_MINUTES + 5`**.
La ventana de gracia de 5 min permite que el cliente vuelva tras la
expiración del link y el bucket (b) regenere. Si esta diferencia se reduce
a 0 (ambos = 30), no hay margen para regenerar; si crece a >10, hay riesgo
de que la orden quede viva mucho tiempo sin actividad real.

**Regla 3 — `payment_link_tool` aplica idempotencia transaccional** ([`services/ai-orchestrator/tools/payment_link_tool.py:55-126`](../../services/ai-orchestrator/tools/payment_link_tool.py#L55-L126)):

- **Bucket (a)** — orden `pending_payment` + `payments.pending` con
  `created_at >= NOW() - 30min` → reutilizar el link vigente, **0 POSTs**
  al Core API. El `wompi_link_id` no cambia.
- **Bucket (b)** — orden `pending_payment` sin `payments.pending` reciente
  → mismo `order_id`, llamar `POST /orders/{id}/payment-link` que inserta
  una nueva fila `payments` con un `wompi_link_id` distinto. La orden no
  se duplica.
- **Bucket (c)** — sin orden `pending_payment` para la conversación →
  flujo normal: crear orden y link nuevos.

Si el bucket (b) falla (Wompi 503 o transient): **retornar `None`** (handoff
a humano). NO se crea orden nueva: Plan A.0.1 prima sobre disponibilidad.

**Regla 4 — `_release_expired_pending_payment_orders` consciente de payments**
([`services/ai-orchestrator/worker.py:777-840`](../../services/ai-orchestrator/worker.py#L777-L840)):
para cada orden `pending_payment` con `created_at < NOW() - 35min`, antes de
cancelar verifica si hay `payments.pending` con `created_at >= NOW() - 35min`.
Si hay → no cancelar (cliente regeneró link recientemente). Si lookup de
payments falla → conservador: NO cancelar (mejor zombie temporal que
cancelar orden con cliente esperando pago).

## 4. Consequences

### Positivas

- **Cart-as-SoT honrado en runtime**: una conversación = una orden
  `pending_payment` por flujo de compra, sin importar cuántas veces el
  cliente vuelva a decir "Sigamos" antes o después del TTL.
- **Trazabilidad limpia**: todos los intentos de pago (links generados)
  cuelgan de la **misma** `order_id` como filas separadas en `payments`.
  Audit log refleja la secuencia real (link #1 generado → reusado → link
  #2 regenerado → pago).
- **Webhook Wompi sigue funcionando sin cambios**: correlaciona por
  `wompi_link_id` (cada link tiene el suyo) → encuentra el `payments` row
  correcto sin conflicto.
- **Cron de cancelación no compite con bucket (b)**: la regla "no cancelar
  si hay payment fresco" elimina la race condition observada en el caso
  runtime #3E10CB92.
- **Mensaje al cliente diferencial**: bucket (a) dice *"Tu pedido ya tiene
  link de pago activo"*; bucket (b) dice *"Tu link anterior expiró. Aquí
  va el nuevo..."* — sin ambigüedad para el cliente.

### Negativas / costos

- Cada lookup de payment_link agrega 1-2 queries a Supabase (orders +
  payments). En el peor caso 2 round-trips. Aceptable: el path es invocado
  solo cuando el cliente explícitamente pide pagar.
- El cron `_release_expired` ahora hace 1 query adicional por orden stale
  (lookup de payments por order_id). Con `limit(50)` por iteración y un
  cron cada 10 min, el costo es bajo. Si crece la carga se puede colapsar
  a una sola query con `NOT EXISTS` correlated.
- Las órdenes que el cliente abandona quedan `pending_payment` durante 35
  min antes de ser canceladas (en lugar de 30). Impacto en reporting:
  ventana 5 min mayor de "limbo". Aceptable: el reporting financiero usa
  `confirmed|delivered`, no `pending_payment`.

### Riesgos residuales

- **Drift entre las constantes**: si alguien cambia
  `WOMPI_PAYMENT_LINK_TTL_MINUTES` sin actualizar las otras dos, el
  lifecycle se rompe silenciosamente. **Mitigación**: comentarios cruzados
  en cada archivo apuntando a este ADR; test
  `test_ttl_default_is_35_minutes` falla si alguien baja el TTL del cron
  al del link.
- **Cliente paga link expirado (>30 min)**: Wompi rechaza con error
  contractual del lado de Wompi. No hay forma de evitarlo desde nuestro
  lado — es responsabilidad de Wompi rechazar el pago. Bucket (b) cubre
  el flujo si el cliente nos pide nuevo link.

## 5. Alternatives considered

### Alternativa A — Un solo TTL (30 min) con cancelación inmediata
Cancelar la orden a los 30 min sin grace window. **Descartada**: si el
cliente vuelve a t=30:01 min, el bucket (b) intentaría regenerar sobre
una orden ya cancelled → endpoint Core API rechaza con 409 → cliente
queda en limbo. Habría que crear orden nueva, violando Plan A.0.1.

### Alternativa B — `orders.updated_at` refrescado por bucket (b)
Cada vez que el bucket (b) regenera, actualizar `orders.updated_at` y el
cron usa `updated_at` en lugar de `created_at`. **Descartada**: requiere
side-effect adicional en el path crítico del cliente, y `updated_at`
también lo tocan otros flujos (status changes, etc.) → lectura ambigua.
Preferimos la regla declarativa "tiene payment fresco" que es explícita
y no requiere mantener un timestamp dedicado.

### Alternativa C — Subir TTL a 60 min
**Descartada**: el TTL Wompi es contractual (30 min), no podemos
extenderlo. Subir solo el TTL de la orden no resuelve la inconsistencia,
solo la posterga.

### Alternativa D — Eliminar el cron de cancelación
**Descartada**: las órdenes zombie contaminan reporting/analytics y dejan
stock-reservations colgadas (cuando exista soft-reserve atómica de Fase 2).
El cron es necesario; lo único que cambia es la regla de elegibilidad.

## 6. Cart-modify después del link — invalidación automática

### 6.1 Smell adicional descubierto en sesión 2026-05-05

Tras certificar buckets (a)/(b)/(c) y el cron consciente de payments, surgió
una pregunta: **¿qué pasa si el cliente agrega productos al cart después de
recibir el link Wompi?** Respuesta del código pre-fix: `cart_tool.add_item`
mutaba el cart pero **no tocaba la orden ni el link**. Resultado:

- `cart_items` reflejaba el cambio (2 items, $63.000).
- `orders.total_amount` quedaba congelado en $25.310 (1 item).
- `payments.checkout_url` seguía vigente por $25.310 los próximos 30 min.

Si el cliente abría el link viejo en su WhatsApp y pagaba, recibía productos
por $63.000 pagando $25.310 → **pérdida o queja**.

### 6.2 Decisión

Toda mutación de cart (`add_item`, `update_item_quantity`, `remove_item`)
debe invocar **antes** del cambio el helper
`invalidate_pending_order_on_cart_change(cart_id, tenant_id, reason)`
([`services/ai-orchestrator/tools/cart_tool.py:67`](../../services/ai-orchestrator/tools/cart_tool.py#L67)) que:

1. Resuelve `conversation_id` desde el cart.
2. Busca `orders.pending_payment` para esa conversación.
3. Si hay → cancela orden (`status='cancelled'`, `notes` con
   `cancelled_due_to_cart_change=<reason>`) y marca todos los
   `payments.pending` como `voided`.
4. Emite `cart_events.order_invalidated_due_to_cart_change`.
5. Retorna dict con `{order_id, voided_payment_count, reason}` para que el
   caller (orchestrator) informe al cliente.

El payload retornado por `add_item` incluye el flag `order_invalidated`
cuando aplica. El orchestrator lo detecta y emite un outbound:

> *"Actualicé tu carrito. El link de pago anterior (#XYZ) ya no es válido.
> Cuando confirmes el resumen actualizado, te genero uno nuevo con el monto
> correcto."*

Cuando el cliente confirma, el bucket (c) entra en acción (no hay orden
`pending_payment` activa) y crea orden nueva con el monto correcto.

### 6.3 Validación end-to-end

Escenario UAT [`scripts/uat/scenarios/s29_cart_modify_after_payment_link.py`](../../scripts/uat/scenarios/s29_cart_modify_after_payment_link.py)
ejecuta el flow completo:
- Cliente confirma → orden #1 + link #1 ($25.310).
- Cliente: "agrégame también un sérum 30ml".
- Bot: notifica invalidación.
- Cliente: "Sí confirmo el nuevo total".
- Bot: orden #2 + link #2 con monto correcto ($110.310).
- DB final: orden #1 `cancelled` + 1 payment `voided`; orden #2
  `pending_payment` con `total_amount=110310`.

### 6.4.4 Tier-2 intent detection (add_item con info parcial)

Smell descubierto en manual UAT 2026-05-05 conv `59bab7cc`. Cliente dijo
*"Puedo adicionar otro jabon? Deseo 1 de lavanda"*. Bot ignoró + emitió
resumen viejo. Insistió: *"Deseo 2 adicionales de lavanda"*. Bot
respondió: *"Cristian, en este momento no tenemos Jabón Artesanal de
Lavanda en nuestro catálogo"* — **alucinación del LLM** sobre catálogo
real (DB confirmó 3 variantes JAB-LAV-60/100/150 + Aceite Lavanda).

Causa raíz arquitectónica: el orchestrator tenía **3 paths de
detección de intent** que no estaban coordinados (detectores
deterministas, bypasses FSM, LLM dispatch). Cuando un inbound expresaba
intent claro pero información parcial (verbo de add + producto sin
variante, o palabra ambigua que matchea ≥2 productos), todos los paths
fallaban en silencio: detector multi-product retornaba `[]` (sin qty>=2
no emitía propuesta), bypass `READY_FOR_SUMMARY` interceptaba con
resumen, y el LLM en último recurso alucinaba.

Faltaba un **tier intermedio determinístico** que clasifique la
resolución del intent y decida la acción sin delegar al LLM cuando
los datos del catálogo permiten responder.

Fix estructural — 4 tiers ordenados:

```
Tier 1 — Intent canónico de alta confianza
  cancel_intent · qty_change_intent · shipping_change_intent
  · add_item resolved (producto+variante+qty completos)

Tier 2 — Intent claro, info parcial    ← ESTE ADR
  add_item con clasificación de resolución:
    · resolved          → flow add_item (delegado a tier 1)
    · product_ambiguous → outbound determinístico con candidatos
    · variant_ambiguous → outbound determinístico con presentaciones

Tier 3 — Bypasses FSM (solo si tier 1+2 no matchearon)
  READY_FOR_SUMMARY · AWAITING_ORDER_CONFIRMATION

Tier 4 — LLM dispatch (último recurso)
```

Detector `_detect_add_item_intent_with_resolution` ([orchestrator.py](../../services/ai-orchestrator/orchestrator.py)):
- Reconoce verbos canónicos (`agregar|adicionar|añadir|incluir|sumar|
  también|deseo|quisiera|me gustaría|ponme|puedo agregar|...`).
- Identifica producto(s) candidato(s) usando `_generic_catalog_terms`
  (palabras compartidas por ≥40% del catálogo, no discriminativas).
- Filtra por `top_score` de palabras discriminativas matcheadas: el
  producto que comparte más palabras con el inbound es el más probable.
  Si hay tie en el top → continuar con filtro variant.
- **Filtro variant compatibility** (rev. 104.1, smell UAT 2026-05-05):
  si hay >1 productos en el top score Y el cliente especificó variante
  explícita (`60g`, `250ml`, etc.), filtrar solo los que tienen esa
  variante. Caso runtime: *"1 adicional de Coco de 60g"* — Aceite Coco
  viene en `100/250/500ml`, Jabón Coco viene en `60/100/150g`. Solo
  Jabón es compatible con `60g` → resolved sin pedir clarificación.
- Si producto único (post filtros) → resolver variante; si no
  resoluble → variant_ambiguous con todas las variantes adjuntas.
- Si >1 productos compatibles → product_ambiguous (real).

Hook en orchestrator emite outbound determinístico:
- product_ambiguous: *"Tenemos varios productos relacionados: A, B.
  ¿Cuál te gustaría llevar?"*
- variant_ambiguous: *"\*X\* lo tenemos en: 60g por $18.000, 100g por
  $24.000, ... ¿Cuál presentación y cuántas unidades?"*

Validación E2E (runtime real, manual UAT 2026-05-05):
- Test 1 (variant_ambiguous): "Puedo agregar 1 jabón de lavanda?" →
  bot lista 3 variantes + pide cuál.
- Test 2 (resolución secuencial): cliente responde "100g" → flow
  add_item agrega Lavanda 100g + invalida orden + recotiza envío.
- Test 3 (product_ambiguous): "Quiero adicionar algo de lavanda" →
  bot lista Aceite Lavanda + Jabón Lavanda + pide cuál.

Cobertura tests: `test_add_item_intent_resolution.py` (12 tests con
catálogo realista de 16 productos espejo del tenant KAIU).

### 6.4.3 Cart-modify intent — cambio de cantidad de item ya en cart

Smell descubierto en manual UAT 2026-05-05 conv `4546b3b6`. Cliente con
cart de 3 items dijo *"Que sean 2 de lavanda por favor"*. Bot respondió
con resumen del cart sin actualizar qty. Cliente insistió:
*"Quiero actualizar que en vez de 1 de lavanda sean 2"*. Bot siguió
ignorando. Logs confirmaron:

```
[CART][PROPOSAL] 2x Aceite Esencial de Lavanda (variante pendiente)
[CART][PROPOSAL] 2x Jabón Artesanal de Lavanda (variante pendiente)
[BYPASS] READY_FOR_SUMMARY → resumen determinístico
```

Causa raíz: `_detect_explicit_products_in_inbound` matcheó la palabra
"lavanda" contra **dos productos** del catálogo (Aceite + Jabón) sin
variante explícita → emitió 2 propuestas pendientes pero **no actualizó
qty del item ya en cart**. El bypass `READY_FOR_SUMMARY` se ejecutó sin
guard contra qty-change intent.

Diferencia conceptual con `add_item`:
- `add_item` (RPC `cart_add_item` UPSERT) **suma** al qty existente.
- `update_item_quantity` (DELETE + INSERT con new_qty) **reemplaza** qty.

Para el cliente, "que sean 2 de lavanda" cuando ya hay 1×Lavanda significa
qty=2 (no qty=3). El detector `_detect_explicit_products_in_inbound` que
reusa `add_item` produciría qty=3 — **smell**.

Fix estructural:

1. **Detector pre-LLM `_detect_qty_change_intent`** ([orchestrator.py](../../services/ai-orchestrator/orchestrator.py#L2440)).
   Reconoce verbos canónicos de update (`que sean N`, `en vez de M sean N`,
   `actualizar...sean N`, `cambia a N`, `ahora son N`, etc.) y resuelve el
   producto contra el **cart real** (cart-as-SoT), no contra el catálogo
   abstracto. Si solo hay 1 item con esa palabra en cart → unívoco aún sin
   variante explícita en el inbound. Si >1 → retorna `ambiguous` con
   candidates, bot pregunta cuál.

2. **Hook en orchestrator** antes del flujo `add_item` normal: si detector
   match, invoca `cart_tool.update_item_quantity` (DELETE + INSERT con qty
   absoluto). El `update_item_quantity` reusa `add_item` internamente, lo
   que dispara automáticamente el guard de invalidación (sección 6.2) +
   recotización lazy (sección 6.4.1) + resumen unificado (sección 6.4.2).

3. **Defensa en profundidad**: el bypass `READY_FOR_SUMMARY` no necesita
   guard adicional — el detector qty_change se ejecuta ANTES y emite el
   resumen unificado con `return`, evitando que el bypass se dispare.

Validación E2E (S30 corrida 2026-05-05):
- Cart inicial: 1×Jabón Coco.
- Cliente: *"Que sean 2 por favor"*.
- Bot ejecutó `update_item_quantity(qty=2)` → cart final 2×Coco
  (NO 3 que indicaría suma incorrecta).
- Orden anterior cancelled con notes `cart_modified`.
- Resumen unificado emitido con qty actualizado.

Validación runtime real (manual UAT post-fix):
- Cart con `1×Coco + 1×Lavanda qty=1`.
- Cliente: *"Que sean 2 de lavanda por favor"*.
- DB: cart final `1×Coco + 2×Lavanda qty=2`. Orden previa cancelled.
- Bot: resumen unificado emitido con prefijo "actualicé tu carrito".

### 6.4.1 Recotización lazy del envío (post 2026-05-05)

Smell adicional descubierto durante validación end-to-end de §6: tras la
invalidación de orden, el resumen+link nuevos **reusaban el shipping de
la cotización vieja del history** (`_extract_shipping_cost_from_history`)
en lugar de recotizar contra Envia con el peso/dims actualizados. Caso
runtime: cliente con 1×Coco recibió shipping $7.310; tras agregar 1×Sérum
(billable_weight +62%), el bot generó link nuevo manteniendo $7.310 →
**el negocio absorbía la diferencia real de envío** (~$3.700 por compra).

Fix arquitectónico (no parche):

1. **`requote_shipping_for_cart`** ([`tools/shipping_quote_tool.py`](../../services/ai-orchestrator/tools/shipping_quote_tool.py)) — función pura que
   recotiza contra Envia con el cart actual, preservando la elección del
   cliente (Económica/Rápida). Retorna `{shipping_cents, carrier_name,
   service_level}` o None si Envia falla.

2. **Persistencia temprana de city** vía `_persist_destination_city_to_cart`
   en `handle_shipping_quote_if_applicable`. La city se guarda en
   `cart.shipping_meta.city` en cuanto Envia confirma una cotización
   exitosa, no se espera al confirmar carrier. Esto cierra la ventana
   donde `cart.shipping_meta.city` estaba vacío y la recotización no podía
   construir el payload Envia. Plan A.0.1: cart-as-SoT desde T-1 de la
   primera cotización.

3. **`_persist_cart_shipping_if_needed`** convertida a `async` y modificada
   para **intentar recotización lazy primero** si `requires_requote=true`.
   Solo cae al fallback de history-parsing si la recotización Envia falla
   (transient 504) o el cart está incompleto. En caso normal, el shipping
   persistido al cart refleja la cotización REAL del cart actual.

Validación E2E (S29 corrida 2026-05-05):
  • Cart 1×Coco: shipping $7.830 (Coordinadora) — primera cotización.
  • Cart 1×Coco + 1×Sérum: shipping **$11.570** (Coordinadora) — bot
    recotizó automáticamente, link nuevo cobra el envío real.
  • Diferencia +$3.740 (+47%) → margen del negocio preservado.

### 6.4 Race condition residual aceptada

Existe una ventana de milisegundos entre `add_item` y la cancelación de la
orden donde, teóricamente, el cliente podría pagar el link viejo. Mitigación:
- `cart_tool` invoca el helper **antes** del cambio del cart, no después.
  Si la cancelación falla, el cart NO se muta (mejor rechazar la
  modificación que dejar inconsistencia).
- El webhook Wompi (handler upstream) opera sobre `orders.id`. Si llegara
  un pago contra una orden `cancelled`, `_upsert_payment_record`
  detectaría el estado inconsistente y lo escalaría a humano. Cubrirlo
  end-to-end requiere lock pesimista (descartado por costo).

## 7. Implementation pointers

- **Idempotency lookup**: [`services/ai-orchestrator/tools/payment_link_tool.py:55`](../../services/ai-orchestrator/tools/payment_link_tool.py#L55) (`_find_pending_order`)
- **Regeneración de link sobre misma orden**: [`payment_link_tool.py:129`](../../services/ai-orchestrator/tools/payment_link_tool.py#L129) (`_regenerate_link_on_existing_order`)
- **Guard del cron**: [`services/ai-orchestrator/worker.py:777`](../../services/ai-orchestrator/worker.py#L777) (`_release_expired_pending_payment_orders`)
- **Invalidación cart-modify**: [`services/ai-orchestrator/tools/cart_tool.py:67`](../../services/ai-orchestrator/tools/cart_tool.py#L67) (`invalidate_pending_order_on_cart_change`)
- **Notificación al cliente**: [`services/ai-orchestrator/orchestrator.py:6418`](../../services/ai-orchestrator/orchestrator.py#L6418) (post `add_item`)
- **Recotización lazy del envío**: [`tools/shipping_quote_tool.py::requote_shipping_for_cart`](../../services/ai-orchestrator/tools/shipping_quote_tool.py)
- **Persistencia temprana de city al cart**: [`tools/shipping_quote_tool.py::_persist_destination_city_to_cart`](../../services/ai-orchestrator/tools/shipping_quote_tool.py)
- **Sync con recotización lazy**: [`orchestrator.py::_persist_cart_shipping_if_needed`](../../services/ai-orchestrator/orchestrator.py)
- **Endpoint Core API que regenera link sobre orden existente**: [`services/api/routers/orders.py:310`](../../services/api/routers/orders.py#L310) (`POST /orders/{id}/payment-link`, acepta `pending|pending_payment`)
- **Tests unitarios**:
  - `tests/test_payment_link_tool.py::PaymentLinkIdempotencyTests` (4 tests, buckets a/b/b-fail/c)
  - `tests/test_r01_stock_release.py::PendingPaymentReleaseTests` (7 tests, payment fresco evita cancelación)
  - `tests/test_cart_invalidate_pending_order.py::*` (7 tests, helper + add_item + remove_item)
  - `tests/test_requote_shipping_lazy.py::*` (6 tests, requote helper buckets cheapest/fastest/fail/no-city)
  - `tests/test_qty_change_detector.py::*` (11 tests, patterns que sean / en vez de / cambia a / ambiguous / cap50)
  - `tests/test_add_item_intent_resolution.py::*` (12 tests, tier-2 buckets resolved / product_ambiguous / variant_ambiguous / no_intent / no_product)
- **Tests UAT end-to-end**:
  - `scripts/uat/scenarios/s29_cart_modify_after_payment_link.py` (modify cart post-link, modo `known`)

## 8. Triggers para revisar este ADR

- Wompi cambia el TTL contractual del checkout_url (>30 min o <30 min).
- Se introducen templates HSM (Fase 2) que permiten enviar recordatorios
  fuera de la CSW de 24h — el `PAYMENT_REMINDER_DELAY_MINUTES` puede
  reducirse o eliminarse.
- Se agrega soft-reserve atómica de stock (Fase 2): la cancelación de
  orden requiere también liberar la reserva, agregando un side-effect
  adicional al cron.
- Se observa drift entre tenants en el comportamiento del lifecycle
  (algunos tenants tienen TTLs distintos por configuración).

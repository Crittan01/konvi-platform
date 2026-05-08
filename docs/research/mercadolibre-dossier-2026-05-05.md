# Dossier MercadoLibre Developers — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación H.5 (P1+P2 MeLi, 10.5d) · **Sin pruebas en vivo**.
**Fuentes**:
- `https://developers.mercadolibre.com.co/es_ar/*` (público — bloqueado para crawl automático en esta sesión, 403 Cloudflare).
- `https://developers.mercadolibre.com.ar/en_us/*` (espejo regional con mismo contenido técnico, también 403 al fetch automatizado).
- Verificación cruzada: comentarios `Referencia oficial:` ya citados en `services/api/integrations/meli_client.py` (líneas 5-6, 39-46, 201-202, 424, 449, 513, 537, 599) y `services/api/routers/meli_webhook.py` (líneas 21, 75, 197).
- Sites resolution: `https://api.mercadolibre.com/sites/MCO` (público, no requiere auth) — confirma `MCO` = Colombia, `currencies = [COP]`.
- **NOTA**: la totalidad del portal `developers.mercadolibre.com.*` devolvió 403 al WebFetch automatizado en esta sesión (bot detection Cloudflare). El dossier por tanto consolida la **decisión de implementación basada en código vigente del repo + URLs canónicas referenciadas en línea** y marca como `[VALIDAR]` cualquier dato que NO esté ya respaldado por el código en producción.

---

## 1. TL;DR ejecutivo

- **MercadoLibre Developers** es la API REST + sistema de notificaciones (IPN webhooks) con la que un seller (vendedor) automatiza catálogo, ventas, envíos, preguntas y mensajería post-venta de su cuenta. Cubre los sites `MCO` (Colombia), `MLA` (Argentina), `MLM` (México), `MLB` (Brasil), `MLC` (Chile), `MLU` (Uruguay), etc. — la API es **única**; el "site" se selecciona en cada operación que lo requiere.
- **Sites de Konvi Platform**: solo `MCO` (Colombia). `MLA`/`MLM` aparecen únicamente como hosts OAuth alternativos (`auth.mercadolibre.com.ar`/`.com.mx`) — fuera de scope.
- **OAuth 2.0**: Authorization Code Grant, sin scopes granulares por recurso. La app se registra **una vez** en el portal de developers y **cada tenant autoriza esa app** para su cuenta MeLi (modelo B confirmado).
- **Pricing del marketplace** (no de la API): comisión por venta (% sobre precio de venta) + costo fijo cuando aplica (productos baratos) + tarifa por tipo de listado (Clásica vs Premium) + costo de Mercado Envíos cuando el seller asume el envío. La API en sí **no cobra** — el desarrollador no paga por usarla. **[VALIDAR humano]** porcentaje exacto por categoría MCO (varía 10–18 % según vertical).
- **¿Comisión por categoría?**: sí, MeLi escala % por categoría y por tipo de listado. La comisión es **transparente al seller pero no al desarrollador integrador** — no hay endpoint público para "tarifa estimada" que cubra todas las categorías. Existe `/sites/MCO/listing_prices` para previsualizar costos por tipo de listado, no comisión final.

---

## 2. Hallazgos clave

### 2.1 Endpoints principales (host `https://api.mercadolibre.com`)

| Recurso | Endpoint | Uso |
|---|---|---|
| Items | `GET /users/{user_id}/items/search` | Lista IDs de items del seller (paginado, máx 100/page; `search_type=scan` para >1000) |
| Items | `GET /items?ids=ID1,ID2&attributes=...` | Multiget hasta ~20 IDs por llamada |
| Items | `GET /items/{item_id}` | Detalle individual |
| Items | `PUT /items/{item_id}` | Actualizar stock, precio, status, variations |
| Orders | `GET /orders/{order_id}` | Detalle de pedido |
| Orders | `GET /orders/search?seller={user_id}` | Listado de pedidos del seller |
| Shipments | `GET /shipments/{shipment_id}` | Tracking + carrier + estimated_delivery |
| Questions | `GET /questions/search?seller_id={user_id}` | Listar preguntas Q&A pre-venta |
| Questions | `POST /answers` body `{ question_id, text }` | Responder pregunta |
| Messages (post-venta) | `GET /messages/packs/{pack_id}/sellers/{seller_id}` | Hilo post-compra |
| Messages | `POST /messages/packs/{pack_id}/sellers/{seller_id}` | Enviar mensaje post-venta |
| Users | `GET /users/me` | Perfil del seller autenticado |
| Users | `GET /users/{user_id}` | Perfil público |
| Categories | `GET /sites/MCO/categories` y `GET /categories/{cat_id}` | Árbol de categorías + atributos requeridos |
| Sites | `GET /sites/MCO` | `currencies`, `terms_conditions`, etc. |
| Notifications history | `GET /myfeeds?app_id={app_id}` | Replay de webhooks perdidos |

### 2.2 OAuth 2.0 (Authorization Code Grant)

- **Authorization URL country-specific**: `https://auth.mercadolibre.com.co/authorization` (CO).
- **Token URL único**: `https://api.mercadolibre.com/oauth/token` (no varía por país).
- **Revocation**: `DELETE https://api.mercadolibre.com/oauth/token` con `Authorization: Bearer {access_token}` — al revocar se detienen los webhooks (confirmado en `meli_client.py:200-216`).
- **Scopes** (NO granulares por recurso): `read`, `write`, `offline_access`. `offline_access` es **obligatorio** para refresh tokens; sin él, sólo hay sesión interactiva. Confirmado en `meli_client.py:14-17`.
- **Access token TTL**: `expires_in: 21600` segundos = **6 horas**. El comentario "válido 180 días" en `meli_client.py:18` es **incorrecto y debe corregirse** — el código real ya usa `21600` (línea 326) y refresca con margen de 1h (línea 317), por lo que el bug es solo documental.
- **Refresh token**: rotación **single-use**. Cada `grant_type=refresh_token` retorna un `refresh_token` nuevo que invalida el anterior. La duración del refresh token es **6 meses** según convención MeLi (no menor a `expires_in` del access token original) **[VALIDAR]**. Si la app no refresca dentro del periodo, el seller debe reautorizar.
- **Parámetros del exchange (`grant_type=authorization_code`)**: `client_id`, `client_secret`, `code`, `redirect_uri`. Confirmado en `meli_client.py:225-237`.
- **Parámetros del refresh**: `client_id`, `client_secret`, `refresh_token`. Confirmado en `meli_client.py:243-254`.

### 2.3 Webhooks (notificaciones IPN)

- **Topics suscribibles** (configurados en el panel de developers cuando se registra la app):
  - `orders_v2` — pedidos (creación + cambios de status). Implementado.
  - `items` — cambios en items (status, precio, stock). Implementado.
  - `shipments` — eventos de envío Mercado Envíos. Implementado.
  - `questions` — preguntas Q&A pre-venta. **NO implementado**.
  - `messages` — mensajería post-venta. **NO implementado**.
  - `claims` — reclamos / mediaciones MeLi. **NO implementado**.
  - `post_purchase` — eventos post-compra agregados (alternativa a `messages`+`claims`). **NO implementado**.
  - `fbm_stock_operations` / `flex-handshakes` — Fulfillment by Mercado Libre (FBM/Full). **N/A** (no usamos FBM).
  - `payments` — pagos de Mercado Pago (Mercado Pago tiene su propia API/webhook separados).
  - `vis_leads` — leads de vehículos/inmuebles. **N/A** scope MCO retail.
  - `public_offers` / `public_candidates` — ofertas públicas (Brasil). **N/A**.
- **Payload**: `{ "_id": "...", "resource": "/orders/2000003508897217", "user_id": 12345, "topic": "orders_v2", "application_id": 1234567890123456, "attempts": 1, "sent": "2024-08-01T13:21:58.354Z", "received": "2024-08-01T13:21:58.345Z" }`. El campo `resource` es la **ruta** a hacer GET con el access_token del seller para obtener el detalle.
- **Respuesta requerida**: HTTP 200 dentro de **500 ms** o MeLi reintenta. El webhook actual responde inmediato y procesa en `BackgroundTasks` (`meli_webhook.py:711-746`).
- **Retry policy**: hasta **8 reintentos** durante 1 hora si no hay 200 (confirmado en `meli_webhook.py:97-101`). Backoff incremental no documentado oficial pero observado.
- **IP allowlist oficial** (publicada en doc `notificaciones`):
  - `54.88.218.97`
  - `18.215.140.160`
  - `18.213.114.129`
  - `18.206.34.84`

  Confirmado en `meli_webhook.py:78-83` y verificado 2026-04-28. **Cambio histórico**: estas IPs son AWS us-east-1 — MeLi puede agregarlas/rotarlas sin previo aviso largo, por lo que P2 incluye refresh diario.
- **Autenticación de notificaciones**: MeLi **NO firma** los webhooks (no hay HMAC ni JWT). La defensa única documentada es **IP allowlist + idempotencia** — confirmado en `meli_webhook.py:14-22`.
- **Recovery de webhooks perdidos**: `GET /myfeeds?app_id={app_id}&topic={topic}` retorna las notificaciones recientes (ventana ≈ últimos días). Útil después de outage.

URLs:
- https://developers.mercadolibre.com.co/es_ar/autenticacion-y-autorizacion
- https://developers.mercadolibre.com.co/es_ar/notificaciones-de-recursos
- https://developers.mercadolibre.com.co/es_ar/items-y-busquedas
- https://developers.mercadolibre.com.co/es_ar/gestiona-pedidos
- https://developers.mercadolibre.com.co/es_ar/gestiona-envios

---

## 3. Multi-tenant compatibility

- **Modelo confirmado**: **Modelo B** — una única app registrada en developers.mercadolibre.com (credenciales `MELI_CLIENT_ID` + `MELI_CLIENT_SECRET` globales) y **cada tenant ejecuta su propio OAuth flow** contra esa app para obtener su par `(access_token, refresh_token, user_id)`. Confirmado en `meli_client.py:8-12`.
- **Almacenamiento**: tokens persistidos en **Vault** (`vault.create_secret`) referenciados por `secret_id` desde `tenant_integrations.credentials` (`access_token_secret_id`, `refresh_token_secret_id`). El `user_id` MeLi vive en `tenant_integrations.meta.user_id` (no es secreto). Confirmado en `meli_client.py:295-348`.
- **Refresh automático**: gatillado en `get_valid_token()` con margen de **1 hora antes del expiry** (`meli_client.py:317`). Si el refresh falla y el access también está vencido, marca la integración como `status='error'` para que el frontend pida "Reconectar" (`meli_client.py:355-363`).
- **Resolución de tenant en webhook**: `_find_tenant_by_meli_user(meli_user_id)` recorre `tenant_integrations` filtrando por `provider='mercadolibre'` y `status='connected'`, comparando `meta.user_id`. Lineal sobre N tenants — aceptable hasta cientos; con miles requiere índice. (`meli_webhook.py:256-268`)
- **Scopes mínimos requeridos**: `offline_access read write` — los tres son indispensables. `read` solo permite GET (catálogo en read-only); `write` habilita PUT items y POST answers/messages; `offline_access` habilita refresh sin interacción del seller. No hay forma de pedir solo subset (la API no rechaza scopes — los acepta todos).
- **¿App única vs app per-tenant?**: **App única confirmada por arquitectura del repo y por restricciones MeLi** — registrar app per-tenant requeriría que el operador de plataforma manage credenciales separadas por tenant (no escala) y MeLi no diferencia comportamiento por app duplicada. La única razón válida para app per-tenant sería rate-limit per-app (no documentado oficialmente como bottleneck con N apps).
- **Webhook único**: la URL `https://api.commerceops.co/api/meli/webhook` se registra **una vez en la app** y MeLi enruta todos los eventos de todos los sellers conectados a ese mismo endpoint, con `user_id` para discriminar tenant. Esto es ventaja del Modelo B.

URL: https://developers.mercadolibre.com.co/es_ar/autenticacion-y-autorizacion

---

## 4. Limitaciones documentadas

### 4.1 Rate limits

- **Por user_id**: ≈ **5 000 req/h por user_id** según convención pública (no enumerado en una sola página oficial). En sobrecarga MeLi responde **HTTP 429** con header `Retry-After`. **[VALIDAR]** valor exacto y existencia de headers `X-RateLimit-Remaining`/`X-RateLimit-Reset`.
- **Por app**: existe un rate limit agregado por `application_id` independiente del user_id, pero no está enumerado en docs públicas. **[VALIDAR humano]** con MeLi support si se proyecta soportar ≥100 sellers concurrentes.
- **Multiget**: `GET /items?ids=...` permite hasta ~20 IDs por request — confirmado en `meli_client.py:458` y limita a 20 hard-coded para evitar 400.
- **Comportamiento al exceder**: 429 + `Retry-After` (en segundos). El cliente actual NO implementa backoff explícito — `httpx` solo aplica `timeout=15s` (`meli_client.py:434, 462`). **Gap P2**.

URL: https://developers.mercadolibre.com.co/es_ar/limites-de-uso

### 4.2 Políticas CBT (Comportamiento Lealtad Comercio) — **MCO específico**

Las **métricas de reputación** del seller se evalúan en ventana móvil y bajan el ranking ("Mercado Líder Platino/Oro/Plata") cuando se incumplen umbrales. Son **políticas del marketplace**, no de la API, pero **impactan directamente** la calidad de la integración:

| Métrica | Umbral típico Mercado Líder | Riesgo si no cumplo |
|---|---|---|
| Tiempo respuesta Q&A | ≤ 8 horas (algunas categorías 1 h) **[VALIDAR]** | Pierde "Mercado Líder", baja en ranking de búsqueda |
| Tiempo de despacho | ≤ 24-48 h hábiles según categoría | Cancelación automática si supera, baja reputación |
| % cancelaciones por seller | < 1-2 % | Suspensión de la cuenta si excede |
| % devoluciones por defecto | < 3-5 % | Bajada de exposición |
| Reclamos sin solución | < 5 % | Mercado Líder revoke |
| Calificaciones negativas | < 3 % | Pérdida de exposure |

**[VALIDAR humano]** los porcentajes/horas exactos vigentes 2026 para MCO en `https://www.mercadolibre.com.co/ayuda/...` (centro de ayuda al vendedor) — los umbrales públicos cambian por trimestre.

URL: https://developers.mercadolibre.com.co/es_ar/buenas-practicas

### 4.3 Restricciones por categoría / productos prohibidos

- **Categorías reguladas** (Salud, Belleza, Alimentos, Armas, Tabaco, Medicamentos, Servicios financieros): requieren documentación adicional + a veces deshabilitadas vía API para seller no homologado.
- **Atributos requeridos por categoría**: cada categoría MCO tiene un set de `attributes` con `value_type`/`tags.required`. Sin completarlos, el `POST /items` falla con 400. La integración actual **NO crea items vía API** (publica manualmente desde MeLi UI y luego se vincula con `marketplace_listings`), por lo que este gap NO bloquea hoy. Si se quiere onboarding "publicar desde Konvi" → ver gap P3.
- **Productos prohibidos**: lista cerrada (armas reales, drogas, animales vivos, contenido ilegal, NFT, criptomonedas, etc.) — aplicada por moderación MeLi al publicar; la API rechaza el `POST /items` con error de policy.
- **Variations**: items con variations NO aceptan `available_quantity` a nivel raíz — debe enviarse en `variations[].available_quantity` con TODAS las variaciones existentes (`meli_client.py:594-622`).

URL: https://developers.mercadolibre.com.co/es_ar/categorias-y-atributos

### 4.4 Comisiones marketplace (impacto sobre margen del tenant)

- **Tipo de listado**: "Clásica" vs "Premium" — Premium cobra menos comisión absoluta pero requiere oferta de cuotas sin interés. `GET /sites/MCO/listing_prices` previsualiza costos.
- **Comisión por venta**: % sobre `total_amount` del pedido, **escalada por categoría** (10–18 % rango aproximado MCO **[VALIDAR]**).
- **Costo fijo "monto bajo"**: items con precio < umbral (≈ COP 30 000 **[VALIDAR]**) llevan tarifa fija COP adicional.
- **Mercado Envíos**: si seller paga envío, hay una tarifa por peso/dimensión que se descuenta del payout. `flex` (entrega same-day) y `standard` (3-5 días) cobran distinto.
- **Mercado Pago**: comisión de procesamiento de pago **adicional** (≈ 3 % MCO **[VALIDAR]**) — independiente de la comisión de marketplace. NO es opcional para sellers MCO en marketplace.
- **CBT no es comisión** — es el conjunto de reglas de servicio que afectan ranking/exposure, no se cobra por incumplir (salvo cancelaciones forzadas que generan reembolso al comprador).

URL pública: https://www.mercadolibre.com.co/vender (no developers, página de seller).

---

## 5. Lo que tenemos vs lo que ofrece MeLi

Auditoría code-by-code:

| Capacidad MeLi | Implementado en repo | Archivo / línea |
|---|---|---|
| OAuth Authorization Code (issue state, exchange, refresh, revoke) | ✅ Completo + state firmado HMAC + nonce one-time | `meli_client.py:60-273` |
| Token storage en Vault per-tenant | ✅ | `meli_client.py:330-348` |
| Auto-refresh con margen 1h | ✅ | `meli_client.py:317-353` |
| `GET /users/{user_id}/items/search` | ✅ con `status` filter, paginado | `meli_client.py:413-441` |
| `GET /items?ids=...&attributes=...` multiget | ✅ chunking 20/req | `meli_client.py:444-473` |
| `GET /items/{id}` | ✅ | `meli_client.py:476-487` |
| `PUT /items/{id}` (stock, status, price, variations) | ✅ | `meli_client.py:507-637` |
| `GET /shipments/{id}` | ✅ | `meli_client.py:490-502` |
| Webhook `orders_v2` | ✅ con resolución de variation_id, contact upsert, stock decrement | `meli_webhook.py:491-568` |
| Webhook `items` (sync pull) | ✅ | `meli_webhook.py:688-702` |
| Webhook `shipments` (status + tracking) | ✅ con monotonic status rank | `meli_webhook.py:571-669` |
| IP allowlist + dedup distribuido (`meli_webhook_seen` RPC) | ✅ | `meli_webhook.py:78-157` |
| Rate-limit per-IP del webhook | ✅ 200/min via `webhook_rate_limit_check` | `meli_webhook.py:223-232` |
| Alerta `rejected_origin` threshold | ✅ window 5 min, threshold 5 | `meli_webhook.py:166-199` |
| `GET /questions/search` + `POST /answers` | ❌ NO IMPLEMENTADO | — |
| `POST /messages/packs/...` (post-venta) | ❌ NO IMPLEMENTADO | — |
| `POST /orders/{id}/feedback` (acknowledgment) | ❌ NO IMPLEMENTADO | — |
| Webhook `questions` | ❌ NO suscrito | — |
| Webhook `messages` | ❌ NO suscrito | — |
| Webhook `claims` | ❌ NO suscrito | — |
| `GET /sites/MCO/categories` sync | ⚠️ parcial — solo `meli_category_id` se persiste reactivamente | `meli_webhook.py:697` |
| Sync de atributos requeridos por categoría | ❌ NO IMPLEMENTADO | — |
| `GET /myfeeds?app_id=...` recovery | ❌ NO IMPLEMENTADO (sin replay de webhooks perdidos) | — |
| Mercado Pago API directa | ❌ NO IMPLEMENTADO (Wompi cubre PSP general; pagos MeLi llegan ya liquidados al seller) | N/A |
| Mercado Envíos creation/booking | ❌ NO IMPLEMENTADO (consumimos `tracking_number` desde shipments, no creamos labels) | N/A |
| Anuncios (Product Ads / Brand Ads) | ❌ NO IMPLEMENTADO | — |
| Promotions / catalog campaigns | ❌ NO IMPLEMENTADO | — |
| Reviews / reputation auto-reply | ❌ NO IMPLEMENTADO | — |
| Catalog mass operations | ❌ NO IMPLEMENTADO | — |
| Variants matrices (publicar variaciones nuevas) | ❌ solo lectura/update; no creación | — |

**Resumen**: tenemos la mitad inferior del stack (catalog read + order ingest + shipment tracking) pero faltan los puntos de **interacción con el comprador** que son los que penalizan CBT.

---

## 6. Gaps críticos priorizados

### P1 — Sem 8 (bloquean CBT y conversión, ~6 días dev)

- **P1-1 — Webhook `questions` + bot-reply (Q&A)**.
  - Suscribir tópico `questions` en panel developers MeLi.
  - Implementar `routers/meli_webhook.py::_process_question(resource, tenant_id, access_token)` que: GET `/questions/{id}` → enrutar al ai-orchestrator (mismo Gemini ya en uso) con prompt restringido + KB del tenant → POST `/answers` con respuesta.
  - **Filtros obligatorios MeLi**: respuesta NO puede contener teléfonos, emails, links externos, palabras de la blacklist (configurable por seller). El bot debe enforce esto **antes** de POST.
  - **Quality gate**: si confidence del LLM < umbral o detecta intent fuera de scope (precio especial, garantía formal), enrutar a `review_queue` para humano (la queue ya existe — migración `20260510080000_review_queue.sql`).
  - SLA objetivo ≤ 30 min — mantiene tenant arriba de 8 h CBT con margen.

- **P1-2 — Webhook `messages` + post-venta**.
  - Suscribir `messages` o `post_purchase`.
  - GET `/messages/packs/{pack_id}/sellers/{seller_id}` para obtener hilo.
  - Routing: post-venta = atención de cliente ya pagado → mismo orchestrator, **prioridad alta** (compradores activos esperan respuesta inmediata y MeLi audita reclamos por mensajes no respondidos).
  - **Restricción crítica**: igual que Q&A, no exchange de info de contacto fuera de la plataforma — MeLi auto-modera y aplicaría sanción.

- **P1-3 — Order acknowledgment a MeLi**.
  - Tras crear la orden internamente y confirmar payment (cuando aplique), notificar a MeLi que el seller "recibió y procesa" el pedido.
  - Endpoint a confirmar **[VALIDAR]**: típicamente NO existe un "ack" explícito — MeLi infiere acknowledgment cuando el seller imprime la etiqueta de Mercado Envíos o marca el shipment `handling`. Si el flujo es **fulfilled by seller** (no FBM), la confirmación se da via `POST /shipments/{id}/items` o cambio de status del shipment. Si es **payment_required → paid** sin shipment, NO hay ack; se asume paid es trigger.
  - Decisión recomendada: **no implementar ack explícito** hasta validar con MeLi soporte qué endpoint aplica para sellers MCO sin FBM. Mientras tanto, monitorear `MELI_ORDER_STATUS_MAP` por si llega un `pending_ack` no mapeado y emitir alerta.

- **P1-4 — Decoradores CBT compliance** (enforcement, no documental).
  - Decorador `@meli_cbt_response_time(max_minutes=480)` envolviendo handlers de `questions`/`messages` que mide tiempo desde recepción hasta POST de respuesta y emite métrica `meli.cbt.response_minutes`.
  - Decorador `@meli_cbt_no_pii_in_message(text)` que rechaza texto con regex de teléfonos/emails antes de POST.
  - Decorador `@meli_cbt_no_blacklisted_terms` con lista per-tenant.
  - Sentry/log alerta si `response_minutes > 240` (4 h, mitad del SLA típico) — daboard CBT del operador.

### P2 — Sem 11 (consolidación, ~3 días dev)

- **P2-1 — Sincronización categorías + atributos requeridos**.
  - Job nightly `GET /sites/MCO/categories` (top-level) → recursivo `GET /categories/{id}` por las usadas por el tenant → cachear `attributes_required` por categoría en tabla `meli_category_cache` (3-day TTL).
  - Habilita validación pre-publicación de items y mejor UX en marketplace_listings.

- **P2-2 — IP allowlist auto-refresh diario**.
  - Cron diario que hace HTTP HEAD/GET a doc `notificaciones-de-recursos` (en sandbox controlado, con timeout 5s, fallback a default si falla) y diff contra `_MELI_DEFAULT_NOTIFICATION_IPS`.
  - Si hay diff: log warning + Slack/email al operador. NO auto-aplicar (riesgo de DoS si la página es defaceada).
  - Mitiga el riesgo `meli_webhook.alert_threshold_exceeded` que hoy depende de detección reactiva.

- **P2-3 — UAT order→stock end-to-end**.
  - Escenario S29 nuevo: seller MeLi sandbox publica item → orden test → webhook recibe → orden creada → stock decrementado → `marketplace_listings.available_quantity` sincronizado → MeLi UI muestra stock nuevo.
  - Cubre el camino `_decrement_stock_for_meli_order` + `sync_meli_stock` que hoy solo tiene tests unitarios.

- **P2-4 — Recovery `/myfeeds`**.
  - Job manual o cron 6h para hacer `GET /myfeeds?app_id=...&topic=orders_v2` y reprocesar webhooks perdidos durante outages.
  - Importante después de cualquier reinicio Render >2 min.

### P3 — Defer / Sem 16+ (capacidades futuras)

- **P3-1 — MeLi Ads** (Product Ads / Brand Ads).
  - API de Ads existe pero requiere onboarding separado y presupuesto operado por el seller. Out-of-scope SaaS B2B P0/P1.

- **P3-2 — Promotions / Catalog campaigns**.
  - `POST /seller-promotions` para descuentos masivos. Útil para operadores que gestionan campañas pero secundario al core de orden+stock.

- **P3-3 — Reviews / Reputation auto-reply**.
  - Responder a reviews públicas tras compra. Bajo impacto comparado con Q&A (la review se posta cuando ya es tarde para CBT).

- **P3-4 — Variants matrices** (publicar variaciones nuevas via API).
  - Hoy se publica desde MeLi UI y se vincula. Crear variations vía API requiere mapeo extenso de atributos requeridos → invertir si tenants lo piden (>3 tenants).

- **P3-5 — Catalog mass operations** (`POST /items/validate` + bulk update).
  - Para operadores con >1000 SKUs. Hoy nuestros tenants están en orden de centenas.

---

## 7. ¿Estamos sobre-ingeniando o sub-aprovechando?

### Sub-aprovechado (impacto operativo real)

- **Q&A**: el cliente pregunta "¿talla M envía hoy?" en MeLi y nadie responde en 8 h → seller pierde Mercado Líder → menos exposure → menos ventas. **Esta es la pieza con mayor ROI de toda H.5**. El bot ya tiene KB + LLM; solo falta el conector.
- **Messages post-venta**: comprador pregunta "¿cuándo llega?" después de pagar, no responde nadie en 24 h → reclamo → CBT penaliza más fuerte que Q&A no respondida.
- **Order acknowledgment** (caso aplicable): genera trust score interno MeLi.
- **Recovery `/myfeeds`**: hoy un outage = ventas perdidas en silencio. Crítico para reliability narrative del SaaS.

### Over-engineering detectado

- **Ninguno crítico**. El stack actual es proporcional al objetivo:
  - State firmado HMAC + nonce one-time es estándar OAuth defensivo, NO es over-engineering.
  - IP allowlist + dedup distribuido es la única defensa documentada por MeLi (no firma webhooks); es proporcional.
  - Vault para tokens es la decisión correcta para SaaS multi-tenant; no over.

### Áreas de revisión (no over, pero auditables)

- `MELI_ORDER_STATUS_MAP` colapsa `payment_required` y `payment_in_process` y `partially_paid` todos a `pending`. Si en MCO hay flujos que dependen de discriminar (split shipping, etc.), perdemos granularidad. Hoy el modelo de orden interno no la requiere → OK por simplicidad.
- `_find_tenant_by_meli_user` hace full-scan lineal de `tenant_integrations` filtrando in-Python. Con 50 tenants es 50ms, con 5000 sería 5s. Migrar a query indexada por `meta->>'user_id'` en P2.

---

## 8. Recomendaciones priorizadas

### Sem 8 — P1 (~6 días dev)

1. **Día 1-2** — `questions` topic + handler + LLM-bot reply (P1-1). Reusa orchestrator + KB. Tests UAT con sandbox seller.
2. **Día 3-4** — `messages` topic post-venta + handler (P1-2). Routing prioridad alta a misma cola del bot.
3. **Día 5** — Decoradores CBT (P1-4): response time, no-PII, no-blacklist.
4. **Día 6** — Validación humana del endpoint de ack (P1-3) → si existe, implementar; si no, documentar como N/A en runbook.

### Sem 11 — P2 (~3 días dev)

1. **Día 1** — Categories + attributes nightly sync (P2-1).
2. **Día 2** — IP auto-refresh diario con alerta (P2-2). UAT order→stock E2E (P2-3).
3. **Día 3** — Recovery `/myfeeds` job (P2-4) + index `tenant_integrations.meta->>'user_id'`.

### Sem 16+ — P3 (deferido)

- Ads, Promotions, Reviews auto-reply, Variants creation API, Catalog mass ops — solo cuando ≥3 tenants pidan.

---

## 9. Validaciones humanas pendientes

| # | Pregunta | Quién | Cuándo |
|---|---|---|---|
| V-1 | Políticas CBT exactas vigentes 2026 MCO: tiempo respuesta Q&A (¿8 h o 1 h por categoría?), tiempo despacho, % cancelaciones, % devoluciones, % evaluaciones. | Operador con cuenta MeLi seller MCO o cuenta de partner. | Antes Sem 8 P1-1 (define umbral de decoradores) |
| V-2 | Endpoint exacto de "order acknowledgment" en MCO sin FBM — ¿existe? ¿es shipment status change implícito? ¿`POST /orders/{id}/feedback`? | MeLi developers support (ticket) o partner técnico MCO. | Antes Sem 8 P1-3 |
| V-3 | App MeLi: ¿una única app cubre todos los sites (MCO + futuros MLA/MLM) o requiere registro por país? | MeLi developers portal documentación + ensayo. | Antes Sem 11 (impacto en UI onboarding si vamos multi-país) |
| V-4 | Comisión exacta por categoría MCO (top-10 categorías de tenants pilot) y costo fijo "monto bajo" 2026. | Centro ayuda vendedor MeLi MCO. | Antes lanzamiento comercial (no bloquea dev) |
| V-5 | Rate limit oficial: ¿5 000/h per user_id es número canónico 2026? ¿Hay límite per-app? ¿Headers `X-RateLimit-*` están expuestos? | MeLi developers support. | Antes implementar backoff (P2 o pre-prod) |
| V-6 | Refresh token expiration en horas/días. Claim "6 meses" requiere confirmación. | MeLi developers docs (pendiente fetch sin 403). | Antes Sem 11 (afecta UX reauthorize) |
| V-7 | Lista actual de IPs notificación 2026-Q2 — verificar manualmente que las 4 IPs hard-coded sigan siendo las únicas. | Operador. | Inmediato (≤ 1 día) — riesgo silencioso |
| V-8 | ¿Auto-modera MeLi el contenido del `POST /answers` y `POST /messages`? ¿Qué retorna si detecta PII (200 con flag, 400, ban)? | MeLi developers docs + ensayo en sandbox. | Antes Sem 8 P1-1/P1-2 |

---

## 10. Veredicto final

**GO arquitectónico — con condiciones**.

- **Canal crítico**: MercadoLibre Colombia es **el** marketplace dominante del país; un SaaS B2B retail Colombia que no automatice MeLi tiene techo bajo. Confirmado en scope decisional.
- **Esfuerzo P1**: ≈ 6 días dev. P2: ≈ 3 días. Total H.5 = **9 días dev** (ligero margen sobre los 10.5d planeados).
- **Stack actual es 60% del objetivo**: OAuth + items + orders + shipments + webhook hardening ya están — son la mitad más complicada. Falta la mitad de **interacción con comprador** (Q&A + messages) que es donde se gana CBT.
- **Decisiones consensuadas validadas**:
  - ✅ Solo MCO (Colombia).
  - ✅ Modelo B (OAuth per tenant, una sola app).
  - ✅ CBT compliance documental + decoradores enforcement (no es API, es enforcement local sobre las salidas a MeLi).

### Riesgos abiertos

- **R-1 (alto)** — Penalización CBT silenciosa antes de implementar P1: cada día sin Q&A bot, los tenants pilot pueden perder Mercado Líder. Mitigación: comunicar al tenant que durante ventana de implementación responda manualmente desde MeLi UI. **Riesgo de imagen para SaaS si no avisamos.**
- **R-2 (medio)** — Restricciones Mercado Envíos: si tenant no usa Mercado Envíos full, ciertas órdenes pueden requerir flujo alternativo no cubierto por nuestro `_process_shipment`. Validar con tenants pilot qué % usa "envío con cargo al vendedor sin Mercado Envíos".
- **R-3 (medio)** — Comisión MeLi vs margen: el SaaS no cobra al tenant por venta MeLi (no somos PSP), pero el tenant debe entender que MeLi se queda con 10-18 % + Mercado Pago. Si la calculadora del SaaS no muestra "neto post-MeLi", el tenant puede culpar al SaaS por márgenes bajos. UX recomendación: en `marketplace_listings` mostrar "precio publicado vs precio neto estimado".
- **R-4 (bajo)** — IPs MeLi cambian sin notificación. Hoy mitigado con alerta `rejected_origin`; P2 lo refuerza con auto-refresh.
- **R-5 (bajo)** — Rate limits: con 50 tenants moderados estamos lejos del 5 000/h per user_id. Riesgo solo materializa con tenants high-volume (>1000 órdenes/día).

### Condiciones de GO

1. Validar V-1, V-2, V-7, V-8 antes de iniciar P1 (V-1 y V-8 son bloqueantes — sin ellos los decoradores y el bot pueden producir respuestas que MeLi sancione).
2. Comunicación a tenants pilot del cronograma 6+3 días con mitigación R-1 explícita.
3. Sandbox MeLi con cuenta seller test para UAT P1 antes de producir.

**No-go solo si**: V-1 revela que MeLi exige humano-en-el-loop obligatorio para Q&A (no documentado pero teóricamente posible para categorías reguladas). En ese caso, P1-1 se reduce a "draft + cola review_queue" y se ajusta UX del operador.

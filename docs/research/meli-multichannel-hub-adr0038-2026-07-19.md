# ADR-0038 (draft) — Hub de Comercio Multicanal: la dimensión COMMERCE del channel registry

**Estado:** propuesto · **Fecha:** 2026-07-18 · **Decisor:** founder + eng · **Relacionados:** ADR-0023 (Direct Provider per-tenant), ADR-0024 (invariante binario), ADR-0025 (aislamiento multi-tenant), ADR-0027/0028/0029 (catálogo navegable / cross-surface / modelo multi-vertical), ADR-0036 (stock idempotente cross-canal), ADR-0037 (roadmap habilitación MeLi)

---

## 1. Contexto y visión

Konvi debe dejar de tener "una integración con MeLi" y pasar a tener **un hub de comercio multicanal**: una capa donde el catálogo vive una sola vez en Supabase y se **proyecta/sincroniza** a N canales de venta (MeLi hoy; tienda virtual, Shopify, otros marketplaces mañana) sin reescribir el núcleo.

> Visión founder (textual): *"stock centralizado, para que lo que se venda en MeLi u otro canal como bot, o tienda virtual, se centralice; que todo se visualice el tema de las categorías, productos, etc, con sincronía o acoplación; si mañana entra un Shopify debe ser modular; finalmente la fuente de verdad es Supabase; armar la estrategia correcta para el todo; sacar todo el jugo a la API de MeLi con los permisos actuales."*

**Principio rector (invariante load-bearing):** **Supabase es la fuente de verdad.** El adapter de un canal es **PURE I/O contra la API de ese canal** — traduce entre la forma canónica del catálogo Supabase y la forma listing/order del canal, y **nunca escribe DB** (ni catálogo, ni `orders`, ni stock). Persistir es responsabilidad del caller. Este es exactamente el invariante que ya sostiene el `ChannelAdapter` de mensajería (`lib/channels/base.py`), llevado a un eje ortogonal: **mensajería y comercio son capacidades independientes**. Un canal implementa una, otra, o ambas:

| Canal | Mensajería | Comercio |
|---|---|---|
| `whatsapp` | ✅ | — |
| `meli` | — (OFF por decisión founder) | ✅ |
| tienda `web` / Shopify | ✅ (opcional) | ✅ |

El resultado esperado: **Shopify mañana = implementar UNA clase** que cumpla el contrato, registrarla, y curar filas de mapping. Cero cambios en el catálogo, en el bot, en el stock RPC o en el esquema de `orders`.

---

## 2. Estado actual (hecho vs. falta)

### Lo que YA existe (hecho, verificado en código)

- **Catálogo canónico Supabase** — `products`, `product_variations` (SKU/precio/stock), `product_categories` (operativa per-tenant, ADR-0027), `platform_categories` (taxonomía global con `gid` Shopify Standard + `google_category_id`), `product_attribute_definitions` (contrato tipado ADR-0029, único vivo; `category_attributes`/`attribute_values` fueron dropeados). El productor canónico es `catalog_tool.get_tenant_catalog()`; proyecta **stock DISPONIBLE = `stock_quantity` − reservas activas**, no el bruto.
- **Stock cross-canal coherente** — `rpc_stock_decrement/restore` idempotente por `(order_id, variation_id, reason)` (ADR-0036), con `orders.channel_source`. Tres orígenes ya convergen (bot WhatsApp, webhook MeLi, consola).
- **Adapter de MENSAJERÍA** — Protocol `ChannelAdapter` + registry (`register_channel`/`get_channel_adapter`) con `_StubAdapter` **default-deny** pre-registrado para 7 canales. Patrón a espejar.
- **MeLi driver (import/sync-only)** — `meli_client.py`: `update_item_listing/quantity/status/price` (`PUT` sobre items **existentes**), `get_item`/`get_user_items`. `marketplace.py`: import, sync stock, link/unlink. `meli_webhook.py`: ingesta `orders_v2` → `orders(source='mercadolibre')`. Mapeo en `marketplace_listings` (`variation_id ↔ external_id`, `provider`).
- **Permisos MeLi concedidos por el founder** — Usuarios R/W, **Publicación y sincronización R/W** (habilita publish + sync), Métricas R, Venta y envíos R/W; topics `orders_v2`/`items`/`shipments`. Comunicaciones/messaging OFF.

### Lo que FALTA (gaps confirmados)

| Gap | Evidencia | Impacto |
|---|---|---|
| **No hay `publish` (`POST /items`)** | `meli_client.py` es PUT/import-only | El vínculo siempre nace de un item que YA existe en MeLi. "Supabase fuente de verdad" no es real para creación. Gap ADR-0037 Bloque 6. |
| **No hay API de categorías/atributos** | solo se persiste `meli_category_id` reactivamente | Sin `fetch_category_attributes` no se puede validar ni publicar. |
| **Precio NO event-driven** | `products.py:601` gatea push por `stock_quantity`; `update_item_price` existe y **nadie lo llama** | Cambiar solo el precio no se propaga → **drift**. |
| **Push disperso, sin dispatcher** | callers MeLi-hardcoded en `orders.py`/`products.py`/`marketplace.py` | Difícil de generalizar, sin idempotencia por dimensión. |
| **Columnas `meli_*` en tabla "genérica"** | `marketplace_listings.meli_title/thumbnail/condition/category_id/attributes/variation_id` | Un 2º provider acumularía `shopify_*`. Bloquea modularidad. |
| **Sin mapping de taxonomía/atributos** | no existe `channel_category_map`/`channel_attribute_map` | Categorías/atributos son cache crudo, no traducción. |
| **RLS rota en `marketplace_listings`** | `USING (tenant_id = auth.uid())` compara contra user id, no tenant | Bug latente **inerte** (aislamiento real lo dan los `.eq("tenant_id", tid)`, ADR-0025). Corregir al tocar la tabla. |
| **Sin single-flight de sync** | A2 residual ADR-0036/0037 | Empujes concurrentes sobre el mismo item son racy. |
| **Sin reconciliación/drift** | no hay `fetch_listing` comparador | Ediciones manuales en el canal o pushes fallidos silenciosos quedan sin detectar. |

---

## 3. Arquitectura objetivo — `CommerceChannelAdapter`

### 3.1 Modelo de autoridad (quién posee cada campo)

| Entidad | Dueño de la verdad | El canal tiene | Regla |
|---|---|---|---|
| Identidad producto/variante, `title`, `description`, `attributes` tipados, `category_id`, `safety_note`, imágenes | **Supabase** | copia proyectada | Push overwrites. Supabase gana SIEMPRE. |
| `price`, `compare_at_price` | **Supabase** | espejo (`external_price`) | Push overwrites. |
| **Stock disponible** (`bruto − reservas`) | **Supabase** (vía RPC) | espejo | Toda mutación entra por `rpc_stock_decrement/restore`, LUEGO fan-out. El canal NUNCA escribe stock directo en catálogo. |
| `external_id`, `permalink`, category/attr id del canal | **el canal** | — | Supabase cachea; nunca lo inventa. |
| Pedidos, tracking | evento nace en el canal; **registro durable = Supabase** (`orders.source=<provider>`) | estado de fulfillment | Ingesta idempotente por `external_order_id`; status monotónico. |
| Identidad comprador | el canal | `contacts` upsert (consent `marketplace_<provider>`) | — |

### 3.2 El contrato (Protocol, métodos concretos)

Nuevo módulo `services/api/lib/commerce/base.py`, hermano de `lib/channels/base.py`. Todos los args keyword-only; el adapter resuelve su token per-tenant con el patrón OAuth existente (`meli_client` single-flight refresh vía RPC lease + Vault) — no se pasa `access_token` crudo por firma pública (se admite inyección en tests).

```python
@runtime_checkable
class CommerceChannelAdapter(Protocol):
    # ── identidad / negociación de capacidad ──
    def channel_name(self) -> str: ...
    def capabilities(self) -> set[str]: ...
        # ⊆ {"publish","update","pause","resume","close","sync_stock","sync_price",
        #    "sync_images","categories","attributes","order_ingest","reconcile"}
        # Degradación grácil: MeLi HOY sin "publish" (import-only) hasta P4.

    # ── A. Ciclo de vida del listing (write; Supabase → canal) ──
    async def publish_listing(self, *, tenant_id, item: CatalogItem, supabase=None) -> PublishResult: ...
    async def update_listing(self, *, tenant_id, ref: ListingRef, item: CatalogItem, supabase=None) -> PublishResult: ...
    async def pause_listing(self, *, tenant_id, ref, supabase=None) -> PublishResult: ...
    async def resume_listing(self, *, tenant_id, ref, supabase=None) -> PublishResult: ...
    async def close_listing(self, *, tenant_id, ref, supabase=None) -> PublishResult: ...   # 'close' = delete lógico (MeLi no tiene hard-delete)

    # ── B. Sync de campo (hot paths; más barato que update completo) ──
    async def sync_stock(self, *, tenant_id, ref, quantity: int,
                         siblings: list[ListingRef] | None = None, supabase=None) -> StockSyncResult: ...
        # 'siblings' = otras variaciones del MISMO item externo (MeLi exige enviar TODAS en el PUT).
    async def sync_price(self, *, tenant_id, ref, price, compare_at=None, supabase=None) -> PriceSyncResult: ...
    async def sync_images(self, *, tenant_id, ref, image_urls: list[str], supabase=None) -> PublishResult: ...

    # ── C. Descubrimiento/validación categoría + atributos ──
    async def fetch_categories(self, *, tenant_id, root, supabase=None) -> list[ChannelCategory]: ...
    async def fetch_category_attributes(self, *, tenant_id, channel_category_id, supabase=None) -> list[RequiredAttribute]: ...
    async def suggest_category(self, *, tenant_id, item, supabase=None) -> ChannelCategory | None: ...
    def validate_for_publish(self, *, item, required) -> ListingValidation: ...   # BINARIA (ADR-0024): presencia + SET membership. NO NLP.

    # ── D. Ingesta de pedidos (canal → Supabase; el caller persiste) ──
    def verify_origin(self, *, headers, raw_body: bytes, tenant_id: str) -> bool: ...   # HMAC donde exista; IP-allowlist donde el canal no firma (MeLi)
    def parse_order_notification(self, payload: dict) -> OrderNotification: ...
    async def fetch_order(self, *, tenant_id, external_order_id, supabase=None) -> IngestedOrder: ...
    async def list_orders(self, *, tenant_id, since_iso, supabase=None) -> list[IngestedOrder]: ...   # backfill / /myfeeds

    # ── E. Reconciliación (canal → Supabase; solo lectura, para drift) ──
    async def fetch_listing(self, *, tenant_id, ref, supabase=None) -> ChannelListingState: ...
```

Dataclasses canónicas: `CatalogItem`, `ListingRef`, `PublishResult`, `StockSyncResult`, `PriceSyncResult`, `ChannelCategory`, `RequiredAttribute`, `ListingValidation`, `IngestedOrder/Line`, `OrderNotification`, `ChannelListingState` — **todas con `error_code`/`retry_after_seconds`** para propagar rate-limit. `CatalogItem` lo ensambla el caller desde `products + product_variations + product_attribute_definitions + product_categories`, proyectando **stock DISPONIBLE, no bruto**.

**DECISIÓN FINAL — registry separado, NO extender `ChannelAdapter`.** `lib/commerce/__init__.py`: `register_commerce_channel` / `get_commerce_adapter` / `list_registered_commerce_channels`, singleton `_COMMERCE_ADAPTERS`, mismo `_StubAdapter` default-deny (`verify_origin`→`False`, writes→`ok=False, error_code="STUB_ADAPTER"`). Pre-registro de stubs: `meli`, `shopify`, `web`. Un registry propio evita polución de stubs y permite que `meli` sea commerce-only sin implementar `send_outbound`, y `whatsapp` messaging-only sin implementar `publish_listing`.

### 3.3 Diagrama de flujo (textual)

```
                        ┌───────────────────────────────────────────┐
                        │              SUPABASE (verdad)             │
                        │  products · product_variations · stock     │
                        │  product_categories · attribute_definitions│
                        │  marketplace_listings · orders · reservas  │
                        └───────────────────────────────────────────┘
        OUTBOUND (Supabase → canal)  ▲  │  INBOUND (canal → Supabase)
   mutación catálogo/precio/stock    │  │  webhook pedido
        │ (misma tx)                 │  ▼
        ▼                            │  parse_order_notification → fetch_order
  commerce_sync_outbox  ──────────►  │  → resolver variation_id (marketplace_listings)
        │ worker single-flight       │  → upsert orders/order_items (idempotente)
        │ por (variation_id,provider)│  → rpc_stock_decrement  ──┐
        ▼                            │                            │ fan-out a OTROS canales
  get_commerce_adapter(provider)     │                            ▼   (cierra oversell)
        │                            └───────────────  commerce_sync_outbox
        ▼
  ┌──────────────┬──────────────┬──────────────┐
  │ MeliAdapter  │ WebAdapter   │ ShopifyAdapter│   ← cada uno PURE I/O, cero DB write
  │ (meli_client)│ (storefront) │ (shopify_cli) │
  └──────┬───────┴──────┬───────┴──────┬────────┘
         ▼              ▼              ▼
     API MeLi       Tienda web     Admin Shopify
```

### 3.4 Enchufar Shopify mañana (criterio de "modular")

1. **Implementar el adapter:** `integrations/shopify_client.py` (OAuth per-tenant + payloads Admin GraphQL/REST) + `lib/commerce/shopify.py` con `class ShopifyCommerceAdapter`. Declarar `capabilities()` real (Shopify SÍ tiene create → incluye `"publish"`).
2. **Registrar:** `register_commerce_channel("shopify", ShopifyCommerceAdapter())` (sobreescribe el stub).
3. **Mapping:** poblar `channel_category_map`/`channel_attribute_map` para `provider='shopify'`. Shopify usa Standard Taxonomy → `platform_categories.gid` **ya es el puente natural** (mapeo casi directo, ventaja sobre MeLi).
4. **Ingesta:** el webhook Shopify llama `verify_origin` (Shopify **SÍ firma HMAC** — más simple que MeLi) → `parse_order_notification` → pipeline §4.3 sin cambios (cae en `orders.source='shopify'`).
5. **Cero cambios** en catálogo Supabase, `catalog_tool` del bot, dispatcher outbox, esquema de `orders`/stock RPCs. Todo el acoplamiento nuevo vive dentro del adapter + filas de mapping.

---

## 4. Reglas de sincronización

### 4.1 Outbound (Supabase → canal): dispatcher único vía outbox transaccional

**DECISIÓN FINAL:** centralizar el push disperso en un **outbox transaccional** + worker fan-out.

```
mutación catálogo (products.py / orders.py / meli_webhook restock / consola)
   │ (misma tx que el UPDATE de catálogo)
   ▼
commerce_sync_outbox ← {tenant_id, variation_id, dims:{stock?,price?,images?,fields?}, dedup_key}
   ▼ worker (single-flight por variation_id+provider, colapsa ráfagas)
para cada marketplace_listings activo de esa variación:
   adapter = get_commerce_adapter(listing.provider)
   if dim ∈ adapter.capabilities():  adapter.sync_<dim>(...)   # fail-soft por listing
   persistir external_price / synced_at / status + sync_state
```

- **Conflicto:** Supabase gana SIEMPRE en outbound. La respuesta del canal (`confirmed_quantity/price`) se guarda como espejo, **nunca** se re-aplica al catálogo.
- **Idempotencia:** `dedup_key = (variation_id, provider, dim, value_hash)`. Si el último push confirmado tiene el mismo hash → skip (evita PUTs redundantes, respeta rate-limit). `sync_state.last_pushed_hash` por dimensión.
- **Orden de stock:** SIEMPRE `rpc_stock_decrement/restore` (idempotente) → leer disponible → encolar outbox → push. **Nunca** push directo desde el evento de venta.
- **Stock con variaciones (MeLi):** `sync_stock` recibe `siblings` y envía TODAS las variaciones del item externo con la verdad Supabase de cada hermano (0 solo si realmente 0), replicando `_resolve_variations_for_put`. El single-flight evita carreras entre dos hermanos que disparan el mismo PUT.
- **Precio ahora ES event-driven:** un cambio de precio sin cambio de stock encola `dim=price` → cierra el gap actual. `compare_at_price` se omite si el canal lo rechaza — el adapter lo captura como `warning`, no error.
- **Fail-soft:** error del canal marca la fila `retry` con backoff (respeta `retry_after_seconds`); nunca rompe la operación local. Tras N intentos → `dead` + alerta Sentry.

### 4.2 Publish (materializar producto nuevo) — orden estricto

1. Resolver categoría de canal vía `channel_category_map(tenant, provider, product_category_id)`. Si falta → `suggest_category()` y **pausar para confirmación humana** (nunca auto-publicar en categoría adivinada).
2. `fetch_category_attributes(channel_category_id)` → required.
3. `validate_for_publish(item, required)` → **binaria (ADR-0024)**. Si `missing_required`/`invalid_values` → NO publica, retorna a consola la lista exacta a completar.
4. `publish_listing()` → `PublishResult.external_id`.
5. **El caller** persiste `marketplace_listings` (`variation_id ↔ external_id`, provider, status, permalink).

### 4.3 Inbound (canal → Supabase): ingesta de pedidos

Generaliza `meli_webhook.py`:
1. `verify_origin(headers, raw_body, tenant_id)` — HMAC donde exista; IP-allowlist donde no (MeLi).
2. `parse_order_notification(payload)` → `external_order_id` + topic. Responder 200 rápido; procesar async.
3. `fetch_order(external_order_id)` → `IngestedOrder` completo (**no confiar en el payload de notificación**).
4. Resolver `variation_id` por línea vía `marketplace_listings`. Línea sin mapeo → persistir con `variation_id=NULL` + flag `unmapped` (no descartar; alerta).
5. Upsert idempotente `orders` (`source=<provider>`, `external_order_id` UNIQUE por tenant+provider) + `order_items`. **Status monotónico** (nunca retroceder `pending←paid←shipped`).
6. Upsert `contacts` (consent `marketplace_<provider>`).
7. `rpc_stock_decrement` idempotente → dispara §4.1 fan-out a los OTROS canales (cierra oversell cross-canal). Doble webhook = un solo decremento.
8. `shipments` → `orders.status` + `order_tracking`.

### 4.4 Evolución de schema (mapeo)

**DECISIÓN FINAL:** desacoplar columnas MeLi-específicas y añadir mapping de taxonomía/atributos.

- `marketplace_listings`: añadir `provider_metadata JSONB DEFAULT '{}'` (absorbe `meli_*` → evita columnas `shopify_*`/`web_*`), `channel_category_id TEXT`, `sync_state JSONB` (`{last_pushed_hash_by_dim, last_synced_at, drift}`). Mantener columnas `meli_*` hasta backfill. **Corregir la RLS rota (`auth.uid()`→tenant GUC) de paso.**
- **`channel_category_map`** (nuevo, per-tenant): `(tenant_id, provider, product_category_id) → channel_category_id, channel_path`. Se apoya en `platform_categories.gid`/`google_category_id`.
- **`channel_attribute_map`** (nuevo, per-tenant): `(tenant_id, provider, product_category_id, attr_code) → channel_attr_id, value_map JSONB`. Traduce el contrato ADR-0029 ↔ atributos del canal, incluido map de `value_id` para listas cerradas.

**RIESGO (RLS):** toda tabla de mapping nueva debe **nacer con RLS correcta** (`tenant_id = current tenant GUC`) + filtro explícito `.eq("tenant_id", tid)`. **No heredar el patrón roto** de `marketplace_listings`.

---

## 5. Roadmap incremental

MeLi primero; **tienda virtual como 2º adapter** (prueba barata de que la abstracción no es MeLi-shaped); Shopify como 3º (ejercita toda la maquinaria).

| Fase | Qué entrega | Tipo | Esfuerzo | Qué desbloquea |
|---|---|---|---|---|
| **P0** | Contrato `CommerceChannelAdapter` + registry + stubs default-deny + pact test | **code-only** | ~1.5 pd | Todo. Blast radius cero. |
| **P1** | `MeliCommerceAdapter` sobre `meli_client.py` (update/stock/price/status/get) + extraer parse de pedidos. Rewire callers con fallback a legacy | **code-only** | ~4 pd | Mecánica MeLi tras el adapter, invariante pure-I/O restaurado |
| **P1b** | `marketplace_listings.meli_* → provider_metadata jsonb` (dual-write → cutover) + fix RLS | **migración** (backward-compat) | ~3 pd | **Prerequisito estructural del 2º adapter** |
| **P2** | A2 single-flight de `sync_stock` (residual ADR-0036/0037) + price-sync event-driven | **migración** (lease/lock) | ~3 pd | Cierra racy pushes + gap de precio drift |
| **P3** | Mapping categorías/atributos: `fetch_categories`/`fetch_category_attributes`/`suggest_category` + `validate_for_publish` binario + tablas mapping | **migración + founder-gated** (curar) | ~6 pd + curación | Base de todo publish real |
| **P4** | `publish_listing` = `POST /items`, **default validate-only** (dry-run) + schema gaps comercio formal (`gtin/currency`, `brand/mpn/slug`) | **migración** | ~7 pd | "Supabase fuente de verdad" real para creación |
| **P5** | GO-LIVE publish (flip validate-only → POST real, per-tenant) | **founder-gated (hard)** | ~1 pd + decisión | Publicar comprable desde consola |
| **P6** | Ingesta de pedidos generalizada tras el adapter + backfill `list_orders` (`/myfeeds`) | code-only (parte migración) | ~3 pd | Recuperación de pedidos perdidos |
| **P7** | 2º adapter = **tienda virtual** (seat del adapter; storefront FE = track XL aparte) | **code-only** (seat) | ~2 pd | Prueba de modularidad; 4º canal sin cambio de esquema |

**Spine code-only hasta publish validate-only (P0–P4, sin storefront FE): ~24–28 pd.** GO-LIVE (P5) y curación (P3) son gated.

**La tienda virtual necesita solo P0 + P1b + P6** — NO P3/P4/P5. Es el caso degenerado donde fuente-de-verdad = canal: `publish` es no-op (el catálogo ya vive en Supabase), `sync_stock` es leer el DISPONIBLE, `order_ingest` es el checkout escribiendo `orders(channel_source='web')`. Por eso conviene construir su *seat* justo tras P1b/P6, **antes** de invertir en el publish MeLi pesado.

---

## 6. Decisiones y acciones del founder

### VALIDAR EN DOCUMENTACIÓN OFICIAL (MeLi) — bloquea construir P3/P4 sin adivinar
El dossier no pudo fetchear el portal (403). **No implementar `publish` antes de cerrar esto** (no inventar endpoints):
- **`POST /items` MCO:** body exacto (`category_id`, `listing_type_id`, `buying_mode`, `condition`, `currency_id`, `pictures[]`, `attributes[]`) + `attributes_required` por categoría + payload de variaciones-on-create + si acepta URLs de imagen externas o exige pre-upload.
- **`GET /categories/{id}/attributes`:** enum `value_type` + `tags` (`catalog_required`, `allow_variations`) que alimentan `RequiredAttribute`/`ListingValidation`.
- **Decimales COP en create** (confirmado en update: `int(round(price))`), rate-limits reales (~5000/h/user_id **sin confirmar**) y presencia de header `Retry-After` (**sin confirmar**), schema `/myfeeds` para backfill.
- **NO agregar `ack_order`:** sin endpoint de ack confirmado para MCO no-FBM (dossier V-2).

### INTERVENCIÓN HUMANA REQUERIDA
- **RESPONSABLE:** founder + eng.
- **PASOS:** (1) **curar el mapping categoría/atributos Konvi→MeLi por vertical** (P3) — el código es code-only, el *contenido* es gated; ADR-0029 §8 exige curaduría humana + legal en categorías reguladas (Salud y Belleza KAIU); (2) decidir **GO-LIVE publish per-tenant** con consentimiento explícito + suscribir tópicos en el panel MeLi de cada tenant (Model B, ADR-0023); (3) confirmar migraciones `provider_metadata` + `channel_category_map`/`channel_attribute_map`; (4) confirmar que **la tienda virtual usa este mismo adapter** (recomendado: sí, 4º canal sin cambio de esquema).
- **INSUMOS:** dossier MeLi §2.1/§5/§9, taxonomía MCO, permisos concedidos (Publicación R/W habilita publish+sync).
- **CRITERIO DE ÉXITO:** un producto nacido en Supabase se valida binariamente (SET-membership verde) + `POST /items/validate` dry-run sin errores → se publica en MeLi → vende → descuenta stock idempotente → re-empuja a los demás canales **sin oversell**.

### RIESGO
Publish real crea listings comprables (comisión/moderación/CBT MeLi = compromiso de marca y dinero). **Mitigación / recomendación: validate-only permanente por default; go-live per-tenant.** El esfuerzo de código del flip es trivial; el gate es de negocio, no técnico.

---

## 7. Recomendación neta

**Empezar por P0 → P1 → P1b, en ese orden, como bloque code-only + una migración backward-compat.** Justificación:

1. **P0 es riesgo cero y desbloquea todo** — es puro contrato + registry + stubs, sin tocar ningún caller. Aterriza la abstracción antes de mover nada.
2. **P1 restaura un invariante que hoy está roto** — la mecánica MeLi ya existe pero dispersa; envolverla con fallback-a-legacy no cambia comportamiento (los ~3490 tests + UAT sync dinámico validan no-regresión) y devuelve el push a "pure I/O, el caller persiste".
3. **P1b es el prerequisito estructural real de la modularidad** (`provider_metadata` + fix RLS) y **no bloquea MeLi**. Sin él, un 2º provider degenera en columnas `shopify_*`.
4. **Luego P2** (single-flight + precio event-driven) cierra dos gaps de reliability con impacto invisible al usuario y sin nueva capacidad de negocio.

Tras P1b, **construir el seat de la tienda virtual (P7) + ingesta generalizada (P6) antes que el publish MeLi pesado (P3/P4)**: la tienda web es la prueba barata de que la abstracción no es MeLi-shaped, y no arrastra los bloqueos de documentación oficial de MeLi.

**P3/P4/P5 quedan detrás del gate founder + validación oficial de endpoints MeLi** — no arrancar hasta cerrar el bloque VALIDAR EN DOC OFICIAL. Default recomendado permanente: **validate-only**; GO-LIVE per-tenant con consentimiento explícito.

---

### Anexo — hecho / hipótesis / pendiente-de-validar

- **HECHO (verificado en código):** Protocol y registry de mensajería; `marketplace_listings` schema + RLS-bug; ausencia de `POST /items` y de API de categorías en `meli_client.py`; `rpc_stock_decrement` idempotente con `channel_source`; catálogo lee Supabase siempre; precio no event-driven (`update_item_price` sin caller).
- **HIPÓTESIS / RECOMENDACIÓN (este diseño):** outbox transaccional único, `provider_metadata`, `channel_category_map`/`channel_attribute_map`, reconciliación por `fetch_listing`, credencial resuelta por el adapter, registry de comercio separado.
- **PENDIENTE DE VALIDAR (no implementar publish antes):** contrato `POST /items` MCO, shape de `GET /categories/{id}/attributes`, decimales COP en create, ingestión de imágenes (URL vs pre-upload), rate-limits + `Retry-After`, schema `/myfeeds`, category predictor. Sin ack a MeLi hasta confirmar endpoint (V-2).
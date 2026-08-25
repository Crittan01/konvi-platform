# Track 5 · M1 — Inventario verificable de capacidades por dominio

> Método: inventario ejecutado 2026-08-24 sobre `develop` @ `d0039e89`, **cero suposiciones** — cada
> afirmación tiene evidencia `archivo:línea` contra el código vivo. 6 frentes de exploración en
> paralelo (catálogo+stock · pedidos+comprobantes · contactos+envíos · promociones+reclamos ·
> compras+finanzas · analítica+canales). Es la fase M1 de
> [`modular-domains-vision.md`](modular-domains-vision.md): matriz dominio × (consola / bot /
> contrato existente) → **backlog exacto de la capa de servicios** (§ final).
> El diseño del contrato que sale de este inventario: [`domain-services-contract.md`](domain-services-contract.md) (M2, propuesta).

---

## 1. Matriz resumen — dominio × superficie

Leyenda: ✅ existe · ❌ no existe · ⚠️ existe pero degradado/duplicado.
"Consola REST" = pasa por el API FastAPI · "Consola DB-directo" = la página lee/escribe Supabase/PostgREST con RLS sin pasar por el API · "Bot" = superficie en `services/ai-orchestrator`.

| Dominio | Consola REST | Consola DB-directo | Bot | Lógica única hoy | Duplicación / drift principal |
|---|---|---|---|---|---|
| **Catálogo** | ⚠️ writes sí; reads no | reads (`catalog/page.tsx:84-98`) | lector + envío imagen | ⚠️ `catalog_contract` partido en 2 productores | shape canónico ×2 · label variante ×2 · fallback categoría ×3 · validación atributos ×2 (server/client) |
| **Stock** | ❌ ajuste sin endpoint REST | ajuste/threshold/media directos (`page.tsx:438-531`) | reservas, consumo, disponible neto | ✅ RPCs SQL transaccionales | restock al cancelar **×3** · escrituras `stock_quantity` fuera de RPC ×3 · bruto (consola) vs neto (bot) |
| **Pedidos** | ⚠️ create/patch/payment-link sí; **listado no** | listados (`orders/page.tsx:88`) | crea vía REST; lee DB directo ×3 | ✅ creación unificada en REST | cancelación **2 pipelines** divergentes · reuso de link ×2 con TTL espejado |
| **Comprobantes** | ❌ sin endpoints | lectura snapshot (`receipts/`) | emisión/entrega en crons del worker | ✅ `rpc_issue_receipt` SQL (ADR-0040) | formato COP/fecha ×3 copias |
| **Contactos** | ⚠️ writes sí; reads no | reads (`contacts/page.tsx:127`) | upsert + tools PII/consent | ❌ | consent/Habeas Data: **4 máquinas de estados** divergentes |
| **Envíos** | ⚠️ quote/rate con semántica pobre; history no | reads (`shipping/page.tsx:75`) | cotización completa (COD+filtros) directo al cliente | ❌ | cliente Aveonline **×2 idénticos** (1507 líneas) · cotización 2 semánticas · mapping estados ×2 · libs ×2 |
| **Promociones** | ⚠️ CRUD sí; GET no | reads + redenciones | anunciar/aplicar/quitar (gate pre-LLM) | ✅ `api/lib/coupons.py` (ADR-0015) vía sys.path hack | validación de input ×2 (TS/PY espejo manual) |
| **Reclamos** | ✅ CRUD + reversión | reads (`claims/page.tsx:32-41`) | create + get_by_ticket (DB directo) | ✅ RPCs reversión en SQL | **2 writers divergentes** · vocabulario de estados extinto en el bot |
| **Compras** | ✅ CRUD + receive | reads (`purchases/page.tsx:45-112`) | ❌ nada | ❌ | receive multi-tabla **no atómico** |
| **Finanzas** | ⚠️ expenses create/reverse; P&L no | reads + **P&L calculado en TS** | ❌ nada | ❌ | `PAID_ORDER_STATUSES` **×4** · P&L client-side con cap 1000 filas |
| **Analítica** | ⚠️ insights/stats/sic-report | reads métricas + auditoría | ❌ nada | ⚠️ RPCs métricas (incompatibles con bot) | "ingreso reconocido" **×5** · ventana hora Colombia ×3 |

**Verificaciones de nomenclatura (correcciones a lo esperado):** la tabla es `product_variations`
(no `product_variants`), el ledger es `stock_movements` (no `inventory_movements`), los carritos son
`conversation_carts`/`conversation_cart_items`, las OCs son `purchase_orders`/`purchase_order_items`,
**no existe** tabla `media` (bucket Storage + columnas URL), **no existen** `data_subject_requests`
(SAR = eventos en `consent_audit_log`), **no existe** `shipping_quotes` (cotizaciones = `shipments`
con `status='quoted'`), y `rma_requests` es **tabla muerta** (sin writers ni readers operativos;
solo la mencionan el RPC de revenue y el offboarding).

---

## 2. Hallazgos estructurales transversales (lo que el contrato debe resolver)

### H1 — La restricción de despliegue manda: hoy se "comparte" código copiándolo

Los servicios tienen rootDirs separados en Render y **no pueden importarse entre sí**. Hoy eso se
resuelve de 4 maneras, todas deuda:

1. **Copia física idéntica**: `aveonline_client.py` (1507 líneas) existe en `services/api/integrations/`
   y `services/ai-orchestrator/integrations/` — verificado con `diff`, idénticos. Igual las libs
   `tenant_carriers.py` (191), `carrier_capabilities.py` (409), `dane_resolver.py` (80). Cada fix se
   aplica dos veces a mano, sin mecanismo que lo garantice.
2. **sys.path hack**: `services/ai-orchestrator/lib/coupons.py:16-18` inserta `services/api/lib` en
   `sys.path` para reusar el motor de cupones — el propio docstring (:7-9) declara la deuda:
   falta `packages/shared-py/`.
3. **Duplicación "a conciencia"**: helpers de formato replicados en `receipt_email.py:7-11`;
   inserción de `cart_events` duplicada en el API (`orders.py:838-841`) "para mantener el boundary
   de servicios".
4. **Bajar la convergencia a SQL** (el precedente exitoso): `rpc_issue_receipt` nació porque "hay
   cinco caminos a 'confirmed' repartidos en tres servicios… el documento se arma igual venga de
   donde venga" (migración `20260725110000:8-14`, ADR-0040). Igual `rpc_stock_decrement`/
   `rpc_stock_restore`/`coupon_increment_redemption`/RPCs de reversión.

### H2 — La consola NO es un canal REST homogéneo

Las **escrituras** pasan por el API; las **lecturas** van directo a PostgREST con RLS en casi todos
los dominios (catálogo, pedidos, contactos, envíos, promociones, reclamos, compras, finanzas,
analítica, auditoría, KB, AI Agents). Endpoints GET de listado que **no existen**: `GET /orders/`,
`GET /contacts/`, `GET /contacts/{id}`, `GET /coupons`, `GET /expenses`, `GET /shipping/history`
(este último anunciado en el docstring `shipping.py:8` pero no implementado), REST de comprobantes,
REST de P&L. Excepciones que sí tienen GET: `GET /claims`, `GET /purchases/`, `GET /products/{id}`,
`GET /conversations/*`.

### H3 — El bot tiene "domain services" enterrados, no compartidos

Dominio puro que hoy vive SOLO dentro del orchestrator (candidatos directos a extracción):

| Pieza | Ubicación | Qué es |
|---|---|---|
| Inventory service transaccional | `services/ai-orchestrator/lib/stock_reservation.py` (348 líneas) | wrapper de los RPCs de reserva/consulta de disponible |
| Pipeline legal de cancelación | `services/ai-orchestrator/lib/order_cancellation.py` (861 líneas) | 11 pasos: reglas, retracto, void Wompi, cancel guía, audit SIC |
| Shipping service completo | `services/ai-orchestrator/agentic/legacy_adapters/aveonline.py` (480) | geo→paquete→cliente→filtros COD/carriers→persist |
| Read de catálogo customer-facing | `services/ai-orchestrator/tools/catalog_tool.py:58-230` | shape + categorías + disponible neto batch |
| Entrega de comprobantes | `services/ai-orchestrator/worker_commerce_crons.py:634-957` | servicio de dominio disfrazado de cron |
| Reembolsos/constancias | `services/ai-orchestrator/refund_notifications.py` + crons | copia declarada de la notificación del API |

Además hay **código muerto verificado** en `services/ai-orchestrator/tools/` (sin callers de
producción, solo tests): `known_customer_tool.py` (213), tracking de `order_status_tool.py:299`,
`handle_shipping_quote_if_applicable`, `requote_shipping_for_cart`. El inventario real del bot es el
registry agentic: **20 tools, todas customer-facing, cero de negocio/owner** (`get_cart, add_to_cart,
update_cart_item_quantity, remove_cart_item, set_shipping_recipient, quote_shipping, select_carrier,
create_claim, get_claim_status, send_product_image, get_contact_info, record_consent, save_*,
get_recent_orders, list_catalog, search_products, kb_query, escalate_to_human, generate_payment_link`).

### H4 — Lo que YA es cimiento (no se toca, se adopta como patrón)

- **RPCs transaccionales en Postgres** con guards de idempotencia: `rpc_stock_reserve/consume/release`,
  `rpc_stock_decrement/restore` (`FOR NO KEY UPDATE`, movement único), `fn_variation_available_stock`,
  `rpc_issue_receipt` + guarda `rpc_order_money`, `coupon_increment_redemption`, RPCs de reversión
  SECURITY DEFINER con constancia congelada (`20260726160000`).
- **Motor de cupones channel-agnóstico** `services/api/lib/coupons.py` (631 líneas, ADR-0015):
  `validate_coupon_applicable` / `compute_discount` / `apply_coupon` / `revoke_coupon` /
  `consume_redemption` — el mejor precedente de domain service del repo.
- **Creación de orden unificada en REST** (`orders.py:143-410`): total recomputado server-side,
  descuento heredado con guard de redención, índice anti doble-cobro
  (`uq_orders_one_pending_payment_per_conversation`), adopt-winner (23505→re-lectura), Idempotency-Key
  (`dependencies/idempotency.py`). **El bot ya la consume por HTTP dual-auth**
  (`payment_link_tool.py:734-748`) — precedente real del patrón "bot → contrato de dominio".
- **Infraestructura transversal**: dual-auth (JWT operador o `X-Internal-Service-Secret` +
  `X-Tenant-Id`, `dependencies/internal_auth.py`), RBAC por endpoint, MFA AAL2 en money-movement,
  rate-limit, `write_audit_event` + `@audit_log` (`dependencies/audit.py`), `log_pii_access`,
  RLS como última barrera (Track 9).
- **Precedente de read-service**: `insights.py` (RPC exacto + feature-detect + fallback acotado +
  flags `revenue_is_exact/approximate`).

### H5 — Contexto tenant incompatible con el canal bot en los RPCs de métricas

`metrics_orders_summary` / `metrics_orders_timeseries` / `rpc_dashboard_revenue` derivan el tenant de
`auth.jwt()` → con service key devuelven vacío; el API lo resuelve re-inyectando el Bearer del usuario
(`insights.py:100-120`). Un domain service llamado desde el bot (service role, sin JWT de usuario)
necesita contexto explícito — patrón ya existente en workers: GUC `app.current_tenant_id` /
`app_current_tenant()` (Track 9).

### H6 — Entidades que el modelo de dominio necesita y no existen

- `data_subject_requests` (SAR con ciclo de vida pendiente→tramitado→cerrado — hoy eventos sueltos).
- Separación cotización/envío: `shipments` mezcla `status='quoted'` con guías reales; además hay DOS
  historiales de tracking por canal de venta (`shipment_tracking_events` = Aveonline;
  `order_tracking` = solo MeLi, `meli_webhook.py:817-842`).
- `rma_requests` muerta → "devoluciones/RMA" es greenfield (el retracto real corre por
  `order_cancellations`, fuera de claims).

---

## 3. Inventario por dominio (detalle con evidencia)

### 3.1 Catálogo

**Tablas:** `products`, `product_variations` (`20260406181236`), `product_categories` per-tenant
(`20260627120000`), `product_attribute_definitions` (ADR-0029, `20260630120000`), bucket Storage
`tenant-media` (sin tabla). Adyacentes: `marketplace_listings`, `platform_categories`.

**Capacidades (consola REST):** listar `GET /products/` (`products.py:276`) · detalle
`GET /products/{id}` (`:470`) · crear con variantes atómico `POST /products/` (`:304-382`) · bulk
≤500 `POST /products/bulk` (`:385-467`) · PATCH semántico (`:496-554`) · soft/hard delete
(`:714-741`) · CRUD variantes (`:557-711`) · CRUD categorías (`product_categories.py:39-209`) ·
CRUD contrato de atributos (`product_attribute_definitions.py:80-207`) · catálogo canónico ADR-0028
`GET /catalog/` (`catalog.py:57-93`) · sugerencia IA draft (`catalog_ai.py:117-185`).
**Consola DB-directo:** TODAS las lecturas de la página (`catalog/page.tsx:84-98`) + media library
(directo a Storage, `media-client.tsx:41-80`).
**Bot:** lector vía `get_tenant_catalog` (`catalog_tool.py:58-230`, DB directo service_role) + tools
LLM `list_catalog`/`search_products` (`agentic/tools/catalog.py:61,250`) + envío de imagen
(`agentic/tools/media.py:104-221`). **El bot no escribe catálogo.**

**Drift medido:**
1. La "forma canónica" tiene **dos productores divergentes**: API `catalog.py:28-54` (sin
   `price_min/price_max/stock_total/category_group`) vs bot `catalog_tool.py:203-223`; el pacto
   (`tests/test_catalog_canonical_contract.py`) solo sincroniza la constante `variants`, no el shape.
2. **Label de variante ×2**: `catalog_contract.variant_label` (`catalog_contract.py:68-85`) vs
   `" / ".join(attrs.values())` propio del API (`catalog.py:33`).
3. **Fallback de categoría por título ×3**: `catalog_tool.py:26-37` · `agentic/tools/catalog.py:158-166`
   · `system_prompt.py:53-68`.
4. **Normalización de unidades ×2 con drift**: `catalog_contract.py:53-65` vs
   `agentic/tools/cart.py:29-86` (alias `lt` vs `l` divergentes).
5. **Validación del contrato de atributos ×2**: server `products.py:240-271` ↔ espejo client
   `catalog/_lib/attribute-contract.ts:37-55` (admite "espeja normKey + canonicalizeAttrs").
6. Import cross-router: `products.py:35` importa `sync_meli_stock` de `routers/marketplace.py`.

**Falta:** el bot no puede escribir catálogo (correcto por rol); la consola no ve **disponible neto
de reservas**; `/api/v1/catalog` **no tiene consumidores reales** (el bot lee DB in-process, la
consola PostgREST).

### 3.2 Stock / inventario

**Tablas/RPCs:** `product_variations.stock_quantity` (+`cost_price` WAC) · `stock_movements`
(`20260409240000`, UNIQUE idempotencia `(order_id, variation_id, reason)`) · `stock_reservations`
(TTL, `20260502000000`) · RPCs `rpc_stock_reserve/extend/consume/release`,
`fn_variation_available_stock`, `fn_expire_stock_reservations` · `rpc_stock_decrement/restore`
(`20260711000000`) · `tenants.low_stock_threshold`.

**Capacidades:** ajuste manual delta+motivo+ledger — **SOLO consola, sin REST, no transaccional**:
server action `adjustStock` (`catalog/page.tsx:438-531`, update+insert+audit a mano; el propio
comentario `:487-489` declara la deuda "mover a un RPC atómico") · set absoluto vía PATCH variante
(`products.py:557-611`, **sin movement ni guard de reservas**) · historial (lectura directa drawer +
`insights.py:175-209`; **sin REST de movimientos**) · reserva soft 15min al agregar al carrito (bot,
`lib/stock_reservation.py:67-124` ← `agentic/tools/cart.py:385-395`) · extensión 35min pre-pago +
re-check (`payment_link_tool.py:355,416-419`) · consumo al confirmar pago
(`orders._decrement_stock_on_confirm` `orders.py:966-1059` ← `wompi_webhook.py:1141-1160`) ·
reposición al cancelar (`orders.py:1062-1089`) · restock por OC recibida + WAC
(`purchases.py:446-521`, **read-modify-write no atómico** `:500-510`) · disponible neto (solo bot:
`stock_reservation.available_stock:274-308` + batch `catalog_tool.py:124-141`) · sync MeLi.

**Drift medido:** reposición al cancelar **TRIPLICADA** (`orders.py:1062` · `meli_webhook.py:494-527`
· `lib/order_cancellation.py:597-649`) · escrituras de `stock_quantity` fuera de los RPCs atómicos
×3 (PATCH absoluto, receive compras, ajuste consola) · disponibilidad: bot vende contra **neto**,
consola/insights muestran **bruto** · deuda conocida de idempotencia cross-path `sale` vs
`reservation_consumed` (`wompi_webhook.py:1151-1154`, W3-remainder).

**Falta:** endpoint REST de ajuste con ledger · REST de movimientos · superficie de reservas activas
para el operador · disponible neto como concepto de primera clase en ambos canales.

### 3.3 Pedidos (dominio PILOTO M2)

**Tablas:** `orders`, `order_items` (`20260409220000:26,42`) · `payments` (`20260424200000:17`) +
vista `payments_safe` (`20260822120100:79`) · `order_cancellations` + `tenant_cancellation_policy`
(`20260606000000:55,232`) · `conversation_carts`/`conversation_cart_items` (`20260501000000:17,97`)
· `stock_reservations` · `wompi_events_seen` · `cart_events` (`20260510090000:18`) ·
`idempotency_keys`.

**Capacidades (consola REST):** crear `POST /orders/` (`orders.py:143`) · detalle `GET /orders/{id}`
(`:413`) · PATCH estado/notas con máquina de estados (`:442`, transiciones `:67-74`, cancel
owner/manager + MFA `:456,483-487`) · payment-link `POST /orders/{id}/payment-link` (`:540`, reuso
TTL `:637-677`) · generar guía (`:1126`). **Sin `GET /orders/` de listado** — la consola lista
directo Supabase (`orders/page.tsx:88`).
**Bot:** crea orden vía REST dual-auth (`payment_link_tool.py:734-748`, keys determinísticas
`ordc:{conv}:{cart_hash}` / `plink:{order}:b{bucket}` `:220-229,721-730`) · lee DB directo ×3
(`order_status_tool.py:241` · `agentic/tools/orders.py:87` · `cancel_intent_resolver.py:103`) ·
pipeline de cancelación completo (`lib/order_cancellation.py:241-440`) · invalidación de orden
stale al mutar carrito (`cart_tool.py:176-320`) · sweeper TTL 35min (`worker.py:3554-3565`) ·
recordatorios de pago (`worker_commerce_crons.py:54`).

**Dónde vive la lógica / drift:**
1. **Creación + invariant de dinero: UNA sola vez en el router** (el buen precedente) — total
   recomputado `:184,221`, guard de redención `:194-218`, adopt-winner `:285-340`.
2. **Cancelación: DOS pipelines que no comparten código.** Consola: flip + restock, **sin
   `order_cancellations`, sin void Wompi, sin cancel de guía** (`orders.py:529-530,1062-1123`). Bot:
   pipeline legal completo con void auto (CARD <23h), cancel Aveonline, audit SIC, confirmación en 2
   turnos B6 (`order_cancellation.py:241-440`, refund `:686-778`). La consola cancela "a medias".
3. **Política de reuso de link duplicada**: criterio espejado `orders.py:617-658` ↔
   `payment_link_tool.py:117-140` (el comentario `:621-636` admite "se espeja EXACTO"); TTL espejado
   `payment_link_ttl_minutes()` vs constante local `WOMPI_LINK_TTL_MINUTES = 30`
   (`payment_link_tool.py:47` — drift posible).
4. Mínimo Wompi $1.500 validado ×2 (`orders.py:685` · `payment_link_tool.py:39,457`); guard
   monto/moneda en webhook (`wompi_webhook.py:632-656`); coherencia `rpc_order_money` en comprobante.
5. `cart_events` con 16 tipos canónicos (`cart/events.py:40-66`) emitidos desde bot, API (insert
   duplicado `:842-849,883-897`) y webhook — sin bus unificado, nadie los consume salvo telemetría.

**Falta:** `GET /orders/` listado · endpoint de refund explícito · transiciones manuales desde el bot
(correcto por rol) · cancelación con void/audit desde consola · lectura unificada (3 reads del bot +
RLS consola).

### 3.4 Comprobantes (ADR-0040)

**Tabla:** `order_receipts` (`20260725110000:133`; UNIQUE(tenant,order), snapshot congelado,
consecutivo `CP-NNNNNN`, `content_hash`, guarda `rpc_order_money`).

**Capacidades:** emisión 100% RPC `rpc_issue_receipt` (`20260725110000:197`) disparada por barrido
10min en el worker (`worker_commerce_crons.py:634-714`) · anulación por trigger al cancelar +
reconciliación (`:719-743`) · acuse WhatsApp legal (`:767-850`) · email Resend
(`receipt_email.py:186`) · vista imprimible consola (`receipts/[id]/page.tsx:29`, lee SOLO snapshot).
**Sin endpoint REST alguno** (cero matches de `receipt` en `services/api`).

**Drift:** formato COP/fecha ×3 (`receipt_email.py` · `receipts/_lib/receipt.ts` · helpers de
`wompi_webhook.py` — duplicación declarada `receipt_email.py:7-11`). Guarda legal anti-factura-DIAN
por test de contrato.

**Falta:** REST de comprobantes · emisión/reenvío bajo demanda desde consola · consulta conversable
("mándame mi comprobante") · tiempo de entrega en el contenido tasado (ADR-0040 `:233-235`).

### 3.5 Contactos

**Tablas:** `contacts` (UNIQUE(tenant,phone)) · `consent_audit_log` (append-only) · `pii_access_log`
· `conversations`, `messages` · **no existe `data_subject_requests`**.

**Capacidades (consola REST):** crear `POST /contacts/` (`contacts.py:276`) · PATCH presencia-de-campo
(`:393`) · delete soft/anonimización (`:836`) · purga física owner (`:716`) · reactivar consent
(`:561`) · SAR export (`data_subject_request.py:256`) + printable (`:569`) + rectify/erase
(`:322-404`). **Sin GET** (docstring anuncia `GET /` no implementado) — lecturas directo Supabase
(`contacts/page.tsx:127`).
**Bot:** upsert silencioso al primer inbound (`dispatcher.py:939-955`) · `get_contact_info` con
auditoría PII (`agentic/tools/contact.py:94-204`) · `save_contact_field` consolidado + 5 individuales
(`:488-1042`) · `record_consent` (`:222-338`) · STOP keyword (`deterministic_gates.py:422-614` →
`whatsapp_optout.py:195-221`) · re-opt-in (`:160-174`) · SAR Art.14 self-service enmascarado
(`deterministic_gates.py:99-141`).

**Drift medido — 4 máquinas de estados de consent con diferencias legales materiales:**
1. API PATCH (`contacts.py:163-271`): la rica — Guard A anti soft-revoke, Guard B renovación,
   `consent_source/channel/notice_version` obligatorios (422), renewals cap 50.
2. Bot `RecordConsentTool`: flip simple; en revoke **anonimiza y cierra conversación**; **no escribe
   `consent_source/channel/notice_version`** (el API los exigiría).
3. STOP keyword: solo `consent_revoked_at`, PII intacta (lista de supresión), keywords ambiguas con
   pedido activo no dan de baja.
4. SAR erase: anonimiza como bot-revoke pero **sin cerrar conversaciones**.
Reactivación también diverge (consola owner+reason ≥10+audit vs bot keyword que solo limpia campos).

**Falta:** GET de contactos · SAR con entidad y ciclo de vida · unificación de la máquina de consent
(la del API es la referencia legal).

### 3.6 Envíos

**Tablas:** `shipments` (mezcla quoted+labeled; columna legacy `envia_shipment_id`) ·
`shipment_tracking_events` (`20260529000000:22` + RPC `fn_record_shipment_tracking_event`) ·
`order_tracking` (solo MeLi) · `tenant_shipping_provider_config` (`real_guides_enabled`) ·
`tenant_carriers` · `aveonline_carrier_capabilities` · `tenant_integrations` (credenciales Vault).

**Capacidades (consola REST):** cotizar `POST /shipping/quote` (`shipping.py:461` →
`_quote_via_aveonline:184-351` — **sin COD, sin filtro `tenant_carriers`, sin capabilities**) ·
confirmar tarifa `PATCH /shipping/{id}/rate` (`:670` + reconciliación `orders.total_amount`
`:545-667`) · purgar huérfanas (`:764`) · guía manual (`orders.py:1126-1239`) · webhook tracking
(`aveonline_webhook.py:778`) · credenciales/agentes/webhook/carriers (`integrations.py:613-1418`).
**Bot:** cotización completa COD+filtros+capabilities **directo al cliente, sin pasar por el API**
(`agentic/legacy_adapters/aveonline.py:26-480` — el domain service más avanzado, enterrado) ·
select_carrier fuzzy (`agentic/tools/shipping.py:347-597`, persiste en cart, **no en `shipments`**)
· guía COD vía endpoint del API (`payment_link_tool.py:824-863`) · cancelación de guía
(`order_cancellation.py:781-822` — **única implementación del sistema; la consola no puede**) ·
poll backup de tracking (`worker.py:3092-3299`).

**Drift medido:** cliente Aveonline **×2 idénticos** (1507 líneas, diff-verificado) · mapping de
estados **espejo declarado** (`aveonline_webhook.py:86-128` ↔
`shipment_status_notifications.py:48-99`, comentarios "ESPEJO") · copy de notificaciones ×2 · libs
idénticas ×3 · fallback `declared_value=50000` ×2 · **la misma capacidad "cotizar" produce
resultados distintos según canal** (carrier deshabilitado aparece en consola, no en bot; COD solo
cotizable por bot).

**Falta:** `GET /shipping/history` (anunciado, no implementado) · cancelar guía en consola ·
cotización COD en consola · tracking conversable con historia de eventos (el bot lee `shipments`
pero no `shipment_tracking_events`) · separación cotización/envío.

### 3.7 Promociones (cupones)

**Tablas:** `coupons` (CHECKs tipo/percent/fechas/tope, UNIQUE(tenant,code), `is_customer_visible`)
· `coupon_redemptions` (FSM `applied|consumed|revoked`, 1 activo/cart, append-only) · columnas
materializadas en `conversation_carts` (`coupon_id`, `coupon_code`, `discount_cents`).

**Capacidades (consola REST):** crear `POST /coupons` (`coupons.py:103-144`) · PATCH (`:147-180`) ·
delete solo si 0 redenciones (`:183-222`). **Sin GET** — lecturas directo Supabase
(`promotions/page.tsx:386-396`) + redenciones (`:342-369`).
**Bot:** anunciar (query + render en prompt, `dispatcher.py:1018-1065` → `system_prompt.py:357-407`,
excluida en estados terminales) · aplicar/quitar vía **gate determinístico pre-LLM, no tool LLM**
(`lib/coupon_detector.py:121-205` → `dispatcher.py:1412-1568` → motor `api/lib/coupons.py:280-512`)
· revalidar/auto-revocar al mutar carrito (`cart_tool.py:69-173`, emite `coupon_auto_revoked`) ·
consumo al pago (`orders.py:862-912` → RPC `coupon_increment_redemption`).

**Dónde vive:** el motor YA es domain service de-facto (`api/lib/coupons.py`, ADR-0015,
"channel-agnóstico" declarado `:5-6`) distribuido por **sys.path hack** (`orch/lib/coupons.py:16-18`).
**Drift:** validación de input espejo manual TS (`promotions/page.tsx:95-128`) ↔ Python
(`coupons.py:92-100`); filtro "anunciable" inline solo en el dispatcher; **no existe tool de cupón
en el registry agentic** (las 20 tools registradas no lo incluyen — invariante `tool_code_leak.py:34`
censura el string).

**Falta:** `validate_coupon(code, subtotal)` expuesto (la función pura existe `api/lib/coupons.py:152-223`)
· aplicar cupón a una conversación desde consola · GET de cupones.

### 3.8 Reclamos (dominio PILOTO M2)

**Tablas:** `claims` (ticket secuencial per-tenant por trigger, CHECK status, `refunded_amount/at`
write-once) · `payment_reversal_requests` (UNIQUE(claim_id), escritura SOLO vía RPCs SECURITY
DEFINER) · **no existe `claim_messages`** (rastro en `messages` `content_type='claim_audit'`) ·
`rma_requests` muerta.

**Máquina de estados (solo en el router):** `VALID = {open, investigating, resolved, refunded,
rejected, cancelled}` (`claims.py:47`) · `TERMINAL = {resolved, refunded, rejected, cancelled}`
(`:51`) · reabrir solo owner desde `{rejected, cancelled}` (`:364-380`) · **`refunded` es final** y
exige `refunded_amount` write-once que sella el KPI net-revenue (`:124-159,353-362`).

**Capacidades (consola REST):** listar `GET /claims` (`claims.py:178-198`) · detalle (`:240-256`) ·
crear (`:201-237`, RBAC owner/manager/operator, `reason` vocabulario CERRADO `:66,101-106`,
`@audit_log`) · PATCH estado/notas (`:315-401`) · resolve (`:404-442`) · reversión del pago Ley 1480
(`:524-621` → RPCs SQL) · notificación WhatsApp outcome al cliente (`:259-312`).
**Bot:** crear (`agentic/tools/claims.py:104-297` — **insert directo a DB, bypassa router**,
patrón declarado intencional `claims.py:14-20`) · consultar por ticket scopeado al cliente
(`:303-374`).

**Drift medido — dos writers divergentes:**
| Eje | API | Bot |
|---|---|---|
| `reason` | vocabulario cerrado | texto libre 3-500 (la DB no tiene CHECK "justamente para no romper la escritura libre del bot" — `claims.py:60-66`) |
| Titularidad | order del tenant | order **+ contact_id** del interlocutor |
| Idempotencia anti-duplicado | ❌ (duplica si se llama ×2) | ✅ (`:163-198`) |
| Audit | `@audit_log` | `messages.claim_audit` + Telegram operador (el API no notifica operador al crear) |
**Drift vivo adicional:** `status_human` del tool usa el set VIEJO `{open, in_progress, resolved,
closed, cancelled}` (`agentic/tools/claims.py:358-364`) — `in_progress`/`closed` ya no existen;
`investigating`/`refunded`/`rejected` caen al fallback crudo. `_VALID_STATUSES` redeclarado a mano
con comentario de riesgo (`:48-52`). Notificación de refund copiada (`refund_notifications.py:14-19`
"Réplica local… SST").

**Falta:** `list_customer_claims(contact_id)` / `get_claim_by_order` para el chat (hoy sin ticket no
hay consulta) · unificación del writer · RMA/devoluciones formales (greenfield).

### 3.9 Compras

**Tablas:** `suppliers` · `purchase_orders` (`po_number` secuencial per-tenant) ·
`purchase_order_items` (`20260413000000:12,29,46`).

**Capacidades (consola REST, owner-only en las 3 capas):** CRUD proveedores (`purchases.py:141-245`)
· CRUD OC (`:246-444`) · recibir `POST /purchases/{id}/receive` (`:446-521`: transición + stock +
WAC `_compute_wac:130-136` + movements — **bucle multi-tabla no atómico**, riesgo documentado
`:490-492`). Lecturas de la página directo Supabase (`purchases/page.tsx:45-112`).
**Bot: nada** (verificado: cero tools de compras/proveedores; los matches de "purchase" en el
orchestrator son el intent de compra del cliente final).

**Falta:** atomicidad de la recepción (RPC transaccional) · exposición de `po_number` como filtro ·
cualquier superficie reusable fuera del router.

### 3.10 Finanzas

**Tablas:** `expenses` (CHECK categorías, columnas de reverso, índice parcial `reversed_at IS NULL`)
· **no existe vista SQL de P&L**.

**Capacidades:** registrar gasto `POST /expenses` (`expenses.py:39`) · anular con reverso auditado
(`:69-124`). **Sin `GET /expenses` ni `GET /finance/pnl`** — el P&L (ingreso − COGS − OPEX) se
calcula **en el frontend TS** (`finance/lib/pnl.ts:87-135` sobre lecturas RLS con **cap PostgREST
1000 filas** y solo flag `truncated` — potencialmente incorrecto a escala, el comentario
`page.tsx:12-14` ya pide un RPC). Ingreso reconocido parcialmente vía `insights.py:517` +
`metrics_orders_summary`; net-revenue home vía `rpc_dashboard_revenue`.
**Bot: nada** (verificado por greps e inventario de tools).

**Drift medido:** `PAID_ORDER_STATUSES` ×4 (`pnl.ts:20` · `insights.py:62` · SQL
`20260704154000:117` · SQL `20260712020000:55`) · categorías de gasto en 3 lugares no sincronizados
(CHECK DB · `pnl.ts:29-35` · el router NO valida `:29`) · `sic_report.py` NO es financiero (es
Habeas Data).

**Falta:** todo el contrato de lectura financiera (`finance.get_pnl` greenfield, idealmente con RPC
`pnl_summary` exacto) · módulo `finance` en insights · dueño único de los enums.

### 3.11 Analítica

**Tablas/RPCs:** `audit_log` · `pii_access_log` · `ai_insights` (cache) · `agentic_shadow_log` ·
RPCs `metrics_orders_summary` (`20260704154000:76-122`) · `metrics_orders_timeseries`
(`20260704156300:30-85`, **capacidad dormida sin consumidor**) · `rpc_dashboard_revenue`
(`20260712020000:36-88`) · vista `vw_consent_events_unified`. **No hay vistas SQL de KPIs.**

**Capacidades:** KPIs de período (server component directo Supabase ×10 queries + RPC,
`metrics/page.tsx:81-131`) · insights IA `POST/GET /insights` (`insights.py:517,599`) · stats inbox
`GET /conversations/stats` (`conversations.py:165-210`) · auditoría (lectura directa
`audit/page.tsx:119-147` + export CSV owner) · reporte SIC (`sic_report.py:198`).
**Bot: nada — la analítica NO es conversable** (M5 la quiere para el owner: "¿cómo van mis ventas
esta semana?"; hoy las 20 tools son customer-facing y ninguna distingue rol de interlocutor).

**Drift medido:** "ingreso reconocido" definido en **5 implementaciones** (TS + Python + 3 SQL) ·
ventana hora Colombia ×3 (`date-window.ts` · `insights.py:80-89` "espejo exacto" · SQL
`America/Bogota`) · fallback de agregación client-side implementado dos veces (TS `metrics.ts:113`
≡ Python `insights.py:142-148`). La duplicación web↔API ya ocurrió una vez (G20) — evidencia
empírica del costo de no tener la capa de dominio.

**Reusable para el domain service de analítica:** los 3 RPCs (con el fix de contexto tenant H5) ·
`_fetch_module_data` (`insights.py:169-350`, de-facto el borrador del DTO) · patrón de auditoría
central (`write_audit_event` + `@audit_log` + `log_pii_access`).

---

## 4. Backlog exacto de la capa de servicios (salida declarada de M1)

Ordenado por (1) pilotos M2, (2) riesgo de drift activo, (3) desbloqueo de M3-M5. Cada ítem indica
de dónde se extrae y qué hueco nuevo hay que construir.

| # | Domain service | Extraer de | Construir nuevo | Drift que mata |
|---|---|---|---|---|
| 1 | **OrdersService** (piloto) | `orders.py:143-752` (create/patch/link) + `order_cancellation.py` (pipeline) + 3 reads del bot | `GET /orders/` listado · `orders.list_by_contact` · cancelación unificada para consola | 2 pipelines de cancelación · reuso/TTL de link ×2 — **M2.0+M2.1 ✅ (create/get/list/list_by_contact + FSM + `GET /orders/` + consola sobre REST) · M2.2 ✅ 2026-08-25: cancelación unificada con paridad de outcome certificada (11 escenarios) + consola con pipeline legal completo (void/guía/audit/restock) vía PATCH; resta M2.3 (link)** |
| 2 | **ClaimsService** (piloto) | `claims.py` (CRUD+reversión+FSM) + `agentic/tools/claims.py` (dedup, titularidad) | `list_by_contact` / `get_by_order` · reason unificado · enums compartidos | 2 writers divergentes · vocabulario extinto en bot |
| 3 | **InventoryService** | `lib/stock_reservation.py` + RPCs (ya SoT) | `POST /stock/adjustments` atómico con ledger (deuda declarada `page.tsx:487-489`) · disponible neto de primera clase · receive compras atómico | restock ×3 · escrituras fuera de RPC ×3 · bruto vs neto |
| 4 | **CatalogService** | `catalog_contract.py` + `catalog.py` + `catalog_tool.py` (read) | shape canónico único + label único + consumidores reales de `/catalog` | shape ×2 · label ×2 · fallback ×3 · validación ×2 |
| 5 | **ShippingService** | `legacy_adapters/aveonline.py` (semántica completa) + `aveonline_client.py` ×2 → 1 | una semántica de cotización (COD+filtros para ambos canales) · cancelar guía en consola · mapping de estados único | cliente ×2 · cotización 2 semánticas · espejos ×N |
| 6 | **CouponsService** | `api/lib/coupons.py` (ya es el servicio) → paquete compartido | `validate_coupon` expuesto · GET cupones · filtro anunciable compartido | sys.path hack · validación input ×2 |
| 7 | **ContactsService** | `contacts.py` + máquina de consent del API | GET contactos · consent unificado (1 máquina) · entidad `data_subject_requests` | 4 máquinas de consent |
| 8 | **ReceiptsService** | `rpc_issue_receipt` (SoT SQL) + crons de entrega | REST comprobantes · emisión/reenvío bajo demanda · consulta conversable | formato ×3 · servicio disfrazado de cron |
| 9 | **PurchasesService** | `purchases.py` | receive atómico (RPC) · filtro por `po_number` | no-atomicidad receive |
| 10 | **FinanceService** | `pnl.ts` (reglas hoy en TS) + `expenses.py` | `finance.get_pnl` + RPC `pnl_summary` exacto · enums únicos (`PAID_ORDER_STATUSES`, categorías) | definición ×4-5 · P&L con cap 1000 |
| 11 | **AnalyticsService** (M5) | RPCs métricas + `_fetch_module_data` | contexto tenant explícito (GUC) · primera audiencia owner-facing del bot | ingreso reconocido ×5 · ventana ×3 |

**Decisiones de modelo de datos que el backlog arrastra (no son bloqueo de M2, sí de M3-M5):**
entidad `data_subject_requests` · separación `shipping_quotes`/`shipments` · destino de
`rma_requests` (revivir como capacidad o dropear formalmente) · unificación de los dos historiales
de tracking.

**Código muerto a retirar cuando el bloque bot adopte los servicios** (verificado sin callers de
producción): `tools/known_customer_tool.py` · tracking de `tools/order_status_tool.py` ·
`handle_shipping_quote_if_applicable` / `requote_shipping_for_cart` en `tools/shipping_quote_tool.py`.

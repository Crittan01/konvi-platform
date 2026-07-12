# Contratos Canónicos — Runtime

**Leer cuando**: se toca el Orchestrator, API Gateway, Connector, Worker o cualquier lógica de estados de conversación / pedidos.  
**No leer si**: la tarea es frontend puro, migrations, o UI sin lógica de negocio.

---

## 1) Conversaciones

Estados únicos en runtime y DB:
- `bot_active` — bot responde automáticamente
- `human_takeover` — bot silenciado, agente humano atiende
- `closed` — bot silenciado, no reabre automáticamente
- `opted_out` — cliente revocó consent vía STOP keyword (rev.105 H.4.1); el orchestrator skipea todo inbound. El operador reactiva manual a `bot_active`. Constante `CONVERSATION_STATUS_OPTED_OUT` en `conversation_contract.py` (orchestrator + API).

Aplicado en: `supabase` (constraint), API, Frontend Inbox, Connector/Worker/Orchestrator.  
Sincronización de recencia: trigger DB `trg_sync_conversation_last_interaction` (`messages → conversations.last_interaction_at`).

## 2) Procesamiento de mensajes inbound

`messages.processing_status`: `pending | processing | processed | skipped | failed | ack_pending`
- `ack_pending` (rev. 67): mensaje outbound enviado a Meta, pero el UPDATE de `meta_message_id` en DB falló los 3 retries.
  Requiere reconciliación manual; la cola pgmq YA hizo ACK (no se reintenta a Meta para evitar duplicados al cliente).

El loop del worker procesa solo `processing_status='pending'`. `processed` es compatibilidad de lectura.  
Al arrancar el worker: sweep de mensajes en `pending`/`processing` > 5 min para recuperar mensajes atascados.

## 3) Human takeover / closed

- `human_takeover`: bot silenciado; escalamiento publica a cola `pgmq` → orchestrator notifica por Telegram.
- `closed`: bot silenciado; no reabre. Solo el agente humano puede reabrir.
- No-texto (imagen/audio/sticker): primera vez → advertencia amable. Si insiste → `human_takeover`.
- "asesor" explícito → `human_takeover` inmediato.

## 4) Outbound humano Inbox → Queue → WhatsApp

`POST /api/v1/conversations/{id}/send` → encola en `whatsapp_outbound_messages` (pgmq).  
Worker consume, envía a Meta con credenciales del tenant, actualiza `messages.processing_status`.  
Retry por visibilidad de cola → `failed` al llegar a `WHATSAPP_OUTBOUND_MAX_ATTEMPTS`.

**Compliance Meta — ventana 24h (rev. 67):**
- El endpoint valida que existe un inbound del cliente en las últimas 24h. Si fuera de ventana → 422 con
  `{code: "WINDOW_EXPIRED", hours_since_last_inbound, last_inbound_at}`. Sin inbound previo → 422
  `{code: "WINDOW_NO_INBOUND"}`. La UI muestra banner amarillo (≤4h restantes) o rojo (expirada).
- Templates aprobados (fuera de scope este cierre): cuando se requiera enviar fuera de ventana, registrar
  plantilla en Meta Business Manager y extender el endpoint para aceptar `template_name`.

**ACK transaccional outbound (B2 rev. 67):**
- Tras Meta entregar y devolver `meta_message_id`, el worker reintenta 3 veces con backoff (100/300/1000 ms)
  el UPDATE de `messages` para registrar la traza. Si los 3 fallan, marca `processing_status='ack_pending'`
  + ACK pgmq igual (NO reenviar a Meta para no duplicar al cliente).

## 5) RBAC runtime

Roles vivos: `owner`, `manager`, `operator`.  
`agent` no existe en runtime (solo en migraciones históricas).

## 6) OAuth Mercado Libre

`state` HMAC firmado + expiración + nonce one-time en DB (`integration_oauth_states`) → anti-replay.  
Callback rechaza state faltante/inválido/expirado/reutilizado.

## 7) Credenciales WhatsApp

Fuente única: `tenant_integrations` por `tenant_id` (`provider='whatsapp'`).  
No hay fallback a `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` en env vars.

### 7.1 Modelo arquitectónico — Model B Direct Provider per-tenant (ADR-0023, rev.110, 2026-06-22)

**CADA tenant tiene SU PROPIA Meta App** (App Secret + Verify Token + WABA +
Phone Number + System User token propios), igual que Wompi/Aveonline/Telegram.
Konvi **NUNCA** es Partner/BSP de Meta. El connector-whatsapp recibe webhooks de
N Meta Apps distintas y las enruta por el path `POST/GET /api/v1/whatsapp/webhook/{tenant_id}`
(el `tenant_id` UUID viene en la URL, es el eje del Model B).

Fuente canónica: `docs/adr/0023-meta-model-b-direct-provider-per-tenant.md`
(supersede la research doc `meta-app-architecture-2026-05-08.md`, que describía el
modelo A "1 Konvi App + N tenants" ya abandonado).

**NO hay env vars globales de credenciales Meta** en el connector. Verificable:
`grep -rn 'META_APP_SECRET\|META_VERIFY_TOKEN' services/connector-whatsapp/` → 0 matches.
Los únicos `os.getenv` del connector son SUPABASE/SENTRY/RENDER.

### 7.2 Schema canónico `tenant_integrations.credentials` (provider='whatsapp')

```jsonc
{
  // Identificadores de la Meta App DEL TENANT
  "app_id": "<Meta App ID del tenant>",       // su propia App
  "phone_number_id": "990364...1295",         // requerido outbound /messages + multiplex inbound
  "waba_id": "215905...8202272",              // requerido templates CRUD (POST /{WABA_ID}/message_templates)
  "display_phone_number": "+57 311 5678910",  // opcional, solo display

  // Secretos del tenant (Vault, resueltos por el connector/orchestrator)
  "app_secret_secret_id": "<vault_uuid>",     // App Secret → HMAC verify per-tenant (Vault)
  "access_token_secret_id": "<vault_uuid>",   // System User token Bearer Graph API (Vault)
  "verify_token": "...",                       // claro en JSONB (no crítico) — handshake GET

  // Ruteo / rol
  "webhook_url_path_segment": "...",           // decorativo; el routing usa el tenant_id UUID del path
  "integration_type": "direct_provider",       // Model B
  "integration_role": "...",

  // Metadata operativa (synced via webhook phone_number_quality_update)
  "tier": "TIER_250",                          // TIER_50|250|1K|10K|100K|UNLIMITED
  "quality_rating": "GREEN"                    // GREEN|YELLOW|RED
}
```

**Notas**:
- El `app_secret` (HMAC) y el `access_token` (outbound) viven en Vault per-tenant
  (`app_secret_secret_id`, `access_token_secret_id`). El `verify_token` (handshake)
  va claro en el JSONB (no es crítico).
- El tenant genera estas credenciales en SU `developers.facebook.com` /
  `business.facebook.com` (su propia Meta App + System User sobre SU WABA).
- Campos reales consumidos por el connector: ver docstring de
  `services/connector-whatsapp/dependencies/meta.py:20-30`.

### 7.3 HMAC verification per-tenant + invariante cross-tenant (rev.110, ADR-0023)

`services/connector-whatsapp/dependencies/meta.py` (`verify_meta_signature_for_tenant`):

1. `tenant_id` viene del URL path (`/webhook/{tenant_id}`). Lee raw_body + header
   `X-Hub-Signature-256: sha256=<hex>`.
2. Resuelve el `app_secret` **per-tenant** desde Vault (cache 300s + single-flight
   anti-stampede) y valida HMAC SHA-256 constant-time contra ESE secret. Falla → 403.
   No existe secret global.
3. **Invariante cross-tenant (defense-in-depth, SÍ bloquea):** tras HMAC OK, extrae
   `phone_number_id` del payload y resuelve su `tenant_id`. Si difiere del `tenant_id`
   del path → métrica `hmac_fail_cross_tenant_invariant` + **403** (no es solo forensics).
4. Tres caches TTL 300s (phone_number_id→tenant_id, tenant_id→app_secret,
   tenant_id→verify_token) con caching negativo + single-flight lock, más métricas
   in-memory expuestas en `GET /health/metrics`.

El handshake GET `/webhook/{tenant_id}` compara `hub.verify_token` contra el
`verify_token` de ESE tenant (`credentials.verify_token`).

Razón de NO usar F.1 webhook framework: `connector-whatsapp` es deploy unit
independiente Render (`rootDir: services/connector-whatsapp`) — no puede importar
de `services/api/lib/` (`meta.py:41-42`). F.1 sigue siendo canónico para webhooks
dentro de `services/api/`.

## 8) Seguridad multi-tenant (service_role) — ADR-0025

`service_role` bypasea RLS → el aislamiento depende de filtros explícitos `tenant_id` en cada query.  
Estrategia canónica (ADR-0025), tres capas:
- **Lint AST estático** `scripts/audit_tenant_filter.py` — enforce el patrón `.table(X).eq("tenant_id", tid)` en queries multi-tenant (baseline 0 gaps, ratchet en CI). Excepciones se taggean `# tenant_filter:exempt:<razón>`.
- **RLS + GUC**: `app_current_tenant()` = COALESCE(GUC `app.current_tenant_id`, JWT `app_metadata.tenant_id`).
- **Vault ownership**: los secretos se leen scoped al tenant dueño.

El helper `scoped_table(...)` y `services/api/dependencies/tenant_scope.py` fueron **ELIMINADOS** (0 adopción, 2 meses post-rev.58). El patrón vigente es el `.eq("tenant_id", tid)` explícito verificado por el lint.

## 9) Shipping Aveonline (CO) — ADR-0019

Provider activo **único** = `aveonline` (Envia fue **ELIMINADO** del runtime en rev.109, 2026-05-30; sus endpoints label/tracking/pickup/cancel se borraron con él). Default resuelto en `services/api/routers/shipping.py` (`_get_active_shipping_provider`).

- DANE: acepta 5 u 8 dígitos, normaliza a 8 para cotizar (`11001 → 11001000`).
- `shipping/quote` retorna `highlights.cheapest` y `highlights.fastest` (determinístico, sin LLM).
- Aveonline maneja eventos de estado post-venta vía webhook (`routers/aveonline_webhook.py`) — ver ADR-0038 (F-6/F-7) + guard monotónico `shipments.status_occurred_at`.
- Generación de guía real gateada per-tenant por `real_guides_enabled` (default false).

## 10) Tiering runtime (Basic / Pro / Enterprise)

Planes en DB: `billing_plans`, `plan_capabilities`, `tenant_subscriptions`.  
Enforcement backend: RPC `consume_tenant_capability(...)` en endpoints críticos.  
Snapshot por tenant: `GET /api/v1/settings/plan-capabilities`.  
Existentes bootstrappeados a `enterprise` para no cortar operación.

## 11) Observabilidad + Rate Limiting distribuido

- `api_security_events`: registra `rate_limit.exceeded`, `idempotency.*`.
- Rate limiter distribuido: tabla `rate_limit_windows` + RPC `rate_limit_hit()` (PostgreSQL, cross-réplica).  
  Fallback automático a in-memory si RPC falla.
- Cleanup periódico: `cleanup_expired_idempotency_keys()` + `cleanup_expired_rate_limit_windows()` desde worker.

## 12) Inbox Fase C — Pagos Wompi

- `payment_link_tool`: detecta `order_acknowledgment` + `total_in_cents` válido → crea orden `pending_payment` → genera link Wompi.
- `total_in_cents` validado contra `_build_verified_order_context()` (catalog DB + historial, tolerancia 5%).
- Webhook `POST /api/v1/webhooks/wompi`: valida firma SHA256, correlaciona `payment_link_id → payments → order_id`.
- APPROVED → `order.status = confirmed`, decrementa stock, notifica cliente.
- Idempotente: si orden ya `confirmed`, skip.
- TTL 30 min en Wompi; worker cancela `pending_payment` expirados a los 35 min (`PENDING_PAYMENT_TTL_MINUTES`).

## 13) FSM Conversacional — estados

**Hay DOS FSM coexistiendo** (no confundir):

**(A) FSM AGENTIC canónico — path PRIMARIO** (`services/ai-orchestrator/agentic/state_machine/states.py`, enum `AgenticState`, 9 estados, desde rev.109/111). Es el que corre para tenants con `agentic_enabled=true` (todos los nuevos, KAIU incluido). Persiste en `conversations.agentic_state` (migración `20260604000000`):

```
GREETING            ← saludo inicial / re-engage tras inactividad
EXPLORING           ← cliente navega categorías, aún 0 items
CART_BUILDING       ← cart con ≥1 item, sin checkout iniciado
PII_COLLECTION      ← recolección de datos de contacto (checkout)
SHIPPING_QUOTE      ← cotización de envío
CARRIER_SELECTION   ← selección de transportadora
PAYMENT             ← método pago / link Wompi / COD pendiente
POST_PAYMENT        ← orden creada, esperando confirmación final / tracking
HUMAN_HANDOFF       ← escalado a operador (accesible desde cualquier estado)
```
Resolver puro determinístico en `agentic/state_machine/resolver.py`; matriz de transiciones en `transitions.py`.

**(B) FSM transaccional LEGACY** (`services/ai-orchestrator/fsm/states.py`) — aún vivo para el resolver de checkout (dirección/PII). Sus estados:

```
CATALOG_MODE                   ← consulta, sin intención de compra
NEEDS_SHIPPING_CITY            ← buying_intent=true, no cotizado
AWAITING_CARRIER_SELECTION     ← cotizado, carrier no elegido
NEEDS_CONSENT                  ← carrier elegido, sin consent
NEEDS_EMAIL                    ← consent=true, sin email
NEEDS_NAME                     ← email en DB, sin nombre
NEEDS_DIRECTION                ← nombre en DB, sin dirección
READY_FOR_SUMMARY              ← todos los datos → resumen determinístico
AWAITING_ORDER_CONFIRMATION    ← usuario confirmó resumen → crear pedido
```

Datos personales: SOLO se piden después de cotización aprobada (carrier seleccionado explícitamente).  
Carrier selection: detecta inbound corto (≤8 tokens), sin pregunta, DESPUÉS del outbound con "continuamos".  
Resumen: usa `_build_verified_order_context()` — precios desde catalog DB, envío desde historial. El LLM NO calcula.

## 16) Coherencia core del bot conversacional (rev. 68)

### Datos del cliente para checkout

| Dato | Origen | Destino |
|---|---|---|
| `name` | `contacts.name` | Wompi `customer_data.full_name` |
| `email` | `contacts.email` | Wompi `customer_data.email` |
| `phone` | `contacts.phone` | Wompi `customer_data.phone_number_prefix` + `phone_number` (+57 separado) |
| `document_type + document_number` | `contacts.document_type` + `contacts.document_number` | Wompi `customer_data.legal_id_type + legal_id` |
| `address.neighborhood` | `contacts.address.neighborhood` | Envia `destination.district` |

Reglas oficiales:
- `legal_id_type` Colombia: solo `CC, CE, NIT, PP, TI, OTHER`. NO `DNI` (Argentina/España) ni `RG` (Brasil).
- `legal_id` y `legal_id_type` van **juntos o ninguno** (regla Wompi).
- Phone Wompi: prefijo separado en `phone_number_prefix` (`+57`) y dígitos en `phone_number`.
- Si algún campo es null, NO se incluye en el payload (Wompi rechaza nulls explícitos).

### FSM rev. 68 — orden aterrizado a la realidad

```
CATALOG_MODE
  ↓ (cliente expresa intención de compra)
PRODUCT_CONFIRMED + opcional carrito multi-producto
  ↓
NEEDS_SHIPPING_CITY (incluye instrucción al LLM: resumir carrito ANTES de pedir ciudad + ofrecer agregar más productos)
  ↓
AWAITING_CARRIER_SELECTION
  ↓
NEEDS_CONSENT  (autorización ANTES de pedir datos)
  ↓
NEEDS_EMAIL
  ↓
NEEDS_NAME
  ↓
NEEDS_DOCUMENT  ← rev. 68: tipo + número (Wompi customer_data)
  ↓
NEEDS_DIRECTION  (estructurada con building_type + neighborhood)
  ↓
READY_FOR_SUMMARY
  ↓
AWAITING_ORDER_CONFIRMATION → handle_payment_link_if_applicable (Wompi con customer_data completo)
```

### Schema canónico `contacts.address` JSONB

```json
{
  "street": "Calle 10 # 5-23",         // requerido
  "number": "401",                     // opcional
  "neighborhood": "Chapinero",         // requerido (Envia district)
  "city": "Bogotá",                    // requerido
  "state": "DC",                       // requerido (código corto)
  "dane_code": "11001000",             // requerido (DANE 8 dígitos)
  "country": "CO",                     // default "CO"
  "building_type": "edificio",         // "casa" | "edificio" | "conjunto"
  "tower": "Torre 3",                  // opcional, solo conjunto
  "apartment": "401",                  // opcional, edificio o conjunto
  "complex_name": "Torres del Parque", // opcional
  "reference": "Frente al parque"      // opcional
}
```

Campos requeridos según `building_type`:
- `casa` → street, neighborhood, city, state, dane_code
- `edificio` → + apartment
- `conjunto` → + tower, apartment

Validación: `dependencies/contact_validators.py.is_address_complete(addr)`.

### Knowledge Base — 6 categorías canónicas (rev. 68)

`kb_documents.category` CHECK: `faq, negocio, politicas, productos, envios, pagos`.

| Categoría | SÍ | NO |
|---|---|---|
| **FAQ** | Preguntas frecuentes con respuestas cortas | Misión, descripción de productos |
| **Negocio** | Historia, equipo, hitos, alianzas | Misión/visión/valores (van en Filosofía) |
| **Políticas** | Devoluciones, cambios, garantía, RMA | Métodos de pago, tarifas envío |
| **Productos** | Guía de uso, talla, cuidado | Precio, stock, descripción de catálogo |
| **Envíos** | Tarifas/zonas/tiempos, restricciones | Política de devolución |
| **Pagos** | Métodos aceptados, financiamiento | Datos del banco (sensible) |

RAG: embeddings `gemini-embedding-2` (3072 dim; `gemini-embedding-001` fue RETIRADO por Google, F-doc Fase 6, y su fallback histórico `text-embedding-004` también se apagó ene-2026), búsqueda semántica pgvector top-3, `match_threshold=0.5` (`tools/kb_tool.py:169`). Sin filtro por categoría — el RAG busca en todo el KB del tenant por significado.

### Identidad del negocio vs Comportamiento del agente (rev. 67)

Ortogonal — dos campos NO confundir:

| Concepto | Dónde vive | Qué describe | UI |
|---|---|---|---|
| **Identidad del negocio** | `tenants.mision/vision/valores/tono_comunicacion` | Qué hace tu negocio, por qué existe, cómo se expresa. Inyecta automáticamente al system prompt en bloque "SOBRE LA TIENDA". | Configuración → General → Filosofía del negocio |
| **Comportamiento del agente** | `ai_agents.role_description` | Cómo responde el bot: qué ofrece primero, cómo cierra, qué pregunta extra hace. Inyecta como bloque "COMPORTAMIENTO DEL AGENTE" del system prompt. | IA y Conocimiento → Agentes IA |

Reglas:
- Si `tenants.mision` está poblada y `ai_agents.role_description` no, el default sintetiza:
  `"Asistente comercial de {tenant_name}, alineado a su misión y valores"`.
- Ambos textos coexisten en el system prompt sin redundancia: misión/visión/valores van como datos de contexto;
  role_description va como instrucción de comportamiento.

## 15) Inbox runtime (rev. 67)

**Frontend:**
- Realtime con fallback polling 5s (cae si socket muere).
- INSERT en `messages` aplica optimistic update sobre `conversations.last_interaction_at` para
  alinear timestamp lateral y chat al instante (sin esperar trigger DB).
- Dedupe por `id` en INSERT realtime + polling fallback.
- Badge unread por conversación basado en `conversation_reads (tenant_id, user_id, conversation_id, last_read_at)`.
- Tooltips en badges de estado (Bot / Agente / Cerradas) con explicación + transiciones.
- Banner ventana 24h: amarillo si <4h restantes, rojo si expirada.
- Scroll histórico cursor-based: carga +50 mensajes al llegar al top.
- Toggle "Ver archivadas" en lista lateral (default oculta `conversations.archived_at IS NOT NULL`).

**Multimodal audio (D rev. 67):**
- Feature flag `MULTIMODAL_AUDIO_ENABLED` (default `true`). Apagable en caliente.
- Flujo: connector persiste `media_id` + `media_mime` → orchestrator descarga via `services/meta_media.py`
  → envía inline al modelo Gemini multimodal (`MULTIMODAL_MODEL`, default `gemini-3.5-flash`) → recibe transcripción.
- La transcripción reemplaza `content` y `content_type='text'`; el flow normal del FSM continúa con ese texto.
- Mimes soportados: `audio/ogg`, `audio/mp3`, `audio/mpeg`, `audio/wav`, `audio/aiff`, `audio/aac`, `audio/flac`.
- Tamaño máx: `META_MEDIA_MAX_BYTES` (default 16 MB).
- Si descarga/transcripción falla, cae al gate humanizado actual ("solo manejo texto").
- Imagen y otros media: NO procesados (futuro F8).

**Migraciones rev. 67 (4 nuevas, total 66):**
- `20260428000000_conversation_reads.sql` — tabla de marcas de lectura por usuario.
- `20260428000001_messages_ack_pending_status.sql` — agrega `ack_pending` al CHECK constraint.
- `20260428000002_messages_media_id.sql` — columnas `media_id` + `media_mime`.
- `20260428000003_archive_orphan_conversations.sql` — `archived_at` + index parcial + backfill 90 días.

## 16) Coherencia core del system prompt (rev. 71)

**Fuentes que consume el bot por mensaje** (orden de inyección al system prompt):

1. **Identidad y comportamiento**: `ai_agents.name` + `ai_agents.role_description`. Default DB `'Vendedor Oficial'` (alineado con readiness check).
2. **Tono**: `tenants.tono_comunicacion` → bloque pre-definido en `_TONO_INSTRUCCIONES` (5 estilos).
3. **Cliente conocido**: `_load_customer_context_block` (lazy mode rev. 69) — pedidos activos + reclamos abiertos + saludo por primer nombre si `consent_given=true`.
4. **Carrito previo cancelado**: `_load_cart_recovery_block` (rev. 70) si trigger lazy + última `orders.status='cancelled'` <`CART_RECOVERY_LOOKBACK_DAYS`.
5. **SOBRE LA TIENDA** (`_build_store_info_section` rev. 71):
   - Modo de operación explícito: presencial / virtual / mixta (línea fija al inicio).
   - Sedes con `is_primary` rotulada y ordenada primero.
   - Horario derivado de `tenants.support_schedule` jsonb vía `_format_support_schedule_text` (ISO 1-7).
   - Misión / visión / valores.
   - Identidad legal: `nit`, `email_contacto`, `telefono_contacto` bajo guard "úsalos SOLO si el cliente lo pregunta".
6. **CONTEXTO TEMPORAL** (rev. 71): si `_is_outside_support_hours(support_schedule)=true`, instrucción de seguir atendiendo PERO no decir "te conecto ahora" — registrar solicitud y prometer respuesta del próximo turno. `after_hours_message` como referencia de tono (no copy literal).
7. **Catálogo**: condicional por FSM state.
8. **KB pre-RAG** (rev. 71):
   - RAG semántico (pgvector top-3, threshold 0.5).
   - Boost determinístico: regex léxico detecta categorías triggered (`pagos|envios|politicas|productos|negocio|garantia`).
   - Si triggered y RAG no la rankeó → `_fetch_top_doc_by_category` agrega top-1.
   - Si triggered y categoría VACÍA → `_missing_category_marker` (con `⚠️`) instruye "NO INVENTES — escala con cordialidad".
9. **CONTEXTO VERIFICADO**: `_build_verified_order_context` en READY_FOR_SUMMARY (totales desde catálogo DB).

**KB categorías canónicas:** `faq, negocio, politicas, productos, envios, pagos`. Plurales canónicos rev. 71.

**`bot_source_log` (rev. 71, IH pendiente)** — append-only por interacción. Flags `injected_*`, `kb_categories_used[]`, `kb_missing_categories[]`, `fsm_state`, `intent_detected`, `prompt_chars`. TTL 30d, RLS por tenant. Sin PII.

**Readiness checks Tenant Console (10, rev. 71):**
1. Identidad del negocio · 2. Tono · 3. Sedes y horario · 4. Catálogo · 5. KB activo · 6. Indexación · 7. Agente IA · 8. **Identidad legal NIT/email/tel** (NUEVO) · 9. **KB cobertura crítica politicas/envios/pagos** (NUEVO) · 10. Pasarela y courier.

**Columnas legacy deprecadas (rev. 71, DROP pendiente IH `20260501000000`):**
- `tenants.business_hours` (TEXT) → reemplazada por derivación de `support_schedule`.
- `tenants.cutoff_message` (TEXT) — orphan. Migra a KB envios.
- `tenants.dispatch_lead_time` (TEXT) — orphan. ETA viene de carrier.

## 17) Routers nuevos y audit_log decorator (rev. 72)

**Cierre arquitectural Front↔API↔DB.** Se agregaron 3 routers que antes
eran bypass desde Server Actions de Next.js a Supabase directo, y un decorator
de audit que populaba la tabla `audit_log` (vacía hasta rev. 71).

### Endpoints nuevos

**`/api/v1/claims`** — `services/api/routers/claims.py`
- `GET /` (filters: status, customer_id, order_id) · `POST /` · `GET /{id}` · `PATCH /{id}` · `POST /{id}/resolve`
- Estados: `open|in_progress|resolved|closed|cancelled`
- RBAC: read=all, write=owner+manager.
- Coexiste con orchestrator que también inserta claims via service_role.

**`/api/v1/purchases`** — `services/api/routers/purchases.py`
- `GET /suppliers` · `POST /suppliers`
- `GET /` · `POST /` · `GET /{id}` · `POST /{id}/cancel` · `POST /{id}/receive`
- Estados PO: `ordered → received | cancelled`
- WAC determinístico al recibir: `((max(0,old_stock)*old_cost) + (po_qty*po_cost)) / (max(0,old_stock) + po_qty)`
- Idempotente: el UPDATE 'ordered'→'received' filtra por status para evitar doble recibo.

**`/api/v1/knowledge-base`** — `services/api/routers/knowledge_base.py`
- `GET /` (filters: category, is_active) · `POST /` · `GET /{id}` · `PATCH /{id}` · `DELETE /{id}` · `POST /{id}/reindex`
- Embedding server-side via `dependencies/embeddings.py` (Gemini 3072-dim, fallback a `text-embedding-004`).
- Cap por tenant: 30 docs.
- `GEMINI_API_KEY` requerida en el API service (movida desde el web service).
- Si embedding falla, doc se persiste con `embedding=NULL` y banner UI muestra "indexing pending"; reintento con `/{id}/reindex`.

### `@audit_log` decorator — `services/api/dependencies/audit.py`

Patrón:
```python
@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="order", action="created")
async def create_order(
    order: OrderCreate,
    request: Request,                                 # requerido para extraer JWT
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    ...
):
    ...
```

- Se ejecuta DESPUÉS del handler (no antes). Si el handler lanza excepción, NO se audita.
- Si el insert al `audit_log` falla, el handler retorna OK (fire-and-forget con log warning).
- `entity_id` se extrae en este orden: path params `*_id` (excluye `tenant_id`/`user_id`) → `result.id` → `result['id']` → None.
- `payload`: snapshot del result (Pydantic `.model_dump(mode='json')` o dict simple).
- Aplicado a: orders (3), contacts (4), products (3) + variations (3), claims (3), purchases (5), knowledge_base (4), settings (3), team_member (2), integrations (3) = 17+ endpoints.

Acciones canónicas: `created, updated, deleted, status_changed, role_changed, connected, disconnected, payment_link_created, consent_recorded`.

Entity types canónicos: `order, contact, product, variation, claim, purchase_order, supplier, kb_doc, settings, integration, team_member`.

### Política rev. 72: las migraciones SQL NO son fuente de verdad

Ver `.context/05-doc-policy.md`. La fuente operacional es DB live + código vivo + `.context/07-schema-canonical.md` (regenerable). Tests `tests/test_coherence_pact.py` validan paridad Pydantic↔DB.

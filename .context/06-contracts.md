# Contratos Canónicos — Runtime

**Leer cuando**: se toca el Orchestrator, API Gateway, Connector, Worker o cualquier lógica de estados de conversación / pedidos.  
**No leer si**: la tarea es frontend puro, migrations, o UI sin lógica de negocio.

---

## 1) Conversaciones

Estados únicos en runtime y DB:
- `bot_active` — bot responde automáticamente
- `human_takeover` — bot silenciado, agente humano atiende
- `closed` — bot silenciado, no reabre automáticamente

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

## 8) Seguridad multi-tenant (service_role)

`service_role` bypasea RLS → el aislamiento depende de filtros explícitos `tenant_id` en cada query.  
Helper: `scoped_table(supabase, table, tenant_id)` en `services/api/dependencies/tenant_scope.py`.

## 9) Shipping Envia (CO)

- DANE: acepta 5 u 8 dígitos, normaliza a 8 para cotizar (`11001 → 11001000`).
- Payload Envia: `city = dane_8digit`, `postalCode = dane_8digit`.
- `shipping/quote` retorna `highlights.cheapest` y `highlights.fastest` (determinístico, sin LLM).
- Envia Fase 2 (label/tracking/pickup/cancel) bajo feature flag `ENVIA_PHASE2_ENABLED=true` (default false).

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

RAG: embeddings `gemini-embedding-001` (3072 dim), búsqueda semántica top-3, threshold 0.4. Sin filtro por categoría — el RAG busca en todo el KB del tenant por significado.

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
  → envía inline al modelo Gemini (`gemini-2.5-flash`, multimodal nativo) → recibe transcripción.
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

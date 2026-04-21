# Current Scope — Estado Real de Implementación

**Última actualización**: 2026-04-21 (rev. 46)
**Fuente de verdad**: código en el repo (`develop`) + migraciones en `supabase/migrations/`.
**Tree funcional vigente**: `.context/00-product.md`.

---

## Estado Ejecutivo

- **Tenant Console**: ✅ Live (fases 1–11.5 completas)
- **Platform Console**: ❌ fuera de alcance (bloqueante OQ-P01)
- **Backend**: ✅ API + Connector WhatsApp + AI Orchestrator operativos
- **DB**: ✅ contrato endurecido (42 migraciones)

---

## Cierre de auditoría doc/código (2026-04-21)

- Se eliminó exposición hardcodeada de `SUPABASE_SERVICE_ROLE_KEY` en `scripts/test-mass-import.mjs` (ahora solo por env).
- Se sanitizó el remote git local para remover token embebido de URL (`origin` queda en `https://github.com/...`).
- Inbox frontend quedó alineado a proxy server-side para cambios de estado/envío:
  - `/api/conversations/{id}/status`
  - `/api/conversations/{id}/send`
- Se unificó prioridad de `API_URL` sobre `NEXT_PUBLIC_API_URL` en server code de catálogo/marketplace.
- Se normalizó arquitectura documental de `packages/`:
  - `shared-types` y `config` activos mínimos
  - `observability` preparado con contrato mínimo
  - `ui` y `test-utils` deferred explícitos
  - `db` marcado snapshot legacy no canónico
- Se congeló contrato de entorno:
  - `.env.example` alineado con variables realmente consumidas por código fuente
  - `render.yaml` alineado con límites API explícitos (`API_RATE_LIMIT_*`)
  - docs de deployment/handoff alineados (requeridas, opcionales y local-only)
- Se formalizó gate de decisión Free -> Pago:
  - scorecard operativa con triggers, bloqueadores, ventana de evidencia y criterios GO/NO-GO
  - documento: `docs/deployment/production-readiness-gate.md`
  - snapshot operativo 2026-04-21 registrado con resultado actual `NO-GO`
- Se formalizó criterio funcional previo a pagos/infra pago en Inbox:
  - matriz de intents y certificación por fases A/B/C en `docs/operations/inbox-intents-matrix.md`
  - preparación documental Wompi (sandbox/prod, llaves/eventos) en `docs/integrations/wompi-prep.md`
- Fase A Inbox (variantes) avanzó en runtime:
  - `catalog_tool` ahora inyecta rango de precio, stock total y desglose de variantes al contexto LLM
  - `orchestrator` muestra variantes explícitas en prompt
  - `orchestrator` agrega análisis determinístico de coincidencia exacta por variante (color/talla/SKU) para reforzar respuesta o escalar sin inventar
  - follow-ups ambiguos (ej. "y en talla L?") ahora usan memoria determinística de corto plazo basada en historial conversacional para detectar producto en contexto
  - cobertura de regresión añadida en tests (`test_catalog_tool_variants`, `test_orchestrator_catalog_prompt`)
- Connector WhatsApp ahora preserva contexto webhook inbound en `messages.payload`:
  - `context.id/from`
  - metadata de respuestas interactivas (`button_reply`, `list_reply`, `button`)
  - parseo de lotes webhook (`entry/changes/messages`) para no perder mensajes cuando llegan múltiples en un mismo POST
  - migración aplicada en linked: `20260421130000_messages_payload_context.sql`
- Se agregó fallback de certificación técnica para entorno Free (sin depender de UI Render):
  - script: `scripts/uat/fase_a_free_fallback.sh`
  - resultado de ejecución en sesión: `PASSED=5`, `FAILED=0` (aprobado técnico)
- Se resolvió bloqueo de `next build` en VM/local:
  - causa: dependencia de `next/font/google` en build sin salida de red estable
  - fix: retirar `next/font/google` en `app/layout.tsx` y definir fallback tipográfico local (`--font-inter`) en `globals.css`

---

## Contratos Canónicos (runtime)

### 1) Conversaciones

Contrato único en runtime y DB:
- `bot_active`
- `human_takeover`
- `closed`

Aplicado en:
- `supabase` (normalización + constraint)
- API (`services/api/routers/conversations.py`)
- Frontend Inbox (`apps/web/app/dashboard/inbox/page.tsx`)
- Connector/Worker/Orchestrator

### 2) Procesamiento de mensajes inbound

`messages` ahora usa outcome explícito:
- `processing_status`: `pending | processed | skipped | failed`
- `skip_reason`
- `last_error`
- `processing_attempts`

`processed` se mantiene por compatibilidad, pero el loop usa `processing_status='pending'`.

### 3) Human takeover / closed

Comportamiento efectivo:
- Si conversación está en `human_takeover`: el bot no responde.
- Si conversación está en `closed`: el bot no responde y no reabre automáticamente.
- Mensajes no-texto: no respuesta automática, se escalan a `human_takeover` y quedan visibles en Inbox.
- Escalamiento a `human_takeover` ahora publica evento a cola durable Supabase Queues (`pgmq`) vía trigger DB sobre `conversations`.
- AI Orchestrator consume la cola y despacha notificaciones por tenant:
  - `telegram` activo
  - `email` preparado (placeholder no bloqueante hasta SMTP productivo)

### 4) Outbound humano Inbox -> Queue -> WhatsApp

Comportamiento efectivo:
- `POST /api/v1/conversations/{id}/send` ya no llama Meta directo; encola evento durable (`pgmq`) para envío async.
- El endpoint persiste primero el outbound en `messages` (`processing_status='pending'`) y luego encola payload con `tenant_id`.
- El AI Orchestrator consume `whatsapp_outbound_messages`, envía a Meta y actualiza `messages`:
  - éxito -> `processing_status='processed'`, `processed=true`, `meta_message_id`
  - fallo transitorio -> retry por visibilidad de cola (`vt`)
  - fallo definitivo -> `processing_status='failed'` al llegar a `WHATSAPP_OUTBOUND_MAX_ATTEMPTS`

### 5) RBAC runtime

Roles vivos en runtime:
- `owner`
- `manager`
- `operator`

`agent` no existe en runtime; queda únicamente en migraciones históricas.

### 6) OAuth Mercado Libre

`state` OAuth endurecido:
- firmado (HMAC)
- con expiración
- nonce one-time persistido en DB (anti-replay)
- callback rechaza `state` faltante/inválido/expirado/reutilizado antes de persistir tokens
- `/integrations/meli/auth-url` responde `503` con detalle explícito de env vars faltantes si la app MeLi no quedó configurada completa en API

### 7) Credenciales WhatsApp

Fuente única runtime:
- `tenant_integrations` por `tenant_id`

No hay fallback a `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` en senders (API/Orchestrator).
El connector solo recibe webhooks; no envía mensajes.

### 8) Seguridad multi-tenant (service_role)

El backend usa `service_role` en varios paths, por lo que:
- RLS **no** es barrera suficiente por sí sola en esos paths
- aislamiento runtime depende de filtros explícitos `tenant_id` + RLS donde aplique

Se reforzaron filtros explícitos en paths críticos (`orders`, `shipping`, `marketplace`, `meli_webhook`).

### 9) Shipping Envia (CO) — contrato de dirección endurecido

- En runtime CO, el backend acepta DANE de 5 u 8 dígitos y normaliza a `stat_8digit` para cotizar (ej. `11001 -> 11001000`).
- Para Colombia, payload de Shipping API usa:
  - `city = dane_8digit`
  - `postalCode = dane_8digit`
- Se retiró la prevalidación bloqueante por Queries `city`/`zipcode` en quote (en cuenta actual esos endpoints retornan `404`).
- Para CO, payload de Shipping API mantiene contrato:
  - `city = dane_code` (normalizado a 8 dígitos)
  - `postalCode = dane_code` (normalizado a 8 dígitos)
- Se eliminó campo no documentado `city_to_display` del payload hacia Envia.
- Descubrimiento de carriers prioriza Queries API (`available-carrier`) con fallback operativo si Queries falla.
- `EnviaClient.get_rates()` ahora interpreta como error respuestas `200` con `code/message` sin `data` (evita falsos "sin tarifas").
- Fallas por carrier guardan mensaje robusto (sin strings vacíos) para diagnóstico en `shipping/quote`.
- Fase 2 parcial implementada en API (feature-flagged):
  - `POST /api/v1/shipping/{shipment_id}/label`
  - `POST /api/v1/shipping/tracking`
  - `POST /api/v1/shipping/pickup`
  - `POST /api/v1/shipping/cancel`
  - activación por env var `ENVIA_PHASE2_ENABLED=true` (default `false`)
- `/dashboard/shipping` ahora consume Fase 2 end-to-end desde frontend:
  - proxies Next server-side:
    - `POST /api/shipping/{shipmentId}/label`
    - `POST /api/shipping/tracking`
    - `POST /api/shipping/pickup`
    - `POST /api/shipping/cancel`
  - bloque UI post-cotización con acciones:
    - generar label
    - consultar tracking
    - agendar pickup
    - cancelar envío
  - manejo explícito de feature flag deshabilitado (`503`): guía operativa para activar `ENVIA_PHASE2_ENABLED=true` en API

### 10) Tiering runtime (Basic / Pro / Enterprise)

Comportamiento efectivo:
- Se implementó catálogo canónico de planes y capabilities en DB (`billing_plans`, `plan_capabilities`, `tenant_subscriptions`).
- API Gateway aplica enforcement backend real por capability + cuota con RPC:
  - `orders.create`
  - `shipping.quote`
  - `shipping.confirm_rate`
  - `conversations.send`
  - `integrations.mercadolibre`
- Se expone snapshot operativo por tenant en `GET /api/v1/settings/plan-capabilities`.
- Sidebar refleja bloqueo UX por plan en módulos capability-gated (sin confiar seguridad al frontend).
- Telemetría de uso por tenant/capability:
  - `tenant_usage_counters`
  - `tenant_usage_events`

### 11) Observabilidad API + mantenimiento idempotency

Comportamiento efectivo:
- API registra eventos operativos de hardening en `api_security_events`:
  - `rate_limit.exceeded`
  - `idempotency.replay`
  - `idempotency.payload_mismatch`
  - `idempotency.in_flight_conflict`
  - `idempotency.duplicate_conflict`
- Limpieza de llaves expiradas disponible por dos vías:
  - RPC DB `cleanup_expired_idempotency_keys(...)`
  - endpoint owner-only `POST /api/v1/settings/maintenance/idempotency-cleanup`
- AI Orchestrator ejecuta cleanup periódico automático (configurable por env vars):
  - `IDEMPOTENCY_CLEANUP_ENABLED`
  - `IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS`
  - `IDEMPOTENCY_CLEANUP_BATCH`

---

## Frontend — ajustes estructurales

- `meliBadge` ya no está hardcodeado; se calcula desde `marketplace_listings`.
- Badge MeLi renderiza correctamente también cuando `Mercado Libre` es child item dentro de grupo sidebar.
- Badge MeLi en sidebar ahora muestra conteo numérico (no solo ícono), consistente con Inbox.
- `/dashboard/inventory` legacy quedó como redirección explícita a `/dashboard/catalog`.
- Se eliminaron links operativos residuales que trataban Inventory como módulo standalone.
- Inbox lista conversaciones por `last_interaction_at` y usa `created_at` solo como fallback visual.
- Inbox muestra estado de error explícito si falla la carga del listado de conversaciones.
- Sidebar ahora bloquea módulos dependientes de integración cuando están desconectados:
  - `Inbox` (requiere `whatsapp`)
  - `Cotizador` (requiere `envia`)
  - `Mercado Libre` (requiere `mercadolibre`)
- Se corrigió bug legacy que construía `dane_code` inválido (`+000`) en selector de direcciones.
- `settings.shipping_origin` ahora preserva `dane_code` explícito y mantiene `postal_code`/`dane_code` alineados para Envia.
- `/dashboard/marketplace` ahora distingue explícitamente tres estados:
  - integración desconectada en DB
  - error/timeout cargando publicaciones desde API
  - reconexión requerida cuando DB está conectada pero API no valida sesión MeLi
- `Knowledge Base` reemplaza banner técnico de RAG por copy orientado a operación de negocio.
- UX móvil en `/dashboard/shipping` ajustada para evitar sobreposición visual:
  - KPIs en una columna en mobile (`sm+` mantiene 3 columnas)
  - Selectores geográficos y bloque de paquete apilados en mobile
  - Tarjetas destacadas de tarifas apiladas en mobile
  - Card de tarifa con layout vertical en mobile (precio/metadata sin montarse)
- Flujos críticos UI ahora generan y envían `Idempotency-Key`:
  - Crear pedido (`/api/orders`)
  - Cotizar envío (`/api/shipping/quote`)
  - Confirmar tarifa (`/api/shipping/{id}/rate`)
  - Enviar mensaje humano Inbox (`/api/v1/conversations/{id}/send`)
- Contactos UI amplió captura legal:
  - fuente de consentimiento
  - versión de aviso/política
  - evidencia (nota)
  - motivo de revocatoria
  - visualización de estado revocado y metadata de consentimiento

---

## Migraciones recientes (2026-04-20)

> **Nota:** Ver bloque 2026-04-18 al final para migraciones anteriores del bloque sales.

- `20260420000000_marketplace_listings_meli_fields.sql`
  - Agrega a `marketplace_listings`: `meli_title`, `meli_thumbnail`, `meli_condition`, `meli_category_id`, `meli_attributes`, `synced_at`
  - Habilita sync pull MeLi → Supabase

- `20260420000001_order_tracking.sql`
  - Nueva tabla `order_tracking` con RLS
  - Centraliza tracking de envíos multi-proveedor (`mercadolibre`, `envia`)
  - Alimentada desde webhook `shipments` MeLi; Envia Fase 2 también escribirá aquí

- `20260420000002_api_hardening_and_contacts_legal.sql`
  - Nueva tabla `idempotency_keys` con RLS tenant-aware
  - Extensión legal de `contacts` para evidencia y revocatoria de consentimiento
  - Índices para operación (`tenant/created`, `expires_at`, `consent_revoked_at`)

- `20260420000003_human_takeover_notifications_queue.sql`
  - Habilita extensión `pgmq` (Supabase Queues)
  - Trigger DB `conversations_human_takeover_queue_trigger` para encolar eventos de takeover
  - Funciones wrapper para backend:
    - `dequeue_human_takeover_notifications(...)`
    - `ack_human_takeover_notification(...)`

- `20260420000004_whatsapp_outbound_queue.sql`
  - Crea cola durable `whatsapp_outbound_messages` (Supabase Queues / `pgmq`)
  - Funciones wrapper para backend:
    - `enqueue_whatsapp_outbound_message(...)`
    - `dequeue_whatsapp_outbound_messages(...)`
    - `ack_whatsapp_outbound_message(...)`

- `20260420000005_plan_tiering_foundation.sql`
  - Crea base de tiering multi-tenant:
    - `billing_plans`
    - `plan_capabilities`
    - `tenant_subscriptions`
    - `tenant_usage_counters`
    - `tenant_usage_events`
  - Seed de capabilities por plan (`basic`, `pro`, `enterprise`)
  - RPCs de enforcement/consulta:
    - `consume_tenant_capability(...)`
    - `get_tenant_plan_capabilities(...)`
  - Existing tenants bootstrap a `enterprise` para evitar regresión inmediata

- `20260420000006_api_security_observability.sql`
  - Crea tabla `api_security_events` con RLS
  - Crea RPC `cleanup_expired_idempotency_keys(...)`

---

## Hardening API (2026-04-20)

- `services/api/dependencies/security.py`:
  - rate limit por tenant + IP en buckets `write.default` y `conversation.send`
- `services/api/dependencies/idempotency.py`:
  - contrato de idempotencia con replay persistido por tenant
  - observabilidad de conflictos/replays vía `api_security_events`
- Endpoints write endurecidos con RL + idempotencia:
  - `orders.create`
  - `contacts.create`
  - `contacts.patch`
  - `shipping.quote`
  - `shipping.confirm_rate`
  - `conversations.send`
- `services/api/main.py`:
  - CORS habilita header `Idempotency-Key`
  - headers de seguridad de respuesta: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`
- Matriz técnica de hardening/validaciones documentada en:
  - `docs/tech/api-hardening-matrix.md`

---

## Notificaciones operacionales (2026-04-20)

- Integración Telegram actualizada a estado operativo:
  - `docs/integrations/telegram.md`
- Pipeline de notificación desacoplado por cola:
  - `conversations.status -> trigger DB -> pgmq -> ai-orchestrator worker`
- Worker implementa manejo de errores transitorios/permanentes en Telegram:
  - errores permanentes de config (`400/401/403/404`) se marcan manejados
  - errores de red/5xx quedan para retry por visibilidad de cola

---

## Contratos MeLi (2026-04-20)

### Sync pull MeLi → Supabase
Campos en `marketplace_listings` actualizados por tres vías:
- Webhook `items`: actualización reactiva ante cambios en MeLi
- `sync_meli_stock()` (sync manual / post-orden): aprovecha el GET previo
- `link_listing()` y `import_from_meli()`: pull inmediato al vincular o importar

### Shipment tracking
- Webhook `shipments`: avanza estado de orden **y** persiste en `order_tracking`
- `order_tracking` es multi-proveedor: `provider = 'mercadolibre' | 'envia'`
- Select/insert-or-update idempotente por `(tenant_id, provider, external_id)`

### Contactos desde órdenes MeLi
- `_process_order()` intenta crear contacto si `buyer.billing_info.phone` está disponible
- Upsert idempotente por `(tenant_id, phone)` — no crea datos fake si no hay teléfono
- `contact_id` se enlaza en la orden al crearse

---

## Migraciones anteriores (2026-04-19)

- `20260419000000_conversation_processing_contract.sql`
  - backfill de estados legacy conversación
  - constraint canónico de conversación
  - contrato explícito de procesamiento de mensajes

- `20260419000001_rbac_operator_runtime_only.sql`
  - backfill `agent -> operator`
  - constraint de roles runtime

- `20260419000002_meli_oauth_state_store.sql`
  - tabla `integration_oauth_states` para nonce one-time de OAuth MeLi

---

## Migraciones anteriores (2026-04-18)

- `20260418000000_marketplace_meli_variation_id.sql`
  - Agrega `meli_variation_id` a `marketplace_listings` para sincronización de variantes MeLi

- `20260418000003_orders_shipping_cost.sql`
  - Agrega columna `shipping_cost DECIMAL(10,2) NOT NULL DEFAULT 0` a tabla `orders`
  - Implementación completa end-to-end:
    - Backend (`services/api/routers/orders.py`): campo en `OrderCreate`, cálculo de `total_amount = sum(items) + shipping_cost`, incluido en INSERT y en SELECT de listado
    - Frontend (`apps/web/app/dashboard/(sales)/shipping/shipping-quote-form.tsx`): formulario completo de cotización con formulario de org/dest/paquete, selección de tarifa, y acciones Fase 2 post-cotización

- `20260418000004_contacts_address.sql`
  - Agrega campos de dirección a `contacts` para contexto de entrega

---

## UX Mercado Libre (2026-04-20)

- `marketplace-manager.tsx`: filtros por estado (Todos / Activos / Pausados / Cerrados / Sin vincular)
- Badge de condición (`Nuevo` / `Usado`) en columna de publicación
- Filtrado combinado: tab de estado + búsqueda por texto

---

## Validación ejecutada en esta sesión

- Certificación 2026-04-21:
  - `git remote -v` ✅ (sin token embebido en URL)
  - `python3.11 -m unittest discover -s tests -p 'test_*.py'` ✅ (42 tests)
  - `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
  - `pnpm --filter web lint` ✅ (warnings preexistentes)
  - `pnpm --filter web exec tsc --noEmit` ✅
  - `python3.11 -m py_compile services/api/main.py services/connector-whatsapp/main.py services/ai-orchestrator/main.py` ✅
  - `supabase db query --linked` (solo lectura) ✅:
    - tablas clave presentes (`api_security_events`, `idempotency_keys`, `integration_oauth_states`, `order_tracking`, `tenant_usage_events`)
    - extensiones `pgmq` y `vector` activas
    - funciones críticas de colas/capabilities/idempotency presentes
  - `pnpm --filter web build` ✅ (build completo, rutas generadas)

- `python3 -m unittest discover -s tests -p 'test_*.py'` ✅ (42 tests)
- `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
- `pnpm --filter web lint` ✅ (con warnings preexistentes, sin errores)
- `python3 -m py_compile services/api/integrations/envia_client.py services/api/routers/shipping.py` ✅
- Re-validación post-ajustes UX (2026-04-20): `node --test apps/web/tests/marketplace-badges.test.mjs` ✅ y `pnpm --filter web lint` ✅ (solo warnings preexistentes)
- Validación hardening/contactos (2026-04-20):
  - `python3 -m py_compile services/api/main.py services/api/routers/orders.py services/api/routers/shipping.py services/api/routers/conversations.py services/api/routers/contacts.py services/api/dependencies/security.py services/api/dependencies/idempotency.py` ✅
  - `pnpm --filter web lint` ✅ (solo warnings preexistentes)
- Validación queue/notifications (2026-04-20):
  - `python3 -m py_compile services/ai-orchestrator/worker.py services/ai-orchestrator/notifications.py` ✅
  - Migraciones ejecutadas en Supabase linked:
    - `20260420000000_marketplace_listings_meli_fields.sql` ✅
    - `20260420000002_api_hardening_and_contacts_legal.sql` ✅
    - `20260420000003_human_takeover_notifications_queue.sql` ✅
    - `20260420000004_whatsapp_outbound_queue.sql` ✅
    - `20260420000001_order_tracking.sql` ya aplicada (DB respondió `relation "order_tracking" already exists`)
  - Certificación SQL remota (`supabase db query --linked`) ✅:
    - `has_meli_title=true`
    - `has_order_tracking=true`
    - `has_idempotency_keys=true`
    - `has_contacts_legal=true`
    - `has_pgmq_extension=true`
    - `has_dequeue_fn=true`
    - `has_ack_fn=true`
    - `has_takeover_trigger=true`
    - `has_queue_table=true`
    - `has_enqueue_wa_fn=true`
    - `has_dequeue_wa_fn=true`
    - `has_ack_wa_fn=true`
    - `has_wa_queue_table=true`
  - Tests dedicados queue outbound:
    - `python3 -m unittest tests/test_conversations_outbound_queue.py tests/test_worker_whatsapp_outbound_queue.py` ✅
  - `python3 -m unittest discover -s tests -p 'test_*.py'` ✅ (39 tests)
  - `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
  - `pnpm --filter web lint` ✅ (solo warnings preexistentes)
- Validación tiering foundation (2026-04-20):
  - Migración aplicada en Supabase linked:
    - `20260420000005_plan_tiering_foundation.sql` ✅
  - Certificación SQL remota (`supabase db query --linked`) ✅:
    - `has_billing_plans=true`
    - `has_plan_capabilities=true`
    - `has_tenant_subscriptions=true`
    - `has_usage_counters=true`
    - `has_consume_fn=true`
    - `has_get_caps_fn=true`
    - distribución inicial de subscriptions: `enterprise=1 tenant`
  - `python3 -m unittest tests/test_plan_capability_dependency.py` ✅
  - `python3 -m unittest discover -s tests -p 'test_*.py'` ✅ (42 tests)
  - `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
  - `pnpm --filter web lint` ✅ (solo warnings preexistentes)
- Validación observabilidad + Envia Fase 2 parcial (2026-04-20):
  - `supabase db query --linked -f supabase/migrations/20260420000006_api_security_observability.sql` ✅
  - Certificación SQL remota (`supabase db query --linked`) ✅:
    - `has_api_security_events=true`
    - `has_cleanup_fn=true`
  - `python3 -m py_compile services/api/integrations/envia_client.py services/api/routers/shipping.py services/api/routers/settings.py services/api/dependencies/idempotency.py services/ai-orchestrator/worker.py services/ai-orchestrator/server.py` ✅
  - `python3 -m unittest discover -s tests -p 'test_*.py'` ✅ (42 tests)
  - `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
  - `pnpm --filter web lint` ✅ (solo warnings preexistentes)
- Smoke E2E Envia (sandbox/prod, token tenant) ✅:
  - Sandbox: con DANE8 hubo tarifas en 4 carriers (`fedex`, `serviEntrega`, `dhl`, `tcc`)
  - Producción: con DANE8 hubo tarifas en 5 carriers (`serviEntrega`, `dhl`, `interRapidisimo`, `deprisa`, `tcc`)

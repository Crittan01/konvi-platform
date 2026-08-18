# Backend — Documento Maestro

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Documento canónico del backend de Konvi Platform. Toda afirmación fue verificada contra el código
(`archivo:línea`) en la fecha de la cabecera. Para stack, CI/CD e infraestructura ver
`docs/tech/TRD.md`; para contratos runtime extendidos (FSM legacy, schema de credenciales, tiering)
ver `.context/06-contracts.md`.

---

## 1. Mapa de servicios y responsabilidades

| Servicio | Deploy Render | Responsabilidad | Entrada |
|---|---|---|---|
| `services/api` | `konvi-api` (web, uvicorn `main:app`) | **Core API REST síncrona / gateway**: 28 routers bajo `/api/v1`, auth JWT, RBAC, rate-limit, idempotency, webhooks de providers de dinero/logística (Wompi, Aveonline, MeLi, Telegram), OAuth MeLi, embeddings KB. | `services/api/main.py` |
| `services/connector-whatsapp` | `konvi-connector` (web, uvicorn `main:app`) | **Webhook gateway Meta — Model B Direct Provider per-tenant** (ADR-0023): recibe webhooks de N Meta Apps (una por tenant) enrutados por `POST/GET /api/v1/whatsapp/webhook/{tenant_id}`, verifica HMAC per-tenant, persiste inbox durable. Deploy unit independiente con pins propios (FastAPI 0.128.8) — **no puede importar de `services/api/`**. | `services/connector-whatsapp/main.py`; `.context/06-contracts.md` §7 |
| `services/ai-orchestrator` | `konvi-orchestrator` (web, uvicorn `server:app`) | **Worker IA**: `OrchestratorWorker` en daemon thread dentro del web service. Polling de inbound (3 s), FSM agentic + cascada LLM, outbound directo y por cola pgmq, y 19 jobs periódicos (crons) — ver §6. | `services/ai-orchestrator/server.py`, `worker.py` |
| `services/worker` | — | **Placeholder vacío** (solo README): reserva para separar workloads de background si el orchestrator migra a `type: worker`. No está en `render.yaml`. | `services/worker/README.md` |
| `services/cron` | — | **Placeholder vacío**: reserva para tareas programadas que no quepan en el polling del orchestrator. Hoy todos los crons corren dentro del orchestrator (§6). | `services/cron/README.md` |
| `services/connector-shopify` | — | **Placeholder vacío**: Fase 13 (futuro lejano), sin fecha. | `services/connector-shopify/README.md` |
| `services/connector-mercadolibre` | — | **Placeholder vacío**: la integración MeLi real vive dentro de `services/api/` (routers `marketplace.py`, `meli_webhook.py`, `integrations.py` + `integrations/meli_client.py`); el directorio reserva una futura extracción a servicio independiente. | `services/connector-mercadolibre/README.md` |

Infraestructura compartida: Supabase (PostgreSQL + RLS + Auth + Vault + pgmq) como única base de
datos; `service_role` en los 3 servicios Python (bypasea RLS → aislamiento por filtro `tenant_id`
explícito + lint AST, ver `docs/tech/TRD.md` §3.1).

---

## 2. Inventario de routers de `services/api` (28 montados)

Verificado: 28 llamadas `app.include_router` en `services/api/main.py:250-311` (28 módulos en
`services/api/routers/`, todos montados). Gates:

- **`_OFFBOARDING_GATE`** = `reject_if_tenant_deleting` → 423 en grace / 410 post-hard-delete, skip
  en GET/HEAD/OPTIONS (`main.py:43-48`).
- **`_MFA_GATE`** = `_OFFBOARDING_GATE` + `enforce_mfa` (AAL2) (`main.py:57`).
- **Sin gate** = webhooks externos (autenticados por firma/secret del provider, no JWT) y routers que
  deben operar durante grace/recovery.

| # | Router (módulo) | Prefix | Gate | Propósito |
|---|---|---|---|---|
| 1 | `products` | `/api/v1/products` | OFFBOARDING | CRUD productos y variaciones |
| 2 | `product_categories` | `/api/v1/product-categories` | OFFBOARDING | CRUD categorías |
| 3 | `product_attribute_definitions` | `/api/v1/product-attribute-definitions` | OFFBOARDING | Definiciones de atributos (ADR-0029) |
| 4 | `catalog` | `/api/v1/catalog` | OFFBOARDING | Vista de catálogo |
| 5 | `coupons` | `/api/v1/coupons` | OFFBOARDING | Cupones de descuento |
| 6 | `expenses` | `/api/v1/expenses` | MFA | Gastos (finanzas) |
| 7 | `conversations` | `/api/v1/conversations` | OFFBOARDING | Inbox + `POST /{id}/send` (guard ventana 24h, ver §5.1) |
| 8 | `orders` | `/api/v1/orders` | OFFBOARDING | Órdenes. MFA **por-endpoint** en money-movement: `PATCH /{id}` (`orders.py:379`), `POST /{id}/payment-link` (`orders.py:474`), `POST /{id}/generate-shipping-guide` (`orders.py:965`); dual-auth bot en create/payment-link |
| 9 | `contacts` | `/api/v1/contacts` | OFFBOARDING | CRM de contactos |
| 10 | `data_subject_request` | `/api/v1/contacts` | MFA | SAR/ARCO Habeas Data (export + printable) (`main.py:259-264`) |
| 11 | `tenant_offboarding` | `/api/v1/tenant/offboarding` | **sin gate de router** (cancel-deletion debe correr en grace); export y request-deletion con `enforce_mfa_strict` por-endpoint | Offboarding: export, soft-delete con grace 30 días, cancel (`main.py:265-269`; `tenant_offboarding.py:148,198`) |
| 12 | `mfa` | `/api/v1/mfa` | **sin MFA gate** (se necesita aal1 para completar el 2º factor) | TOTP enrollment/verify + recovery codes (`main.py:270-273`) |
| 13 | `sic_report` | `/api/v1` | MFA | Reporte SIC pre-cocinado (datos de crédito) (`main.py:274-278`) |
| 14 | `settings` | `/api/v1/settings` | MFA | Config del tenant, plan capabilities, mantenimiento |
| 15 | `integrations` | `/api/v1/integrations` | MFA | Credenciales de providers (Wompi/Aveonline/Telegram), OAuth MeLi (ver §5.4), sync |
| 16 | `shipping` | `/api/v1/shipping` | OFFBOARDING | Cotización Aveonline (highlights cheapest/fastest determinísticos) |
| 17 | `marketplace` | `/api/v1` | OFFBOARDING | MeLi: listings, link, import, sync de stock |
| 18 | `meli_webhook` | `/api/v1/meli` | **sin gate** — IP allowlist + dedup + anti-SSRF (§5.5) | IPN de Mercado Libre |
| 19 | `wompi_webhook` | `/api/v1/webhooks` | **sin gate** — firma SHA256 per-tenant (§5.2) | Webhook de pagos Wompi |
| 20 | `aveonline_webhook` | `/api/v1/webhooks/aveonline` | **sin gate** — secret bcrypt (§5.3) | Webhook de estados de guía |
| 21 | `telegram_webhook` | `/api/v1/integrations` | **sin gate** — secret token HMAC (§5.6) | Comandos de operador (/resolver, /estado, /ayuda) |
| 22 | `ai_agents` | `/api/v1` | OFFBOARDING | Multi-agente por tenant (templates + AI suggest) |
| 23 | `catalog_ai` | `/api/v1` | OFFBOARDING | Espejo server-side de catálogo AI |
| 24 | `ai_preview` | `/api/v1` | OFFBOARDING | Espejo server-side de preview del agente |
| 25 | `ai_index` | `/api/v1` | OFFBOARDING | Espejo server-side de indexación |
| 26 | `claims` | `/api/v1/claims` | OFFBOARDING | Reclamos (read=all, write=owner+manager) |
| 27 | `purchases` | `/api/v1/purchases` | MFA | Órdenes de compra + suppliers; WAC determinístico al recibir; recibo idempotente |
| 28 | `knowledge_base` | `/api/v1/knowledge-base` | OFFBOARDING | KB docs, embeddings server-side (Gemini 3072-dim), reindex; cap 30 docs/tenant |

Notas verificadas:

- Los routers 22-25 (prefix `/api/v1`) son espejos server-side aditivos de endpoints `/api/ai/*` del
  web (drift D3); el web sigue operando hasta el cutover (`main.py:299-307`).
- Rate limiting: los buckets `RL_WRITE_DEFAULT` / `RL_SEND_MESSAGE` se aplican **por endpoint**, no a
  nivel router; los 12 endpoints que carecían de bucket fueron cubiertos el 2026-08-02 (M15 cerrado).
- Health: `GET /health` (liveness, no toca DB) y `GET /health/ready` (readiness con check DB; 503 con
  detalle genérico — el error completo va a logs, M14 cerrado) (`main.py:322-357`).

---

## 3. Patrones de seguridad por capa

### 3.1 Auth de usuarios — JWT (`services/api/dependencies/auth.py`)

- Verificación **JWKS asimétrica**: `PyJWKClient` contra
  `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, cache 3600 s (`auth.py:29,47-50`). Acepta
  `ES256` y `RS256` vía JWKS; `HS256` solo si `SUPABASE_JWT_SECRET` está presente (fallback legacy
  transicional A0.2b); `audience="authenticated"` en ambos caminos (`auth.py:94-152`).
- Claims: `tenant_id` desde `app_metadata.tenant_id` (`get_current_tenant`, `auth.py:173-186`, 403
  si falta); `role` desde `app_metadata.role` con default `operator` (`auth.py:189-200`); `sub`
  (`auth.py:203-206`); `aal` para MFA (`auth.py:386,409`).
- **RBAC runtime**: roles vivos `owner|manager|operator` (`RUNTIME_ROLES`, `auth.py:53`);
  `require_write_role` (owner+manager, `auth.py:209-223`) y `require_owner_role`
  (`auth.py:226-239`). `agent` no existe en runtime (`.context/06-contracts.md` §5).
- **MFA**: `enforce_mfa` (`auth.py:381-395`) — pasa con `aal2`; si `aal1` y el usuario tiene factor
  verificado (lookup cacheado 60 s, `auth.py:247-248`) → 401; fail-open ante outage del Auth admin.
  `enforce_mfa_strict` (`auth.py:398-428`) — fail-closed (503) para crown-jewels (export/deletion de
  offboarding). Enforcement de **enrolamiento** para write-roles con grace:
  deadline = max(created_at, `MFA_MANDATORY_START`) + `MFA_MANDATORY_GRACE_DAYS` (14)
  (`auth.py:68-75,300-348`); invocado desde los gates de rol. En prod `MFA_MANDATORY_ENABLED=false`
  (brecha A1). La dependencia standalone `enforce_mfa_enrollment` (`auth.py:367-378`) existe pero no
  tiene consumidores.
- **Ciclo de vida del tenant**: `reject_if_tenant_deleting` (`auth.py:439-518`) — 423 si
  `deletion_requested_at`, 410 si `deleted_at`, fail-open si la query falla.

### 3.2 Dual-auth service-to-service (`services/api/dependencies/internal_auth.py`)

- Headers `X-Internal-Service-Secret` (verificado con `hmac.compare_digest` contra env,
  `internal_auth.py:40-48`) + `X-Tenant-Id` (400 `MISSING_TENANT_ID` si falta, `:64-71`).
- `get_tenant_id_internal_or_user` (`:51-75`): secret válido → tenant del header; si no, fallback a
  JWT. `get_role_internal_or_user` (`:78-86`): internal → `owner`. `enforce_mfa_internal_or_user`
  (`:108-117`): NO-OP para service-to-service.
- Consumidores: solo `routers/orders.py` y `routers/shipping.py` (payment-link, create order,
  shipping quote/guide desde el bot).
- **Limitación A12**: el `X-Tenant-Id` es autodeclarado — la única barrera es el secret compartido.

### 3.3 Rate limiting (`services/api/dependencies/security.py`)

- Distribuido: RPC `rate_limit_hit` (ventana fija, UPSERT atómico, SECURITY DEFINER — migración
  `20260425000000_distributed_rate_limiter.sql:22-47`) sobre tabla `rate_limit_windows`; llamada en
  `security.py:75-95`. Fallback automático a sliding-window in-memory ante excepción (`:205-212`).
- Key: `bucket:tenant[:user]:ip` (`:191-196`); headers `X-RateLimit-*`; 429 con `Retry-After`;
  registra `api_security_events` (`:218-252`).
- Buckets: `write.default` 120/min (`:258,261-263`), `conversation.send` 40/min (`:259,264-267`),
  MFA verify 5/min (`:288-291`), MFA regenerate 1/día (`:293-300`), offboarding export 1/h
  (`:302-308`) y deletion 1/día (`:310-316`). Env: `render.yaml:269-276`.
- IP del cliente: `resolve_client_ip` (`security.py:119-145`) — `TRUSTED_CLIENT_IP_HEADER`
  (`cf-connecting-ip` en prod, `render.yaml:303-304`) → XFF → `request.client.host`. **Pendiente
  T4-01**: verificación empírica de que Render/CF sobrescribe el header (spoofing potencial, A2).
- Webhooks: `webhook_rate_limit_check` por IP (`:319-346`), usado en meli/aveonline/wompi.

### 3.4 Idempotency (`services/api/dependencies/idempotency.py`)

- Header opcional `Idempotency-Key` (regex `^[A-Za-z0-9:_-]{8,128}$`, 422 si inválido) (`:22,36-60`).
- Scope `tenant_id + method + path + key`; tabla `idempotency_keys` con UNIQUE y `expires_at`
  default 24 h (migración `20260420000002`).
- Semántica: payload distinto o request en curso → **409**; replay exacto → respuesta persistida
  (`:79-122`); `finalize_idempotency` persiste respuesta (`:163-179`), `abort_idempotency` borra
  (`:182-196`). Cleanup: RPC `cleanup_expired_idempotency_keys` desde el worker (§6.2, job 5) y
  endpoint manual `settings.py:431-453`.

### 3.5 CORS, security headers, request-id, errores (`services/api/main.py`)

- **CORS**: orígenes de `ALLOWED_ORIGINS` (default localhost); credentials on; headers permitidos
  `Authorization, Content-Type, Idempotency-Key`; expuestos `X-RateLimit-*, Retry-After,
  X-Request-ID` (`main.py:124-146`).
- **Security headers** (middleware, `main.py:149-167`): `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`,
  CSP `default-src 'none'; connect-src 'self'; frame-ancestors 'none'` (la API solo sirve JSON),
  HSTS `max-age=31536000; includeSubDomains`.
- **Request-ID**: middleware (`main.py:170-186`) — respeta `X-Request-ID` entrante (truncado a 64) o
  genera UUID; lo expone en `request.state.request_id` y en la respuesta.
- **Errores uniformes es-CO**: handler de `RequestValidationError` (`main.py:189-247`) normaliza el
  422 de FastAPI a `{detail: "<texto es-CO>", errors: [{field, message}], request_id}` con el mapa
  `_VALIDATION_ES` (missing→"es obligatorio", enum→"no es una opción permitida", etc.). Sin este
  handler el frontend recibiría mensajes en inglés.
- **Startup fail-fast**: `_validate_startup_config()` hace `sys.exit(1)` si falta
  `NEXT_PUBLIC_SUPABASE_URL`, secret key o `INTERNAL_SERVICE_SECRET` (`main.py:67-104`).

### 3.6 Audit decorator (`services/api/dependencies/audit.py`)

- `@audit_log(entity_type, action)` opt-in (`audit.py:153-215`): inserta en `audit_log` **después**
  del handler (excepción → no audita); fire-and-forget (fallo del insert → warning, no rompe,
  `:74-86`). `entity_id` desde path params `*_id` → `result.id` (`:110-124`); user desde JWT `sub`/
  email (`:127-135`). Aplicado a 17+ endpoints (orders, contacts, products, claims, purchases, KB,
  settings, team, integrations — `.context/06-contracts.md` §17).

---

## 4. Contratos de datos clave (verificados en migraciones)

> Referencia narrativa: `.context/06-contracts.md`. Aquí va el estado **de la DB** verificado contra
> `supabase/migrations/` el 2026-08-02. Donde difieren, manda esto (política rev.72: la fuente viva
> es DB + código, no docs — `.context/05-doc-policy.md`).

### 4.1 `conversations.status` — CHECK vigente

`bot_active | human_takeover | closed | opted_out`
(`supabase/migrations/20260514180000_conversations_status_opted_out.sql:20-27`;
ninguna migración posterior lo redefine).

- `bot_active`: el bot responde. `human_takeover` / `closed`: bot silenciado (solo humano reabre).
- `opted_out`: cliente revocó consent (STOP); el orchestrator skipea todo inbound; reactivación
  manual del operador.

### 4.2 `messages.processing_status` — CHECK vigente

`pending | processing | processed | skipped | failed | ack_pending`
(`supabase/migrations/20260428000001_messages_ack_pending_status.sql:21-23`).

- El worker solo procesa `pending` (§6.1). `ack_pending`: outbound ya enviado a Meta pero el UPDATE
  de traza falló 3 reintentos — reconciliación manual, **no** se reenvía (anti-duplicado).

### 4.3 `orders.status` — CHECK vigente

`pending | pending_payment | confirmed | processing | shipped | delivered | cancelled`
(`supabase/migrations/20260703160000_f62_orders_status_check.sql:16-18`).

⚠ El CHECK quedó `NOT VALID` (filas preexistentes nunca validadas; el `VALIDATE CONSTRAINT` quedó
como tarea manual pendiente, nota en la propia migración).

### 4.4 `conversations.agentic_state` — FSM agentic (9 estados)

`GREETING | EXPLORING | CART_BUILDING | PII_COLLECTION | SHIPPING_QUOTE | CARRIER_SELECTION |
PAYMENT | POST_PAYMENT | HUMAN_HANDOFF` — CHECK `conversations_agentic_state_chk`
(`supabase/migrations/20260604000000_conversations_agentic_state.sql:24-39`, NULL permitido para
legacy) == enum `AgenticState` (`services/ai-orchestrator/agentic/state_machine/states.py:11-36`,
su docstring exige paridad con el CHECK). Resolver determinístico `resolver.py`, matriz
`transitions.py`. Coexiste con el FSM transaccional legacy (`fsm/states.py`, ver
`.context/06-contracts.md` §13).

### 4.5 `claims.status` — CHECK vigente

`open | investigating | resolved | refunded | rejected | cancelled`
(`supabase/migrations/20260624010000_claims_status_check.sql:32-36`).

⚠ **Corrección a `.context/06-contracts.md` §17** (dice `open|in_progress|resolved|closed|cancelled`
— stale): el vocabulario real se unificó al de la UI en el finiquito A4.

### 4.6 `purchase_orders.status` — CHECK vigente

`ordered | received | cancelled` (`supabase/migrations/20260704153002:64-66`). La poda desde
`draft|ordered|in_transit|received|cancelled` fue **condicional**: si prod tenía filas legacy, el
tightening se omitió con `RAISE NOTICE` (`:56-72`).

### 4.7 Otros contratos runtime (referencia)

- Roles: `owner|manager|operator` (§3.1). RBAC claims: read=all, write=owner+manager.
- Wompi: orden `pending_payment` → link; APPROVED → `confirmed` + stock; TTL 35 min (§5.2).
- Credenciales WhatsApp: `tenant_integrations` per-tenant, Model B, secretos en Vault
  (`.context/06-contracts.md` §7).
- Shipping: provider único `aveonline` (ADR-0019); guía real gateada per-tenant por
  `real_guides_enabled` (`.context/06-contracts.md` §9).
- Tiering: RPC `consume_tenant_capability(...)`; snapshot `GET /api/v1/settings/plan-capabilities`
  (`.context/06-contracts.md` §10).

---

## 5. Flujos backend críticos

### 5.1 Meta → inbox durable → orchestrator → outbound

1. **Recepción**: `POST /api/v1/whatsapp/webhook/{tenant_id}` → `receive_message`
   (`services/connector-whatsapp/routers/webhook.py:153`; handshake GET en `webhook.py:45` con
   `verify_token` per-tenant).
2. **Verificación** (`dependencies/meta.py:475` `verify_meta_signature_for_tenant`): cap body 512 KB
   (413, `meta.py:77,497-503`); rate-limit per-IP 240/60 s (`meta.py:74-106`); app_secret per-tenant
   desde Vault (`meta.py:347-379`); HMAC SHA-256 constant-time (`meta.py:465-472,550`);
   **invariante cross-tenant**: `phone_number_id` del payload debe resolver al `tenant_id` del path,
   si no → 403 (`meta.py:562-572`). Caches TTL 300 s con single-flight (`meta.py:145,262-297`).
3. **Inbox durable**: persiste payload crudo en `whatsapp_webhook_inbox` (PK sha256 del body) ANTES
   del 200 (`webhook.py:180-187` → `services/inbox.py:54-70`); 200 inmediato a Meta
   (`webhook.py:197`).
4. **Procesamiento (BackgroundTask)**: `decouple_and_enqueue` (`webhook.py:81-150`) → parseo →
   `persist_whatsapp_message` (`services/db_persistence.py:237`): tenant = el HMAC-verificado del
   path (`:281`), find-or-create conversación con gate Habeas Data (`:102-234`), dedup por
   `meta_message_id` (`:294-308`), insert `messages` con `processing_status='pending'` (`:310-326`).
5. **Re-drive**: `redrive_loop` (`main.py:20-43` + `services/inbox.py:195-222`) — lease 120 s, máx 5
   intentos, dead-letter, para crashes entre el 200 y el procesamiento.
6. **Orchestrator (polling)**: `_poll_inbound_messages` (`worker.py:791`) — SELECT inbound `pending`
   top-50 (`:814-822`), round-robin por tenant (`:829`), coalescing por conversación (`:840`), CAS
   lock a `processing` (`:867-872`), dispatch agentic (`:907` → `agentic/dispatcher.py:146`).
7. **Respuesta del bot — dos caminos** (`orchestrator.py`):
   - Directo: `_send_outbound_text` (`orchestrator.py:836`) → Meta Graph API
     `POST /{phone_id}/messages` (`whatsapp_sender.py:119,186-190`, API **v22.0** `:19`) + insert
     outbound `processed` (`orchestrator.py:1126-1137`).
   - Si el envío directo falla → insert outbound pending + RPC `enqueue_whatsapp_outbound_message`
     (`orchestrator.py:1159-1183`) → cola pgmq.
8. **Outbound humano (Inbox)**: `POST /api/v1/conversations/{id}/send` → `send_agent_message`
   (`services/api/routers/conversations.py:840`): guard `human_takeover` + **ventana 24 h**
   (`:895-905`, 422 `WINDOW_EXPIRED`/`WINDOW_NO_INBOUND`), insert + enqueue pgmq (`:907-949`).
9. **Consumo pgmq**: `_poll_whatsapp_outbound_messages` (`worker.py:1083`) — RPC dequeue VT 90 s
   batch 20 → envío Meta → `_mark_outbound_sent` (3 retries 100/300/1000 ms → `ack_pending`) + ACK
   pgmq (`:1182-1183`); `read_ct ≥ 5` → `failed` (`:1217-1225`); Meta **131047** (ventana cerrada) →
   no reintenta, marca `fuera_de_ventana_csw` + ACK (`:1201-1211`).
10. **Status callbacks** (sent/delivered/read): `statuses[]` → `outbound_status`
    (`services/parser.py:325,372-376` → `services/template_events.py:315,461`).

### 5.2 Wompi webhook → confirmación de orden → generación de guía

1. `POST /api/v1/webhooks/wompi` (`services/api/routers/wompi_webhook.py:43`); rate-limit 200/60 s
   (`:53-62`).
2. **Inbox durable ANTES del 200**: insert en `wompi_webhook_inbox` idempotente por
   `signature.checksum` (`:81-108`) — deliberadamente **antes** de verificar firma (filas inertes si
   es forjado; la firma se valida en background, `:76-80`).
3. Background `_process_wompi_event` (`:247`): correlación `payment_link_id → payments → order_id`
   (`_get_order_id_by_link`, `:1011-1027`); huérfano sin payments → log + return (`:304-312`).
4. **Firma**: `events_key` del tenant desde Vault (`integrations/wompi_client.py:49-86`) →
   `verify_event_signature` (`wompi_client.py:94`): SHA256 de properties+timestamp+events_key,
   `hmac.compare_digest`, fail-closed sin key (`:107-109`).
5. **Dedup** processed-aware en `wompi_events_seen` (`:336-393`); upsert `payments` (`:877`).
6. **Huérfanos**: `_handle_orphan_payment` (`:159`) — void automático si elegible
   (`wompi_client.py:558,489`), marca `orphan_voided`/`orphan_refund_pending` (`:236-244`).
7. **Validación de monto fail-closed**: total None / mismatch en centavos / moneda ≠ COP → NO
   confirma (`:520-541`).
8. **Confirmación** (idempotente: skip si ya `confirmed`, guard terminal `:465-504`):
   `_confirm_order` (`:1049`) → `orders.status='confirmed'` (`:1063-1066`) +
   `_decrement_stock_on_confirm` (`routers/orders.py:796`).
9. **Notificación**: WhatsApp vía pgmq (`:1259,1071`) + email etapa 1 (`:1477`).
10. **Guía Aveonline**: `_generate_shipping_guide` (`:1755`) — delay `GUIDE_GENERATION_DELAY_SECONDS`
    default 60 s (`:1768,1806-1807`) → claim-before-bill insert `shipments` 'generating' con índice
    único anti-doble-facturación (`:2068-2091`) → `generate_guide(simulate=…)` (`:2098-2112`) →
    update labeled/simulated con tracking (`:2173-2194`). `simulate = not (env
    AVEONLINE_GENERATE_REAL_GUIDES && tenant real_guides_enabled)` (`:1995-1999`);
    `bloquegenerarguia: "0"|"1"` (`integrations/aveonline_client.py:764`).
11. **Re-drive** de eventos perdidos: worker `wompi_inbox_reconcile` (§6.2 job 10).

### 5.3 Aveonline webhook → tracking → notificación

1. `POST /api/v1/webhooks/aveonline/{tenant_id}[/{secret_token}]`
   (`services/api/routers/aveonline_webhook.py:758-774`); rate-limit per-IP (`:599-609`).
2. **Auth**: secret de path/body/query → `verify_inbound_secret` — **bcrypt** (`checkpw`) con hash
   current + previous (grace de rotación) (`lib/webhook_secret_manager.py:115-119,154-158`); 401 si
   inválido (`:617-630`).
3. **Dedup**: `external_event_id = "{guia}|{estado}|{fecha}"` (`:252`) → RPC
   `fn_record_shipment_tracking_event` con `ON CONFLICT DO NOTHING`
   (migración `20260712040000_g_shipment_status_monotonic.sql:63`).
4. **Guard monotónico** `shipments.status_occurred_at` (en SQL): estados terminales
   (delivered/returned/cancelled) no retroceden; solo avanza si `p_occurred_at >=
   status_occurred_at` (`:71-87`); sort cronológico app-layer (`aveonline_webhook.py:690`).
5. **Orden → delivered** por rank monotónico: `_advance_order_to_delivered` (`:323`, call-site
   `:723-724`).
6. **Notificación cliente**: `_notify_status_change` (`:432`) → WhatsApp vía cola pgmq (helpers de
   `wompi_webhook.py:1311-1364`, **no** pasa por el orchestrator) + email Resend (`:481-565`).
   Alerta al operador por Telegram en exception/returned (`:365` → `telegram_webhook.py:315`).
7. **Polling backup** (A10 cerrado 2026-08-02): job periódico del worker (`AVEONLINE_STATUS_POLL_*`)
   consulta `get_estado` de shipments stale no-terminales y aplica el mismo avance monotónico vía
   RPC compartida — el tracking ya no depende al 100% del webhook.

### 5.4 OAuth Mercado Libre

1. `GET /api/v1/integrations/meli/auth-url` (`routers/integrations.py:199`, owner-only + plan gate)
   → `meli_client.get_auth_url` (`integrations/meli_client.py:197`).
2. **State firmado**: `issue_oauth_state` (`meli_client.py:116`) — payload `{tid, nonce, iat, exp}`
   b64 + HMAC-SHA256 con `MELI_OAUTH_STATE_SECRET`; TTL `MELI_OAUTH_STATE_TTL_SECONDS=600` (`:73`);
   nonce sha256 persistido en `integration_oauth_states` (`:105-113`).
3. `GET /api/v1/integrations/meli/callback` (`integrations.py:223`, sin JWT) →
   `validate_and_consume_oauth_state` (`meli_client.py:133`): firma constant-time, exp, lookup por
   nonce_hash, rechazo si consumido, **consume anti-replay con CAS**
   (`UPDATE ... .is_("consumed_at","null")`, `:184-192`).
4. **Intercambio**: `exchange_code` (`meli_client.py:256`); access + refresh tokens a **Vault**
   (`integrations.py:289-294`); upsert `tenant_integrations` provider='mercadolibre' (`:301`).
5. **Disconnect**: `DELETE /meli` (`integrations.py:343`) — revoca en MeLi + limpieza local.

### 5.5 Webhook MeLi (IPN)

`POST /api/v1/meli/webhook` (`routers/meli_webhook.py:891`): **IP allowlist** de 4 IPs oficiales
hardcoded + override env (`:80-93`), 403 + alerta por umbral (`:168-224`); rate-limit 200/60 s
(`:225-234`); **dedup distribuido** RPC `meli_webhook_seen` cross-réplica con fallback in-memory
(`:108-152`); **anti-SSRF**: `_RESOURCE_PATTERNS` por tópico validado antes del GET autenticado
(`:294-301,859-864`); procesamiento background con token auto-refresh (`:847-884`).

### 5.6 Webhook Telegram (comandos de operador)

`POST /api/v1/integrations/telegram/webhook` (`routers/telegram_webhook.py:61`): 503 si falta
`TELEGRAM_WEBHOOK_SECRET`; header `X-Telegram-Bot-Api-Secret-Token` con `hmac.compare_digest` → 401
(`:70-77`); **RBAC chat→tenant** vía `tenant_provider_identity` con self-heal contra
`notification_settings` (`:112-141`); comandos `/resolver` (UPDATE a `bot_active` filtrado por
tenant, `:236-265`), `/estado` (`:277-293`), `/ayuda` (`:226-232`); respuesta con bot_token del
tenant desde Vault (`:315-358`).

---

## 6. Worker del orchestrator (`services/ai-orchestrator/worker.py`)

### 6.1 Loop principal y heartbeat

- `run()` (`worker.py:487-500`): re-latido al tope de cada ciclo (`:495`) + `_poll_cycle()` +
  `asyncio.sleep(POLL_INTERVAL_SECONDS)` (default 3 s, `:24`; `render.yaml:382-383`).
- `_poll_inbound_messages` (`worker.py:791`): ver §5.1 paso 6. `MAX_PROCESSING_ATTEMPTS=5` (`:25`).
- **Sweep de arranque**: `_sweep_stale_messages_on_startup` (`:2419-2424`) — re-encola inbound
  `pending`/`processing` >5 min; attempts ≥5 → `failed`.
- **Heartbeat**: NO hay thread separado. Es un timestamp (`last_heartbeat_ts`, `:378`) re-latido por
  ítem dentro de los loops largos (`:848,1588,1664,2498,2906,3204`). `server.py` lo compara con
  `HEALTH_HEARTBEAT_STALE_SECONDS=120` (`server.py:66`): si age >120 s → `/health` devuelve 503 →
  Render reinicia. **Mitigado (A5 cerrado 2026-08-02)**: la cascada LLM tiene deadline de turno
  (`LLM_CASCADE_DEADLINE_SECONDS`, default 100 s < 120 s) que corta al path degraded antes de
  superar el heartbeat.

### 6.2 Los 19 jobs de `_poll_cycle` (`worker.py:518-546`, cada uno aislado con `_run_job`)

| # | Job | Método (`worker.py`) | Intervalo | Qué hace |
|---|---|---|---|---|
| 1 | `sweep_stale_processing` | `:2426` | 60 s | Reclama inbound `processing` huérfanos >3 min |
| 2 | `poll_inbound` | `:791` | cada ciclo (3 s) | Procesa mensajes pendientes → agentic → WhatsApp |
| 3 | `human_takeover_notif` | `:988` | cada ciclo (VT 90 s) | Consume pgmq takeover → Telegram/email (§6.4) |
| 4 | `whatsapp_outbound` | `:1083` | cada ciclo (VT 90 s) | Consume pgmq outbound → envío real a Meta (§5.1) |
| 5 | `idempotency_cleanup` | `:1229` | 3600 s | RPCs cleanup: idempotency keys, rate-limit windows, dedup MeLi, webhook secrets, bot_source_log, outbound cache |
| 6 | `payment_reminders` | `:2442` | 60 s | Recordatorio a órdenes `pending_payment` de 25-30 min; free-form si CSW abierta, HSM si cerrada (`:2666`) |
| 7 | `cart_abandoned` | `:2836` | 300 s | HSM MARKETING `cart_abandoned_24h_v1` a carritos 24-72 h; gate consent Ley 2300; cap 15/tenant/ciclo |
| 8 | `release_pending_payment` | `:3368` | 600 s | Cancela `pending_payment` >35 min TTL; nunca si hay pago approved/pending fresco (`:3440-3499`) |
| 9 | `wompi_void_poll` | `:3096` | 1800 s | GET /transactions/{id} para voids sin webhook; notif-antes-de-sync; lookback 48 h |
| 10 | `wompi_inbox_reconcile` | `:3274` | 180 s | Re-drive: re-POST payloads crudos de `wompi_webhook_inbox` al API (`:3336-3346`); grace 120 s, máx 5 → dead-letter |
| 11 | `anti_hibernation` | `:1311` | 840 s | **DESHABILITADO** (`render.yaml:544-545`; servicios ya Starter/always-on) |
| 12 | `takeover_sla` | `:1338` | 600 s | Alerta Telegram si escalación sin respuesta de operador >2 h; idempotente vía `sla_breach_audit` |
| 13 | `silent_conversations` | `:2189` | 300 s | Cliente escribió >10 min sin respuesta → escala a human_takeover + Telegram + mensaje degraded |
| 14 | `order_coherence` | `:2130` | 1800 s | RPC `rpc_find_incoherent_orders` (ítems+envío−descuento ≠ total), ventana 48 h (Ley 1480 art. 26) |
| 15 | `acceptance_stamp` | `:1545` | 600 s | RPC `rpc_stamp_order_acceptance` — aceptación verificable (Ley 1480 art. 50 lit. d) |
| 16 | `receipts` | `:1807` | 600 s | Emite comprobante (`rpc_issue_receipt`) + acuse WhatsApp (`:1940`) + email (`:2025`) + anulación de huérfanos (`:1892`) |
| 17 | `reversal_constancias` | `:1619` | 300 s | Constancia Decreto 1074 por WhatsApp (`:1646`) + alerta doble pago → Telegram (`:1737`) |
| 18 | `tenant_hard_delete` | `:3631` | 21600 s (6 h) | Hard-delete tenants con grace expirado: archiva a Storage + RPC atómica, batch 10. **ACTIVO en prod** (`render.yaml:355-356`) aunque el default de código es false (`:281-283`) |
| 19 | `health_metrics` | `:3763` | 300 s | Salud de integraciones per-tenant/per-provider; alerta Telegram en transiciones healthy→warning/critical |

Runbook de knobs/kill-switches: `services/ai-orchestrator/README.md` (todas las vars
`*_ENABLED` están versionadas en `render.yaml`).

### 6.3 Cascada LLM

- **Path productivo (agentic)**: `llm_invoke.py` — primary `gemini-3.1-flash-lite` (`:37`), fallback
  `gemini-3.5-flash` tras 2 fallos (`:38,45`), hasta 8 intentos (`:39`), backoff 1/2/4/8/16/16/16 s
  (`:102-104`), timeout 30 s/llamada (`agentic/agent.py:55,72`). Peor caso = 8×30+63 = **303 s**.
  Solo errores transitorios reintentan (`:85-99`); todo falla → `degraded=True` (`:72-80`).
- **Rescue Claude — muerto en prod (A6)**: `llm_claude_rescue.py:41-52` requiere
  `ANTHROPIC_API_KEY` **y** el SDK `anthropic`, que **no está en ningún requirements.txt** →
  `is_available()` siempre False.
- **Divergencia M8**: default `orchestrator.py:35` = `gemini-3.5-flash` vs `llm_invoke.py:37` =
  `gemini-3.1-flash-lite`; en prod los alinea `GEMINI_MODEL` de render.yaml. Docstrings de
  `llm_invoke.py:6-15` y `llm_cascade.py:4-16` desactualizados (tiers/modelos viejos).
- `llm_cascade.py` (multi-vendor) solo lo usa el path multimodal (`agentic/multimodal.py:196-228`).

### 6.4 Colas pgmq y notificaciones

- **Outbound**: §5.1 paso 9 (VT 90 s, batch 20, max 5, ack transaccional, 131047 no-retry).
- **Human takeover → Telegram**: `_poll_human_takeover_notifications` (`worker.py:988`) — RPC
  dequeue VT 90 s batch 10 → `notifications.py:379-425` (canales telegram/email per-tenant,
  bot_token desde Vault `:411`); dead-letter a 10 lecturas (`worker.py:1053-1070`). Las alertas
  SLA/silent/health/doble-pago **no** pasan por esta cola — llaman directo
  `telegram_notifications.notify_escalation_async` (`worker.py:1493,1764,2303,3864`).

---

## 7. Testing del backend

### 7.1 Estructura (verificado 2026-08-02 con `pytest --collect-only`)

- **361 archivos** `test_*.py` en `tests/`; **~4.300 items**: ~4.100 con
  `-m 'not dbharness'` + 201 dbharness. Frontend: **33 archivos** Vitest en `apps/web` (320 tests).
- **Markers** (`pyproject.toml:64-71`, `--strict-markers`): solo `dbharness` y `connector`.
  `SLOW_TESTS=1` es env var para `unittest.skipUnless` (paths bcrypt MFA), no marker.
- `tests/conftest.py:23-28`: aplica el marker `connector` a los tests de
  `connector_manifest.CONNECTOR_OWNED` (split de venv por pins FastAPI — el job `py-core` los
  excluye con `not connector`, `ci.yml:234`).
- **Pacto de coherencia**: `tests/test_coherence_pact.py` — cada modelo Pydantic Create/Patch de
  `services/api/routers/*` debe tener sus campos como columnas reales según
  `tests/fixtures/db_schema_canonical.json` (golden file generado desde DB live).

### 7.2 Harness DB con Postgres real (`tests/dbharness/`)

- 14 archivos, **201 tests**: RLS cross-tenant, inbox `FOR UPDATE SKIP LOCKED`, money RBAC,
  oversell, receipts, reversión de pago, SECDEF destructivas, auth claim hook, silent conversations,
  grants. Baseline de schema: `tests/dbharness/schema_baseline.sql`.
- **Cómo se levanta**: `scripts/schema_drift_check.sh` — `supabase db start` + `db reset`
  (replay-desde-cero de las migraciones, 3 reintentos) + `db dump` + **diff normalizado contra el
  baseline** (gate anti-drift; `--update` regenera). Local: `scripts/dbharness_up.sh` (docker o
  podman rootless, puerto 54322).
- **Skip elegante local** (`tests/dbharness/conftest.py`): sin `psycopg` ignora colección; DB caída
  → skip; en CI `HARNESS_REQUIRED=1` → `pytest.exit` hard-fail (all-skipped = gate rojo,
  `ci.yml:288-297`).

### 7.3 Cómo correr la suite

```bash
# Suite unidad (gate CI) — desde la raíz del repo
python3.11 -m pytest tests/ -q -m 'not dbharness' -n auto -p no:cacheprovider

# Todo el pipeline de gates (equivale al CI)
bash scripts/validate.sh --ci

# Harness DB (requiere Postgres local 54322; levantar con scripts/dbharness_up.sh)
bash scripts/validate.sh --db-harness

# Frontend
pnpm --filter web test        # Vitest
pnpm --filter web exec tsc --noEmit
```

### 7.4 Gates

| Gate | Valor | Evidencia |
|---|---|---|
| Coverage | `COVERAGE_MIN=60` (default; real ~69.5% medido 2026-08-02) | `scripts/validate.sh:25,128-149` |
| Ruff | `BASELINE_RUFF_ERRORS=202` (ratchet anti-regresión; config raíz conservadora, `services/api/pyproject.toml` estricta opt-in) | `scripts/validate.sh:424-458` |
| Tenant filter AST | 0 gaps nuevos, `--max-gaps 0` (protegido por CODEOWNERS) | `scripts/validate.sh:200-227` |
| Harness | `HARNESS_REQUIRED=1` en CI | `ci.yml:288-297` |
| Coherence pact | Pydantic↔DB golden file | `tests/test_coherence_pact.py` |
| Anti-drift schema | replay + diff contra baseline | `scripts/schema_drift_check.sh` |

Deuda: ~187 archivos de tests con path absoluto `/home/ansible/...` → CI usa symlink shim
(`ci.yml:127-139`); suite no portable (M9).

---

## 8. Operación

### 8.1 Aplicar SQL a producción

```bash
supabase db query --linked -f archivo.sql
```

**psql TCP directo está bloqueado por Supavisor** — toda interacción SQL va por la CLI (Supabase CLI
2.90.0, binario nativo). El proyecto linked es la única Supabase productiva (compartida con el dev
local, ver `docs/tech/TRD.md` §4).

### 8.2 Protocolo de migraciones

Documentado en `docs/deployment/rollout-and-rollback.md:31-32` (y resumido en `docs/HANDOFF.md`):

1. **Smoke ROLLBACK**: ejecutar la migración envuelta en `BEGIN; … ROLLBACK;` para validar sintaxis y
   plan sin aplicar.
2. **Apply**: `supabase db query --linked -f <migracion>.sql` (una migración aislada por vez).
3. **Repair**: `supabase migration repair --status applied <timestamp>` para registrar el ledger.

Reglas: **nunca** modificar migraciones aplicadas (forward-only); ante drift live↔fixture,
`python3.11 scripts/dump_schema_canonical.py --diff` y regenerar con
`python3.11 scripts/dump_schema_canonical.py` (actualiza `tests/fixtures/db_schema_canonical.json` y
`.context/07-schema-canonical.md`). Estado: **251 migraciones** en repo = ledger prod (última:
`20260802120000_drop_ghost_tables_and_revoke_grants.sql`).

### 8.3 Runbooks disponibles

| Runbook | Contenido |
|---|---|
| `docs/operations/runbooks.md` | Health/restart, env vars, aplicar SQL, incidente conversacional, certificación de intents |
| `docs/operations/runbooks/wompi-payment-reconciliation.md` | Reconciliación manual de pagos Wompi (webhook perdido del todo — limitación del API público, reintentos 30 m/3 h/24 h) |
| `docs/operations/runbooks/supabase-auth-email.md` | Email auth Supabase |
| `docs/deployment/rollout-and-rollback.md` | Protocolo de migraciones y rollback |
| `docs/runbooks/slo-and-dr.md` | SLO y disaster recovery |
| `docs/runbooks/converge-auth-claims-hook.md` | Auth claims hook |
| `docs/runbooks/backend-domains-cutover.md` / `custom-domain-cutover.md` | Cutovers de dominio |
| `services/ai-orchestrator/README.md` | Runbook de crons: kill-switches `*_ENABLED`, intervalos, semántica de los 19 jobs |
| `docs/operations/HUMAN_INTERVENTIONS.md` | Intervenciones manuales ejecutadas (pre-check → apply → post-check → repair) |

### 8.4 Operación frecuente

- **Stack local**: `make -C .local up|down|restart|status|print-urls` (api :8001, connector :8000,
  web :3000, túneles ngrok; logs `.local/logs/`). Cambios en `services/ai-orchestrator/*.py`
  requieren `make -C .local restart` (o `stop-orchestrator`/`start-orchestrator`).
- **Deploy a prod**: `git push origin origin/develop:production` (autoDeploy de los 4 servicios;
  correr `bash scripts/validate.sh --ci` antes).
- **Recargar config**: env vars se leen al inicio del proceso (excepciones hot-reload documentadas en
  `.context/02-stack.md`).

---

## Referencias internas

- `docs/tech/TRD.md` — stack, NFR, entornos, CI/CD, límites de infra.
- `.context/06-contracts.md` — contratos runtime narrativos (FSM legacy, Model B, Wompi, tiering).
- `.context/05-doc-policy.md` — política documental (migraciones ≠ fuente de verdad).
- `.audit/findings/2026-08-02-consolidated-audit.md` — hallazgos referenciados (A1-A12, M1-M20, B1-B6).
- `docs/adr/0023-meta-model-b-direct-provider-per-tenant.md` — Model B Meta per-tenant.
- `docs/HANDOFF.md` — puerta operativa (qué está live, comandos, ramas, migraciones, seguridad).

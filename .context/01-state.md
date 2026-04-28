# Current Scope — Estado Real de Implementación

**Última actualización**: 2026-04-29 (rev. 68)
**Fuente de verdad**: código en el repo (`develop`) + migraciones en `supabase/migrations/`.
**Tree funcional vigente**: `.context/00-product.md` (rev. 6).

---

## Estado Ejecutivo

- **Tenant Console**: ✅ Live (fases 1–11.5 completas)
- **Platform Console**: ❌ fuera de alcance (bloqueante OQ-P01)
- **Backend**: ✅ API + Connector WhatsApp + AI Orchestrator operativos
- **Inbox**: ✅ Certificado (rev. 67) — compliance Meta ventana 24h, multimodal audio, multi-tenant runtime
- **Coherencia core del bot**: ✅ Certificado (rev. 68) — Wompi customer_data + Envia district + FSM aterrizado + KB con guías por categoría
- **DB**: ✅ contrato endurecido (69 migraciones aplicadas)

---

## Cierre de sesión actual (2026-04-29, rev. 68) — COHERENCIA CORE DEL BOT

### Estado: 13/13 OK · 452 tests · TypeScript OK · Lint OK · 69 migraciones

Cierre completo de coherencia conversacional aterrizado a las APIs reales (Wompi customer_data + Envia district), eliminando duplicaciones de prompt y haciendo el FSM del bot cero alucinaciones / cero punto de fallo.

### Investigación oficial validada

- **Wompi `legal_id_type` Colombia**: solo `CC, CE, NIT, PP, TI, OTHER` (`DNI, RG` no aplican CO).
- **Wompi customer_data**: técnicamente opcional pero PSE/Bancolombia los requieren — pre-poblarlos reduce abandono.
- **Envia `district`**: hoy estaba en el modelo pero NO se enviaba; carriers como Coordinadora lo usan para optimizar zona de despacho.

### WS1 — Filosofía + UI Settings (eliminar duplicaciones)

- **D1 misión duplicada**: `_build_system_prompt()` ya no duplica la misión — solo va en "SOBRE LA TIENDA".
- **Placeholders humanos**: `after_hours_message` con ejemplo cálido (no robótico).
- **`escalation_role` configurable** por tenant (`tenants.escalation_role`, default `'asesor'`). UI Settings → "Escalación" con dropdown {asesor, especialista, consultor, agente}. El bot usa este término en escalaciones; tokens de detección admiten múltiples variantes para el cliente.

### WS2 — Knowledge Base reestructurado

- **6 categorías canónicas** con CHECK constraint DB: `faq, negocio, politicas, productos, envios, pagos`. "general" eliminada (cajón de sastre); migración bulk de valores antiguos a `faq`.
- **Guía por categoría** colapsable en UI: ejemplos placeholder + qué SÍ va aquí + qué NO (cross-references a Filosofía y Productos para evitar duplicación).

### WS3 — Estado del bot ampliado (4 → 8 checks)

`readiness-card.tsx` con tooltips por check + link a configurar:
1. Identidad del negocio (mision/vision/valores)
2. Tono de comunicación
3. Sedes y horario
4. Catálogo de productos
5. Knowledge Base
6. Indexación para IA
7. Agente IA — comportamiento
8. Pasarela y courier (Wompi + Envia)

### WS4 — Contactos rediseñado (document + address estructurada)

- **Migración `20260429000000_contacts_document_and_address.sql`**: `document_type` (CC/CE/NIT/PP/TI/OTHER) + `document_number` con CHECK constraint + index parcial.
- **Schema canónico de `address` JSONB** documentado en COMMENT: street, neighborhood, city, state, dane_code, building_type (casa/edificio/conjunto), tower, apartment, complex_name, reference.
- **Validators Python** en `dependencies/contact_validators.py`: tipos aceptados, longitud por tipo, normalización (puntos/espacios), helper `is_address_complete()` por building_type.
- **API**: `ContactCreate`/`ContactPatch` con field_validator + endpoint valida cruzada doc_type+doc_number; SELECT, INSERT, UPDATE incluyen los nuevos campos.
- **Anonimización Ley 1581**: revocación + soft-delete anonimizan también `document_type` + `document_number`.

### WS5 — FSM aterrizado a la realidad

- **Nuevo estado `NEEDS_DOCUMENT`** entre NAME y DIRECTION. Orden FSM rev. 68:
  ```
  CONSENT → EMAIL → NAME → DOCUMENT → DIRECTION → READY_FOR_SUMMARY
  ```
- **`OrchestratorOutput`** con `extracted_document_type` + `extracted_document_number` que el LLM extrae.
- **Persistencia validada**: el orchestrator solo escribe a DB si tipo+número son válidos (CC/CE/NIT/PP/TI/OTHER).
- **`_clear_contact_field('document')`** limpia ambos campos juntos.
- **`_CORRECTION_FIELD_TOKENS`/_PROMPT/_VARIANTS**: agregada categoría `document` para flujo de corrección post-resumen.
- **Cart summary pre-shipping**: instrucción explícita en state_instruction de `NEEDS_SHIPPING_CITY` para resumir carrito + ofrecer "agregar más productos" antes de cotizar.
- **Contexto cliente conocido**: nueva función `_load_customer_context_block()` carga pedidos activos + reclamos abiertos del contacto y los inyecta como bloque "CONTEXTO DEL CLIENTE" en el system prompt cuando hay consent.

### WS6 — Wompi customer_data completo

- `_build_customer_data()` arma el bloque desde el contacto: email, full_name, phone (con prefix `+57` separado), legal_id, legal_id_type. Solo incluye campos no vacíos.
- `create_payment_link` y `create_payment_link_sync` reciben `contact: dict` y lo propagan al payload.
- Call sites actualizados: `routers/orders.py:create_payment_link` y `routers/wompi_webhook.py` (retry) cargan `email, document_type, document_number` desde la relación `contacts` y los pasan completos.

### WS7 — Envia district enviado

- `_coerce_origin` y `_coerce_destination` en `tools/shipping_quote_tool.py` mapean `address.neighborhood` → `district` cuando está poblado. Si no, omiten el campo (no envían null).
- Funciona end-to-end desde el FSM hasta el payload Envia.

### Tests nuevos (~41)

- `tests/test_contacts_document_validation.py` (18) — tipos, longitud, normalización, address completa por building_type.
- `tests/test_orchestrator_fsm_needs_document.py` (8) — orden FSM rev. 68 con NEEDS_DOCUMENT.
- `tests/test_wompi_payment_link_customer_data.py` (9) — builder customer_data, prefix +57, regla legal_id+type juntos.
- `tests/test_envia_payload_district.py` (6) — district desde neighborhood, omisión si vacío.

Total tests: 411 → 452. Sin regresiones (test_orchestrator_catalog_prompt ajustado para nuevo orden FSM).

### Migraciones nuevas (3)

| Archivo | Descripción |
|---|---|
| `20260429000000_contacts_document_and_address.sql` | document_type/number + CHECK + index parcial + COMMENT schema address JSONB |
| `20260429000001_kb_categories_constraint.sql` | CHECK 6 categorías + migración valores legacy → faq |
| `20260429000002_tenant_escalation_role.sql` | escalation_role TEXT NOT NULL DEFAULT 'asesor' + CHECK |

Total migraciones: 66 → 69.

### Riesgos abiertos (no bloqueantes)

- **Frontend Contacts UI**: el form de contactos no muestra aún los campos `document_type/number` y `building_type` estructurado — el bot conversacional ya los captura por WhatsApp. La UI manual de contactos es backlog para sesión futura (no bloquea el flujo conversacional).
- **F7 cart abandonment**: sigue bloqueado por templates Meta.
- **F8 multimodal imagen**: aplazado tras audio (rev. 67).

---

## Cierre de sesión anterior (2026-04-28, rev. 67) — INBOX CERTIFICADO

### Estado: 13/13 OK · 411 tests · TypeScript OK · Lint OK · 66 migraciones

Certificación profunda del módulo Inbox tras Configuración e IA y Conocimiento. 7 workstreams (A-G).

### Workstream A — Frontend Inbox

- **A1 Bug timestamp lateral fix**: optimistic update sobre `conversations.last_interaction_at` cuando llega INSERT en `messages` (sin esperar al trigger DB). El UPDATE de `conversations` ahora aplica payload directamente al estado local (sin re-fetch).
- **A2 Badge unread**: tabla nueva `conversation_reads (tenant_id, user_id, conversation_id, last_read_at)` con RLS. Lateral muestra dot verde + nombre en negrita cuando hay inbound posterior a `last_read_at`. Upsert al abrir conversación.
- **A3 Banner ventana 24h Meta**: amarillo si quedan <4h, rojo si expirada o sin inbound previo. Solo en `human_takeover`.
- **A4 Tooltips en badges Bot/Agente/Cerradas**: cada estado lleva descripción explicando transiciones (no requiere docs externas para operadores no técnicos).
- **A5 Idempotency-Key end-to-end en PATCH /status**: scope canónico (`createIdempotencyKey('conversations.status')`) + proxy reenvía header + backend honra con `begin_idempotency`. Doble click rápido → 1 sola transición + 1 sola notificación Telegram.
- **A6 Dedupe realtime INSERT**: por id, evita duplicado entre realtime y polling fallback.
- **A7 Render emojis WhatsApp**: `font-family` en globals.css incluye `Apple Color Emoji`, `Segoe UI Emoji`, `Noto Color Emoji`, `Twemoji Mozilla` para que los mensajes se vean a color como en celular.

### Workstream B — Compliance Meta

- **B1 Ventana 24h en envío outbound**: `_check_24h_window_or_raise()` en `routers/conversations.py` verifica `MAX(created_at) FROM messages WHERE direction='inbound'`. Si fuera de ventana → 422 con códigos accionables (`WINDOW_EXPIRED`, `WINDOW_NO_INBOUND`). Cierra el vector de baneo del WABA.
- **B2 ACK transaccional outbound**: `_mark_outbound_sent` reintenta UPDATE 3 veces (backoff 100/300/1000 ms). Si falla los 3, marca `processing_status='ack_pending'` y ACK pgmq (NO reenvía a Meta para no duplicar al cliente). Migración 20260428000001 agrega `ack_pending` al CHECK constraint.

### Workstream C — Multi-tenant runtime

- `tests/test_tenant_isolation_inbox.py` (5 tests): valida que TODOS los endpoints del Inbox filtran por `tenant_id` en cada query a Supabase. Defensa en profundidad (RLS sola no aplica con service_role).

### Workstream D — Multimodal audio Gemini

- Módulo `services/ai-orchestrator/services/meta_media.py` con `fetch_media_bytes()` (descarga 2-step Meta: resolver URL + bytes), caché in-memory TTL 240s, validación de tamaño máx (16 MB), timeout configurable (10s).
- `_transcribe_audio_or_none()` en `orchestrator.py`: descarga audio + envía inline a Gemini 2.5 Flash multimodal (`Part(inline_data=Blob)`) + reemplaza content por la transcripción + el flow normal continúa.
- Connector persiste `media_id` + `media_mime` (extracted_media_metadata) en `messages`.
- Mimes soportados: `audio/ogg`, `audio/mp3`, `audio/mpeg`, `audio/wav`, `audio/aiff`, `audio/aac`, `audio/flac`.
- Feature flag `MULTIMODAL_AUDIO_ENABLED=true` (default activo, apagable sin redeploy).
- Migración 20260428000002 agrega `messages.media_id` + `messages.media_mime`.

### Workstream E — Limpieza y coherencia

- **E1 role_description vs misión ortogonales**: system prompt ahora separa "COMPORTAMIENTO DEL AGENTE" (de `ai_agents.role_description`) de "SOBRE LA TIENDA" (de `tenants.mision/vision/valores`). UI Settings y AI Agents con nota cruzada explicando la distinción.
- **E2 default ai_agent**: si `mision` poblada → `role_description` default sintetiza `"Asistente comercial de {tenant}, alineado a su misión y valores"`.
- **E3**: eliminado `services/api/integrations/whatsapp_sender.py` (legacy duplicado, 0 usos confirmados).
- **E4**: barrer roles legacy `agent` → 0 referencias residuales.

### Workstream F — Conversaciones huérfanas + scroll

- Migración 20260428000003 agrega `conversations.archived_at` + index parcial + backfill 90 días sin actividad. Frontend filtra `archived_at IS NULL` por default; toggle "Ver archivadas" expone histórico.
- Scroll histórico cursor-based (`loadMoreMessages`) carga +50 al llegar al top, manteniendo scroll position.

### Workstream G — Documentación

- `.context/06-contracts.md` ampliado con secciones 14 (identidad vs comportamiento), 15 (Inbox runtime).
- `.context/01-state.md` rev. 67 (este bloque).
- `.context/04-next-steps.md` actualizado.

### Tests nuevos del workstream (24)

- `tests/test_send_message_24h_window.py` (6).
- `tests/test_outbound_ack_transactional.py` (4).
- `tests/test_multimodal_audio.py` (9).
- `tests/test_tenant_isolation_inbox.py` (5).

### Riesgos abiertos (no bloqueantes)

- **Templates Meta para envío proactivo (F7 cart abandonment)**: requiere registrar plantillas en Meta Business Manager. Documentado como IH cuando se priorice.
- **Multimodal imagen (F8)**: aplazado para sesión futura. Audio ya activo cubre el caso real más frecuente.
- **Costo tokens multimodal**: cada audio 30s ≈ 5k tokens input. Despreciable a escala Free; revisar al masificar.

---

## Cierre de sesión anterior (2026-04-28, rev. 66) — CIERRE DE CERTIFICACIÓN REAL

### Estado: 13/13 OK · 389 tests · TypeScript OK · Lint OK

Cierre repo-wide en 4 workstreams. Coherencia entre código, runtime, infra,
seguridad, UX, pruebas y documentación.

### Workstream 1 — Humanización end-to-end de la conversación

**Razón:** el producto no debe sonar robótico en NINGUNA parte de la conversación.

- **System prompt Gemini**: nuevo bloque `_HUMAN_STYLE_GUIDE` inyectado en
  `_build_system_prompt`. Lista frases prohibidas ("Procesando su solicitud",
  "Estamos procesando", "Lamentamos los inconvenientes ocasionados"), reglas
  de variación sintáctica, adaptación de registro al cliente y rotación de
  expresiones de confirmación.
- **`_TONO_INSTRUCCIONES` ampliado** (orchestrator.py:1293): cada uno de los 5
  tonos pasó de un descriptor de 1 línea a un bloque con saludo / confirmación /
  cierre + ejemplo natural concreto. Reduce drift del LLM.
- **Salvaguarda de saludo determinística** (orchestrator.py): hardcoded único
  reemplazado por `_safety_greeting_response()` con **5 variaciones por tono
  (25 totales)**, rotativas por seed `hash(conversation_id + day_of_year) % 5`.
  Personalización por `first_name` cuando hay consent. Tono inválido → fallback
  amigable.
- **Mensajes templated humanizados**:
  - Cancelación de pedido (success / no-pedido-activo): 3 variantes c/u.
  - Reactivación 24h: 3 variantes.
  - Corrección de datos (`_CORRECTION_PROMPT_VARIANTS`): 2 variantes por campo.
  - Pago fallido Wompi (`_PAYMENT_FAILED_VARIANTS`): 3 variantes seleccionadas
    por hash(order_id) — mismo pedido siempre recibe la misma para consistencia.
  - Tracking no disponible: 3 variantes empáticas.
  - Ticket de claim creado: 3 variantes.
- Helper `_pick_variant(variants, seed)` y `_today_seed(conversation_id)` para
  selección determinística reutilizable.

### Workstream 2 — `MAX_PROCESSING_ATTEMPTS` unificado a 5

- `.env.example`: `5` (era `3`).
- `services/ai-orchestrator/worker.py:15`: default `5` (era `3`).
- `render.yaml:236`: ya estaba en `5`.
- Resultado: el comportamiento de reintentos local replica producción. Bugs en
  reintento 4-5 dejan de ser invisibles localmente.

### Workstream 3 — MeLi webhook hardening

**Razón:** `POST /api/v1/meli/webhook` aceptaba cualquier POST del internet
(vector DoS y costo: cada notificación dispara GET a la API MeLi).

- **IP allowlist con default seguro en código**: 4 IPs oficiales de MeLi
  (`54.88.218.97`, `18.215.140.160`, `18.213.114.129`, `18.206.34.84`)
  hardcoded como `_MELI_DEFAULT_NOTIFICATION_IPS`. Verificadas en doc oficial
  con fecha 23/04/2026. Override opcional por env var `MELI_WEBHOOK_ALLOWED_IPS`.
- **Dependency `_verify_meli_origin`**: extrae IP de `x-forwarded-for` (primer
  hop) o `request.client.host`; rechaza con 403 si IP no está en allowlist.
  Latencia in-memory < 1ms (cumple regla MeLi de 500ms en respuesta).
- **Rate-limit por IP**: bucket `webhook.meli`, 200 req/min, sobre el mismo
  limiter distribuido (`rate_limit_hit` RPC). Helper nuevo
  `webhook_rate_limit_check()` en `dependencies/security.py` no requiere
  `tenant_id` (a diferencia del rate limiter de endpoints autenticados).
- **Idempotencia in-memory**: dedup TTL 300s por
  `(application_id, resource, sent)` para defender contra replays con IP legítima.
- **`.env.example` + `render.yaml`**: variable `MELI_WEBHOOK_ALLOWED_IPS=""`
  agregada con `sync: false`. **Sin IH obligatoria** — el default cubre producción.

### Workstream 4 — Coherencia documental

- `.context/00-product.md` rev. 6: nueva sección 5.1 "Rutas hidden /
  pendientes de decisión de producto" listando `/dashboard/(products)/media`
  (gestor funcional oculto) y `/dashboard/(products)/inventory` (redirect legacy).
- `.context/01-state.md` rev. 66: este bloque.
- `.context/04-next-steps.md`: cierre 2026-04-28 + items resueltos.
- `docs/HANDOFF.md`: conteo migraciones actualizado a 62.

### Tests nuevos (74 total)

| Archivo | Tests | Cobertura |
|---|---|---|
| `tests/test_text_utils.py` | 22 | normalize_text, tokenize_text, normalize_phone, safe_float, format_pesos, format_cents_cop |
| `tests/test_orchestrator_safety_greeting.py` | 11 | 5 variaciones × 5 tonos, personalización first_name, fallback amigable, determinismo por seed |
| `tests/test_orchestrator_conversation_start.py` | 8 | helpers legacy eliminados confirmados, salvaguarda no escala |
| `tests/test_orchestrator_tone_variation.py` | 9 | cada tono con ≥200 chars, ejemplos concretos, frases anti-robot en _HUMAN_STYLE_GUIDE |
| `tests/test_humanization_audit.py` | 3 | auditoría estática anti-robot en orchestrator + routers + bancos de variantes |
| `tests/test_db_persistence_reopen.py` | 5 | reapertura de conversación closed, selección por last_interaction_at desc, creación nueva |
| `tests/test_meli_webhook_origin.py` | 16 | IP allowlist, override por env, x-forwarded-for, rate-limit, idempotencia, latencia |

### Archivos modificados

- `services/ai-orchestrator/orchestrator.py` — system prompt + tonos + salvaguarda + variantes templated
- `services/ai-orchestrator/worker.py:15` — default 5
- `services/ai-orchestrator/tools/order_status_tool.py` — variantes "tracking no disponible"
- `services/api/routers/wompi_webhook.py` — `_PAYMENT_FAILED_VARIANTS`
- `services/api/routers/meli_webhook.py` — IP allowlist + rate-limit + idempotencia
- `services/api/dependencies/security.py` — `webhook_rate_limit_check()` helper
- `.env.example` — MAX_PROCESSING_ATTEMPTS=5, MELI_WEBHOOK_ALLOWED_IPS
- `render.yaml` — MELI_WEBHOOK_ALLOWED_IPS

### Riesgos abiertos (no bloqueantes)

- **MeLi puede cambiar las 4 IPs** publicadas. Mitigación: env var override + revisión trimestral en backlog.
- **Variantes hardcoded** en código; mover a tabla `tenants.greeting_variations` queda fuera de alcance.
- **Tokens del system prompt** crecen ~150-300 por request. Despreciable a escala Free actual.

---

## Cierre de sesión anterior (2026-04-26, rev. 65) — MÓDULO CONFIGURACIÓN CERTIFICADO

### Estado: 13/13 OK · 305 tests · TypeScript OK · Lint OK

---

### Sub-módulo: General (`/dashboard/settings`)

**Identidad del negocio:**
- Logo: solo PNG/JPG/WebP; extensión derivada de MIME (no `file.name`) — previene path traversal
- Nombre: `maxLength=100`, label NIT → "NIT / CC"
- Email + celular: validados (patrón + formato)
- Todas las acciones en `actions.ts` centralizado; `getOwnerTenantId` hace `redirect('/dashboard')` si no es owner

**Filosofía del negocio (nuevo — conecta con IA):**
- Campos: `mision`, `vision`, `valores` (max 280 chars), `tono_comunicacion` (formal/amigable/cercano/profesional/juvenil)
- El orchestrator los inyecta automáticamente en el system prompt — bot habla con coherencia de marca
- DB: columnas en `tenants` + migración `20260426030000_tenant_brand_and_hours.sql`

**Presencia y ubicaciones (`StorePresenceForm` — client component):**
- Tipo: física / virtual / ambas — secciones visibles/ocultas dinámicamente
- Sedes físicas: DANE en cascada (Departamento → Municipio), campos: nombre, dirección, celular, email
- Validación: física → ≥1 sede con ciudad + dirección; virtual → ≥1 canal digital
- Canales digitales: Instagram, Facebook, TikTok, YouTube, Website
- DB: `store_type` + `social_links` + `store_locations` (JSONB flexible, incluye phone y email)

**Horario y disponibilidad (nuevo — reestructurado):**
- Horario de asesor: días Lu-Do (selector reactivo `DaysSelector` client component) + hora apertura/cierre
- Mensaje fuera de horario: el bot lo envía automáticamente cuando cliente pide asesor fuera de franja
- Política de envío: texto libre con cut-off y promociones (ej. "envío gratis desde $150.000")
- DB: `support_schedule` (JSONB), `after_hours_message`, `cutoff_message`
- Orchestrator: gate `_is_outside_support_hours()` + `_TONO_INSTRUCCIONES` por tono de marca

**Opciones de despacho — Envia (`ShippingOriginForm` — client component):**
- Selector de sede: auto-rellena nombre, dirección, departamento, municipio, celular al elegir
- "Empresa": read-only vinculada al nombre del negocio (evita inconsistencia)
- DANE en cascada igual que sedes
- Celular reactivo (state controlado)

**Resumen (panel derecho):**
- Rows navegables: cada ítem hace scroll suave a su sección (`#section-*`)
- Indicadores: ✅ configurado / ❌ sin configurar por sección
- Incluye: Estado, Stock, Tipo tienda, Sedes, Redes, Filosofía, Horario, Despacho

**Configuración operativa:** umbral de stock bajo (1–999)

---

### Sub-módulo: Usuarios y Acceso (`/dashboard/team`)

**Protección de acceso:**
- `redirect('/dashboard')` si el usuario no es owner (protección por navegación directa)
- Todas las server actions verifican `role === 'owner'`

**Estados de miembros (nuevo):**

| Estado | Descripción | Acciones disponibles |
|---|---|---|
| **Pendiente** | Invitado, no aceptó | Reenviar · Eliminar |
| **Activo** | Acceso normal | Cambiar rol · **Inactivar** · Eliminar |
| **Inactivo** | Suspendido temporalmente | **Activar** · Eliminar |

**Inactivar** (`InactivateMemberButton` con motivo opcional):
- `ban_duration: '876600h'` en Supabase Auth nativo → bloquea login + refresh de token
- `signOut(global)` → corta sesión activa inmediatamente
- `tenant_users.status = 'inactive'` → display en UI
- DB: columnas `status`, `inactivated_at`, `inactivated_reason`, `inactivated_by`

**Activar:**
- `ban_duration: 'none'` → permite login de nuevo
- `tenant_users.status = 'active'`

**Eliminar** (`RemoveMemberButton` con dialog):
- Borra de `tenant_users`
- `deleteUser(id, true)` → soft delete en Supabase (preserva UUID para audit, anonimiza PII)
- `signOut(global)` → revoca sesión inmediatamente

**Cambiar rol** (`ChangeRoleButton` con dialog):
- Dialog advierte "sesión se cerrará" antes de confirmar
- `signOut(global)` → fuerza re-autenticación con nuevas claims
- API `PATCH /settings/team/{id}` rechaza `role='owner'` (ASSIGNABLE_ROLES = {manager, operator})

**Invitación:**
- Nuevo usuario → `inviteUserByEmail` → email con link → set-password
- Usuario existente → `add_member_to_tenant` (sin email, sin nuevo usuario en auth)
- Banner diferenciado: "Invitación enviada" vs "Acceso otorgado"
- Validación: email duplicado detectado antes de invitar
- `?error=ya-es-miembro` si ya está en el equipo

**URL cleanup:** params de resultado se limpian a los 4 segundos (`TeamUrlCleaner` client component)

---

### Sub-módulo: Integraciones (`/dashboard/integrations`)

**Acceso:** owner y manager (sidebar actualizado); operators → redirect

**Vault (Supabase) — credenciales cifradas:**
- Todas las integraciones usan Vault en lugar de texto plano en JSONB
- `pgsec_create_secret` / `pgsec_read_secret` / `pgsec_update_secret` / `pgsec_delete_secret`
- `pgsec_upsert_secret` → evita error 23505 al reconectar sin haber desconectado
- Migración: `20260426020000_vault_setup_and_migration.sql`
- Ver: migración `20260426050000_vault_upsert_secret.sql`

**Confirmación antes de desconectar** (`DisconnectIntegrationButton` — dialog con advertencia específica por integración)

**Tests de conexión:**
- WhatsApp: `GET /v21.0/{phone_number_id}` en Meta API — verifica token y número activo
- Envia: `GET /available-carrier/CO/0` — verifica API key y servicio disponible
- Telegram: `sendMessage` al grupo del asesor
- Todos usan `AbortController` manual (no `AbortSignal.timeout` — compatibilidad Next.js)
- Banners de resultado con URL cleanup a los 4 segundos

**Estado visual:**
- Envia: badge "Sandbox" (naranja) / "Producción" (verde)
- MeLi: panel "Token expirado" con botón Reconectar cuando `status='error'`
- SubmitButton en todos los botones Guardar/Probar (loading state)
- `tgConnected` verifica `bot_token_secret_id` (vault) o `bot_token` (legacy)

**Manager puede:** configurar Telegram y notificaciones  
**Solo owner puede:** configurar WhatsApp, Envia, MeLi

---

### Flujos de autenticación (nuevos)

**`/set-password`** (invite + reset):
- Show/hide contraseña en ambos campos
- Validación inline (no URL redirect para errores básicos)
- Loading spinner "Guardando..."

**`/login`:**
- Show/hide contraseña
- Link "¿Olvidaste tu contraseña?" → `/forgot-password`
- Loading spinner "Ingresando..."

**`/forgot-password`:**
- Client component — `resetPasswordForEmail` desde browser (PKCE verifier en cookies del browser)
- Mensaje de éxito sin revelar si el email existe (seguridad)

**`/dashboard/account`** (nueva):
- Cambio de contraseña para usuarios logueados
- Link en sidebar: dropdown usuario → "Cambiar contraseña"

**Sidebar usuario (dropdown):**
- Avatar con inicial, email, badges de rol y plan
- Clic abre menú arriba con colores del sidebar (oscuro)
- Opciones: Cambiar contraseña · Cerrar sesión

---

### Seguridad — resumen de capas

| Capa | Implementación |
|---|---|
| Redirect por navegación directa | `/settings`, `/team` → solo owner; `/integrations` → owner/manager |
| API role enforcement | `ASSIGNABLE_ROLES = {manager, operator}` — nunca owner por API |
| Logo upload | MIME_TO_EXT — extensión del path nunca viene de `file.name` |
| Credenciales | Supabase Vault — AES cifrado, nunca texto plano en JSONB |
| Sesiones | `signOut(global)` en inactivar/eliminar/cambiar rol |
| Inactivación | `ban_duration` nativo Supabase Auth — bloquea login + refresh |
| JWT claims | Trigger `on_tenant_assignment` (activo) — Custom Access Token Hook preparado (pendiente activación en Dashboard, en beta) |

---

### Migraciones aplicadas en esta sesión

| Archivo | Descripción |
|---|---|
| `20260426000000_tenant_store_info.sql` | `store_type`, `social_links` |
| `20260426010000_tenant_locations_and_hours.sql` | `store_locations`, `business_hours` |
| `20260426020000_vault_setup_and_migration.sql` | Vault RPCs + migración de credentials existentes |
| `20260426030000_tenant_brand_and_hours.sql` | `mision`, `vision`, `valores`, `tono_comunicacion`, `support_schedule`, `after_hours_message`, `cutoff_message` |
| `20260426040000_tenant_vision.sql` | Campo `vision` |
| `20260426050000_vault_upsert_secret.sql` | `pgsec_upsert_secret` (fix reconexión) |
| `20260426060000_tenant_users_status.sql` | `status`, `inactivated_at/reason/by` en `tenant_users`; RPC `get_tenant_team` actualizada |
| `20260426070000_auth_custom_access_token_hook.sql` | Función hook (pendiente IH para activar) |
| `20260426080000_drop_tenant_assignment_trigger.sql` | Trigger a eliminar post-IH (no aplicada) |

---

### Pendientes operativos (no bloquean producción)

| Item | Estado |
|---|---|
| SMTP propio (Resend/SendGrid) | ⏳ Pre go-live — R-08 |
| Custom Access Token Hook | ⏳ Activar en Dashboard cuando salga de beta |
| `ANTI_HIBERNATION_PING_URL` en Render | ⏳ IH pendiente |

---

## Cierre de sesión anterior (2026-04-25, rev. 64)

- **GAP-1 — Corrección de datos en READY_FOR_SUMMARY** (`orchestrator.py`):
  - `_detect_correction_intent(text)`: detecta frases como "el email está mal", "quiero cambiar mi nombre", "la dirección está incorrecta" → retorna `'email'`, `'name'` o `'address'`.
  - `_clear_contact_field(supabase, contact_id, tenant_id, field)`: limpia el campo en DB → el FSM lo detecta vacío y vuelve al estado correcto (`NEEDS_EMAIL`, `NEEDS_NAME`, `NEEDS_DIRECTION`) en el siguiente mensaje.
  - `_CORRECTION_PROMPT`: respuestas amigables por campo ("Entendido 👍 ¿Cuál es tu correo electrónico correcto?").
  - Gate insertado entre el check de afirmativo y el LLM, solo cuando `display_state == READY_FOR_SUMMARY`.
  - Tests: `tests/test_orchestrator_data_correction.py` (18 tests: 14 detección + 3 limpieza + 2 prompts).

- **GAP-2 — Alternativas determinísticas cuando producto sin stock** (`orchestrator.py`):
  - En `_build_system_prompt`, cuando `display_state` ∉ data-collection-states y el producto del contexto tiene `stock_total=0`: inyecta bloque "⚠️ PRODUCTO AGOTADO + INSTRUCCIÓN" con hasta 5 alternativas con stock > 0 del catálogo real.
  - Si no hay alternativas: mensaje "sin alternativas en catálogo" para que el LLM informe al cliente.
  - El LLM usa datos reales (no inventa precios ni stock).
  - Tests: `tests/test_orchestrator_no_stock_alternatives.py` (6 tests).

- **TTL verificado**: `payment_link_tool.py` ya decía "30 minutos" — sin cambio necesario.

- **Principio aplicado**: todas las implementaciones basadas en evidencia de código real, sin asumir comportamiento no verificado.

- **Pruebas de regresión**: `validate.sh` → 13/13 OK, **259 tests OK** (+29), TypeScript OK, lint OK.

---

## Cierre de sesión anterior (2026-04-25, rev. 63)

- **F5 — Ticket automático en claims al escalar reclamo**:
  - `services/ai-orchestrator/orchestrator.py`: constante `_COMPLAINT_INTENTS` (`complaint`, `reclamo`, `devolucion`, etc). Funciones `_find_recent_claimable_order` (busca orden confirmed/processing/shipped/delivered) y `_create_claim` (INSERT en `claims`, retorna `ticket_number` del trigger).
  - En bloque de escalación (paso 8): si `requires_human=True` y `intent_detected ∈ _COMPLAINT_INTENTS`, crea ticket automático y agrega `#ticket` al mensaje de escalación.
  - `order_id NOT NULL` en claims: si no hay orden elegible, escala sin ticket (sin error).
  - Tests: `tests/test_orchestrator_claims_flow.py` (11 tests).

- **F6 — Telegram bidireccional (`/resolver` desde Telegram)**:
  - `services/api/routers/telegram_webhook.py` (nuevo): `POST /api/v1/integrations/telegram/webhook`.
  - Auth: header `X-Telegram-Bot-Api-Secret-Token` validado contra `TELEGRAM_WEBHOOK_SECRET`.
  - Comandos: `/resolver {conv_id}` → `bot_active`; `/estado {conv_id}` → status, phone, timestamp; `/ayuda` → lista de comandos.
  - Responde al asesor via `sendMessage` al mismo `chat_id` usando `bot_token` de `notification_settings`.
  - Sin `TELEGRAM_WEBHOOK_SECRET` → 503 (endpoint deshabilitado, no rompe producción).
  - `services/api/main.py`: router registrado en `/api/v1/integrations`.
  - `render.yaml`: variable `TELEGRAM_WEBHOOK_SECRET` (sync: false).
  - Tests: `tests/test_telegram_webhook.py` (15 tests).
  - **INTERVENCION HUMANA REQUERIDA**: configurar `setWebhook` y `TELEGRAM_WEBHOOK_SECRET` en Render.

- **Pruebas de regresión**: `validate.sh` → 13/13 OK, **230 tests OK** (+26), TypeScript OK, lint OK.

---

## Cierre de sesión anterior (2026-04-25, rev. 62)

- **F1 — Wompi FAILED/DECLINED → retry de pago**:
  - `services/api/integrations/wompi_client.py`: nueva función `create_payment_link_sync` (síncrona para BackgroundTasks).
  - `services/api/routers/wompi_webhook.py`: nuevo `_maybe_offer_payment_retry` — si status ∈ `{DECLINED, ERROR, VOIDED}` y pedido sigue en `pending_payment`, genera nuevo link Wompi y encola outbound al cliente. Si falla o sin clave, encola mensaje de fallo ("escríbenos asesor"). Helpers: `_enqueue_payment_failed_msg`, `_enqueue_outbound_text`.
  - Tests: `tests/test_wompi_retry_payment.py` (6 tests).

- **F2 — Tracking real en bot via `order_tracking`**:
  - `services/ai-orchestrator/tools/order_status_tool.py`: nueva función `_get_order_tracking`, `_format_tracking_date`. `_build_order_response` recibe `tracking` opcional y muestra guía, carrier, URL, ETA cuando el pedido está en `shipped`/`processing`/`delivered`. Sin tracking → mensaje "guía no disponible".
  - Tests: `tests/test_order_status_tracking.py` (14 tests).

- **F3A — Timeout ventana 24h (WhatsApp policy)**:
  - `services/ai-orchestrator/orchestrator.py`: nueva función `_is_conversation_window_expired` (consulta `last_interaction_at`). Si expiró, `buying_intent = False` → FSM fuerza `CATALOG_MODE`, ignorando historial de compra anterior.
  - Variable nueva: `CONVERSATION_WINDOW_HOURS=24` en `render.yaml`, `.env.example`.

- **F3B — Comando "cancelar/reiniciar"**:
  - `services/ai-orchestrator/orchestrator.py`: constante `_CANCEL_TOKENS`, gate nuevo antes del shipping_quote_tool. Si el cliente escribe "cancelar" (o variantes), cancela pedido `pending_payment` de la conversación y responde. Si no hay pedido activo, responde amablemente.
  - `_cancel_pending_payment_order`: busca `orders` con `status=pending_payment` por `conversation_id`, actualiza a `cancelled`. Stock no estaba decrementado (solo se decrementa en APPROVED), no hay rollback de stock necesario.

- **F4 — R-13: Persistir selección de producto al confirmar carrier**:
  - `services/ai-orchestrator/orchestrator.py`: `_find_context_product_from_history` ahora busca primero un `context_snapshot` en el historial antes de hacer text-matching.
  - Nuevo `_save_product_snapshot`: cuando carrier es confirmado por primera vez, inserta mensaje `content_type='context_snapshot'` con `payload={product_id, variation_id, quantity, unit_price_cents}` en tabla `messages`. El snapshot sobrevive reinicios del worker.
  - `_has_product_snapshot`: guard para no duplicar snapshots por conversación.

- **Pruebas de regresión**: `validate.sh` → 13/13 OK, **204 tests OK** (+20 nuevos), TypeScript OK, lint OK.

---

## Cierre de sesión anterior (2026-04-25, rev. 61)

- **Migración `20260425000000_distributed_rate_limiter.sql` aplicada en Supabase linked.**
  - Tabla `rate_limit_windows` + RPC `rate_limit_hit()` ahora operativos en DB.
  - Rate limiter distribuido activo (ya no usa fallback in-memory en producción).

- **R-11: Wompi webhook idempotencia + logging estructurado** (`services/api/routers/wompi_webhook.py`):
  - `_upsert_payment_record` retorna `bool` indicando si fue replay (txn_id ya existía).
  - Logs ahora en formato `key=value` estructurado para cada paso del flujo.
  - Replay de webhook explícitamente logeado como `pago_replay`.
  - Guards nombrados: `pago_no_aprobado`, `pago_sin_orden`, `orden_ya_confirmada`, `orden_confirmada`.

- **R-15: Refetch contacto antes de READY_FOR_SUMMARY** (`services/ai-orchestrator/orchestrator.py`):
  - Justo antes de mostrar el resumen de pedido, se hace un refetch del contacto desde DB.
  - Garantiza que nombre, email y dirección guardados en mensajes previos lleguen frescos al prompt.

- **R-18: Eliminado `NEXT_PUBLIC_API_URL` legacy**:
  - `apps/web/lib/runtime-env.ts`: eliminado fallback a `NEXT_PUBLIC_API_URL`.
  - `apps/web/next.config.js`: `apiOrigin` ahora lee solo `API_URL` (variable canónica).
  - Sin usos residuales en `apps/web/`.

- **`render.yaml`: `ANTI_HIBERNATION_ENABLED=true`** (era `false`).
  - INTERVENCION HUMANA REQUERIDA: configurar `ANTI_HIBERNATION_PING_URL` en Render Dashboard.
  - Formato: URLs de `/health` separadas por coma (api + connector + orchestrator).

- **Pruebas de regresión**: `validate.sh` → 13/13 OK, **184 tests OK**, TypeScript OK, lint OK.

---

## Cierre de sesión anterior (2026-04-25, rev. 60)

- **Cierre correctivo arquitectónico completo**:
  - `render.yaml`: eliminado duplicado `MAX_PROCESSING_ATTEMPTS` (valor "3" viejo convivía con "5" nuevo → desplegaba valor incorrecto).
  - `services/api/routers/orders.py` → `get_order`: select de `order_items` ahora incluye `variation_id` y `unit_cost` (faltaban desde que se implementó R-02).
  - `services/api/routers/contacts.py`:
    - `ContactCreate` y `ContactPatch`: agregado campo `email` (la migración `20260424300000_contacts_email.sql` añadió la columna en DB pero la API no la exponía).
    - `list_contacts`: select ahora incluye `email` y `address`; filtro de búsqueda extiende a email.
    - `create_contact`: payload incluye email normalizado (lowercase, strip).
    - Soft-delete (`delete_contact`): ahora anonimiza `email=None` (Ley 1581 Art. 15 — omisión legal corregida).
  - `services/ai-orchestrator/orchestrator.py` → `_record_consent`: revocación vía WhatsApp ahora anonimiza `email=None` (misma corrección legal que en API).
  - `services/ai-orchestrator/scratch_test.py`: eliminado archivo stale con función inexistente (`handle_incoming_message`) y tenant ID hardcodeado que no debía estar en el servicio.
  - Conteo de migraciones corregido en `docs/HANDOFF.md` y `01-state.md`: 43/45 → **49** (real).
- **Pruebas de regresión**: `validate.sh` → 13/13 OK, `184 tests OK`, TypeScript OK, lint OK.

---

## Cierre de sesión anterior (2026-04-25, rev. 59)

- **R-05 — Gate WOMPI_ENV en startup** (`services/api/main.py`):
  - `_validate_startup_config()` via FastAPI `lifespan`: si `WOMPI_ENV=production` y las llaves no comienzan con `prv_prod_`/`prod_events_`, la API falla al arrancar (`sys.exit(1)`) antes de aceptar tráfico.
  - Valida también que `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` y `SUPABASE_JWT_SECRET` estén configuradas.

- **R-07 — CONVERSATION_HISTORY_LIMIT=25** (`orchestrator.py`):
  - Default subido de 10 a 25. Evita truncamiento del historial de cotización en conversaciones medianas.

- **R-09 — Sweep de startup** (`worker.py`):
  - `_sweep_stale_messages_on_startup()`: al iniciar el worker, re-encola mensajes en `pending`/`processing` más viejos de 5 min. Cubre el caso de restart del worker (Render Free hiberna, deploy).
  - Mensajes que superaron `MAX_PROCESSING_ATTEMPTS` se marcan `failed` directamente.

- **R-10 — Anti-hibernación Render Free** (`worker.py`):
  - `_anti_hibernation_ping_if_due()`: GET periódico (cada 14 min, configurable) a las URLs en `ANTI_HIBERNATION_PING_URL`. Activado con `ANTI_HIBERNATION_ENABLED=true`.
  - Desactivado por defecto (no penaliza planes de pago ni dev local).

- **R-12 — Carrier selection con opción única** (`orchestrator.py`):
  - `_has_carrier_been_selected()` ahora detecta si el outbound de cotización mostró UNA sola opción ("¿Continuamos con la opción Económica?"). En ese caso, un "sí" / "ok" / "dale" corto cuenta como selección válida.

- **R-03 — Rate limiter distribuido** (`services/api/dependencies/security.py` + migración):
  - Tabla `rate_limit_windows` + RPC `rate_limit_hit()` en Supabase para conteo atómico cross-réplica.
  - `security.py` usa Supabase RPC como path principal; fallback automático a in-memory si la RPC falla (migración no aplicada, etc.).
  - `API_RATE_LIMIT_DISTRIBUTED=true` por defecto.
  - El worker limpia `rate_limit_windows` expiradas junto con idempotency keys.
  - Migración: `supabase/migrations/20260425000000_distributed_rate_limiter.sql`.

- **R-04 — Guard multi-tenant** (`services/api/dependencies/tenant_scope.py`):
  - Helper `scoped_table(supabase, table, tenant_id)`: aplica `.eq("tenant_id", tenant_id)` automáticamente y falla con `ValueError` si `tenant_id` está vacío.
  - `TENANT_SCOPED_TABLES`: 18 tablas críticas registradas.
  - Test `test_tenant_isolation_audit.py`: auditoría estática que verifica que los routers críticos tienen filtro de `tenant_id`.

- **Tests de regresión**:
  - `python3.11 -m unittest discover -s tests -p 'test_*.py'` → **184 tests OK**.

---

## Cierre de sesión anterior (2026-04-25, rev. 58)

- **R-01 — Job de liberación de stock expirado** (`services/ai-orchestrator/worker.py`):
  - Nuevo método `_release_expired_pending_payment_orders()` en `OrchestratorWorker`.
  - Cancela pedidos en `pending_payment` más viejos del TTL (35 min por defecto, 5 min sobre el link de 30 min).
  - Se ejecuta cada `PENDING_PAYMENT_RELEASE_INTERVAL_SECONDS` (default 10 min) en el mismo ciclo del worker.
  - Guard `eq("status", "pending_payment")` en el UPDATE evita race conditions con el webhook de Wompi.
  - Variables de entorno: `PENDING_PAYMENT_RELEASE_ENABLED`, `PENDING_PAYMENT_RELEASE_INTERVAL_SECONDS`, `PENDING_PAYMENT_TTL_MINUTES`.

- **R-02 — variation_id real en pedido conversacional** (3 archivos):
  - `tools/catalog_tool.py`: SELECT ahora incluye `id` de `products` y `product_variations`.
  - `orchestrator.py` → `_build_verified_order_context()`: retorna `product_id` y `variation_id` reales desde DB. Detecta variante del historial con label normalizado (sin puntuación). Fallback: usa variante más barata con stock si no hay mención explícita.
  - `tools/payment_link_tool.py` → `handle_payment_link_if_applicable()`: acepta `verified_ctx` opcional. Si está presente, crea ítem del pedido con `variation_id`, `product_id`, precio y cantidad reales. Si no, usa ítem genérico con warning en log.
  - Resultado: `_decrement_stock_on_confirm` ahora PUEDE decrementar stock al confirmar pago conversacional (antes siempre saltaba porque `variation_id=NULL`).

- **Tests de regresión**:
  - `python3.11 -m unittest discover -s tests -p 'test_*.py'` → **175 tests OK**.
  - `tests/test_r01_stock_release.py` (5 tests): TTL, intervalo, no-op sin pedidos, deshabilitado.
  - `tests/test_r02_variation_id.py` (6 tests): IDs en contexto, variante detectada, fallback.

---

## Cierre de sesión anterior (2026-04-25, rev. 57)

- **Inbox CxD + FSM hardening (sesión rev. 57)**:
  - **Gate no-texto**: advertencia amable en primer mensaje no-texto; solo escala a `human_takeover` si el cliente insiste. Nuevo marker `_NON_TEXT_WARNING_MARKER` en historial outbound.
  - **Gate saludo inicial**: cuando no hay outbounds previos, bot saluda con variante rotativa (4 variantes); si hay nombre con consentimiento, saluda por primer nombre ("¡Hola, Cristian!").
  - **Gate asesor explícito**: si el cliente escribe "asesor", escala directamente a `human_takeover`.
  - **Carrier selection hardening**: detección ahora busca el outbound de cotización (marker: `continuamos`) y solo acepta inbounds posteriores cortos (≤8 tokens), sin signo de pregunta. Elimina falsos positivos de preguntas sobre el carrier.
  - **Humanización de nombre — edge case**: nueva función `_try_extract_name_from_message()` extrae el nombre del mensaje del cliente cuando el LLM falla (`extracted_name=null` en estado `NEEDS_NAME`). Primero nombre en conversación, nombre completo en resumen.
  - **NEEDS_NAME state instruction**: instrucción explícita al LLM para extraer `extracted_name` obligatoriamente y usar solo primer nombre en `response_text`.
  - **READY_FOR_SUMMARY con contexto verificado**: nueva función `_build_verified_order_context()` calcula subtotal + envío + total desde catálogo DB y historial sin delegar al LLM. Bloque "CONTEXTO VERIFICADO" inyectado en state_instruction para que el LLM use valores reales, no los calcule.
  - **Payment link bounds validation**: antes de crear el link de pago, `total_in_cents` del LLM se valida contra el contexto verificado (tolerancia 5%). Si difiere, se usa el valor verificado.
  - **Smalltalk personalizado**: `_deterministic_smalltalk_response()` acepta `first_name` y `seed` para variar respuestas y personalizar con nombre del cliente.
  - **Optimización tokens (30-45%)**: catálogo condicional por estado — en `NEEDS_CONSENT/EMAIL/NAME/DIRECTION/AWAITING_ORDER_CONFIRMATION` solo se inyecta el producto en contexto (no el catálogo completo). KB omitida en estados de recolección de datos.
  - **AWAITING_ORDER_CONFIRMATION**: instrucción explícita al LLM para usar el mismo `total_in_cents` del resumen previo.
  - **Resolución temprana de tenant+contacto+historial**: movida al inicio del flow (antes de las herramientas determinísticas) para que todos los gates tengan contexto completo.
- **Pruebas de regresión ejecutadas**:
  - `python3.11 -m unittest discover -s tests -p 'test_*.py'` → **164 tests OK**.
  - `python3.11 -m py_compile services/ai-orchestrator/orchestrator.py` → **OK**.
  - `python3.11 scripts/uat/inbox_wompi_e2e_simulated.py` → **E2E simulado completo OK** (10/10 checks: saludo, cotización, carrier selection, resumen, link de pago Wompi, webhook APPROVED, idempotencia DECLINED).

---

## Historial

> Sesiones rev. ≤56, auditoría 2026-04-21 y registros de validación históricos
> están archivados en `.context/01-state-archive.md` (no leer en contexto normal).

---

## Cierre de auditoría doc/código (2026-04-21 — resumen)

- Contrato de entorno congelado (`.env.example`, `render.yaml`, docs alineados).
- Inbox Fase A/B completadas: variantes, shipping quote, order_status_tool, panel UI.
- Fase C Wompi implementada y validada en sandbox.
- Historial detallado: `.context/01-state-archive.md`.

---

## Contratos Canónicos (runtime)

> Movidos a `.context/06-contracts.md` para lectura on-demand.
> Leer cuando se toca Orchestrator, API, Connector, Worker o lógica de estados.

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

## Migraciones anteriores (2026-04-18 / 2026-04-19)

- `20260419000000` — conversation_processing_contract (estados + constraint canónico)
- `20260419000001` — rbac_operator_runtime_only (backfill agent→operator)
- `20260419000002` — meli_oauth_state_store (nonce OAuth one-time)
- `20260418000000` — marketplace_meli_variation_id
- `20260418000003` — orders_shipping_cost (columna + E2E)
- `20260418000004` — contacts_address (campo dirección JSONB)

---

## UX Mercado Libre (2026-04-20)

- `marketplace-manager.tsx`: filtros Todos/Activos/Pausados/Cerrados/Sin vincular
- Badge condición (`Nuevo`/`Usado`), filtrado combinado

---

## Validación ejecutada (resumen ejecutivo)

> Registros detallados archivados en `.context/01-state-archive.md`. No leer en contexto normal.

- Certificaciones aplicadas a las sesiones 2026-04-20 al 2026-04-25.
- Progresión de tests: 39 → 42 → 50 → 83 → 164 → **184 tests OK** (estado actual).
- Todas las migraciones del bloque 2026-04-19 / 2026-04-20 aplicadas en Supabase linked y certificadas.
- Smoke E2E Envia (sandbox/prod, DANE8): OK.
- `scripts/validate.sh` cubre Python syntax + tests + TypeScript + lint + render.yaml coherencia.
- Usar `bash scripts/validate.sh` antes de cualquier deploy a Render.

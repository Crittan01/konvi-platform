> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Dossier WhatsApp Cloud API (Meta) — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación previa antes de H.4.2 (HSM onboarding) + I.4.
**Fuente primaria**: `developers.facebook.com/docs/whatsapp/cloud-api/*` y `developers.facebook.com/documentation/business-messaging/whatsapp/*`. Cross-check con BSP públicos (Twilio, Infobip, Wati, Heltar) cuando docs Meta solo entregan navegación.
**Sin pruebas en vivo.** Toda evidencia es documental (no se enviaron mensajes reales contra graph.facebook.com en esta sesión).

> **Nota metodológica**: la documentación oficial de Meta migró su URL canónica de `/docs/whatsapp/cloud-api/` a `/documentation/business-messaging/whatsapp/`. Varias páginas devuelven solo navegación al fetch, por lo que algunos datos cuantitativos (tarifas exactas, listados completos de error codes) provienen de partners BSP con citas explícitas a Meta. Donde el dato sea third-party sin confirmación Meta, va marcado **(BSP)**.

## 1. TL;DR ejecutivo

- **Cloud API es la única API soportada hoy.** On-Premise API fue oficialmente apagada el **23-Oct-2025**: "Messages sent to or from business numbers still registered for use with On-Premises API will not be delivered". v2.53 fue el último cliente (ene-2024) y desde **1-Jul-2024** Meta ya no aceptaba nuevos sign-ups On-Premise. Cualquier consideración alternativa "on-prem" es discusión histórica.
  URL: https://developers.facebook.com/docs/whatsapp/on-premises/sunset
- **Cloud API NO es lo mismo que Marketing Messages Lite API (MM Lite).** MM Lite es producto separado lanzado **abr-2025** específico para broadcasts marketing, con deliverability ~9% mayor que Cloud API en pruebas Meta. Corre en paralelo a Cloud API; NO la reemplaza. Para nuestro caso (transactional + service + utility) Cloud API es lo correcto. URL: https://developers.facebook.com/documentation/business-messaging/whatsapp/marketing-messages/overview
- **Modelo de negocio Meta = 3 roles**:
  - **Direct (cliente final)**: el negocio gestiona su propia WABA y App Meta — mínimo viable, no escala multi-tenant.
  - **Solution Partner / BSP**: empresa certificada por Meta (Twilio, Infobip, 360dialog, Wati). Ofrece reventa con margen.
  - **Tech Provider**: ISV no-BSP que se enrola en programa Meta Tech Provider y onboardea clientes vía Embedded Signup. **Esta es la figura aplicable a Konvi Platform** — somos plataforma B2B SaaS multi-tenant, cada cliente trae su WABA pero la app de integración es la nuestra.
  URL: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/
- **Pricing model = PMP (Per-Message Pricing) desde 1-Jul-2025.** Antes era CBP (Conversation-Based, ventana 24h por categoría). Hoy se factura **por mensaje template entregado**. Categorías:
  - **MARKETING** — siempre paid.
  - **UTILITY** — paid fuera CSW; **gratis dentro de la ventana 24h** abierta por el usuario.
  - **AUTHENTICATION** — paid; tarifa AUTHENTICATION-INTERNATIONAL distinta para cross-country.
  - **SERVICE** — mensajes free-form dentro CSW; **gratis siempre dentro de CSW**, prohibido fuera.
  El "1000 free service conversations/mes" del modelo CBP **fue eliminado** con PMP.
  URL: https://developers.facebook.com/docs/whatsapp/pricing/updates-to-pricing/
- **Costo aproximado Colombia (USD/msg) tras Oct-2025**:
  - Marketing: ~$0.0125 (BSP - flowcall.co)
  - Utility: ~$0.0008 fuera CSW, $0 dentro CSW
  - Authentication: ~$0.0008
  Colombia tuvo subida de tarifas utility/auth efectiva **1-Oct-2025** (ycloud.com cita Meta directly).
  Hay **descuento por volumen**: utility + authentication tienen tiers de hasta -20% por volumen mensual.
  URL: https://www.ycloud.com/blog/whatsapp-api-pricing-update
- **Dos cambios estructurales 2026 que afectan diseño**:
  - **Q1-Q2 2026**: Meta elimina tiers 1K y 10K. Negocios verified saltan directo a **100K conversations/24h** una vez completen verification + quality path.
  - **Jun-H2 2026**: WhatsApp introduce **Usernames** + **BSUID (Business-Scoped User ID)** como identificador primario via webhook (en lugar de phone number). Implica que arquitectura `wa_id`-based debe migrar a soportar BSUID además de `wa_id` legacy.
  URL: https://developers.facebook.com/documentation/business-messaging/whatsapp/upcoming-messaging-limits-changes/

## 2. Hallazgos clave

### 2.1 Endpoints + autenticación

- **Base URL Graph API**: `https://graph.facebook.com/v{NN}.0/{PHONE_NUMBER_ID}/messages` para outbound. La versión Graph API que usamos hoy es **v21.0** (`META_API_VERSION` en `services/ai-orchestrator/whatsapp_sender.py:8` y `services/ai-orchestrator/services/meta_media.py:7`).
- **Versionado Graph API**: Meta libera nueva versión cada ~3 meses. v22.0 (ene-2025), v23.0, v24.0 (oct-2025), v25.0 (feb-2026). Cada versión tiene SLA de **~2 años** antes de deprecation. **Desde 9-Sep-2025 Meta rechaza requests a v<22.0**, por lo que **v21.0 está en su última ventana** — debemos planear upgrade a v22.0+ antes de que Meta endurezca el corte. URL: https://developers.facebook.com/docs/graph-api/changelog/versions/
- **Auth header**: `Authorization: Bearer <ACCESS_TOKEN>` + `Content-Type: application/json`. NO existe API key separada.
- **Tipos de Access Token**:
  - **Temporary user token (24h)** — solo dev/test.
  - **System User Access Token (permanente o long-lived)** — el que producción debe usar. Asignado al System User del Business Portfolio con scopes `whatsapp_business_messaging` (envío) y `whatsapp_business_management` (templates, phone numbers, webhooks).
  - **Tech Provider tokens vía Embedded Signup** — se obtienen en callback OAuth + intercambio `code` → token con `App ID` + `App Secret`. Per-tenant (uno por WABA onboardeada).
- **Ambientes**: NO hay sandbox/prod separados como Wompi. Meta ofrece **Test Phone Number gratis** asignado al desarrollador en App Dashboard — permite enviar a hasta 5 números allowlisted, gratis, para probar Cloud API sin cuenta business verified.

### 2.2 Phone Number format

- **E.164 sin "+"**: `573001234567` (no `+57 300 1234567`, no `0573001234567`). Confirmado en send-messages reference.

### 2.3 Tipos outbound disponibles

Según `developers.facebook.com/docs/whatsapp/cloud-api/reference/messages/`:
- `text` (con `preview_url` opcional para link preview)
- `image`, `audio`, `video`, `document`, `sticker` — referenciables por `id` (media uploaded a Meta) o `link` (HTTPS público).
- `location` (lat/long/name/address).
- `contacts` (vCard formato Meta).
- `interactive` con sub-tipos:
  - `button` — hasta 3 quick-reply buttons.
  - `list` — hasta 10 sections × 10 rows total.
  - `cta_url` — UN solo botón URL por mensaje (más buttons → solo el primero se envía).
  - `location_request` — botón "Send Location" (sin header/footer).
  - `flow` — Flow Messages (encuesta multi-pantalla con `flow_id`, `flow_token`, `flow_action_payload`).
  - `address_message`, `product`, `product_list` — commerce.
- `template` — único modo válido fuera de CSW. Requiere `name`, `language.code` (e.g. `es_CO`, `es_MX`, `en_US`), `components[]` con HEADER/BODY/BUTTONS hidratados.
- `reaction` — emoji a un mensaje previo `wamid`.

### 2.4 Webhook config + verification

- **GET handshake** (suscripción inicial): `?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<n>`. Si match con `META_VERIFY_TOKEN`, responder challenge en text/plain. Implementado en `services/connector-whatsapp/routers/webhook.py:14-36`.
- **POST con HMAC SHA-256**: header `X-Hub-Signature-256: sha256=<hex>` calculado con `App Secret` sobre el body raw. Implementado en `services/connector-whatsapp/dependencies/meta.py`.
- **Reglas Meta de webhook**:
  - Responder **HTTP 200 en milisegundos**, sin importar si la lógica downstream falla. Si Meta recibe 5xx o timeout, **reintenta hasta 7 días** con backoff. Tras múltiples 5xx puede **deshabilitar** la suscripción (`webhook disabled` event en App Dashboard).
  - Comentario en código (`webhook.py:81-82`): "OBLIGATORIO POLÍTICA DE META: Responder 200 de inmediato" — alineado con doc.
- **Webhook fields disponibles para suscripción** (en App Dashboard > Webhooks > WhatsApp Business Account):
  - `messages` — inbound messages + statuses (delivered/read/sent/failed).
  - `message_template_status_update` — APPROVED/REJECTED/PAUSED/DISABLED template lifecycle.
  - `message_template_quality_update` — quality rating cambios (HIGH/MEDIUM/LOW) per template.
  - `message_template_components_update` — cambios en componentes de template.
  - `account_update` — cambios a la WABA.
  - `account_review_update` — review de Meta sobre la cuenta.
  - `account_alerts` — alertas operativas.
  - `business_capability_update` — capabilities del negocio.
  - `phone_number_quality_update` — quality rating per phone number (GREEN/YELLOW/RED).
  - `security` — cambios de seguridad (2FA, login).
  - `partner_solutions` — eventos relevantes a Tech Provider.
  - `history` — sync histórico (post-Embedded Signup, opcional).
  URL: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/

### 2.5 Status webhook (delivery receipts)

`statuses[]` array con cada update:
- `id` — el `wamid` del mensaje saliente (mismo que retornó POST /messages).
- `status` — `sent` → `delivered` → `read` (read solo si destinatario tiene "read receipts" habilitado).
- `timestamp` — epoch.
- `recipient_id` — wa_id destino.
- `conversation.id`, `conversation.expiration_timestamp`, `conversation.origin.type` — `authentication`/`marketing`/`utility`/`service`/`referral_conversion` (FEPC).
- `pricing` object — **post-PMP** ahora trae `pricing_model="PMP"`, `category`, `billable: bool`, `pricing_type` (sub-field nuevo). Antes era `pricing_model="CBP"`.
- `errors[]` solo si `status=failed` con código + título + href.

> **Nota crítica de Meta** (vía Sinch): "in rare cases, the same message may trigger both success and failure message status update webhooks" — un mensaje puede llegar a `delivered` en un device del usuario y `failed` en otro (multi-device). El consumidor debe tratar el último status timestamp como verdad.
URL: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status/

## 3. Multi-tenant compatibility

### 3.1 Modelo arquitectónico Meta

- **WABA per-tenant** es **obligatorio** — Meta NO permite que múltiples negocios distintos compartan una WABA. Cada cliente B2B (tenant) debe tener su propia WABA bajo su Business Portfolio (Meta Business Manager). Modelo actual de `tenant_integrations.meta` (un set de credenciales WhatsApp per-tenant) es el correcto y único viable.
- **App Meta puede ser ÚNICA** — Konvi Platform mantiene **una sola Meta App** (App ID + App Secret) que se usa contra todas las WABAs de los tenants. Los tenants NO necesitan crear su propia Meta App.
- **System User**: cada WABA onboardeada vía Embedded Signup recibe asignación automática a un System User compartido bajo el Tech Provider. NO es un System User por tenant; es un System User del partner (nuestro), que adquiere acceso al asset del cliente (WABA, phone numbers).
- **Phone Number ID vs WABA ID**:
  - `WABA_ID` — identifica la cuenta. Necesario para crear templates, leer quality, configurar webhooks.
  - `PHONE_NUMBER_ID` — identifica el número específico dentro de una WABA. Necesario para enviar mensajes y para la URL `/{PHONE_NUMBER_ID}/messages`.
  - Una WABA puede tener múltiples phone numbers (rara vez relevante para B2B SaaS — típicamente 1 WABA = 1 número).

### 3.2 Embedded Signup (Tech Provider flow)

Flujo end-to-end para onboarding de un tenant nuevo:

1. **Frontend** (Tenant Console) carga JS SDK de Facebook Login y dispara `FB.login()` con:
   - `config_id` (Configuration ID — provisto por Meta tras aprobación del partner solution).
   - `response_type: 'code'`.
   - `override_default_response_type: true`.
   - `extras: { feature: 'whatsapp_embedded_signup', sessionInfoVersion: 3 }`.
2. **Usuario tenant** en popup Meta:
   - Crea o selecciona Business Portfolio.
   - Crea WABA o selecciona existente.
   - Verifica número (SMS o llamada) — a menos que use número Twilio en modo `only_waba_sharing`.
   - Otorga permisos `whatsapp_business_messaging` + `whatsapp_business_management` + `business_management` al partner.
3. **Callback retorna** al frontend `code` + `data` con `phone_number_id`, `waba_id`, `business_id`.
4. **Backend exchange**: `POST graph.facebook.com/v{NN}/oauth/access_token` con `client_id={APP_ID}&client_secret={APP_SECRET}&code={code}` → access token.
5. **Backend persiste** `{phone_number_id, waba_id, access_token, business_id}` en `tenant_integrations.meta` (encriptado en Vault).
6. **Webhook subscription automática** — al asignarse el WABA al partner solution, Meta auto-suscribe el webhook URL configurado en la App Meta. NO requiere `POST /{WABA_ID}/subscribed_apps` manual (a diferencia de flujo Direct Provider).

**Límites Embedded Signup**:
- Máximo **200 onboardings rolling 7 días** por partner solution. Si crece > 200/sem hay que solicitar a Meta upgrade.
- Cada `App Meta` Tech Provider permite UN solo `Solution ID` (= partner solution config).
- App debe pasar **App Review** para advanced access en `whatsapp_business_messaging` y `whatsapp_business_management` antes de activar Embedded Signup en producción (con grabación de pantalla demostrando uso).

URL: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/
URL alterna (Twilio guide cita Meta): https://www.twilio.com/docs/whatsapp/isv/tech-provider-program/integration-guide

### 3.3 Direct Provider vs Tech Provider — decisión

Hoy Konvi Platform opera en modo **Direct Provider de facto**: cada tenant manualmente:
- Crea su propia App Meta (no compartida).
- Genera su System User Token.
- Configura webhook URL del tenant.
- Entrega `phone_number_id`, `access_token` a operaciones para inserción en `tenant_integrations`.

Esto:
- Funciona para 1-5 tenants — escala horrible.
- No nos exige aprobación Tech Provider de Meta.
- Cada tenant es responsable de su App Review (fricción enorme onboarding).

Migrar a **Tech Provider + Embedded Signup** elimina la fricción y reduce onboarding de horas/días a 5-10 minutos UI-driven, pero requiere:
1. Aprobación Meta como Tech Provider (proceso documental + screen recording demo).
2. App Review única (la nuestra, no la de cada tenant).
3. Configurar Solution ID + Configuration ID en Meta App Dashboard.
4. Frontend que integre JS SDK + manejo callback.
5. Backend que intercambie code → token y persista per-tenant.

## 4. Limitaciones documentadas

### 4.1 Customer Service Window (CSW) 24h

- **Apertura**: cualquier inbound message del usuario al business reabre la ventana 24h. Click-to-WhatsApp Ad o CTA (FEPC) abre ventana **72h** equivalente para mensajes free-form (manteniéndose tras PMP, "free entry point conversations continue").
- **Dentro de CSW**: mensajes free-form (`type=text/image/...`) **gratis siempre**; templates utility **gratis también**; templates marketing/auth **paid**.
- **Fuera de CSW**: solo templates aprobados envían. Free-form devuelve **error 131047 (Re-engagement Message)** — comentado correctamente en `services/ai-orchestrator/worker.py:51-52, 638, 713-722` ("F2 (templates HSM) cubrirá el out-of-CSW").
- URL: https://developers.facebook.com/docs/whatsapp/cloud-api/conversations (página redirige a /documentation/.../pricing — verificación humana pendiente).

### 4.2 Rate limits

- **Throughput**: 80 mps default; hasta 1,000 mps tier alto para apps registradas eligibles. Excederlo → **error 130429 (Rate limit hit)** "Cloud API message throughput has been reached". (BSP Heltar)
- **App-level rate**: 200 calls/h/app/WABA default; 5,000 calls/h para WABAs activas con phone numbers registrados → **error 4 (API too many calls)**. (BSP Heltar)
- **Pair rate limit** (mismo sender → mismo recipient muchos mensajes seguidos): **error 131056** "Pair rate limit reached". (BSP Heltar)

### 4.3 Messaging tier limits (unique recipients/24h)

Estado **mayo 2026**:
- Default new WABA = **250** unique conversations/24h.
- Tiers progresivos: 1K → 10K → 100K → Unlimited.
- Upgrade automático con quality GREEN + uso real.
- **Q1-Q2 2026**: Meta elimina tiers 1K y 10K. Verified WABAs saltan directo a **100K**.
- **Desde Oct-2025**: portfolio inheritance — todos los phone numbers en el mismo Business Portfolio comparten el highest tier alcanzado por cualquiera; new numbers heredan inmediatamente.
- URL: https://developers.facebook.com/documentation/business-messaging/whatsapp/upcoming-messaging-limits-changes/

### 4.4 Quality rating

- **Per phone number** (no per WABA): GREEN (high), YELLOW (medium), RED (low), FLAGGED (suspendido).
- Calculada en últimos 7 días sobre block rate + report rate del usuario.
- RED **bloquea upgrade tier** pero ya no causa downgrade automático (cambio post-2024) "as long as no policy violations".
- FLAGGED = restricción temporal — phone number congelado hasta auto-recovery o Meta intervención.
- **Per template quality**: cada template aprobado tiene quality HIGH/MEDIUM/LOW basado en interacción → blocks. Si LOW persiste → **PAUSED** (132015) → repetidos pauses → **DISABLED** (132016) sin recuperación; toca crear template nuevo.
  URL: https://developers.facebook.com/docs/whatsapp/business-management-api/quality-rating

### 4.5 Template lifecycle (HSM)

- **Crear**: `POST /{WABA_ID}/message_templates` con `name`, `language` (e.g. `es_CO`), `category` (`MARKETING`/`UTILITY`/`AUTHENTICATION`), `components[]` con sub-tipos:
  - `HEADER` — text, image, video, document, location.
  - `BODY` — texto con `{{1}}, {{2}}` placeholders y `parameter_format: "POSITIONAL"` o `"NAMED"`.
  - `FOOTER` — texto opcional.
  - `BUTTONS` — `QUICK_REPLY`, `URL` (con dynamic URL params), `PHONE_NUMBER`, `COPY_CODE`, `CATALOG`, `MPM` (multi-product), `OTP` (autofill auth code).
- **Estados**: `PENDING` → `APPROVED` | `REJECTED`. Post-aprobación puede ir a `PAUSED` o `DISABLED` por quality.
- **Review SLA**: ~24h documentado, en práctica **15min – 48h** según partner reports. Authentication templates suelen ser instant; marketing/utility van a review humana.
- **Razones de rechazo más comunes** (Meta Business Policies):
  - Promotional content en categoría UTILITY → reject o re-categorizar a MARKETING.
  - Personal data exposure sin consentimiento.
  - Productos prohibidos (alcohol, tabaco, gambling en países restrictos, healthcare claims, weapons).
  - Templates con ALL_CAPS, emoji excessive, click-bait.
- **Post-PMP enforcement**: Meta es más estricto re-categorizando UTILITY → MARKETING si detecta upsell o promo.

### 4.6 Frequency capping (MARKETING)

- Meta limita cuántos marketing templates un usuario recibe **del ecosistema completo** en una ventana. Si excede → **error 131049** "Healthy ecosystem engagement" — Meta no entrega aunque el sender envíe correctamente.
- El cap es **adaptativo** por usuario (se ajusta según interacción previa, blocks acumulados).
- No documentado público el N exacto; BSPs reportan ~6 marketing/usuario/window.

### 4.7 Error codes principales (relevantes para nuestro código)

| Código | Significado | Acción |
|---|---|---|
| 0 | Auth exception | Renovar token system user |
| 3 | Permission/capability | Revisar scopes `whatsapp_business_*` |
| 4 | App rate limit | Backoff exponencial |
| 100 | Invalid params | Validar payload (typo en `messaging_product`, phone format) |
| 130429 | Throughput rate limit | Backoff + queue |
| 131000 | Generic error | Retry; si persiste, BSP nueva app |
| 131008 | Required param missing | Validar JSON antes de POST |
| 131009 | Invalid param value / phone not in WABA | Confirmar phone_number_id |
| 131016 | Service unavailable | Backoff; check status page |
| 131021 | Sender = recipient | Bug de routing — NO retry |
| 131026 | Message undeliverable | User no tiene WhatsApp / no aceptó ToS — bandera y skip |
| 131031 | Account locked | Intervención humana — appeal Meta Business Support |
| 131042 | Payment issue | Recargar billing — bloquea TODOS los outbound paid |
| 131045 | Cert / register issue | Re-registrar phone |
| 131047 | Re-engagement (CSW cerrado) | Usar HSM template |
| 131048 | Spam rate limit / quality drop | Pausar broadcasts; mejorar quality |
| 131049 | Frequency cap ecosystem | Skip — el usuario topa cap global, no nuestro |
| 131051 | Unsupported message type | Bug en payload type |
| 131052/053 | Media download/upload error | Validar URL HTTPS, MIME, size |
| 131056 | Pair rate limit | Backoff específico al recipient |
| 131057 | Maintenance mode | Backoff minutos |
| 132000 | Template param count mismatch | Validar componentes vs definición template |
| 132001 | Template not found / not approved / wrong language | Confirmar name + language code |
| 132005 | Hydrated text too long | Truncar variables |
| 132007 | Policy violation | Re-someter template revisado |
| 132012 | Param format mismatch | Validar tipos (date vs text) |
| 132015 | Template paused (low quality) | Esperar recovery o usar template alternativo |
| 132016 | Template disabled | **Irrecuperable** — crear template nuevo |
| 132068/069 | Flow blocked / throttled | Revisar Flow config / mejorar metrics |
| 133000 | Incomplete deregistration | Completar deregister antes |
| 133010 | Phone not registered | Registrar antes de enviar |
| 133015 | Phone recently deleted | Esperar 5+ min |
| 133016 | Register/deregister rate limit | Max 10 req/72h por número |

> Lista oficial Meta: https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes (página retorna nav; descripciones consolidadas vía Heltar 2025 BSP guide).

## 5. Lo que tenemos vs lo que ofrece la API

Auditoría contra `services/connector-whatsapp/` + `services/ai-orchestrator/whatsapp_sender.py` + `services/ai-orchestrator/services/meta_media.py`:

| Capability | Implementado | Notas |
|---|---|---|
| Outbound `text` | ✅ | `whatsapp_sender.py:89-97` con `preview_url=False`. Correcto. |
| Outbound `image` por `link` HTTPS | ✅ | `whatsapp_sender.py:70-87`. Validación HTTPS-only correcta (Meta exige). |
| Outbound `image` por `id` (media uploaded) | ❌ | NO se sube media a Meta — siempre se pasa link público. Limita imágenes a URL accesibles desde Internet. |
| Outbound `audio`, `video`, `document`, `sticker` | ❌ | No implementado. Document útil para remisiones/facturas; voice/audio para confirmaciones. |
| Outbound `location` | ❌ | No implementado. Útil para confirmar dirección entrega. |
| Outbound `contacts` | ❌ | No implementado. Útil para enviar contacto de soporte/dropshipping. |
| Outbound `interactive.button` (3 quick-reply) | ❌ | No implementado. Sería útil para "Confirmar pedido / Modificar / Cancelar". |
| Outbound `interactive.list` | ❌ | No implementado. Útil para selección de productos en catálogo limitado. |
| Outbound `interactive.cta_url` | ❌ | No implementado. Útil para "Pagar" → link Wompi. |
| Outbound `interactive.location_request` | ❌ | No implementado. Reduciría typo en direcciones. |
| Outbound `interactive.flow` | ❌ | No implementado. Más sofisticado — para encuestas de satisfacción multi-paso. |
| Outbound `template` (HSM) | ❌ | F2 pendiente — `worker.py:51-52` lo nota explícitamente. **Bloqueante para reactivación CSW cerrada**. |
| Outbound `reaction` | ❌ | No implementado. Bajo valor. |
| Outbound `commerce` (catalog/product/MPM/order) | ❌ | Fuera de roadmap por ahora. |
| Inbound webhook + HMAC SHA-256 | ✅ | `dependencies/meta.py` + `routers/webhook.py`. Correcto. |
| GET handshake `hub.challenge` | ✅ | `routers/webhook.py:14-36`. |
| 200 OK <100ms + background processing | ✅ | `routers/webhook.py:60-82` usa `BackgroundTasks` correctamente. |
| Idempotency `meta_message_id` | ✅ | Ya implementado per repo state. |
| Statuses webhook (delivered/read/sent/failed) | ⚠️ parcial | `messages` field suscrito recibe statuses, pero **no persistimos delivery state** en `messages` table — dato perdido. |
| Pricing object (PMP) en statuses | ❌ | No leemos `pricing.category` ni `pricing.billable` — sin esto no podemos imputar costo per-tenant ni reporte de gasto real Meta. |
| Conversation object | ⚠️ | Antes era único timer CSW; con PMP queda residual. Igualmente útil para tracking FEPC. |
| `message_template_status_update` field | ❌ | Field no suscrito → no nos enteramos cuando un template pasa APPROVED/REJECTED/PAUSED/DISABLED. |
| `message_template_quality_update` | ❌ | No suscrito. Sin esto no sabemos si templates degradaron quality. |
| `phone_number_quality_update` | ❌ | No suscrito → quality rating per-tenant desconocido. |
| `account_alerts` / `account_review_update` | ❌ | No suscritos. |
| STOP / opt-out detector inbound | ⚠️ parcial | "STOP detector parcial" del context. Meta NO procesa STOP automáticamente — es responsabilidad business. |
| Tier-based rate limit per-tenant | ❌ | No tracking del tier per-WABA → riesgo broadcast > tier límite. |
| Multi-WABA per-tenant | ✅ | `tenant_integrations.meta` per-tenant correcto. |
| Embedded Signup onboarding | ❌ | Onboarding manual hoy — fricción alta. F4-F11 plan futuro. |
| Graph API version | ⚠️ | v21.0 hoy, debe migrarse a v22.0+ antes de cierre Meta. |
| Marketing Messages Lite | ❌ | Fuera de scope (MM Lite es producto separado). |

## 6. Gaps críticos priorizados

### 🔴 P0 — bloquean operación o compliance

- **P0-1: STOP / opt-out detector robusto inbound.**
  Meta exige opt-out **honor inmediato**, sin embargo NO parsea palabras clave automáticamente. Es responsabilidad nuestra detectar variaciones (`STOP`, `BAJA`, `CANCELAR`, `NO MOLESTEN`, `UNSUBSCRIBE`, `BAJA AHORA`) en inbound, marcar `contact.opt_out_at`, y bloquear todo outbound posterior (excepto un confirmation message). Sin esto: violación Meta Business Messaging Policy → riesgo `account_review_update` adverso → suspensión.
  URL Meta: https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in (página redirige; política reflejada en Business Messaging Policy).
  **Esfuerzo**: 2-3 días (lista keywords ES + EN, normalización accent-insensitive, flag DB, gate outbound).

- **P0-2: Migración Graph API v21.0 → v22.0** antes que Meta corte.
  Desde 9-Sep-2025 Meta rechaza requests <v22.0. Hoy `META_API_VERSION = "v21.0"` en 2 archivos. Risk: en cualquier release de hardening Meta puede bumpar el corte. **Esfuerzo**: 0.5 día (cambiar constante + smoke test). Validar payload diff v21→v22 en changelog.
  URL: https://developers.facebook.com/docs/graph-api/changelog/version22.0/

### 🟡 P1 — cierra gaps funcionales clave del plan H.4.2 + I.4

- **P1-1: HSM Templates onboarding + send (F2).**
  Implementar:
  1. CRUD template via `POST /{WABA_ID}/message_templates`, lista via `GET /{WABA_ID}/message_templates?fields=name,status,category,language,components`.
  2. Per-tenant template registry en DB (`whatsapp_templates` table) con cache de status.
  3. `whatsapp_sender.py` extender con `send_template(tenant, to, name, language, components_params)`.
  4. Suscribir `message_template_status_update` + `message_template_quality_update`.
  5. Sembrar templates "tenant pilot" (e.g. `order_confirmation`, `order_shipped`, `payment_reminder`, `cart_abandoned_24h`) en categoría correcta — UTILITY los transaccionales, MARKETING para abandoned cart.
  **Esfuerzo H.4.2**: 11 días estimados en plan original — **se confirma rango realista**: 2d API client + 2d DB schema + 2d UI tenant template manager + 2d send_template integration + 2d webhook subs + 1d QA. Sin esto, **toda comunicación post-CSW cerrado falla con 131047** y el flujo de re-engagement (e.g. payment_reminder a las 25h) está bloqueado.

- **P1-2: Tier-based rate limit per-tenant.**
  Suscribir `phone_number_quality_update` y `account_update` para cachear tier actual per-WABA. Implementar bucket counter `outbound_24h_unique_recipients[tenant_id]` y rechazar/colar mensajes que excedan tier. Sin esto, un broadcast a 1K destinatarios desde una WABA tier-250 produce 750 errores 131048+131049 + quality drop → degrada al tenant. **Esfuerzo**: 3 días.

- **P1-3: Persistir delivery receipts en `messages` table.**
  Hoy parser ignora `statuses[]`. Agregar columnas `delivered_at`, `read_at`, `failed_at`, `failed_code`, `pricing_category`, `pricing_billable` y handler en `services/parser.py` + `db_persistence.py`. Habilita reporte de costo Meta + dashboard de delivery rate per-tenant + signal early de quality drop. **Esfuerzo**: 2 días.

### 🟢 P2 — capacidades futuras alto valor

- **P2-1: Interactive messages** — `cta_url` para link Wompi (reemplaza enviar URL en text), `button` para confirmaciones de pedido (3 opciones), `location_request` para captura de dirección. UX dramáticamente mejor. **Esfuerzo**: 4 días.

- **P2-2: Quality rating monitoring + alerting.**
  Suscribir `message_template_quality_update` + `phone_number_quality_update` y disparar alerta a operadores tenant cuando quality YELLOW/RED. Dashboard health per-tenant. **Esfuerzo**: 2 días.

- **P2-3: Document outbound** — para enviar facturas PDF post-pago, remisiones de envío. Útil pero no urgente. **Esfuerzo**: 1 día.

- **P2-4: Embedded Signup onboarding** (Tech Provider).
  Reemplazar onboarding manual. Requiere:
  1. Aplicar a Tech Provider Program Meta (paperwork).
  2. App Review producción.
  3. Frontend FB JS SDK + popup flow.
  4. Backend code → token exchange.
  5. UI tenant onboarding wizard.
  **Esfuerzo**: 8-10 días + 2-6 semanas calendar para aprobación Meta. Recomendable empezar paperwork temprano si se proyecta >5 tenants pipeline.

### ⚪ P3 — defer

- **P3-1: FEPC (Free Entry Point) via Click-to-WhatsApp Ads** — oportunidad monetización tenants (72h ventana free). Requiere integración con Meta Ads. Out of scope hoy.
- **P3-2: Commerce / Catalog / Payments** — `interactive.product`, `product_list`, `order` messages. Requiere catalog Meta sync. No alineado con stack actual (Wompi).
- **P3-3: Flows messages** — encuestas multi-pantalla. Bajo valor para B2C transaccional ahora.
- **P3-4: BSUID / Usernames migration** — H2 2026 deadline. Planificar pero no bloquear.
- **P3-5: Marketing Messages Lite (MM Lite)** — si tenant requiere broadcasts >10K/día con mejor delivery. Producto separado. Defer hasta señal de demanda real.

## 7. ¿Estamos sobre-ingeniando o sub-aprovechando?

**Sobre-ingeniería detectada**: ninguna grave. El stack mínimo (text + image + webhook HMAC + multi-tenant credentials) está alineado con MVP correcto. Validación HTTPS-only para imágenes (`whatsapp_sender.py:72-77`) es defensa adecuada — Meta v21.0+ rechaza HTTP plano de todos modos.

**Sub-aprovechamiento severo**:
- **HSM Templates** — sin ellos perdemos toda capacidad de **outbound proactivo** (recordatorios pago, abandoned cart, order shipped, etc.). En e-commerce Colombia esto es ~30-50% del valor del canal. Bloquea casos de uso enteros.
- **Interactive messages** — toda confirmación se hace con texto libre y "Sí/No" parseado. UX inferior. `cta_url` para link Wompi reduciría confusión + clicks erróneos.
- **Delivery receipts no persistidos** — ciegos a quality. No detectamos drops antes de que Meta nos restrinja.
- **Embedded Signup ausente** — barrera de onboarding por tenant.
- **Tier monitoring ausente** — riesgo no controlado de exceder tier y dañar quality.

**Decisiones arquitectónicas correctas**:
- **Multi-WABA per-tenant**: única ruta posible. Confirmado.
- **Ventana 24h CSW enforce**: NO opcional — Meta lo enforcing duro con 131047. Implementación correcta en worker.py.
- **App Meta única (Tech Provider model)**: correcto cuando migremos. Hoy estamos Direct de facto (cada tenant = su App), debemos consolidar.
- **Webhook 200 + BackgroundTasks**: correcto.
- **HMAC con App Secret**: correcto.

**Decisión Tech Provider vs Solution Partner (BSP)**:
- **Tech Provider directo a Meta** (lo que recomendamos): mantenemos control, costo Meta directo (PMP rates oficiales), no hay markup de BSP. Trade-off: paperwork Meta + nosotros somos accountable de App Review + compliance.
- **Solution Partner (Twilio/Infobip/360dialog)**: BSP intermedia, simplifica onboarding pero markup ~25-100% sobre PMP rates Meta. Para B2B SaaS escala perdemos margen real.
**Recomendación**: Tech Provider directo. Es más trabajo upfront pero económicamente óptimo a >10 tenants.

## 8. Recomendaciones priorizadas (orden de implementación)

| # | Item | Prioridad | Esfuerzo | Bloquea |
|---|---|---|---|---|
| 1 | STOP/opt-out detector robusto + DB flag | P0 | 2-3d | Compliance Meta |
| 2 | Bump Graph API v21 → v22 | P0 | 0.5d | Continuidad servicio |
| 3 | HSM Templates: API client + DB + send + UI tenant manager (H.4.2) | P1 | 11d | Re-engagement, broadcasts, F2 plan |
| 4 | Persistir delivery receipts + pricing object | P1 | 2d | Cost reporting + quality monitoring |
| 5 | Tier-based rate limiting per-tenant | P1 | 3d | Quality drop prevención |
| 6 | Suscribir webhook fields adicionales (template_status, quality_update, phone_number_quality_update) | P1 | 1d | Observability |
| 7 | Interactive `cta_url` (link pago) + `button` (confirmación) | P2 | 3-4d | UX |
| 8 | Quality rating monitoring + dashboard | P2 | 2d | Health tenant |
| 9 | Outbound `document` (facturas PDF, remisiones) | P2 | 1d | Post-venta |
| 10 | Embedded Signup Tech Provider | P2 | 8-10d + Meta approval | Onboarding scale |
| 11 | BSUID / Usernames migration | P3 (H2 2026) | 4-5d | Compliance futura |
| 12 | Flows / Commerce / MM Lite | P3 | TBD | Diferenciación futura |

**Orden de inicio sugerido**: 1 → 2 → 3 (paralelo a 4 + 6) → 5 → 7 → 8 → 9 → 10.

## 9. Validaciones humanas pendientes

**INTERVENCION HUMANA REQUERIDA**

| # | Acción | Responsable | Insumos | Criterio éxito |
|---|---|---|---|---|
| H1 | Confirmar tarifas PMP exactas Colombia post-Oct-2025 (UTILITY/MARKETING/AUTHENTICATION) directamente en Meta Business Manager > Billing > Rate Card del tenant piloto | Ops | Acceso BM tenant piloto | Snapshot rate card archivado en `docs/research/` |
| H2 | Solicitar Meta Tech Provider enrollment (paperwork: business verification, app review screen recording, demo flow) | Founder + Legal | LLC documents, App ID Meta, demo recording | Approval status "Tech Provider" en App Dashboard |
| H3 | Registrar y aprobar 2 templates piloto (`order_confirmation` UTILITY, `payment_reminder` UTILITY) en es_CO bajo WABA del tenant piloto | Ops + Tenant pilot | Phone number registered, contenido aprobado por tenant | 2 templates en estado APPROVED |
| H4 | Configurar webhook delivery_status events suscritos (`messages` con statuses + `message_template_status_update` + `phone_number_quality_update`) en App Meta | Ops | App Dashboard access | Webhook fields visibles en config + test event recibido |
| H5 | Decidir explícitamente: ¿Tech Provider directo a Meta o ir vía Solution Partner (Twilio/Infobip)? | Founder | Análisis costos (este dossier sec 7) | Decision Memo firmado |
| H6 | Verificar políticas Meta Commerce (productos prohibidos en Colombia: alcohol, tabaco, healthcare, gambling, weapons) contra catálogos de tenants pipeline | Legal + Ops | Tenant catálogos | Lista whitelist tenants compatibles |
| H7 | Configurar Business Verification + 2FA en Business Portfolio del tenant piloto | Tenant + Ops | NIT, RUT, doc legal representante | Status verified en BM |
| H8 | Aprobar política privacidad + Habeas Data referenciable desde mensajes opt-in | Legal | URL pública privacy policy | Link usable en templates |

**VALIDAR EN DOCUMENTACIÓN OFICIAL antes de cada fase**:
- Antes de migrar a v22.0: leer https://developers.facebook.com/docs/graph-api/changelog/version22.0/ (breaking changes payload).
- Antes de implementar Embedded Signup: leer https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/ + Twilio guide cross-check.
- Antes de pricing math per-tenant: leer https://developers.facebook.com/docs/whatsapp/pricing y descargar rate card.
- Antes de implementar STOP: revisar Business Messaging Policy en https://www.whatsapp.com/legal/business-policy/ para listing de causales de account restriction por opt-out abuse.

## 10. Veredicto final

**GO arquitectónico** — WhatsApp Cloud API es correcta para Konvi Platform. No hay alternativa real:
- WhatsApp Business App (no-API) no escala B2B.
- On-Premise está sunset.
- BSP intermediario nos margina costos.
- Cloud API directa nos da control + cost optimization.

**Comparativa breve con BSPs**:
- **Twilio WhatsApp**: $0.005 markup por mensaje sobre rates Meta + $0.0042/msg conversation fee adicional. Embedded Signup hosted listo. Rápido onboarding pero margen perdido.
- **Infobip / 360dialog / Wati**: rangos similares. Algunos ofrecen flat-fee pricing. Útiles si no queremos build de Tech Provider features.
- **Cloud API directa (recomendada)**: 0 markup. Pago directo a Meta vía billing del tenant en su Business Manager. Modelo "tenant trae su WABA" alinea con multi-tenant del producto.

**Estimación implementación crítica (P0+P1) total**: ~22 días-persona.
- P0 (STOP + v22): 3d.
- P1 (HSM + delivery receipts + tier limits + webhooks subs): 17d.
- Buffer QA + integración: 2d.

**Estimación H.4.2 HSM onboarding multi-tenant aislado**: **11 días confirmados** del plan original son realistas — no hay sorpresas que justifiquen inflación. Riesgos timeline:
- Meta template review SLA variable (15min – 48h) — bloquea QA E2E.
- Quality rating necesita producción real para calibrar — no se puede simular.

**Riesgos arquitectónicos persistentes (no eliminables por código)**:
- 🔴 **Template rejection arbitrario** — Meta puede rechazar template sin reason code claro; iteraciones consume time. Mitigar con BSP-style "pre-validated templates library" (templates probados aceptados que tenants reutilizan).
- 🔴 **Tier downgrade por quality drop** — un tenant con malas prácticas (broadcasts no consentidos) puede arrastrar el phone number a RED. Mitigar con tier monitoring (P1-2) + auto-pause broadcasts si quality YELLOW.
- 🟡 **Costo PMP no controlable** — Meta puede subir tarifas (caso Colombia Oct-2025). Tarifa se paga en USD desde billing del tenant en BM, así que el riesgo se transfiere al tenant — pero impacta retención.
- 🟡 **App Meta rate limits ÚNICA** — usamos una sola App para todos los tenants en Tech Provider model. Si Meta limitara la app misma (no la WABA), todos los tenants caen juntos. Mitigar con monitoring + escalation Meta Business Support.
- 🟡 **BSUID migration H2 2026** — schema cambia. Implementar columna `bsuid` paralela a `wa_id` antes de Q3 2026.

**Decisión recomendada al founder**:
1. **Esta semana**: P0-1 (STOP) + P0-2 (v22).
2. **Próximas 3 semanas**: H.4.2 HSM + delivery receipts + webhook subs adicionales (P1).
3. **Mes 2**: Tier monitoring + interactive `cta_url` + quality dashboard (P1-2 + P2-1 + P2-2).
4. **Mes 3+**: empezar paperwork Tech Provider Embedded Signup (P2-4) — calendar Meta es lo lento, no la implementación.
5. **H2 2026**: BSUID migration (P3-4).

---

## Fuentes

### Meta oficial
- [WhatsApp Cloud API — Get Started](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)
- [WhatsApp Cloud API — Send Messages](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages)
- [WhatsApp Cloud API — Messages reference](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages/)
- [Webhook reference — Status messages](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status/)
- [Webhook fields reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/)
- [Error codes (oficial)](https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes)
- [Pricing — Per-Message](https://developers.facebook.com/docs/whatsapp/pricing)
- [Pricing updates Jul-2025](https://developers.facebook.com/docs/whatsapp/pricing/updates-to-pricing/)
- [Embedded Signup — Overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/)
- [Embedded Signup — Onboarding business app users](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/)
- [Quality rating — Business Mgmt API](https://developers.facebook.com/docs/whatsapp/business-management-api/quality-rating)
- [Upcoming messaging limits changes (Q1-Q2 2026)](https://developers.facebook.com/documentation/business-messaging/whatsapp/upcoming-messaging-limits-changes/)
- [On-Premises API Sunset (Oct-23-2025)](https://developers.facebook.com/docs/whatsapp/on-premises/sunset)
- [Marketing Messages API (MM Lite)](https://developers.facebook.com/documentation/business-messaging/whatsapp/marketing-messages/overview)
- [Get Opt-in](https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in)
- [Graph API changelog v22.0](https://developers.facebook.com/docs/graph-api/changelog/version22.0/)
- [Graph API versions](https://developers.facebook.com/docs/graph-api/changelog/versions/)
- [Interactive CTA URL](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-cta-url-messages/)
- [Interactive List](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-list-messages/)
- [Tech Provider integration (Twilio guide cita Meta)](https://www.twilio.com/docs/whatsapp/isv/tech-provider-program/integration-guide)

### BSP cross-check (citan a Meta directamente)
- [Heltar — Meta Cloud API error codes 2025](https://www.heltar.com/blogs/all-meta-error-codes-explained-along-with-complete-troubleshooting-guide-2025-cm69x5e0k000710xtwup66500)
- [YCloud — Pricing Update Jul-2025 (cita Meta)](https://www.ycloud.com/blog/whatsapp-api-pricing-update)
- [Eesel.ai — Pricing/Policy changes Jul-2025](https://www.eesel.ai/blog/whatsapp-business-api-latest-pricing-and-policy-changes)
- [Chakra HQ — Pricing Updates Jul-2025](https://chakrahq.com/article/pricing-updates-for-whatsapp-business-platform-effective-july-2025-onwards/)
- [Flowcall — Country rates 2026](https://www.flowcall.co/blog/whatsapp-business-api-pricing-2026)
- [Wati — API rate limits](https://www.wati.io/en/blog/whatsapp-business-api/whatsapp-api-rate-limits/)
- [Woztell — 2026 Updates (Pacing, 100K limits, Usernames)](https://woztell.com/whatsapp-api-2026-updates-pacing-limits-usernames/)

---

# Refresh 2026-06-01 — Verificación contra docs Meta vigentes


**Disparador**: founder solicitó paso a paso para crear Meta App bajo Konvi BM. Antes de redactarlo, se verificó dossier 2026-05-05 + `meta-app-architecture-2026-05-08.md` contra docs Meta Developers vigentes (developers.facebook.com + Meta Business Help Center + Tech Provider docs). Hallazgos:


## R.1 Estado general del dossier al 2026-06-01

**Veredicto**: dossier **vigente al 90%+**. Ninguna sección requiere rewrite estructural. Todas las cifras (pricing PMP, tier limits Q1-Q2 2026, BSUID H2 2026, v22.0 cutoff Sep-2025) siguen alineadas con doc vigente.

Los items P0 siguen pendientes en código (no hubo trabajo en STOP detector ni bump v21→v22 entre 2026-05-05 y 2026-06-01):
- 🔴 **P0-1 STOP detector**: 0 progreso
- 🔴 **P0-2 Graph API v22.0**: 0 progreso (`META_API_VERSION = "v21.0"` aún en código)


## R.2 Clarificaciones añadidas por verificación 2026-06-01

### R.2.1 Path UI canónico para transferir App (App-side, NO BP-side)

El dossier no detalla este path. La fuente oficial vigente ([developers.facebook.com/docs/development/create-an-app/transfer-an-app](https://developers.facebook.com/docs/development/create-an-app/transfer-an-app/)) documenta el flujo **desde el lado de la App**, no desde el Business Portfolio:

```
developers.facebook.com → My Apps → seleccionar App (ID 819229210624423)
  → App Settings → Basic (Configuración de la app → Básica)
  → sección "Business Portfolio Ownership" (Propiedad del portfolio comercial)
  → click "+ Business Portfolio" / "+ portfolio comercial"
  → seleccionar Konvi BP del popup
  → submit (envía asset claim request al inbox "Requests/Solicitudes" del BP destino)
  → desde Konvi BP, admin acepta el request
```

**Quién puede iniciar**: usuarios con rol **admin** sobre la App.

**Acción irreversible** (cita literal Meta): *"esta acción no se puede deshacer"*. Una vez aceptado, la App es organization-owned y la cuenta personal del founder pierde rol owner.

### R.2.2 Comportamiento de App Secret + tokens post-transferencia (NO documentado por Meta)

La documentación oficial vigente **NO aborda explícitamente** qué pasa con `META_APP_SECRET`, `App ID`, ni `System User access tokens` post-transferencia. Plausibilidad alta de que se preserven (App ID es la identidad inmutable), pero **sin confirmación documental Meta**.

**Mitigación operativa obligatoria**:
1. **Smoke test E2E inmediato post-transferencia**: founder envía mensaje real a WhatsApp KAIU; bot debe responder + logs `services/connector-whatsapp` sin errores HMAC.
2. **Plan contingencia listo**: si smoke falla, rotación de `META_APP_SECRET` + `META_VERIFY_TOKEN` + per-tenant `access_token` en Vault + Render env. ~1h dev work, idempotente.

### R.2.3 Tech Provider Program — armonización con `meta-app-architecture-2026-05-08.md`

Detectada contradicción entre los dos docs canónicos del repo:

| Doc | Postura |
|---|---|
| Este dossier §1 línea 17 | "Tech Provider — **figura aplicable a Konvi Platform** — somos plataforma B2B SaaS multi-tenant" |
| `meta-app-architecture-2026-05-08.md` §3.1 | "Tech Provider Program — **No lo necesitamos** — onboarding manual funciona" |

**Veredicto verificación 2026-06-01**: ambos son ciertos en planos distintos. Armonización oficial:

| Escenario | Modelo aplicable | Tech Provider Program requerido |
|---|---|---|
| 1-5 tenants, onboarding manual founder/ops | "Direct Provider de facto" (System User token per-tenant) | ❌ NO |
| 5+ tenants, onboarding self-service UI-driven | Tech Provider + Embedded Signup | ✅ SÍ |
| Solution Partner (con línea crédito Meta + facturación directa) | Solution Partner Program | Aplicación separada |

**Confirmado por docs vigentes**:
- Embedded Signup específicamente requiere ser **Tech Provider o Solution Partner**. Fuente: [Onboarding business customers as a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider/).
- Advanced access a `whatsapp_business_management` es **required to access clients' WABAs** — sin esto, API calls retornan **error code 200** (no error 200 OK; código de error 200 dentro de Meta's error system). Aplica a ambos modelos (Direct + Tech Provider).

**Recomendación post-verificación**:
1. **Hoy y próximos 6 meses** (1-3 tenants pipeline: KAIU + Lucams + 1 potencial): Direct Provider manual. NO solicitar Tech Provider Program todavía.
2. **Cuando llegue señal demanda real ≥5 tenants self-service**: arrancar paperwork Tech Provider (proceso 2-6 semanas calendar Meta).

### R.2.4 Distinción tipos de access token (refinamiento §2.1 dossier)

Docs vigentes diferencian:

| Tipo | Uso | Rol Konvi |
|---|---|---|
| **Temporary user token (24h)** | Solo dev/test | No producción |
| **System User Access Token** (long-lived) | Producción standard. Asignado al System User del Business Portfolio del **tenant**. Scopes `whatsapp_business_messaging` + `whatsapp_business_management` | ✅ Modelo actual KAIU |
| **System User Access Token** del partner (compartido) | Solution Partners para compartir línea de crédito Meta con tenants onboardeados | ❌ NO aplica (no somos Solution Partner) |
| **Business Integration System User access token** ("business token") | Scoped a customer onboardeado individual. Usado por Tech Providers + Solution Partners post-Embedded Signup | 🟡 Futuro (post-Tech Provider enrollment) |

Esta distinción no estaba clara en §2.1 del dossier original. Modelo actual KAIU usa **System User Access Token estándar generado en el BM del tenant** — correcto.


## R.3 Items P0+P1 del dossier (estado al 2026-06-01)

| # | Item | Estado 2026-06-01 |
|---|---|---|
| P0-1 | STOP/opt-out detector | 🔴 0% — no implementado, sigue siendo bloqueante compliance |
| P0-2 | Bump Graph API v21→v22 | 🔴 0% — `META_API_VERSION = "v21.0"` aún en `whatsapp_sender.py:9` (verificado en código actual) |
| P1-1 | HSM Templates (F2 / H.4.2) | 🟡 parcial — `whatsapp_templates` table existe; `payment_reminder_v1` activo + `cart_abandoned_v1` seeded NO en cron (per `docs/research/audit-finiquito-2026-05-31.md` §1) |
| P1-2 | Tier-based rate limit per-tenant | 🔴 0% |
| P1-3 | Persistir delivery receipts | 🔴 0% |
| P1 | Suscribir webhook fields adicionales | 🔴 0% — `messages` suscrito; `message_template_status_update` + quality + phone_number_quality NO |

**Conclusión**: P0+P1 del dossier permanecen abiertos. La auditoría finiquito (2026-05-31) los mapea como items Fase A8 (Inbox refactor) y H.4.* (integraciones).


## R.4 Cross-reference con audit-finiquito-2026-05-31.md

Items del dossier mapeados a Fase A del audit finiquito:

| Dossier | Audit finiquito | Severidad |
|---|---|---|
| P0-1 STOP detector | A8 Multi-agente router + addenda §13 del audit | 🔴 CRITICAL |
| P0-2 v21→v22 bump | NO mapeado en audit — addenda recomendada | 🟡 HIGH (riesgo continuidad) |
| P1-1 HSM Templates | B2 (Plan finiquito Fase B "WhatsApp Flows Phase 1") + parte de H.4 plan K | 🟡 HIGH |
| P1-2 Tier rate limit | H.4.3 Plan K | 🟡 HIGH |
| P1-3 Delivery receipts | H.4.4 Plan K | 🟡 HIGH |
| §3.3 Tech Provider migration | A12 NUEVO (addenda §14 audit 2026-06-01) | 🔴 CRITICAL bloqueante multi-tenant |


## R.5 Fuentes verificadas en este refresh (2026-06-01)

- [Transfer Ownership — App Development with Meta](https://developers.facebook.com/docs/development/create-an-app/transfer-an-app/) — pasos transfer App
- [Create an App with Meta](https://developers.facebook.com/docs/development/create-an-app/) — creación App
- [Become a Tech Provider — WhatsApp Business Platform](https://developers.facebook.com/docs/whatsapp/solution-providers/get-started-for-tech-providers/) — Tech Provider eligibility
- [Become a Solution Partner — WhatsApp Business Platform](https://developers.facebook.com/docs/whatsapp/solution-providers/get-started-for-solution-partners/) — Solution Partner diferencias
- [Embedded Signup Overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/) — Embedded Signup flow
- [Onboarding business customers as a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider/) — multi-tenant onboarding
- [Transfer App Ownership — Meta Business Help Center](https://www.facebook.com/business/help/236817717885919) — Help Center alternative path
- [Create a Business Portfolio — Meta Business Help Center](https://www.facebook.com/business/help/1710077379203657) — crear BP
- [DIAN RUT 2026 consultation](https://dian.com.co/consultar-rut-dian-2026/) — RUT Colombia (persona natural + entidad)


## R.6 Próximo refresh sugerido

**Trigger refresh**: cualquiera de:
1. Cierre de A12 audit finiquito (transferencia App + Business Verification).
2. Cierre de P0-1 + P0-2 del dossier (STOP + v22 bump).
3. 3 meses transcurridos (próximo: 2026-09-01).
4. Cambio mayor anunciado por Meta (Embedded Signup deprecation, PMP rate hike, tier model overhaul).

Política `changelog-watch.md` aplica: re-investigar cada 3 meses WhatsApp/Meta o ante cambio mayor.
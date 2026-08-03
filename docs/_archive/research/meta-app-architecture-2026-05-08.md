> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Meta App Architecture — Konvi (modelo definitivo)

**Sesión**: 2026-05-08.
**Revisado**: 2026-06-01 — §3.1 armonizada con `whatsapp-meta-dossier-2026-05-05.md` Refresh R.2.3 tras verificación docs Meta vigentes.
**REVISIÓN MAYOR**: 2026-06-03 — Modelo **REFORMULADO** post-decisión founder. Ver §0 Adenda 2026-06-03 al final del documento. **El modelo "1 Meta App + N tenants" descrito originalmente está OBSOLETO**. Modelo final es **Direct Provider per-tenant**: cada tenant trae su propia Meta App. Konvi App actual sirve como entorno propio de Konvi Dev test, NO para servir tenants externos.
**Disparador**: founder clarificó setup actual (Meta App "Commerce Ops App" → renombrar a "Konvi App", id=`819229210624423` en cuenta personal Facebook + Business Portfolio "Kaiu Natural Living" alojando System User commerce-ops). Mi A.2 implementación inicial sobre-ingenió el lookup `app_secret` per-tenant — el modelo real es **1 Meta App + N tenants conectados**.

**Estado**: este documento es la fuente única de verdad arquitectónica. Cualquier diff entre código y este doc → re-leer y corregir código (no doc).

---

## 1. Modelo arquitectónico definitivo

```
┌─────────────────────────────────────────────────────────────┐
│  BUSINESS PORTFOLIO "Konvi"  (TARGET — a crear)      │
│  ─────────────────────────────────────────────────────────  │
│  Owner: legal entity Konvi o founder con NIT          │
│  Business Verification: ⚠️ pendiente (1-3 semanas Meta)       │
│                                                              │
│  Aloja:                                                      │
│    • Meta App "Konvi App" (id=819229210624423)       │
│      - App Secret  → META_APP_SECRET env var (global)        │
│      - Verify Token → META_VERIFY_TOKEN env var (global)     │
│      - Webhook URL: connector commerce-ops (UNA URL)         │
│      - Subscribed fields: messages, message_template_*,      │
│        phone_number_quality_update, account_alerts           │
│      - App Mode: Live (post-App Review)                      │
│    • App Review aprobado (post Business Verification):       │
│      - whatsapp_business_messaging (Advanced Access)         │
│      - whatsapp_business_management (Advanced Access)        │
│                                                              │
│  NO aloja WABAs de tenants. Cada tenant trae el suyo.        │
└─────────────────────────────────────────────────────────────┘
                        │
                        │ Meta firma webhooks con META_APP_SECRET
                        │ (mismo secret para TODOS los tenants)
                        ▼
        ┌──────────────────────────────────┐
        │  Connector commerce-ops (Render) │
        │  - Verifica HMAC con secret global│
        │  - Extrae phone_number_id        │
        │  - Lookup → tenant_id (forensics)│
        │  - Persist + dispatch eventos    │
        └──────────────────────────────────┘
            ▲              ▲              ▲
            │              │              │
   ┌────────┴───┐   ┌──────┴────┐   ┌─────┴──────┐
   │ KAIU       │   │ Tenant 2  │   │ Tenant N   │
   │ "Kaiu      │   │ "Tienda   │   │ "Marca XYZ"│
   │  Natural   │   │  Belleza" │   │            │
   │  Living"   │   │           │   │            │
   │            │   │           │   │            │
   │ WABA       │   │ WABA      │   │ WABA       │
   │ Phone Num  │   │ Phone Num │   │ Phone Num  │
   │ Token      │   │ Token     │   │ Token      │
   │ (System    │   │ (System   │   │ (System    │
   │  User      │   │  User     │   │  User      │
   │  generado  │   │  generado │   │  generado  │
   │  en SU     │   │  en SU    │   │  en SU     │
   │  Business  │   │  Business │   │  Business  │
   │  Manager)  │   │  Manager) │   │  Manager)  │
   └────────────┘   └───────────┘   └────────────┘
```

---

## 2. Estado actual vs target

| Elemento | Actual (2026-05-08) | Target | Acción |
|---|---|---|---|
| Nombre Meta App en developers.facebook.com | "Commerce Ops App" (legacy) | "Konvi App" | **Rename en developers.facebook.com** (Settings → Basic → App Display Name). 5 min. App ID `819229210624423` no cambia. |
| Meta App owner | Cuenta personal del founder | Business Portfolio "Konvi" | Migrar (30 min) |
| Business Portfolio "Konvi" | NO existe | Existe + verificado | Crear (30 min) + Business Verification (1-3 sem Meta) |
| Business Portfolio "Kaiu Natural Living" | Existe + aloja KAIU + System User commerce-ops | Existe + aloja sólo KAIU (tenant) | Mover System User commerce-ops a Konvi portfolio? **Innecesario** — el System User es del tenant, queda en SU Business Portfolio (Kaiu Natural Living es el tenant) |
| App Mode | Development | Live | Toggle post-App Review |
| App Review whatsapp_business_messaging | Standard Access (limitado) | Advanced Access | Submit post Business Verification (1-2 sem Meta) |
| `META_APP_SECRET` (Render) | ✅ presente en konvi-connector | ✅ idem | Sin cambio |
| `META_VERIFY_TOKEN` (Render) | ✅ presente | ✅ idem | Sin cambio |
| KAIU `tenant_integrations.credentials.waba_id` | ⚠️ NULL → ✅ corregido a `2159052118202272` (2026-05-08 C5) | ✅ presente | UPDATE aplicado |
| KAIU `tenant_integrations.credentials.access_token_secret_id` | ✅ Vault | ✅ idem | Sin cambio |

---

## 3. Por qué este modelo (justificación)

### 3.1 Tech Provider Program — armonización 2026-06-01

> ⚠️ **Sección revisada 2026-06-01** tras verificación contra docs vigentes Meta + cross-check con `whatsapp-meta-dossier-2026-05-05.md` §1 y §3.3. La versión original ("No lo necesitamos") era impresa por simplificación. La versión armonizada distingue por escala:

Confusion común: "necesitamos ser partner de Meta para multi-tenant".

**Respuesta matizada por escala**:

| Escenario | Modelo aplicable | Tech Provider Program |
|---|---|---|
| **1-5 tenants** onboarding manual (founder/ops genera System User token) | "Direct Provider de facto" | ❌ NO requerido |
| **5+ tenants** con onboarding self-service UI (Embedded Signup) | Tech Provider + Embedded Signup | ✅ SÍ requerido |
| Solution Partner (línea crédito Meta + facturación directa a clientes) | Solution Partner Program | Aplicación separada |

**Hoy KAIU** (único tenant) → modelo Direct Provider funcional sin Tech Provider Program.

**Cuando Konvi escale a 5+ tenants**: Tech Provider Program necesario para Embedded Signup. Proceso 2-6 semanas calendar Meta. Iniciar paperwork cuando exista pipeline real ≥3 tenants.

**Lo que SÍ necesitamos HOY** (independiente del escenario):
- Business Portfolio "Konvi" verificado (Business Verification — proceso estándar, gratis, 1-3 semanas Meta).
- App Review para Advanced Access en `whatsapp_business_messaging` + `whatsapp_business_management` (proceso estándar, gratis, 1-2 semanas Meta). **`whatsapp_business_management` con Advanced access es required para acceder WABAs no-owned por nuestro BM** — confirmado en docs vigentes ([Embedded Signup onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider/)).

Con esos dos pasos, Konvi puede operar 1 App + N tenants (manual hoy, Embedded Signup futuro).

**Fuente para detalle Tech Provider eligibility + Embedded Signup**: ver `whatsapp-meta-dossier-2026-05-05.md` §3.2 y §3.3 (versión refresh 2026-06-01 R.2.3).

### 3.2 Per-tenant vs global — tabla de decisión

| Concepto | Per-tenant | Razón |
|---|---|---|
| `App Secret` | ❌ Global | Es de NUESTRA App. Todos los webhooks de todos los tenants se firman con el mismo. |
| `Verify Token` | ❌ Global | Una sola URL webhook configurada en developers.facebook.com → un solo verify_token. |
| `App ID` | ❌ Global | Ídem App Secret. Público de todos modos. |
| `phone_number_id` | ✅ Per-tenant | Cada tenant tiene su WhatsApp Business Phone Number. |
| `waba_id` | ✅ Per-tenant | Cada tenant tiene su WhatsApp Business Account. |
| `access_token` | ✅ Per-tenant | System User token generado por el tenant en SU Business Manager. Otorga permisos sobre SU WABA exclusivamente. |
| `tier` (1K/10K/100K) | ✅ Per-tenant | Meta calcula quality + tier por WABA, independientemente. |
| Webhook subscriptions | ❌ Global | Configuradas en NUESTRA App una vez (messages, template_status_update, etc.). Aplican a todos los tenants. |

### 3.3 Compliance Meta Business Messaging Policy

Aplica per-WABA. Cada tenant es responsable de su contenido. La plataforma:
- Implementa STOP detector global (rev. 105 H.4.1) — opt-out automático.
- Provee compliance decoradores para template approval (F2).
- NO interpone contenido entre tenant y Meta — sólo es transport.

Habeas Data Ley 1581 Colombia: cada tenant es Responsable del Tratamiento de sus contactos. Konvi actúa como Encargado. Audit log + consent storage per-tenant.

---

## 4. Multi-canal Meta (Instagram, Messenger) — extensión natural

Mismo modelo. La Meta App de Konvi puede tener varios productos habilitados:
- WhatsApp Cloud API (hoy)
- Instagram Direct Messaging (futuro)
- Messenger Platform (futuro)

Cada tenant nuevo agregaría a su Business Manager:
- `instagram_user_id` + `instagram_access_token` (provider='instagram' en `tenant_integrations`)
- `page_id` + `page_access_token` (provider='messenger')

**Webhook URL** sigue siendo única (la nuestra). Multiplex:
- `object = "whatsapp_business_account"` → flow WhatsApp
- `object = "instagram"` → flow Instagram
- `object = "page"` → flow Messenger (FB)

**HMAC** con el mismo `META_APP_SECRET` global.

---

## 5. Trámites humanos pendientes (founder)

Ver checklist accionable en [`docs/onboarding/H1-H5-checklist.md`](../onboarding/H1-H5-checklist.md).

| # | Trámite | Quién | Tiempo estimado |
|---|---|---|---|
| H1 | Decidir nombre platform (no necesariamente "Konvi") | Founder | Sesión aparte |
| H2.1 | Crear Business Portfolio platform en business.facebook.com | Founder | 30 min |
| H2.2 | Transferir Meta App `819229210624423` del personal al nuevo Business Portfolio | Founder | 5 min |
| H3 | Iniciar Business Verification del nuevo Business Portfolio | Founder + docs | 1-3 semanas Meta |
| H4 | Submit App Review post Business Verification | Founder + screencast demo | 1-2 semanas Meta |

**Mientras tanto**: KAIU sigue funcionando en Development Mode (válido hasta 5 testers — incluyendo al founder). H1-H4 no bloquean desarrollo de código.

---

## 6. Implicaciones para código (post-clarificación)

### Hecho 2026-05-08 (commit pendiente):

- ✅ `services/connector-whatsapp/dependencies/meta.py` simplificado:
  - Removido lookup per-tenant del `app_secret` (era over-engineering).
  - Mantiene lookup `phone_number_id → tenant_id` para FORENSICS.
  - HMAC verify usa `META_APP_SECRET` global directo. 503 si no configurado.
- ✅ `.context/06-contracts.md` §7 reescrito reflejando 1 App + N tenants.
- ✅ Tests actualizados (HmacGlobalTests + TenantResolutionForensicsTests).
- ✅ KAIU `waba_id = 2159052118202272` agregado a credentials (UPDATE C5).

### Pendiente F2 HSM (Sem 7):

- `MetaBusinessManagementClient` extiende F.2 → `POST /{WABA_ID}/message_templates`.
- DB schema `whatsapp_templates` per-tenant.
- Suscripción `message_template_status_update` + handler DB persistence (parser dispatcher ya emite el evento).
- UI Tenant Console: template manager.

---

**Branch**: `phase-0-pre-prod`.
**Próxima sesión**: leer este doc + `docs/onboarding/whatsapp-tenant-setup.md` + `docs/onboarding/H1-H5-checklist.md` antes de tocar código Meta.


---


# §0 ADENDA 2026-06-03 — Reformulación arquitectónica MAYOR

> **Crossref (Rev. 110 2026-06-22)**: esta ADENDA fue **formalizada como ADR canónico** en
> [`docs/adr/0023-meta-model-b-direct-provider-per-tenant.md`](../adr/0023-meta-model-b-direct-provider-per-tenant.md).
> Para decisiones, plan de implementación, status Phases 1-8 y Q1-Q10 sealed, leer el ADR-0023.
> Esta sección queda como dossier histórico del razonamiento + topología técnica.

**Disparador**: founder identificó que el botón de Meta dashboard ofrecía dos opciones — "Integrate with API" (que YA HABÍA elegido) y "Become a Partner". Esto reveló que el modelo "1 App Konvi + N tenants" original asumía que Konvi sería Partner (Tech Provider Program). Founder eligió explícitamente NO ser Partner.


## Decisión arquitectónica definitiva

**Konvi NUNCA será Partner Meta**. Konvi clickeó "Integrate with API" en Meta dashboard. Modelo correcto = **Direct Provider per-tenant**: cada tenant trae su propia Meta App + WABA + Phone Number + System User token. Konvi connector es infraestructura multi-tenant que enruta webhooks y orquesta API calls.


## Topología revisada

```
KONVI CONSOLE (la plataforma)
├── Konvi BP (propio, ID 2046090036314027)
│   └── Konvi App (ID 819229210624423)
│       └── Test Phone + Test WABA (asignados Meta auto)
│       └── Usado por "Konvi Dev" tenant interno
│
├── Backend FastAPI + Connector multi-tenant
│   ├── Per-tenant app_secret en Vault (NO env global)
│   ├── Per-tenant webhook URL: /webhook/{tenant_id}
│   └── HMAC validation con secret per-tenant lookup
│
└── Tenant Console UI (igual que Wompi/Aveonline)
    └── Tenant ingresa SUS credentials: app_id, app_secret, verify_token, phone_number_id, waba_id, access_token

TENANT 1 — KAIU (1er tenant productivo)
├── Kaiu BP (propio)
│   └── KAIU Chat App (ID 2024793711712790, su propia App)
│       ├── WABA 2159052118202272 (su propia)
│       ├── Phone Number 990364080831295 (su propio)
│       └── System User commerce-ops (su propio)

TENANT N (futuro Lucams, etc.)
├── Tenant BP (propio)
│   └── Su propia Meta App
│       ├── WABA propia
│       ├── Phone Number propio
│       └── System User propio
```

Cada tenant clickea **"Integrate with API"** en SU PROPIO Meta dashboard (no "Become a Partner").


## Lo que cambia respecto §3.1 original

Original §3.1 decía: "1-5 tenants onboarding manual con System User token → Tech Provider Program NO requerido para Direct de facto".

**Refinamiento 2026-06-03**: el "Direct de facto" SIN partner business assignment significa que **cada tenant debe tener su PROPIA Meta App** (no usar Konvi App). Esto es porque sin Tech Provider OR partner assignment, el System User del tenant no puede autorizar Konvi App a usar SU WABA. La única alternativa viable sin paperwork Meta es Direct Provider per tenant.

El modelo "1 App Konvi + N tenants compartiendo Konvi App" del §3.2 original SOLO funciona con Tech Provider Program enrolado + Embedded Signup. Sin eso, requiere partner business assignment (que falla con BPs sin BV approved).

**Por eso la decisión final 2026-06-03 es Direct Provider per-tenant**: arquitectónicamente factible HOY sin paperwork Meta, consistente con cómo Konvi maneja Wompi/Aveonline/Telegram.


## Cambios concretos a hacer

### Refactor connector code (~1-2 días dev)

- `services/connector-whatsapp/dependencies/meta.py`:
  - Eliminar `META_APP_SECRET = os.getenv(...)` global env-var
  - Nueva función `_get_tenant_app_secret(tenant_id) -> str`: lookup `tenant_integrations.meta.app_secret_secret_id` → Vault `resolve_secret`
  - HMAC validation usa secret per-tenant
- `services/connector-whatsapp/routers/webhook.py`:
  - Endpoint path: `/api/v1/whatsapp/webhook/{tenant_id}`
  - Extraer tenant_id del URL path (routing seguro sin chicken-and-egg HMAC)
- Schema `tenant_integrations.meta` whatsapp:
  - `app_id` (string, Meta App ID del tenant)
  - `app_secret_secret_id` (UUID Vault, encrypted)
  - `verify_token` (string, configurable per-tenant)
  - `phone_number_id`, `waba_id`, `access_token_secret_id` (igual que ya está)

### Schema migration

```sql
-- No schema change required (credentials es JSONB)
-- Solo aplicar nuevo shape:
UPDATE tenant_integrations
SET credentials = jsonb_set(
  jsonb_set(credentials, '{app_id}', '"2024793711712790"'),  -- KAIU Chat App ID
  '{verify_token}', '"konvi-kaiu-direct-2026"'
)
WHERE tenant_id = '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9'
  AND provider = 'whatsapp';
```

### Producción real

Para que tenants tengan webhook URL estable (no ngrok rotando):
- Reactivar Render Starter para connector (~$7/mes)
- Cloudflare DNS: CNAME `api.konvi.co` → Render endpoint
- Tenants configuran webhook a `https://api.konvi.co/api/v1/whatsapp/webhook/{tenant_id}` (permanente)
- mTLS automático (Cloudflare Full Strict ya configured)


## Lo que se DESCARTA en este nuevo modelo

- Tech Provider Program enrollment ❌
- Embedded Signup implementation ❌
- Konvi BP Business Verification para servir tenants ❌ (solo necesario si Konvi quiere su propio Live mode test)
- Partner business assignment Kaiu BP ↔ Konvi BP ❌
- Modelo §3.2 "Embedded Signup (Tech Provider flow)" ❌
- Modelo §3.3 párrafo "Migrar a Tech Provider + Embedded Signup" ❌


## Trade-offs aceptados conscientemente

| Pro Direct Provider per-tenant | Con Direct Provider per-tenant |
|---|---|
| Konvi nunca paperwork Meta Tech Provider | Cada tenant pasa SU OWN BV + App Review (1-3 sem + 1-2 sem Meta) |
| Consistente con Wompi/Aveonline/Telegram | Onboarding tenant más manual (10-12 pasos) |
| Cada tenant 100% independiente | Konvi blind a cambios config tenant en Meta |
| 0 dependencia Meta Partner Program | Custodia App Secret cliente-Konvi requiere DPA escrito |
| No SPOF Tech Provider enrollment | Multi-secret HMAC en connector (refactor real) |

Founder acepta estos trade-offs conscientemente sesión 2026-06-03.


## Referencias

- Workflow profundo 2026-06-03 verificación Model B feasibility (8 agents) — output guardado en `/tmp/claude-1000/.../tasks/wyoyzacnz.output`
- Memoria `feedback_konvi_not_partner_direct_provider.md` — regla operativa
- Memoria `project_meta_app_ownership.md` — estado actual assets Meta
- Audit `audit-finiquito-2026-05-31.md §14b` — plan ejecutable actualizado
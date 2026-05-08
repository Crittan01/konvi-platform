# Meta App Architecture — Commerce Ops (modelo definitivo)

**Sesión**: 2026-05-08.
**Disparador**: founder clarificó setup actual (Meta App "Commerce Ops App" id=`819229210624423` en cuenta personal Facebook + Business Portfolio "Kaiu Natural Living" alojando System User commerce-ops). Mi A.2 implementación inicial sobre-ingenió el lookup `app_secret` per-tenant — el modelo real es **1 Meta App + N tenants conectados**.

**Estado**: este documento es la fuente única de verdad arquitectónica. Cualquier diff entre código y este doc → re-leer y corregir código (no doc).

---

## 1. Modelo arquitectónico definitivo

```
┌─────────────────────────────────────────────────────────────┐
│  BUSINESS PORTFOLIO "Commerce Ops"  (TARGET — a crear)      │
│  ─────────────────────────────────────────────────────────  │
│  Owner: legal entity Commerce Ops o founder con NIT          │
│  Business Verification: ⚠️ pendiente (1-3 semanas Meta)       │
│                                                              │
│  Aloja:                                                      │
│    • Meta App "Commerce Ops App" (id=819229210624423)       │
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
| Meta App owner | Cuenta personal del founder | Business Portfolio "Commerce Ops" | Migrar (30 min) |
| Business Portfolio "Commerce Ops" | NO existe | Existe + verificado | Crear (30 min) + Business Verification (1-3 sem Meta) |
| Business Portfolio "Kaiu Natural Living" | Existe + aloja KAIU + System User commerce-ops | Existe + aloja sólo KAIU (tenant) | Mover System User commerce-ops a Commerce Ops portfolio? **Innecesario** — el System User es del tenant, queda en SU Business Portfolio (Kaiu Natural Living es el tenant) |
| App Mode | Development | Live | Toggle post-App Review |
| App Review whatsapp_business_messaging | Standard Access (limitado) | Advanced Access | Submit post Business Verification (1-2 sem Meta) |
| `META_APP_SECRET` (Render) | ✅ presente en commerce-ops-connector | ✅ idem | Sin cambio |
| `META_VERIFY_TOKEN` (Render) | ✅ presente | ✅ idem | Sin cambio |
| KAIU `tenant_integrations.credentials.waba_id` | ⚠️ NULL → ✅ corregido a `2159052118202272` (2026-05-08 C5) | ✅ presente | UPDATE aplicado |
| KAIU `tenant_integrations.credentials.access_token_secret_id` | ✅ Vault | ✅ idem | Sin cambio |

---

## 3. Por qué este modelo (justificación)

### 3.1 No requiere Tech Provider Program / Solution Partner

Confusion común: "necesitamos ser partner de Meta para multi-tenant". **Falso**.

- **Tech Provider Program** = barrera alta, paperwork, App Review especializada. Beneficios: Embedded Signup automatizado para onboarding tenants. **No lo necesitamos** — onboarding manual funciona.
- **Solution Partner Program** = programa comercial Meta, otra cosa. **Tampoco lo necesitamos**.
- **Lo que SÍ necesitamos**:
  - Business Portfolio verificado (Business Verification — proceso estándar, gratis).
  - App Review para Advanced Access (proceso estándar, gratis).

Con esos dos pasos, cualquiera puede operar 1 App + N tenants sin ser partner.

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

Habeas Data Ley 1581 Colombia: cada tenant es Responsable del Tratamiento de sus contactos. Commerce Ops actúa como Encargado. Audit log + consent storage per-tenant.

---

## 4. Multi-canal Meta (Instagram, Messenger) — extensión natural

Mismo modelo. La Meta App de Commerce Ops puede tener varios productos habilitados:
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
| H1 | Decidir nombre platform (no necesariamente "Commerce Ops") | Founder | Sesión aparte |
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

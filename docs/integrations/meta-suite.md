# Meta Suite — Arquitectura de Integración Unificada

Última actualización: 2026-04-16

**Fuentes oficiales verificadas:**
- [Meta Embedded Signup Overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/)
- [Become a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers)
- [Solution Providers Overview](https://developers.facebook.com/docs/whatsapp/solution-providers/)
- [Instagram Platform Overview](https://developers.facebook.com/docs/instagram-platform/overview/)
- [Business Login for Instagram](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-login-for-instagram/)
- [Meta Webhooks for Messenger](https://developers.facebook.com/docs/messenger-platform/webhooks)

---

## Decisión arquitectónica (OQ-W01, OQ-W02)

**Modelo:** Meta Embedded Signup — cada tenant conecta su propia cuenta Meta.
**Rol de la plataforma:** Tech Provider (no Solution Partner).
**Canal inicial:** WhatsApp. Messenger e Instagram son canales adicionales activables por tenant.

**Por qué Tech Provider y no Solution Partner:**
- Los tenants pagan a Meta directamente por uso de la API (mensajes).
- La plataforma cobra por el SaaS (mensualidad), no por mensajes individuales.
- Solution Partner requiere crédito extendido y ser Meta Business Partner — proceso más largo y modelo de billing diferente.
- Tech Provider permite onboarding completo vía Embedded Signup con los mismos permisos técnicos.

---

## Los tres canales Meta

| Canal | API base | Caso de uso | Disponibilidad |
|-------|----------|-------------|----------------|
| **WhatsApp Business** | Cloud API v21+ | Ventas conversacionales (canal principal) | Fase actual |
| **Messenger** | Graph API + Messenger Platform | Atención via Facebook Page | Futuro — mismo OAuth |
| **Instagram DMs** | Graph API + Instagram Messaging | Ventas via Instagram Business | Futuro — mismo OAuth |

Los tres comparten la misma Meta App y el mismo flujo de autorización (Meta Business Login / Embedded Signup). El tenant conecta una vez su Meta Business Account y puede activar canales adicionales sin re-autenticarse.

---

## Arquitectura de datos

### `tenant_integrations` — registro unificado Meta

```json
{
  "tenant_id": "uuid",
  "provider": "meta",
  "status": "connected",
  "credentials": {
    "access_token": "EAAxxxxxxx",
    "token_type": "system_user",
    "expires_at": null
  },
  "meta": {
    "business_id": "123456789",
    "whatsapp": {
      "waba_id": "987654321",
      "phone_number_id": "111222333",
      "display_phone": "+57 321 000 0000",
      "verified_name": "Mi Tienda"
    },
    "messenger": {
      "page_id": "444555666",
      "page_name": "Mi Tienda FB"
    },
    "instagram": {
      "ig_business_id": "777888999",
      "username": "@mitienda"
    }
  }
}
```

### Migración desde modelo actual

El campo `tenants.meta_waba_id` es **legacy**. Al implementar Embedded Signup:
1. Los nuevos tenants se onboardean directo a `tenant_integrations` con `provider='meta'`.
2. Los tenants existentes migran: se crea su registro en `tenant_integrations` con los datos ya en `meta_waba_id`.
3. El campo `meta_waba_id` queda deprecado pero no se elimina hasta que todos los tenants hayan migrado.
4. El connector-whatsapp resuelve el tenant buscando primero en `tenant_integrations`, luego fallback a `meta_waba_id`.

---

## Flujo de autorización (Embedded Signup)

### Diagrama

```
Tenant (owner) en Integraciones
        ↓
[Botón: Conectar con Meta]
        ↓
  Meta Business Login popup (OAuth)
  ├── Autenticar con Facebook
  ├── Seleccionar Meta Business Account
  ├── Crear o seleccionar WABA
  ├── Verificar número de teléfono (OTP)
  └── Autorizar permisos a la plataforma
        ↓
  Meta redirige a: /api/v1/integrations/meta/callback
  con: ?code=AUTH_CODE&state=TENANT_ID_BASE64
        ↓
  Backend (FastAPI):
  1. Valida state → extrae tenant_id
  2. POST a Graph API → intercambia code por access_token
  3. GET /me?fields=id,name,whatsapp_business_accounts → obtiene waba_id
  4. Registra phone number → POST /{waba_id}/phone_numbers
  5. Suscribe webhook → POST /{waba_id}/subscribed_apps
  6. Guarda en tenant_integrations
        ↓
  Redirect a: /dashboard/integrations?connected=meta
```

### Permisos OAuth requeridos por canal

**WhatsApp (obligatorio):**
```
whatsapp_business_management
whatsapp_business_messaging
```

**Messenger (cuando se active):**
```
pages_messaging
pages_show_list
pages_manage_metadata
```

**Instagram DMs (cuando se active):**
```
instagram_manage_messages
instagram_basic
pages_show_list
pages_manage_metadata
```

**Nota:** Solicitar todos los permisos desde el inicio en App Review, aunque los canales se activen progresivamente. Cambiar permisos después requiere nueva revisión de Meta.

---

## Arquitectura de webhooks

### Endpoint unificado

Un único endpoint recibe eventos de todos los canales Meta:

```
POST https://konvi-connector.onrender.com/api/v1/meta/webhook
```

El conector rutea por canal según el campo del payload:

```python
def route_meta_webhook(payload: dict):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = change.get("field")
            if field == "messages":
                # WhatsApp Cloud API
                handle_whatsapp_message(entry, change)
            elif field == "messaging":
                # Messenger Platform
                handle_messenger_message(entry, change)
            elif field == "instagram_messages":
                # Instagram Messaging
                handle_instagram_message(entry, change)
```

### Resolución de tenant desde webhook

```python
# WhatsApp: resolver por phone_number_id o waba_id
def resolve_tenant_whatsapp(phone_number_id: str):
    return supabase.table("tenant_integrations") \
        .select("tenant_id") \
        .eq("provider", "meta") \
        .contains("meta", {"whatsapp": {"phone_number_id": phone_number_id}}) \
        .single().execute()

# Messenger: resolver por page_id
def resolve_tenant_messenger(page_id: str):
    return supabase.table("tenant_integrations") \
        .select("tenant_id") \
        .eq("provider", "meta") \
        .contains("meta", {"messenger": {"page_id": page_id}}) \
        .single().execute()
```

---

## Responsabilidades: plataforma vs tenant

| Tarea | Quién | Frecuencia | Notas |
|-------|-------|------------|-------|
| Crear Meta App | Plataforma | Una vez | IH-META-01 |
| Verificar Meta Business | Plataforma | Una vez | IH-META-01 |
| App Review (permisos avanzados) | Plataforma | Una vez (y en cambios) | IH-META-01 |
| Configurar Embedded Signup | Plataforma | Una vez | IH-META-01 |
| Registrar webhook URL | Plataforma | Una vez por URL | Automático con Render |
| Conectar WhatsApp Business | **Tenant** | Por tenant | Self-serve via UI |
| Verificar número de teléfono | **Tenant** | Por número | Durante Embedded Signup |
| Activar Messenger/Instagram | **Tenant** | Opcional | Self-serve via UI |
| Renovar tokens | Plataforma | Automático | System User token = sin expiración |

---

## IH-META-01 — Convertirse en Tech Provider de Meta

> **INTERVENCIÓN HUMANA REQUERIDA**
> **RESPONSABLE:** Operador de plataforma (dueño del negocio SaaS)
> **DURACIÓN ESTIMADA:** 3-10 días hábiles (depende de la revisión de Meta)
> **PRERREQUISITO PARA:** Embedded Signup, onboarding self-serve de tenants

### PASO 1 — Preparar cuenta de Facebook y Meta Business

**Qué necesitas antes de empezar:**
- Una cuenta de Facebook personal activa (necesaria para crear la Meta Business Account).
- Un dominio de negocio (ej: `commerceops.co`) — necesario para la verificación.
- Acceso al DNS del dominio para verificar ownership.

**Pasos:**
1. Ve a [business.facebook.com](https://business.facebook.com).
2. Si no tienes una Meta Business Account, haz clic en **"Crear cuenta"**.
3. Ingresa el nombre de tu negocio (ej: "Konvi"), tu nombre, y tu email corporativo.
4. Verifica el email que Meta te envíe.

---

### PASO 2 — Verificar el negocio con Meta

La verificación es obligatoria para obtener acceso avanzado a las APIs.

1. En Meta Business Suite → **Configuración del negocio** → panel izquierdo → **"Verificación del negocio"**.
2. Haz clic en **"Iniciar verificación"**.
3. Completa los datos:
   - Nombre legal del negocio
   - Dirección física
   - Número de teléfono del negocio
   - Sitio web (`https://commerceops.co`)
4. Meta puede pedir documentos de respaldo:
   - Certificado de Cámara de Comercio, o
   - Estado de cuenta bancario con nombre del negocio, o
   - Carta tributaria / NIT
5. Sube los documentos en formato PDF o imagen nítida.
6. Espera la confirmación de Meta (usualmente 1-5 días hábiles).

**Cómo saber que pasó:** El panel de verificación mostrará una palomita verde y el badge "Negocio verificado".

---

### PASO 3 — Crear la Meta App

1. Ve a [developers.facebook.com/apps](https://developers.facebook.com/apps).
2. Haz clic en **"Crear app"**.
3. Selecciona el tipo: **"Empresa"** (Business).
4. Nombre de la app: `Konvi Platform` (este nombre lo ven los tenants en el popup de autorización).
5. Email de contacto del desarrollador: tu email.
6. Asociar al Meta Business Account que verificaste en el PASO 2.
7. Haz clic en **"Crear app"**.

---

### PASO 4 — Agregar productos a la App

Dentro del Dashboard de tu App en developers.facebook.com:

**Agregar WhatsApp:**
1. Panel izquierdo → **"Agregar producto"** → busca **"WhatsApp"** → clic en "Configurar".
2. Selecciona tu Meta Business Account.
3. Esto crea un WABA de prueba para desarrollo.

**Agregar Messenger (para el futuro):**
1. Panel izquierdo → **"Agregar producto"** → busca **"Messenger"** → clic en "Configurar".
2. Conecta una Facebook Page de prueba.

**Agregar Instagram (para el futuro):**
1. Panel izquierdo → **"Agregar producto"** → busca **"Instagram"** → clic en "Configurar".

---

### PASO 5 — Configurar Embedded Signup

1. En el panel de tu App → **WhatsApp** → **"Embedded Signup"**.
2. Activa **"Enable Embedded Signup"**.
3. Configura la URL de redirección (donde Meta redirige al tenant tras autorizar):
   ```
   https://konvi-api.onrender.com/api/v1/integrations/meta/callback
   ```
4. Guarda los cambios.

**Variables de entorno que debes agregar a Render (konvi-api):**
```
META_APP_ID=<ID de la app — visible en el Dashboard>
META_APP_SECRET=<App Secret — Settings > Basic > App Secret>
META_EMBEDDED_SIGNUP_CONFIG_ID=<Flow Config ID — aparece en la sección Embedded Signup>
```

---

### PASO 6 — Solicitar App Review (acceso avanzado)

Este paso es el que puede tardar más. Es la revisión de Meta para aprobar el uso de las APIs en producción.

1. En tu App → panel izquierdo → **"App Review"** → **"Permisos y funciones"**.

2. Solicita **Advanced Access** para cada permiso:

   | Permiso | Para qué | Estado inicial |
   |---------|----------|----------------|
   | `whatsapp_business_management` | Gestionar WABAs de clientes | Standard Access → solicitar Advanced |
   | `whatsapp_business_messaging` | Enviar/recibir mensajes WhatsApp | Standard Access → solicitar Advanced |
   | `pages_messaging` | Mensajes por Messenger | — → solicitar |
   | `instagram_manage_messages` | DMs por Instagram | — → solicitar |
   | `instagram_basic` | Datos básicos de cuenta IG | — → solicitar |

3. Para cada permiso, Meta pedirá:
   - **Descripción** de cómo lo usas (en inglés): sé específico. Ejemplo para `whatsapp_business_messaging`: *"Our SaaS platform enables small e-commerce businesses to manage customer conversations via WhatsApp. We use this permission to send and receive messages on behalf of our business clients, who connect their own WhatsApp Business Accounts through Embedded Signup."*
   - **Video de demostración** (screencast): graba tu pantalla mostrando el flujo completo. Para WhatsApp puedes usar cURL scripts o el WhatsApp Manager si aún no tienes la UI de Embedded Signup lista.

4. Envía la solicitud y espera la aprobación (2-10 días hábiles).

**Consejo:** Asegúrate de que tu política de privacidad (`https://commerceops.co/privacy`) esté publicada antes de enviar — Meta la revisa.

---

### PASO 7 — Configurar el webhook de la plataforma

Una vez aprobado App Review:

1. En tu App → **WhatsApp** → **"Configuration"** → sección **"Webhooks"**.
2. Editar:
   - **Callback URL:** `https://konvi-connector.onrender.com/api/v1/meta/webhook`
   - **Verify Token:** genera un string aleatorio seguro y guárdalo como `META_VERIFY_TOKEN` en Render.
3. Suscribir a los campos: `messages`, `message_deliveries`, `message_reads`.
4. Verificar que Meta puede hacer el challenge GET exitosamente.

**Para Messenger (cuando se active):**
- En **Messenger** → **"Webhooks"** → misma URL, agregar campos: `messages`, `messaging_postbacks`.

**Para Instagram (cuando se active):**
- En **Instagram** → **"Webhooks"** → misma URL, agregar campo: `messages`.

---

### PASO 8 — Crear System User Token (token permanente)

Los tokens de usuario expiran. Para producción se usa un System User Token sin expiración.

1. [Meta Business Suite](https://business.facebook.com) → **Configuración del negocio** → **Usuarios** → **"Usuarios del sistema"**.
2. Haz clic en **"Agregar"** → nombre: `konvi-api` → rol: **Admin**.
3. Haz clic en el usuario → **"Generar nuevo token"**.
4. Selecciona tu App (`Konvi Platform`).
5. Permisos a otorgar:
   - `whatsapp_business_management`
   - `whatsapp_business_messaging`
   - `business_management`
6. Expiración: **Nunca**.
7. Copia el token y guárdalo en Render como `META_SYSTEM_USER_TOKEN`.

**Este token NO cambia.** Si necesitas revocar acceso, elimina el System User desde Meta Business Suite.

---

### CRITERIO DE ÉXITO de IH-META-01

- [ ] Meta Business Account verificada (badge verde)
- [ ] Meta App creada y asociada al Business Account
- [ ] `whatsapp_business_management` con Advanced Access aprobado
- [ ] `whatsapp_business_messaging` con Advanced Access aprobado
- [ ] Embedded Signup habilitado con redirect URL configurada
- [ ] Webhook URL registrada y challenge verificado exitosamente
- [ ] System User Token generado y configurado en Render
- [ ] Un tenant de prueba puede conectar su WhatsApp vía Embedded Signup en la UI

---

## Implementación en el código (después de IH-META-01)

Una vez aprobado el Tech Provider status, los cambios de código son:

1. **Nuevo endpoint en FastAPI:** `GET /api/v1/integrations/meta/callback` — intercambia el code por token, obtiene waba_id, registra webhook, guarda en `tenant_integrations`.
2. **Renombrar** `connector-whatsapp` → `connector-meta`, adaptar para rutear los tres canales.
3. **Nuevo UI en Integraciones:** tarjeta "Meta Suite" con Embedded Signup flow y estado por canal.
4. **Migración DB:** crear registros `tenant_integrations` para tenants existentes.
5. **Deprecar** `tenants.meta_waba_id` (mantener como fallback durante migración).

Ver `docs/integrations/whatsapp.md` para el estado actual del conector.

---

## Política y cumplimiento

- **Anti-Spam:** No enviar mensajes masivos no solicitados. Solo responder dentro de la ventana de 24h del usuario. Usar Templates aprobados para mensajes outbound fuera de esa ventana.
- **Datos del usuario:** Los tenants son los responsables del tratamiento de datos de sus clientes (GDPR/Habeas Data). La plataforma actúa como procesador.
- **Commerce Policy de Meta:** Verificar que los negocios de los tenants cumplen la política de comercio de Meta antes del onboarding. Meta puede contactar en 24h si detecta violaciones.
- **Cada tenant es dueño de sus assets:** El WABA, el número, y los mensajes pertenecen al tenant. La plataforma tiene acceso delegado. El tenant puede revocar el acceso en cualquier momento.

---

## Documentos relacionados

- `docs/integrations/whatsapp.md` — Conector WhatsApp actual (legacy, pre-Embedded Signup)
- `docs/operations/onboarding-tenants.md` — Proceso de onboarding de nuevos clientes
- `docs/risks/open-questions.md` — OQ-W01, OQ-W02 (decisiones tomadas)
- `docs/operations/HUMAN_INTERVENTIONS.md` — IH-META-01 (referencia cruzada)

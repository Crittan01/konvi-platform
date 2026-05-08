# Onboarding WhatsApp — Guía para tenants nuevos

**Audiencia**: tenant nuevo que quiere conectar su WhatsApp Business a Commerce Ops.
**Tiempo estimado**: 20-40 min (depende de si ya tiene Business Manager configurado).
**Pre-requisito**: tener un número WhatsApp Business activo (no es el WhatsApp personal).

---

## Resumen del flow (qué pasa al final)

Al terminar este onboarding, tu WhatsApp Business va a recibir mensajes de tus clientes y el bot de Commerce Ops va a responder automáticamente: cotizar envíos, generar links de pago, enviar resumen del pedido, etc.

Esquema técnico:

```
Tu cliente WhatsApp ────► Tu WhatsApp Business ────► Meta Cloud API
                                                          │
                                                          ▼
                                             Commerce Ops Connector
                                                          │
                                                          ▼
                                                 Bot orquesta + responde
                                                          │
                                                          ▼
                                                    Tu cliente
```

---

## Pre-requisitos (tener listos antes de empezar)

| # | Item | Dónde lo obtenés |
|---|---|---|
| 1 | Cuenta Facebook personal | facebook.com (debe existir, es lo que usás para entrar a Business Manager) |
| 2 | Business Portfolio de tu negocio | business.facebook.com → crear si no existe (5 min) |
| 3 | Página de Facebook de tu negocio | business.facebook.com → Configuración → Páginas → conectar la página |
| 4 | Número telefónico para WhatsApp Business (NO usado en WhatsApp personal) | Tu propio celular nuevo o una línea SIM nueva |
| 5 | Acceso al panel admin Commerce Ops como **Administrador** del tenant | te lo otorga el founder de Commerce Ops |

---

## Paso 1 — Crear/verificar tu Business Portfolio

(Skip este paso si ya tenés Business Portfolio activo con tu negocio.)

1. Entrá a [business.facebook.com](https://business.facebook.com)
2. Si no tenés Business Portfolio: clic **Crear cuenta** → llenar nombre legal del negocio + tu nombre + email comercial.
3. En **Configuración → Información del negocio**, llenar todos los campos (NIT, dirección, sector, sitio web).
4. En **Configuración → Páginas**, agregar la página de Facebook de tu negocio (si no la tenés, crearla).

> ✅ Verificación: en la esquina superior izquierda debería aparecer el nombre de tu negocio + un avatar. Si decís cosas como "Personal account" o "Mi cuenta", aún estás en personal — buscá tu Business Portfolio en el selector.

---

## Paso 2 — Activar WhatsApp Business en tu Business Portfolio

1. En [business.facebook.com](https://business.facebook.com) → **Configuración del negocio** (`/settings`).
2. En el menú izquierdo: **Cuentas → Cuentas de WhatsApp** → **Agregar** → **Crear una cuenta nueva de WhatsApp Business**.
3. Llenar: nombre del negocio (verá tu cliente), zona horaria, descripción.
4. Asignar el número de teléfono (Paso 1.4 pre-requisito):
   - Verificación SMS o llamada al número.
   - El número quedará registrado a nombre de WhatsApp Business — **no funcionará más en WhatsApp personal**.
5. Anotá:
   - **WhatsApp Business Account ID (WABA ID)** — número largo, ej: `2159052118202272`.
   - **Phone Number ID** — número largo, ej: `990364080831295`.

> ⚠️ Si ya tenías el número en WhatsApp Business app: tendrás que migrarlo a Meta Cloud API. El proceso desactiva el WhatsApp Business app de ese número (la API toma control).

---

## Paso 3 — Conectar Commerce Ops App a tu Business Portfolio

(Esta es la pieza clave que permite que Commerce Ops actúe en nombre de tu WhatsApp.)

1. En **Configuración del negocio → Cuentas → Apps** → **Agregar**.
2. Pegar el ID público de la Meta App de Commerce Ops:

   ```
   App ID: 819229210624423
   ```

   (Si Commerce Ops está corriendo bajo otro nombre/App ID, te lo darán al onboardear.)
3. Aceptar permisos:
   - ✅ Mensajería WhatsApp (`whatsapp_business_messaging`)
   - ✅ Gestión WhatsApp (`whatsapp_business_management`) — necesario para HSM templates futuros.
4. Asignar el WABA del Paso 2 a Commerce Ops App con todos los permisos.

> ⚠️ Si Commerce Ops App aún está en App Review pendiente o en Development Mode, este paso puede requerir que el founder agregue tu Business como tester. Avisá al founder con tu **Business ID** (lo ves en `/settings/info`).

---

## Paso 4 — Crear System User + Token

(El System User es como un "usuario robot" de tu Business que Commerce Ops usará para enviar mensajes en tu nombre.)

1. **Configuración del negocio → Usuarios → Usuarios del sistema** → **Agregar**.
2. Crear System User:
   - **Nombre**: `commerce-ops` (o lo que prefieras).
   - **Rol**: Empleado.
3. Asignar permisos al System User:
   - Click en el System User recién creado → **Asignar activos** → seleccionar la WABA del Paso 2 → permisos: **Acceso completo** o al menos `whatsapp_business_messaging` + `whatsapp_business_management`.
4. Generar token:
   - Click **Generar token** → seleccionar Commerce Ops App → permisos: `whatsapp_business_messaging` + `whatsapp_business_management`.
   - Token expira: **Nunca** (System User tokens de Meta son de larga duración por default).
   - **COPIAR EL TOKEN** — sólo se muestra una vez. Si lo perdés, generás otro.

> 🔐 El token es como una contraseña — **no lo compartas en chat público o emails sin cifrar**. Pegarlo SÓLO en el panel de Commerce Ops (Paso 5).

---

## Paso 5 — Conectar en Commerce Ops

1. Entrá a Commerce Ops como Administrador del tenant.
2. Sidebar → **Integraciones**.
3. En el card de WhatsApp → **Configurar**.
4. Pegar:

   | Campo Commerce Ops | Valor |
   |---|---|
   | **WABA ID** | El del Paso 2.5 (`2159052118202272`) |
   | **Phone Number ID** | El del Paso 2.5 (`990364080831295`) |
   | **Token de Acceso (System User)** | El del Paso 4.4 |

5. Click **Conectar WhatsApp**.
6. Esperá a ver el badge **Conectado** en color naranja (color de marca Envia/WhatsApp en Commerce Ops).
7. Click **Probar** para verificar que el token + número están vivos. Mensaje de éxito esperado: *"WhatsApp verificado — el token es válido y el número está activo"*.

> ⚠️ Si el botón **Probar** sale **Error**:
> - "Token inválido" → re-generar el System User token (Paso 4.4) y probar de nuevo.
> - "Phone number not registered" → confirmar que terminaste el Paso 2 (registro del número en Meta Cloud API).
> - "Permission denied" → Commerce Ops App no tiene permisos sobre tu WABA — re-revisar Paso 3.4.

---

## Paso 6 — Probar end-to-end con un mensaje real

1. Desde tu celular personal, mandá un mensaje al número WhatsApp Business del tenant: por ejemplo, *"Hola"*.
2. Esperá ~5 segundos.
3. El bot debería responder con el saludo configurado en Settings → Agente IA (sin esto se ve un saludo genérico).
4. Verificar en Commerce Ops → **Inbox** → debería aparecer la conversación con tu mensaje + la respuesta del bot.

> ✅ Si todo funcionó: tu WhatsApp Business está activo en Commerce Ops. El bot va a responder automáticamente a tus clientes 24/7.

---

## Resolución de problemas comunes

### Bot no responde

1. Verificar **Inbox** — ¿aparece tu mensaje? Si **NO**:
   - Webhook no llega → revisar Paso 3.4 (permisos al WABA).
   - Si el founder confirma que Commerce Ops Connector recibe webhooks pero no se procesan → puede ser issue de phone_number_id mal mapeado en DB. Reportar.
2. Si tu mensaje aparece pero no hay respuesta:
   - Settings → Agente IA → ¿el agente está activo?
   - Settings → Agente IA → ¿prompt configurado?
3. Si todo lo anterior OK y aún no responde: revisar logs con el founder.

### Bot responde pero "yo no entiendo"

- Revisar Settings → Catálogo → ¿hay productos? Sin productos el bot no puede cotizar.
- Revisar Settings → Despachos → ¿origen configurado? Sin esto el bot no sabe desde dónde cotizar envíos.

### Token expirado o revocado

- Vas a ver mensaje de error en `Probar` o webhooks empezando a fallar (lado founder).
- Repetir Paso 4.4 (regenerar System User token) y Paso 5 (re-pegar en Commerce Ops).
- El cambio es transparente para los clientes — las conversaciones existentes siguen.

---

## Mantenimiento

| Acción | Cuándo | Cómo |
|---|---|---|
| Cambiar foto de perfil WhatsApp Business | Branding | business.facebook.com → WABA → Configuración del perfil |
| Cambiar mensaje de bienvenida del agente | Personalización | Commerce Ops → Settings → Agente IA |
| Agregar templates HSM (proactivos fuera CSW 24h) | Cuando F2 HSM esté implementado | Commerce Ops → Settings → Templates |
| Cambiar carriers de despacho | Operativo | Commerce Ops → Integraciones → Envia → Configurar |
| Pausar respuestas del bot temporalmente | Vacaciones, mantenimiento | Settings → Agente IA → Toggle off |

---

## Política y compliance

- **Habeas Data Ley 1581 Colombia**: vos sos Responsable del Tratamiento. Commerce Ops actúa como Encargado. Tus clientes ven banners de consentimiento + tienen derecho a SAR (Solicitud de Acceso del Sujeto).
- **Meta Business Messaging Policy**: aplica a tu WABA. NO mandes spam ni contenido prohibido (drogas, armas, esquemas piramidales). Meta puede degradar quality o suspender tu WABA.
- **Conversation window 24h (CSW)**: podés responder gratis dentro de 24h del último mensaje del cliente. Fuera de eso, Meta cobra por mensaje (utility/marketing/authentication tier). Commerce Ops respeta esto automáticamente.

---

**¿Dudas?** Contactá al founder de Commerce Ops o al equipo de soporte del tenant.

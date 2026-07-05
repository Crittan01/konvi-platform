# Onboarding WhatsApp — Guía para tenants nuevos (Model B · Direct Provider)

**Audiencia**: tenant nuevo que quiere conectar su WhatsApp Business a Konvi.
**Modelo**: **Direct Provider per-tenant (ADR-0023)**. Vos creás **TU PROPIA Meta App**, con tus propias
credenciales y tu propio webhook. Konvi NO es Partner Meta y NO comparte su App con vos.
**Tiempo estimado**: 30-60 min de configuración + **2-5 semanas calendario** de trámites Meta (Business
Verification + App Review propios). El bot funciona en Development Mode mientras tanto (hasta 5 números de
prueba), así que podés probar antes de terminar los trámites.
**Pre-requisito**: número WhatsApp Business activo (NO tu WhatsApp personal).

> ⚠️ Esta guía **reemplaza** la versión anterior (Modelo A — "conectar la Konvi App a tu Business
> Portfolio"). Ese modelo fue **superseded por ADR-0023**. Si alguien te pidió reclamar/autorizar la Konvi
> App (`819229210624423`), ignoralo: bajo Model B cada tenant crea su App. La Konvi App es sólo para el
> entorno de desarrollo interno de Konvi.

---

## Resumen del flow (qué pasa al final)

Al terminar, tu WhatsApp Business recibe mensajes de tus clientes y el bot de Konvi responde
automáticamente: cotizar envíos, generar links de pago, resumen del pedido, etc.

```
Tu cliente WhatsApp ─► Tu WhatsApp Business ─► Meta Cloud API (TU Meta App)
                                                     │  webhook per-tenant
                                                     ▼
                                          Konvi Connector  /api/v1/whatsapp/webhook/{tu_tenant_id}
                                                     │  (valida HMAC con TU app_secret)
                                                     ▼
                                             Bot orquesta + responde ─► Tu cliente
```

Las **6 credenciales** que vas a capturar en Konvi (Integraciones → WhatsApp → panel completo):

| # | Credencial | Para qué sirve | Dónde la obtenés |
|---|---|---|---|
| 1 | **app_id** | Identifica tu Meta App | developers.facebook.com → tu App → Settings → Basic |
| 2 | **app_secret** | Firma HMAC del webhook (Konvi valida cada payload con esto) | idem, "App Secret" → **Mostrar** |
| 3 | **verify_token** | Handshake GET del webhook (lo elegís vos, cadena secreta) | lo inventás (ej. `mi-negocio-wh-2026`) |
| 4 | **phone_number_id** | Identifica tu número en Cloud API | WhatsApp → API Setup |
| 5 | **waba_id** | WhatsApp Business Account ID | WhatsApp → API Setup |
| 6 | **access_token** | Token System User (never-expires) para enviar mensajes | Business Settings → System Users → Generar token |

`app_secret` y `access_token` se guardan cifrados en Vault. El resto viaja en `credentials`. Konvi **nunca**
ve tu contraseña de Facebook.

---

## Paso 0 — Pedí tu acceso a Konvi + tu tenant_id

1. El founder de Konvi te provisiona (script `provision_tenant.py`) y te entrega un **enlace de recuperación**
   (o contraseña temporal) para tu primer login. Cambiá la contraseña al entrar.
2. Entrá a Konvi → **Integraciones → WhatsApp → panel completo**. Ahí verás **tu URL de webhook per-tenant**,
   que incluye tu `tenant_id`:

   ```
   https://<host-connector-konvi>/api/v1/whatsapp/webhook/<tu_tenant_id>
   ```

   Copiala con el botón **Copiar** — la vas a pegar en Meta (Paso 5). Contiene tu `tenant_id`, no la tipees
   a mano.

---

## Paso 1 — Crear tu Business Portfolio y tu Meta App

1. Entrá a [business.facebook.com](https://business.facebook.com) con tu cuenta personal de Facebook.
2. Si no tenés Business Portfolio: **Crear cuenta** → nombre legal del negocio + tu nombre + email comercial.
3. En **Configuración → Información del negocio**, llená todo (NIT, dirección, sector, sitio web).
4. Entrá a [developers.facebook.com](https://developers.facebook.com) → **My Apps → Create App**.
   - Tipo: **Business**.
   - Vinculá la App a **tu** Business Portfolio.
5. En tu App → **Add Product → WhatsApp → Set up**.
6. Anotá de **Settings → Basic**: **App ID** (#1) y **App Secret** (#2, click "Show").

---

## Paso 2 — Registrar tu número en WhatsApp Cloud API

1. En tu App → **WhatsApp → API Setup**.
2. Agregá el número WhatsApp Business (Paso pre-requisito). Verificación por SMS/llamada.
   - El número queda registrado en Cloud API — **no funcionará más en la app WhatsApp Business** de ese
     número.
3. Anotá: **Phone Number ID** (#4) y **WhatsApp Business Account ID / WABA ID** (#5).

> ⚠️ Si el número ya estaba en la app WhatsApp Business, tenés que migrarlo a Cloud API (la API toma control).

---

## Paso 3 — Crear System User + token never-expires

(El System User es un "usuario robot" de TU Business que Konvi usa para enviar mensajes en tu nombre.)

1. **Business Settings → Usuarios → Usuarios del sistema → Agregar**.
   - Nombre: `konvi-bot` (o el que prefieras). Rol: Admin.
2. **Asignar activos** → seleccioná tu WABA (Paso 2) → permisos: **Acceso completo**.
3. **Generar token** → seleccioná **TU App** → permisos:
   `whatsapp_business_messaging` + `whatsapp_business_management`.
   - Expiración: **Never** (System User tokens son de larga duración).
   - **COPIÁ EL TOKEN** — se muestra una sola vez (#6).

> 🔐 El token y el app_secret son como contraseñas. Pegalos SÓLO en el panel de Konvi (Paso 6), nunca en
> chat/email sin cifrar.

---

## Paso 4 — Elegí tu verify_token

Inventá una cadena secreta, ej. `mi-negocio-wh-2026` (#3). La vas a poner en dos lugares idénticos: en el
webhook de Meta (Paso 5) y en el panel de Konvi (Paso 6). Meta la usa para el handshake inicial (GET).

---

## Paso 5 — Configurar el webhook en TU Meta App

1. En tu App → **WhatsApp → Configuration → Webhook → Edit**.
2. **Callback URL**: pegá tu URL per-tenant del Paso 0:

   ```
   https://<host-connector-konvi>/api/v1/whatsapp/webhook/<tu_tenant_id>
   ```

3. **Verify token**: pegá el mismo `verify_token` del Paso 4.
4. Click **Verify and save**. Meta hace un GET a esa URL con tu verify_token; el connector responde el
   challenge. Si falla, revisá que el verify_token sea idéntico y que ya lo hayas guardado en Konvi (Paso 6
   primero) — el connector necesita conocerlo para responder el handshake.
5. En **Webhook fields**, suscribite a **messages** (mínimo). Opcional: `message_template_status_update`.

> El orden recomendado es: **Paso 6 primero** (guardar en Konvi) → **luego Verify and save en Meta**. Así el
> connector ya conoce tu verify_token cuando Meta hace el handshake.

---

## Paso 6 — Conectar en Konvi (form de 6 campos)

> ⚠️ **Pre-requisito legal (producción)**: al pegar tu **App Secret** le entregás a Konvi la custodia de una
> credencial de TU Meta App. Para tenants **externos** en producción esto exige el **DPA tenant-Konvi**
> aceptado (custodia de `app_secret`, Model B — `docs/legal/dpa.md` §5.bis, ADR-0023 OQ-1). Mientras la
> cláusula de custodia esté **pendiente de cierre legal** (acción founder), la conexión en producción de un
> tenant externo queda bloqueada. **KAIU (self) no aplica.** Coordiná el estado del DPA con el founder antes
> de este paso.

1. Konvi → **Integraciones → WhatsApp → panel completo** (form Model B).
2. Pegá las 6 credenciales:

   | Campo Konvi | Valor |
   |---|---|
   | App ID | #1 |
   | App Secret | #2 → se cifra en Vault |
   | Verify Token | #3 (el que inventaste) |
   | Phone Number ID | #4 |
   | WABA ID | #5 |
   | Access Token | #6 → se cifra en Vault |

3. Guardar. El estado pasa a **Conectado**.
4. Volvé al Paso 5.4 y hacé **Verify and save** en Meta si no lo habías hecho.

> El form de 3 campos (WABA + Phone Number ID + Token) que aparece en el hub de integraciones es **legacy** y
> NO alcanza para Model B (falta app_secret + verify_token). Usá siempre el **panel completo** de 6 campos.

---

## Paso 7 — Probar end-to-end

1. Desde otro celular, mandá "Hola" al número WhatsApp Business del negocio.
2. Esperá ~5 s. El bot debería responder con el saludo configurado en Settings → Agente IA.
3. Verificá en Konvi → **Inbox**: aparece la conversación con tu mensaje + la respuesta del bot.

> ✅ Si funcionó: tu WhatsApp Business está activo en Konvi.

---

## Trámites Meta para producción (fuera de Development Mode)

En Development Mode tu App sólo puede mensajear con hasta ~5 números de prueba. Para atender clientes reales
necesitás, **con TU propia App y TU propio Business** (no los de Konvi):

1. **Business Verification** de tu Business Portfolio (10 min trámite + **1-3 semanas** review Meta).
   Documentos: RUT, certificación bancaria, factura de servicios a nombre del negocio, sitio web con SSL.
2. **App Review** de TU App para Advanced Access de `whatsapp_business_messaging` (+ `..._management` si vas
   a usar HSM templates): 30 min + screencast + **1-2 semanas** review Meta.

Estos trámites NO los hace Konvi por vos (Model B) — sos Direct Provider. El founder puede orientarte pero la
titularidad es tuya.

---

## Resolución de problemas

### El handshake del webhook falla (Verify and save da error)

- El `verify_token` en Meta y en Konvi deben ser **idénticos** (sin espacios).
- Guardá primero en Konvi (Paso 6), luego "Verify and save" en Meta.
- La URL debe incluir tu `tenant_id` correcto (copiala del panel, no la tipees).

### Bot no responde

1. **Inbox** — ¿aparece tu mensaje?
   - **No** → el webhook no llega o la firma HMAC falla: revisá que el **app_secret** en Konvi sea el de TU
     App (Settings → Basic) y que estés suscrito al campo `messages` en Meta.
   - **Sí, sin respuesta** → Settings → Agente IA: ¿activo? ¿prompt configurado?
2. Sin catálogo el bot no cotiza: Settings → Catálogo. Sin origen de despacho no cotiza envíos.

### Token expirado o revocado

- Regenerá el System User token (Paso 3) y re-pegalo en el panel (Paso 6). Transparente para tus clientes.

---

## Mantenimiento

| Acción | Cómo |
|---|---|
| Cambiar foto/branding WhatsApp Business | business.facebook.com → WABA → Perfil |
| Cambiar saludo del agente | Konvi → Settings → Agente IA |
| Rotar access_token | Regenerar System User token → re-pegar en panel WhatsApp |
| Cambiar carriers de despacho | Konvi → Integraciones → **Aveonline** → Configurar |
| Pausar el bot | Settings → Agente IA → Toggle off |

---

## Política y compliance

- **Habeas Data Ley 1581 (Colombia)**: vos sos Responsable del Tratamiento; Konvi es Encargado. Tus clientes
  ven banners de consentimiento y pueden ejercer SAR.
- **Meta Business Messaging Policy**: aplica a TU WABA. Nada de spam/contenido prohibido.
- **Conversation window 24h (CSW)**: respondés gratis dentro de 24h del último mensaje del cliente; fuera de
  eso Meta cobra por template. Konvi lo respeta automáticamente.
- **Custodia de app_secret**: al compartir tu app_secret con Konvi (para validar HMAC) aplica el DPA
  tenant-Konvi (`docs/legal/dpa.md` §5.bis, ADR-0023 OQ-1). Es **pre-requisito** en producción para tenants
  externos (ver Paso 6); la cláusula de custodia está pendiente de cierre legal (acción founder).

---

**Referencia arquitectónica**: `docs/adr/0023-meta-model-b-direct-provider-per-tenant.md`.
**¿Dudas?** Contactá al founder de Konvi.

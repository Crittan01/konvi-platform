# Intervenciones Humanas Requeridas

Este documento registra **cada paso que requiere acción manual** fuera del automatismo del agente.
Debe actualizarse cada vez que se identifique una nueva intervención.

---

## [IH-001] Aplicar Migración SQL: `messages.processed`

**Estado**: ✅ COMPLETADO — 2026-04-07  
**Resuelto por**: `supabase db query --linked` (Management API — no TCP directo)

### Cómo se aplicó (para futuras migraciones)

La VM no puede conectar a Postgres via TCP (el Supavisor rechaza conexiones de esta IP).
Pero el **Supabase CLI con `--linked`** usa la **Management API REST** que sí funciona.

Instalación única del CLI:

```bash
# Descargar binario oficial desde GitHub Releases
curl -fsSL https://github.com/supabase/cli/releases/latest/download/supabase_linux_amd64.tar.gz \
  -o /tmp/supabase.tar.gz
tar -xzf /tmp/supabase.tar.gz -C /tmp/
sudo mv /tmp/supabase /usr/local/bin/supabase
supabase --version  # Debe mostrar versión
```

Vincular el proyecto (una sola vez):

```bash
cd /home/ansible/workspaces/commerce-ops-platform
supabase link --project-ref ***SUPABASE_PROJECT_REF_REDACTED***
# No pide login si el proyecto es público o está en modo anon
```

Ejecutar SQL / migraciones:

```bash
# Ejecutar un archivo .sql completo
supabase db query --linked -f supabase/migrations/20260407200700_messages_processed_flag.sql

# Ejecutar SQL inline
supabase db query --linked "SELECT * FROM tenants;"
```

Verificación realizada:
```
column_name    | data_type                   | column_default
processed      | boolean                     | false
processed_at   | timestamp with time zone    | null
```

### Por qué psql directo no funciona (investigado)

El Supabase Supavisor (pooler) responde **"Tenant or user not found"** a conexiones TCP desde esta IP.
Esto NO es un bug — el Supavisor usa IPv6 para routing interno y esta VM usa IPv4. El CLI `--linked` sortea este problema usando HTTPS a `api.supabase.com`.

---

## [IH-002] Configurar `meta_waba_id` en el tenant de Supabase

**Estado**: ✅ COMPLETADO — 2026-04-07  
**meta_waba_id configurado**: `2159052118202272`  
**Tenant**: `Matriz Commerce Dev` (id: `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`)

Verificado vía REST API:
```json
[{"id":"0fb0777e-...","name":"Matriz Commerce Dev","meta_waba_id":"2159052118202272"}]
```

Para futuras consultas:
```bash
supabase db query --linked "SELECT id, name, meta_waba_id FROM tenants;"
```

### Contexto

El campo `meta_waba_id` en la tabla `tenants` es el vínculo entre el número de WhatsApp Business Account (WABA) de Meta y el tenant interno del sistema.

Después del fix del tenant resolver, si el `meta_waba_id` del tenant en la base de datos no coincide con el WABA ID que Meta envía en los webhooks, **los mensajes serán descartados** con el log: `"Tenant no encontrado para meta_waba_id='...'"`.

### Pasos

**PASO 1 — Obtener el WABA ID**

1. Ve a [Meta Business Suite](https://business.facebook.com/) → **WhatsApp** → **Cuentas de WhatsApp**.
2. El número que aparece como **"WhatsApp Business Account ID"** es el WABA ID.  
   *(Formato: número largo, ej: `102938475628374`)*
3. O bien: en [Meta Developers](https://developers.facebook.com/), ve a tu App → **WhatsApp** → **API Setup**. El campo `"WhatsApp Business Account ID"` es lo que necesitas.

**PASO 2 — Actualizar el tenant en Supabase**

1. Ve a `https://supabase.com/dashboard` → proyecto `commerce-ops-dev`.
2. En el menú lateral: **Table Editor** → tabla **`tenants`**.
3. Haz clic en la fila de tu tenant (debería haber 1 fila si es entorno dev).
4. En la columna `meta_waba_id`, haz doble clic y pega el WABA ID del Paso 1.
5. Haz clic fuera de la celda para guardar.

**O via SQL Editor:**

```sql
UPDATE public.tenants
SET meta_waba_id = 'TU_WABA_ID_AQUI'
WHERE name = 'Matriz Commerce Dev';  -- Ajusta el name si es diferente
```

### Criterio de Éxito

```sql
SELECT id, name, meta_waba_id FROM public.tenants;
```

La columna `meta_waba_id` debe tener el valor del WABA ID de Meta (no NULL ni vacío).

---

## [IH-003] META_ACCESS_TOKEN — Renovación Periódica

**Estado**: ⚠️ RENOVACIÓN PENDIENTE PERIÓDICAMENTE  
**Última renovación**: 2026-04-07 ~16:41 CDT (segunda renovación del día, token de ~297 chars)

### Contexto

El `META_ACCESS_TOKEN` es un **User Access Token temporal** de Meta Developers. Expira cada ~24 horas.
Para desarrollo es aceptable renovarlo manualmente. Para producción, usar un **System User Token permanente**.

### Cómo renovar el token temporal (entorno dev)

1. Ir a [Meta Developers](https://developers.facebook.com/) → Tu App → **WhatsApp** → **API Setup**
2. En la sección **"Temporary access token"**, hacer clic en **"Generate access token"**
3. Copiar el token generado
4. Actualizar en `.env`: `META_ACCESS_TOKEN="<nuevo_token>"`
5. Reiniciar el conector: `uvicorn main:app --reload --port 8000`

### Cómo crear un Token Permanente (producción)

Según la [documentación oficial de Meta](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started#get-access-token):

1. Ve a [Meta Business Suite](https://business.facebook.com/) → **Configuración del negocio**
2. Menú izquierdo: **Usuarios** → **Usuarios del sistema** → **+ Agregar**
3. Nombre: `commerce-ops-bot`, Rol: **Admin**
4. Clic en el usuario → **"Generar nuevo token"** → Seleccionar App
5. Permisos mínimos: `whatsapp_business_messaging`, `whatsapp_business_management`
6. Expiración: **Nunca**
7. En Render: configurar como env var `META_ACCESS_TOKEN` (nunca en el repo)

---

## [IH-004] Primer Deploy en Render

**Estado**: 🟡 PASOS 1-5 COMPLETADOS — PASOS 6-7 pendientes (ver abajo)  
**Completado**:
- ✅ `GEMINI_API_KEY` configurada en `.env` y en Render
- ✅ `render.yaml` v5 con 4 servicios (web + connector + api + orchestrator)
- ✅ Guía paso a paso `FASE7_RENDER_DEPLOY.md` creada
- ✅ 4 servicios desplegados y vivos en Render
- ✅ Smoke tests pasados (PASO 5)
- ✅ TailwindCSS fix: `postcss.config.js` + `--include=dev` + clear build cache

**Pendiente (requiere acción humana)**:
- ⚠️ PASO 6: Actualizar Callback URL del webhook en Meta Developers:
  - Callback URL: `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook`
  - Verify Token: `***META_VERIFY_TOKEN_LEGACY_REDACTED***`
  - Campo: `messages`
- ⚠️ PASO 7: Test E2E — enviar WhatsApp al número Meta → verificar respuesta Gemini

---

## [IH-005] Obtener SUPABASE_JWT_SECRET

**Estado**: ✅ COMPLETADO — 2026-04-08  
**`SUPABASE_JWT_SECRET` presente** en `.env` y configurado en Render Dashboard.  
`GET https://commerce-ops-api.onrender.com/health` responde `{"status":"ok"}` ✅

### Cómo se obtuvo (referencia para futuros proyectos)

1. Ir a [https://supabase.com/dashboard](https://supabase.com/dashboard) → Proyecto `***SUPABASE_PROJECT_REF_REDACTED***`
2. Menú lateral → **Project Settings** → **Data API**
3. Sección **JWT Settings** → copiar el valor de **JWT Secret**
4. Configurar en `.env` y en Render Dashboard → servicio `commerce-ops-api` → Environment

---

## [IH-006] META_ACCESS_TOKEN — Upgrade a System User Token Permanente

**Estado**: ✅ COMPLETADO — 2026-04-09  
**Usuario del sistema creado**: `commerce-ops` (nombre ajustado por política de Meta — sin guiones múltiples)  
**Token**: Permanente (sin expiración), configurado en Render (connector + orchestrator) y en `.env` local  
**Verificación**:
```
curl https://commerce-ops-connector.onrender.com/health  → {"status":"ok","service":"connector-whatsapp"}
curl https://commerce-ops-api.onrender.com/health        → {"status":"ok"}
```

---

---

## [IH-007] Registrar App en MeLi Developers — Fase 10

**Estado**: ⏳ PENDIENTE — bloquea la conexión OAuth de MeLi  
**Bloquea**: Botón "Conectar con Mercado Libre" en `/dashboard/integrations`

### Por qué es necesario

MeLi requiere una app registrada para obtener `client_id` y `client_secret` del OAuth 2.0.
Sin esto, la plataforma no puede iniciar el flujo de autorización por tenant.

### Pasos

1. Ve a [developers.mercadolibre.com.mx](https://developers.mercadolibre.com.mx) → **Crear aplicación**
2. Nombre: `Commerce Ops Platform`
3. Redirect URI: `https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback`
   - Debe ser HTTPS exacto — no agregar trailing slash
4. Scopes a habilitar: `read`, `write`, `offline_access`
5. Copiar `App ID` (= CLIENT_ID) y `Secret key` (= CLIENT_SECRET)
6. En Render Dashboard → servicio `commerce-ops-api` → Environment:
   - `MELI_CLIENT_ID` = App ID
   - `MELI_CLIENT_SECRET` = Secret key
   - `MELI_REDIRECT_URI` = `https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback`
7. Redeploy `commerce-ops-api`
8. Probar flujo desde `/dashboard/integrations` → botón "Conectar con Mercado Libre"

### Criterio de Éxito

El botón de MeLi en `/dashboard/integrations` ya no muestra "(requiere IH-007)" y permite iniciar el flujo OAuth.

---

## [IH-008] Obtener API Key de Envia

**Estado**: ⏳ PENDIENTE — bloquea cotizaciones de envío  
**Bloquea**: Formulario de cotización en `/dashboard/shipping` + `/dashboard/integrations`

### Por qué es necesario

Envia usa Bearer token per-tenant. El tenant (owner) debe obtener su token desde su cuenta Envia y configurarlo desde la UI.

### Pasos

1. Ve a [app.envia.com](https://app.envia.com) → inicia sesión con tu cuenta Envia
2. Menú → **Configuración** → **API** → **Generar token** (o copiar el existente)
3. En la plataforma: `/dashboard/integrations` → sección **Envia** → pegar el token → **Conectar Envia**
4. Si no tienes cuenta Envia: regístrala en [envia.com](https://envia.com) (acepta cuentas de prueba/sandbox)

> Esta acción la realiza el owner del tenant directamente desde la UI.
> No requiere configuración en Render — el token se almacena en `tenant_integrations`.

### Criterio de Éxito

Estado de Envia en `/dashboard/integrations` cambia a "Conectado".
La página `/dashboard/shipping` muestra el formulario de cotización en lugar del banner de advertencia.

---

## Regla de Actualización

Cada vez que se resuelva una intervención, cambiar su estado a `✅ COMPLETADO` y agregar la fecha de resolución.  
Cada vez que el agente identifique un nuevo paso manual, agregarlo a este documento.

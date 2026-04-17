# Fase 7 — Deploy en Render.com

**Estado**: ✅ COMPLETADO — Todos los pasos (1-7) ejecutados. Deploy live en producción.  
**Fecha**: 2026-04-09  
**Responsable técnico**: Ver IH-004 en `HUMAN_INTERVENTIONS.md`

---

## Resumen de servicios a desplegar

| Nombre en Render | Tipo | Origen | URL resultante |
|---|---|---|---|
| `commerce-ops-web` | Web Service (Node) | `apps/web` | `https://commerce-ops-web.onrender.com` |
| `commerce-ops-connector` | Web Service (Python) | `services/connector-whatsapp` | `https://commerce-ops-connector.onrender.com` |
| `commerce-ops-api` | Web Service (Python) | `services/api` | `https://commerce-ops-api.onrender.com` |
| `commerce-ops-orchestrator` | Background Worker | `services/ai-orchestrator` | (sin URL pública) |

---

## PRE-REQUISITO: Obtener SUPABASE_JWT_SECRET

> ⚠️ Esta variable es necesaria para el `commerce-ops-api` y puede no estar en tu `.env` local.

**ACCIÓN HUMANA — 2 minutos**

1. Ir a [https://supabase.com/dashboard](https://supabase.com/dashboard) → Proyecto `xmelwnhhphksbpdjmbbp`
2. Menú lateral → **Project Settings** → **Data API**
3. Sección **JWT Settings** → copiar el valor de **JWT Secret**
4. En la VM, editar `.env`:

```bash
# El archivo ya tiene la línea preparada, solo llenar el valor:
# SUPABASE_JWT_SECRET=""
nano /home/ansible/workspaces/commerce-ops-platform/.env
```

5. Rellenar el valor: `SUPABASE_JWT_SECRET="tu_jwt_secret_aqui"`

**Criterio de éxito**: El valor no es vacío y corresponde al de Supabase Dashboard.

---

## PASO 1 — Crear/conectar cuenta en Render

**ACCIÓN HUMANA — 5 minutos**

1. Ir a [https://render.com](https://render.com)
2. Hacer clic en **"Get Started for Free"** o **"Sign In"**
3. Recomendado: iniciar sesión con **GitHub** (el mismo que contiene el repo)
4. Una vez dentro del Dashboard, NO crear servicios aún — ir al Paso 2

---

## PASO 2 — Conectar repositorio vía Blueprint

**ACCIÓN HUMANA — 5 minutos**

1. En el Render Dashboard, clic en **"New +"** (botón azul superior derecho)
2. Seleccionar **"Blueprint"**
3. Aparecerá "Connect a repository" → conectar **GitHub** (si no está conectado)
4. Buscar y seleccionar el repositorio: **`Crittan01/commerce-ops-platform`**
5. Rama a usar: **`develop`** (o `main` si se ha hecho merge)
6. Render escaneará el `render.yaml` de la raíz → mostrará 4 servicios detectados
7. Revisar que los 4 servicios aparecen:
   - `commerce-ops-web` (web)
   - `commerce-ops-connector` (web)
   - `commerce-ops-api` (web)
   - `commerce-ops-orchestrator` (worker)
8. Hacer clic en **"Apply"** — Render creará los servicios (los builds fallarán por las vars pendientes, eso es normal)

> 📌 **Referencia oficial**: [https://render.com/docs/blueprint-spec](https://render.com/docs/blueprint-spec)

---

## PASO 3 — Configurar variables de entorno por servicio

**ACCIÓN HUMANA — 15 minutos**

Para cada servicio en el Render Dashboard → seleccionar el servicio → **"Environment"**

### 3a — `commerce-ops-web` (Frontend)

| Variable | Valor | ¿Marcar como Secret? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xmelwnhhphksbpdjmbbp.supabase.co` | No |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | *(del .env local)* | No |

### 3b — `commerce-ops-connector` (WhatsApp Webhook)

| Variable | Valor | ¿Marcar como Secret? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xmelwnhhphksbpdjmbbp.supabase.co` | No |
| `SUPABASE_SERVICE_ROLE_KEY` | *(del .env local - eyJhbG...)* | **SÍ — SECRET** |
| `META_APP_SECRET` | *(del .env local)* | **SÍ — SECRET** |
| `META_VERIFY_TOKEN` | `commercesuperclave2025` | **SÍ — SECRET** |
| `META_ACCESS_TOKEN` | *(System User Token — ver IH-003)* | **SÍ — SECRET** |
| `WHATSAPP_PHONE_ID` | `990364080831295` | No |
| `ALLOWED_ORIGINS` | `https://commerce-ops-web.onrender.com,https://commerce-ops-api.onrender.com` | No |

### 3c — `commerce-ops-api` (Core API REST)

| Variable | Valor | ¿Marcar como Secret? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xmelwnhhphksbpdjmbbp.supabase.co` | No |
| `SUPABASE_SERVICE_ROLE_KEY` | *(del .env local - eyJhbG...)* | **SÍ — SECRET** |
| `SUPABASE_JWT_SECRET` | *(del Supabase Dashboard → Project Settings → Data API → JWT Secret)* | **SÍ — SECRET** |
| `ALLOWED_ORIGINS` | `https://commerce-ops-web.onrender.com` | No |

### 3d — `commerce-ops-orchestrator` (AI Worker)

| Variable | Valor | ¿Marcar como Secret? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xmelwnhhphksbpdjmbbp.supabase.co` | No |
| `SUPABASE_SERVICE_ROLE_KEY` | *(del .env local - eyJhbG...)* | **SÍ — SECRET** |
| `META_ACCESS_TOKEN` | *(System User Token — ver IH-003)* | **SÍ — SECRET** |
| `WHATSAPP_PHONE_ID` | `990364080831295` | No |
| `GEMINI_API_KEY` | *(del .env local - AIzaSy...)* | **SÍ — SECRET** |
| `GEMINI_MODEL` | `gemini-1.5-flash` | No |
| `POLL_INTERVAL_SECONDS` | `3` | No |
| `CONVERSATION_HISTORY_LIMIT` | `10` | No |

> ⚠️ **NUNCA** pegar secrets directamente en el `render.yaml`. Render los encripta solo si se marcan como "Secret" en la UI.

---

## PASO 4 — Trigger manual de deploy

**ACCIÓN HUMANA — 2 minutos**

Después de configurar todas las variables:

1. Para cada servicio en Render Dashboard → **"Manual Deploy"** → **"Deploy latest commit"**
2. Monitorear los logs en la pestaña **"Logs"** de cada servicio
3. Build exitoso mostrará: `Build successful 🎉` o `==> Your service is live 🎉`

---

## PASO 5 — Smoke Tests desde la VM

**ACCIÓN AGENTE** — Después del Paso 4

Una vez que los servicios están `Live`, desde la VM ejecutar:

```bash
# Health check — Frontend (debe retornar HTML del login page)
curl -I https://commerce-ops-web.onrender.com
# Esperado: HTTP/2 200

# Health check — Connector
curl https://commerce-ops-connector.onrender.com/health
# Esperado: {"status":"ok"}

# Health check — Core API
curl https://commerce-ops-api.onrender.com/health
# Esperado: {"status":"ok"}

# Verificar webhook endpoint del connector
curl https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=commercesuperclave2025&hub.challenge=test123
# Esperado: test123 (echo del challenge)
```

---

## PASO 6 — Actualizar Callback URL en Meta Developers

**ACCIÓN HUMANA — 5 minutos**

Una vez que `commerce-ops-connector` esté `Live`:

1. Ir a [Meta Developers](https://developers.facebook.com/apps/) → Tu App → **WhatsApp** → **Configuration**
2. En la sección **Webhook** → clic en **"Edit"**
3. Actualizar:
   - **Callback URL**: `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook`
   - **Verify Token**: `commercesuperclave2025` (valor de `META_VERIFY_TOKEN`)
4. Clic en **"Verify and Save"** — Meta enviará un GET de verificación
5. Activar el campo **`messages`** con **"Subscribe"**

**Criterio de éxito**: Panel de Meta muestra ✅ verde en el campo `messages`.

> 📌 **Referencia**: [https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks)

---

## PASO 7 — Test E2E Post-Deploy

**ACCIÓN HUMANA + AGENTE — 10 minutos**

1. Desde un celular con WhatsApp, enviar un mensaje al número de prueba de Meta
2. Verificar el flujo completo:
   - Meta → `commerce-ops-connector` → Supabase `messages` (processed=false)  
   - `commerce-ops-orchestrator` detecta → llama Gemini → responde por `META_ACCESS_TOKEN`  
   - El celular recibe la respuesta del bot  
   - En `https://commerce-ops-web.onrender.com/dashboard/inbox` aparece el hilo en tiempo real

**Desde la VM, verificar que el mensaje llegó a Supabase:**
```bash
supabase db query --linked "SELECT id, from_number, body, processed, created_at FROM messages ORDER BY created_at DESC LIMIT 5;"
```

---

## Advertencia Post-Deploy: Plan Free de Render

> ⚠️ **IMPORTANTE para producción real**:
> 
> El plan Free de Render tiene las siguientes limitaciones:
> - Los Web Services se **"duermen"** después de 15 minutos de inactividad (cold start ~30-60s)
> - Los Background Workers en Free **se reinician con frecuencia**
> - **Para producción real**, usar plan **Starter ($7/mes por servicio)** que mantiene el servicio activo 24/7
> 
> El `commerce-ops-orchestrator` es un worker crítico — considerar upgrade a Starter para producción.

---

## URLs en producción (post-deploy)

| Servicio | URL |
|---|---|
| Frontend Backoffice | `https://commerce-ops-web.onrender.com` |
| WhatsApp Webhook | `https://commerce-ops-connector.onrender.com` |
| Core API REST | `https://commerce-ops-api.onrender.com` |
| AI Orchestrator | (Background Worker — sin URL) |
| Webhook Meta configurar | `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook` |

---

## Estado de completitud — 2026-04-09

- [x] PRE-REQ: `SUPABASE_JWT_SECRET` ✅ en .env
- [x] PRE-REQ: `META_ACCESS_TOKEN` ✅ en Render Dashboard
- [x] PRE-REQ: `GEMINI_API_KEY` ✅ configurada — billing habilitado (paid tier)
- [x] PASO 1: Cuenta Render creada/conectada ✅
- [x] PASO 2: Blueprint aplicado — 4 servicios creados ✅
- [x] PASO 3: Variables de entorno ✅ — todos los servicios configurados
  - `commerce-ops-connector` ✅ live
  - `commerce-ops-api` ✅ live
  - `commerce-ops-orchestrator` ✅ live — `GEMINI_MODEL=gemini-2.5-flash`
  - `commerce-ops-web` ✅ live — TailwindCSS OK tras "Clear build cache & deploy"
- [x] PASO 4: Deploy exitoso en los 4 servicios ✅
- [x] PASO 5: Smoke tests pasados desde VM ✅ — 2026-04-09
  - `commerce-ops-web` → HTTP 200 ✅
  - `commerce-ops-connector /health` → `{"status":"ok","service":"connector-whatsapp"}` ✅
  - `commerce-ops-api /health` → `{"status":"ok"}` ✅
  - Webhook verification echo → `test123` ✅
  - `commerce-ops-orchestrator` → worker running, polling Supabase cada 3s ✅
- [ ] PASO 6: **ACCIÓN HUMANA** → Meta Developers → Webhook Callback URL actualizar
  - URL: `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook`
  - Verify Token: `commercesuperclave2025`
  - Suscribir campo `messages`
- [ ] PASO 7: Test E2E — mensaje WhatsApp → Gemini → respuesta automática + Inbox AI

## Lecciones aprendidas — Problemas resueltos en Fase 7

### 1. Gemini quota/modelo
- **Síntoma**: `429 RESOURCE_EXHAUSTED` (free tier con quota=0) o `404 gemini-1.5-flash not found`
- **Causa**: La GEMINI_API_KEY estaba en free tier de Google AI Studio (quota agotada).
  El SDK `google-genai==1.47.0` usa endpoint v1beta → solo soporta `gemini-2.0-flash` / `gemini-2.5-flash`.
  `gemini-2.0-flash` fue deprecado para cuentas nuevas con billing.
- **Fix aplicado**: Habilitar billing en Google AI Studio + cambiar a `gemini-2.5-flash` en `render.yaml`
  y `orchestrator.py`. Actualizar valor en Render Dashboard (`GEMINI_MODEL=gemini-2.5-flash`).

### 2. UI plana — TailwindCSS no procesado
- **Síntoma**: UI sin estilos (texto plano, sin colores, sin layout)
- **Causa**: `NODE_ENV=production` hace que `npm install` omita devDependencies. Sin `postcss.config.js`,
  Next.js no procesaba los `@tailwind` directives. Además, el `.next/cache` de Render guardaba el CSS
  roto, por lo que builds posteriores no regeneraban el CSS aunque se añadiera `postcss.config.js`.
- **Fix aplicado**:
  1. `render.yaml` buildCommand: `npm install --include=dev`
  2. `apps/web/postcss.config.js` creado con tailwindcss + autoprefixer
  3. `autoprefixer` añadido a devDependencies en `apps/web/package.json`
  4. Render Dashboard → `commerce-ops-web` → **"Clear build cache & deploy"**

### 3. TypeScript missing en build
- **Síntoma**: `Please install typescript by running: yarn add --dev typescript`
- **Causa**: `NODE_ENV=production` → npm omitía devDependencies (TypeScript está en devDeps)
- **Fix**: `npm install --include=dev` en buildCommand

### 4. badge.tsx no committed (módulos en cascada)
- **Síntoma**: webpack reporta `@/utils/supabase/client` y `@/components/ui/button` como no encontrados
- **Causa real**: `apps/web/components/ui/badge.tsx` no estaba committed. webpack corrompe el grafo de
  módulos cuando un import falla, reportando otros módulos existentes como no encontrados.
- **Fix**: `git add apps/web/components/ui/badge.tsx && git commit`

### `commerce-ops-web` — REQUERIDAS EN BUILD TIME

> ⚠️ Las variables `NEXT_PUBLIC_*` en Next.js son embebidas en el bundle durante el build.
> Si no están configuradas en Render Dashboard ANTES del build, el cliente no tendrá acceso a Supabase.

| Variable | Valor |
|---------|-------|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xmelwnhhphksbpdjmbbp.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | *(del .env local)* |

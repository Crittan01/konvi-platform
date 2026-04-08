# Fase 7 — Deploy en Render.com

**Estado**: 🟡 EN PROGRESO  
**Fecha**: 2026-04-08  
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

1. Ir a [https://supabase.com/dashboard](https://supabase.com/dashboard) → Proyecto `***SUPABASE_PROJECT_REF_REDACTED***`
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
| `NEXT_PUBLIC_SUPABASE_URL` | `https://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co` | No |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | *(del .env local)* | No |

### 3b — `commerce-ops-connector` (WhatsApp Webhook)

| Variable | Valor | ¿Marcar como Secret? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co` | No |
| `SUPABASE_SERVICE_ROLE_KEY` | *(del .env local - eyJhbG...)* | **SÍ — SECRET** |
| `META_APP_SECRET` | *(del .env local)* | **SÍ — SECRET** |
| `META_VERIFY_TOKEN` | `***META_VERIFY_TOKEN_LEGACY_REDACTED***` | **SÍ — SECRET** |
| `META_ACCESS_TOKEN` | *(System User Token — ver IH-003)* | **SÍ — SECRET** |
| `WHATSAPP_PHONE_ID` | `990364080831295` | No |
| `ALLOWED_ORIGINS` | `https://commerce-ops-web.onrender.com,https://commerce-ops-api.onrender.com` | No |

### 3c — `commerce-ops-api` (Core API REST)

| Variable | Valor | ¿Marcar como Secret? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co` | No |
| `SUPABASE_SERVICE_ROLE_KEY` | *(del .env local - eyJhbG...)* | **SÍ — SECRET** |
| `SUPABASE_JWT_SECRET` | *(del Supabase Dashboard → Project Settings → Data API → JWT Secret)* | **SÍ — SECRET** |
| `ALLOWED_ORIGINS` | `https://commerce-ops-web.onrender.com` | No |

### 3d — `commerce-ops-orchestrator` (AI Worker)

| Variable | Valor | ¿Marcar como Secret? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co` | No |
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
curl https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=***META_VERIFY_TOKEN_LEGACY_REDACTED***&hub.challenge=test123
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
   - **Verify Token**: `***META_VERIFY_TOKEN_LEGACY_REDACTED***` (valor de `META_VERIFY_TOKEN`)
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

## Estado de completitud

- [ ] PRE-REQ: Obtener `SUPABASE_JWT_SECRET` de Supabase Dashboard
- [ ] PASO 1: Cuenta Render creada/conectada
- [ ] PASO 2: Blueprint aplicado — 4 servicios creados
- [ ] PASO 3: Variables de entorno configuradas en todos los servicios
- [ ] PASO 4: Deploy manual exitoso en todos los servicios
- [ ] PASO 5: Smoke tests pasados desde VM
- [ ] PASO 6: Webhook Meta → `commerce-ops-connector.onrender.com` actualizado
- [ ] PASO 7: Test E2E — mensaje WhatsApp procesado y respondido correctamente

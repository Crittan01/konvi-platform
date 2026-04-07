# Guía de Despliegue — Commerce Ops Platform

Esta guía lleva el sistema desde cero en una VM hasta producción en Render, paso a paso.
Cada paso indica si requiere acción manual o si puede ejecutarse desde la VM.

---

## Paso 1 — GEMINI_API_KEY (Cerebro de IA)

> estado: ⏳ Pendiente

**ACCIÓN HUMANA — 3 minutos**

1. Ir a [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Clic en **"Create API Key"** → seleccionar un proyecto de Google Cloud (o crear uno nuevo)
3. Copiar el string generado (formato: `AIzaSy...`)
4. En la VM, abrir `.env` y agregar:
   ```
   GEMINI_API_KEY="AIzaSy_TU_KEY_AQUI"
   ```
5. Verificar que el Orchestrator arranca:
   ```bash
   cd /home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator
   export $(grep -v '^#' ../../.env | sed 's/"\(.*\)"/\1/' | xargs)
   python3 main.py
   # Debe imprimir: "🚀 AI Orchestrator iniciando..." y luego el worker activo
   # Ctrl+C para detener
   ```

---

## Paso 2 — META_ACCESS_TOKEN y WhatsApp (Meta Developers)

> estado: ✅ Completado (token renovado 2026-04-07)

Credenciales activas en `.env`:
- `META_ACCESS_TOKEN` ✅ renovado
- `WHATSAPP_PHONE_ID` ✅ configurado
- `META_APP_SECRET` ✅ configurado
- `META_VERIFY_TOKEN` ✅ configurado
- `meta_waba_id = 2159052118202272` ✅ en Supabase

> ⚠️ El token actual expira en ~24h. Para producción, crear un System User Token permanente — ver [IH-003] en `HUMAN_INTERVENTIONS.md`.

---

## Paso 3 — Túnel HTTPS Temporal para Pruebas (Pinggy)

> estado: ⏳ Necesario para test E2E local antes de deploy

Meta necesita una URL HTTPS pública para enviar webhooks. En desarrollo usamos Pinggy (sin cuenta, via SSH nativo).

**Terminal 1 — Iniciar el conector de WhatsApp:**
```bash
cd /home/ansible/workspaces/commerce-ops-platform/services/connector-whatsapp
export $(grep -v '^#' ../../.env | sed 's/"\(.*\)"/\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Verificar: http://localhost:8000/health → {"status":"ok"}
```

**Terminal 2 — Crear el túnel público:**
```bash
ssh -p 443 -R0:localhost:8000 a.pinggy.io
# Aparecerá una URL tipo: https://abcd1234.auto.pinggy.link
# Copiar esa URL — la necesitas en el Paso 4
```

> **Referencia oficial Pinggy**: [pinggy.io/docs/quickstart](https://pinggy.io/docs/quickstart/)  
> No requiere instalación ni cuenta. Usa SSH estándar ya disponible en la VM.

---

## Paso 4 — Registrar el Webhook en Meta Developers

> estado: ⏳ Hacer después del Paso 3

**ACCIÓN HUMANA — 5 minutos**

1. Ir a [Meta Developers](https://developers.facebook.com/apps/) → tu App → **WhatsApp** → **Configuration**
2. En la sección **Webhook**, clic en **"Edit"**
3. Completar:
   - **Callback URL**: `https://TU_URL_PINGGY/api/v1/whatsapp/webhook` (del Paso 3)
   - **Verify Token**: el valor de `META_VERIFY_TOKEN` en tu `.env`
4. Clic en **"Verify and Save"** — Meta enviará un GET al webhook, que debe responder 200
5. En la sección **Webhook Fields**, activar el campo **`messages`** con "Subscribe"

**Criterio de éxito**: El panel de Meta muestra ✅ en el campo `messages`.

> **Referencia oficial**: [Configurar Webhooks — Meta Developers](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks)

---

## Paso 5 — Test E2E Local (Ciclo Completo)

> estado: ⏳ Hacer después de Pasos 3 y 4, y después de tener GEMINI_API_KEY

**Terminal 1** — WhatsApp Connector (ya corriendo desde Paso 3)

**Terminal 2** — AI Orchestrator:
```bash
cd /home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/"\(.*\)"/\1/' | xargs)
python3 main.py
```

**Terminal 3** — Frontend Backoffice:
```bash
cd /home/ansible/workspaces/commerce-ops-platform
pnpm --filter web dev
# Accesible en: http://localhost:3000
```

**Prueba desde celular:**
1. Enviar un WhatsApp al número de prueba asignado por Meta (ej: "¿Cuánto cuesta el producto X?")
2. El flujo completo debe ejecutarse:
   - Pinggy → Connector → Supabase `messages` (processed=False)
   - Orchestrator detecta → llama Gemini con catálogo → respuesta
   - Guardrail valida → WhatsApp Cloud API envía respuesta al celular
   - Inbox en `http://localhost:3000/dashboard/inbox` muestra el hilo en tiempo real

---

## Paso 6 — Deploy en Render (Producción)

> estado: ⏳ Pendiente — requiere cuenta de Render y `render.yaml` creado

### 6.1 — Cuenta y Proyecto en Render

**ACCIÓN HUMANA — 5 minutos**

1. Ir a [render.com](https://render.com) y crear cuenta (o iniciar sesión)
2. En el Dashboard, clic en **"New +"** → **"Blueprint"**
3. Conectar el repositorio de GitHub/GitLab del proyecto
4. Render detectará automáticamente el `render.yaml` de la raíz del monorepo
5. Revisar los servicios detectados y hacer clic en **"Apply"**

> **Referencia oficial**: [Render Blueprints (Infrastructure as Code)](https://render.com/docs/blueprint-spec)

### 6.2 — Variables de Entorno en Render

**ACCIÓN HUMANA — 10 minutos**

Una vez aplicado el Blueprint, para cada servicio en Render Dashboard → **Environment**:

| Variable | Dónde obtenerla |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `.env` local |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `.env` local |
| `SUPABASE_SERVICE_ROLE_KEY` | `.env` local → **marcar como Secret** |
| `META_APP_SECRET` | `.env` local → **marcar como Secret** |
| `META_VERIFY_TOKEN` | `.env` local → **marcar como Secret** |
| `META_ACCESS_TOKEN` | Meta Developers → System User Token → **marcar como Secret** |
| `WHATSAPP_PHONE_ID` | `.env` local |
| `GEMINI_API_KEY` | Google AI Studio → **marcar como Secret** |
| `ALLOWED_ORIGINS` | URL del frontend en Render (ej: `https://commerce-ops-web.onrender.com`) |
| `POLL_INTERVAL_SECONDS` | `3` (default) |
| `GEMINI_MODEL` | `gemini-1.5-flash` (default) |

> ⚠️ Nunca pegar secrets en el `render.yaml` directamente. Usar la UI de Render o el [Render CLI](https://render.com/docs/cli).

### 6.3 — Actualizar Callback URL del Webhook

Después del deploy, el Pinggy tunnel ya no se necesita. Actualizar en Meta Developers:
- **Callback URL**: `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook`

---

## Resumen de URLs tras el Deploy

| Servicio | URL en Render |
|---|---|
| Frontend Backoffice | `https://commerce-ops-web.onrender.com` |
| WhatsApp Connector | `https://commerce-ops-connector.onrender.com` |
| AI Orchestrator | (Background Worker — sin URL pública) |

---

## Regla de Actualización

Actualizar este documento cada vez que un paso sea completado. Marcar con ✅ y la fecha.

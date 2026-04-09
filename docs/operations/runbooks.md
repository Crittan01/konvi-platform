# Runbooks Operacionales — Commerce Ops Platform

Última actualización: 2026-04-09

---

## 1. Reiniciar servicios en Render

### Síntoma
El servicio está caído, responde con error, o tiene un cold start prolongado.

### Pasos
1. Ir a [Render Dashboard](https://dashboard.render.com/)
2. Seleccionar el servicio afectado:
   - `commerce-ops-web` — Frontend
   - `commerce-ops-connector` — WhatsApp Connector
   - `commerce-ops-api` — API Gateway
   - `commerce-ops-orchestrator` — AI Worker
3. Clic en **"Manual Deploy"** → **"Deploy latest commit"**
4. O clic en **"Restart"** si el servicio ya está desplegado

### Verificación
```bash
# Health check de cada servicio
curl https://commerce-ops-connector.onrender.com/health
curl https://commerce-ops-api.onrender.com/health
```

---

## 2. Renovar META_ACCESS_TOKEN (token temporal)

### Síntoma
El AI Orchestrator falla al enviar mensajes. Error 401 en logs de Meta API.

### Cuándo ocurre
El token temporal expira en ~24h. Solo aplica hasta tener el System User Token permanente (IH-006).

### Pasos
1. Ir a [Meta Developers](https://developers.facebook.com/) → Tu App → WhatsApp → API Setup
2. Sección **"Temporary access token"** → clic en **"Generate access token"**
3. Copiar el token (empieza con `EAA...`)
4. En Render Dashboard → servicio `commerce-ops-orchestrator` → Environment
5. Actualizar variable `META_ACCESS_TOKEN` con el nuevo token
6. Render hace redeploy automático (o hacer Manual Deploy)
7. Verificar que el orchestrator retoma polling

---

## 3. Resetear variable de entorno en Render

### Síntoma
Un servicio falla con error de configuración o variable faltante.

### Pasos
1. Render Dashboard → seleccionar el servicio
2. Clic en **"Environment"** en el menú lateral
3. Localizar la variable → clic en el ícono de editar
4. Actualizar el valor → clic en **"Save Changes"**
5. Render hace redeploy automático

### Variables críticas por servicio

| Servicio | Variables críticas |
|----------|-------------------|
| `commerce-ops-connector` | `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_ACCESS_TOKEN`, `WHATSAPP_PHONE_ID`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
| `commerce-ops-orchestrator` | `GEMINI_API_KEY`, `GEMINI_MODEL`, `META_ACCESS_TOKEN`, `WHATSAPP_PHONE_ID`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
| `commerce-ops-api` | `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, `ALLOWED_ORIGINS` |
| `commerce-ops-web` | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` |

---

## 4. Aplicar migración SQL en Supabase

### Síntoma
Necesitas crear o modificar tablas/índices/funciones en la DB de producción.

### Prerrequisito
Supabase CLI instalado y proyecto vinculado:
```bash
supabase --version   # debe mostrar versión
supabase projects list   # debe mostrar ***SUPABASE_PROJECT_REF_REDACTED***
```

### Pasos
```bash
cd /home/ansible/workspaces/commerce-ops-platform

# Ejecutar SQL inline
supabase db query --linked "SELECT * FROM tenants;"

# Ejecutar archivo de migración
supabase db query --linked -f supabase/migrations/nuevo_archivo.sql

# Verificar resultado
supabase db query --linked "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'messages';"
```

> ⚠️ `psql` directo NO funciona desde esta VM (Supavisor bloquea TCP). Usar siempre `supabase db query --linked`.

---

## 5. Limpiar cache de build en Render (CSS plano / UI sin estilos)

### Síntoma
La UI del frontend se ve sin estilos CSS (HTML plano). Ocurre cuando Next.js tiene cache de transformaciones CSS desactualizado.

### Pasos
1. Render Dashboard → `commerce-ops-web`
2. Clic en **"Manual Deploy"**
3. Seleccionar **"Clear build cache & deploy"**
4. Esperar que el build completo termine
5. Verificar que la UI muestra TailwindCSS correctamente

---

## 6. Ejecutar servicios localmente

```bash
# Terminal 1 — Frontend
cd /home/ansible/workspaces/commerce-ops-platform
pnpm --filter web dev
# Acceso: http://localhost:3000

# Terminal 2 — WhatsApp Connector
cd /home/ansible/workspaces/commerce-ops-platform/services/connector-whatsapp
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Health: curl http://localhost:8000/health

# Terminal 3 — AI Orchestrator
cd /home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py

# Terminal 4 — API Gateway
cd /home/ansible/workspaces/commerce-ops-platform/services/api
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

---

## 7. Test E2E del AI Orchestrator (local)

```bash
cd /home/ansible/workspaces/commerce-ops-platform
export $(grep -v '^#' .env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 scripts/test_worker_e2e.py
# El envío a Meta API está mockeado — no requiere token activo
```

---

## Documentos relacionados

- `docs/operations/HUMAN_INTERVENTIONS.md` — Acciones que requieren humano
- `docs/deployment/DEPLOYMENT_GUIDE.md` — Guía completa de deploy
- `docs/deployment/FASE7_RENDER_DEPLOY.md` — Deploy actual en Render

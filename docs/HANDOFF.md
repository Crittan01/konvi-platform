# Handoff — Estado del Proyecto al 2026-04-09 (rev. 3)

Este documento existe para que el próximo chat de IA retome trabajo exactamente desde donde se dejó.
**Leer este archivo antes de cualquier otra acción.**

---

## Resumen del sistema

SaaS Conversacional Multi-Tenant para e-commerce vía WhatsApp.
- Tenants aislados con RLS en PostgreSQL (Supabase)
- Canal: WhatsApp Cloud API (Meta) — sin librerías no oficiales
- IA: Google Gemini via `google-genai==1.47.0` (nuevo SDK oficial)
- Hosting destino: Render.com

---

## ✅ Fases completadas (no tocar)

| Fase | Descripción | Archivos clave |
|---|---|---|
| 1 | Base monorepo pnpm | `pnpm-workspace.yaml`, `.gitignore` |
| 2 | Auth + RLS Supabase | `supabase/migrations/` (6 migraciones) |
| 3a | Backoffice Next.js | `apps/web/app/dashboard/` |
| 3b | WhatsApp Connector | `services/connector-whatsapp/` |
| 4 | AI Orchestrator | `services/ai-orchestrator/` (server.py + worker + orchestrator + guardrails) |
| 5 | Inbox AI (Realtime) | `apps/web/app/dashboard/inbox/page.tsx` |
| 6 | API Gateway real | `services/api/` (JWT real, CRUD completo) |
| 7 | Deploy Render | 4 servicios live — ver estado abajo |

> ⚠️ **`services/orchestrator/` fue eliminado el 2026-04-08** — era un prototipo obsoleto con bugs
> (async/sync mismatch, Meta API v18.0, sin graceful shutdown, sin requirements.txt).
> El directorio canónico del orchestrator es `services/ai-orchestrator/`.

---

## ✅ Fase 7 completada (PASOS 1-5) — Estado al 2026-04-09

### 4 servicios en producción (Render Free)

| Servicio | URL | Estado |
|---|---|---|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live, UI con TailwindCSS |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | (background, sin URL pública) | ✅ Live, polling cada 3s |

### Lecciones aprendidas — críticas para futuras sesiones

1. **Modelo Gemini**: `gemini-2.0-flash` NO disponible para cuentas nuevas con billing.
   Usar `gemini-2.5-flash`. Billing habilitado en Google AI Studio (free tier tenía quota=0).

2. **CSS en Render**: `NODE_ENV=production` + `npm install` omite devDependencies.
   Fix aplicado: `npm install --include=dev` en `render.yaml` buildCommand.
   Requiere: `apps/web/postcss.config.js` + `autoprefixer` en devDependencies.
   Si la UI se ve plana: **"Clear build cache & deploy"** (Next.js cachea transforms CSS — el nuevo
   `postcss.config.js` no aplica hasta rebuild limpio).

3. **badge.tsx**: `apps/web/components/ui/badge.tsx` debe estar committed. Si falta, webpack
   reporta otros módulos como no encontrados (error en cascada).

4. **OOM en Render Free (512MB)**: `NODE_OPTIONS='--max-old-space-size=460'` en buildCommand.

### Pendiente para completar Fase 7

- **PASO 6 [HUMANO]**: Meta Developers → App → WhatsApp → Configuration → Webhook
  - Callback URL: `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook`
  - Verify Token: `***META_VERIFY_TOKEN_LEGACY_REDACTED***`
  - Suscribir campo: `messages`
- **PASO 7 [HUMANO + AGENTE]**: Test E2E — enviar WhatsApp al número de prueba Meta → verificar
  respuesta automática de Gemini + hilo en Inbox AI
- **[IH-006]**: Crear System User Token permanente en Meta Business Suite (actual es ~24h)

---

## Infraestructura activa (Supabase)

- **Proyecto**: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1)
- **Tenant**: `Matriz Commerce Dev` — id `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`
- **meta_waba_id**: `2159052118202272` ✅
- **6 migraciones aplicadas** incluyendo `messages.processed BOOLEAN DEFAULT false`

Para ejecutar SQL desde la VM:
```bash
supabase db query --linked "SELECT * FROM tenants;"
supabase db query --linked -f supabase/migrations/archivo.sql
```
> `psql` directo NO funciona (Supavisor bloquea TCP desde esta IP)

---

## Credenciales y estado de tokens

| Token | Estado | Acción |
|---|---|---|
| `META_ACCESS_TOKEN` | ✅ Renovado 2026-04-08 | **⚠️ Temporal ~24h**. Para Render producción: crear System User Token permanente (IH-006) |
| `GEMINI_API_KEY` | ✅ Configurada en `.env` | Lista para deploy |
| `SUPABASE_JWT_SECRET` | ✅ Presente en `.env` | Lista para deploy |

---

## Entorno de la VM (Oracle Linux 9)

- **Sin venv** — todo con `pip3` de sistema (máquina dedicada)
- **Python**: 3.9.25 — usar `Optional[X]` no `X | None`
- **Node**: v20.20.2 via nvm, pnpm 10.33.0
- **Binarios instalados**: `supabase` CLI v2.84.2 en `/usr/local/bin/`

Paquetes Python instalados a nivel sistema — verificados 2026-04-08:
```
google-genai==1.47.0       ← SDK oficial (google-generativeai DESINSTALADO)
supabase==2.28.3           ← alineado con requirements.txt ✅
httpx==0.28.1
pydantic==2.12.5
PyJWT==2.10.1
fastapi==0.128.8           ← alineado con requirements.txt ✅
uvicorn==0.39.0            ← alineado con requirements.txt ✅
python-dotenv==1.2.1       ← alineado con requirements.txt ✅
python-multipart==0.0.20
starlette==0.49.3          ← dep transitiva de fastapi
anyio==4.12.1
git-filter-repo (pip)
```

---

## Cómo probar localmente antes del deploy

```bash
# Terminal 1 — WhatsApp Connector
cd /home/ansible/workspaces/commerce-ops-platform/services/connector-whatsapp
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Health check: curl http://localhost:8000/health

# Terminal 2 — AI Orchestrator (requiere GEMINI_API_KEY en .env)
cd /home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py

# Terminal 3 — Frontend
cd /home/ansible/workspaces/commerce-ops-platform
pnpm --filter web dev
# Acceso: http://localhost:3000
```

---

## Documentos de referencia en el repo

| Archivo | Contenido |
|---|---|
| `AGENTS.md` | **Estado del sistema vigente** — leer primero siempre |
| `docs/architecture/modules.md` | Estado de cada módulo |
| `docs/roadmap/implementation-phases.md` | Avance por fases |
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-001 a IH-004 con estado |
| `docs/deployment/DEPLOYMENT_GUIDE.md` | Guía paso a paso para deploy |
| `docs/setup/development_environment.md` | Setup de la VM |
| `render.yaml` | Infraestructura como código para Render |

---

## Decisiones de diseño importantes (no revertir)

1. **Sin `.venv`** en esta VM — todo pip3 sistema (máquina dedicada al proyecto)
2. **Supabase CLI `--linked`** para DDL — psql TCP bloqueado por Supavisor
3. **Polling activo** en el Orchestrator (no Realtime) — más simple para Render worker
4. **Soft delete** en productos (`is_active=False`) — para mantener historial de pedidos
5. **SDK Gemini**: `google-genai==1.47.0` (nuevo) — no usar `google-generativeai` (deprecado)
6. **Python 3.9 compatible** — usar `Optional[X]` en type hints, no `X | None`
7. **`git-filter-repo`** ya instalado en VM para limpiar archivos pesados del historial

---

## Rama activa

`develop` → `origin/develop` en `https://github.com/Crittan01/commerce-ops-platform`

Last commit: `c6d644f` — "fix: remove node_modules from git tracking"

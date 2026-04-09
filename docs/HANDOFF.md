# Handoff — Estado del Proyecto al 2026-04-08 (rev. 2)

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

> ⚠️ **`services/orchestrator/` fue eliminado el 2026-04-08** — era un prototipo obsoleto con bugs
> (async/sync mismatch, Meta API v18.0, sin graceful shutdown, sin requirements.txt).
> El directorio canónico del orchestrator es `services/ai-orchestrator/`.

---

## ⏳ Siguiente tarea — Fase 7: Deploy en Render

**Bloqueante humano [IH-004]:** Requiere cuenta Render.com con el repositorio conectado.

### Pasos exactos

1. **Humano** → ir a [render.com](https://render.com) → "New +" → "Blueprint" → conectar el repo `Crittan01/commerce-ops-platform`
2. Render detectará `render.yaml` en la raíz → 3 servicios aparecerán:
   - `commerce-ops-web` (Next.js — web service)
   - `commerce-ops-connector` (FastAPI — web service)
   - `commerce-ops-orchestrator` (Python — background worker)
3. **Humano** → configurar env vars secretas en Render Dashboard para cada servicio (ver tabla en `docs/deployment/DEPLOYMENT_GUIDE.md` → Paso 6.2)
4. **Agente** → verificar que los servicios levantan y hacer smoke test

### Variables críticas que el humano debe poner en Render

```
NEXT_PUBLIC_SUPABASE_URL       = (del .env local)
NEXT_PUBLIC_SUPABASE_ANON_KEY  = (del .env local)
SUPABASE_SERVICE_ROLE_KEY      = (del .env local) ← SECRET
SUPABASE_JWT_SECRET            = (del .env local) ← SECRET
META_ACCESS_TOKEN              = (del .env local) ← SECRET, renovar a System User Token
META_APP_SECRET                = (del .env local) ← SECRET
META_VERIFY_TOKEN              = (del .env local) ← SECRET
WHATSAPP_PHONE_ID              = (del .env local)
GEMINI_API_KEY                 = (Google AI Studio) ← SECRET, PENDIENTE
ALLOWED_ORIGINS                = https://commerce-ops-web.onrender.com
```

---

## Infraestructura activa (Supabase)

- **Proyecto**: `xmelwnhhphksbpdjmbbp` (us-east-1)
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
| `META_ACCESS_TOKEN` | Renovado 2026-04-07 ~16:41 CDT (~24h) — **⚠️ verificar si expiró** | Renovar en Meta Developers → App → WhatsApp → API Setup. Para Render: migrar a System User Token (IH-006) |
| `GEMINI_API_KEY` | ✅ Configurada en `.env` | Verificar antes de deploy en Render |
| `SUPABASE_JWT_SECRET` | ⚠️ Pendiente obtener (IH-005) | Supabase Dashboard → Project Settings → Data API → JWT Secret |

---

## Entorno de la VM (Oracle Linux 9)

- **Sin venv** — todo con `pip3` de sistema (máquina dedicada)
- **Python**: 3.9.25 — usar `Optional[X]` no `X | None`
- **Node**: v20.20.2 via nvm, pnpm 10.33.0
- **Binarios instalados**: `supabase` CLI v2.84.2 en `/usr/local/bin/`

Paquetes Python instalados a nivel sistema:
```
google-genai==1.47.0    ← SDK NUEVO (no usar google-generativeai — deprecado)
supabase==2.10.0        ← ⚠️ VM tiene 2.10.0, requirements.txt usa 2.28.3
httpx==0.28.1
pydantic==2.12.5
PyJWT==2.10.1
fastapi==0.115.12
uvicorn[standard]==0.34.0
python-dotenv==1.0.1
git-filter-repo (pip)
```

> Para alinear supabase en la VM: `pip3 install supabase==2.28.3`

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

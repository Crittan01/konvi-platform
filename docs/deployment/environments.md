# Entornos de Deployment — Commerce Ops Platform

Última actualización: 2026-04-16

---

## Entornos activos

| Entorno | URL | Rama | Auto-deploy |
|---------|-----|------|------------|
| **Producción** | `https://commerce-ops-web.onrender.com` | `main` | ✅ Sí — Render |
| **Desarrollo local** | `http://localhost:3000` (web) / `:8000` (connector) / `:8001` (api) | cualquier | Manual |

> No hay entorno de staging configurado. Render PRs no activan blueprints en Free plan.

---

## Producción (Render)

- 4 servicios en Render Free plan (ver `render.yaml`)
- AutoDeploy activado desde `origin/main`
- Variables de entorno gestionadas en Render Dashboard (NO en el repo)
- Supabase Cloud `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1) como DB/Auth

**Deploy manual:**
```
Render Dashboard → Servicio → Manual Deploy → Deploy latest commit
```

**Clear build cache (si CSS plano):**
```
Render Dashboard → commerce-ops-web → Manual Deploy → Clear build cache & deploy
```

---

## Desarrollo local

```bash
# Frontend (Next.js)
pnpm --filter web dev
# → http://localhost:3000

# WhatsApp Connector
cd services/connector-whatsapp
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# API Gateway
cd services/api
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# AI Orchestrator
cd services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3 main.py
```

Variables de entorno locales: copiar `.env.example` → `.env` y completar los valores.

---

## Variables requeridas por entorno

| Variable | Local | Render |
|----------|-------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | ✅ En `.env` | ✅ Render env |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | ✅ En `.env` | ✅ Render env |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ En `.env` | ✅ Render env |
| `SUPABASE_JWT_SECRET` | ✅ En `.env` | ✅ Render env |
| `META_ACCESS_TOKEN` | ✅ En `.env` | ✅ Render env |
| `GEMINI_API_KEY` | ✅ En `.env` | ✅ Render env |
| `APP_URL` | Local: `http://localhost:3000` | Fijo en render.yaml |
| `ALLOWED_ORIGINS` | Local: `http://localhost:3000` | Render env (`https://commerce-ops-web.onrender.com`) |

---

## Próximos pasos de entorno

- **Staging**: Crear entorno Render Starter para validación pre-merge. No implementado — ver `render-upgrade-path.md`.
- **Custom domain**: Pendiente dominio propio. Impacta SMTP Supabase (IH-SMTP).

# Arquitectura de Deployment — Render + Supabase

Última actualización: 2026-04-16

---

## Visión general

| Capa | Plataforma | Estado |
|------|-----------|--------|
| Frontend (Next.js) | Render — Web Service (Node) | ✅ Live |
| WhatsApp Connector (FastAPI) | Render — Web Service (Python) | ✅ Live |
| API Gateway (FastAPI) | Render — Web Service (Python) | ✅ Live |
| AI Orchestrator (FastAPI + daemon thread) | Render — Web Service (Python) | ✅ Live |
| Base de datos + Auth + Realtime | Supabase Cloud (us-east-1) | ✅ Live |

> Nota: El frontend vive en **Render**, no en Vercel. Todo el stack está en Render.

---

## Servicios en Render

| Servicio Render | Origen en repo | URL | Plan |
|----------------|---------------|-----|------|
| `commerce-ops-web` | `apps/web` | `https://commerce-ops-web.onrender.com` | Free |
| `commerce-ops-connector` | `services/connector-whatsapp` | `https://commerce-ops-connector.onrender.com` | Free |
| `commerce-ops-api` | `services/api` | `https://commerce-ops-api.onrender.com` | Free |
| `commerce-ops-orchestrator` | `services/ai-orchestrator` | (solo `/health` interno) | Free |

Toda la configuración IaC está en `render.yaml` en la raíz del repo.
Render detecta el archivo automáticamente y despliega en cada push a `main`.

---

## Supabase

- **Proyecto**: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1)
- **Migraciones**: 25 aplicadas — fuente canónica en `supabase/migrations/`
- **Auth**: Supabase Auth + SSR (`@supabase/ssr`)
- **Realtime**: Activo para `messages` y `conversations` (Inbox)
- **RLS**: Activo en todas las tablas del esquema `public`
- **Storage**: Bucket `tenant-media` (archivos de catálogo/media)

### Comandos SQL seguros

```bash
# psql TCP NO funciona desde esta VM (Supavisor bloquea)
# Usar siempre:
supabase db query --linked -f supabase/migrations/archivo.sql
supabase db query --linked "SELECT * FROM tenants;"
```

---

## Variables de entorno por servicio

Ver `render.yaml` para la lista completa. Las marcadas `sync: false` deben configurarse
manualmente en Render Dashboard → Environment.

| Variable | Servicio | Notas |
|----------|---------|-------|
| `NEXT_PUBLIC_SUPABASE_URL` | web, connector | URL pública Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | web | Key anónima (pública, segura) |
| `SUPABASE_SERVICE_ROLE_KEY` | web, connector, api, orchestrator | NUNCA exponer con NEXT_PUBLIC_ |
| `SUPABASE_JWT_SECRET` | api | Para validar JWTs en FastAPI |
| `META_ACCESS_TOKEN` | connector, orchestrator | Token permanente System User |
| `GEMINI_API_KEY` | orchestrator | Billing activo requerido |
| `ALLOWED_ORIGINS` | api | CORS — `https://commerce-ops-web.onrender.com` |
| `APP_URL` | web | Para invite flow — ya fijo en render.yaml |

---

## Limitaciones del plan Free

Ver análisis completo en `docs/deployment/render-upgrade-path.md`.

Resumen: cold starts de 15-30s, sin workers nativos, 512MB RAM (workarounds en render.yaml).
Para producción con tenants reales se recomienda Starter ($7/servicio/mes).

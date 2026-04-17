# Secrets y Configuración — Commerce Ops Platform

Última actualización: 2026-04-16

---

## Política de secrets

- `.env` **NUNCA** al repositorio (está en `.gitignore`)
- En producción (Render): variables configuradas manualmente en Render Dashboard → Environment
- Localmente: `.env` en la raíz del monorepo (copiar de `.env.example`)
- **No se usa** 1Password, Doppler ni Supabase Vault en el estado actual (Free plan)

---

## Mapa de variables por servicio

### Frontend — `commerce-ops-web` (`apps/web`)

| Variable | Tipo | Fuente |
|----------|------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | Pública (baked en build) | Supabase Dashboard → Project Settings → API |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Pública (baked en build) | Supabase Dashboard → Project Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | **Secreta — nunca NEXT_PUBLIC_** | Supabase Dashboard → Project Settings → API |
| `APP_URL` | Valor fijo en render.yaml | `https://commerce-ops-web.onrender.com` |
| `API_URL` | Valor fijo en render.yaml | `https://commerce-ops-api.onrender.com` |
| `MELI_CLIENT_ID` | Secreta | Meta Developers → MeLi App |
| `MELI_REDIRECT_URI` | Valor | `https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback` |
| `MELI_AUTH_URL` | Valor | `https://auth.mercadolibre.com.co/authorization` |

### WhatsApp Connector — `commerce-ops-connector`

| Variable | Tipo | Fuente |
|----------|------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | Ref | Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | **Secreta** | Supabase |
| `META_APP_SECRET` | **Secreta** | Meta Developers → App Settings → Basic |
| `META_VERIFY_TOKEN` | Secreta | Definido por nosotros al configurar webhook |
| `META_ACCESS_TOKEN` | **Secreta** | System User Token permanente (`commerce-ops`) |
| `WHATSAPP_PHONE_ID` | Valor | Meta Developers → WhatsApp → API Setup |

### API Gateway — `commerce-ops-api`

| Variable | Tipo | Fuente |
|----------|------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | Ref | Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | **Secreta** | Supabase |
| `SUPABASE_JWT_SECRET` | **Secreta** | Supabase Dashboard → Project Settings → Data API → JWT Secret |
| `ALLOWED_ORIGINS` | Valor | `https://commerce-ops-web.onrender.com,http://localhost:3000` |
| `MELI_CLIENT_ID` | Secreta | MeLi Developers |
| `MELI_CLIENT_SECRET` | **Secreta** | MeLi Developers |

### AI Orchestrator — `commerce-ops-orchestrator`

| Variable | Tipo | Fuente |
|----------|------|--------|
| `NEXT_PUBLIC_SUPABASE_URL` | Ref | Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | **Secreta** | Supabase |
| `META_ACCESS_TOKEN` | **Secreta** | System User Token permanente |
| `WHATSAPP_PHONE_ID` | Valor | Meta Developers |
| `GEMINI_API_KEY` | **Secreta** | Google AI Studio |
| `GEMINI_MODEL` | Valor fijo en render.yaml | `gemini-2.5-flash` |
| `POLL_INTERVAL_SECONDS` | Valor fijo en render.yaml | `3` |

---

## Tokens y credenciales activas

| Token | Estado | Notas |
|-------|--------|-------|
| `META_ACCESS_TOKEN` | ✅ Permanente | System User `commerce-ops`, sin expiración |
| `GEMINI_API_KEY` | ✅ Activa | Billing habilitado en Google Cloud |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ Activa | Bypasea RLS — solo usar en contextos privilegiados |
| `SUPABASE_JWT_SECRET` | ✅ Activa | Para validar JWTs en API Gateway |
| `MeLi OAuth tokens` | ✅ Por tenant | Guardados en `tenant_integrations.credentials` |
| `Envia API key` | ✅ Por tenant | Guardados en `tenant_integrations.credentials` |

---

## Rotación de credentials

- `META_ACCESS_TOKEN`: Permanente (System User) — no requiere rotación programática
- `GEMINI_API_KEY`: Rotar si hay sospecha de compromiso (Google AI Studio → API Keys)
- `SUPABASE_SERVICE_ROLE_KEY`: Rotar en Supabase Dashboard → Project Settings → API (requiere redeploy de todos los servicios)
- `SUPABASE_JWT_SECRET`: No rotar sin causa — invalida todos los JWTs activos

---

## Gestión futura de secrets

Para producción multi-tenant con volumen real, evaluar:
- **Doppler** o **Infisical**: sync automático a Render en rotación
- **Supabase Vault**: para credentials de integraciones por tenant (MeLi, Envia)

Actualmente fuera de scope — ver `docs/risks/open-questions.md` para decisiones pendientes.

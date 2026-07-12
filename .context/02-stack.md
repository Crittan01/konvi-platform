# Stack Técnico Real

> Verificar siempre en `apps/web/package.json` y `services/*/requirements.txt`. No asumir versiones.

## Frontend — `apps/web`

| Elemento | Versión real |
|---------|-------------|
| Next.js | **15.5.20** (App Router, Server Actions, Server Components) |
| React | ^19 |
| TypeScript | ^5 |
| TailwindCSS | ^3.3.0 |
| `@supabase/ssr` | ^0.10.0 |
| shadcn/ui | 11 componentes en `apps/web/components/ui/` |

⚠️ `packages/ui` está vacío. Los componentes UI viven en `apps/web/components/ui/`.

## Backend — servicios Python

| Elemento | Versión real |
|---------|-------------|
| Python (VM) | **3.11.13 disponible** (`/usr/bin/python3.11`) y `python3` actualmente apunta a 3.9.25 |
| FastAPI | 0.128.8 |
| Pydantic | 2.12.5 |
| google-genai | 1.47.0 — SDK oficial Gemini (no usar `google-generativeai`) |
| supabase-py | 2.28.3 |
| httpx | 0.28.1 |
| PyJWT | 2.10.1 |
| GEMINI_MODEL | `gemini-3.1-flash-lite` (prod, render.yaml) · default en código `gemini-3.5-flash` · cascade a Claude rescue |

## Infraestructura

- **DB/Auth**: Supabase PostgreSQL + RLS + Auth + Realtime
- **Hosting**: Render (Free plan dev → Starter antes de producción)
- **Monorepo**: pnpm workspaces
- **SQL**: `supabase db query --linked -f archivo.sql` (psql TCP bloqueado por Supavisor)
- **Supabase CLI**: **2.90.0** — binario nativo en `/usr/local/bin/supabase`

## VM — Política de herramientas nativas

Esta VM es dedicada 100% al proyecto. Todas las herramientas del sistema se instalan **nativas** — sin venv, sin pipx, sin brew, sin contenedores locales.

| Herramienta | Instalación | Actualización |
|---|---|---|
| Python 3.11.13 | dnf (sistema) | `sudo dnf upgrade python3` |
| Node 20.x | nvm | `nvm install --lts` |
| pnpm | npm global | `npm i -g pnpm` |
| Supabase CLI | binario estático `/usr/local/bin/` | `curl releases GitHub → sudo mv /usr/local/bin/supabase` |

**Regla operativa:** ejecutar servicios/tests Python con `python3.11` hasta alinear el alias `python3` al runtime objetivo.

## Servicios — VM local (Render en freeze)

Render se mantiene en **freeze** hasta que se retome producción. Toda prueba corre en VM local con un `Makefile` orquestador.

| Comando | Acción |
|---|---|
| `make -C /home/ansible/commerce-ops-local up` | Levanta api + connector + orchestrator + web + tunnels ngrok |
| `make -C /home/ansible/commerce-ops-local down` | Para todo |
| `make -C /home/ansible/commerce-ops-local restart` | Reinicia todo |
| `make -C /home/ansible/commerce-ops-local stop-orchestrator` | Para solo el orchestrator (ej. para recargar código) |
| `make -C /home/ansible/commerce-ops-local start-orchestrator` | Levanta solo el orchestrator |
| `make -C /home/ansible/commerce-ops-local status` | Estado de procesos |
| `make -C /home/ansible/commerce-ops-local print-urls` | URLs de webhooks ngrok |

**Ubicaciones:**

- Logs: `/home/ansible/commerce-ops-local/logs/{orchestrator,api,connector,web}.log`
- PIDs: `/home/ansible/commerce-ops-local/pids/`
- `.env` que cargan los servicios: `/home/ansible/workspaces/konvi-platform/.env` (raíz del repo)

**Importante** — cambios de código en `services/ai-orchestrator/*.py` requieren reiniciar el orchestrator. Cambios en `.env` (env vars) son leídos al inicio del proceso, **excepto los flags hot-reload** (ver `USE_NEW_ORCHESTRATOR` que se relee por cada llamada).

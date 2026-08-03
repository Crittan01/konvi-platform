# Stack Técnico Real

> Verificar siempre en `apps/web/package.json` y `services/*/requirements.txt`. No asumir versiones.
> **Verificado contra repo**: 2026-08-02 @ `5fdad396` (develop).

## Frontend — `apps/web`

| Elemento | Versión real |
|---------|-------------|
| Next.js | **16.2.11** (App Router, Server Actions, Server Components) |
| React | ^19 |
| TypeScript | ^5 |
| TailwindCSS | **4.3.3** (tokens en `globals.css` `@theme inline`, sin `tailwind.config`) |
| `@supabase/ssr` | ^0.12.1 |
| shadcn/ui | **20 componentes + `empty-state` + `motion`** en `apps/web/components/ui/` |
| Deps UX (2026-08-02) | `framer-motion` ^12, `cmdk` ^1, `vaul` ^1, `embla-carousel-react` ^8, `@tanstack/react-virtual` ^3 |

⚠️ `packages/ui` está vacío. Los componentes UI viven en `apps/web/components/ui/`.

## Backend — servicios Python

| Elemento | Versión real |
|---------|-------------|
| Python (VM) | **3.11.13 disponible** (`/usr/bin/python3.11`) y `python3` actualmente apunta a 3.9.25 |
| FastAPI | **0.139.0** (api + ai-orchestrator) · connector-whatsapp 0.128.8 (drift menor, alinear) |
| Pydantic | **2.13.4** (api + ai-orchestrator) · connector-whatsapp 2.12.5 |
| google-genai | **2.11.0** — SDK oficial Gemini (no usar `google-generativeai`) |
| supabase-py | **2.31.0** (api + ai-orchestrator) · connector-whatsapp 2.28.3 |
| httpx | 0.28.1 |
| PyJWT | **2.13.0** |
| Modelos Gemini | 3.x — primario prod `gemini-3.1-flash-lite` (render.yaml); default de código unificado 2026-08-02. Rescate Claude **eliminado** (2026-08-02: `anthropic` nunca estuvo instalado) |

## Infraestructura

- **DB/Auth**: Supabase PostgreSQL + RLS + Auth + Realtime — 251 migraciones = ledger prod, 79 tablas live, cero drift
- **Hosting**: Render (Free plan dev → Starter antes de producción)
- **Monorepo**: pnpm workspaces
- **SQL**: `supabase db query --linked -f archivo.sql` (psql TCP bloqueado por Supavisor)
- **Supabase CLI**: **2.90.0** — binario nativo en `/usr/local/bin/supabase`
- **Tests**: 4.298 pytest colectados (201 dbharness) + 31 archivos Vitest

## VM — Política de herramientas nativas

Esta VM es dedicada 100% al proyecto. Todas las herramientas del sistema se instalan **nativas** — sin venv, sin pipx, sin brew, sin contenedores locales.

| Herramienta | Instalación | Actualización |
|---|---|---|
| Python 3.11.13 | dnf (sistema) | `sudo dnf upgrade python3` |
| Node **22** (`.nvmrc`) | nvm — instalada v22.23.1 | `nvm install --lts` |
| pnpm | npm global | `npm i -g pnpm` |
| Supabase CLI | binario estático `/usr/local/bin/` | `curl releases GitHub → sudo mv /usr/local/bin/supabase` |

**Node — realidad verificada 2026-08-02:** el repo declara Node **22** en `.nvmrc` y v22.23.1 está instalada, pero el alias default de nvm en la VM sigue apuntando a v20.20.2 (los docs decían "Node 20.x" — stale). **Recomendación**: alinear el alias default a 22 (`nvm alias default 22`) para que shells nuevos usen la versión del repo.

**Regla operativa:** ejecutar servicios/tests Python con `python3.11` hasta alinear el alias `python3` al runtime objetivo.

## Servicios — VM local + Render productivo

**Render está LIVE** (ya NO en freeze). La rama `production` autodespliega los 4 servicios; hubo múltiples deploys a producción en jul-2026 (iniciativa production-grade bloques 0→H). El desarrollo/UAT dinámico corre en la VM local con un `Makefile` orquestador; localhost comparte la MISMA Supabase productiva.

| Comando | Acción |
|---|---|
| `make -C /home/ansible/workspaces/konvi-platform/.local up` | Levanta api + connector + orchestrator + web + tunnels ngrok |
| `make -C /home/ansible/workspaces/konvi-platform/.local down` | Para todo |
| `make -C /home/ansible/workspaces/konvi-platform/.local restart` | Reinicia todo |
| `make -C /home/ansible/workspaces/konvi-platform/.local stop-orchestrator` | Para solo el orchestrator (ej. para recargar código) |
| `make -C /home/ansible/workspaces/konvi-platform/.local start-orchestrator` | Levanta solo el orchestrator |
| `make -C /home/ansible/workspaces/konvi-platform/.local status` | Estado de procesos |
| `make -C /home/ansible/workspaces/konvi-platform/.local print-urls` | URLs de webhooks ngrok |

**Ubicaciones:**

- Logs: `/home/ansible/workspaces/konvi-platform/.local/logs/{orchestrator,api,connector,web}.log`
- PIDs: `/home/ansible/workspaces/konvi-platform/.local/pids/`
- `.env` que cargan los servicios: `/home/ansible/workspaces/konvi-platform/.env` (raíz del repo)

**Importante** — cambios de código en `services/ai-orchestrator/*.py` requieren reiniciar el orchestrator. Cambios en `.env` (env vars) son leídos al inicio del proceso, **excepto los flags hot-reload** (ver `USE_NEW_ORCHESTRATOR` que se relee por cada llamada).

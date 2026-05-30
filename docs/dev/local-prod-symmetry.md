# Simetría dev local ↔ Render prod

**Objetivo**: ambiente local de desarrollo se comporta IDÉNTICO a Render producción para evitar bugs "dev OK / prod KO" (ej. commit `ee4e707` — tres bugs latentes que rompían `next build` no detectados en `next dev --turbo`).

**Estado actual**: ~70%. Este doc lleva a 95%. El 5% restante es asimetría inherente Next.js Turbopack (dev) vs webpack (prod) — mitigada con disciplina pre-PR.

---

## 5 capas de simetría

### Capa A — Código + dependencias ✅

| Aspecto | Cómo se sincroniza |
|---|---|
| Git branch | Local trabaja en `phase-2-agentic-rewrite` o feature branches. Render auto-deploy desde `develop` (staging) o `main` (prod). Mientras no se mergea a `develop`/`main`, NO hay deploy automático. |
| `pnpm-lock.yaml` | Commited. Render usa `pnpm install --frozen-lockfile`. Local DEBE usar lo mismo (script `sync-local.sh` lo enforca). |
| `requirements.txt` | Commited per servicio. Render hace `pip install -r requirements.txt`. Local hace lo mismo via `sync-local.sh`. |
| Node/Python versions | Pin en `render.yaml` (Node 20, Python 3.11). Local usa nvm/pyenv con misma versión. |

**Drift principal detectado**: cuando mergeas PRs con nuevas deps (ej. `@sentry/nextjs` post-PR #6), local NO auto-instala. Solución: correr `bash scripts/sync-local.sh` después de CADA `git pull`.

### Capa B — Runtime ⚠️ (asimetría intrínseca)

| Aspecto | Local | Render |
|---|---|---|
| Frontend runtime | `next dev --turbo` (Turbopack) | `next start` (webpack/SWC compiled) |
| Compile checks | laxas (Turbopack tolera más) | estrictas (webpack falla por `any` mal tipado, missing imports, type narrow violations) |
| Hot reload | sí | no |
| Backend (FastAPI) | `uvicorn --reload` | `uvicorn` sin reload |

**Por qué no podemos arrancar local con webpack**: hot reload se rompe → DX intolerable. Aceptamos esta asimetría.

**Mitigación**: pre-validar el build de producción ANTES de cada PR:

```bash
bash scripts/validate.sh --build
```

Esto corre Next.js `build` completo y detecta los problemas que Turbopack permite pero webpack rechaza. CI lo corre también automáticamente en cada PR (`.github/workflows/ci.yml`), pero pre-validar localmente ahorra ciclos de "push → CI rojo → fix → push otra vez".

### Capa C — Variables de entorno ⚠️ (disciplina manual)

| Aspecto | Cómo se gestiona |
|---|---|
| `.env.example` (commited) | Documenta TODAS las vars con marcadores `[LOCAL]/[RENDER]/[DB]/[DEPRECATED]`. Fuente única de verdad. |
| `.env` (root, NOT commited) | Local backend (Python). Cubre vars sin prefix `NEXT_PUBLIC_`. |
| `apps/web/.env.local` (NOT commited) | Local frontend (Next.js). Cubre `NEXT_PUBLIC_*`. |
| `render.yaml` (commited) | Define structure de env vars per servicio. Valores reales se cargan en Render Dashboard como secrets. |
| Render Dashboard | Valores reales (production secrets). |

**Drift principal**: cuando alguien añade una var nueva al código, `sync-local.sh` la detecta como faltante en `.env` o `apps/web/.env.local`. Para Render: añadir manualmente en Dashboard ANTES de mergear a `main`.

**Convención**: PRs que añadan vars nuevas DEBEN actualizar `.env.example` con marcadores correctos.

### Capa D — Servicios externos ✅ (mismo proyecto, distintos modos)

| Servicio | Local | Render |
|---|---|---|
| Supabase | mismo proyecto `***SUPABASE_PROJECT_REF_REDACTED***` (compartido) | mismo proyecto |
| Webhooks inbound | ngrok URLs `*.ngrok-free.app` (cuentas separadas: api + connector-whatsapp) | dominio Render `*.onrender.com` |
| Wompi | sandbox keys | prod keys (por tenant en Vault) |
| Meta WhatsApp | tenant test (UAT) | tenants prod (multi-WABA) |
| MercadoLibre | OAuth sandbox | OAuth prod |
| Envia | sandbox per tenant | prod per tenant |

**Convención multi-tenant**: cada tenant trae sus credenciales en `tenant_integrations.meta` (Vault Supabase). Ningún secret de provider sale al `.env`. Esto garantiza que local y prod difieren solo en WHICH tenant tienen activo, no en HOW se autentican.

### Capa E — Telemetría ✅ (post PR #6 Sentry)

| Aspecto | Local | Render |
|---|---|---|
| Sentry DSN | `SENTRY_DSN` apunta a proyecto Sentry con `SENTRY_ENV=development` | mismo DSN con `SENTRY_ENV=production` |
| Filtrado | Sentry dashboard filtra por `environment` tag | dashboard idem |
| Source maps | NO (dev usa source maps inline) | SÍ (upload via `SENTRY_AUTH_TOKEN` en build step) |

**Beneficio**: errores prod se ven side-by-side con errores dev en `sentry.io/organizations/konvi/`. Facilita reproducir bugs.

---

## Workflow disciplinado (para mantener 95%+ simetría)

### Cada `git pull`

```bash
bash scripts/sync-local.sh
```

Cubre:
- Instala deps Node + Python con lockfile
- Verifica `.env` + `apps/web/.env.local` cubren lo declarado en `.env.example`
- Recuerda recurrir a `validate.sh --build` antes de PR

### Antes de cada PR

```bash
bash scripts/validate.sh --build
```

Corre:
- 1490+ tests Python pytest
- TypeScript compile check
- Ruff lint Python (con baseline)
- ESLint frontend
- pip-audit Python (vulnerabilities)
- Next.js `build` completo (detecta gaps Turbopack vs webpack)

### Después de cada merge a `develop`/`main`

Render hace auto-deploy. Verificar:

1. **Render Dashboard logs** del servicio recién desplegado — buscar errores de startup
2. **`/health` endpoint** de cada servicio — 200 OK
3. **Sentry**: filtrar por release tag, verificar 0 errors críticos en primeros 10 min
4. **Si hay vars nuevas en el PR**: añadirlas al Render Dashboard ANTES del deploy (sino arranca con valores default que pueden ser inseguros)

### Cuando añadas una variable de entorno nueva

Checklist:
- [ ] Añadirla a `.env.example` con marcador `[LOCAL]/[RENDER]/[BOTH]`
- [ ] Añadir a `.env` local (root) si es backend, o `apps/web/.env.local` si es frontend
- [ ] Añadir a `render.yaml` (structure) Y al Render Dashboard (valor real)
- [ ] Documentar en el PR description

---

## Cuándo NO podemos llegar a 100%

| Asimetría inevitable | Por qué |
|---|---|
| Turbopack vs webpack | Cambiar local a webpack mata hot reload (DX intolerable). Aceptamos + mitigamos con `validate.sh --build`. |
| ngrok vs domain Render | Webhooks externos necesitan URL pública. ngrok free tier es la opción dev. Wompi/Meta/MeLi distinguen sandbox vs prod, no host. |
| Render Free vs Starter | Plan K J.2.7.8 — migrar a Starter ($28/mo) antes de go-live. Hoy Free tiene cold starts y RAM limits. |
| sandbox keys vs prod keys | Wompi/Meta/MeLi: usar prod en local arriesga datos reales. Sandbox es la práctica correcta. |

---

## Detección de drift en CI

`.github/workflows/ci.yml` corre `validate.sh --ci` en cada PR. Bloquea merge si:

- `pnpm-lock.yaml` no commited / mismatch con `package.json`
- TypeScript no compila
- Tests Python fallan
- Next.js build falla
- Ruff regresión sobre baseline
- pip-audit detecta vulnerabilities

Esto cierra la categoría de drift estructural. El drift de env vars NO se valida en CI (depende de cada deploy target) — por eso `sync-local.sh` es manual + reglas operacionales en este doc.

---

## Referencias

- Script: [`scripts/sync-local.sh`](../../scripts/sync-local.sh)
- Validate: [`scripts/validate.sh`](../../scripts/validate.sh) — `--ci`, `--build`, `--full`, `--coverage`, `--lint`
- Env reference: [`.env.example`](../../.env.example)
- Render config: [`render.yaml`](../../render.yaml)
- Sentry setup: [`docs/observability/sentry-setup.md`](../observability/sentry-setup.md)

# TRD — Technical Requirements Document — Konvi Platform

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

SaaS multi-tenant de operaciones e-commerce conversacionales vía WhatsApp (B2B2C, foco Colombia).
Este documento fija los requisitos técnicos del sistema **tal como están implementados** — cada
afirmación tiene evidencia `archivo:línea` verificada contra el código en la fecha de la cabecera.
Los documentos de contexto histórico (`.context/02-stack.md`, `AGENTS.md`) contienen versiones
**stale**; donde difieran, manda este TRD (ver §1.3).

---

## 1. Stack real verificado

### 1.1 Tabla canónica

| Capa | Componente | Versión real | Evidencia |
|---|---|---|---|
| Frontend | Next.js | **16.2.11** | `apps/web/package.json:30` |
| Frontend | React | ^19 | `apps/web/package.json:31-32` |
| Frontend | TypeScript | ^5 | `apps/web/package.json:52` |
| Frontend | TailwindCSS | **^4.3.3** (v4: sin `tailwind.config`, tokens en `@theme inline`) | `apps/web/package.json:26,36`; `apps/web/app/globals.css:1,11` |
| Frontend | Componentes UI | 21 componentes propios (shadcn-style) + 1 test | `apps/web/components/ui/` (22 archivos, incl. `badge.test.tsx`) |
| Frontend | Tests | Vitest ^4.1.10 | `apps/web/package.json:53` |
| Runtime JS | Node | **22** (CI y prod; Render corre 22.22.0 en konvi-web) | `.nvmrc` (=22); `.github/workflows/ci.yml:19-23` |
| Runtime JS | pnpm | **10.34.4** (corepack shim en Render, `--frozen-lockfile`) | `ci.yml:24`; `render.yaml:45-46` |
| Backend | Python | **3.11.13** (VM y CI `PYTHON_VERSION=3.11`) | `python3.11 --version`; `ci.yml:18` |
| Backend API/Orch | FastAPI | **0.139.0** | `services/api/requirements.txt:1`; `services/ai-orchestrator/requirements.txt:7` |
| Backend Connector | FastAPI | 0.128.8 (divergencia intencional, ver §1.2) | `services/connector-whatsapp/requirements.txt:1` |
| Backend API/Orch | pydantic | 2.13.4 | `services/api/requirements.txt:3`; `services/ai-orchestrator/requirements.txt:4` |
| Backend API/Orch | supabase-py | 2.31.0 | `services/api/requirements.txt:4`; `services/ai-orchestrator/requirements.txt:5` |
| Backend API/Orch | PyJWT | 2.13.0 | `services/api/requirements.txt:8`; `services/ai-orchestrator/requirements.txt:3` |
| Backend API/Orch | google-genai | 2.11.0 | `services/api/requirements.txt:10`; `services/ai-orchestrator/requirements.txt:1` |
| Backend (todos) | httpx | 0.28.1 | `services/api/requirements.txt:7`; `services/ai-orchestrator/requirements.txt:2`; `services/connector-whatsapp/requirements.txt:7` |
| IA | Modelos Gemini (runtime) | `GEMINI_MODEL=gemini-3.1-flash-lite` en prod (web + orchestrator); embeddings `gemini-embedding-2` (3072-dim) | `render.yaml:88-89,359-360,241-243,369-371` |
| DB/Auth | Supabase | PostgreSQL + RLS + Auth + Realtime + Vault + pgmq | `render.yaml` (env vars); `.context/06-contracts.md` §4,§7,§11 |
| Herramienta | Supabase CLI | **2.90.0** (binario nativo `/usr/local/bin/supabase`; CI pinea la misma) | `supabase --version`; `ci.yml:264` |

### 1.2 Divergencia de versiones por servicio (intencional)

`services/connector-whatsapp` corre su propio pin más viejo (FastAPI 0.128.8 / pydantic 2.12.5 /
supabase-py 2.28.3 — `services/connector-whatsapp/requirements.txt`). Es un
deploy unit independiente con deps mínimas (no usa PyJWT ni google-genai). El CI tiene un job
dedicado (`py-core`, `ci.yml:193-234`) que corre los tests de api+orchestrator bajo **sus** pins de
prod (FastAPI 0.139.0), porque en el job `validate` el venv compartido deja ganar al 0.128.8 del
connector (comentario `ci.yml:185-192`).

### 1.3 Versiones stale en otros docs (no usar como fuente)

| Doc | Dice | Real (este TRD) |
|---|---|---|
| `AGENTS.md` | Next 14.2.35, React ^18, Tailwind ^3.3.0, FastAPI 0.128.8, google-genai 1.47.0, gemini-2.5-flash, "Render Free plan" | §1.1 |
| `.context/02-stack.md` | Next 15.5.20, Tailwind ^3.3.0, FastAPI 0.128.8, pydantic 2.12.5, supabase-py 2.28.3, PyJWT 2.10.1, google-genai 1.47.0, "Node 20.x" | §1.1 |
| `.context/02-stack.md` | "11 componentes shadcn/ui" | 21 componentes (`apps/web/components/ui/`) |
| `AGENTS.md` / `.context/02-stack.md` | "Envia API (Fase Inicial)" | Envia **eliminado** del runtime (rev.109); shipping = Aveonline único (`.context/06-contracts.md` §9) |
| `AGENTS.md` | "WhatsApp Cloud API (Meta oficial v21.0)" | El código usa `META_API_VERSION = "v22.0"` (`services/ai-orchestrator/whatsapp_sender.py:19`) |
| `docs/HANDOFF.md` | "218 migraciones" | **251** archivos en `supabase/migrations/` (ver §4.3) |

---

## 2. Arquitectura de servicios

### 2.1 Servicios Render live (4)

Blueprint: `render.yaml` (raíz del repo). Los 4 servicios están en **plan `starter`** (always-on),
región `oregon`, `branch: production`, `autoDeploy: true` (`render.yaml:27-118,125-165,172-307,316-587`).

| Servicio Render | rootDir | Tipo | Rol | Healthcheck |
|---|---|---|---|---|
| `konvi-web` | `apps/web` | `web` (Node) | Backoffice Next.js (Tenant Console) | `/` (`render.yaml:116`) |
| `konvi-connector` | `services/connector-whatsapp` | `web` (Python) | Webhook gateway Meta (Model B per-tenant) | `/health` (`render.yaml:163`) |
| `konvi-api` | `services/api` | `web` (Python) | Core API REST síncrona (gateway) | `/health` (`render.yaml:305`) |
| `konvi-orchestrator` | `services/ai-orchestrator` | `web` (Python) | Worker IA: polling inbound, FSM/agentic, outbound, crons | `/health` (`render.yaml:581`) |

Notas verificadas:

- El orchestrator es `type: web` con `uvicorn server:app` y el `OrchestratorWorker` corriendo en un
  **daemon thread** dentro del mismo proceso (comentario `render.yaml:309-314`). Es un workaround
  histórico del plan Free (que no ofrecía `type: worker`); se mantiene en Starter.
- Build web: `corepack pnpm@10.34.4 install --frozen-lockfile` + `next build` con heap Node de
  1500 MB (`render.yaml:45`). `npm` está prohibido en este repo (lockfile pnpm; ver comentario
  `render.yaml:38-44`).
- Secrets: toda env var con `sync: false` se configura en el Render Dashboard, no en el repo
  (`render.yaml:8-9`).

### 2.2 Placeholders vacíos (4) — razón de existir

Verificado 2026-08-02: los 4 directorios contienen **únicamente un README.md**. Ninguno está en
`render.yaml` ni se despliega.

| Directorio | Contenido | Razón de existir (verificado en su README) |
|---|---|---|
| `services/worker/` | solo README | Reserva para separar workloads de background si el orchestrator (único worker real, en daemon thread) se migra a `type: worker` o se divide (`services/worker/README.md`). |
| `services/cron/` | solo README | Reserva para tareas programadas que no quepan en el polling del orchestrator (refresh OAuth masivo, reportes, cleanups). Hoy **todos** los crons corren dentro del orchestrator (`services/cron/README.md`). |
| `services/connector-shopify/` | solo README | Fase 13 (futuro lejano), prerequisito: decisión de producto (`services/connector-shopify/README.md`). |
| `services/connector-mercadolibre/` | solo README | La integración MeLi real vive **dentro de `services/api/`** (routers `marketplace.py`, `meli_webhook.py`, `integrations.py` + `integrations/meli_client.py`). El directorio reserva la extracción a servicio independiente si se justifica (escalado/rate-limit separados) (`services/connector-mercadolibre/README.md`). |

### 2.3 Topología de ramas (verificado con git 2026-08-03)

```
develop  ── trunk de integración; CI corre aquí (push + PRs)
   │         promoción manual: git push origin origin/develop:production
   ▼
production ── deploy target de los 4 servicios Render (autoDeploy on-push)
```

- Verificado 2026-08-03 (`git ls-remote`): `origin/develop` = `a66d45f7`; `origin/production` =
  `5fdad396` (8 commits atrás — la promoción es decisión founder, ver `docs/PLAN.md` §E).
- **`main` NO EXISTE** en el remoto (`git ls-remote --heads origin` → solo `develop`, `production`
  y ramas de trabajo dependabot/fix): `main` no es deploy target **porque no existe**; el deploy
  target es `production`.
- CI **no** corre en push a `production` por diseño: el deploy es autoDeploy de Render observando la
  rama, y el commit es idéntico al ya validado en `develop` (comentario `ci.yml:7-10`).

---

## 3. Requisitos no funcionales y cómo se cumplen

### 3.1 Multi-tenancy (requisito: aislamiento total por `tenant_id`)

| Mecanismo | Implementación verificada |
|---|---|
| RLS Postgres | 79/79 tablas con RLS (auditoría consolidada 2026-08-02 §4, verificado contra DB live). Última barrera. |
| Filtro aplicación | `service_role` bypasea RLS → cada query multi-tenant lleva `.eq("tenant_id", tid)` explícito (patrón canónico ADR-0025, `.context/06-contracts.md` §8). |
| Lint AST estático | `scripts/audit_tenant_filter.py` enforcea el patrón en CI con **ratchet `BASELINE_MAX=0`** (`scripts/validate.sh:210-227`). Ejecutado 2026-08-02: exit 0, baseline con 0 gaps conocidos (`gaps_tenant_filter_baseline.csv` = solo header). Excepciones: `# tenant_filter:exempt:<razón>`. |
| Vault per-tenant | Secretos de integraciones (Meta app_secret, tokens) en Supabase Vault, leídos scoped al tenant dueño (`.context/06-contracts.md` §7.2, §8). |
| Deuda declarada | A6.3 (middleware GUC RLS) y A6.4 (Vault RPC ownership) **sin implementar**: el aislamiento hoy depende del lint + filtros app + RLS (auditoría M7). |

### 3.2 Seguridad

| Requisito | Implementación | Evidencia |
|---|---|---|
| Auth usuarios | JWT verificado vía **JWKS asimétrico** (`PyJWKClient`, cache 3600 s): acepta `ES256` y `RS256` vía JWKS; `HS256` solo si `SUPABASE_JWT_SECRET` está presente (fallback legacy transicional); `audience="authenticated"`. Claims: `tenant_id` y `role` desde `app_metadata`, `aal` para MFA. RBAC: `require_write_role` (owner+manager) / `require_owner_role` | `services/api/dependencies/auth.py:29,47-50,94-152,173-239`; `services/api/main.py:90-92` |
| Gate de ciclo de vida | `reject_if_tenant_deleting` → HTTP **423** en writes si el tenant está en grace period; HTTP **410** si ya fue hard-deleted; skip GET/HEAD/OPTIONS; aplicado a nivel router (`_OFFBOARDING_GATE`) | `services/api/dependencies/auth.py:439-518`; `services/api/main.py:43-48,250-311` |
| MFA | `enforce_mfa` exige AAL2 (401 si aal1 con factor verificado; lookup cacheado 60 s) en routers sensibles (`_MFA_GATE`: settings, integrations, expenses, purchases, SAR/DSR, SIC). Variante `enforce_mfa_strict` fail-closed (503 ante outage) para crown-jewels de offboarding | `services/api/dependencies/auth.py:381-428`; `services/api/main.py:49-57,255,264,278-280,310` |
| MFA enrolamiento | Enforcement para write-roles (owner/manager) con grace: deadline = max(created_at, `MFA_MANDATORY_START`) + 14 días. `MFA_MANDATORY_ENABLED=false` en prod; **brecha conocida A1** | `services/api/dependencies/auth.py:68-75,300-348`; `render.yaml:208-213`; auditoría A1 |
| Auth service-to-service | Header `X-Internal-Service-Secret` verificado con `hmac.compare_digest` + `X-Tenant-Id`; callers internos actúan con rol owner; MFA no-op para service-to-service. Consumidores: `orders.py` y `shipping.py`. Bloqueante en startup | `services/api/dependencies/internal_auth.py:37-117`; `services/api/main.py:93-97`. Limitación conocida: `X-Tenant-Id` autodeclarado no verificado (auditoría A12). |
| Rate limiting | Distribuido PostgreSQL: RPC `rate_limit_hit()` (**ventana fija**, UPSERT atómico) + tabla `rate_limit_windows`; fallback automático a sliding-window in-memory si la RPC falla. Límites: 120 write/min, 40 send/min; buckets estrictos MFA (5/min, regenerate 1/día) y offboarding (export 1/h, deletion 1/día); 429 con `Retry-After` + registro en `api_security_events`. Webhooks: rate limit por IP | `services/api/dependencies/security.py:75-95,170-346`; migración `20260425000000_distributed_rate_limiter.sql`; `render.yaml:269-276` |
| Idempotency | Header `Idempotency-Key` (opcional, regex `^[A-Za-z0-9:_-]{8,128}$`), scope `tenant+method+path+key`, TTL 24 h; payload distinto o request en curso → **409**; replay exacto devuelve respuesta persistida. Cleanup vía RPC `cleanup_expired_idempotency_keys` ejecutada por el worker del orchestrator (cada 3600 s) | `services/api/dependencies/idempotency.py:22-196`; migración `20260420000002`; `services/ai-orchestrator/worker.py:1229`; `services/api/main.py:135` |
| Webhooks firmados | Meta: HMAC SHA-256 **per-tenant** (Vault) + invariante cross-tenant `phone_number_id→tenant_id` → 403 + cap payload 512 KB. Wompi: firma SHA256. MeLi: IP allowlist + dedup distribuido + anti-SSRF. Telegram: secret token HMAC compare. Aveonline: secret bcrypt + dedup | `.context/06-contracts.md` §7.3; auditoría §4; `services/connector-whatsapp/dependencies/meta.py`; routers `wompi_webhook.py`, `meli_webhook.py`, `telegram_webhook.py`, `aveonline_webhook.py` |
| CORS | Orígenes restringidos por `ALLOWED_ORIGINS`; headers expuestos: `X-RateLimit-*`, `Retry-After`, `X-Request-ID` | `services/api/main.py:124-146` |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, CSP `default-src 'none'`, HSTS 1 año | `services/api/main.py:149-167` |
| Errores uniformes | Contrato 422 es-CO: `{detail, errors[], request_id}` (mapa `_VALIDATION_ES`) | `services/api/main.py:189-247` |
| Validación de arranque | Fail-fast `sys.exit(1)` si falta config crítica (Supabase URL, secret key, INTERNAL_SERVICE_SECRET) | `services/api/main.py:67-104` |
| Supply chain | pip-audit (3 servicios, allowlist 5 PYSEC) + osv-scanner (lockfile JS, allowlist `osv-scanner.toml`) en CI | `scripts/validate.sh:350-394` |

### 3.3 Durabilidad (requisito: ningún mensaje/pago se pierde ante crash)

- **Inbox durable WhatsApp**: el connector persiste el **payload crudo** en `whatsapp_webhook_inbox`
  (PK = sha256 del body, idempotente) **antes** de responder 200 a Meta
  (`services/connector-whatsapp/routers/webhook.py:180-187`, `services/inbox.py:54-70`); el parseo e
  insert a `messages` (`processing_status='pending'`) ocurre en BackgroundTask posterior
  (`services/connector-whatsapp/services/db_persistence.py:310-326`). Un `redrive_loop` re-procesa
  los eventos del inbox no consumidos (lease 120 s, máx 5 intentos, dead-letter)
  (`services/connector-whatsapp/main.py:20-43`, `services/inbox.py:195-222`).
- **Inbox durable Wompi + re-drive**: el webhook persiste en `wompi_webhook_inbox` (dedup por
  `signature.checksum`) antes de responder 200 — deliberadamente antes de verificar la firma, que se
  valida en background (`services/api/routers/wompi_webhook.py:76-108`). El worker re-conduce los
  perdidos por crash: RPC `claim_wompi_inbox_batch` + re-POST del payload crudo a
  `/api/v1/webhooks/wompi`, grace 120 s, máx 5 intentos → dead-letter
  (`services/ai-orchestrator/worker.py:3274-3346`; `WOMPI_INBOX_RECONCILE_ENABLED=true`, intervalo
  180 s — `render.yaml:491-497`).
- **Outbound durable**: cola pgmq `whatsapp_outbound_messages` (migración `20260420000004`) con retry
  por visibility timeout 90 s, `WHATSAPP_OUTBOUND_MAX_ATTEMPTS=5` → `failed`
  (`services/ai-orchestrator/worker.py:1083,1217-1225`; `render.yaml:394-401`); ACK transaccional con
  3 reintentos (100/300/1000 ms) → estado `ack_pending` si falla el UPDATE de traza (se hace ACK
  pgmq igual: no reenvío a Meta, anti-duplicado) (`worker.py:3570-3623`; `.context/06-contracts.md` §2, §4).
- **Recuperación de atascados**: sweep de mensajes `pending`/`processing` >5 min al arranque del
  worker (`worker.py:2419-2424`) + reclaim continuo de `processing` colgados cada 60 s
  (`STALE_PROCESSING_RECLAIM_MINUTES=3`, `worker.py:2426`; `render.yaml:529-533`).
- **Auditoría append-only**: `audit_log` + `consent_audit_log` + `pii_access_log` (Habeas Data,
  migraciones 20260502010000/010001; ver `docs/HANDOFF.md`).

### 3.4 Observabilidad

| Requisito | Implementación | Evidencia |
|---|---|---|
| Error tracking | Sin error-tracking externo (S8, 2026-08-17: Sentry eliminado por decisión founder — free tier vencido). Postura vigente: logs estructurados stdout (Render los retiene) + `/health` + `/agentic/metrics`; la observabilidad propia se construye en la fase Platform Console (fase 12) | `docs/PLAN.md` §E (S8) |
| Correlación | `X-Request-ID` middleware (respeta entrante o genera, expone en respuesta); correlation-id en webhook framework | `services/api/main.py:170-186` |
| Health | `/health` (liveness, no toca DB) + `/health/ready` (readiness con check DB, 503 si cae) | `services/api/main.py:322-357` |
| Trazas | OpenTelemetry mínimo en orchestrator, exporter desactivado por default (`OTEL_EXPORTER_ENABLED=true` para activar) | `services/ai-orchestrator/requirements.txt:10-15` |
| Eventos seguridad | Tabla `api_security_events` (`rate_limit.exceeded`, `idempotency.*`) | `.context/06-contracts.md` §11 |
| Métricas worker | Health metrics collector per-tenant/per-provider cada 300 s | `render.yaml:524-528` |

### 3.5 Performance

- **Polling inbound**: `POLL_INTERVAL_SECONDS=3` s (`render.yaml:382-383`); historial de conversación
  al LLM limitado a 25 mensajes (`CONVERSATION_HISTORY_LIMIT=25`, `render.yaml:384-385`; CI falla si
  vuelve a 10, `validate.sh:303-309`).
- **Cascada LLM** (path agentic productivo): 2 modelos — primary `gemini-3.1-flash-lite`, fallback
  `gemini-3.5-flash` tras 2 fallos; hasta 8 intentos, backoff truncado 1/2/4/8/16/16/16 s; timeout
  30 s por llamada (`services/ai-orchestrator/llm_invoke.py:37-45,102-104`;
  `services/ai-orchestrator/agentic/agent.py:55,72`). **Límite conocido (A5)**: peor caso =
  8×30 s + 63 s backoff = **303 s (~5 min)** vs heartbeat del worker de **120 s**
  (`HEALTH_HEARTBEAT_STALE_SECONDS`, `services/ai-orchestrator/server.py:66`) → Render puede
  reiniciar el servicio a mitad de un turno LLM con riesgo de outbound duplicado. El heartbeat es un
  timestamp re-latido por ítem procesado (no hay thread separado ni latido dentro del turno LLM)
  (`services/ai-orchestrator/worker.py:495,848`). Ver auditoría A5.
- **CI rápido**: detector de cambios por dominio (backend/frontend) con fail-safe a correr todo
  (`ci.yml:27-69`); pytest paralelo `-n auto` (xdist) (`validate.sh:90-99`).
- **Anti-hibernación desactivada**: los 4 servicios son Starter/always-on; el ping anti-spin-down
  quedó en `ANTI_HIBERNATION_ENABLED=false` (código conservado) (`render.yaml:539-549`).

### 3.6 Legal / cumplimiento (Colombia)

| Requisito | Implementación | Evidencia |
|---|---|---|
| Habeas Data (Ley 1581) | SAR/ARCO endpoint bajo `_MFA_GATE`; retention policies per-tenant; hard-delete de tenant tras grace period (RPC `fn_hard_delete_tenant`, archiva a Storage antes); click-wrap DPA/privacy; tokenización PII (hash+last4) | `services/api/main.py:259-264`; `render.yaml:351-356`; migraciones 20260502010000–20260508010000; `docs/HANDOFF.md` |
| Comprobante de compra (Ley 1480 art. 50) | Jobs `RECEIPT_ISSUE_*` (comprobante ≤ día siguiente) y `ACCEPTANCE_STAMP_*` (aceptación verificable, separado por diseño) | `render.yaml:447-473` |
| Reversión del pago (Decreto 1074) | Constancia de reversión emitida activamente (`REVERSAL_CONSTANCIA_*`) | `render.yaml:474-483` |
| Ventana legal de contacto (Ley 2300) | Gate de outbound con ventana legal L-V 7-19, sáb 8-15, nunca dom/festivos, zona `America/Bogota` (`lib/outbound_gate.py` del orchestrator) | `render.yaml:509-515` |
| Coherencia de precios (Ley 1480 art. 26) | Job `ORDER_COHERENCE_*` cada 30 min | `render.yaml:439-446` |
| Docs legales | `docs/legal/` (dpa, privacy-policy, subprocessors, contract-template-tenant) — **brecha B3** (doc corregida 2026-08-02): el contrato tenant ya declara Aveonline como único operador logístico, alineado con `subprocessors.md`; pendiente revisión de abogado antes de firma con tenants | `docs/legal/`; auditoría B3 |

---

## 4. Entornos

### 4.1 Dev local (VM dedicada, herramientas nativas — sin venv)

| Herramienta | Uso canónico |
|---|---|
| Python | `python3.11` explícito (`python3` del sistema apunta a 3.9) |
| Node/pnpm | `pnpm` 10.34.4 (`.nvmrc`=22; el shell de la VM resolvía v20.20.2 al verificar — usar `nvm use` para alinear a 22) |
| Supabase CLI | `supabase db query --linked -f archivo.sql` — **psql TCP directo está bloqueado por Supavisor**; toda interacción SQL va por la CLI |
| Stack local | `make -C .local up` levanta api (:8001) + connector (:8000) + orchestrator + web (:3000) + túneles ngrok; logs en `.local/logs/`, PIDs en `.local/pids/` (`.local/Makefile`) |

⚠️ El localhost comparte la **misma Supabase productiva** (`.context/02-stack.md:54`) — no hay
Supabase de staging separada para el dev dinámico.

### 4.2 Render (producción)

- Blueprint `render.yaml` en la raíz (Render lo detecta automáticamente).
- 4 servicios §2.1, plan Starter, región Oregon, deploy por push a `production`.
- Env vars secretas (`sync: false`) se configuran en el Dashboard (`.env` **nunca** al repo).

### 4.3 Supabase

- Un único proyecto productivo (DB + Auth + Realtime + Vault + pgmq), compartido por Render y por el
  dev local. `supabase/config.toml:5` → `project_id = "konvi-platform"` (config local).
- Migraciones: **251 archivos** en `supabase/migrations/` (última:
  `20260802120000_drop_ghost_tables_and_revoke_grants.sql`), ledger de prod al día
  (auditoría §0/§5).

---

## 5. CI/CD

### 5.1 `scripts/validate.sh --ci` — paso a paso

`--ci` = `--full` + `--coverage` + `--build` + **warnings cuentan como errores**
(`scripts/validate.sh:34`). Orden real de ejecución:

1. **Python syntax check** — `py_compile` de todos los `.py` de `services/api`,
   `services/ai-orchestrator`, `services/connector-whatsapp` (`validate.sh:52-67`).
2. **Python unit tests** — `pytest tests/ -q -m 'not dbharness'` con `-n auto` si xdist está;
   `SLOW_TESTS=1` exportado (ejerce paths bcrypt de MFA); con coverage: `--cov=services`
   (`validate.sh:75-126`).
3. **Coverage gate** — `coverage report`, **mínimo `COVERAGE_MIN=55`** (default; sobreescribible por
   env). Genera `coverage.xml` (`validate.sh:25,128-149`).
4. **Test files syntax** — `py_compile` de `tests/test_*.py` (`validate.sh:151-164`).
5. **TypeScript** — `pnpm --filter web exec tsc --noEmit` (`validate.sh:166-179`).
6. **Vitest** — `pnpm --filter web test` si existen `*.test.ts(x)` (`validate.sh:181-198`).
7. **Tenant filter AST lint** — `scripts/audit_tenant_filter.py --baseline … --max-gaps 0`:
   0 gaps nuevos permitidos, ratchet protegido por CODEOWNERS (`validate.sh:200-227`).
8. **Anti-drift webhooks** — `scripts/check_no_ngrok.sh`: 0 URLs ngrok en render.yaml/services/apps
   (`validate.sh:229-242`).
9. **ESLint** — `pnpm --filter web lint` (exit code + formato de error Next; fallos de herramienta
   también fallan) (`validate.sh:244-271`).
10. **Next.js build** — `pnpm --filter web build` con placeholders Supabase (`validate.sh:273-296`).
11. **render.yaml coherencia** — `CONVERSATION_HISTORY_LIMIT`≠10; presencia de
    `PENDING_PAYMENT_RELEASE_ENABLED`, `API_RATE_LIMIT_DISTRIBUTED`, `ANTI_HIBERNATION_ENABLED`
    (`validate.sh:298-323`).
12. **.env.example coherencia** — vars críticas presentes (`validate.sh:325-348`).
13. **pip-audit** (--full) — 3 `requirements.txt`, allowlist 5 vulns conocidas; exit code manda
    (`validate.sh:350-376`).
14. **osv-scanner** (--full) — `pnpm-lock.yaml` contra `osv-scanner.toml` (`validate.sh:378-394`).
15. **.env local** (--full) — informativo; ausente es lo esperado en CI (`validate.sh:396-422`).
16. **ruff** (en --ci) — `ruff check services/ tests/`; falla solo si errores >
    **`BASELINE_RUFF_ERRORS=202`** (ratchet anti-regresión, no lint estricto) (`validate.sh:424-458`).
17. *(opt-in `--db-harness`, no incluido en `--ci`)* Harness Postgres real (`validate.sh:460-480`).

Exit 1 si hay ≥1 error → "NO desplegar" (`validate.sh:482-497`).

### 5.2 Workflow `.github/workflows/ci.yml` — jobs reales

Triggers: PR a `develop`/`phase-*` y push a `develop`; `concurrency` con cancel-in-progress
(`ci.yml:3-15`).

| Job | Qué hace | Líneas |
|---|---|---|
| `changes` | Detector de dominio (backend/frontend) por paths; **fail-safe**: si no puede determinar archivos → corre todo | `ci.yml:30-69` |
| `validate` | Corre `bash scripts/validate.sh --ci` completo (Python 3.11, pnpm 10.34.4, Node 22, symlink compat para tests con path absoluto); osv-scanner standalone si solo cambió el frente JS; sube artifact de coverage (7 días) | `ci.yml:71-183` |
| `py-core` | Tests core api+orch bajo **FastAPI 0.139** (pins de prod, sin el connector): `pytest -m 'not dbharness and not connector' -n auto` | `ci.yml:193-234` |
| `db-harness` | Supabase CLI 2.90.0 + `scripts/schema_drift_check.sh` (levanta Postgres local, replay de migraciones desde cero, gate anti-drift contra baseline) + `pytest tests/dbharness` con `HARNESS_REQUIRED=1` (all-skipped = fallo) | `ci.yml:236-297` |
| `build-web` | tsc + ESLint + Vitest + `next build` (solo si cambió frontend) | `ci.yml:299-355` |

### 5.3 Gates y thresholds reales

| Gate | Valor real | Evidencia |
|---|---|---|
| Coverage mínimo | **55%** (real medido 2026-08-01: 66.0%; los comentarios que dicen "target 70" son aspiracionales — M18) | `validate.sh:25`; auditoría §0, M18 |
| Ruff baseline | **202** errores tolerados máximo (ratchet: bajar requiere solo cambiar el número; subirlo requiere review) | `validate.sh:440` |
| Tenant filter gaps | **0** (baseline vacía + max-gaps 0; script y baseline protegidos por `.github/CODEOWNERS`) | `validate.sh:210-227` |
| Harness DB | Obligatorio en CI: `HARNESS_REQUIRED=1`, 0 tests pasados = gate rojo | `ci.yml:288-297` |
| Suite | 4.031 tests Python (3.830 gate `-m 'not dbharness'` + 201 dbharness; 346 archivos `test_*.py`) + 30 archivos Vitest — verificado 2026-08-02 con `pytest --collect-only` | auditoría §0; `pyproject.toml:64-71` |

---

## 6. Requisitos de infraestructura y límites conocidos

### 6.1 Infraestructura

- **Render**: 4 servicios Starter (migrados desde Free el 2026-07-17 — el ping anti-hibernación se
  desactivó entonces, `render.yaml:539-545`). Región única Oregon. Sin autoscaling configurado.
  Upgrade path documentado: `docs/deployment/render-upgrade-path.md`.
- **Supabase**: proyecto único productivo. **Supavisor bloquea conexión TCP directa (psql)** desde la
  VM → toda operación SQL usa `supabase db query --linked` (`.context/02-stack.md:36`).
- **Healthchecks**: Render consulta `/health` (ver §2.1). El readiness real de dependencias es
  `/health/ready` (`services/api/main.py:332-357`).

### 6.2 Límites y riesgos conocidos (verificados en auditoría 2026-08-02)

| Límite | Detalle | Ref auditoría / evidencia |
|---|---|---|
| Guías Aveonline simuladas | `AVEONLINE_GENERATE_REAL_GUIDES=false` en prod → toda guía es dry-run (`bloquegenerarguia="0"`). Guía real exige **doble compuerta**: env master **y** flag per-tenant `real_guides_enabled` (default false) | B1; `render.yaml:226-227,348-350`; `services/api/routers/wompi_webhook.py:1995-1999`; `services/api/integrations/aveonline_client.py:764` |
| MFA no obligatorio | `MFA_MANDATORY_ENABLED=false` en prod | A1; `render.yaml:208-209` |
| Reconciliación Wompi | Si el webhook se pierde del todo (reintentos Wompi 30m/3h/24h agotados), la reconciliación es **manual** (limitación del API público Wompi) | M4; runbook `docs/operations/runbooks/wompi-payment-reconciliation.md` |
| `X-Tenant-Id` autodeclarado | La barrera service-to-service es solo `INTERNAL_SERVICE_SECRET`; el tenant declarado no se verifica criptográficamente (cada llamada sí deja fila de auditoría en `api_security_events`) | A12; `services/api/dependencies/internal_auth.py` |
| Tests no portables | ~187 archivos de test con path absoluto `/home/ansible/...` → CI usa symlink shim | M9; `ci.yml:127-139` |

> Cerrados el 2026-08-02 (detalle y evidencia en `docs/PLAN.md` §B): A5 (deadline de cascada
> `LLM_CASCADE_DEADLINE_SECONDS=100` < heartbeat 120 s), A6 (rescate Claude eliminado del repo),
> M8 (default de modelo unificado vía `DEFAULT_PRIMARY_MODEL`), A10 (polling backup
> `_aveonline_status_poll` del worker).

---

## Referencias internas

- `docs/backend/BACKEND.md` — documento maestro del backend (routers, flujos, worker, testing, operación).
- `.context/06-contracts.md` — contratos runtime canónicos (FSM, Wompi, Model B, tiering).
- `.context/05-doc-policy.md` — jerarquía de fuentes de verdad documental.
- `docs/HANDOFF.md` — estado operativo, credenciales, lecciones.
- `.audit/findings/2026-08-02-consolidated-audit.md` — auditoría con evidencia de los límites citados.

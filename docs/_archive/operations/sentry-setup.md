⚠️ ARCHIVADO — 2026-08-17 (S8: Sentry eliminado del repo por decisión founder; este setup ya no aplica. La observabilidad propia se construye en la fase Platform Console — fase 12).
# Sentry — Setup + operación

**Rev. 109 J.2.7.4** — Sentry tracing E2E cross-service. Cierra item del Plan K (audit 2026-05-29) ajustado de "OTEL+Grafana" a "Sentry tracing" tras feedback founder (Sentry tiene su UI propia, sin dominio nuevo, free 5k events/mo).

## ⚠️ Estado activación

**Sentry NO es bloqueante para producción** (clarificación founder 2026-05-29).

| Componente | Estado |
|---|---|
| Código deployed (SDK + configs + env vars en render.yaml) | ✅ |
| DSNs configurados en Render Dashboard | ❌ NO (espera trigger) |
| Estado runtime SDK | `enabled: false` — falla silente sin DSN, build pasa, runtime no captura nada |

**Sentry NO requiere Platform Console**: son herramientas independientes. Sentry tiene su propia UI (sentry.io), distinta de la futura Platform Console.

**Triggers de activación** (cualquiera basta):
1. Primer incidente productivo reportado por un tenant
2. Konvi crece >5 tenants activos (debugging manual via `render logs` ya no escala)
3. Founder decide proactivamente baseline observability antes de onboarding agresivo
4. Compliance externo (pen testing OWASP) lo solicita para audit

**Cuando se active**: ejecutar §1-4 abajo (~30 min). **NO requiere redeploy de código** — solo configurar env vars en Render Dashboard (Render hace pickup automático).

## Arquitectura

```
                                                    ┌──────────────────┐
                                                    │   sentry.io      │
                                                    │   organizations/ │
                                                    │   konvi/         │
                                                    └─────────┬────────┘
                                                              │  (1 trace_id correlaciona)
                                                              │
┌───────────┐    ┌────────────┐    ┌────────────┐    ┌────────────────┐
│ Browser   │───▶│ apps/web   │───▶│ services/  │───▶│ services/      │
│ (Inbox UI)│    │ Next.js    │    │ api        │    │ ai-orchestrator│
└───────────┘    │ @sentry/   │    │ sentry-sdk │    │ sentry-sdk     │
                 │ nextjs     │    │ [fastapi]  │    │ [fastapi]      │
                 └────────────┘    └────────────┘    └────────────────┘
                       │                                    │
                       └──────────────┬─────────────────────┘
                                      │
                          ┌───────────▼───────────┐
                          │ services/             │
                          │ connector-whatsapp    │
                          │ sentry-sdk [fastapi]  │
                          └───────────────────────┘

Trace propagation: W3C `sentry-trace` + `baggage` headers automáticos
via integrations del SDK (browser fetch → Next server → httpx → Supabase).
```

## Setup founder (one-time, ~30 min)

### 1. Cuenta + 4 proyectos en sentry.io

1. Crear cuenta en https://sentry.io (free 5k events/mo + 10k transactions).
2. Crear org `konvi`.
3. Crear 4 **Projects** (Settings → Projects → Create New):
   - `konvi-web` — Platform: `Next.js`
   - `konvi-api` — Platform: `Python > FastAPI`
   - `konvi-orchestrator` — Platform: `Python > FastAPI`
   - `konvi-connector` — Platform: `Python > FastAPI`

### 2. Tomar 4 DSNs

Para cada proyecto: **Settings → Projects → {name} → Client Keys (DSN)** → copiar el DSN URL completo (formato `https://xxx@oXXXX.ingest.sentry.io/PROJECT_ID`).

### 3. Configurar Render env vars (sync: false en blueprint)

En **Render Dashboard** para cada servicio (con `sync: false`, no commitear):

#### konvi-web (apps/web)

```
SENTRY_DSN              = <konvi-web DSN>
NEXT_PUBLIC_SENTRY_DSN  = <konvi-web DSN>   # MISMO valor — va al bundle browser
SENTRY_AUTH_TOKEN       = sntrys_xxx        # ver paso 4
```

#### konvi-api (services/api)

```
SENTRY_DSN              = <konvi-api DSN>
```

#### konvi-orchestrator (services/ai-orchestrator)

```
SENTRY_DSN              = <konvi-orchestrator DSN>
```

#### konvi-connector (services/connector-whatsapp)

```
SENTRY_DSN              = <konvi-connector DSN>
```

Resto de vars Sentry (`SENTRY_TRACES_RATE=0.1`, `SENTRY_ENV=production`, `SENTRY_ORG=konvi`, `SENTRY_PROJECT=konvi-web`, `NEXT_PUBLIC_SENTRY_TRACES_RATE=0.1`, `NEXT_PUBLIC_SENTRY_ENV=production`) ya están en `render.yaml` con `value:` literal — Render los inyecta automáticamente.

### 4. Source map upload token (solo apps/web)

Para que Sentry muestre stack traces **legibles** (con código original) en lugar de minified:

1. **Settings → Account → API → Auth Tokens → Create New Token**
2. Scope mínimo: `project:releases` + `project:write` (org-level OK).
3. Copiar el token `sntrys_...` y configurarlo como `SENTRY_AUTH_TOKEN` en Render Dashboard para `konvi-web` (sync: false).

Sin este token: build sigue OK pero stack traces en Sentry muestran código minified (debugging produccion limitado).

### 5. Test inicial

Tras deploy con los DSNs:

1. **Trigger artificial**: en apps/web abrir DevTools console y ejecutar:
   ```js
   throw new Error("Sentry smoke test — debe aparecer en konvi-web project")
   ```
2. Verificar en `sentry.io/organizations/konvi/issues/?project={konvi-web}` que el error aparece (~5-10s).
3. Repetir para backend: `curl -X POST <API_URL>/api/v1/diag/sentry-trigger` (si existe endpoint diag) o simplemente provocar un 500 en cualquier endpoint.

## Sampling — ajuste por entorno

`SENTRY_TRACES_RATE` controla cuántas transacciones se capturan (default 0.1 = 10%).

| Entorno | Sample rate | Razón |
|---|---|---|
| development | 0.0 | NO enviar a Sentry desde local |
| staging | 1.0 | Capturar todo en QA |
| production (early) | 0.1 | Suficiente para detectar patrones, bajo volumen |
| production (>100 tenants) | 0.05 | Bajar para no saturar free tier 10k transactions/mo |
| debugging activo bug específico | 1.0 temporal | Subir en Render Dashboard, bajar tras resolver |

## Diferencias browser vs server SDK

| Aspecto | Browser (`sentry.client.config.ts`) | Server (`sentry.server.config.ts`) |
|---|---|---|
| DSN | `NEXT_PUBLIC_SENTRY_DSN` (va al bundle) | `SENTRY_DSN` |
| Replay (grabaciones) | DESACTIVADO por costo + PII | N/A |
| PII | `sendDefaultPii: false` siempre | `sendDefaultPii: false` |
| Integraciones | `browserTracingIntegration()` | Auto (FastAPI / HTTPX) |

## Costos esperados

| Tier Sentry | Events/mo | Transactions/mo | Mejorías | Costo USD |
|---|---|---|---|---|
| **Free** | 5k | 10k | Suficiente para 5-20 tenants | $0 |
| Team | 50k | 100k | Cuando >100 tenants | $26/mo |
| Business | 100k | 250k | Para SLAs estrictos | $80/mo |

Konvi en early stage (5-20 tenants): **Free tier alcanza**.

## Compliance Habeas Data

- `sendDefaultPii: false` en client + server → NO se envían emails, IPs ni cookies por default.
- URL parameters que contengan PII (e.g. `?phone=573...`) podrían filtrarse — la heurística `Sentry.beforeSend` puede sanear (a implementar si llegan PRs con PII en URL).
- Stack traces NO contienen PII por sí mismos (son referencias a líneas de código).
- Body de requests outbound NO se loguea por default (solo metadata).

**Riesgo low**, pero monitor primer mes de uso real y ajustar `beforeSend` si Sentry captura algo sensible.

## Troubleshooting

### "Sentry SDK loaded but no events arrive"

1. Verifica DSN configurado correctamente (no placeholder `your-key@`).
2. `enabled: !!process.env.SENTRY_DSN` — sin DSN, SDK queda inerte por diseño.
3. Open browser DevTools Network → filter `sentry.io` → debes ver POST cada vez que ocurre error/transaction.

### "Stack traces minified en production"

`SENTRY_AUTH_TOKEN` no configurado → source maps no se suben.
Ver paso 4 arriba.

### "Demasiados events — quota agotada"

Bajar `SENTRY_TRACES_RATE` en Render Dashboard sin redeploy (env var pickup en next request).
Si error rate alto: investigar root cause antes de mutear con sampling.

### "PII apareció en Sentry"

1. Identificar el evento exacto + qué campo tiene PII.
2. Agregar `beforeSend` hook en `sentry.{client,server}.config.ts` que sane el campo.
3. Borrar el event manualmente en sentry.io UI.
4. Documentar el patrón en este doc para no repetir.

## Referencias

- Sentry Docs Next.js: https://docs.sentry.io/platforms/javascript/guides/nextjs/
- Sentry Docs FastAPI: https://docs.sentry.io/platforms/python/integrations/fastapi/
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- Plan K J.2.7.4: `.context/04-next-steps.md`

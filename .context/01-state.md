# Estado de Implementación — Resumen

> Fuente de verdad completa: `docs/product/current-scope.md`

## Fases

| Rango | Estado |
|-------|--------|
| Fases 1-11 | ✅ Completadas (2026-04-09) |
| Fase 12 — Platform Console | ❌ Pendiente — bloqueante: OQ-P01 |
| Fase 13 — Shopify | ❌ Futuro |

## Servicios live en Render

| Servicio | URL |
|---------|-----|
| `apps/web` — Tenant Console | `https://commerce-ops-web.onrender.com` |
| `services/connector-whatsapp` | `https://commerce-ops-connector.onrender.com` |
| `services/api` — API Gateway | `https://commerce-ops-api.onrender.com` |
| `services/ai-orchestrator` | Background worker — polling 3s |

- Supabase: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1) — **13 migraciones aplicadas**
- Tenant dev: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`

## Bloqueante activo

**OQ-P01**: ¿Platform Console en misma app Next.js (`/platform/*`) o app separada?
Sin decidir → no se puede iniciar Fase 12.

# Arquitectura Render + Supabase (vigente)

Última actualización: 2026-04-21

## Topología activa

| Capa | Plataforma | Estado |
|---|---|---|
| Frontend (`apps/web`) | Render Web Service | Live |
| Connector WhatsApp (`services/connector-whatsapp`) | Render Web Service | Live |
| API Gateway (`services/api`) | Render Web Service | Live |
| AI Orchestrator (`services/ai-orchestrator`) | Render Web Service (`server.py` + thread) | Live |
| DB/Auth/Realtime/Queues | Supabase | Live |

## Fuente de verdad de infraestructura

1. `render.yaml`
2. `docs/HANDOFF.md`
3. `.context/01-state.md`

## Migraciones

`supabase/migrations/` es fuente canónica de esquema.

Aplicación segura:

```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

## Nota Free vs pago

En Free, orchestrator corre como `web` por limitación de workers.
El target recomendado para pago (Starter+) es `type: worker`.

Ver análisis: `docs/deployment/render-upgrade-path.md`.

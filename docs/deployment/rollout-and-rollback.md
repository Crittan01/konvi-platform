# Rollout y Rollback

Última actualización: 2026-04-21

## Rollout normal

1. Merge a rama de despliegue (`develop` en flujo actual).
2. Render auto-deploy desde `render.yaml`.
3. Ejecutar smoke checks (`/health`, Inbox, envío humano, shipping quote).

## Rollback código

```bash
git revert <sha>
git push origin develop
```

## Rollback de esquema

No hay down-migrations automáticas.
Si se requiere reversión, crear migración compensatoria nueva en `supabase/migrations/`.

## Checklist mínimo post-deploy

- `web` responde
- `connector` `/health` ok
- `api` `/health` ok
- `orchestrator` `/health` ok
- Inbox lista conversaciones sin error
- envío humano en Inbox crea outbound en cola y se procesa

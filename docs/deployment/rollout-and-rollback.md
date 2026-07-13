# Rollout y Rollback

Última actualización: 2026-07-13

## Topología de deploy (IMPORTANTE)

Render está configurado con `branch: production` + `autoDeploy: true` en los 4 servicios
(`web`, `api`, `connector`, `orchestrator`) — ver `render.yaml`. Por tanto:

- **`develop`** = rama de INTEGRACIÓN (se mergean los PRs ahí; NO despliega).
- **`production`** = rama TARGET de deploy. Un push a `production` dispara el autodeploy.
- **`main`** NO es target de deploy (puede estar atrás; no confiar en ella para prod).

**Desplegar = promover `develop` a `production`:**

```bash
git fetch origin
# (opcional) verificar qué se va a desplegar:
git log --oneline origin/production..origin/develop
# promover:
git push origin origin/develop:production
```

Render detecta el push a `production` y redespliega solo los servicios cuyos archivos
cambiaron. Confirmar los 4 en "Deployed" en el dashboard de Render.

## Rollout normal

1. Merge de PRs a `develop` (gate `validate.sh --ci` VERDE + review).
2. **Promover a producción**: `git push origin origin/develop:production`.
3. Aplicar migraciones nuevas a prod con protocolo seguro (smoke `BEGIN…ROLLBACK` →
   `supabase db query --linked -f <mig>` → `supabase migration repair --status applied <ts>`)
   ANTES o coordinado con el push (RLS-tightening ANTES del código; tablas nuevas ANTES).
4. Smoke checks (`/health` de los 4, Inbox, envío humano, shipping quote).

## Rollback de código

`production` es una rama ordinaria → el rollback es apuntarla a un commit sano.

```bash
# Opción A — reset de production a un commit bueno conocido (redeploy inmediato):
git push origin <sha_bueno>:production --force-with-lease

# Opción B — revert forward (deja historia lineal en develop y re-promueve):
git revert <sha_malo>            # en develop, vía PR
git push origin origin/develop:production
```

Opción A es la más rápida en incidente (Render redeploya el `<sha_bueno>`). Verificar
`/health` de los 4 servicios tras el redeploy.

## Rollback de esquema

No hay down-migrations automáticas. Si se requiere reversión de esquema, crear una
migración compensatoria NUEVA en `supabase/migrations/` (nunca editar una aplicada) +
aplicarla con el protocolo seguro. Nota: dev y prod comparten la misma Supabase hasta que
exista staging aislado (auditoría 2026-07-13, W3) — extremar el smoke `BEGIN…ROLLBACK`.

## Checklist mínimo post-deploy

- `web` responde
- `connector` `/health` ok
- `api` `/health` ok
- `orchestrator` `/health` ok (worker `running:true`, `error:null`)
- Inbox lista conversaciones sin error
- envío humano en Inbox crea outbound en cola y se procesa

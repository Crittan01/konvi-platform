# Rollout y Rollback — Commerce Ops Platform

Última actualización: 2026-04-16

---

## Rollout normal (deploy en Render)

El ciclo estándar es:
1. Desarrollo en rama `develop`
2. Push → `origin/develop`
3. PR → `main` (revisión + merge)
4. Render detecta push a `main` → autodeploy de los 4 servicios

No hay rollback automático en Render Free. El rollback es manual.

---

## Rollback de servicios (Render)

### Cuándo hacer rollback
- Build exitoso pero comportamiento incorrecto en producción
- Regresión detectada en funcionalidades clave

### Pasos

**Opción A — Revert del commit (recomendado):**
```bash
git revert HEAD --no-edit
git push origin main
# Render detecta el push y redespliega automáticamente
```

**Opción B — Manual Deploy a commit anterior:**
1. Render Dashboard → Servicio afectado → "Manual Deploy"
2. Seleccionar commit anterior de la lista
3. Deploy

### Orden de rollback por dependencia

Si el cambio involucra schema de DB + código:
1. Primero: rollback de código (Render)
2. Luego: evaluar si la migración SQL es reversible
3. Ejecutar down-migration si existe (ver abajo)

---

## Rollback de migraciones SQL (Supabase)

> ⚠️ Las migraciones en este proyecto son **acumulativas hacia adelante**. No hay down-migrations automáticas.

### Estrategia general

Para cada migración en `supabase/migrations/`, si se necesita revertir:

1. Escribir una migración inversa manual (`ALTER TABLE DROP COLUMN`, `DROP TABLE`, etc.)
2. Aplicarla con:
   ```bash
   supabase db query --linked -f supabase/migrations/YYYYMMDDHHMMSS_rollback_xxx.sql
   ```
3. Agregar el archivo de rollback al repo en `supabase/migrations/` con nombre apropiado

### Migraciones de alto riesgo (no revertir sin análisis)

| Migración | Riesgo si se revierte |
|-----------|----------------------|
| `20260415030000_rename_agent_to_operator.sql` | Rompe auth de todos los usuarios existentes |
| `20260415000000_security_tenant_users_rls.sql` | Abre acceso entre tenants |
| `20260416000000_fix_claims_rls.sql` | RLS de claims volvería a estar roto |

---

## Rollback de variables de entorno

Si un cambio de variable causa fallo:
1. Render Dashboard → Servicio → Environment
2. Restaurar el valor anterior de la variable
3. Save Changes → Render redespliega automáticamente

---

## Checklist pre-deploy

Antes de mergear a `main`:
- [ ] `pnpm --filter web build` pasa sin errores
- [ ] No hay `getSession()` en Server Components (usar `getUser()`)
- [ ] No hay funciones arrow como props RSC
- [ ] Variables nuevas documentadas en `.env.example` y en `render.yaml`
- [ ] Si hay migración SQL nueva: aplicada manualmente con `supabase db query --linked`
- [ ] Si hay cambio de schema: código y migración son coherentes

---

## Health checks post-deploy

```bash
# Connector
curl https://commerce-ops-connector.onrender.com/health

# API
curl https://commerce-ops-api.onrender.com/health

# Orchestrator
curl https://commerce-ops-orchestrator.onrender.com/health

# Web (redirección a /login en 200/302)
curl -I https://commerce-ops-web.onrender.com
```

Ver runbooks completos en `docs/operations/runbooks.md`.

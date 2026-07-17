# Runbook — Convergencia del claim de auth: habilitar hook + retirar trigger legacy

> **Origen:** hallazgo del gate anti-drift (W8, 2026-07-16). Verificado vía Management
> API que en prod `hook_custom_access_token_enabled = **False**`.

## Contexto (qué está pasando en prod)

El claim `app_metadata.tenant_id` / `app_metadata.role` del JWT autoriza en **los tres
planos**: API (`services/api/dependencies/auth.py` — `get_current_tenant` / `get_current_role`),
web (`apps/web/utils/supabase/cached-user.ts`) y RLS de Postgres (`app_current_tenant()` +
policies `role='owner'`/`IN ('owner','manager')`).

Ese claim lo puede mantener **una de dos** mecánicas:

| Mecánica | Qué hace | Estado en prod |
|---|---|---|
| **Trigger legacy** `on_tenant_assignment` → `handle_new_user_claims()` | Escribe `tenant_id`/`role` en `auth.users.raw_app_meta_data` en cada INSERT/UPDATE de `tenant_users`. **NO filtra `status`.** | ✅ **ACTIVO** (mantiene el claim hoy) |
| **Hook** `custom_access_token_hook(event)` | Deriva `tenant_id`/`role` de `tenant_users` (**con `status='active'`**) en CADA emisión de JWT y sobrescribe el claim; lo BORRA si no hay membresía activa. | ⚠️ función existe + con grant a `supabase_auth_admin`, pero el **toggle del dashboard está OFF** → NO corre |

**Conclusión:** el trigger legacy es **load-bearing**, no muerto. Las migraciones
(`20260426080000`) intentan dropearlo asumiendo que el hook tomó el relevo, pero el hook
nunca se habilitó → si el drop se hubiera aplicado, **el auth se habría roto**. El drift de
prod (retener el trigger) es lo que mantiene el auth funcionando.

**Gap de seguridad que esto deja abierto:** el trigger legacy NO filtra por `status='active'`.
A un miembro **removido/inactivado**, su `role` puede **persistir en su JWT** hasta el próximo
re-login. El hook lo limpiaría en la siguiente emisión de token; el trigger no.

---

## INTERVENCION HUMANA REQUERIDA

- **RESPONSABLE:** founder (toggle de dashboard = acción manual, fuera de migraciones) + asistente (verificación SQL + migración).
- **CRITERIO DE ÉXITO:** hook habilitado en prod, claims del JWT poblados **por el hook**
  (verificado), trigger legacy retirado, y un cambio de rol/inactivación se refleja en el JWT
  en el próximo login (cierra el gap de stale-role).
- **RIESGO:** aplicar el drop del trigger **antes** de verificar el hook → los claims dejan de
  propagarse → 403 en API, redirects en web, **denegación RLS**. Por eso el ORDEN es estricto.
- **REVERSIBLE:** sí — deshabilitar el toggle vuelve al estado actual; y el trigger se puede
  recrear (SQL de rollback al final).

## Pre-condiciones (ya verificadas 2026-07-16)

- [x] `public.custom_access_token_hook("event" jsonb)` existe en prod.
- [x] Tiene `GRANT ALL ... TO "supabase_auth_admin"` (requerido para que GoTrue lo invoque).
- [x] `handle_new_user_claims()` solo se referencia en su migración de creación
      (`20260406181239`) → dropearla no rompe nada más.

---

## Paso 0 — Verificar la LÓGICA del hook (antes de tocar nada, sin login)

Confirma que el hook deriva bien los claims para un usuario real con membresía activa. Contra
prod (**read-only**, con `.env.prod` + protocolo seguro / `psql` a prod):

```sql
-- Reemplazá <USER_ID> por un user_id con membresía 'active' en tenant_users.
SELECT public.custom_access_token_hook(
  jsonb_build_object(
    'user_id', '<USER_ID>'::text,
    'claims',  jsonb_build_object('app_metadata', '{}'::jsonb)
  )
) -> 'claims' -> 'app_metadata' AS app_metadata_resultante;
```

**CRITERIO:** devuelve `{"tenant_id": "...", "role": "..."}` correctos. Si sí → la lógica del
hook es correcta y solo falta habilitarlo.

## Paso 1 — Habilitar el hook (dashboard, founder, ~2 min)

Dashboard de `konvi-prod` → **Authentication → Hooks (Beta)** → **Custom Access Token** →
Enable → apuntar a `public.custom_access_token_hook` → Save.

## Paso 2 — Verificar que el JWT real trae el claim DEL HOOK (~5 min)

1. Cerrar sesión y volver a iniciar sesión en el backoffice (fuerza emisión de token nuevo).
2. En la consola del navegador (o vía el cliente Supabase) decodificar el `access_token` y
   confirmar que `app_metadata.tenant_id` y `app_metadata.role` están poblados.
3. Prueba del `status` filter (lo que el trigger NO hacía): en un tenant de prueba, inactivar
   una membresía (`UPDATE tenant_users SET status='inactive' ...`), re-login de ese usuario, y
   confirmar que el claim `role` **desaparece** del JWT. Revertir el estado tras la prueba.

**CRITERIO:** claims poblados con el hook activo + el claim se limpia al inactivar la membresía.
Si esto NO se cumple → **NO continuar**; deshabilitar el hook y revisar.

## Paso 3 — Retirar el trigger legacy (migración, protocolo seguro)

Solo tras el Paso 2 OK. Crear la migración y aplicarla con el protocolo seguro
(smoke `BEGIN..ROLLBACK` → apply → `supabase migration repair --status applied <ts>`):

```sql
-- <ts>_converge_drop_legacy_claims_trigger.sql
-- Retira la mecánica legacy de claims. El hook custom_access_token_hook ya es la
-- fuente viva del claim (verificado, con status='active'). Aplicar SOLO tras el
-- runbook docs/runbooks/converge-auth-claims-hook.md (hook habilitado + verificado).
DROP TRIGGER IF EXISTS on_tenant_assignment ON public.tenant_users;
DROP FUNCTION IF EXISTS public.handle_new_user_claims();
```

> Nota: esta migración es **idempotente para el replay** (el trigger ya está ausente en el
> schema que producen las migraciones desde `20260426080000`; la función se elimina). Tras
> aplicarla, regenerar el baseline canónico: `bash scripts/schema_drift_check.sh --update`.

## Paso 4 — Verificar post-drop

- Re-login OK; claims siguen poblados (ahora provistos por el hook, no el trigger).
- Un cambio de rol (`UPDATE tenant_users SET role=...`) se refleja en el JWT del próximo login.
- API/RLS/web autorizan correctamente (probar una acción owner-only).

## Rollback (si algo falla en Paso 3/4)

```sql
-- Recrea la mecánica legacy (fuente: 20260406181239_custom_claims_trigger.sql).
-- Recuperar el cuerpo EXACTO de handle_new_user_claims() de esa migración y recrearlo, luego:
CREATE OR REPLACE TRIGGER on_tenant_assignment
  AFTER INSERT OR UPDATE ON public.tenant_users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_claims();
```
Y/o deshabilitar el hook en el dashboard para volver 1:1 al estado actual.

---

## Follow-up separado — `rls_auto_enable()` (drift menor, no auth)

Prod tiene un event-trigger `rls_auto_enable()` (auto-habilita RLS en tablas nuevas) que
**ninguna migración define** (vive solo en prod). No es peligroso (red de seguridad), pero es
drift. Convergencia: una migración aditiva que lo formalice (crear la función + el event
trigger), luego `schema_drift_check.sh --update`. Independiente de la convergencia de auth.

# Supabase — plataforma base (Postgres + RLS + Auth + Realtime + Vault + Storage)

> Estado: VIGENTE · **Revalidación contra doc oficial vigente (Track 6): 2026-08-22** (fetch live supabase.com/docs — URLs citadas por fila en la matriz de la investigación).
> Este doc no repite el modelo de datos (ver `docs/backend/BACKEND.md` y `docs/architecture/`); cubre la **alineación con las capacidades oficiales vigentes** y las decisiones de adopción.

## Veredicto de la revalidación 2026-08-22

**Nuestro modelo sigue siendo el oficial.** Realtime Authorization (RLS sobre canales) NO es una migración obligatoria: la doc confirma que `postgres_changes` se autoriza con la RLS de la tabla origen, en canales públicos o privados ([realtime/authorization](https://supabase.com/docs/guides/realtime/authorization)). Las policies sobre `realtime.messages` solo gobiernan Broadcast/Presence — que no usamos todavía.

## Adoptado en esta revalidación (2026-08-22)

| Cambio | Detalle |
|---|---|
| **`select` de columnas en suscripciones realtime** | `use-messages.ts` + `use-conversations.ts` — la fila completa arrastra columnas pesadas y Realtime **trunca silencioso >1.024 KB** (campos >64 B se omiten del payload, [quotas](https://supabase.com/docs/guides/realtime/quotas)). Además: re-fetch por id cuando `content` no viaja (señal de truncamiento) y merge (no reemplazo) en UPDATE para no pisar campos omitidos |
| **Fallback de legacy keys eliminado** | `packages/auth/lib/client-browser.ts` + `server-client.ts`: sin `|| NEXT_PUBLIC_SUPABASE_ANON_KEY` (las legacy anon/service_role están desactivadas a nivel Supabase desde 2026-08-19 — el fallback era código muerto que convertiría una config faltante en un error críptico downstream) |
| **Runbook DR: root key de Vault** | Documentado en `docs/HANDOFF.md` §6: sin portar la root key de pgsodium vía Management API (`GET/PUT /v1/projects/{ref}/pgsodium`), un restore manual a proyecto nuevo deja **ilegibles todos los secretos de tenants** ([vault §key-portability](https://supabase.com/docs/guides/database/vault)) |
| **Verificación `payments_safe`** | La vista es deliberadamente security-definer + `security_barrier` + WHERE `tenant_id = app_current_tenant()` (la RESTRICTIVE owner-only de la tabla base no debe heredarse: la vista es la proyección segura para members). Cross-tenant anclado con test dbharness |

## Confirmado alineado (sin cambio)

- **Publicación + RLS por tenant** para realtime (conversations/messages/orders) — modelo oficial vigente; filtros server-side ya en uso; `REPLICA IDENTITY FULL` donde se consume `old`.
- **Vault per-tenant** vía wrappers `pgsec_*` con guarda owner/manager+active (Track 9) — uso alineado con la API oficial (`vault.create_secret`/`decrypted_secrets`).
- **API keys publishable/secret** adoptadas (G23); servicios verifican JWT vía **JWKS (ES256)** primario.
- **Storage**: buckets privados + RLS en `storage.objects` + signed URLs — alineado.

## Pendientes de plataforma (ops/founder, no código)

| Ítem | Qué falta |
|---|---|
| **Secret key por servicio** (best practice oficial: una `sb_secret_` por componente — rotación acotada ante leak) | Crear 4 en Dashboard → API Keys y asignar una por servicio en Render (misma var `SUPABASE_SECRET_KEY`, valores distintos). Sin cambio de código |
| **Cerrar ciclo JWT signing keys** | Verificar en Dashboard que la key activa es ES256 → esperar ≥ `jwt_expiry` (3600s) post-rotación → revocar legacy secret → PR que retira `SUPABASE_JWT_SECRET` de `render.yaml` y la rama HS256 de `services/api/dependencies/auth.py`. Precondición (legacy anon/service desactivadas) ya cumplida en G23 |
| **Plan real del proyecto** (Free vs Pro — define límites Realtime/Storage) | Registrar en HANDOFF al confirmarlo |

## Diseñado para el futuro (puntos de extensión)

- **Broadcast privado por tenant** (`tenant:{id}:inbox` con `private: true` + policies sobre `realtime.messages` + `realtime.broadcast_changes` en triggers): reemplazaría postgres_changes + polling fallback del inbox. La doc oficial lo marca como el camino para ese patrón; exige Realtime Authorization (obligatoria para broadcast-from-DB).
- **Presence** de operadores en el inbox (mismo canal privado).
- **Branching persistente** como STG cloud si se paga Pro (~$0,01344/branch/hora) — alternativa al "dev cloud" del PLAN §A #16.
- **TUS resumable uploads** solo si evidencias superan 6 MB.
- **Declarative schemas (pg-delta)**: NO adoptar — el diff no trackea `alter publication … add table` (nuestras 8 migraciones de publicación realtime quedarían invisibles); el ledger imperativo de 262+ migraciones funciona.

## Referencias oficiales (fetcheadas 2026-08-22)

- [realtime/postgres-changes](https://supabase.com/docs/guides/realtime/postgres-changes) (incl. §selecting-columns) · [realtime/authorization](https://supabase.com/docs/guides/realtime/authorization) · [realtime/quotas](https://supabase.com/docs/guides/realtime/quotas) · [realtime/broadcast](https://supabase.com/docs/guides/realtime/broadcast) · [realtime/presence](https://supabase.com/docs/guides/realtime/presence)
- [database/vault](https://supabase.com/docs/guides/database/vault) · [api/api-keys](https://supabase.com/docs/guides/api/api-keys) · [auth/signing-keys](https://supabase.com/docs/guides/auth/signing-keys)
- [storage/uploads](https://supabase.com/docs/guides/storage/uploads/standard-uploads) · [storage/downloads](https://supabase.com/docs/guides/storage/serving/downloads) · [deployment/branching](https://supabase.com/docs/guides/deployment/branching)

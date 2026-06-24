# ADR-0025 — Estrategia de aislamiento multi-tenant: lint AST + RLS GUC, NO wrapper

**Status**: Accepted (2026-06-24)
**Deciders**: Founder + AI Architect
**Context**: Finiquito NIVEL 2 A6 + super-audit `worwkgukx` + root-cause workflow `w7hw4n935`
**Supersedes**: R-04 (helper `scoped_table`, rev. 58 commit `4963bd10`)

---

## Contexto

El backend Konvi usa `service_role` de Supabase que **bypasea RLS**. Toda query a una tabla con `tenant_id` debe filtrar explícitamente por tenant, sino hay riesgo de fuga cross-tenant (un tenant ve datos de otro).

La estrategia original (R-04, abril 2026) fue el helper `scoped_table(supabase, "orders", tenant_id)` que auto-aplicaba `.eq("tenant_id", tenant_id)`. **Dos meses después su adopción era 0 callsites en producción** (verificado super-audit `w7hw4n935`): los 600+ queries usan el patrón explícito `.table(X).eq("tenant_id", tid)`.

Causas del rechazo orgánico del wrapper:
1. **DX inferior**: `.table(X).eq("tenant_id", tid)` es idiomático supabase-py (autocomplete, mocks triviales). El wrapper rompe esos ejes.
2. **No aplica cross-service**: `tenant_scope.py` vivía en `services/api/dependencies/`, inaccesible a `ai-orchestrator` (54% del scope DB) sin cross-service import.
3. **Bug semántico**: `scoped_table().insert()/.upsert()` aplicaba `.eq()` que NO afecta el payload PostgREST → falso sentido de seguridad.
4. **Sin enforcement**: el test de regresión (`test_tenant_isolation_audit.py`) solo verificaba que el string `'tenant_id'` existiera en el archivo, no por-query. Teatro de seguridad.

Además, super-audit reveló:
5. RLS está habilitado en 66/71 tablas, PERO el backend **nunca setea `app.current_tenant_id`** (GUC) → las policies que dependen de ese context son no-op contra service_role.
6. `pgsec_read_secret(uuid)` Vault RPC tiene GRANT a `authenticated` **sin validación de ownership** → riesgo de lectura cross-tenant de secrets.

---

## Decisión

**Aislamiento multi-tenant = defensa en capas SIN wrapper:**

1. **Patrón canónico de query**: `.table(X).eq("tenant_id", tid)` explícito para reads, `.insert({"tenant_id": tid, ...})` para writes. Idiomático, sin magia.

2. **Lint AST en CI** (`scripts/audit_tenant_filter.py`): detecta estáticamente cada query a tabla tenant-scoped que omita el filtro. Reemplaza el wrapper + el test-teatro previo. Características:
   - `TENANT_SCOPED_TABLES_EXTENDED` **derivado automáticamente** de `supabase/migrations/*.sql` (66 tablas con columna `tenant_id`) — sin drift hardcoded.
   - Detección por-query (AST), no por-archivo (string match).
   - Modos: `missing_eq`, `missing_payload_key_*`, `unverifiable_payload_*` (strict default).
   - Exemption marker `# tenant_filter:exempt:<reason>` para casos legítimos (webhook tenant resolution antes de tener tenant_id).
   - Baseline CSV + ratchet `BASELINE_MAX` decreciente: gaps solo pueden bajar.
   - `.github/CODEOWNERS` protege baseline + script (no se puede vaciar el guardrail sin review).

3. **RLS DB-enforced** (Fase A6.3 — RE-SCOPED 2026-06-24): el plan original (middleware `SET LOCAL app.current_tenant_id` por request) es **NO-VIABLE con el stack actual**. `supabase-py` habla con **PostgREST (HTTP stateless)**: cada query es un request independiente, así que un `SET LOCAL` no persiste a las queries siguientes de la misma "request" lógica. Hacerlo efectivo requeriría envolver TODAS las queries en RPCs (impráctico) o una capa psycopg con connection pooling per-tenant (rework arquitectónico mayor, varias sesiones). **Decisión:** diferir GUC enforcement. La cobertura ya es adecuada sin él:
   - **service_role** (backend, bypasea RLS) → cubierto por el **lint AST A6.2.7** (0 gaps, CI-enforced).
   - **authenticated** (frontend, NO bypasea RLS) → ya protegido por las policies RLS existentes. Cobertura verificada 2026-06-24: **65/66 tablas tenant-scoped con policy `tenant_id = app_current_tenant()`**; `tenant_users` ya tiene policy (`20260415000000`); la única sin policy es `rate_limit_windows` (infra sin columna `tenant_id`, solo backend la usa → RLS-enabled sin policy = locked a service_role, postura correcta).
   - Re-evaluar GUC solo si se adopta la capa psycopg directa o un ORM con tenant scoping nativo.

4. **Vault RPC ownership** (Fase A6.4 — migración autorada 2026-06-24): `pgsec_read/update/delete/upsert/create_secret` validan internamente ownership. El nombre del secret codifica `{tenant_id}/provider/credential`, así que el RPC deriva el tenant dueño (`split_part(name,'/',1)::uuid`) y exige que el `authenticated` sea miembro vía `public.tenant_users`; `service_role` (auth.uid() NULL) bypasa. Sigue el precedente `get_aveonline_credentials` (`20260527020000`). **NO** requiere tabla metadata ni dual-read (el nombre ya es la fuente de verdad del owner). Migración: `20260624000000_vault_rpc_tenant_ownership.sql`. **INTERVENCION HUMANA**: aplicar a dev → verificar lectura propia + cross-tenant=NULL + smoke frontend/bot → aplicar a prod.

5. **Webhooks resuelven tenant ANTES del primer query tenant-scoped** (per ADR-0023 Direct Provider): vía secret per-tenant o path `/webhook/{tenant_id}`. Los lookups de resolución llevan exemption marker.

6. **`scoped_table` ELIMINADO**: `services/api/dependencies/tenant_scope.py` + `tests/test_tenant_isolation_audit.py` borrados (A6.5). 0 adopción, bug insert, no cross-service.

---

## Reglas de oro

1. **Toda query nueva a tabla en `TENANT_SCOPED_TABLES_EXTENDED`** requiere `.eq("tenant_id", tid)` (read) o `tenant_id` en payload (write) + el lint lo enforce en CI.
2. **El set de tablas se deriva de migrations**, nunca se hardcodea. Migration nueva con `tenant_id` → regenerar baseline.
3. **Defensa en capas**: lint (estático) + RLS GUC (runtime DB) + Vault ownership (secrets). Ninguna capa sola es suficiente.
4. **Webhooks son la excepción documentada**: resuelven tenant primero, exemption marker explícito.

---

## Consecuencias

### Positivas
- DX intacta — developers escriben supabase-py idiomático.
- Cobertura cross-service (el lint escanea api + ai-orchestrator + connector).
- Set de tablas sin drift (derivado de migrations).
- Regression-proof por construcción (CI falla en gap nuevo).
- RLS existente capitalizado (no se reescriben 600 callsites).

### Negativas (trade-offs aceptados)
- El lint NO puede verificar payloads variables estáticamente (flag `unverifiable_payload_*` los marca para revisión manual, no los resuelve).
- RLS GUC añade ~0.5ms/request (SET LOCAL). Despreciable.
- 198 gaps en baseline al momento de A6.1 (deuda real expuesta) — se reducen en A6.2.7 fix puntuales.

### Triggers para revisitar
- Si Konvi adopta un ORM (SQLAlchemy/Prisma) con tenant scoping nativo → re-evaluar lint.
- Si volumen de exemptions crece >20 → revisar si el patrón webhook necesita refactor.

---

## Estado de implementación (Fase A6)

| Sub-fase | Item | Status |
|---|---|---|
| A6.1 | Lint AST + baseline + CI | ✅ DONE (commit 660e2b3f) |
| A6.2.1 | Defensa silent regression P1 (dispatcher) | ✅ DONE |
| A6.2.2 | Schema discovery automático | ✅ DONE |
| A6.2.3 | Lint strictness payload | ✅ DONE |
| A6.2.4 | CODEOWNERS + ratchet | ✅ DONE |
| A6.2.5 | Runner pytest + cross-test fix | ✅ DONE |
| A6.5 | Eliminar scoped_table + ADR-0025 | ✅ DONE (este ADR) |
| A6.2.7 | Cierre TOTAL gaps tenant_filter 198→0 + Telegram raíz | ✅ DONE (`BASELINE_MAX=0`) |
| A6.3 | RLS GUC middleware | 🔶 RE-SCOPED (GUC no-viable con PostgREST — ver abajo) |
| A6.4 | Vault RPC ownership | 🟡 MIGRACIÓN AUTORADA (pendiente apply prod, founder) |
| A7 | RBAC marketplace + ai_agents (+ Telegram constant-time en A6.2.7) | ✅ DONE |

---

## Referencias

- Root-cause workflow `w7hw4n935` (Opción E híbrida vs wrapper big-bang)
- Super-audit `worwkgukx` (lint baseline integrity gotchas)
- ADR-0023 (Direct Provider — webhook tenant resolution)
- ADR-0024 (tests/invariants binarios — el lint es AST binario, no semántico)
- `scripts/audit_tenant_filter.py` + `tests/test_audit_tenant_filter.py`
- `gaps_tenant_filter_baseline.csv` + `.github/CODEOWNERS`

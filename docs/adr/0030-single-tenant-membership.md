# ADR-0030 — Membresía single-tenant: un usuario pertenece a un solo negocio

**Status**: Accepted (2026-07-04)
**Deciders**: Founder + AI Architect
**Context**: Fase 0 completeness audit — decisión `impl_team_rbac` (business_call, group F6)
**Relacionado**: ADR-0025 (aislamiento multi-tenant), F10 hardening `add_member_to_tenant`

---

## Contexto

El schema (`tenant_users`) modelaba membresía con `UNIQUE(user_id, tenant_id)`, lo que
**permitía** que un mismo humano fuera miembro de N tenants. La UI de invitación y el
`removeMember` incluso contemplaban ese caso ("membresía multi-tenant permitida por el schema").

Pero el `custom_access_token_hook` (inyecta `tenant_id`/`role` en el JWT) leía con
`LIMIT 1` **sin `ORDER BY`** → para un usuario en >1 tenant el JWT elegía tenant de forma
**no determinista**. Estado incoherente: permitido por schema, roto en el JWT. Bug latente
de seguridad/UX (entrar al negocio equivocado).

No existe hoy caso de negocio real de un operador gestionando múltiples marcas con una
sola cuenta. Konvi es onboarding ADMIN-controlado, un negocio por operador.

## Decisión

**Un usuario pertenece a UN solo tenant (single-tenant membership).** Se prohíbe la
multi-membresía. Enforcement en capas (autoritativo en DB):

1. **JWT determinista** — `custom_access_token_hook` con `ORDER BY` estable
   (owner → manager → operator, luego `created_at ASC`, luego `tenant_id`). Correcto
   aun antes del `UNIQUE` (defensa en profundidad).
2. **`add_member_to_tenant` rechaza membresía cruzada** — si el `user_id` ya pertenece a
   otro tenant, `RAISE EXCEPTION` con `ERRCODE unique_violation`. Choke-point que cubre el
   invite de usuario existente y cualquier caller `service_role`. Preserva el hardening F10
   (`SET search_path`).
3. **`UNIQUE(user_id)`** en `tenant_users` — enforcement duro. Migration **guardado**: si ya
   hay usuarios en >1 tenant, aborta con `INTERVENCION HUMANA REQUERIDA` en vez de fallar opaco.
4. **Frontend** (`dashboard/team/page.tsx`) — pre-valida y muestra copy amigable
   (`error=ya-en-otro-negocio`); la verdad la impone la DB.

Migration: `supabase/migrations/20260704156200_f6_single_tenant_membership.sql` (idempotente,
NO auto-aplicado; degradación segura: sin aplicar, se mantiene el comportamiento vigente).

## Consecuencias

- Si en el futuro Konvi vende a operadores multi-marca, revertir es un cambio grande:
  drop `UNIQUE(user_id)`, añadir selector de tenant en login + `ORDER BY` ya existe, y
  revisar `removeMember`/`deleteUser` (hoy soft-delete de cuenta al salir del único tenant).
  Ese camino queda documentado aquí pero NO implementado.
- El `removeMember` conserva el chequeo `otherMemberships` como defensa en profundidad
  (relevante sólo si el migration aún no está aplicado).

## INTERVENCION HUMANA REQUERIDA

- **RESPONSABLE**: Founder / DBA.
- **PASOS**: aplicar `20260704156200_f6_single_tenant_membership.sql` al remote (protocolo de
  migraciones con drift del ledger). Si aborta por membresías cruzadas, resolver manualmente
  antes de reintentar.
- **CRITERIO DE EXITO**: constraint `tenant_users_user_id_unique` presente; login de un usuario
  emite JWT con `tenant_id` estable; invitar a un email ya-miembro de otro negocio devuelve el
  error amigable.

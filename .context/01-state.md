# Current Scope — Estado Real de Implementación

**Última actualización**: 2026-04-19 (rev. 26)
**Fuente de verdad**: código en el repo (`develop`) + migraciones en `supabase/migrations/`.
**Tree funcional vigente**: `.context/00-product.md`.

---

## Estado Ejecutivo

- **Tenant Console**: ✅ Live (fases 1–11.5 completas)
- **Platform Console**: ❌ fuera de alcance (bloqueante OQ-P01)
- **Backend**: ✅ API + Connector WhatsApp + AI Orchestrator operativos
- **DB**: ✅ contrato endurecido (35 migraciones)

---

## Contratos Canónicos (runtime)

### 1) Conversaciones

Contrato único en runtime y DB:
- `bot_active`
- `human_takeover`
- `closed`

Aplicado en:
- `supabase` (normalización + constraint)
- API (`services/api/routers/conversations.py`)
- Frontend Inbox (`apps/web/app/dashboard/inbox/page.tsx`)
- Connector/Worker/Orchestrator

### 2) Procesamiento de mensajes inbound

`messages` ahora usa outcome explícito:
- `processing_status`: `pending | processed | skipped | failed`
- `skip_reason`
- `last_error`
- `processing_attempts`

`processed` se mantiene por compatibilidad, pero el loop usa `processing_status='pending'`.

### 3) Human takeover / closed

Comportamiento efectivo:
- Si conversación está en `human_takeover`: el bot no responde.
- Si conversación está en `closed`: el bot no responde y no reabre automáticamente.
- Mensajes no-texto: no respuesta automática, se escalan a `human_takeover` y quedan visibles en Inbox.

### 4) RBAC runtime

Roles vivos en runtime:
- `owner`
- `manager`
- `operator`

`agent` no existe en runtime; queda únicamente en migraciones históricas.

### 5) OAuth Mercado Libre

`state` OAuth endurecido:
- firmado (HMAC)
- con expiración
- nonce one-time persistido en DB (anti-replay)
- callback rechaza `state` faltante/inválido/expirado/reutilizado antes de persistir tokens

### 6) Credenciales WhatsApp

Fuente única runtime:
- `tenant_integrations` por `tenant_id`

No hay fallback a `META_ACCESS_TOKEN` ni `WHATSAPP_PHONE_ID` en senders (API/Orchestrator).
El connector solo recibe webhooks; no envía mensajes.

### 7) Seguridad multi-tenant (service_role)

El backend usa `service_role` en varios paths, por lo que:
- RLS **no** es barrera suficiente por sí sola en esos paths
- aislamiento runtime depende de filtros explícitos `tenant_id` + RLS donde aplique

Se reforzaron filtros explícitos en paths críticos (`orders`, `shipping`, `marketplace`, `meli_webhook`).

---

## Frontend — ajustes estructurales

- `meliBadge` ya no está hardcodeado; se calcula desde `marketplace_listings`.
- Badge MeLi renderiza correctamente también cuando `Mercado Libre` es child item dentro de grupo sidebar.
- `/dashboard/inventory` legacy quedó como redirección explícita a `/dashboard/catalog`.
- Se eliminaron links operativos residuales que trataban Inventory como módulo standalone.

---

## Migraciones recientes (2026-04-19)

- `20260419000000_conversation_processing_contract.sql`
  - backfill de estados legacy conversación
  - constraint canónico de conversación
  - contrato explícito de procesamiento de mensajes

- `20260419000001_rbac_operator_runtime_only.sql`
  - backfill `agent -> operator`
  - constraint de roles runtime

- `20260419000002_meli_oauth_state_store.sql`
  - tabla `integration_oauth_states` para nonce one-time de OAuth MeLi

---

## Validación ejecutada en esta sesión

- `python3 -m unittest discover -s tests -p 'test_*.py'` ✅ (27 tests)
- `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
- `pnpm --filter web lint` ✅ (con warnings preexistentes, sin errores)

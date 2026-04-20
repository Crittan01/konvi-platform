# Current Scope — Estado Real de Implementación

**Última actualización**: 2026-04-20 (rev. 31)
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
- `/integrations/meli/auth-url` responde `503` con detalle explícito de env vars faltantes si la app MeLi no quedó configurada completa en API

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

### 8) Shipping Envia (CO) — contrato de dirección endurecido

- En runtime CO, el backend acepta DANE de 5 u 8 dígitos y normaliza a `stat_8digit` para cotizar (ej. `11001 -> 11001000`).
- Para Colombia, payload de Shipping API usa:
  - `city = dane_8digit`
  - `postalCode = dane_8digit`
- Se retiró la prevalidación bloqueante por Queries `city`/`zipcode` en quote (en cuenta actual esos endpoints retornan `404`).
- Para CO, payload de Shipping API mantiene contrato:
  - `city = dane_code` (normalizado a 8 dígitos)
  - `postalCode = dane_code` (normalizado a 8 dígitos)
- Se eliminó campo no documentado `city_to_display` del payload hacia Envia.
- Descubrimiento de carriers prioriza Queries API (`available-carrier`) con fallback operativo si Queries falla.

---

## Frontend — ajustes estructurales

- `meliBadge` ya no está hardcodeado; se calcula desde `marketplace_listings`.
- Badge MeLi renderiza correctamente también cuando `Mercado Libre` es child item dentro de grupo sidebar.
- `/dashboard/inventory` legacy quedó como redirección explícita a `/dashboard/catalog`.
- Se eliminaron links operativos residuales que trataban Inventory como módulo standalone.
- Inbox lista conversaciones por `last_interaction_at` y usa `created_at` solo como fallback visual.
- Inbox muestra estado de error explícito si falla la carga del listado de conversaciones.
- Sidebar ahora bloquea módulos dependientes de integración cuando están desconectados:
  - `Inbox` (requiere `whatsapp`)
  - `Cotizador` (requiere `envia`)
  - `Mercado Libre` (requiere `mercadolibre`)
- Se corrigió bug legacy que construía `dane_code` inválido (`+000`) en selector de direcciones.
- `settings.shipping_origin` ahora preserva `dane_code` explícito y mantiene `postal_code`/`dane_code` alineados para Envia.

---

## Migraciones recientes (2026-04-20)

- `20260420000000_marketplace_listings_meli_fields.sql`
  - Agrega a `marketplace_listings`: `meli_title`, `meli_thumbnail`, `meli_condition`, `meli_category_id`, `meli_attributes`, `synced_at`
  - Habilita sync pull MeLi → Supabase

- `20260420000001_order_tracking.sql`
  - Nueva tabla `order_tracking` con RLS
  - Centraliza tracking de envíos multi-proveedor (`mercadolibre`, `envia`)
  - Alimentada desde webhook `shipments` MeLi; Envia Fase 2 también escribirá aquí

---

## Contratos MeLi (2026-04-20)

### Sync pull MeLi → Supabase
Campos en `marketplace_listings` actualizados por tres vías:
- Webhook `items`: actualización reactiva ante cambios en MeLi
- `sync_meli_stock()` (sync manual / post-orden): aprovecha el GET previo
- `link_listing()` y `import_from_meli()`: pull inmediato al vincular o importar

### Shipment tracking
- Webhook `shipments`: avanza estado de orden **y** persiste en `order_tracking`
- `order_tracking` es multi-proveedor: `provider = 'mercadolibre' | 'envia'`
- Select/insert-or-update idempotente por `(tenant_id, provider, external_id)`

### Contactos desde órdenes MeLi
- `_process_order()` intenta crear contacto si `buyer.billing_info.phone` está disponible
- Upsert idempotente por `(tenant_id, phone)` — no crea datos fake si no hay teléfono
- `contact_id` se enlaza en la orden al crearse

---

## Migraciones anteriores (2026-04-19)

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

## UX Mercado Libre (2026-04-20)

- `marketplace-manager.tsx`: filtros por estado (Todos / Activos / Pausados / Cerrados / Sin vincular)
- Badge de condición (`Nuevo` / `Usado`) en columna de publicación
- Filtrado combinado: tab de estado + búsqueda por texto

---

## Validación ejecutada en esta sesión

- `python3 -m unittest discover -s tests -p 'test_*.py'` ✅ (27 tests)
- `node --test apps/web/tests/marketplace-badges.test.mjs` ✅
- `pnpm --filter web lint` ✅ (con warnings preexistentes, sin errores)
- `python3 -m py_compile services/api/integrations/envia_client.py services/api/routers/shipping.py` ✅

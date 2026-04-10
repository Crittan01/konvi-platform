# Esquema de Base de Datos — Commerce Ops Platform

Última actualización: 2026-04-10 (rev. 3 — 13 migraciones, low_stock_threshold + consent añadidos)

Supabase PostgreSQL — Proyecto: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1)

> **Nota de estructura**: Las migraciones canónicas están en `supabase/migrations/`.
> `packages/db/migrations/` solo contiene las 5 iniciales (mirrors parciales sin las de Fases 9-11).

---

## Migraciones aplicadas (13 total)

| Migración | Descripción | Fase | Estado |
|-----------|-------------|------|--------|
| `20260406181235` | tenants + tenant_users | 2 | ✅ Aplicada |
| `20260406181236` | products + product_variations | 2 | ✅ Aplicada |
| `20260406181237` | conversations + messages | 3b | ✅ Aplicada |
| `20260406181238` | RLS policies + `app_current_tenant()` | 2 | ✅ Aplicada |
| `20260406181239` | Custom claims trigger (JWT con tenant_id) | 2 | ✅ Aplicada |
| `20260407200700` | messages.processed + índice parcial | 6 | ✅ Aplicada |
| `20260409220000` | contacts + orders + order_items + tenant_integrations + notification_settings | 9 | ✅ Aplicada |
| `20260409230000` | shipments | 9 | ✅ Aplicada |
| `20260409240000` | stock_movements | 11 | ✅ Aplicada |
| `20260409250000` | kb_documents | 11 | ✅ Aplicada |
| `20260409260000` | audit_log | 11 | ✅ Aplicada |
| `20260410010000` | tenants.low_stock_threshold (umbral configurable por tenant) | 11 | ✅ Aplicada |
| `20260410020000` | contacts.consent_given + consent_date (Habeas Data) | 11 | ✅ Aplicada |

---

## Tablas vigentes

### `tenants`

```sql
tenants (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active',   -- active, suspended, inactive
  meta_waba_id    TEXT,                              -- WhatsApp Business Account ID
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `id = app_current_tenant()`

**Tenant activo en dev**: `Matriz Commerce Dev` — `meta_waba_id = 2159052118202272`

---

### `tenant_users`

```sql
tenant_users (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES auth.users(id),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  role        TEXT NOT NULL DEFAULT 'agent',   -- owner, manager, agent
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `tenant_id = app_current_tenant()`

---

### `products`

```sql
products (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id               UUID NOT NULL REFERENCES tenants(id),
  title                   TEXT NOT NULL,
  description             TEXT,
  status                  TEXT NOT NULL DEFAULT 'active',
  external_reference_id   TEXT,      -- ID en Mercado Libre u otro marketplace
  is_active               BOOLEAN NOT NULL DEFAULT true,   -- soft delete
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `tenant_id = app_current_tenant()`

---

### `product_variations`

```sql
product_variations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id      UUID NOT NULL REFERENCES products(id),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  price           NUMERIC(10,2),
  stock_quantity  INTEGER NOT NULL DEFAULT 0,
  attributes      JSONB,    -- {color: "rojo", talla: "M"}
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `tenant_id = app_current_tenant()`

---

### `conversations`

```sql
conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  customer_phone  TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'bot_active',   -- bot_active, human_takeover, closed
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `tenant_id = app_current_tenant()`

---

### `messages`

```sql
messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  direction       TEXT NOT NULL,          -- inbound, outbound
  content_type    TEXT NOT NULL DEFAULT 'text',   -- text, image, audio, etc.
  content         TEXT,
  meta_message_id TEXT,                   -- ID de mensaje en WhatsApp
  processed       BOOLEAN NOT NULL DEFAULT false,    -- para el AI Orchestrator
  processed_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `tenant_id = app_current_tenant()`

**Índice parcial (optimización AI Orchestrator)**:
```sql
CREATE INDEX idx_messages_unprocessed ON public.messages (created_at)
WHERE processed = false AND direction = 'inbound';
```

---

## Tablas vigentes — Fases 9-11 (migración `20260409220000` y siguientes)

Las siguientes tablas fueron creadas en las Fases 9 y 11. Todas están aplicadas en producción.

### `orders` — Pedidos

```sql
-- APLICADA: migración 20260409220000
orders (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  conversation_id UUID REFERENCES conversations(id),
  customer_phone  TEXT,
  status          TEXT NOT NULL DEFAULT 'pending',   -- pending, confirmed, shipped, delivered, cancelled
  total_amount    NUMERIC(10,2),
  shipping_status TEXT,
  notes           TEXT,
  metadata        JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ
)
```

### `order_items` — Líneas de pedido

```sql
-- APLICADA: migración 20260409220000
order_items (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id        UUID NOT NULL REFERENCES orders(id),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  product_id      UUID REFERENCES products(id),
  variation_id    UUID REFERENCES product_variations(id),
  quantity        INTEGER NOT NULL,
  unit_price      NUMERIC(10,2) NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

### `contacts` — Clientes del tenant

```sql
-- APLICADA: migración 20260409220000
contacts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  phone       TEXT NOT NULL,
  name        TEXT,
  email       TEXT,
  metadata    JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ
)
```

### `shipments` — Envíos (Envia)

Ver detalle completo en `docs/integrations/courier-envia.md`.

```sql
-- APLICADA: migración 20260409230000
shipments (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID NOT NULL REFERENCES tenants(id),
  order_id            UUID REFERENCES orders(id),
  status              TEXT NOT NULL DEFAULT 'quoted',
  carrier             TEXT,
  service             TEXT,
  origin_address      JSONB NOT NULL,
  destination_address JSONB NOT NULL,
  parcels             JSONB NOT NULL,
  quote_response      JSONB,
  selected_rate       JSONB,
  label_url           TEXT,
  tracking_number     TEXT,
  tracking_url        TEXT,
  envia_shipment_id   TEXT,
  pickup_id           TEXT,
  estimated_delivery  DATE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ
)
```

### `tenant_integrations` — Configuración de conectores por tenant

```sql
-- APLICADA: migración 20260409220000
tenant_integrations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  provider        TEXT NOT NULL,   -- mercadolibre, envia, shopify, telegram
  status          TEXT NOT NULL DEFAULT 'connected',   -- connected, disconnected
  credentials     JSONB,           -- tokens, api_key, sandbox flag (sensible — no exponer en frontend)
  meta            JSONB,           -- datos no-sensibles (ej: meli_user_id, empresa_id)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ,
  UNIQUE (tenant_id, provider)
)
```

RLS: `tenant_id = app_current_tenant()`

**Estado en dev**: MeLi conectado (user_id `603780765`). Envia Sandbox conectado (Empresa #5017).

---

### `notification_settings` — Configuración de notificaciones

```sql
-- APLICADA: migración 20260409220000
notification_settings (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  channel         TEXT NOT NULL,   -- email, telegram, whatsapp
  enabled         BOOLEAN NOT NULL DEFAULT true,
  config          JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

---

### `stock_movements` — Historial de cambios de stock

```sql
-- APLICADA: migración 20260409240000
stock_movements (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  variation_id    UUID NOT NULL REFERENCES product_variations(id),
  delta           INTEGER NOT NULL,     -- positivo = entrada, negativo = salida
  new_stock       INTEGER NOT NULL,     -- stock resultante
  reason          TEXT,                 -- sale, restock, adjustment, sync_meli
  created_by      TEXT,                 -- email del operador
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `tenant_id = app_current_tenant()`

---

### `kb_documents` — Knowledge Base

```sql
-- APLICADA: migración 20260409250000
kb_documents (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  title       TEXT NOT NULL,
  content     TEXT NOT NULL,
  category    TEXT NOT NULL DEFAULT 'general',   -- faq, politica, negocio, producto, general
  is_active   BOOLEAN NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ   -- actualizado via trigger
)
```

RLS: `tenant_id = app_current_tenant()`

**Uso en AI**: `kb_tool.py` → `format_kb_for_prompt()` inyecta KB activa en system prompt del Orchestrator.
**Sin pgvector**: inyección de texto plano (markdown). PV-04 pendiente para RAG real.

---

### `audit_log` — Trazabilidad de acciones

```sql
-- APLICADA: migración 20260409260000
audit_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id),   -- NULL para acciones de plataforma (futuro)
  action          TEXT NOT NULL,    -- product.create, order.update, conversation.takeover
  entity_type     TEXT,             -- product, order, contact, shipment, etc.
  entity_id       UUID,
  payload         JSONB,            -- snapshot del recurso o diff
  user_email      TEXT,             -- snapshot del email del operador
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

RLS: `tenant_id = app_current_tenant()`

---

## Tablas pendientes — Fase 12 (Platform Console)

| Tabla | Propósito | Fase |
|-------|-----------|------|
| `platform_users` | Roles de operadores de plataforma (superadmin, support, ops) | 12 |
| `tenant_plans` | Planes de suscripción por tenant (billing) | 12 |
| `feature_flags` | Flags por tenant o por plan | 12 |

> Ninguna de estas tablas debe crearse antes de decidir OQ-P01 (arquitectura Platform Console).

---

## Función central: `app_current_tenant()`

```sql
CREATE OR REPLACE FUNCTION app_current_tenant()
RETURNS UUID
LANGUAGE sql STABLE
AS $$
  SELECT COALESCE(
    NULLIF(current_setting('app.current_tenant_id', true), '')::uuid,
    (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );
$$;
```

Dos vías de resolución:
- **Frontend (Next.js)**: JWT de Supabase Auth contiene `app_metadata.tenant_id`
- **Workers backend**: Usan `service_role` + `SET app.current_tenant_id = '<uuid>'`

---

## Regla de acceso a la DB

```bash
# Única forma funcional desde esta VM (TCP bloqueado por Supavisor)
supabase db query --linked "SELECT * FROM tenants;"
supabase db query --linked -f supabase/migrations/archivo.sql
```

---

## Documentos relacionados

- `docs/data/rls-policies.md` — Políticas RLS detalladas
- `docs/data/tenant-isolation.md` — Aislamiento multi-tenant
- `docs/data/audit-model.md` — Modelo de auditoría
- `docs/architecture/multi-tenant-security.md` — Contratos de seguridad
- `docs/integrations/courier-envia.md` — Schema de shipments

# Esquema de Base de Datos — Commerce Ops Platform

Última actualización: 2026-04-09

Supabase PostgreSQL — Proyecto: `***SUPABASE_PROJECT_REF_REDACTED***` (us-east-1)

---

## Migraciones aplicadas (6 total)

| Migración | Descripción | Estado |
|-----------|-------------|--------|
| `20260406181235` | tenants + tenant_users | ✅ Aplicada |
| `20260406181236` | products + product_variations | ✅ Aplicada |
| `20260406181237` | conversations + messages | ✅ Aplicada |
| `20260406181238` | RLS policies + `app_current_tenant()` | ✅ Aplicada |
| `20260406181239` | Custom claims trigger (JWT con tenant_id) | ✅ Aplicada |
| `20260407200700` | messages.processed + índice parcial | ✅ Aplicada |

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

## Tablas pendientes de crear

Las siguientes tablas son necesarias para completar el producto. No están en el schema todavía.

### `orders` — Pedidos

```sql
-- DISEÑO — pendiente migración
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
-- DISEÑO — pendiente migración
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
-- DISEÑO — pendiente migración
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

Ver diseño completo en `docs/integrations/courier-envia.md`.

```sql
-- DISEÑO — pendiente migración
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
-- DISEÑO — pendiente migración
tenant_integrations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  integration     TEXT NOT NULL,   -- mercadolibre, envia, shopify, telegram
  status          TEXT NOT NULL DEFAULT 'active',
  config          JSONB,           -- config no-sensible
  encrypted_creds TEXT,            -- tokens encriptados
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ,
  UNIQUE (tenant_id, integration)
)
```

### `audit_log` — Trazabilidad de acciones

```sql
-- DISEÑO — pendiente migración
audit_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id),   -- NULL para acciones de plataforma
  user_id         UUID REFERENCES auth.users(id),
  action          TEXT NOT NULL,    -- product.create, order.update, conversation.takeover...
  resource_type   TEXT,
  resource_id     UUID,
  metadata        JSONB,
  ip_address      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

### `stock_movements` — Historial de cambios de stock

```sql
-- DISEÑO — pendiente migración
stock_movements (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  variation_id    UUID NOT NULL REFERENCES product_variations(id),
  delta           INTEGER NOT NULL,   -- positivo = entrada, negativo = salida
  reason          TEXT,   -- sale, restock, adjustment, sync_meli
  reference_id    UUID,   -- FK a order o shipment si aplica
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

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

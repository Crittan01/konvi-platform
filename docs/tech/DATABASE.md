# Realidad de Base de Datos — Snapshot Empírico

Este documento refleja el estado **real** de la base de datos `public` en Supabase, verificado mediante inspección directa vía CLI (abril 2026).

## Aislamiento Multi-tenant (RLS)

El sistema utiliza un modelo de aislamiento basado en `tenant_id` (UUID).

### Mecanismo de Resolución: `app_current_tenant()`
Verificado en DB:
```sql
CREATE OR REPLACE FUNCTION app_current_tenant()
RETURNS UUID AS $$
  SELECT COALESCE(
    NULLIF(current_setting('app.current_tenant_id', true), '')::uuid,
    (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );
$$ LANGUAGE sql STABLE;
```

---

## Inventario de Tablas (Realidad Comprobada)

### 1. Núcleo (Tenants & Auth)
- **tenants**: `id`, `name`, `status`, `meta_waba_id`, `shipping_origin`, `low_stock_threshold`, `logo_url`.
- **tenant_users**: `id`, `user_id`, `tenant_id`, `role`.
- **platform_categories**: `id`, `name`, `slug`, `icon` (Verificado: Usado en importación de MeLi).

### 2. Catálogo e Inventario
- **products**: `id`, `tenant_id`, `title`, `description`, `status`, `cover_image_url`, `platform_category_id`.
- **product_variations**: `id`, `product_id`, `price`, `stock_quantity`, `sku`, `attributes`, `cost_price`.
- **stock_movements**: `id`, `tenant_id`, `variation_id`, `delta`, `new_stock`, `reason` (sale, restock, manual).

### 3. Ventas y CRM
- **orders**: `id`, `tenant_id`, `contact_id`, `status`, `total_amount`, `notes`.
- **order_items**: `id`, `order_id`, `product_id`, `quantity`, `unit_price`, `unit_cost`.
- **contacts**: `id`, `tenant_id`, `phone`, `name`, `email`, `consent_given`.
- **conversations**: `id`, `tenant_id`, `customer_phone`, `status` (bot_active, human_takeover).
- **messages**: `id`, `conversation_id`, `direction`, `content`, `processed`.

### 4. Canales e Integraciones
- **tenant_integrations**: `id`, `tenant_id`, `provider`, `status`, `credentials`, `meta`.
- **marketplace_listings**: `id`, `tenant_id`, `variation_id`, `external_id`, `status`.
- **shipments**: `id`, `tenant_id`, `order_id`, `status`, `carrier`, `tracking_number`.

---

## Auditoría de Seguridad RLS (Resumen CLI)

| Tabla | Política | Estado |
|-------|----------|--------|
| `tenants` | `id = app_current_tenant()` | ✅ CORRECTO |
| `orders` | `tenant_id = app_current_tenant()` | ✅ CORRECTO |
| `products` | `tenant_id = app_current_tenant()` | ✅ CORRECTO |
| `marketplace_listings` | `tenant_id = auth.uid()` | ❌ **ERROR** (Debe ser `app_current_tenant()`) |
| `claims` | `tenant_id = app_current_tenant()` | ✅ CORRECTO |

> [!WARNING]
> La tabla `marketplace_listings` requiere una corrección inmediata en la política de RLS para alinearse con el aislamiento multi-tenant del resto del sistema.

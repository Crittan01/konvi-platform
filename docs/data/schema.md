# Esquema de Base de Datos Base (Supabase / Postgres)

El módulo de base de datos está físicamente resuelto en `packages/db/migrations`.

## 1. Módulo Tenants (`00001_initial_schema.sql`)
- **`tenants`**: Almacena el `tenant_id` maestro. Atado al WABA ID de WhatsApp.
- **`tenant_users`**: Relación Many-to-Many contra la tabla interna de de Supabase `auth.users`, decidiendo si el usuario es _owner_ o _agent_.

## 2. Módulo Catálogo (`00002_catalog_schema.sql`)
- **`products`**: Nodos padres. Omiten stock, son genéricos. Contienen un `external_reference_id` para acoplar con Mercado Libre.
- **`product_variations`**: Hijos descriptivos (JSON en `attributes`). Poseen precio propio y el _holy grail_ del `stock_quantity`.

## 3. Módulo Conversacional (`00003_conversational_schema.sql`)
- **`conversations`**: Un hilo atado a un `customer_phone` con un estado (`bot_active` vs `human_handoff`).
- **`messages`**: Log de inputs (inbound) y outputs del bot (outbound). El campo `content_type` especifica si debemos leer `content` text o `media_url`.

*Nota de Extensión:* Cada tabla contiene un FK `tenant_id` para garantizar el aislamiento nativo de Row-Level Security.
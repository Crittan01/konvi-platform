# Schema Canónico — DB Live (rev. 72)

**Fuente de verdad operacional**: la DB Supabase viva (`***SUPABASE_PROJECT_REF_REDACTED***`).
**NO** las migraciones SQL en `supabase/migrations/` — esas son **history reproducible**.

Este documento se mantiene en sincro con `tests/fixtures/db_schema_canonical.json`,
generado por `scripts/dump_schema_canonical.py` desde `information_schema`.

## Cómo regenerar

```bash
python3.11 scripts/dump_schema_canonical.py            # genera fixture
python3.11 scripts/dump_schema_canonical.py --diff     # detecta drift live vs fixture
```

Ejecutar tras cualquier rev. con cambio de schema. Commitear el JSON junto al
cambio de código. Tests `tests/test_coherence_pact.py` usan este fixture como
golden file.

---

## Tablas core (25 capturadas en el fixture rev. 72)

A continuación el shape compacto. Para detalle completo (tipos, defaults,
nullable) ver `tests/fixtures/db_schema_canonical.json`.

### Identidad y configuración

#### `tenants` (22 columnas)
Root del aislamiento multi-tenant. Sin FK a otras tablas.
Campos clave (rev. 71):
- `id`, `name`, `status` (`active|inactive`)
- Identidad legal: `nit`, `email_contacto`, `telefono_contacto`
- Operación: `store_type` (`fisica|virtual|fisica_virtual`), `store_locations` (jsonb con `is_primary` rev. 71)
- Despacho: `shipping_origin` (jsonb con `dane_code`/`postal_code`)
- Marca: `mision`, `vision`, `valores`, `tono_comunicacion` (5 enums)
- Soporte: `support_schedule` (jsonb estructurado), `after_hours_message`, `escalation_role` (4 enums)
- Stock: `low_stock_threshold` (int default 5)

> Columnas legacy `business_hours`, `cutoff_message`, `dispatch_lead_time` eliminadas en rev. 71.

#### `ai_agents` (7 columnas)
- `tenant_id` FK + UNIQUE
- `name` (default `'Vendedor Oficial'`)
- `role_description` (text)
- `strict_guardrails` (bool default true)

### Conversacional

#### `conversations` (7 columnas)
- `tenant_id`, `customer_phone`, `status` (`bot_active|human_takeover|closed`)
- `last_interaction_at`, `archived_at`, `created_at`

#### `messages` (18 columnas)
- `tenant_id`, `conversation_id`
- `direction` (`inbound|outbound`), `content`, `content_type` (text/image/audio/...)
- Multimedia: `media_url`, `media_id`, `media_mime`
- Procesamiento: `processed`, `processed_at`, `processing_status`, `processing_attempts`, `payload` (jsonb)
- Meta: `meta_message_id` (idempotencia con Meta)

### Contactos

#### `contacts` (23 columnas — rev. 68/69)
- Identificación: `phone` (NOT NULL), `name`, `email`
- Documento (CO): `document_type`, `document_number`
- Dirección: `address` (jsonb estructurado con `building_type`, `tower`, `apartment`, etc.)
- Consent (Ley 1581): `consent_given`, `consent_given_at`, `consent_revoked_at`, `consent_source`, `consent_evidence` (jsonb), `consent_actor_email`
- Soft-delete: `deleted_at`

### Catálogo y stock

#### `products` (10 columnas)
- `tenant_id`, `title`, `description`, `cover_image_url`
- `status` (`active|inactive`), `external_reference_id`, `platform_category_id`

#### `product_variations` (17 columnas)
- `product_id`, `tenant_id`, `sku`, `price`, `compare_at_price`, `cost_price` (default 0)
- Stock: `stock_quantity`
- Atributos: `attributes` (jsonb)
- Logística: `weight_kg`, `length_cm`, `width_cm`, `height_cm`
- Imagen: `image_url`, `external_variation_id`

#### `stock_movements` (10 columnas — append-only)
- `tenant_id`, `variation_id`, `product_id` (nullable rev. 65)
- `delta` (signed int), `new_stock`, `reason`
- `order_id` (idempotencia anti-double-decrement)

#### `stock_reservations` (14 columnas)
- TTL para `pending_payment` orders (Wompi flow).

### Comercial

#### `orders` (10 columnas)
- `tenant_id`, `contact_id`, `conversation_id`
- `status` (`pending|pending_payment|confirmed|processing|shipped|delivered|cancelled`)
- `total_amount`, `shipping_cost`, `notes`

#### `order_items` (10 columnas)
- `order_id`, `tenant_id`, `product_id`, `variation_id`
- `title`, `unit_price`, `unit_cost`, `quantity`

#### `payments` (14 columnas — Wompi)
- `order_id`, `tenant_id`
- `provider` (default `wompi`), `wompi_link_id`, `wompi_txn_id`, `checkout_url`
- `amount_in_cents`, `currency` (default `COP`)
- `status` (`pending|approved|declined|...`), `wompi_status`, `raw_webhook` (jsonb)

#### `claims` (11 columnas)
- `tenant_id`, `order_id`, `customer_id`
- `reason`, `status` (`open|in_progress|resolved|closed|cancelled`)
- `requested_amount`, `resolution_notes`, `ticket_number`

### Logística

#### `shipments` (19 columnas)
Cotización Envia + label + tracking (Fase 2 parcial).

#### `order_tracking` (13 columnas)
Snapshots de status del carrier por orden.

#### `marketplace_listings` (17 columnas)
MeLi listings vinculados a `product_variations`. RLS custom.

### Compras y costos

#### `suppliers` (8 columnas)
- `tenant_id`, `name`, `contact_email`, `phone`, `lead_time_days`

#### `purchase_orders` (8 columnas)
- `tenant_id`, `supplier_id`, `status` (`ordered|received|cancelled`)
- `expected_date`, `total_amount`

#### `purchase_order_items` (7 columnas)
- `tenant_id`, `po_id`, `variation_id`, `quantity`, `unit_cost`

#### `expenses` (7 columnas)
Gastos operativos (CAPEX/OPEX). Reportería en módulo Finanzas.

### IA y conocimiento

#### `kb_documents` (9 columnas)
- `tenant_id`, `title`, `content`, `category` (6 canónicas: faq/negocio/politicas/productos/envios/pagos)
- `is_active`, `embedding` (`vector(3072)` pgvector)

### Integraciones

#### `tenant_integrations` (8 columnas)
- `tenant_id`, `provider`, `status` (`connected|disconnected|pending_auth`)
- `credentials` (jsonb, secrets en Vault)
- `meta` (jsonb)

#### `notification_settings` (7 columnas)
Config Telegram + email alerts.

### Auditoría y observabilidad

#### `audit_log` (9 columnas — rev. 72 cierra D4)
- `tenant_id`, `user_id`, `user_email`
- `action`, `entity_type`, `entity_id` (text)
- `payload` (jsonb)
- `created_at`

Poblada por `@audit_log` decorator (`services/api/dependencies/audit.py`)
en endpoints de mutation.

#### `bot_source_log` (20 columnas — rev. 71)
Append-only por interacción del bot. TTL 30d. Sin PII.

---

## Política de actualización

Ver `.context/05-doc-policy.md` (sección **"Las migraciones SQL NO son fuente
de verdad"** rev. 72).

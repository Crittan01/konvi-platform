# Schema Canónico — DB Live

**Fuente de verdad operacional**: la DB Supabase viva (`***SUPABASE_PROJECT_REF_REDACTED***`).
**NO** las migraciones SQL en `supabase/migrations/` — esas son **history reproducible**.

Este documento se mantiene en sincro con `tests/fixtures/db_schema_canonical.json`,
generado por `scripts/dump_schema_canonical.py` desde `information_schema`.

> **Verificado contra repo y DB live**: 2026-08-02 @ `5fdad396` — fixture regenerado,
> `python3.11 scripts/dump_schema_canonical.py --diff` → **verde (39 tablas)**.

## Cómo regenerar

```bash
python3.11 scripts/dump_schema_canonical.py            # genera fixture
python3.11 scripts/dump_schema_canonical.py --diff     # detecta drift live vs fixture
```

Ejecutar tras cualquier rev. con cambio de schema. Commitear el JSON junto al
cambio de código. Tests `tests/test_coherence_pact.py` usan este fixture como
golden file.

---

## Tablas core (39 capturadas en el fixture; 79 tablas live en total)

A continuación el shape compacto de las **39 tablas CORE** (lista `CORE_TABLES`
del script). La DB live tiene **79 tablas** (incluye infra auxiliar, billing y
retention fuera del set CORE). Para detalle completo (tipos, defaults,
nullable) ver `tests/fixtures/db_schema_canonical.json`.

### Identidad y configuración

#### `tenants` (41 columnas)
Root del aislamiento multi-tenant. Sin FK a otras tablas.
Campos clave:
- `id`, `name`, `status` (`active|inactive`)
- Identidad legal: `nit`, `email_contacto`, `telefono_contacto`, `email_habeas_data`
- Persona: `tipo_persona`, `razon_social`, `doc_tipo`, `doc_numero`, `doc_dv`, `regimen_iva`
- Domicilio: `domicilio_direccion/ciudad/departamento/pais`
- Operación: `store_type` (`fisica|virtual|fisica_virtual`), `store_locations` (jsonb con `is_primary`)
- Despacho: `shipping_origin` (jsonb con `dane_code`/`postal_code`)
- Marca: `mision`, `vision`, `valores`, `tono_comunicacion`, `business_pitch`, `product_groups`
- Soporte: `support_schedule` (jsonb estructurado), `after_hours_message`, `escalation_role`
- Stock: `low_stock_threshold` (int default 5)
- Cierre de cuenta: `deletion_requested_at`, `deletion_scheduled_for`, `deleted_at`

#### `ai_agents` (12 columnas)
- `tenant_id` FK + UNIQUE
- `name` (default `'Vendedor Oficial'`), `role_description` (text)
- `strict_guardrails` (bool default true)
- Multi-agente: `role`, `is_default`, `tools_allowed`, `fsm_states_allowed`, `fallback_for_roles`

#### `tenant_users` (9 columnas)
Membresía usuario↔tenant con `role` (`owner|manager|operator`), `status`,
`inactivated_at/reason/by`.

#### `tenant_subscriptions` (9 columnas)
Suscripción del tenant a `billing_plans`: `plan_code`, `status`, ventana `started_at/ended_at`.

### Conversacional

#### `conversations` (11 columnas)
- `tenant_id`, `customer_phone`, `contact_name`
- `status` (`bot_active|human_takeover|closed|opted_out`)
- `agentic_state` (FSM agentic, 9 estados — ver `.context/06-contracts.md` §13)
- `channel`, `last_interaction_at`, `human_takeover_at`, `archived_at`, `created_at`

#### `messages` (25 columnas)
- `tenant_id`, `conversation_id`
- `direction` (`inbound|outbound`), `content`, `content_type` (text/image/audio/...)
- Multimedia: `media_url`, `media_id`, `media_mime`
- Procesamiento: `processed`, `processed_at`, `processing_status` (`pending|processing|processed|skipped|failed|ack_pending`),
  `processing_attempts`, `skip_reason`, `last_error`, `payload` (jsonb)
- Meta: `meta_message_id` (idempotencia con Meta)
- Delivery: `delivery_status`, `delivered_at`, `read_at`, `failed_at`, `delivery_error`,
  `pricing_category`, `pricing_billable`

#### `conversation_carts` (22 columnas)
Cart-as-SoT por conversación: `status`, `version`, `subtotal_cents`, `shipping_cents`,
`total_cents`, `currency`, `shipping_meta`, `converted_order_id`, `requires_requote`,
`payment_method`, cupón (`coupon_id`, `coupon_code`, `discount_cents`),
`abandoned_reminder_sent_at`, `expires_at`.

#### `conversation_cart_items` (10 columnas)
Ítems del cart: `cart_id`, `product_id`, `variation_id`, `quantity`, `unit_price_cents`.

#### `conversation_notes` (9 columnas)
Notas internas del operador por conversación (`is_pinned`, soft-delete `deleted_at`).

#### `conversation_reads` (4 columnas)
Marcas de lectura por usuario: `(tenant_id, user_id, conversation_id, last_read_at)`.

#### `agentic_shadow_log` (21 columnas)
Log de shadow/observabilidad del loop agentic: `inbound_text`, `agentic_outbound`,
`tool_calls_executed`, `tool_call_log`, `invariant_outcome/name`, `elapsed_seconds`,
`total_tokens`, `mode`, `finish_reason`, `truncated`.

### Contactos

#### `contacts` (29 columnas)
- Identificación: `phone` (NOT NULL), `name`, `email`, `shipping_phone`
- Documento (CO): `document_type`, `document_number`, `document_number_hash`, `document_number_last4`
- Dirección: `address` (jsonb estructurado con `building_type`, `tower`, `apartment`, etc.)
- Consent transaccional (Ley 1581): `consent_given`, `consent_given_at`, `consent_channel`,
  `consent_text_version`, `consent_notice_version`, `consent_source`, `consent_evidence` (jsonb),
  `consent_actor_email`, `consent_revoked_at`, `consent_revoked_reason`
- Consent comercial (Ley 2300): `consent_comercial_at`, `consent_comercial_revoked_at`, `consent_comercial_fuente`
- Soft-delete: `deleted_at`

### Catálogo y stock

#### `products` (15 columnas)
- `tenant_id`, `title`, `description`, `cover_image_url`
- `status` (`active|inactive`), `external_reference_id`, `platform_category_id`
- `category_id` (→ `product_categories`), `attributes` (jsonb)
- Retracto: `retracto_excluded`, `retracto_excluded_reason`, `safety_note`

#### `product_categories` (8 columnas)
Categorías del tenant: `name`, `display_label`, `sort_order`, `parent_id`, `platform_category_id`.

#### `product_attribute_definitions` (13 columnas)
Atributos por categoría: `code`, `label`, `type`, `unit`, `is_required`,
`is_variant_axis`, `allowed_values`, `localizable`, `sort_order`.

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

#### `orders` (22 columnas)
- `tenant_id`, `contact_id`, `conversation_id`
- `status` (`pending|pending_payment|confirmed|processing|shipped|delivered|cancelled`)
- `total_amount`, `shipping_cost`, `discount_amount`, `payment_method`, `notes`
- `source`, `external_order_id`
- Cancelación: `cancelled_at`, `cancelled_by_actor`, `cancellation_id`
- Aceptación (evidencia contractual G-8): `accepted_at`, `accepted_message_id`,
  `accepted_meta_message_id`, `accepted_source`

#### `order_items` (10 columnas)
- `order_id`, `tenant_id`, `product_id`, `variation_id`
- `title`, `unit_price`, `unit_cost`, `quantity`

#### `payments` (14 columnas — Wompi)
- `order_id`, `tenant_id`
- `provider` (default `wompi`), `wompi_link_id`, `wompi_txn_id`, `checkout_url`
- `amount_in_cents`, `currency` (default `COP`)
- `status` (`pending|approved|declined|...`), `wompi_status`, `raw_webhook` (jsonb)

#### `claims` (13 columnas)
- `tenant_id`, `order_id`, `customer_id`
- `reason`, `status` (`open|investigating|resolved|refunded|rejected|cancelled` —
  CHECK `claims_status_check`, migración `20260624010000`)
- `requested_amount`, `resolution_notes`, `ticket_number`
- Reembolso: `refunded_amount`, `refunded_at`

#### `coupons` (16 columnas)
Cupones del tenant: `code`, `discount_type` (`percent|fixed_amount|free_shipping`),
`discount_value`, `min_subtotal_cents`, `max_redemptions`, `redemptions_count`,
ventana `valid_from/valid_until`, `is_active`, `is_customer_visible`.

#### `coupon_redemptions` (12 columnas)
Redenciones: `coupon_id`, `cart_id`, `contact_id`, `order_id`,
`discount_applied_cents`, `status`, `applied_at/consumed_at/revoked_at`.

#### `order_receipts` (16 columnas — ADR-0040)
Comprobante de compra: `numero_seq`, `numero`, `snapshot` (jsonb inmutable),
`content_hash`, `issued_at`, anulación (`voided_at`, `void_reason`),
acuse WhatsApp (`ack_sent_at`, `ack_channel`) y email (`email_sent_at`, `email_to`).

#### `rma_requests` (33 columnas)
Retracto/devolución (Ley 1480): `status`, `retracto_deadline`, `reason_code`,
`refund_amount_cents`, `refund_legal_deadline`, logística de devolución
(`return_label_url`, `return_carrier`, `return_tracking`), inspección, notificaciones.

#### `payment_reversal_requests` (31 columnas)
Reversión del pago (Ley 1480 art. 51, G-7): `radicado`, `causal`, `valor`,
`es_parcial`, `instrumento`, `presentada_at`, `canal`, constancia art. 2.2.2.51.4
(`constancia`, `constancia_hash`, `constancia_emitida_at`), `doble_pago_detectado_at`, `estado`.

### Logística

#### `shipments` (18 columnas)
Cotización y envío **Aveonline** (único provider; Envia eliminado rev. 109):
`carrier`, `service`, `origin_address`/`destination_address` (jsonb), `parcels`,
`quote_response`, `selected_rate`, `label_url`, `tracking_number`, `tracking_url`,
`estimated_delivery`, guard monotónico `status_occurred_at`.

#### `order_tracking` (13 columnas)
Snapshots de status del carrier por orden.

#### `marketplace_listings` (17 columnas)
MeLi listings vinculados a `product_variations`. RLS custom.

### Compras y costos

#### `suppliers` (9 columnas)
- `tenant_id`, `name`, `contact_email`, `phone`, `lead_time_days`, `is_active`

#### `purchase_orders` (9 columnas)
- `tenant_id`, `supplier_id`, `status` (`ordered|received|cancelled`)
- `po_number`, `expected_date`, `total_amount`

#### `purchase_order_items` (7 columnas)
- `tenant_id`, `po_id`, `variation_id`, `quantity`, `unit_cost`

#### `expenses` (10 columnas)
Gastos operativos (CAPEX/OPEX). Reportería en módulo Finanzas.
Reversión: `reversed_at`, `reversed_by`, `reversal_reason`.

### IA y conocimiento

#### `kb_documents` (10 columnas)
- `tenant_id`, `title`, `content`, `category` (6 canónicas: faq/negocio/politicas/productos/envios/pagos)
- `is_active`, `embedding` (`vector(3072)` pgvector), `embedding_model_version`

### Integraciones

#### `tenant_integrations` (11 columnas)
- `tenant_id`, `provider`, `status` (`connected|disconnected|pending_auth`)
- `credentials` (jsonb, secrets en Vault), `meta` (jsonb)
- Refresh tokens: `refresh_lease_until`, `refresh_lease_token`, `refresh_fail_count`

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

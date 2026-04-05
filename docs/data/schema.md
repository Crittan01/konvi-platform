# Data Schema

## Tablas principales previstas
- tenants
- tenant_domains
- tenant_members
- roles
- permissions
- role_permissions
- profiles
- products
- product_variants
- product_images
- warehouses
- inventory_snapshots
- inventory_movements
- channels
- channel_accounts
- product_channel_mappings
- contacts
- conversations
- messages
- orders
- order_items
- shipments
- shipping_quotes
- knowledge_documents
- knowledge_chunks
- embeddings
- automation_rules
- handoff_tickets
- audit_logs
- sync_runs
- sync_errors

## Tablas adicionales importantes
- platform_users_view (si se requiere una vista administrativa)
- tenant_status_history
- billing_status_events
- feature_flags
- tenant_feature_flags
- support_access_logs

## Regla
Toda tabla sensible debe evaluar si requiere tenant_id y RLS.

## Nota sobre administración de plataforma
El sistema debe distinguir entre datos del tenant y metadatos de plataforma.
Las operaciones de suspensión, reactivación, facturación y soporte deben modelarse explícitamente.
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

## Regla
Toda tabla sensible debe evaluar si requiere tenant_id y RLS.
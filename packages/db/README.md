# Database Package

Este módulo contiene las migraciones SQL del schema de Supabase.

## Fuente de verdad canónica

**`supabase/migrations/`** es la fuente canónica. Los archivos en `packages/db/migrations/` son copias de referencia sincronizadas. Para aplicar migraciones usar siempre:

```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

## Archivos en migrations/

| Archivo | Notas |
|---------|-------|
| `00001` – `00005` | Mirrors legacy (renombrados). Mismo contenido que los `2026040618123x_*.sql`. |
| `20260406181235_initial_schema.sql` | Tenants, tenant_users |
| `20260406181236_catalog_schema.sql` | Products, product_variations |
| `20260406181237_conversational_schema.sql` | Conversations, messages |
| `20260406181238_rls_policies.sql` | Políticas RLS por tenant |
| `20260406181239_custom_claims_trigger.sql` | Trigger handle_new_user_claims |
| `20260407200700_messages_processed_flag.sql` | Flag processed en messages |
| `20260409220000_fase9_schema_core.sql` | Contacts, orders, order_items, tenant_integrations, notification_settings |
| `20260409230000_shipments.sql` | Tabla shipments |
| `20260409240000_stock_movements.sql` | Tabla stock_movements |
| `20260409250000_kb_documents.sql` | Tabla kb_documents |
| `20260409260000_audit_log.sql` | Tabla audit_log |
| `20260409270000_tenant_shipping_origin.sql` | Campo shipping_origin en tenants |
| `20260410010000_tenant_low_stock_threshold.sql` | Campo low_stock_threshold en tenants |
| `20260410020000_contacts_consent.sql` | Campos consent_given/consent_date en contacts |

Total: 14 migraciones canónicas aplicadas en producción (Supabase linked project).

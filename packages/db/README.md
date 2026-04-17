# @commerce/db — Migraciones SQL (Copia parcial)

Última actualización: 2026-04-16

## ⚠️ Advertencia crítica

**`supabase/migrations/` es la fuente canónica.** Los archivos en `packages/db/migrations/`
son una copia parcial que **NO está sincronizada** con la fuente real.

`packages/db/migrations/` contiene las primeras 15 migraciones (hasta `20260410020000`).
Las siguientes 10 migraciones (desde `20260411162042` en adelante) solo existen en `supabase/migrations/`.

**Para aplicar migraciones, usar siempre:**
```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

---

## Estado de sincronización

| Fuente | Archivos |
|--------|---------|
| `supabase/migrations/` ← **CANÓNICA** | 25 archivos |
| `packages/db/migrations/` ← Copia parcial | 15 archivos (desincronizado desde 20260411) |

---

## Archivos en packages/db/migrations/ (15)

| Archivo | Estado |
|---------|--------|
| `00001` – `00005` | Legacy renaming mirrors (mismo contenido que los `2026040618123x_*.sql`) |
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

## Migraciones solo en supabase/migrations/ (10 — no copiadas aquí)

| Archivo | Descripción |
|---------|-------------|
| `20260411162042_fase11_3_catalog_enterprise.sql` | Campos enterprise para catálogo |
| `20260412000000_ai_agents_and_vectors.sql` | Tablas ai_agents + pgvector |
| `20260413000000_purchases_and_finance.sql` | purchase_orders, suppliers, finance_entries |
| `20260413000001_finance_polish.sql` | Ajustes finanzas |
| `20260413000002_marketplace_listings.sql` | marketplace_listings |
| `20260413150000_claims.sql` | Tabla claims |
| `20260415000000_security_tenant_users_rls.sql` | RLS tenant_users + add_member_to_tenant |
| `20260415010000_get_tenant_team_confirmed.sql` | Función get_tenant_team con status confirmado |
| `20260415020000_tenant_identity_fields.sql` | nit, email_contacto, telefono_contacto en tenants |
| `20260415030000_rename_agent_to_operator.sql` | Renombra agent→operator en tenant_users |
| `20260416000000_fix_claims_rls.sql` | Fix RLS policies en claims |

---

## Propósito futuro de este paquete

`packages/db` podría eventualmente contener:
- Types TypeScript generados desde el schema (via `supabase gen types`)
- Helpers de query compartidos entre el frontend y servicios
- Seed data para testing local

Por ahora, el único artefacto real aquí son los mirrors parciales de migraciones.
**No usar este directorio como referencia de schema — usar `supabase/migrations/`.**

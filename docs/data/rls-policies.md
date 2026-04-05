# RLS Policies

## Objetivo
Definir el aislamiento por tenant y rol.

## Principios
- acceso solo a filas del tenant permitido
- uso de claims/JWT para validar membresía y rol
- service role solo en backend confiable
- jamás usar service role en frontend

## Tablas a proteger prioritariamente
- products
- product_variants
- inventory_snapshots
- inventory_movements
- contacts
- conversations
- messages
- orders
- order_items
- knowledge_documents
- knowledge_chunks
- sync_runs
- sync_errors
- audit_logs
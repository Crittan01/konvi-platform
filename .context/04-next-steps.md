# Próximos Pasos — Estado 2026-04-20

## Pendientes reales

1. **Envia Fase 2**
   - Label generation
   - Tracking (escribir en `order_tracking` con `provider='envia'`)
   - Pickup scheduling
   - Reemplazar catálogo DANE estático del frontend por source dinámico desde Envia Queries (`/state`, `/city`) para no depender de snapshot local.
   - Agregar observabilidad específica a validación previa de direcciones (Geocodes/Queries) con alertas de falla por carrier/tenant.

2. **Mercado Libre — pendientes menores**
   - Exponer tracking de `order_tracking` en detalle de pedido (UI Pedidos)
   - Paginación completa en `GET /marketplace/listings` (actualmente máx 100)

3. **Operación/Infra**
   - SMTP propio en Supabase (cuando exista dominio propio)
   - Monitoreo operativo (alertas centralizadas por fallos de integración)

## Migraciones pendientes de aplicar en Supabase

- `20260420000000_marketplace_listings_meli_fields.sql`
- `20260420000001_order_tracking.sql`

```bash
supabase db query --linked -f supabase/migrations/20260420000000_marketplace_listings_meli_fields.sql
supabase db query --linked -f supabase/migrations/20260420000001_order_tracking.sql
```

## No pendientes (cerrado en sesión 2026-04-20)

- Sync pull MeLi → Supabase (title/thumbnail/condition/category/attributes/synced_at)
- Shipment tracking persistido en `order_tracking` (multi-proveedor)
- Buyer contact creation desde órdenes MeLi (con teléfono si disponible)
- `get_shipment()` en meli_client + `ITEM_ATTRIBUTES` ampliados
- UX Mercado Libre: filtros por estado (Todos/Activos/Pausados/Cerrados/Sin vincular)
- Badge de condición (Nuevo/Usado) en tabla de publicaciones
- Shipping CO endurecido: validación oficial Envia (Geocodes + Queries fallback, best-effort) previa a quote
- Normalización DANE canónica (5 dígitos) en backend + fix del bug frontend `dane_code + "000"`
- Sidebar con activación por integración para Inbox/Cotizador/Mercado Libre

## No pendientes (cerrado en sesión 2026-04-19)

- Contrato único de estados de conversación end-to-end
- Human takeover efectivo (bot silenciado en runtime)
- RBAC runtime unificado (`owner/manager/operator`)
- OAuth MeLi con state firmado + expiración + anti-replay
- Endpoint MeLi `/auth-url` con error explícito cuando faltan env vars requeridas
- Credenciales WhatsApp por tenant como única fuente runtime
- Frontend residual: badge MeLi real + inventory legacy redirigido
- Inbox ordenado por `last_interaction_at` + estado de error al fallar carga de conversaciones
- Contrato explícito de procesamiento de mensajes (`processing_status`)

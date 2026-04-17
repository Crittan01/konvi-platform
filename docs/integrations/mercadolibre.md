# Integración Mercado Libre

Última actualización: 2026-04-16 (rev. 2 — actualizado a estado real post Fase 11.5)

---

## Estado

✅ **Live — Fase Avanzada** (implementado en Fases 10–11.5)

> ⚠️ Nota arquitectónica: el código de MeLi NO vive en `services/connector-mercadolibre/` (ese directorio está vacío).
> La integración está implementada directamente en `services/api/`:
> - `services/api/routers/marketplace.py` — endpoints REST
> - `services/api/routers/meli_webhook.py` — IPN webhook
> - `services/api/routers/integrations.py` — OAuth flow
> - `services/api/integrations/meli_client.py` — cliente HTTP MeLi API

---

## Capacidades implementadas

| Capacidad | Estado | Implementación |
|-----------|--------|----------------|
| OAuth 2.0 por tenant (connect/disconnect) | ✅ Live | `integrations.py` → `/meli/auth-url` + `/meli/callback` |
| Listar publicaciones reales de MeLi | ✅ Live | `GET /marketplace/listings` → MeLi API real (user items + multiget) |
| Vincular publicación MeLi ↔ variante Supabase | ✅ Live | `POST /marketplace/link` |
| Desvincular publicación | ✅ Live | `DELETE /marketplace/link/{id}` |
| Importar publicación MeLi → catálogo Supabase | ✅ Live | `POST /marketplace/import` — crea product + variation + listing |
| Pausar / activar publicación en MeLi | ✅ Live | `PATCH /marketplace/{id}/status` |
| Stock sync Supabase → MeLi (automático) | ✅ Live | `sync_meli_stock()` — llamado desde `orders.py` y `products.py` |
| Stock sync manual Supabase → MeLi | ✅ Live | `PATCH /marketplace/{id}/sync-stock` |
| IPN Webhook `orders_v2` (pedidos) | ✅ Live | `meli_webhook.py` → crea/actualiza `orders` en Supabase |
| IPN Webhook `items` (status de publicación) | ✅ Live | `meli_webhook.py` → actualiza `marketplace_listings.status` |
| Auto-refresh de access_token | ✅ Live | `_get_valid_token()` en webhook — usa refresh_token automáticamente |
| UI de gestión de publicaciones | ✅ Live | `/dashboard/marketplace` + `MarketplaceManager` component |

## Capacidades pendientes (genuinamente)

| Capacidad | Estado | Notas |
|-----------|--------|-------|
| Sync catálogo completo MeLi→Supabase (precios, descripciones automático) | ❌ Pendiente | Import manual disponible; sync batch/automático no implementado |
| Tracking de envíos desde MeLi | ❌ Pendiente | Handler en webhook dice "Fase 12" |
| Validación HMAC de webhooks MeLi | ❌ No implementado | MeLi IPN no firma los requests — verificación de origen por user_id |

---

## Modelo de autenticación

- **Protocolo**: OAuth 2.0 con refresh token (válido 180 días)
- **Modelo**: **Por tenant** — cada tenant conecta su propia cuenta de Mercado Libre
- **App credentials** (`MELI_CLIENT_ID`, `MELI_CLIENT_SECRET`): globales de plataforma — env vars en Render
- **Tokens por tenant**: almacenados en `tenant_integrations.credentials` → `{ access_token, refresh_token, user_id, expires_in }`
- **Refresh automático**: implementado en `_get_valid_token()` dentro de `meli_webhook.py`

---

## Modelo de datos

```
MeLi Publicación → marketplace_listings (external_id, variation_id, status, external_price, external_url)
MeLi Orden       → orders (status, total_amount, notes con meli_order_id) + order_items
MeLi Variante    → vinculada a product_variations vía marketplace_listings.variation_id
```

Migración: `supabase/migrations/20260413000002_marketplace_listings.sql`

---

## Flujo de stock bidireccional

```
Supabase → MeLi (automático):
  - orders.py: al confirmar pedido → _decrement_stock_on_confirm() → sync_meli_stock()
  - products.py: al ajustar variante con nuevo stock_quantity → sync_meli_stock()
  - marketplace.py: PATCH /{id}/sync-stock → fuerza sync manual

MeLi → Supabase (via IPN webhook):
  - topic=orders_v2 → _process_order() → INSERT/UPDATE orders + order_items
  - topic=items → UPDATE marketplace_listings.status
```

---

## Arquitectura de servicios

**El MeLi integration NO es un servicio separado.** Vive dentro de `services/api/` como módulos:

```
services/api/
├── routers/
│   ├── marketplace.py      ← CRUD listings, link, import, sync-stock
│   ├── meli_webhook.py     ← IPN endpoint /webhook
│   └── integrations.py     ← OAuth flow /meli/auth-url + /meli/callback
└── integrations/
    └── meli_client.py      ← cliente HTTP: oauth, items API, update stock/status
```

`services/connector-mercadolibre/` existe pero está **vacío** — es un placeholder para una eventual extracción como servicio independiente. No tiene implementación y no está en `render.yaml`.

---

## Variables de entorno

```bash
MELI_CLIENT_ID=...        # ID de la app MeLi (global de plataforma)
MELI_CLIENT_SECRET=...    # Secret de la app
MELI_REDIRECT_URI=...     # https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback
MELI_AUTH_URL=...         # https://auth.mercadolibre.com.co/authorization (Colombia)
```

Tokens de acceso por tenant se almacenan en DB, no en env vars.

---

## Reglas de implementación

1. Nunca exponer tokens MeLi al frontend
2. El LLM nunca consulta directamente a MeLi
3. Toda operación incluye `tenant_id` y valida pertenencia
4. `sync_meli_stock()` falla silenciosa — un error en MeLi no rompe la operación principal de Supabase
5. El webhook MeLi siempre responde 200 inmediatamente (BackgroundTask)
6. Verificar documentación oficial antes de cambios en API: https://developers.mercadolibre.com.ar/

---

## Documentos relacionados

- `docs/integrations/whatsapp.md` — canal conversacional
- `docs/risks/open-questions.md` — OQ-03 (modelo OAuth por tenant vs intermediario)
- `supabase/migrations/20260413000002_marketplace_listings.sql` — schema

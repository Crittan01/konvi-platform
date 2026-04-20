# Integración Mercado Libre (estado real)

Última actualización: 2026-04-19

---

## Implementación real

La integración vive en `services/api`:

- `routers/integrations.py` -> OAuth connect/disconnect
- `routers/marketplace.py` -> list/link/import/sync/estado
- `routers/meli_webhook.py` -> IPN webhook
- `integrations/meli_client.py` -> cliente HTTP + OAuth helpers

`services/connector-mercadolibre/` no es servicio activo.

---

## OAuth endurecido

`/api/v1/integrations/meli/auth-url` genera `state` seguro con:

- firma HMAC (`MELI_OAUTH_STATE_SECRET`)
- expiración (`MELI_OAUTH_STATE_TTL_SECONDS`, default 600s)
- nonce one-time persistido en `integration_oauth_states`

`/api/v1/integrations/meli/callback`:

- rechaza `state` faltante
- rechaza `state` manipulado
- rechaza `state` expirado
- rechaza replay (nonce reutilizado)
- solo persiste tokens cuando el `state` valida y se consume

---

## Modelo de credenciales

### Plataforma (env vars)
- `MELI_CLIENT_ID`
- `MELI_CLIENT_SECRET`
- `MELI_REDIRECT_URI`
- `MELI_AUTH_URL`
- `MELI_OAUTH_STATE_SECRET`
- `MELI_OAUTH_STATE_TTL_SECONDS`

### Tenant (DB)
`tenant_integrations` (`provider='mercadolibre'`):
- `credentials.access_token`
- `credentials.refresh_token`
- `credentials.expires_at`
- `meta.user_id`

Refresh token se maneja en backend, nunca en frontend.

---

## Capacidades live

- OAuth por tenant
- Listado real de publicaciones MeLi
- Link/unlink publicación <-> variación interna
- Import publicación a catálogo interno
- Cambio de estado (`active|paused` desde UI)
- Sync de stock (manual y por eventos internos)
- Webhook `orders_v2` e `items`

---

## Reglas de seguridad multi-tenant

- operaciones con `service_role` deben filtrar explícitamente por `tenant_id`
- no exponer tokens al frontend
- no persistir tokens cuando falla validación de OAuth `state`

---

## Referencias

- `services/api/integrations/meli_client.py`
- `services/api/routers/integrations.py`
- `services/api/routers/marketplace.py`
- `services/api/routers/meli_webhook.py`
- `supabase/migrations/20260419000002_meli_oauth_state_store.sql`

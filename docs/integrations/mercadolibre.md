# Mercado Libre — Marketplace (documento canónico)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

## Estado

**LIVE** — OAuth por tenant, webhook IPN endurecido y sincronización de stock bidireccional en producción. Significa: un tenant owner puede conectar su cuenta MeLi desde Integraciones, importar publicaciones a su catálogo, y el stock se mantiene coherente en ambos sentidos (venta WhatsApp → MeLi, venta MeLi → catálogo Konvi).

`services/connector-mercadolibre/` es un **placeholder vacío** (M20) — la integración vive íntegra en `services/api`.

## Dónde vive el código

| Pieza | Archivo | Líneas |
|---|---|---|
| Cliente HTTP + OAuth + tokens | `services/api/integrations/meli_client.py` | 794 |
| OAuth connect/callback/disconnect | `services/api/routers/integrations.py` (`/meli/*`) | — |
| Listings: list/link/import/sync/estado | `services/api/routers/marketplace.py` | 999 |
| Webhook IPN | `services/api/routers/meli_webhook.py` | 926 |
| Wrapper canal (capabilities) | `services/api/lib/commerce/meli.py` | — |
| ADRs | `docs/adr/0036-bloque-d-mercadolibre-stock-coherence.md`, `0037-meli-reliability-and-full-enablement-roadmap.md`, `0038-bloque-f-postventa-wiring.md` | — |
| Dossier (histórico) | `docs/_archive/research/mercadolibre-dossier-2026-05-05.md` | — |

## Flujos implementados

### 1. OAuth por tenant (state endurecido)

1. `GET /api/v1/integrations/meli/auth-url` [owner] (`integrations.py:206-208`) → `issue_oauth_state` (`meli_client.py:116-129`): payload firmado con **HMAC** (`MELI_OAUTH_STATE_SECRET`, `:96`) + **nonce one-time** persistido en `integration_oauth_states` (`:105-113`) + expiración `MELI_OAUTH_STATE_TTL_SECONDS` (**600 s**, `render.yaml:264-265`).
2. `GET /api/v1/integrations/meli/callback` (`integrations.py:224-249`): sin JWT — el `state` ES la autoridad. `validate_and_consume_oauth_state` (`meli_client.py:133`) rechaza state faltante, manipulado, expirado o con nonce ya consumido (replay) → redirect con `?error=invalid_state`. Solo con state válido y consumido se intercambia `code` por tokens (`exchange_code:256`).
3. Tokens a **Vault** (`access_token_secret_id`/`refresh_token_secret_id` en `tenant_integrations.credentials`, `:335-338,430-434`); `meta.user_id` guarda el seller id. Refresh: `get_valid_token` (`:315-319`) refresca **lazy** cuando `expires_at < now + 1h` y persiste el token rotado ANTES de usarlo (write-before-consume, `:430-434`). Access token MeLi: 6 h (`expires_in=21600`).
4. `DELETE /api/v1/integrations/meli` [owner] (`integrations.py:345`): revoca el token en MeLi (`revoke_token:233`) y desconecta.

### 2. Catálogo y stock (panel marketplace)

Endpoints en `services/api/routers/marketplace.py` (mount `/api/v1`, `main.py:282`):

- `GET /listings` (`:290`) — listado real de publicaciones MeLi.
- `POST /link` (`:428`) / `DELETE /link/{listing_id}` (`:523`) — vincular/desvincular publicación MeLi ↔ variación interna.
- `POST /import` (`:889`) / `POST /import-bulk` (`:930`) — importar publicación al catálogo interno.
- `PATCH /{listing_id}/status` (`:550`) — `active|paused` desde la UI.
- `PATCH /{listing_id}/sync-stock` (`:606`) — empujar stock interno → MeLi manual.
- `sync_meli_stock(variation_id, new_qty)` (`:190`) — núcleo async de sync; `lib/commerce/meli.py:104-112` mapea `sync_stock` → `update_item_quantity` (`meli_client.py:664-668`, `PUT /items/{id}` `available_quantity`).

### 3. Sync bidireccional automático

- **Venta WhatsApp → MeLi**: al confirmar/cancelar una orden, `_fire_meli_sync_for_order` (`orders.py:750-817`) recalcula el stock de cada variación linkeada y dispara `sync_meli_stock` — evita oversell cross-canal. También en edición de stock desde catálogo (`products.py:603`).
- **Venta MeLi → Konvi**: el webhook `orders_v2` deriva la venta y rebaja stock interno; un `orders_v2` tardío NO pisa estados terminales del fulfillment (`meli_webhook.py:248`).

### 4. Webhook IPN

Receptor: `POST /api/v1/meli/webhook` (`meli_webhook.py:891`; mount `/api/v1/meli`, `main.py:286`). Tópicos: **orders_v2, items, shipments** (`:4`).

1. **IP allowlist** (dependencia `_verify_meli_origin:216`): solo las 4 IPs oficiales de notificaciones MeLi (`:80-86`, verificadas 2026-04-28 contra https://developers.mercadolibre.com.co/es_ar/notificaciones); override por `MELI_WEBHOOK_ALLOWED_IPS` (CSV) si MeLi publica IPs nuevas (`:88-95`). IP real del cliente vía `cf-connecting-ip` (`:204-213` — ver gap A2).
2. **Alerta proactiva**: N rechazos de origen en ventana → log warning estructurado (`_check_meli_origin_alert:168`; umbrales `MELI_WEBHOOK_ALERT_THRESHOLD=5` / `MELI_WEBHOOK_ALERT_WINDOW_SECONDS=300`).
3. **Dedup cross-instancia**: RPC en DB (`application_id|resource|sent`, TTL 300 s) con fallback a dedup in-memory por instancia (`:101-159`) — sobrevive a 2+ réplicas en Render.
4. **Anti-SSRF**: MeLi no firma el body; el `resource` se valida contra patrones por tópico antes de hacer `GET {MELI_API_URL}{resource}` con el token del seller (`:282-304`).
5. Fetch del recurso con `get_valid_token` del tenant y aplicación del efecto (orden, ítem, envío).

## Config por tenant vs global

### Por tenant — `tenant_integrations` (`provider='mercadolibre'`)

```json
"credentials": { "access_token_secret_id": "…", "refresh_token_secret_id": "…", "expires_at": "…" },
"meta": { "user_id": 123456789 }
```

Tokens en Vault; refresh automático server-side; nunca expuestos al frontend.

### Globales (env vars — app de plataforma MeLi)

| Var | Valor | Qué controla |
|---|---|---|
| `MELI_CLIENT_ID` / `MELI_CLIENT_SECRET` | `sync:false` | App de plataforma en MeLi Developers |
| `MELI_REDIRECT_URI` | `https://konvi-api.onrender.com/api/v1/integrations/meli/callback` | Callback OAuth |
| `MELI_AUTH_URL` | `https://auth.mercadolibre.com.co/authorization` | Por país (CO/MX/AR, `render.yaml:252-256`) |
| `MELI_OAUTH_STATE_SECRET` | `sync:false` | Firma HMAC del state |
| `MELI_OAUTH_STATE_TTL_SECONDS` | `600` | Expiración del state |
| `MELI_WEBHOOK_ALLOWED_IPS` | vacío (usa default) | Override de la allowlist |
| `MELI_WEBHOOK_ALERT_THRESHOLD` / `_WINDOW_SECONDS` | `5` / `300` | Alerta de rechazos de origen |

`meli_client.is_configured()` / `missing_required_config()` (`:294-299`) — `auth-url` responde 503 detallando qué falta si la config de plataforma está incompleta.

## Seguridad

- **OAuth state**: HMAC + expiración + nonce one-time (replay rechazado); tokens solo se persisten tras consumir el state.
- **Webhook**: IP allowlist + alerta + dedup distribuido + anti-SSRF de `resource` (MeLi no ofrece firma de payloads — la allowlist ES la barrera documentada por el proveedor).
- **Vault** para access/refresh tokens con rotación write-before-consume.
- Operaciones `service_role` siempre con filtro explícito `tenant_id`.

## Modo de fallo

| Fallo | Comportamiento |
|---|---|
| Access token expirado | Refresh lazy automático (`get_valid_token`); si el refresh falla, la operación se marca fallida visible (no silenciosa) |
| Refresh token expirado (>6 meses sin uso, límite MeLi) | Integración queda inoperante hasta que el owner reconecta (M17) — no hay cron de keep-alive |
| Webhook duplicado (MeLi reintenta hasta 8 veces en 1 h sin 200) | Dedup RPC cross-instancia → no-op |
| IP de origen no reconocida | Rechazo + contador de alerta; si MeLi cambió IPs, override por env sin redeploy de código (sí de env) |
| Push de stock a MeLi falla | Log + estado de sync consultable en UI; el stock interno es la fuente de verdad y se re-empuja con `sync-stock` manual |
| Dedup RPC cae | Fallback a dedup local in-memory (degradado pero funcional por instancia) |

## Operación

- **Manual de plataforma (IH-007)**: registrar la app en MeLi Developers, configurar `MELI_CLIENT_ID/SECRET/REDIRECT_URI/AUTH_URL` en Render, suscribir los tópicos `orders_v2`, `items`, `shipments` apuntando a `https://konvi-api.onrender.com/api/v1/meli/webhook`.
- **Manual por tenant**: owner → Integraciones → Conectar Mercado Libre (OAuth self-serve).
- **Revisión trimestral de IPs de notificación** contra docs oficiales — **VENCIDA 2026-07-28 (A3)**: ejecutar y actualizar `_MELI_DEFAULT_NOTIFICATION_IPS` si cambiaron.
- **Monitoreo disponible**: logs estructurados (`meli_webhook.alert_threshold_exceeded`, dedup_rpc_failed), 503 explícito si falta config.

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| A3 | Alto | Revisión trimestral de IPs MeLi vencida (2026-07-28) — allowlist potencialmente stale |
| A2 | Alto | `cf-connecting-ip` sin verificación empírica (T4-01): si Render/CF no sobrescribe el header, la allowlist y el rate-limit son spoofeables |
| M17 | Medio | Refresh lazy: un tenant >6 meses sin actividad pierde el refresh token y debe reconectar |
| B5 | Alto | Cobertura `meli_webhook.py` 37.7% — path de dinero sub-testeado |
| M13 | Medio | ADR 0023 duplicado (meta-model-b vs shipping-provider-pattern) — ruido documental al citar |
| M20 | Medio | `services/connector-mercadolibre/` placeholder vacío (documentado, no confundir con la integración real) |

## Referencias oficiales

- Notificaciones MeLi (IPs oficiales, tópicos): https://developers.mercadolibre.com.co/es_ar/notificaciones — verificada 2026-04-28.
- OAuth MeLi (`offline_access`, `expires_in=21600`): docs MeLi Developers, reflejada en `meli_client.py:11-19`.

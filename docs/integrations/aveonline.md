# Aveonline — Shipping (documento canónico)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

## Estado

**PARCIAL** — cotización live, guías en DRY-RUN global. Significa exactamente:

- **Cotización**: LIVE. El bot y el operador cotizan envíos reales multi-carrier contra Aveonline (precios reales del tenant).
- **Generación de guías**: DRY-RUN por flag global `AVEONLINE_GENERATE_REAL_GUIDES=false` (`render.yaml:226-227` api, `348-350` orchestrator). Toda guía se genera con `bloquegenerarguia="0"` → **no factura ni despacha nada** (B1). El flip requiere además `tenant_shipping_provider_config.real_guides_enabled=true` por tenant (doble compuerta, `wompi_webhook.py:1996-1998`).
- **Webhook de estados**: implementado y activo (secret + dedup + avance monotónico + notificaciones).
- **Tracking de respaldo (polling)**: implementado — job `_aveonline_status_poll` del worker (intervalo 1 h, guías reales >6 h sin update vía webhook, batch 25; knobs en `render.yaml:503-509`).

Aveonline es el **único provider de shipping** del runtime (ADR-0019).

## Dónde vive el código

| Pieza | Archivo | Líneas |
|---|---|---|
| Cliente (auth, cotizar, guía, estado) | `services/api/integrations/aveonline_client.py` | 1176 |
| **Espejo idéntico** en orchestrator (deuda M16, `diff` = idénticos) | `services/ai-orchestrator/integrations/aveonline_client.py` | 1176 |
| Webhook de estados | `services/api/routers/aveonline_webhook.py` | — |
| Endpoint de cotización operador | `services/api/routers/shipping.py` (`POST /api/v1/shipping/quote`) | — |
| Tool de cotización del bot | `services/ai-orchestrator/tools/shipping_quote_tool.py` | — |
| Generación de guía post-pago | `services/api/routers/wompi_webhook.py` (`_generate_shipping_guide:1757`) | — |
| Endpoints de gestión (owner) | `services/api/routers/integrations.py` (`/aveonline/*`) | — |
| Gestor de secrets de webhook (bcrypt) | `services/api/lib/webhook_secret_manager.py` | — |
| Dossier de investigación (docs oficiales) | `docs/research/aveonline-dossier.md` | 2015 |
| ADR | `docs/adr/0019-aveonline-as-primary-shipping-provider.md` | — |

## Flujos implementados

### 1. Autenticación (JWT per-tenant con refresh)

1. Credenciales `usuario`/`password` por tenant en Vault; se resuelven vía RPC `get_aveonline_credentials` (migración `20260527020000`, `aveonline_client.py:214-236`).
2. Login contra `auth.aveonline.co/api/comunes/v1.0/autenticarusuario.php` → JWT cacheado en `tenant_integrations.credentials.jwt_token` (`aveonline_client.py:7-8`).
3. Refresh automático con buffer de 10 min (`JWT_REFRESH_BUFFER_SECONDS = 600`, `:68,239-251`); el TTL cacheado se capa a ≤3600 s aunque Aveonline devuelva `tiempoToken` mayor (`:304-309`). Ante `-2 credenciales`, refresh + 1 retry (`:25`).

### 2. Cotización (bot y operador)

1. Bot: `shipping_quote_tool.py`; operador: `POST /api/v1/shipping/quote` [owner, manager] → `_quote_via_aveonline` (`shipping.py:184-231`).
2. Siempre `tipo: "cotizarDoble"` (multi-carrier, recomendación del dossier §3.2; el bug `999` de `cotizar2` se ignora, `aveonline_client.py:29,56`).
3. Cache de idempotencia en memoria de **60 s** por hash de payload (`QUOTE_CACHE_TTL_SECONDS = 60`, `:70-71`) — replica el comportamiento del plugin oficial.
4. Fallos mapeados a respuesta humana sin inventar precio (`shipping_quote_tool.py:1478-1516`): provider no conectado → "no tengo habilitada la cotización automática… te paso con un asesor" (escala); timeout tras 1 reintento → 504 "está tardando… ¿probamos de nuevo?" (NO escala); error genérico → "no pude cotizar… intentemos en unos minutos".

### 3. Generación de guía post-pago (automática)

1. Webhook Wompi `APPROVED` → BackgroundTask `_generate_shipping_guide` (`wompi_webhook.py:1757-1775`).
2. **Delay de 60 s** previo (`GUIDE_GENERATION_DELAY_SECONDS`, `:1768`) — ventana de cancelación/edición decidida en UAT founder 2026-07-10.
3. Gate 1: `tenant_shipping_provider_config.active_provider = 'aveonline'`; si no, skip.
4. Gate 2 (doble compuerta): master env `AVEONLINE_GENERATE_REAL_GUIDES=true` **Y** `real_guides_enabled=true` del tenant (`:1996-1998`). Hoy el master es `false` → `simulate=True` → `bloquegenerarguia="0"` (`aveonline_client.py:685,764`).
5. Best-effort: si falla, queda shipment `pending` para generación manual desde Inbox. Path manual del operador (desde `orders.py`) sin delay.
6. UAT aislado del flujo real: `POST /api/v1/integrations/aveonline/guide-dry-run` [owner o internal-service] (`integrations.py:596-604`). UAT de guía real ejecutada 2026-08-03: `scripts/uat/runs/aveonline_guia_real_2026-08-03.md`.

### 4. Webhook de estados (`webhookEstadosGuias`)

Receptor: `POST /api/v1/webhooks/aveonline/{tenant_id}` y variante con secret en path `/{tenant_id}/{secret_token}` (`aveonline_webhook.py:758,767`; mount en `main.py:290`).

1. **Secret**: verificación bcrypt con grace period vía `webhook_secret_manager` (`aveonline_webhook.py:137-153`; hash en `webhook_secret_manager.py:111-119`). Tolera ambos formatos del proveedor: oficial (`token` top-level, fechas `fechanovedad`/`fechacreacion`) y legacy AveCRM (`secret`/`param1_value`, fecha `fecha`) — `:12-23,165-187`.
2. **Dedup**: `event_uid = "{guia}|{estado_id}|{fecha}"` — replay protection (`:30-31`).
3. Del array `estado[]` se toma el evento más reciente por fecha (`_select_latest_estado:221`) y se mapea a estado interno (`_map_raw_status:129`; `12=ENTREGADA` por id, el resto por nombre).
4. **Avance monotónico**: `orders.status` solo avanza hacia `delivered` por rank, nunca retrocede; el UPDATE re-filtra por rank en SQL (race-safe) (`_ORDER_STATUS_RANK:118-129`, `_advance_order_to_delivered:323-345`).
5. **Notificaciones al cliente**: WhatsApp + email según estado (en tránsito / entregado / novedad) vía `_notify_status_change` → `_notify_client_shipment_*` y `_send_payment_confirmation_email` (`aveonline_webhook.py:432-506`, implementadas en `wompi_webhook.py:1311-1477`). El email es el canal de respaldo cuando WhatsApp está fuera de ventana 24 h (M10).

## Config por tenant vs global

### Por tenant

- `tenant_integrations` (`provider='aveonline'`): `credentials = { usuario, password_secret_id (Vault) }`; el JWT se cachea en `credentials.jwt_token` con `jwt_expires_at` (`.env.example:247-248`).
- `tenant_shipping_provider_config`: `active_provider='aveonline'`, `real_guides_enabled` (compuerta per-tenant de guías reales), `shipping_origin_*`.
- Secret del webhook: generado por plataforma, bcrypt en `tenant_webhook_secrets` (`integration='aveonline'`); se entrega al proveedor al registrar el webhook.

### Globales (env vars)

| Var | Valor | Servicio | Qué controla |
|---|---|---|---|
| `AVEONLINE_GENERATE_REAL_GUIDES` | `false` | api + orchestrator | Kill-switch master guías reales vs dry-run (B1) |
| `GUIDE_GENERATION_DELAY_SECONDS` | `60` | api | Pausa pre-guía automática post-pago |
| `PUBLIC_WEBHOOK_URL` | `https://konvi-api.onrender.com` | api | Base HTTPS para registrar webhooks en el proveedor (`render.yaml:215-217`) |

No hay credenciales Aveonline en env vars — todo per-tenant en DB/Vault.

## Seguridad

- **Secret bcrypt** con rotación y grace period (el secret viejo sigue válido durante la ventana de rotación); nunca se persiste el plaintext (`webhook_secret_manager.py`).
- **Sin HMAC del proveedor**: Aveonline no firma payloads; la única autenticación es el secret compartido. Compensaciones: dedup estricto, parseo tolerante, avance monotónico (un replay no puede retroceder estados).
- **Rate-limit**: el webhook está bajo el rate-limit global del API; los endpoints de gestión `/aveonline/*` tienen gaps declarados (M15).
- JWT y password siempre en Vault; en logs nunca se imprime el token.

## Modo de fallo

| Fallo | Comportamiento |
|---|---|
| Aveonline cae en cotización | `AveonlineTransientError` / timeout → 1 reintento y respuesta humana al cliente ("No pude cotizar el envío en este momento…", `shipping_quote_tool.py:1478-1516`); nunca se inventa un precio |
| JWT inválido/expira server-side | Refresh automático + 1 retry; si persiste, `AveonlineAuthError` (fail-visible, no silencioso) |
| Guía falla post-pago | Best-effort: shipment queda `pending`, log warning, operador genera manual desde Inbox — **el pago ya confirmado no se revierte** |
| Webhook de estado no llega | **El envío se congela en su último estado conocido** — no hay polling de respaldo (A10). `get_estado` existe (`aveonline_client.py:1138`) pero tiene **0 callers** |
| Webhook duplicado/replay | Dedup `guia|estado_id|fecha` + monotonía → no-op seguro |

## Operación

- **Manual por tenant**: credenciales Aveonline en Integraciones; registrar el webhook en el panel Aveonline (o soporte) con la URL y el `token` que entrega `POST /api/v1/integrations/aveonline/webhook/configure` [owner] (`integrations.py:897`); rotación vía `POST /aveonline/webhook/rotate` (`integrations.py:993`); estado en `GET /aveonline/webhook` (`:851`).
- **Pendiente de lanzamiento (B1)**: flip `AVEONLINE_GENERATE_REAL_GUIDES=true` + `real_guides_enabled` por tenant + UAT de guía real (el endpoint de UAT existe).
- **Monitoreo disponible**: logs `[AVEONLINE_WH]` (outcome por evento, verify_secret errors, ambiguity), métricas del shipping tool en health del orchestrator.

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| B1 | Bloqueante | `AVEONLINE_GENERATE_REAL_GUIDES=false` → ninguna guía real se despacha; flip pendiente + UAT guía real |
| A10 | Alto | Sin polling de tracking: `get_estado` implementado pero huérfano (0 callers); webhook perdido = envío congelado |
| M16 | Medio | Cliente duplicado espejo api/orchestrator (1176 líneas ×2, `diff` idénticos) — doble mantenimiento |
| M15 | Medio | Gaps de rate-limit en `integrations/aveonline/*` |
| M12 | Medio | `active_provider DEFAULT 'envia'` persiste en migraciones viejas — verificar tenants legacy antes de go-live |
| B5 | Alto | Cobertura `aveonline_client.py` 48.2% — path de dinero/logística sub-testeado |

## Referencias oficiales

- Dossier validado contra docs Aveonline: `docs/research/aveonline-dossier.md` (endpoints `autenticarusuario`, `cotizarDoble`, `generarGuiaTransporteNacional`, `webhookEstadosGuias`, `agentes`).

# Aveonline — Shipping (documento canónico)

> Estado: VIGENTE · Última verificación contra código: 2026-08-22 @ develop
> Última verificación contra doc oficial (`integraciones.aveonline.co`): 2026-08-22
> (fetch directo de autenticación, cotización, generaciónGuia, solicitudRecogida,
> estadoGuia, listadoAgentes, webhookEstadosGuias, webhookPersonalizadoApi,
> sandbox×3 + probes live contra la cuenta demo `demointegracion` — ver addendum
> 2026-08-22 en `docs/research/aveonline-dossier.md`).

## Estado

**PARCIAL** — cotización live, guías en DRY-RUN global. Significa exactamente:

- **Cotización**: LIVE. El bot y el operador cotizan envíos reales multi-carrier contra Aveonline (precios reales del tenant).
- **Generación de guías**: DRY-RUN por flag global `AVEONLINE_GENERATE_REAL_GUIDES=false` (`render.yaml:226-227` api, `348-350` orchestrator). Toda guía se genera con `bloquegenerarguia="0"` → **no factura ni despacha nada** (B1). El flip requiere además `tenant_shipping_provider_config.real_guides_enabled=true` por tenant (doble compuerta, `wompi_webhook.py:1996-1998`).
- **Webhook de estados**: implementado y activo (secret + dedup + avance monotónico + notificaciones). Registro en el proveedor por el endpoint OFICIAL `webhookPersonalizadoApi` (upsert por empresa, token generado por Aveonline) con fallback al legacy AveCRM `createWebhook.php`.
- **Tracking de respaldo (polling)**: implementado — job `_aveonline_status_poll` del worker (intervalo 1 h, guías reales >6 h sin update vía webhook, batch 25; knobs en `render.yaml:503-509`).

Aveonline es el **único provider de shipping** del runtime (ADR-0019).

## Dónde vive el código

| Pieza | Archivo |
|---|---|
| Cliente (auth, cotizar, guía, estado, agentes, webhooks) | `services/api/integrations/aveonline_client.py` |
| **Espejo idéntico** en orchestrator (deuda M16, `diff` = idénticos, test de paridad lo vigila) | `services/ai-orchestrator/integrations/aveonline_client.py` |
| Webhook de estados | `services/api/routers/aveonline_webhook.py` |
| Espejo mapping estados p/ poll del worker | `services/ai-orchestrator/shipment_status_notifications.py` |
| Endpoint de cotización operador | `services/api/routers/shipping.py` (`POST /api/v1/shipping/quote`) |
| Tool de cotización del bot | `services/ai-orchestrator/tools/shipping_quote_tool.py` + `agentic/legacy_adapters/aveonline.py` |
| Generación de guía post-pago | `services/api/lib/shipping_guides.py` (invocada desde `routers/wompi_webhook.py`) |
| Endpoints de gestión (owner) | `services/api/routers/integrations.py` (`/aveonline/*`) |
| Gestor de secrets de webhook (bcrypt) | `services/api/lib/webhook_secret_manager.py` |
| Dossier de investigación (docs oficiales) | `docs/research/aveonline-dossier.md` |
| ADR | `docs/adr/0019-aveonline-as-primary-shipping-provider.md` |

## Flujos implementados

### 1. Autenticación (JWT per-tenant con refresh)

1. Credenciales `usuario`/`password` por tenant en Vault; se resuelven vía RPC `get_aveonline_credentials` (migración `20260527020000`, `aveonline_client.py`).
2. Login contra `app.aveonline.co/api/comunes/v1.0/autenticarusuario.php` → JWT cacheado en `tenant_integrations.credentials.jwt_token`.
3. Refresh automático con buffer de 10 min (`JWT_REFRESH_BUFFER_SECONDS = 600`); el TTL cacheado se capa a ≤3600 s (doc oficial: vigencia 1 hora) aunque Aveonline acepte `tiempoToken` mayor. Nota live 2026-08-22: el server interpreta `tiempoToken` en HORAS y lo estampa en el `exp` del JWT (pedido 3600 → exp +3600 h); el cap de 1 h se mantiene por ser lo documentado.
4. Password inválida: Aveonline devuelve `status:"ok"` con token hueco y `cuentas: []` (doc oficial) — el cliente lo detecta y levanta `AveonlineAuthError` en vez de cachear un token inútil.
5. Token expirado en endpoints posteriores: llega como `message: "credenciales incorrectas"` / `"autenticacion fallida"` (NO como numbererror) — el cliente lo mapea a `AveonlineAuthError` por mensaje.
6. **`idagente` auto-resuelto** (2026-08-22): el cliente lo toma de `credentials.idagente` (override manual del tenant desde `GET /aveonline/agents`) y, si falta, llama `listarAgentesPorEmpresaAuth` → agente `principal=SI` (cache in-mem 24 h + persistencia best-effort en `credentials.idagente` vía RPC `upsert_aveonline_idagente`, migración `20260822020000`). Sin `idagente` la cotización pierde carriers (verificado live: la cuenta demo sin idagente no recibe tarifa de INTERRAPIDISIMO).

### 2. Cotización (bot y operador)

1. Bot: `shipping_quote_tool.py`; operador: `POST /api/v1/shipping/quote` [owner, manager] → `_quote_via_aveonline` (`shipping.py:184-231`).
2. Siempre `tipo: "cotizarDoble"` (multi-carrier, recomendación del dossier §3.2; el bug `999` de `cotizar2` se ignora). Nota doc 2026-08-22: la doc oficial solo documenta `cotizar2` (single-carrier); `cotizarDoble` no tiene página oficial — su comportamiento está verificado contra el plugin WooCommerce oficial y contra probes live (última: 2026-08-22, 5 carriers reales Bogotá→Bogotá con la demo).
3. Cache de idempotencia en memoria de **60 s** por hash de payload (incluye `valorrecaudo` COD desde 2026-08-22) — replica el comportamiento del plugin oficial.
4. **COD**: cuando el cart es `payment_method='cod'`, el adapter envía `contraentrega=1`, `idasumecosto=1` y `valorrecaudo=<total cart COP>` (tabla oficial "Formas de pago de la guía": destinatario paga recaudo + transporte + servicio de recaudo — el mismo combo que usa `generate_guide`). Sin `valorrecaudo`, la cotización COD omite la comisión de recaudo (`valorOtrosRecaudos`) y sub-precía la guía.
5. **`numbererror` según tabla oficial vigente** (fetch 2026-08-22): `-1` origen no existe, `-2` destino no existe, `-3` peso ≤0, `-4` unidades ≤0, `-5` valor declarado <10.000 → permanentes; `-6` unidades>máx, `-7` kilos>máx, `-1000` trayecto con límites → `AveonlinePackageLimitError`; `999`/`-999` servicio no configurado → permanente (por fila se filtran; global indica bug de `cotizar2`). "Sin carriers" no es un numbererror: `cotizarDoble` responde `status:"ok"` con `cotizaciones: []` o filas 999 → `AveonlineNoCarriersError` por 0 opciones. El caso documentado `status:"error"` + "cotizaciones no encontradas" también mapea a `NoCarriers`.
6. Fallos mapeados a respuesta humana sin inventar precio (`shipping_quote_tool.py:1478-1516`): provider no conectado → "no tengo habilitada la cotización automática… te paso con un asesor" (escala); timeout tras 1 reintento → 504 "está tardando… ¿probamos de nuevo?" (NO escala); error genérico → "no pude cotizar… intentemos en unos minutos".

### 3. Generación de guía post-pago (automática)

1. Webhook Wompi `APPROVED` → BackgroundTask `_generate_shipping_guide` (`wompi_webhook.py:1757-1775`; lógica en `lib/shipping_guides.py`).
2. **Delay de 60 s** previo (`GUIDE_GENERATION_DELAY_SECONDS`, `:1768`) — ventana de cancelación/edición decidida en UAT founder 2026-07-10.
3. Gate 1: `tenant_shipping_provider_config.active_provider = 'aveonline'`; si no, skip.
4. Gate 2 (doble compuerta): master env `AVEONLINE_GENERATE_REAL_GUIDES=true` **Y** `real_guides_enabled=true` del tenant (`:1996-1998`). Hoy el master es `false` → `simulate=True` → `bloquegenerarguia="0"`.
5. **`dsnit` obligatorio server-side** (verificado live 2026-08-22, dry-run): el server rechaza `dsnit` vacío o `"00000"` siempre — "Debe ser numérico, tener al menos 5 dígitos y ser mayor a 10000" — aunque la doc solo lo exija para COD. Si el contacto no tiene `document_number` válido, la generación se salta ANTES del claim (fail-visible; el operador completa el dato y genera manual desde Inbox). El documento se sanea a solo dígitos.
6. Best-effort: si falla, queda shipment `pending_generation` para generación manual desde Inbox. Path manual del operador (desde `orders.py`) sin delay.
7. UAT aislado del flujo real: `POST /api/v1/integrations/aveonline/guide-dry-run` [owner o internal-service] (`integrations.py`). UAT de guía real ejecutada 2026-08-03: `scripts/uat/runs/aveonline_guia_real_2026-08-03.md`.

### 4. Webhook de estados (`webhookEstadosGuias`)

Receptor: `POST /api/v1/webhooks/aveonline/{tenant_id}` y variante con secret en path `/{tenant_id}/{secret_token}` (`aveonline_webhook.py`; mount en `main.py`).

1. **Registro en el proveedor** (`POST /api/v1/integrations/aveonline/webhook/configure` [owner]):
   - **OFICIAL (2026-08-22)**: `webhookPersonalizadoApi` — `POST api.aveonline.co/api-integrations/public/api/integrations/custom-webhook` con el JWT en `Authorization` (sin Bearer) y body `{name, webhookUrl}`. Es **upsert por empresa** (una sola URL de tracking por cuenta: STG y PRD no pueden compartir cuenta con URLs distintas — ver `docs/infra/environment-segregation-plan.md` §S6.2). Aveonline genera `data.token` y lo reenvía **top-level** en cada notificación → su hash bcrypt se persiste vía `store_external_secret` (con grace period igual que una rotación).
   - **⚠️ AUTH del endpoint (fix 2026-08-27, bug latente cazado por el panel "Mis integraciones" vacío)**: el servicio api-integrations **exige JWT RS256** — el JWT operativo de la auth v1.0 (`autenticarusuario.php`) es **HS256** y muere con `400 "Incorrect key for this algorithm"` (reproducido en cuenta demo Y cuenta real). El token RS256 se obtiene de la **auth v3.0** (`app.aveonline.co/api/auth/v3.0/index.php`, `tipo:"AuthProduct"`, body `user`/`password` — su ejemplo de doc muestra alg RS256). `AveonlineClient._get_integrations_jwt()` lo emite fresco por llamada (sin caché) y SOLO lo usa `register_custom_webhook`; todo lo demás sigue con HS256. Con el fix: registro E2E verificado contra Aveonline real → `201/200 + data.token` (probe demo: "Custom webhook updated successfully", companyId 15289).
   - **Fallback legacy**: AveCRM `avestock/api/createWebhook.php` con `param1_name="secret"` generado localmente (si el endpoint oficial falla para la cuenta). El response del configure informa `mechanism: custom-webhook | legacy-avestock`. NOTA 2026-08-27: el legacy respondió 401 "No tienes permisos" en la cuenta real — cuentas sin AveCRM no pueden usarlo; el oficial con RS256 es LA vía.
   - **Lección de verificación**: el panel "Mis integraciones" del proveedor puede NO listar webhooks registrados por API (la cuenta demo respondía `updated` por upsert sin mostrar nada en el panel) — la verificación honesta es el response del endpoint + los logs, no el panel.
2. **Secret**: verificación bcrypt con grace period vía `webhook_secret_manager`. Tolera ambos formatos del proveedor: oficial (`token` top-level, fechas `fechanovedad`/`fechacreacion`) y legacy AveCRM (`secret`/`param1_value`, fecha `fecha`).
3. **Dedup**: `event_uid = "{guia}|{estado_id}|{fecha}"` — replay protection. `estado[].comentarionovedad` se persiste como `description` del evento (forensics).
4. Del array `estado[]` se procesan todos los eventos en orden cronológico y el estado actual se fija con el más reciente (guard monotónico por `occurred_at` en DB).
5. **Mapping RAW→interno** (2026-08-22, cubre el flujo oficial del API Sandbox): `GENERADA`/`PRODUCIDA`/pre-recogida → `pending`; `EN DESPACHO`/`EN REPARTO`/tránsito → `in_transit`; `ENTREGADA` → `delivered`; `EN NOVEDAD` + novedades → `exception`; `DEVOLUCION` → `returned`; `ANULADA`/`CANCELADA` → `cancelled` (terminal). Desconocido → `pending` (nunca asumir entrega).
6. **Avance monotónico**: `orders.status` solo avanza hacia `delivered` por rank, nunca retrocede; el UPDATE re-filtra por rank en SQL (race-safe).
7. **Notificaciones al cliente**: WhatsApp + email según estado (en tránsito / entregado / novedad); alerta al operador por Telegram ante novedad/devolución. El email es el canal de respaldo cuando WhatsApp está fuera de ventana 24 h (M10).

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
| JWT inválido/expira server-side | Refresh automático; el token expirado se detecta por mensaje ("credenciales incorrectas"/"autenticacion fallida") → `AveonlineAuthError` (fail-visible, no silencioso) |
| Guía falla post-pago | Best-effort: shipment queda `pending_generation`, log warning, operador genera manual desde Inbox — **el pago ya confirmado no se revierte** |
| Contacto sin documento válido | Skip ANTES del claim (dsnit obligatorio server-side, verificado live 2026-08-22); operador completa el dato y genera manual |
| Webhook de estado no llega | Polling de respaldo del worker `_aveonline_status_poll` (1 h, guías reales >6 h stale, batch 25) consulta `obtenerEstadoAuth` y aplica la misma semántica del webhook (A10 CERRADO) |
| Webhook duplicado/replay | Dedup `guia|estado_id|fecha` + monotonía → no-op seguro |

## Operación

- **Manual por tenant**: credenciales Aveonline en Integraciones; registrar el webhook vía `POST /api/v1/integrations/aveonline/webhook/configure` [owner] (oficial `webhookPersonalizadoApi` primero, legacy AveCRM fallback — el response informa `mechanism`); rotación vía `POST /aveonline/webhook/rotate`; estado en `GET /aveonline/webhook`.
- **Pendiente de lanzamiento (B1)**: flip `AVEONLINE_GENERATE_REAL_GUIDES=true` + `real_guides_enabled` por tenant (UAT de guía real ya VERDE 2026-08-03, `scripts/uat/runs/aveonline_guia_real_2026-08-03.md`).
- **Monitoreo disponible**: logs `[AVEONLINE_WH]` (outcome por evento, verify_secret errors, ambiguity), métricas del shipping tool en health del orchestrator.
- **API Sandbox oficial** (addendum dossier 2026-08-16 + verificación 2026-08-22): las empresas demo **6077/25505** permiten simular el flujo de estados de una guía sin mensajero real — `avanzarEstado` la mueve por GENERADA→PRODUCIDA→EN DESPACHO→EN REPARTO→ENTREGADA (forzable a EN NOVEDAD; terminales ENTREGADA/ANULADA) y `obtenerEstadoAuth` la consulta. Solo acepta guías de esas dos empresas (otro id → 403; token de otra empresa → 401, ambos verificados live). La cuenta demo pública `demointegracion` (idempresa 15289) **NO** es empresa sandbox. Útil para UAT E2E de tracking sin guías reales.

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| B1 | Bloqueante | `AVEONLINE_GENERATE_REAL_GUIDES=false` → ninguna guía real se despacha; flip pendiente (UAT guía real ya VERDE 2026-08-03) |
| ~~A10~~ | ~~Alto~~ | CERRADO: polling `_aveonline_status_poll` del worker invoca `get_estado` (ver "Modo de fallo") |
| M16 | Medio | Cliente duplicado espejo api/orchestrator (`diff` idénticos, test de paridad lo vigila) — doble mantenimiento |
| M15 | Medio | Gaps de rate-limit en `integrations/aveonline/*` |
| M12 | Medio | `active_provider DEFAULT 'envia'` persiste en migraciones viejas — verificar tenants legacy antes de go-live |
| B5 | Alto | Cobertura `aveonline_client.py` — path de dinero/logística sub-testeado (mejorada 2026-08-22: tests idagente/custom-webhook/COD/numbererror) |
| REC-1 | Medio | **Recogida programada NO implementada**: la doc oficial sí existe (`solicitudRecogida` → `tipo:"generarRecogida2"`, cutoff 11:00 a.m.) pero el código no la expone (dossier §5, plan P1.3). Hoy la recogida se gestiona desde el panel Aveonline |
| CAN-1 | Bajo | **Cancelación de guía individual NO existe por API** (reconfirmado 2026-08-22: sin página en el devsite; UAT 2026-08-03: `cancelarGuia` responde "parametro incorrecto"). `cancel_guide` queda best-effort + escalación a operador; `eliminarRelacionEnvios` (batch v2) no implementado |

## Referencias oficiales

- Dossier validado contra docs Aveonline: `docs/research/aveonline-dossier.md` (endpoints `autenticarusuario`, `cotizarDoble`, `generarGuiaTransporteNacional`, `webhookEstadosGuias`, `webhookPersonalizadoApi`, `listadoAgentes`, `solicitudRecogida`, `obtenerEstadoAuth`, sandbox `avanzarEstado`).

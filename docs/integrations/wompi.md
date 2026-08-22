# Wompi — Pagos (documento canónico)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop · **Revalidación contra doc oficial vigente (Track 6): 2026-08-22** — matriz abajo §"Alineación doc oficial".

## Estado

**LIVE** — payment links reales, webhook firmado y reconciliación automática de 3 capas en producción. Significa: un tenant con llaves productivas (`prv_prod_*` / `prod_events_*`) cargadas en Vault puede cobrar desde el bot de WhatsApp hoy, sin intervención de plataforma. La activación comercial por tenant (nombre comercio "KONVI" en Wompi, llaves prod) es founder-gate (B6), no bloqueo técnico.

Ambientes soportados por tenant: `sandbox` (`https://sandbox.wompi.co/v1`) y `production` (`https://production.wompi.co/v1`), seleccionado en `tenant_integrations.meta.environment` (`services/api/integrations/wompi_client.py:45`).

## Dónde vive el código

| Pieza | Archivo | Líneas |
|---|---|---|
| Cliente HTTP + firma + void | `services/api/integrations/wompi_client.py` | 774 |
| Webhook receptor + confirmación de orden + guía post-pago | `services/api/routers/wompi_webhook.py` | 2660 |
| Endpoint manual de link | `services/api/routers/orders.py` (`POST /api/v1/orders/{id}/payment-link`) | — |
| Tool del bot (genera link en conversación) | `services/ai-orchestrator/tools/payment_link_tool.py` | 906 |
| Re-drive del inbox + poll de voids | `services/ai-orchestrator/worker.py` | jobs `wompi_inbox_reconcile`, `wompi_void_poll` |
| Espejo del cliente (orchestrator) | `services/ai-orchestrator/integrations/wompi_client.py` | — |
| Runbook reconciliación manual | `docs/operations/runbooks/wompi-payment-reconciliation.md` | 99 |
| ADR ciclo de vida del link | `docs/adr/0011-payment-link-lifecycle.md` | — |

## Flujos implementados

### 1. Generación de payment link (conversacional)

1. El cliente confirma la compra en WhatsApp → el bot invoca `payment_link_tool` (`services/ai-orchestrator/tools/payment_link_tool.py`).
2. Validaciones determinísticas pre-llamada: mínimo **$1.500 COP = 150.000 cents** (`payment_link_tool.py:37`, modelo Agregador), cap de sanidad $100M COP (`payment_link_tool.py:38`).
3. Reuso idempotente: si la orden `pending_payment` tiene link vigente (≤ TTL), reutiliza el `checkout_url` en vez de crear otro (`payment_link_tool.py:411-412`).
4. La API crea el link en Wompi con **`sku = order_id`** (UUID v4 = 36 chars exactos, el máximo del campo) y **`expires_at = now + 30 min`** (`wompi_client.py:274-275,348-349`). El TTL tiene 3 puntos alineados a mano: `orders.py:76` (endpoint manual, hardcoded 30), `wompi_webhook.py:40` (regeneración de links, **este sí lee el env** `WOMPI_PAYMENT_LINK_TTL_MINUTES`, usado en `:760`) y `payment_link_tool.py:45` (boundary del idempotency guard del bot).
5. La orden queda `pending_payment` con TTL de 35 min (`PENDING_PAYMENT_TTL_MINUTES`, 5 min de buffer sobre el link); un job del worker libera el stock si expira sin pago (`render.yaml:414-418`).
6. Recordatorio de pago a los 25 min dentro de la ventana CSW de Meta (`PAYMENT_REMINDER_*`, `render.yaml:419-423`).

La API de Wompi **no acepta `metadata` libre** en payment_links; la correlación orden↔pago es `sku`/`payment_link_id`, nunca `transaction.reference` (la genera Wompi). Endpoint manual equivalente para el operador: `POST /api/v1/orders/{id}/payment-link` [owner, manager] (`orders.py:9`), con el mismo piso de $1.500 COP (`orders.py:522`).

### 2. Webhook `transaction.updated` (confirmación de pago)

Receptor: `POST /api/v1/webhooks/wompi` (`services/api/main.py:287` + `wompi_webhook.py:43`). Orden de operaciones dentro del handler:

1. **Inbox durable pre-ACK**: el payload crudo se persiste en `wompi_webhook_inbox` (idempotente por checksum) ANTES de responder 200 (`wompi_webhook.py:70-86`, `_persist_inbox:94`). Un crash post-ACK ya no pierde el pago.
2. **Resolución de tenant** vía `payment_link_id` → `payments` → `tenant_id` (el evento llega sin contexto de tenant).
3. **Verificación de firma** con el `events_key` **del tenant** cargado desde Vault (`wompi_webhook.py:314-321`). Algoritmo oficial: SHA256 simple sobre `valores(signature.properties) + timestamp + events_key`, comparado contra `signature.checksum` — **no es HMAC** (`wompi_client.py:94`, `verify_event_signature`). Un flake de Vault propaga el error (el inbox queda pendiente y reconcilia) en vez de degradar a firma inválida (`wompi_webhook.py:315-316`).
4. **Dedup por checksum** — los reintentos de Wompi y los re-drives del worker chocan aquí sin efecto (`wompi_webhook.py:325+`).
5. **Validación fail-closed de monto y moneda**: `amount_in_cents` debe ser exactamente `orders.total * 100` (`wompi_webhook.py:526-531`) y `currency == "COP"` (`wompi_webhook.py:534-539`). Mismatch → NO se confirma, log para revisión manual.
6. Si `APPROVED`: confirma orden, descuenta stock (con guard de idempotencia), notifica al cliente por WhatsApp y dispara la generación de guía Aveonline (ver `aveonline.md`).
7. Si `DECLINED` / `ERROR` / `VOIDED`: no toca la orden; el TTL de `pending_payment` libera el stock.

### 3. Pagos huérfanos (APPROVED sobre orden en estado terminal)

`_handle_orphan_payment` (`wompi_webhook.py:159-231`): el dinero entró pero no hay orden que confirmar. Se alerta con log estructurado y, si el método es **CARD pre-settlement**, se intenta **void automático** (`is_void_eligible` → `void_transaction_sync`, `wompi_client.py:489-558`). Resultado: `payments.status = 'orphan_voided'` o marcado para **reembolso manual**. NEQUI/PSE/Bancolombia no admiten void (fondos ya transferidos) — siempre manual.

### 4. Reconciliación (3 capas automáticas + 1 manual)

| Capa | Mecanismo | Dónde |
|---|---|---|
| 1. Reintentos del proveedor | Wompi reintenta el webhook a los **30 min, 3 h y 24 h** si no recibe 2xx | `wompi_client.py:378`; runbook sección "Primera línea de defensa" |
| 2. Re-drive del inbox | Worker barre `wompi_webhook_inbox` cada 180 s (gracia 120 s) y re-POSTea el payload crudo a la API; **máx 5 intentos** → dead-letter con log | `worker.py:137-144,3274-3366` |
| 3. Poll de voids | Cada 30 min consulta transacciones pendientes de void (lookback 48 h) tras cancelación/expiry | `worker.py:122-129,3096` |
| 4. Manual (pérdida total) | Si el webhook se pierde las 3 veces Y el inbox no lo capturó: Wompi **no expone búsqueda de transacción por `reference` ni `payment_link_id`** (validado 2026-06-26 contra docs oficiales), así que la reconciliación es manual contra el dashboard | `docs/operations/runbooks/wompi-payment-reconciliation.md` |

## Config por tenant vs global

### Por tenant — `tenant_integrations` (`provider='wompi'`)

```json
"credentials": { "private_key_secret_id": "…", "events_key_secret_id": "…",
                 "public_key_secret_id": "… (opcional)", "integrity_key_secret_id": "… (opcional)" },
"meta": { "environment": "sandbox|production", "private_key_preview": "prv_test_…", "public_key_preview": "pub_test_… (opcional)" }
```

Las llaves viven cifradas en **Supabase Vault** (se referencian por `secret_id`); en DB solo queda el preview. Se ingresan por UI: Ajustes → Integraciones → Wompi. Las 2 obligatorias (`private` + `events`) sostienen el flujo de payment links; las 2 opcionales (`public` + `integrity`) son el **punto de extensión del checkout embebido** (Track 6, validado contra doc oficial 2026-08-22: el Widget/Web Checkout exige `pub_` client-side + firma `integrity` server-side SHA256 `reference`+`amount`+`currency`+secreto). El runtime actual no las consume; el guardado es merge no-destructivo (dejarlas vacías conserva las existentes). La URL del webhook se registra en el dashboard de Wompi por ambiente: `https://konvi-api.onrender.com/api/v1/webhooks/wompi` (prod) — ver `.env.example:106-111`.

### Globales (env vars — sin credenciales Wompi, `render.yaml:289-291`)

| Var | Default / valor | Servicio | Qué controla |
|---|---|---|---|
| `WOMPI_PAYMENT_LINK_TTL_MINUTES` | `30` | api | TTL del link solo en el path de **regeneración** (`wompi_webhook.py:40,760`); la creación inicial usa el hardcode de `orders.py:76` — cambiar el env sin alinear `orders.py` deja los dos paths divergentes |
| `WOMPI_INBOX_RECONCILE_ENABLED` | `true` | orchestrator | kill-switch del re-drive (`render.yaml:494-495`) |
| `WOMPI_INBOX_RECONCILE_INTERVAL_SECONDS` | `180` | orchestrator | período del barrido (`render.yaml:496-497`) |
| `WOMPI_VOID_POLL_ENABLED` | `true` | orchestrator | poll de voids (`render.yaml:485-486`) |
| `WOMPI_VOID_POLL_INTERVAL_SECONDS` | `1800` | orchestrator | cada 30 min (`render.yaml:487-488`) |
| `WOMPI_VOID_POLL_LOOKBACK_HOURS` | `48` | orchestrator | ventana de búsqueda (`render.yaml:489-490`) |
| `GUIDE_GENERATION_DELAY_SECONDS` | `60` | api | pausa pre-guía post-pago (`render.yaml:228-231`) |
| `AVEONLINE_GENERATE_REAL_GUIDES` | `false` | api + orchestrator | kill-switch guías reales (ver `aveonline.md`) |

`WOMPI_INBOX_MIN_AGE_SECONDS` (120 s) y `WOMPI_INBOX_MAX_ATTEMPTS` (5) existen como defaults de código (`worker.py:143-144`), no declaradas en render.yaml.

## Seguridad

- **Firma SHA256** por evento con `events_key` per-tenant desde Vault (nunca global); comparación case-insensitive del checksum (`wompi_client.py:94`).
- **Fail-closed de dinero**: monto exacto y moneda COP obligatorios antes de confirmar (`wompi_webhook.py:515-539`); también se valida contra el ledger de pagos (`wompi_webhook.py:964-969`).
- **Dedup por checksum** + inbox idempotente → replay de Wompi o re-drive interno no duplican efectos.
- **Rate-limit** per-IP antes de procesar (`webhook_rate_limit_check`, `wompi_webhook.py:48-59`; IP real vía `cf-connecting-ip` — ver gap A2 en `mercadolibre.md`).
- Confirmación de pago **solo** server-side por webhook; jamás por interpretación de texto del cliente en chat (regla de producto).

## Modo de fallo

| Fallo | Comportamiento |
|---|---|
| Wompi cae al crear el link | El tool responde al cliente que no pudo generar el link; la orden queda `pending_payment` sin link y expira por TTL liberando stock |
| Webhook perdido (transitorio) | Reintento Wompi 30m/3h/24h (capa 1) |
| Crash del API entre ACK y procesamiento | Re-drive del inbox, máx 5 intentos → dead-letter logueado (capa 2) |
| Webhook perdido total (3 reintentos + sin inbox) | Orden estancada `pending_payment` → **runbook manual** (M4). El cliente pagó: reconciliar en dashboard Wompi y confirmar/voidar a mano |
| Pago huérfano (orden ya terminal) | Alerta + void automático si CARD pre-settlement; si no, reembolso manual |
| Refund post-settlement | **Wompi no tiene API pública de refund** (`wompi_client.py:479-481`); NEQUI/PSE siempre manual vía dashboard |

## Operación

- **Manual por tenant**: alta del comercio en Wompi, copiar llaves a la UI de Integraciones, registrar la URL de eventos en el dashboard Wompi (sandbox y prod por separado).
- **Runbook**: `docs/operations/runbooks/wompi-payment-reconciliation.md` — esperar ≥24 h antes de reconciliar manualmente (los reintentos resuelven lo transitorio).
- **Monitoreo disponible**: logs estructurados `[WOMPI]` (evento_recibido, monto_mismatch, moneda_invalida, ORPHAN, INBOX re-drive/DEAD_LETTER) filtrables en Render Dashboard.

## Alineación doc oficial (Track 6 — fetch live 2026-08-22)

Matriz capacidad × doc × código completa ejecutada el 2026-08-22 (cada URL fetcheada ese día). **Veredicto: nada de lo que usamos está deprecado ni cambió** — payment links (campos, `sku` máx 36 chars), reintentos de eventos 30min/3h/24h esperando HTTP 200, firma SHA256 de `signature.properties`+`timestamp`+events secret, void con `prv_`. Las decisiones históricas "sin API para invalidar links" y "sin refund público" se sostienen en la guía vigente.

| Capacidad (doc oficial) | Estado en código | Decisión Track 6 |
|---|---|---|
| 4 llaves por ambiente (`pub_`, `prv_`, `*_events_`, `*_integrity_`) — [ambientes-y-llaves](https://docs.wompi.co/en/docs/colombia/ambientes-y-llaves/) | Las 4 capturables por UI desde 2026-08-22 (pub/integrity opcionales, validación de prefijos en `apps/web/lib/wompi-keys.ts`) | **Hecho** (punto de extensión) |
| Widget/Web Checkout: `pub_` + firma integrity + acceptance NO requeridos (el checkout hosted presenta los contratos) — [widget-checkout-web](https://docs.wompi.co/en/docs/colombia/widget-checkout-web/) | Ausente (storefront fuera de alcance); `_build_customer_data` preservado (`wompi_client.py:241-301`) | Diseñado para el futuro: firma server-side + reuso del builder; acceptance tokens solo si se va a `POST /transactions` directo |
| `taxes` (VAT/CONSUMPTION) en payment links — [links-de-pago](https://docs.wompi.co/en/docs/colombia/links-de-pago/) | Ausente | **Pendiente decisión founder** (amarrado a B6/DIAN: ¿IVA desglosado en el checkout?) — implementación = 1 campo en payload |
| `redirect_url`, `image_url` en links | Cliente los soporta; ningún caller los pasa | Punto de extensión (decisión de producto: página de "pago recibido" / branding) |
| Reintentos webhook 30min/3h/24h esperando 200 — [eventos](https://docs.wompi.co/en/docs/colombia/eventos/) | Asumido exactamente así en inbox durable + dedup + reconciliación | Confirmado vigente — sin cambio |
| Firma de eventos = SHA256 concatenación (NO HMAC); `properties` variable por evento | Código correcto (data-relative + fallback, `compare_digest`); **copy de UI corregido 2026-08-22** (decía "HMAC-SHA256") | Hecho |
| Eventos de token (`nequi_token.updated`, etc.) — solo aplican a suscripciones | No procesados (modelo one-shot); copy de UI corregido | No aplica hoy |
| `GET /payment_links/:id` sin auth | Ausente | Punto de extensión (verificar `active` real antes de reusar link) — baja prioridad |
| Tokenización / payment sources / COF / suscripciones — [fuentes-de-pago](https://docs.wompi.co/docs/colombia/fuentes-de-pago/) | Ausente | No aplica (modelo cobro one-shot por orden) |
| Datos de prueba sandbox oficiales: tarjeta `4242…`→APPROVED / `4111…`→DECLINED, Nequi `3991111111`/`3992222222`, PSE inst. 1/2 — [datos-de-prueba](https://docs.wompi.co/docs/colombia/datos-de-prueba-en-sandbox/) | Referenciados ahora para la recertificación E2E (B4) | Hecho (insumo UAT) |

**No verificable ese día:** API Reference exhaustivo (HTTP 403) — la conclusión "no hay API para invalidar links" se sostiene en la guía de links (solo documenta POST y GET). Ventana exacta de settlement para void: no publicada (la heurística conservadora de 23h se mantiene).

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| M4 | Medio | Reconciliación de webhook totalmente perdido es **manual** (limitación del API público de Wompi, documentada en runbook) |
| B5 | Alto | Cobertura de `wompi_webhook.py` 55.0% (754 stmts, 339 sin cubrir) — path de dinero sub-testeado |
| B6 | Bloqueante | Founder-gates fiscales: nombre de comercio "KONVI" en Wompi, facturación DIAN — sin ellos no hay go-live comercial |
| A12 | Alto | El re-drive worker→API se autentica con `INTERNAL_SERVICE_SECRET` + `X-Tenant-Id` autodeclarado (barrera única service-to-service) |
| B4 | Bloqueante | UAT E2E conversacional stale desde 2026-05; el flujo de pago del bot necesita re-certificación pre-lanzamiento |

## Referencias oficiales

- https://docs.wompi.co/en/docs/colombia/ (links de pago, eventos, transacciones, ambientes y llaves) — validada 2026-04-24; runbook re-validado 2026-06-26; **revalidación completa Track 6 el 2026-08-22** (incl. widget-checkout-web, tokens-de-aceptacion, fuentes-de-pago, datos-de-prueba-en-sandbox).

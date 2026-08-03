# Asíncrono AI Orchestrator

Patrón Arquitectónico del Orquestador de la plataforma conversacional.
Este módulo corre un *Background Worker* en Python / FastAPI desacoplado totalmente de las interfaces públicas, protegiéndose así contra caídas de LLM latencias usando Supabase Queues o PGMQ como amortiguador.

## Arquitectura del Servicio

1. **El Worker Loop:** Un poller / listen thread de Postgres recuperando JSON payloads generados por los webhooks públicos.
2. **Context Manager Middleware:** Encapsula el `tenant_id` y las credenciales firmadas. El modelo carece del ID.
3. **Structured Pydantic Calling:** Cada Tool es dictada e inyectada bajo validación robusta (usando Instructor o LangChain con Pydantic JSON Schema strict mode).
4. **Guardrail Evaluator Middleware:** Antes del broadcast al servicio conector de Telegram / Meta, valida la salubridad y fidelidad del output.

## Deployments
- Render Background Worker Profile (No HTTP entry point).
- En caso de necesitar scaling horizontal, escalar las réplicas del deployment.
- Requiere acceso total a credenciales de `Vertex AI` o `Gemini API` en Secrets.

## Runbook de crons (D-F7)

El worker (`worker.py`) corre un solo loop async (`_poll_cycle`, cada
`POLL_INTERVAL_SECONDS`) que ejecuta varios jobs periódicos con su propio gate de
intervalo. Todos los parámetros están **versionados en `render.yaml`** (servicio
`konvi-orchestrator`); los valores por defecto viven en el código y se pueden
sobreescribir sin redeploy desde el Render Dashboard.

> Nota de arquitectura (D-F7): la recolección de health metrics hace HTTP síncrono
> (Graph API + Telegram) y queries supabase bloqueantes. Se ejecuta vía
> `asyncio.to_thread` para **no congelar el event loop** (uvicorn `/health` corre
> en el mismo proceso; bloquearlo lo marca *unhealthy* en Render).

### Kill-switches (poner en `false` para apagar sin redeploy)

| Env | Default | Job |
|---|---|---|
| `PAYMENT_REMINDER_ENABLED` | `true` | Recordatorio de pago dentro de la CSW (24h Meta) + HSM fuera de CSW |
| `CART_ABANDONED_REMINDER_ENABLED` | `true` | HSM `cart_abandoned_24h_v1` (MARKETING) |
| `WOMPI_VOID_POLL_ENABLED` | `true` | Poll de anulaciones (voids) Wompi |
| `AVEONLINE_STATUS_POLL_ENABLED` | `true` | Poll backup de tracking Aveonline (A10) |
| `HEALTH_METRICS_ENABLED` | `true` | Collector de salud per-tenant per-provider |
| `PENDING_PAYMENT_RELEASE_ENABLED` | `true` | Libera stock de órdenes `pending_payment` expiradas |
| `IDEMPOTENCY_CLEANUP_ENABLED` | `true` | Limpieza de claves de idempotencia |
| `HUMAN_TAKEOVER_QUEUE_ENABLED` | `true` | Cola de takeover humano |
| `WHATSAPP_OUTBOUND_QUEUE_ENABLED` | `true` | Cola de salientes WhatsApp |
| `TENANT_HARD_DELETE_ENABLED` | `true` | Borrado definitivo de tenants (grace expirado, Ley 1581) |
| `ANTI_HIBERNATION_ENABLED` | `true` | Ping anti-hibernación (Render Free) |

### Frecuencias e intervalos

| Env | Default | Efecto |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `3` | Cadencia del loop principal |
| `PAYMENT_REMINDER_INTERVAL_SECONDS` | `60` | Cada cuánto revisa órdenes candidatas a recordatorio |
| `PAYMENT_REMINDER_DELAY_MINUTES` | `25` | Espera tras crear la orden antes de recordar |
| `PAYMENT_REMINDER_WINDOW_MINUTES` | `5` | Ancho de la ventana de disparo |
| `META_CSW_HOURS` | `24` | Ventana de servicio al cliente Meta (free-form permitido) |
| `PENDING_PAYMENT_TTL_MINUTES` | `35` | TTL antes de liberar la orden (≥ delay+window del recordatorio) |
| `CART_ABANDONED_REMINDER_INTERVAL_SECONDS` | `300` | Cadencia del cron de carrito abandonado |
| `CART_ABANDONED_THRESHOLD_HOURS` | `24` | Antigüedad mínima del carrito para recordar |
| `CART_ABANDONED_MAX_AGE_HOURS` | `72` | Antigüedad máxima (fuera → no se molesta al cliente) |
| `CART_ABANDONED_MAX_PER_TENANT_PER_CYCLE` | `15` | Tope de envíos por tenant por ciclo (anti-ráfaga) |
| `CART_ABANDONED_DISCOUNT_LABEL` | `10%` | Etiqueta de descuento en el copy |
| `CART_ABANDONED_QUIET_HOURS_ENABLED` | `false` | Silenciar HSM de madrugada (hora CO) |
| `CART_ABANDONED_QUIET_START_HOUR` / `_END_HOUR` | `21` / `8` | Rango quiet-hours (hora CO) |
| `COLOMBIA_UTC_OFFSET_HOURS` | `-5` | Offset para calcular hora local CO |
| `WOMPI_VOID_POLL_INTERVAL_SECONDS` | `1800` | Cada cuánto reconcilia voids Wompi |
| `WOMPI_VOID_POLL_LOOKBACK_HOURS` | `48` | Ventana hacia atrás del poll de voids |
| `AVEONLINE_STATUS_POLL_INTERVAL_SECONDS` | `3600` | Cada cuánto consulta estados de guías stale (1 h) |
| `AVEONLINE_STATUS_POLL_STALE_HOURS` | `6` | Guía real sin update vía webhook >N h → candidata |
| `AVEONLINE_STATUS_POLL_BATCH` | `25` | Cap de guías consultadas por ciclo |
| `HUMAN_TAKEOVER_SLA_CHECK_INTERVAL_SECONDS` | `600` | Cada cuánto evalúa SLA de takeover |
| `HUMAN_TAKEOVER_SLA_HOURS` | `2` | Umbral sin respuesta humana → alerta |
| `HEALTH_METRICS_INTERVAL_SECONDS` | `300` | Cadencia del collector de salud |
| `STALE_PROCESSING_RECLAIM_MINUTES` | `3` | Antigüedad para reclamar mensajes `processing` colgados |
| `STALE_PROCESSING_SWEEP_INTERVAL_SECONDS` | `60` | Cadencia del sweep de reclamo |
| `IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS` | `3600` | Cadencia de limpieza de idempotencia |
| `IDEMPOTENCY_CLEANUP_BATCH` | `2000` | Tamaño de lote de la limpieza |
| `TENANT_HARD_DELETE_INTERVAL_SECONDS` | `21600` | Cada cuánto procesa borrados (6 h) |
| `TENANT_HARD_DELETE_BATCH_SIZE` | `10` | Tenants por ciclo de hard-delete |
| `ANTI_HIBERNATION_INTERVAL_SECONDS` | `840` | Cadencia del ping (14 min) |

### Trigger manual — recordatorio de pago

Para disparar `payment_reminder_v1` a una orden concreta (soporte / VIP), sin
esperar al cron:

```bash
python3.11 scripts/admin/send_payment_reminder.py \
  --tenant-id <uuid> --order-id <uuid> [--dry-run]
```

El script hidrata desde el **esquema real** (teléfono en `conversations`, nombre
en `contacts.name`, link en `payments.checkout_url`, `total_amount` en **pesos**)
y respeta el soft opt-out (`consent_revoked_at`) igual que el cron.

> Los env de crons se ajustan en el Render Dashboard del servicio
> `konvi-orchestrator`; los defaults y su documentación canónica están en
> `render.yaml` y en esta tabla.

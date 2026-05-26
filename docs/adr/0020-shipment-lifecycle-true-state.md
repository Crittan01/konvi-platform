# ADR-0020 — Shipment lifecycle con estados ciertos (Rev. 108)

**Fecha**: 2026-05-25 · **Sesión**: rev. 108 · **Status**: Aprobado.

## Contexto

Hasta rev. 107, el sistema notificaba al cliente "📦 Tu envío está en camino"
inmediatamente después de que Aveonline retornara `generarGuia2` OK. Eso es
**falso positivo**: la guía generada solo significa que el courier asignó un
tracking_number — el paquete físico aún no fue recogido.

Adicionalmente, el flujo conversacional `payment_link_tool` hacía un
soft-check de `stock_quantity` pero NO creaba reservas atómicas. Dos clientes
solicitando el último item al mismo tiempo recibían dos links Wompi válidos;
solo el primero en pagar conseguía stock real, el segundo quedaba con orden
confirmada sin inventario (oversell silencioso).

Aveonline tiene webhook oficial `webhookEstadosGuias` (dossier §6.2) que
reporta estados físicos reales (EN RUTA, ENTREGADA, NOVEDAD, DEVUELTA) pero
hasta rev. 107 no estaba implementado.

## Decisión

### 1. Soft-reserve atómica obligatoria

`payment_link_tool` invoca `rpc_stock_reserve` (existente desde rev. 78)
**antes** de crear orden + link Wompi. TTL 35 min alineado con
`PENDING_PAYMENT_TTL_MINUTES`. En insufficient_stock, rollback de reservas
previas del mismo intento + mensaje al cliente sin generar link.

### 2. Lifecycle de notificaciones en 4 etapas (verdad observable)

| Etapa | Trigger real | WhatsApp | Email |
|---|---|---|---|
| 1 | Wompi APPROVED | "✅ Pago confirmado" | "Pago recibido" |
| 2 | Aveonline `generarGuia2` OK | "📋 Guía asignada" | "📋 Guía generada" |
| 3 | Webhook Aveonline EN RUTA / EN REPARTO / EN TRANSITO | "🚚 Tu envío salió en ruta" | "🚚 Tu envío salió en ruta" |
| 4 | Webhook Aveonline ENTREGADA | "📬 Tu pedido fue entregado" | "📬 Pedido entregado" |
| novedad | Webhook EN NOVEDAD / DEVUELTA | "⚠️ Novedad con tu envío" | "⚠️ Novedad con tu envío" |

Las etapas 3, 4 y novedad SOLO se disparan cuando el courier reporta el
cambio físico vía webhook — nunca antes.

### 3. Webhook Aveonline implementado

**Endpoint**: `POST /api/v1/webhooks/aveonline/{tenant_id}` (con secret en
body via `param1_value`) o `POST /api/v1/webhooks/aveonline/{tenant_id}/{secret}`
(secret en URL path).

**Defensa en profundidad** (Aveonline NO tiene HMAC nativo — dossier §6.2):

- **F.10 secret manager**: pseudo-secret UUIDv4 por tenant, bcrypt hash en
  `tenant_webhook_secrets` con rotación trimestral + grace period 7d.
  Aveonline guarda el plaintext en su lado (registrado vía `createWebhook`
  con `param1_name="secret"`).
- **F.4 dedup genérica**: `shipment_tracking_events.external_event_id` =
  `"{guia}|{estado_id}|{fecha}"` UNIQUE constraint (at-least-once safe).
- **Audit forensics**: cada webhook recibido se intenta registrar en
  `shipment_tracking_events` (válido o inválido) para investigación
  post-incidente.

**Mapping cross-provider**:

| Aveonline raw | Internal status |
|---|---|
| `EN OFICINA`, `EN RECOGIDA`, `RECOGIDA` | `pending` |
| `EN BODEGA`, `EN TRANSITO`, `EN REPARTO`, `EN ENTREGA`, `RECIBIDA EN TRANSPORTADORA` | `in_transit` |
| `ENTREGADA` | `delivered` |
| `EN NOVEDAD`, `DIRECCION ERRONEA`, `CLIENTE AUSENTE`, `RECHAZA PRODUCTO` | `exception` |
| `DEVOLUCION`, `DEVUELTA` | `returned` |
| Unknown | `pending` (conservador — NO asumir entrega) |

### 4. Tabla `shipment_tracking_events` (nueva)

Append-only, cross-provider (`aveonline`, `envia`, `mercadolibre`). Permite
reconstruir el historial físico completo del envío independiente del
`shipments.status` denormalized.

```sql
CREATE TABLE shipment_tracking_events (
    id UUID PK,
    tenant_id UUID NOT NULL,
    shipment_id UUID,
    order_id UUID,
    provider TEXT NOT NULL,
    external_event_id TEXT NOT NULL,  -- dedup key
    raw_status TEXT,
    raw_estado_id INTEGER,
    internal_status TEXT NOT NULL,
    description TEXT,
    occurred_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    raw JSONB,
    UNIQUE(provider, external_event_id)
);
```

RPC atómica `fn_record_shipment_tracking_event` hace: dedup INSERT +
UPDATE `shipments.status` si el nuevo evento es relevante y el shipment NO
está en estado terminal.

### 5. UI Settings Aveonline

Nueva sección "Webhook de estados" con:
- Status (configurado / no configurado).
- URL pública del webhook (read-only, copy button).
- Botones: Configurar / Rotar secret / Eliminar.
- Display de secret plaintext UNA VEZ tras rotación (warning amber + copy).

## Consecuencias

### Positivas

- **Verdad observable**: nunca prometemos "envío en camino" sin confirmación
  física del courier. Mejora trust + reduce reclamos por falsas alarmas.
- **Anti-oversell**: race condition de doble venta del último item queda
  cerrada por rpc_stock_reserve atómico con FOR NO KEY UPDATE.
- **Cross-provider extensible**: `shipment_tracking_events` tiene mismo
  schema para Envia + MercadoLibre. Reutilizable cuando se integre webhook
  Envia (F.7) o MeLi shipments topic.
- **Forensics + Habeas Data**: cada webhook intentado queda registrado,
  facilita auditoría regulatoria y diagnóstico de spoofing.

### Negativas / Riesgos

- **Aveonline sin HMAC nativo**: pseudo-secret + URL es la única defensa.
  Si el secret se filtra, atacante puede spoofear `ENTREGADA` falsos. Mitigación
  ya implementada: rotación 90d default + grace period 7d. IP allowlist
  Cloudflare es validación humana pendiente con `desarrollo1@aveonline.co`.
- **Dependencia de webhook reachability**: si nuestra URL pública cae,
  Aveonline NO retry-policy documentada. Backup: polling cron via
  `AveonlineClient.get_estado` (planeado follow-up, no incluido en rev. 108).
- **PUBLIC_WEBHOOK_URL env var requerida en prod**: si falta, la UI muestra
  placeholder `YOUR_PUBLIC_HOST` — tenant ve URL bonita pero Aveonline NO
  podrá llegar. Documentar en runbook de deploy.

## Verification

1. **Suite tests**: 2454 verde (incluye 13 nuevos tests
   `test_aveonline_webhook.py` cubriendo mapping + secret extraction +
   estado history selection).
2. **TypeScript**: tsc `--noEmit` OK.
3. **Migration**: `supabase/migrations/20260529000000_shipment_tracking_events.sql`
   aplicada al remote vía protocolo seguro (`supabase db query --linked -f`).
4. **UAT live** (post-deploy):
   - Generar guía real Aveonline con DEMO account → Etapa 2 "📋 Guía
     asignada".
   - Esperar webhook EN RUTA → Etapa 3 disparo automático.
   - Esperar webhook ENTREGADA → Etapa 4 + cierre.
   - Soft-reserve: 2 clientes en paralelo solicitando último item → solo
     1 obtiene link, otro recibe "sin stock suficiente".

## Pendientes follow-up

- **Polling backup**: cron `services/ai-orchestrator/worker.py` que cada 6h
  invoca `AveonlineClient.get_estado` para shipments en
  `status IN ('labeled', 'in_transit')` con `last_polled_at < NOW() - 6h`.
  Cierra el gap si webhook llega corrupto o se pierde.
- **IP allowlist Cloudflare**: pedir a `desarrollo1@aveonline.co` el rango
  CIDR de IPs origen de webhooks Aveonline. Defensa adicional al
  pseudo-secret.
- **PUBLIC_WEBHOOK_URL** debe estar seteado en Render env vars antes del
  primer registro de webhook por tenant en producción.
- **Cron expire_stock_reservations** (`fn_expire_stock_reservations`): ya
  existe en DB pero requiere `pg_cron.schedule(...)` configurado en
  Supabase. Verificar en migración follow-up.

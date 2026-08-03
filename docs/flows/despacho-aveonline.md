# Flujo — Despacho Aveonline (cotización → guía → tracking)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Estado al 2026-08-02 (auditoría §4): **Aveonline PARCIAL** — cotización live, **guías en dry-run** (`AVEONLINE_GENERATE_REAL_GUIDES=false`, bloqueante B1), webhook de estados implementado. Aveonline es el **único** provider de shipping (Envia eliminado en rev. 109).

---

## 1. Cotización

- **Desde el bot**: `services/ai-orchestrator/tools/shipping_quote_tool.py` → Core API `POST /api/v1/shipping/quote` (auth service-to-service por header `INTERNAL_SERVICE_SECRET`, líneas 21-22). Defaults de paquete por env (1kg, 10×10×10cm, 24-27); timeout 25s (28). Ambigüedad controlada: no adivinar producto si la diferencia es baja (750).
- **Desde consola**: módulo Cotizador (`/dashboard/shipping`) → mismo endpoint; RBAC owner/manager (`services/api/routers/shipping.py:5`).
- **En Core API**: branch `_quote_via_aveonline` (`shipping.py:184`) — agrega peso/dimensiones de los parcels (Aveonline cotiza por paquete único, 220) → `client.quote(...)` (231) → persiste la cotización canónica `quote_response`, incluyendo `order_id` cuando la cotización nace DESDE un pedido (328).
- **Sincronización de tarifa a la orden** (`_sincronizar_envio_en_orden`, `shipping.py:545-578`): baja la tarifa confirmada y **recalcula el total desde la fuente de verdad** (ítems + envío − descuento). Regla de dinero (566-576): si el pedido ya fue cobrado (pago `approved` en `payments`, no la etiqueta de estado) o está cerrado → **no se toca el dinero**; se registra ERROR y se devuelve aviso para conciliación humana. Base legal: Ley 1480 art. 26 (564).
- Resolver provider activo: `_get_active_shipping_provider` (`shipping.py:155`). Deuda M12: `active_provider DEFAULT 'envia'` persiste en migraciones viejas — verificar tenants legacy antes de go-live.

## 2. Generación de guía

### 2.1 Automática post-pago (Wompi APPROVED o COD)

- Trigger: paso 7.6 del webhook Wompi (`services/api/routers/wompi_webhook.py:584-596`, best-effort ~10-15s) → `_generate_shipping_guide` (1755).
- **Delay deliberado**: `GUIDE_GENERATION_DELAY_SECONDS` default **60s** (1768), `asyncio.sleep` solo en el path automático (1794-1807) — ventana para que el operador detecte un pedido anómalo antes de facturar guía (UAT founder 2026-07-10). La generación **manual** del operador (desde `orders.py`) no pasa delay (1798).
- **Flag dry-run (B1)**: `simulate = not (AVEONLINE_GENERATE_REAL_GUIDES && tenant_real_guides)` (1998-1999) — hoy el master env está `false` en Render (`render.yaml`, bloqueante B1) → toda guía es **simulada** (`bloquegenerarguia="0"`), nada se despacha de verdad. Status resultante: `'simulated'` vs `'labeled'` (2179).
- **Claim anti-duplicado**: fila de claim con status `('generating','labeled','simulated')` — un 2º INSERT concurrente/retry falla por constraint único (2039) → nunca dos guías para la misma orden.
- **Timeout money-safe**: si Aveonline hace timeout con `simulate=True` → no hubo cobro → shipment a `pending_generation`; con guía REAL el timeout es **ambiguo** (pudo facturar) → se deja para revisión, no se reintenta a ciegas (2115-2122).
- **Path COD**: tras crear la orden contraentrega (nace `confirmed`), el bot intenta auto-guía best-effort (`tools/payment_link_tool.py:720-755`); rechazo/exception solo loguea.
- **Endpoint manual**: existe generación desde operador vía `services/api/routers/integrations.py` (la auditoría B1 cita `integrations.py:597` como endpoint listo para el UAT de guía real).

### 2.2 Notificación "Guía generada" (etapa 2)

Solo si la guía se generó: email `shipment_label_ready` + WhatsApp con carrier/tracking/URL (`wompi_webhook.py:598-639`). Copy deliberado (599-603): la guía significa **tracking asignado**, no "envío en camino" — el estado físico llega por webhook (§3).

## 3. Webhook de estados (tracking)

`services/api/routers/aveonline_webhook.py` (774 líneas). Responsabilidades (docstring 5-6): actualizar `shipments.status` con mapping cross-provider y notificar al cliente.

1. **Formatos soportados** (12-22): A) oficial (custom-webhook `api-integrations`, secret en `token`) y B) legacy (AveCRM `createWebhook.php`, secret en `secret`/`param1_value`).
2. **Verificación de secret** (26-30, `_verify_secret` 137): vía F.10 `webhook_secret_manager` (`integration='aveonline'`) con grace period; extracción multi-fuente (URL path `/webhooks/aveonline/{tenant_id}/{secret}`, `token`, `secret`, `param1_value`, query `?secret=`) (165-187). Ante error del verificador → no procesa (153).
3. **Dedup**: `event_uid = "{guia}|{estado_id}|{fecha}"` con fecha = `fechanovedad`/`fechacreacion` (30, 189-197); dedup atómico por evento (247).
4. **Estado más reciente**: si el POST trae múltiples estados históricos en `estado[]`, el shipment se actualiza solo con el más reciente por fecha (`_select_latest_estado`, 221-232).
5. **Mapping y monotonía**: `_map_raw_status` (129-134, default `pending`); rank de avance de `orders.status` **monotónico** — nunca regresa un estado alcanzado ni pisa uno superior (118-120).
6. **Notificación cliente por estado** (`_notify_status_change`, 432): WhatsApp + email para `in_transit` (490-513), `delivered` (517-534) y `exception` (544-565); el email muestra el **raw_status** del carrier (p. ej. "EN REPARTO", "CLIENTE AUSENTE") en vez del enum interno (504-506, 557-558). Errores de notificación: log, no rompen el ACK (750).

**Gap conocido (A10)**: no hay polling de respaldo — `get_estado` está implementado en el cliente pero con **0 callers**; si el webhook no llega, el envío se congela en su último estado notificado.

## 4. Cancelación

- **Del pedido**: cancelación desde consola (owner/manager) — restock idempotente + refund/void del pago si aplica (ver [`pago-wompi.md`](pago-wompi.md) §3).
- **De la guía/envío**: **no existe en Konvi hoy**. Los endpoints `/label`, `/tracking`, `/pickup`, `/cancel` se eliminaron con Envia; la nota rectora (`shipping.py:536-542`) lo dice explícito: label es implícito en `generarGuia2`, tracking llega por webhook, y **pickup/cancel se agenda vía API Aveonline directamente si se necesita (no vía Konvi)**. Cualquier flujo de cancelación de despacho es hoy un procedimiento operativo externo + corrección manual del estado en consola. **[EXTERNO]**

## 5. Secuencia resumida (estado real)

```text
Cotización (bot o consola) ──► tarifa sincronizada a la orden (total recalculado)
Pago APPROVED (o COD)      ──► +60s delay ──► generarGuia2 [SIMULATE hoy] ──► shipment 'simulated'|'labeled'
                           ──► email+WA etapa 2 "Guía generada" (tracking)
Webhook Aveonline          ──► secret OK + dedup ──► shipments.status (monotónico)
                           ──► WA + email por estado (in_transit / delivered / exception)
Cancelación                ──► pedido: consola (restock+refund) · guía: vía Aveonline directa [EXTERNO]
```

---

### Archivos clave

| Pieza | Archivo |
|---|---|
| Cotización bot | `services/ai-orchestrator/tools/shipping_quote_tool.py` |
| Cotización API + sync tarifa | `services/api/routers/shipping.py` |
| Auto-guía post-pago | `services/api/routers/wompi_webhook.py` (1755-2210), delay 1768 |
| Auto-guía COD | `services/ai-orchestrator/tools/payment_link_tool.py` (720-755) |
| Guía manual operador | `services/api/routers/integrations.py` (~597) |
| Webhook estados | `services/api/routers/aveonline_webhook.py` |
| Timeline UI | `apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx` |

# Runbook — Reconciliación de pagos Wompi (webhook perdido)

**Última validación contra docs oficiales:** 2026-06-26 (https://docs.wompi.co/docs/)
**Responsable:** operador / founder
**Frecuencia:** on-demand (ante una orden estancada) — ver "Cuándo" abajo.

## Problema

Una orden queda en `orders.status = 'pending_payment'` indefinidamente si Wompi
aprobó el pago pero **el webhook `transaction.updated` no llegó** (outage,
timeout, firma rechazada, purga del orphan-buffer). El cliente pagó pero la
plataforma no lo refleja.

## Por qué NO hay cron automático (limitación REAL del API público de Wompi)

Validado contra la documentación oficial vigente (2026-06-26):

| Endpoint | Resultado |
|---|---|
| `GET /v1/payment_links/{id}` | Devuelve solo metadata del link (`id`, `sku`, `amount_in_cents`, `active`, ...). **NO incluye estado de pago ni transacciones.** |
| `GET /v1/transactions/{id}` | Confiable, pero **requiere el `transaction_id`** — que solo viene en el webhook (el que se perdió). |
| `GET /v1/transactions?reference=` / `?payment_link_id=` | **NO existe / no documentado.** El API público solo expone el GET por `id`. |

Lo único que persistimos para una orden es `payments.wompi_link_id`. Con SOLO el
`payment_link_id` **no hay forma documentada de encontrar la transacción** en el
API de Wompi. Por eso un cron automático no es viable hoy (no inventamos
endpoints — ADR/reglas de proyecto). Wompi mismo remite a "contactar soporte"
para workflows de reconciliación.

## Primera línea de defensa (automática, ya activa)

**Wompi reintenta los webhooks**: ~30 min, 3 h y 24 h tras el evento. La mayoría
de pérdidas son transitorias y se resuelven solas con el reintento. **Espera al
menos 24 h** antes de reconciliar manualmente — probablemente el reintento ya lo
resolvió.

## Procedimiento de reconciliación manual

### 1. Encontrar órdenes estancadas (>24 h sin pago)

```sql
SELECT o.id AS order_id, o.tenant_id, o.total_amount, o.created_at,
       p.wompi_link_id, p.wompi_txn_id, p.checkout_url
FROM orders o
LEFT JOIN payments p ON p.order_id = o.id
WHERE o.status = 'pending_payment'
  AND o.created_at < NOW() - INTERVAL '24 hours'
ORDER BY o.created_at;
```

### 2. Verificar en el dashboard de Wompi

Dashboard Wompi → **Transacciones** → buscar por monto + fecha + `checkout_url`/link.
Determinar el estado real de la transacción asociada al link:
- **APPROVED** → el cliente pagó; hay que confirmar la orden (paso 3).
- **DECLINED / VOIDED / sin transacción** → no pagó; dejar que el cron
  `_release_expired_pending_payment_orders` la cancele (o cancelar manual).

### 3a. Confirmar (si hay `wompi_txn_id` guardado)

Si la fila `payments` ya tiene `wompi_txn_id` (recibimos un webhook previo no
final), se puede verificar por el endpoint DOCUMENTADO y confirmar:

```bash
# Verificar estado real (usar la private_key del tenant + env correcto):
curl -s -H "Authorization: Bearer <PRIVATE_KEY_TENANT>" \
  https://production.wompi.co/v1/transactions/<WOMPI_TXN_ID> | jq '.data.status'
# → si "APPROVED", confirmar la orden (ver 3b).
```

### 3b. Confirmar la orden (verificado el pago)

Con el pago verificado APPROVED en Wompi, confirmar la orden por la vía canónica
`_confirm_order` (idempotente: status→confirmed + decremento de stock). Opciones:

- **Reenviar el webhook** desde el dashboard de Wompi (Transacciones → la
  transacción → reenviar evento), si el dashboard lo permite. Es la vía más
  limpia — pasa por todas las validaciones (firma, monto, idempotencia).
- Si no es posible, ejecutar la confirmación administrativa (INTERVENCIÓN
  HUMANA, requiere `order_id` + `tenant_id` + el `wompi_txn_id` verificado).
  Coordinar con dev: llamar `_confirm_order(supabase, order_id, tenant_id)`
  (services/api/routers/wompi_webhook.py) — NO hacer UPDATE directo a `orders`
  sin el decremento de stock asociado.

## Cuándo automatizar (revisar)

Construir un cron/script automático SOLO si:
1. **Wompi publica** un endpoint para listar/buscar transacciones por
   `reference`/`payment_link_id`/merchant (re-validar docs cada Q — ver
   `docs/research/changelog-watch.md`), **o**
2. El volumen justifica un **poll por `txn_id`** acotado: para órdenes
   `pending_payment` que YA tienen `payments.wompi_txn_id` (capturado de un
   webhook previo no-final), pollear `GET /v1/transactions/{txn_id}` y confirmar
   si APPROVED. Cubre el caso "llegó un webhook temprano, se perdió el final".
   Usa la función existente `get_transaction_with_resilience` (ya implementada,
   0 callers). Endpoint DOCUMENTADO. NO cubre webhooks 100% perdidos (sin txn_id).

Estado al 2026-06-26: **0 órdenes `pending_payment` en prod** → sin incidencia
actual. Medida preventiva; el runbook manual es suficiente a bajo volumen.

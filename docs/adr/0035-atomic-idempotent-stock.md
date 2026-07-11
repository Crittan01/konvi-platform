# ADR-0035 — BLOQUE C (item 4): Decremento/reposición de stock atómico e idempotente

- **Estado:** Aceptado (2026-07-11) — núcleo. Reforzado por revisión adversarial (14 agentes, 6 hallazgos → remediados). Continuación scopeada abajo.
- **Contexto:** El decremento de stock al confirmar (`_decrement_stock_on_confirm`, orders.py) y la
  reposición al cancelar (`order_cancellation.py`) eran **read-modify-write en 2-3 llamadas PostgREST
  separadas** (SELECT stock → UPDATE → INSERT movement), sin transacción ni idempotencia efectiva. El
  índice único `uq_stock_movements_order_variation_reason (order_id, variation_id, reason)` existía pero
  el código no lo usaba como guard → un retry Wompi tardío (3h/24h) re-confirmaba y **re-decrementaba**
  (inventario desinflado → falso 'sin stock'); y el read-modify-write podía perder decrementos concurrentes.

## Decisión
RPCs transaccionales `rpc_stock_decrement` / `rpc_stock_restore` (SECURITY DEFINER, tenant-scoped,
mismo patrón que `rpc_stock_reservation_consume`):
- **Guard de idempotencia:** INSERT del movement PRIMERO con
  `ON CONFLICT (order_id, variation_id, reason) WHERE order_id IS NOT NULL DO NOTHING RETURNING`. Si el
  movement ya existe (retry / webhook duplicado / reconciliación) → NO-OP TOTAL (no toca stock). Solo si
  el movement es nuevo se aplica el UPDATE. `FOR UPDATE` serializa concurrencia por variante.
- Enrutados: `_decrement_stock_on_confirm` (path directo, reason='sale') y el restore de cancelación
  (reason='cancellation_refund'). El path de reservas ya era atómico (`rpc_stock_reservation_consume`).

### Remediación de la revisión adversarial (6 hallazgos, todos corregidos)
1. **Clamp por el CHECK `stock_quantity >= 0`:** la premisa "permitir negativo" era FALSA — existe un CHECK
   activo (20260702150000). Un `v_new` negativo hacía fallar el UPDATE → ROLLBACK de toda la RPC (movement
   no persistía, stock intacto → revendible sin auditoría). Fix: `v_new := GREATEST(0, v_current - qty)` +
   `delta = v_new - v_current` (ledger consistente: `new_stock = old + delta`). El over-sell queda visible
   comparando order_items vs el movimiento.
2. **Agregación por variación (decremento):** la idempotencia por (order, variation, 'sale') colapsaba dos
   líneas de `order_items` de la MISMA variante → la 2ª era no-op y se perdía su qty (sub-decremento). Fix:
   sumar cantidades por variación antes de una única llamada por variación.
3. **Guard `order_id NULL`:** con order_id NULL el índice parcial no arbitra → sin idempotencia. Fix: RAISE
   explícito (la primitiva exige order_id).
4. **Restore completo:** el restore solo cubría `reason='reservation_consumed'` → una orden decrementada vía
   `'sale'` (manual/COD) NUNCA reponía stock al cancelar (inventario inflado). Fix: incluir `'sale'` + agregar.
5–6. (refutados / cubiertos por lo anterior).

## Consecuencias
- **Positivas:** cierra el doble-decremento por retry tardío, las races del read-modify-write, y la
  reposición incompleta/no atómica de la cancelación. El over-sell ahora registra movimiento + clampa a 0.
- **Riesgo:** medio — toca el money-path de confirmación. Sin regresión (gate verde, sin test del RMW viejo).

## ⚠️ Continuación scopeada (BLOQUE C item 4 — fases siguientes)
No incluidas en este núcleo (cada una su propio cambio verificado):
1. **MeLi oversell/restore:** venta MeLi que paga → decrementar inventario local (hoy no baja → el bot
   promete stock inexistente); cancelación MeLi → restore. Enrutar el path MeLi por `rpc_stock_decrement`/`restore`.
2. **patch_order timing:** decrementar en la PRIMERA transición desde pending/pending_payment (no solo en
   `→confirmed`).
3. **wompi guard status-regression:** ampliar `TERMINAL_STATES` para que un APPROVED tardío no regrese una
   orden `processing/shipped` a `confirmed` (issue de FSM de orden; el stock ya está protegido por la idempotencia).

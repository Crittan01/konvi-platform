# Flujo — Pago Wompi (ciclo completo del dinero)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Del link de pago a la confirmación, anulación, reembolso y reconciliación. Estado: **Wompi LIVE** (auditoría §4). Las validaciones de dinero son **fail-closed**: ante dato ambiguo, no se confirma — se deja para revisión manual.

---

## 1. Generación del link (validaciones pre-pago determinísticas)

Implementado en `services/ai-orchestrator/tools/payment_link_tool.py` → `handle_payment_link_if_applicable` (línea 337), invocado por el tool agéntico `agentic/tools/payment.py` y por el path legacy. Cadena de validaciones (todas determinísticas, cero LLM):

1. **Monto válido** — `total_in_cents` ≥ `WOMPI_MIN_AMOUNT_CENTS` y ≤ `WOMPI_MAX_AMOUNT_CENTS` (cap de sanidad); si no → `None` → fallback a humano (359-373).
2. **Gate `requires_requote`** — si el cart abierto/checkout tiene `requires_requote=True` (cliente cambió ítems/dirección tras cotizar) → **no se genera link** (375-405; defensa en el chokepoint compartido, ADR-0024). Ante fallo de DB en ESTE gate se degrada sin bloquear (404-405).
3. **Idempotencia por conversación** (407-506) — una conversación + cart abierto = una orden activa (`orders.status='pending_payment'`):
   - (a) link vigente ≤ TTL → **reutiliza** el mismo link (454-473).
   - (b) orden sin link vigente → **regenera sobre el mismo order_id** (475-498). Si la regeneración falla → degrada a handoff; Plan A.0.1 prohíbe orden duplicada (499-506).
   - (c) **monto stale (F42)**: si el monto vigente ≠ total actual del cart (cupón o carrier cambiaron después del link) → invalida la orden vieja y crea una nueva con el monto correcto (430-446).
4. **Reserva de stock** — `_reserve_checkout_stock` (238): `add_to_cart` ya creó reserva SOFT (15 min); el checkout **extiende** esas reservas a la ventana de 35 min y reserva fresco solo el delta no cubierto (evita doble-conteo que bloqueaba la última unidad, 248-253). Si hay insuficiencia → rollback de reservas frescas (255-256). Helper: `lib/stock_reservation.py`.
5. **TTL 30 minutos** — `WOMPI_LINK_TTL_MINUTES = 30` (45), espejo obligatorio de `services/api/routers/orders.py:WOMPI_PAYMENT_LINK_TTL_MINUTES` (comentario 39-43); el `expires_at` se envía a Wompi desde Core API.
6. **Credenciales**: `INTERNAL_SERVICE_SECRET` requerido para llamar a Core API (425-428); las llaves Wompi del tenant (`private_key`, `events_key`) viven en Vault (ver [`onboarding-tenant.md`](onboarding-tenant.md)).

**COD**: no genera link — ver [`venta-conversacional.md`](venta-conversacional.md) §7.

## 2. Webhook `transaction.updated` (confirmación)

`services/api/routers/wompi_webhook.py` (2.660 líneas). Diseño: **200 ACK inmediato + procesamiento async** (docstring líneas 6-7, endpoint en 44).

### 2.1 Inbox durable (antes del ACK)

- El payload **crudo** se persiste en `wompi_webhook_inbox` ANTES de responder 200 (70-86, `_persist_inbox` 94-110) — si el proceso muere post-ACK, el evento no se pierde: el worker lo re-drivea (§4.2).
- Idempotente por `signature.checksum`; sin checksum no hay clave de dedup → se omite la persistencia (96-98).
- Persistir pre-firma es deliberado (77-80): un atacante solo logra filas inertes (rate-limit + cleanup + rechazo en la verificación de firma del re-drive).

### 2.2 Verificación de firma

- Algoritmo: **SHA256 simple, no HMAC** (validado 2026-04-24, línea 13) vía `verify_event_signature` (de `api/integrations/wompi_client.py`).
- La `events_key` del tenant se carga desde Vault (314-316); un flake de Vault **propaga** (inbox sin procesar → reconcilia) en vez de degradar a firma inválida → pago perdido (W3-F1, 315-316).
- Firma inválida → log `firma_invalida` y descarte (321-322).

### 2.3 Dedup processed-aware

- Tabla `wompi_events_seen` con dedup por checksum (325-391). Wompi reintenta en 30m/3h/24h ante no-2xx (325-327).
- Distingue **"ya procesado"** (descarta, 377) de **"recibido sin procesar"** (crash previo → **REPROCESA**, 383) — sin esto, un crash mid-procesamiento sería irrecuperable (330-334).
- Si el chequeo de dedup falla → propaga para reconciliación (366-371).

### 2.4 Validación de monto/moneda — fail-closed

Antes de confirmar (paso 5b, 512-540; A11 audit 2026-06-25 + F16):

- Orden sin `total_amount` → **NO se confirma**, revisión manual (518-524).
- Monto cobrado ≠ monto esperado → **NO se confirma**, log `monto_mismatch`, revisión manual (529-531).
- Moneda ≠ COP → **NO se confirma** (538).

### 2.5 Guard de estado terminal + reconciliación de auto-cancel

- Si la orden ya está en estado terminal, un APPROVED tardío normalmente se rechaza (470); excepción BLOQUE A (456-508): si la orden fue **auto-cancelada por TTL** (worker, §4.3) y llega el APPROVED tardío → se **revierte el auto-cancel y se confirma** — única vía documentada de recuperar un webhook perdido. La validación de monto de §2.4 protege contra reconciliaciones erróneas (463-464).
- Replay del mismo webhook sobre orden confirmada → idempotente (475); pago **distinto** sobre orden confirmada = posible doble cobro → ERROR en logs + void automático si aplica, si no, refund manual (482-486).

### 2.6 Confirmación y notificaciones

1. Confirmar orden + descontar stock (543-551); si falla → propaga (inbox queda para re-drive idempotente).
2. WhatsApp al cliente vía outbound queue (553-566).
3. **Email etapa 1** "Pago recibido" (Resend, best-effort, 568-582) — sin tracking (la guía aún no existe).
4. **Auto-guía Aveonline** best-effort (584-596) — detalle en [`despacho-aveonline.md`](despacho-aveonline.md) §2.
5. Si guía OK → **email etapa 2 + WhatsApp** "Guía generada" con tracking (598-639).
6. Marcar evento procesado en `wompi_events_seen` (641-650).

Estados de orden: `pending | pending_payment → confirmed → processing → shipped → delivered | cancelled` (`services/api/routers/orders.py:11,51`).

## 3. Void / refund

- **Pagos huérfanos** (APPROVED sin orden que lo respalde): `_handle_orphan_payment` (159-229). Si es void-eligible (`is_void_eligible` — solo CARD pre-settlement) → `void_transaction_sync` con la private_key del tenant (200-215) → `payments.status='orphan_voided'`; NEQUI/PSE/Bancolombia **no admiten void** (fondos ya transferidos) → `'orphan_refund_pending'` → reembolso manual (183-185, 229). El void es best-effort: si falla, queda marcado para manual (224-226).
- **Cancelación de pedido** (`services/api/routers/orders.py`): cancelar mueve dinero (refund/void Wompi) e inventario → **solo owner/manager** (RBAC, comentario 404). Restock idempotente cross-path con reason único `'cancellation_refund'` e índice único `(order_id, variation_id, reason)` (449-451, 900-927) — dos caminos de cancelación nunca reponen dos veces.
- **Refund por reclamo** (`services/api/routers/claims.py`): transición a `refunded` **exige `refunded_amount`** real (BLOQUE G-2, 82-143) — sella monto + fecha para el KPI net-revenue; `refunded` es terminal y NUNCA reabrible (55); `rejected`/`cancelled` sí son reabribles (54). UI: `apps/web/app/dashboard/(sales)/claims/_components/reversion-panel.tsx`.
- **Auto-void post-cancel**: cuando la cancelación anula el pago en Wompi, el webhook `VOIDED` tardío notifica "reembolso completado" al cliente en vez de ofrecer retry (419-426).

## 4. Reconciliación — 3 capas

| Capa | Mecanismo | Evidencia |
|---|---|---|
| **1. Idempotencia en línea** | Inbox durable pre-ACK + dedup processed-aware + guard de estado terminal + validación de monto fail-closed | `wompi_webhook.py` §2.1-2.5 |
| **2. Re-drive del worker** | `services/ai-orchestrator/worker.py`: cada `WOMPI_INBOX_RECONCILE_INTERVAL_SECONDS` (default **180s**, 137-141) reclama lote vía RPC `claim_wompi_inbox_batch` (límite 20, `min_age`, `max_attempts`) y re-POSTea a `/api/v1/webhooks/wompi` (3303-3355). Flag `WOMPI_INBOX_RECONCILE_ENABLED` default `true`. Tras `MAX_ATTEMPTS` → dead-letter + métrica `wompi_inbox_dead_lettered`; gauge de backlog `wompi_inbox_depth` (3325-3326, 3356-3359) |
| **3. Reversión de auto-cancel** | APPROVED tardío sobre orden auto-cancelada por TTL revierte y confirma (§2.5) | `wompi_webhook.py:456-508` |

Higiene del inbox: RPC `cleanup_wompi_inbox` cada 6h — retención **7d procesadas / 30d dead-letter** (el payload crudo contiene PII del pagador, Ley 1581) (`worker.py:3290-3301`).

### 4.3 Auto-cancel de órdenes `pending_payment` expiradas

Job del worker `release_pending_payment` (`worker.py:535`, `_release_expired_pending_payment_orders` 3368): cancela las `pending_payment` vencidas (TTL) y libera las reservas — como el stock aún no se descontó, cancelar no requiere restock (3373). Si el "cancel" falla porque el pago llegó entre medio → NO se cancela, queda para reconciliar (3453). Log: "Pedidos pending_payment expirados cancelados: N (TTL=Xmin)" (3543).

## 5. Pérdida total de webhook → runbook manual

- Si Wompi **nunca** entrega el webhook (no llegó ni al inbox), no hay reconciliación automática posible — **limitación del proveedor, documentada** (hallazgo M4 de la auditoría). El comentario en `wompi_webhook.py:293-302` lo prevé: evento sin link correlacionable queda logueado claro "para reconciliación manual con dashboard Wompi".
- Señales operativas para detectar: órdenes `pending_payment` que el cliente afirma haber pagado (inbox Wompi dashboard vs Konvi), gauge `wompi_inbox_depth`, dead-letters.
- Runbook (derivado del código): ① verificar pago en dashboard Wompi **[EXTERNO]**; ② si existe APPROVED y la orden sigue `pending_payment`/auto-cancelada → re-POST manual del evento al endpoint (el pipeline completo de §2 aplica: firma, dedup, monto, confirmación) o corrección manual de la orden por owner; ③ si es huérfano → flujo §3.

---

### Archivos clave

| Pieza | Archivo |
|---|---|
| Generación link | `services/ai-orchestrator/tools/payment_link_tool.py` |
| API órdenes/TTL/cancel | `services/api/routers/orders.py` |
| Webhook | `services/api/routers/wompi_webhook.py` |
| Cliente Wompi (firma/void) | `services/api/integrations/wompi_client.py` |
| Re-drive + auto-cancel + cleanup | `services/ai-orchestrator/worker.py` (137-141, 535, 3290-3360, 3368-3543) |
| Refunds por reclamo | `services/api/routers/claims.py` |
| Reservas stock | `services/ai-orchestrator/lib/stock_reservation.py` |

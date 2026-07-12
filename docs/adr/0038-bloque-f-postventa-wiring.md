# ADR-0038 — BLOQUE F post-venta: sync de estado de pedido + alerta al operador (F-6/F-7)

- **Estado:** Aceptado (2026-07-11). Implementado en este PR (`services/api/routers/aveonline_webhook.py`, code-only, sin migración). Reforzado por revisión adversarial (11 agentes, 4 dimensiones → 5 hallazgos confirmados, todos resueltos o diferidos con registro).
- **Contexto:** El webhook de Aveonline (`webhookEstadosGuias`) persistía `shipment_tracking_events` + `shipments.status` y notificaba al **cliente** (WhatsApp + email) en `in_transit`/`delivered`/`exception`. Dos huecos post-venta quedaban abiertos tras F-1..F-5:
  - **F-6:** una guía `delivered` actualizaba `shipments.status` pero **nadie** avanzaba `orders.status` → el pedido quedaba en `shipped` para siempre (dashboard, analytics y estado que ve el bot desincronizados de la realidad física).
  - **F-7:** una **novedad** (`exception`) solo notificaba al cliente y una **devolución** (`returned`) solo dejaba un `logger.info` → el **operador** nunca se enteraba de un envío que exige su acción (contactar cliente, reintentar, gestionar devolución).

## Decisión 1 — F-6: sync forward-only de `orders.status` a `delivered`

`_advance_order_to_delivered(supabase, tenant_id, order_id, current_status)` avanza el pedido a `delivered` cuando el envío se entrega. Propiedades:

- **Monotónico / forward-only:** espejo del rank canónico de `meli_webhook._STATUS_RANK` (coherencia cross-connector). Solo avanza desde `confirmed`/`processing`/`shipped` (rank 1..3). El guard temprano (`rank(current) >= rank(delivered)`) hace no-op sobre estados terminales (`delivered`/`cancelled`) sin tocar la DB.
- **Race-safe:** el UPDATE re-filtra en SQL con `.in_("status", advanceable)` + `.eq("tenant_id")` → dos webhooks concurrentes no re-escriben ni regresan un terminal (ADR-0025).
- **Exclusión deliberada de `pending`/`pending_payment` (rank 0):** representan pedidos **prepago impagos**; marcarlos `delivered` ocultaría el impago. **No afecta contraentrega:** un pedido COD nace `confirmed` ([orders.py:248](../../services/api/routers/orders.py#L248)) y un prepago pagado pasa a `confirmed` por el webhook Wompi → ambos caen dentro del rango advanceable. Verificado durante la revisión (la hipótesis "gap COD" se refutó con el código).
- **Ubicación (durabilidad — hallazgo LOW de la revisión):** el avance vive en `_handle_aveonline_webhook`, llamado **incondicional** cuando `latest_internal == 'delivered'`, NO dentro del dispatch de notificación (que solo corre en la transición). Si el UPDATE fallara una vez, el guard de transición (shipment ya terminal) nunca re-invocaría el dispatch → el pedido quedaría colgado en `shipped`. Al ser idempotente, ponerlo en el flujo incondicional **auto-sana** en cualquier webhook `delivered` posterior.

## Decisión 2 — F-7: alerta al operador (Telegram) en `exception`/`returned`

`_alert_operator_shipment_issue(...)` alerta al operador por el **mismo canal** por el que llegan los escalamientos humanos (`notification_settings` `channel='telegram'`, `enabled=true`; `chat_id` en `config.chat_id`, canónico). Reusa `telegram_webhook._send_telegram_reply` (resuelve el `bot_token` del tenant vía Vault, scoped al mismo `tenant_id` → sin fuga cross-tenant). Best-effort: cualquier fallo se loguea, no rompe el ACK 200 del webhook.

- **Independiente de `conversation_id` (hallazgo HIGH de la revisión, resuelto):** la alerta al operador NO puede depender de que exista una conversación WhatsApp — un pedido MeLi/consola (sin conversación) igual necesita gestión del operador. El guard `conversation_id` envuelve **solo** el dispatch al cliente; la alerta al operador es incondicional (paridad con el branch `returned` y con F-6).

## Decisión 3 — Orden cronológico del historial (hardening del guard de F-7)

`_handle_aveonline_webhook` ahora procesa `estado[]` **ordenado ascendente por `fecha`** antes del loop. Aveonline manda historial sin orden garantizado (dossier §6.2) y el RPC hace last-write-wins entre no-terminales → iterar en orden de array podía dejar `shipments.status` **regresado**, y el guard de dedup del que depende F-7 (`latest_internal != prev_status`) misfirear. Ordenar asc → el evento más reciente se procesa último y gana (misma key que `_select_latest_estado`).

## Diferido → RESUELTO (cierre 2026-07-12)

- **RPC time-aware (hallazgo MEDIUM) — ✅ RESUELTO.** Migración `20260712040000_g_shipment_status_monotonic.sql`: se añadió `shipments.status_occurred_at` + guard monotónico en `fn_record_shipment_tracking_event` (`... AND (status_occurred_at IS NULL OR p_occurred_at IS NULL OR p_occurred_at >= status_occurred_at)`) → un evento MÁS VIEJO ya no pisa el status fijado por uno más nuevo, ni entre POSTs concurrentes. Backfill best-effort del último `occurred_at` por shipment. Smoke-test ROLLBACK OK.
- **Reconciliación de `delivered` de un solo disparo — ✅ CERRADO (sin cron).** Verificado en prod: `shipments.status='delivered'` con pedido aún en `{confirmed,processing,shipped}` = **0 filas**. Además la Decisión 1 (F-6) avanza el pedido en el flujo INCONDICIONAL del handler → auto-sana en CUALQUIER webhook `delivered` posterior (Aveonline reenvía historial). Un cron para 0 filas sería infra muerta; se cierra como cubierto por F-6 + verificación empírica. Si a futuro aparecieran filas rezagadas, la query de detección queda documentada aquí.

## Consecuencias

- Pedidos entregados se reflejan como `delivered` en toda la superficie (dashboard/analytics/bot). Novedades y devoluciones dejan de ser invisibles para el operador.
- Sin migración, sin cambio de contrato externo, sin regresión (gate `validate.sh --ci` verde; `tests/test_shipment_postventa_wiring.py`, 17 casos).
- Deuda registrada arriba (2 ítems diferidos), ninguno bloqueante para producción.

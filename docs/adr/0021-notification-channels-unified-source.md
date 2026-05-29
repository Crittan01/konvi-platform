# ADR-0021 — Notificaciones a operador: fuente única `notification_settings` (deprecación path A)

**Estado:** ACEPTADO + IMPLEMENTADO (rev. 109 commit `eb30a74`).
**Fecha:** 2026-05-28.
**Branch:** `phase-2-agentic-rewrite`.
**Tabla deprecada para canales:** `tenant_integrations.provider='telegram'`.

## Contexto

El sistema tenía **dos fuentes paralelas** para resolver "dónde notificar al operador del tenant" cuando el bot escala humano o crea evento crítico:

| Fuente | Consumidor | Disparo |
|---|---|---|
| `tenant_integrations.provider='telegram'` (path A) | `notify_escalation_async` en `telegram_notifications.py` | Inline desde tool (`escalate_to_human`, `create_claim`) |
| `notification_settings.channel='telegram'` (path B) | `dispatch_human_takeover_event` en `notifications.py` | Async vía pgmq + DB trigger `conversations_human_takeover_queue_trigger` |

**Riesgo arquitectónico previo:**

1. **Divergencia silente**: tenant podía configurar SOLO una de las dos. Si configuraba path A → path B fallaba (worker no encontraba). Si configuraba path B → path A fallaba (tool inline encontraba 0 rows).
2. **Caso real KAIU**: tenía solo path B. Path A devolvía 0 rows y caía silente. Toda notif inline desde tools (incluyendo `create_claim` nuevo) no llegaba al operador.
3. **Bug histórico oculto**: aún con path A correctamente configurado, `_send_telegram_notification` (notifications.py:46) espera keys `bot_token` / `chat_id`. El código de path A pasaba `telegram_bot_token` / `telegram_chat_id` → la función fallaba con "Telegram habilitado pero incompleto" y retornaba True silente. Path A NUNCA envió Telegram aunque tuviera config.

## Decisión

**`notification_settings` es la ÚNICA fuente de verdad** para canales operacionales (telegram, email, slack futuro).

`notify_escalation_async` se refactoriza para leer de `notification_settings` con el mismo patrón que `dispatch_human_takeover_event` (path B). El bug de naming se corrige al unificar.

### Cambios en código (rev. 109)

- `services/ai-orchestrator/telegram_notifications.py:50-110` — query a `notification_settings`, resolución bot_token vía Vault (`bot_token_secret_id`), config keys correctas (`bot_token`, `chat_id`).
- Test `TestNotificationSourceUnified` verifica `inspect.getsource(notify_escalation_async)` NO contiene `"tenant_integrations"`.

### Lo que NO cambia

- `tenant_integrations` se PRESERVA en DB y código (uso para credenciales de providers de negocio: WhatsApp, MercadoLibre, Wompi, Envia, Aveonline). **Solo se deprecó el provider='telegram'**.
- Path B (DB trigger → pgmq → worker → `dispatch_human_takeover_event`) sigue activo en paralelo. Defensa en profundidad: si el path A inline falla, path B respalda. Ambos consumen la misma `notification_settings` ahora.

## Compat + plan de deprecación

**Fase 1 — rev. 109 commit `eb30a74`** ✅ DONE:
- Código refactorizado. KAIU funcionando con `notification_settings` única.

**Fase 2 — D+30 (~2026-06-27)**:
- Audit: query `SELECT COUNT(*) FROM tenant_integrations WHERE provider='telegram'`. Si 0 → seguro proceder a Fase 3. Si >0 → migrar primero a `notification_settings` (script semi-automático: lee `meta.chat_id` + `credentials.bot_token_secret_id` → upsert `notification_settings`).
- Validación con cada tenant afectado antes de drop.

**Fase 3 — D+60 (~2026-07-27)**:
- Migration aditiva: `DELETE FROM tenant_integrations WHERE provider='telegram'`. NO se dropea la tabla (otros providers la siguen usando).
- ADR este se marca CERRADO.

## Acciones humanas pendientes

| # | Acción | Responsable | Cuándo |
|---|---|---|---|
| A1 | Verificar que todos los tenants productivos tienen `notification_settings.channel='telegram'` configurado | Founder + CS | D+30 |
| A2 | Si hay tenants legacy en `tenant_integrations.provider='telegram'`, migrar via script | DevOps | D+30 |
| A3 | Ejecutar migration Fase 3 (delete rows path A) | DevOps | D+60 |

## Justificación

1. **Single source of truth**: imposible que las 2 fuentes divergen porque solo existe 1.
2. **Patrón unificado**: `notify_escalation_async` y `dispatch_human_takeover_event` leen la misma tabla con el mismo helper `resolve_secret`. Cambios futuros (rotación token, nuevo channel) tocan 1 sola fuente.
3. **Bug histórico cerrado**: el naming `telegram_bot_token` quedó eliminado en la refactorización. No vuelve a aparecer.
4. **Defense in depth preservada**: path B sigue activo (DB trigger + worker) como segundo canal para escalaciones críticas (`status='human_takeover'`).
5. **Coherente con UI**: Settings → Canales (UI Tenant Console) edita `notification_settings`, no `tenant_integrations`. La fuente que se ve en UI ahora coincide con la que el código lee.

## Riesgos residuales

- **Tenant con notification_settings sin bot_token resuelto a Vault**: notif retorna False (logueado, no crashea). Mitigación: validación en endpoint `POST /api/v1/notifications/test` (no implementado todavía, backlog).
- **Latencia adicional path A vs path B**: path A es síncrono inline en el tool (~300ms POST telegram.org). Path B es async (worker poll). Aceptable.

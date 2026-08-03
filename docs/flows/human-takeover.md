# Flujo — Human Takeover (escalación bot → operador → retorno al bot)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Cómo una conversación sale del bot, llega a un humano y vuelve al bot. Regla de voz verificada en el propio tool (`agentic/tools/escalation.py:7-12`): de cara al cliente **SIEMPRE "especialista", nunca "asesor humano"** — el cliente no debe percibir que habla con un bot. Internamente el estado es `human_takeover` (compat DB/orchestrator).

---

## 1. Vías de escalación (4 verificadas + gates)

### 1.1 Tool explícita `escalate_to_human`

`services/ai-orchestrator/agentic/tools/escalation.py` (ADR-0018):

- Args: `reason` obligatorio, 10-300 chars (`EscalateToHumanArgs`) — el prompt del tool restringe cuándo escalar: (a) cliente pide especialista explícitamente, (b) reclamo que requiere intervención, (c) fuera de scope (refund manual, etc.); **NO** escalar lo que otras tools resuelven.
- Efecto: `UPDATE conversations SET status='human_takeover'` con filtro `tenant_id` (multitenant seguro). La razón se persiste como audit en `messages.payload`/cart_events (la tabla `conversations` no tiene `escalation_reason`).
- Notifica al equipo (Telegram, §2) — best-effort, la escalación no depende de la notificación.

### 1.2 Invariant anti "fake escalation"

`services/ai-orchestrator/agentic/invariants/fake_escalation.py` — bug runtime founder 2026-05-28: el LLM "actuaba" la escalación lingüísticamente ("te paso con un especialista") **sin invocar el tool** → cliente colgado, nadie notificado.

Defensa en profundidad: si el texto candidato contiene frase de escalación y el `tool_call_log` NO incluye `escalate_to_human` → el invariant **ejecuta la escalación real**: ① UPDATE status, ② INSERT audit con reason, ③ Telegram best-effort. El texto se mantiene (la promesa al cliente ahora sí está respaldada). "Si el LLM dice 'te paso con un especialista', el cliente SIEMPRE recibirá atención humana."

### 1.3 Degraded path (fallos del agente)

`agentic/dispatcher.py:_emit_degraded_response_and_escalate` (línea 343):

- **1er fallo** de la conversación en ventana de 10 min → mensaje natural invitando a reintentar, **NO escala** (la mayoría de crashes son transitorios: saturación LLM, edge cases).
- **2º fallo consecutivo** del mismo cliente en <10 min → `human_takeover` + notificación Telegram (patrón crítico, no transitorio).

### 1.4 Silent escalation

`dispatcher.py:3136-3141, 3253-3259`: cuando el resultado del agente trae `requires_silent_escalation=True`, el `outbound_text` es el mensaje natural al cliente y el dispatcher ejecuta la escalación con reason — el cliente no percibe el corte.

### 1.5 Gates de compliance que también escalan

DSR/Habeas Data y ciertos paths de seguridad derivan a humano (ver [`opt-out-habeas-data.md`](opt-out-habeas-data.md) §3). Además el flag `agentic_enabled` es fail-closed: error transitorio de lectura del flag = escalación (hallazgo M11).

## 2. Notificación Telegram al operador

`services/ai-orchestrator/telegram_notifications.py`:

- `notify_escalation_async` (37): invocación inline desde el dispatcher/tool; lee `notification_settings` del tenant; el bot token se resuelve desde Vault (110).
- `dispatch_human_takeover_event` (en `notifications.py:286`): variante async vía cola pgmq — misma configuración.
- Self-heal del binding chat→tenant: la notificación mantiene vivo el mapeo para que `/resolver` y `/estado` funcionen desde ese chat (101-102).
- **Gap M17**: el `setWebhook` de Telegram es **manual por tenant** (ver [`onboarding-tenant.md`](onboarding-tenant.md) §4).

## 3. Inbox del operador (consola web)

- **Señal**: badge rojo en el sidebar con el conteo de `conversations.status='human_takeover'` no archivadas (`apps/web/app/dashboard/layout.tsx:90` query; render `sidebar-client.tsx:319-323`, cap "99+"). **Gap M1**: el badge NO existe en el bottom-nav móvil (ver `docs/ux/UX-UI.md` §6.1).
- **Deep-link**: `/dashboard/inbox?status=human_takeover` siembra el filtro one-shot (`inbox-manager.tsx:82-101`).
- **Filtros**: `active` = bot_active + human_takeover; `sla_breach` = human_takeover sin respuesta humana ≥ `SLA_BREACH_HOURS` (`inbox-manager.tsx:111-113` + `_lib/format.isSlaBreach`).
- **Atención**: 3 paneles (lista/chat/contexto) con máquina de vistas móvil; envío de mensaje con `Idempotency-Key` scope `conversations.send`, timeout 90s, insert optimista; cambio de estado con scope `conversations.status` + retry 503 (`inbox-manager.tsx:217-317`). El backend es `services/api/routers/conversations.py` (`PATCH /api/conversations/{id}/status`, `POST .../send`).
- El bot no responde mientras dura el takeover: `human_takeover ∈ _SKIP_STATUSES` (`dispatcher.py:3618`).

## 4. Retorno al bot

Dos vías verificadas:

1. **Comando Telegram `/resolver {conversation_id}`** — `services/api/routers/telegram_webhook.py`: restaura `bot_active` (docstring línea 7, dispatch 222-223, handler `_cmd_resolver` 236). **Seguridad multi-tenant** (104-106): el comando valida el binding chat→tenant — un operador del tenant B no puede mutar conversaciones del tenant A. `/estado` también disponible (229).
2. **Consola**: el operador cambia el estado desde el chat del Inbox (mismo `PATCH /status` de §3) → la conversación vuelve a `bot_active` y el próximo inbound entra al dispatcher normalmente.

Secuencia completa:

```text
Trigger (tool | invariant fake-escalation | degraded ×2 | silent | gate DSR)
  → conversations.status='human_takeover' (+audit reason)
  → Telegram al chat operador (inline o pgmq; token Vault)
  → Badge sidebar + filtro human_takeover en Inbox
  → Operador responde (idempotente, optimista) — bot en skip
  → /resolver {conv_id} (Telegram) o cambio de estado (consola)
  → status='bot_active' → el bot retoma el próximo inbound
```

---

### Archivos clave

| Pieza | Archivo |
|---|---|
| Tool escalación | `services/ai-orchestrator/agentic/tools/escalation.py` |
| Invariant fake-escalation | `services/ai-orchestrator/agentic/invariants/fake_escalation.py` |
| Degraded + silent | `services/ai-orchestrator/agentic/dispatcher.py` (343, 3136-3259) |
| Notif Telegram | `services/ai-orchestrator/telegram_notifications.py`, `notifications.py` |
| Comandos /resolver /estado | `services/api/routers/telegram_webhook.py` |
| API conversaciones | `services/api/routers/conversations.py` |
| Inbox operador | `apps/web/app/dashboard/inbox/_components/inbox-manager.tsx` |
| Badge sidebar | `apps/web/app/dashboard/sidebar-client.tsx:319-323`, `layout.tsx:90` |

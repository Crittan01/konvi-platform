# Baseline programático — Refactor Inbox monolito

**Fecha:** 2026-05-29.
**Branch:** `refactor/inbox-components` (rama dedicada, rebased sobre `phase-2-agentic-rewrite` post-fixes urgentes).
**Commit base:** `ee4e707` (`fix(rev109-build-baseline): tres bugs latentes que rompían next build`).

## Métricas pre-refactor

| Métrica | Valor |
|---|---|
| LOC monolito `apps/web/app/dashboard/inbox/page.tsx` | **2341** |
| Hash MD5 monolito | `31b40037201a9b0918cc5645c9c00e6d` |
| Tests backend que cubren Inbox | **156 passed, 6 subtests** (suite Inbox completa) |
| `next build` (producción) | ✅ **PASS** (post fix commit `ee4e707`) |
| TypeScript strict (`--noEmit`) | ✅ PASS |

## Hallazgo crítico del baseline

3 bugs latentes detectados durante validación:

1. `agents-list.tsx:160` — iteración Set rota (mi commit 44d0598)
2. `inbox/page.tsx:341` — iteración Map rota (mi commit 6f76f24)
3. `integrations/page.tsx:22` — `meli_same_user` faltante en type (pre-existente)

Corregidos en commit `ee4e707`. **Sin este baseline el refactor habría comenzado sobre código que NO compilaba para producción.**

## Tests backend que sirven como red de seguridad post-refactor

| Suite | Cobertura |
|---|---|
| `tests/test_api_conversations_contract.py` | API contract: list, stats, status updates, legacy rejection |
| `tests/test_tenant_isolation_inbox.py` | Multi-tenant: list, get, messages, status, send, context (cross-tenant prevention) |
| `tests/test_orchestrator_takeover.py` | Bot respeta human_takeover, closed handling, escalación |
| `tests/test_send_message_24h_window.py` | Meta ventana 24h: WINDOW_EXPIRED, WINDOW_NO_INBOUND |
| `tests/test_whatsapp_optout.py` | Detector STOP/BAJA/CANCELAR + 8 patrones |
| `tests/agentic/test_rev109_uat_regression.py` | FSM state machine + tools subset |
| `tests/agentic/test_rev109_p0_p1_certified.py` | rev109: persona, cupones, fallback, opt-out gate, fake_escalation, SLA, claims, notif unificada |

**Criterio**: tras cada paso del refactor, esta suite debe seguir verde.

## Gaps cubiertos sólo manualmente (sin test automatizado)

19 funcionalidades identificadas por el agente de cobertura. Las más críticas — el operador debe **smoke-checkear manualmente** post-refactor:

### Bloque 1: data flow crítico
1. Realtime mensajes (<2s desde insert hasta UI)
2. Realtime conversations (status updates aparecen en lista lateral)
3. Polling fallback (5s mensajes / 20s convs / 5s context)
4. URL sync `?conv=ID` (refresh restaura selección)
5. Dedupe Realtime + polling (no duplicar mensajes)

### Bloque 2: UI features rev109
6. Group-by-phone con expand chevron
7. SLA breach badge ⏰ + filtro
8. Filtro "Activas" default
9. Agentic state badges (Saludo/Carrito/Pago/etc.)
10. Unread badge (last_read_at)
11. Toggle "Ver archivadas"

### Bloque 3: acciones operador
12. Tomar control / Volver al bot (PATCH status)
13. Enviar mensaje + 24h window
14. Editor WhatsApp toolbar (B/I/S/code/quote/lists/Ctrl+B,I,E)
15. Mini-form crear pedido (variantes + cantidades + envío)
16. Idempotency en send (doble click no duplica)

### Bloque 4: rendering
17. Phone formatting Colombia
18. Load more mensajes (cursor pagination)
19. Mobile view 3-paneles (list/chat/context)

## Plan de extracción (10 pasos)

Definido por el workflow multi-agente. Ver mensaje del founder + workflow output. Cada paso = 1 commit aislado + verificación.

| # | Riesgo | Extrae |
|---|---|---|
| 1 | 🟢 | `_lib/{types,constants,format,editor}.ts` |
| 2 | 🟢 | `page.tsx` thin Server + `_components/inbox-manager.tsx` Client |
| 3 | 🟢 | `chat-editor-toolbar.tsx` |
| 4 | 🟡 | `order-mini-form.tsx` |
| 5 | 🟡 | `_hooks/use-conversation-context.ts` |
| 6 | 🟡 | `context-panel.tsx` |
| 7 | 🔴 | `_hooks/use-conversations.ts` (Realtime+URL sync) |
| 8 | 🟡 | `conversation-list.tsx` |
| 9 | 🔴 | `_hooks/use-messages.ts` (Realtime+dedupe+pagination) |
| 10 | 🟡 | `chat-panel.tsx` (última pieza) |

## Criterio de éxito final

Post paso 10:
- LOC `page.tsx` ≤ 60 (Server Component thin)
- LOC `inbox-manager.tsx` ≤ 600 (orquestador)
- Total LOC inbox/ comparable (~2200, distribuido en archivos focales ~50-500 LOC c/u)
- `next build` ✅ verde
- Suite tests ✅ 156+ verde
- Manual smoke ✅ 19 escenarios baseline reproducibles

# Flujos de Negocio — Índice

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Flujos de negocio verificados contra el código que los implementa (regla: cero suposición — cada paso cita sus archivos clave). Cubren el ciclo completo: cliente WhatsApp → venta → pago → despacho → post-venta, más los flujos de gobierno del tenant.

| Flujo | Documento | Servicios clave |
|---|---|---|
| **Venta conversacional** | [`venta-conversacional.md`](venta-conversacional.md) | `services/ai-orchestrator/agentic/` (dispatcher, FSM, tools), `services/api/routers/` |
| **Pago Wompi** | [`pago-wompi.md`](pago-wompi.md) | `services/ai-orchestrator/tools/payment_link_tool.py`, `services/api/routers/wompi_webhook.py`, `services/ai-orchestrator/worker.py` |
| **Despacho Aveonline** | [`despacho-aveonline.md`](despacho-aveonline.md) | `services/api/routers/shipping.py`, `wompi_webhook.py`, `aveonline_webhook.py` |
| **Human takeover** | [`human-takeover.md`](human-takeover.md) | `agentic/tools/escalation.py`, `agentic/invariants/fake_escalation.py`, `telegram_notifications.py`, `api/routers/telegram_webhook.py`, Inbox |
| **Onboarding de tenant** | [`onboarding-tenant.md`](onboarding-tenant.md) | `apps/web/app/dashboard/(settings-group)/`, `services/api/routers/integrations.py` |
| **Opt-out y Habeas Data** | [`opt-out-habeas-data.md`](opt-out-habeas-data.md) | `agentic/dispatcher.py`, `lib/whatsapp_optout.py`, `safety/consent_gates.py`, `api/routers/data_subject_request.py` |

## Cómo leer estos documentos

- Cada paso del flujo cita el archivo (y cuando aplica, la línea) que lo implementa. Si el código y un doc discrepan, **el código manda**.
- Lo no verificable desde el repo se marca **[DECLARADO]** o **[EXTERNO]** (p. ej. comportamiento del proveedor).
- Estado de producción al 2026-08-02 según `.audit/findings/2026-08-02-consolidated-audit.md`:
  - Wompi: **LIVE** (reconciliación 3 capas). Telegram: **LIVE**. Meta WhatsApp Model B: **LIVE**.
  - Aveonline: **PARCIAL** — cotización live; generación de guías en dry-run (`AVEONLINE_GENERATE_REAL_GUIDES=false`, bloqueante B1); webhook de estados implementado.
  - COD (contraentrega): implementado en el flujo del bot; H.2.4 (logística COD avanzada) pausado formal (KYC Ecart Pay + DANE).

## Mapa de servicios

```text
Cliente WhatsApp ──► connector-whatsapp (webhook Meta, HMAC per-tenant)
                   ──► ai-orchestrator (gates → FSM → LLM+tools → outbound pgmq)
                   ──► api (Core Gateway: orders, shipping, webhooks Wompi/Aveonline)
                   ──► Operador: apps/web Inbox + Telegram (/resolver, /estado)
```

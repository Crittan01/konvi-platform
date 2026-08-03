> **⚠️ ARCHIVADO — 2026-08-03.** Contenido histórico superado, conservado solo como registro. Estado vigente: docs/PLAN.md y .context/01-state.md.

---

# Flujo Conversacional de Pedido — Diagrama de Estados

Última actualización: 2026-04-23
Estado: documento de preparación para Fase C (pagos/Wompi)

> **Restricción**: Este documento describe el diseño objetivo. La implementación runtime de
> Fase C (crear pedido desde bot + link de pago + webhook Wompi) está bloqueada hasta que
> se cumplan los gates definidos en `.context/04-next-steps.md`.

> **Verificado 2026-08-02**: shipping real = Aveonline como único provider (Envia eliminado
> del runtime en rev. 109, ADR-0019). Cotización vía `cotizarDoble` multi-carrier
> (`services/api/integrations/aveonline_client.py`). Generación de guía automática post-pago
> en el webhook Wompi (`services/api/routers/wompi_webhook.py::_generate_shipping_guide`),
> hoy en dry-run (`simulate=True`) salvo flag `AVEONLINE_GENERATE_REAL_GUIDES=true`.

---

## 1. Estados de Conversación del Bot (runtime actual)

```text
[INICIO] ──mensaje inbound──► bot_active
                                │
                                ├─── shipping_quote_tool ───► responde cotización real
                                │                              (Aveonline cotizarDoble
                                │                               multi-carrier)
                                │
                                ├─── order_status_tool ─────► responde estado real de pedido
                                │                              (orders por conversation/contact)
                                │
                                ├─── smalltalk determinístico ─► saludo/agradecimiento
                                │
                                ├─── FSM contextual de venta ───► ver §2
                                │
                                └─── LLM (Gemini) + guardrails ─► respuesta asistida
                                │
                                ▼
                    human_takeover  ◄── escalamiento automático
                         │
                    closed  ◄── cierre manual por operador
```

### Estados canónicos (`conversations.status`)

| Estado | Significado | Bot responde |
|---|---|---|
| `bot_active` | Bot puede responder automáticamente | Sí |
| `human_takeover` | Operador humano tomó control | No |
| `closed` | Conversación cerrada definitivamente | No |

---

## 2. FSM Contextual de Venta (prompt-level, rev. 56)

La FSM solo se activa cuando `_has_buying_intent()` detecta intención de compra real.
En modo consulta pura (precio/stock/variante) se suprime para no presionar al usuario.

```text
                    ┌─────────────────────────────────────────┐
                    │           MODO CONSULTA                 │
                    │  (sin buying intent detectado)          │
                    │  → Solo responde catálogo/KB            │
                    │  → NO pide datos personales             │
                    └─────────────────────────────────────────┘
                                    │ buying intent detectado
                                    ▼
                           ┌────────────────┐
                           │  NEEDS_CONSENT │
                           │  (1/4)         │
                           └───────┬────────┘
                                   │ consent_given = true
                                   ▼
                           ┌────────────────┐
                           │  NEEDS_NAME    │
                           │  (2/4)         │
                           └───────┬────────┘
                                   │ name capturado
                                   ▼
                           ┌────────────────┐
                           │ NEEDS_DIRECTION│
                           │  (3/4)         │
                           └───────┬────────┘
                                   │ address completa
                                   ▼
                           ┌────────────────┐
                           │ READY_FOR_SUMMARY│
                           │  (4/4)           │
                           └───────┬──────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────────────┐
                    │  Resumen + confirmación + escalamiento  │
                    │  a humano para link de pago (Fase C)    │
                    └─────────────────────────────────────────┘
```

### Reglas de transición

1. **Recuperación de contexto**: si el usuario cambia de tema abruptamente (ej: estaba dando dirección y ahora pregunta por otro producto), el bot abandona la FSM y responde la nueva consulta.
2. **Extracción inteligente**: si el usuario da nombre + dirección en un solo mensaje, el bot extrae AMBOS y salta al Paso 4 sin obligar paso a paso.
3. **Stall**: ≥2 rondas de desambiguación sin resolver → `requires_human=True`.

---

## 3. Flujo transaccional objetivo (Fase C — Wompi)

```text
Cliente confirma producto + cantidad + opción de envío
        │
        ▼
Bot: resumen del pedido (productos + envío = total)
        │
        ▼
Bot solicita: nombre + dirección de entrega
        │
        ▼
Sistema: crea Order en DB
        ├── status = pending_payment
        ├── stock reservado (no descontado definitivo)
        └── reservation_ttl = 30 minutos (propuesta)
        │
        ▼
Sistema: genera link de pago Wompi sandbox
        ├── POST https://sandbox.wompi.co/v1/payment_links
        └── requiere: WOMPI_PUBLIC_KEY + WOMPI_PRIVATE_KEY por tenant
        │
        ▼
Bot: envía link de pago al cliente vía WhatsApp
        │
        ├─── [Cliente paga] ───► Webhook Wompi: transaction.updated
        │                              │
        │                              ▼
        │                    Sistema valida firma (x-event-checksum)
        │                              │
        │                              ▼
        │                    Order status = confirmed
        │                    Stock descontado definitivamente
        │                    Bot: "Pago confirmado. Pedido #XXX listo."
        │                              │
        │                              ▼
        │                    Sistema: genera guía Aveonline automática post-pago
        │                              (dry-run simulate=True; guías reales con flag
        │                               AVEONLINE_GENERATE_REAL_GUIDES=true)
        │
        └─── [No paga en 30 min] ───► release_order_tool
                                      ├── Libera reserva de stock
                                      └── Bot: "Tu reserva expiró. ¿Deseas reactivarla?"
```

---

## 4. Estados de orden en flujo conversacional

| Estado | Significado | Stock | Notas |
|---|---|---|---|
| `pending_payment` | Pedido creado, esperando pago | Reservado | Nuevo estado para Fase C |
| `confirmed` | Pago confirmado | Descontado | Transición actual: pending → confirmed |
| `processing` | En preparación | Descontado | |
| `shipped` | En camino | Descontado | |
| `delivered` | Entregado | Descontado | |
| `cancelled` | Cancelado | Liberado | |

---

## 5. Componentes a construir (Fase C)

| Componente | Tipo | Descripción |
|---|---|---|
| `create_order_tool` | Tool determinística | Crea orden desde orquestador con stock reservado |
| `payment_link_tool` | Tool determinística | Genera link de pago Wompi sandbox/prod |
| `release_order_tool` | Job/Cron | Libera reservas expiradas (TTL) |
| `POST /api/v1/webhooks/wompi` | Endpoint API | Recibe y valida eventos Wompi |
| `payments` (tabla DB) | Migración | Traza intentos de pago, reembolsos |
| `stock_reservations` (tabla DB) | Migración opcional | Reservas independientes de stock |

---

## 6. Gates de entrada Fase C

Ver `.context/04-next-steps.md` para checklist completo.

Resumen:
1. [ ] Fase B certificada con UAT ≥ 95%
2. [ ] Validar política Wompi sandbox (COP, montos mínimos, fees)
3. [ ] Tenant con cuenta Wompi activa / sandbox
4. [ ] Definir TTL de reserva (propuesta: 30 min)
5. [ ] Revisión legal términos de compra vía WhatsApp
6. [ ] `docs/integrations/wompi.md` creado
7. [ ] `docs/operations/order-flow-conversational.md` creado ✅

---

## Referencias

- `.context/04-next-steps.md` — gates y estado de Fase C
- `docs/integrations/wompi.md` — contrato técnico Wompi (la prep histórica `wompi-prep.md` está archivada en `docs/_archive/integrations/`)
- `services/ai-orchestrator/orchestrator.py` — FSM contextual actual

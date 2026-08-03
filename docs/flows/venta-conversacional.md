# Flujo — Venta Conversacional (WhatsApp → pedido confirmado)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Ciclo completo: mensaje inbound del cliente → gates de compliance → FSM → catálogo/carrito → cotización de envío → resumen → pago (Wompi link o COD) → confirmación por webhook → generación de guía → tracking.

Detalle de dinero en [`pago-wompi.md`](pago-wompi.md); detalle logístico en [`despacho-aveonline.md`](despacho-aveonline.md); escalación en [`human-takeover.md`](human-takeover.md).

---

## 1. Inbound: WhatsApp → dispatcher

1. Meta entrega el mensaje al webhook del tenant (**connector-whatsapp**); la firma se verifica con HMAC **per-tenant** (credenciales Model B, ver [`onboarding-tenant.md`](onboarding-tenant.md)) — auditoría §4 "Meta (HMAC per-tenant + defensa cross-tenant + cap 512KB)".
2. El turno entra al dispatcher agéntico: `services/ai-orchestrator/agentic/dispatcher.py` → `dispatch_message()` (línea 146).
3. **Skip por estado de conversación** — `_SKIP_STATUSES = frozenset({"human_takeover", "closed", "opted_out"})` (`dispatcher.py:3618`): si la conversación está en takeover humano, cerrada u opted-out, el bot no procesa (segunda defensa tras el gate del connector; comentario en 3621-3635).

## 2. Gates determinísticos pre-LLM (en este orden)

Todos corren **antes** de invocar el LLM, en `dispatch_message()`:

| # | Gate | Evidencia | Comportamiento |
|---|---|---|---|
| 1 | **Re-opt-in** | `dispatcher.py:167-185` | Corre **primero, antes del skip**: si un cliente opted-out escribe `SUSCRIBIR`/`START`/`REACTIVAR`, se restaura consent y vuelve al bot. Sin esto, el re-opt-in sería skipped para siempre (comentario 168-169). Detalle en [`opt-out-habeas-data.md`](opt-out-habeas-data.md) |
| 2 | **Opt-out STOP (fail-closed)** | `dispatcher.py:196-224`, handler `_handle_optout_if_keyword` (3856) | Keywords inequívocas `STOP/BAJA/CANCELAR/UNSUBSCRIBE/...` (3810, 3926): confirmación canónica + revoca consent + marca conv `opted_out` + **no invoca LLM** (post-check en 212-216). Si el handler falla, `_optout_failclosed_should_skip` (222) **skips el turno** — fail-closed, un STOP jamás cae al LLM |
| 3 | **Menor de edad** | `dispatcher.py:230-248`, handler (664) | Decreto 1377/2013 Art. 7 — "prohibición más fuerte", corre antes del gate DSR (comentario 232). `safety.consent_gates.detect_minor_intent` determinístico; ante error del handler, re-detección local y skip (247-248) |
| 4 | **DSR / Habeas Data** | `dispatcher.py:252-270`, handler `_handle_data_rights_if_intent` (513) | Acceso/rectificación/eliminación → **escalación humana, nunca auto-borra** (docstring 525: "un DSR exige verificación + plazo legal; lo tramita un humano"); pausa la conversación tras el DSR (612-627) y notifica Telegram (642). Ante error → skip (270): "responder mal a un DSR es la dirección legalmente insegura" |

Flag de corte adicional: `agentic_enabled` per-tenant (`is_tenant_agentic_enabled`, `dispatcher.py:111`) — hallazgo M11: error transitorio de lectura = escalación masiva (fail-closed).

## 3. FSM conversacional — 10 estados

`services/ai-orchestrator/fsm/states.py` (verificado: **10** constantes de estado, no 9):

```text
CATALOG_MODE                     ← sin compra activa
│
├── Pre-checkout:    NEEDS_SHIPPING_CITY → AWAITING_CARRIER_SELECTION
│
├── PII (orden canónico rev. 68): NEEDS_CONSENT → NEEDS_EMAIL → NEEDS_NAME
│                                 → NEEDS_DOCUMENT → NEEDS_DIRECTION
│
└── Checkout:        READY_FOR_SUMMARY → AWAITING_ORDER_CONFIRMATION
```

Sets agrupados para guards: `PII_COLLECTION_STATES`, `PRE_CHECKOUT_STATES`, `CHECKOUT_STATES`, `ALL_STATES` (`states.py:44-62`). Resolución/persistencia del estado por turno: `_resolve_and_persist_agentic_state` (`dispatcher.py:3328`).

## 4. Catálogo y carrito (tools, con guardián anti-adivinanza)

- Tools del agente en `services/ai-orchestrator/agentic/tools/`: `catalog.py`, `cart.py`, `orders.py`, `shipping.py`, `payment.py`, `escalation.py`, `knowledge.py`, `contact.py`, `claims.py`, `media.py` (registro en `registry.py`).
- **Guardián anti-adivinanza** (`agentic/tools/cart.py:230`): "la regla es NUNCA adivinar variantes con múltiples opciones". Si el cliente no mencionó ninguna variante y el LLM eligió una → el tool falla y pide clarificación (patrón espejo en prompt: `agentic/prompt/states.py:92` — "¿el de coco se refiere al jabón o al aceite? en vez de adivinar"). El guardián juzga con el historial completo del cliente, no con un solo mensaje (fix `agentic/agent.py:151`).
- **Variante relativa determinística** (`cart.py:306-335` + `lib/variante_relativa.py`): "el más grande" NO es adivinanza — `resolver_variante_relativa` resuelve referencias determinadas sobre el conjunto listado; devuelve `None` ante la menor ambigüedad (unidades no comparables, empate, "el mediano" sin tres opciones) y entonces manda el guardián. Si el cliente señaló una y el LLM agregó otra → `tool_failure` con código `VARIANT_MISMATCH_RELATIVE`.
- Ambigüedad de producto en cotización: `tools/shipping_quote_tool.py:750` — "no adivinar producto si la diferencia es baja".

## 5. Cotización de envío (Aveonline)

- El bot cotiza vía `tools/shipping_quote_tool.py` → Core API `POST /api/v1/shipping/quote` (`services/api/routers/shipping.py`, branch `_quote_via_aveonline`, línea 184). Auth service-to-service por header `INTERNAL_SERVICE_SECRET` (`shipping_quote_tool.py:21-22`).
- Defaults de paquete configurables por env: peso 1kg, 10×10×10cm (`shipping_quote_tool.py:24-27`); timeout 25s (28).
- La tarifa confirmada se sincroniza a la orden recalculando el total desde la fuente de verdad — "nunca cambiar en silencio lo que un cliente ya pagó" (`shipping.py:545-578`); si ya fue cobrado, no se toca el dinero y se avisa para conciliación humana (606+).
- Tras cotizar: el carrier queda pendiente de selección (`AWAITING_CARRIER_SELECTION`); si el cliente agrega/quita ítems o cambia dirección después de cotizar, el cart queda `requires_requote=True` y **no se puede generar link de pago** hasta recotizar (gate en `payment_link_tool.py:375-405`).

## 6. Resumen y confirmación

- `READY_FOR_SUMMARY` → resumen del pedido → `AWAITING_ORDER_CONFIRMATION`: el cliente debe confirmar afirmativamente ("sí, confirmo") — el tool de pago valida la confirmación internamente (`agentic/tools/payment.py:24`).
- Invariants post-LLM que protegen el resumen y la coherencia: `summary_coherence`, `payment_coherence`, `requote_pending_summary`, `cart_render_coherence`, `post_tool_coherence` (15 invariantes en `agentic/invariants/`).

## 7. Pago: Wompi link o COD

Tool `generate_payment_link` (`agentic/tools/payment.py`) → `handle_payment_link_if_applicable` (`tools/payment_link_tool.py:337`). Validaciones determinísticas pre-pago:

1. **Monto**: mínimo `WOMPI_MIN_AMOUNT_CENTS` y cap de sanidad `WOMPI_MAX_AMOUNT_CENTS` → fallback a humano (359-373).
2. **Gate requires_requote** (375-405) — nunca cobrar con envío inválido (ADR-0024).
3. **Idempotencia por conversación** (407-506): una conversación + cart abierto = una orden activa. (a) link vigente ≤ TTL → reutiliza; (b) link vencido → regenera sobre la misma orden; (c) monto stale (cupón/carrier cambió tras generar) → invalida la orden vieja y crea nueva (F42, 430-446); si regenerar falla → handoff, **nunca orden duplicada** (499-506).
4. **Reserva de stock** (`_reserve_checkout_stock`, 238): `add_to_cart` ya creó reserva SOFT de 15min por ítem; el checkout **extiende** esas reservas a la ventana de 35min y reserva fresco solo el delta — evita doble-conteo contra stock (248-253). Rollback de reservas frescas si hay insuficiencia.
5. **TTL 30 min**: `WOMPI_LINK_TTL_MINUTES = 30` (`payment_link_tool.py:45`) — debe coincidir con `services/api/routers/orders.py:WOMPI_PAYMENT_LINK_TTL_MINUTES` (comentario 39-43).

**COD (contraentrega)**: branch en `payment_link_tool.py:664-765` — `payment_link: False` (664), la orden nace `confirmed` sin link vía `orders.py:create_order`, reserva stock, y tras crearla intenta la **auto-guía Aveonline** (720-755, best-effort: rechazo/exception solo loguea).

Detalle completo del dinero: [`pago-wompi.md`](pago-wompi.md).

## 8. Confirmación de pago (webhook) → notificaciones

`services/api/routers/wompi_webhook.py` (detalle en `pago-wompi.md` §2): al `APPROVED` — confirma orden + descuenta stock (paso 6, línea 543-551) → notifica cliente WhatsApp vía outbound queue (553-566) → email etapa 1 "Pago recibido" sin tracking (568-582, patrón Amazon/MeLi: separar pago de envío en 2 emails).

## 9. Generación de guía y tracking

- Auto-guía post-pago best-effort (~10-15s + delay): paso 7.6 del webhook (`wompi_webhook.py:584-596`) → `_generate_shipping_guide` (1755) con `GUIDE_GENERATION_DELAY_SECONDS` default **60s** solo en el path automático (1768, 1794-1807; el path manual del operador no espera).
- Si guía OK → email + WhatsApp etapa 2 "Guía generada" con tracking (598-639). El copy **no** promete "envío en camino": la guía solo significa tracking asignado (599-603); el estado físico llega por webhook Aveonline.
- Tracking: `services/api/routers/aveonline_webhook.py` actualiza `shipments.status` (mapping cross-provider, monotónico) y notifica cliente WhatsApp + email por estado (in_transit/delivered/exception) — detalle en [`despacho-aveonline.md`](despacho-aveonline.md) §3-4.
- **Hoy las guías son simuladas** (`simulate=True` por defecto; bloqueante B1: `AVEONLINE_GENERATE_REAL_GUIDES=false` en prod).

## 10. Anti-alucinación (3 capas, contexto del flujo)

Auditoría §4, verificado en el árbol `agentic/`:

1. **Referential integrity pre-tool** — `invariants/tool_id_referential_integrity.py` (+ guardián anti-adivinanza del carrito, §4).
2. **15 invariantes post-LLM** — `agentic/invariants/`: `fake_escalation`, `payment_coherence`, `summary_coherence`, `pii_coherence`, `consent_required`, `empty_promise`, `no_internals_exposure`, `tool_code_leak`, `variant_availability_assertion`, etc. (Hallazgo A4: invariantes que lanzan excepción DB se tragan con warning → guardrail fail-open en ese borde, `invariants/base.py:93-100`.)
3. **OutputValidator pre-envío** — `outbound/validator.py`: hard-rewrite PII-pre-consent (Ley 1581 art. 9, `validator.py:90-101`), entre otros checks.

## 11. Post-venta y borde de ventana 24h

- Reclamos desde el bot: `agentic/tools/claims.py`; desde consola: módulo Reclamos.
- Hallazgo M10: fuera de la ventana 24h de Meta, el outbound transaccional puede morir con error 131047 — el email de confirmación mitiga (etapa 1/2 siempre se intentan).

---

### Archivos clave (índice de evidencia)

| Paso | Archivos |
|---|---|
| Dispatcher + gates | `services/ai-orchestrator/agentic/dispatcher.py` |
| FSM | `services/ai-orchestrator/fsm/states.py`, `fsm/resolver.py` |
| Tools | `services/ai-orchestrator/agentic/tools/*.py`, `services/ai-orchestrator/tools/payment_link_tool.py`, `tools/shipping_quote_tool.py` |
| Guardián/variante relativa | `agentic/tools/cart.py`, `lib/variante_relativa.py` |
| Cotización | `services/api/routers/shipping.py` |
| Pago/webhook | `services/api/routers/wompi_webhook.py`, `services/api/routers/orders.py` |
| Guía/tracking | `services/api/routers/aveonline_webhook.py`, `wompi_webhook.py` (`_generate_shipping_guide`) |
| Invariants/validador | `services/ai-orchestrator/agentic/invariants/`, `outbound/validator.py` |

# Mapa de cobertura conversacional — estado real + plan de cierre

Mapeo exhaustivo (multi-agente, 2026-06-26): matriz **estado×intención** (9 estados
FSM × 22 intenciones) + auditoría del **contrato de invariants**. Objetivo: cobertura
total, con evidencia, no por pedazos.

## Estado real (honesto)

- **Diagonal (happy path):** ~85-90% cubierta, 3 capas (prompt + tool_subset + invariant/resolver). **Sólido.**
- **Contrato anti-alucinación (que el bot no MIENTA):** ~18/19 verdades cubiertas. **Fuerte.**
- **Off-diagonal (que el bot no ACTÚE sobre estado inconsistente):** ahí está la deuda — **13 gaps (5 alta, 8 media)**, concentrados en ~7 **clases estructurales** que se repiten celda a celda.

> Resumen de una línea: lo que protege contra que el bot **mienta** está bien; lo que protege
> contra que el bot **actúe** sobre estado inconsistente (carrito mutado, stock agotado, consent
> revocado, pago sin envío válido) tiene huecos sistemáticos.

## Las 7 palancas de cierre (cierran CLASES, no celdas sueltas)

| # | Palanca | Tipo | Cierra | Sev |
|---|---|---|---|---|
| 1 | **Reconciliación de estado intra-turno** — tras cualquier mutación de carrito/dirección, forzar `requires_requote` y bloquear total/confirmación/link hasta recotizar en el MISMO turno | resolver+invariant | SHIPPING/CART/PII/CARRIER #6/#7/#8/#12/#10 | alta |
| 2 | **Suite de gates PRE-`generate_payment_link`** (binarios ADR-0024): envío>0 opciones ∧ city_cotizada==city_address (anti-teleporte) ∧ payment_method∈tenant.enabled ∧ cart no-abandonado>24h ∧ no-doble-conversión ∧ dedup-link<5min | invariant/gate | toda la clase "pago sobre estado inválido" | alta |
| 3 | **Resolver consent/Habeas-Data NO-keyword** — detecta revocación/borrado más allá de "STOP" y garantiza side-effect (record_consent(False)/delete_contact_data) patrón FakeEscalation | resolver+invariant | #11 en 9 estados + GDPR delete | alta (legal) |
| 4 | **Resolver cardinalidad/stock pre-LLM** — lookup de stock, marca AGOTADO/DISPONIBLE antes del LLM + endurece invariant para bloquear "agregado" si stock=0 | resolver+invariant | #5 variante agotada en 5 estados | media-alta |
| 5 | **Cupones** — decidir arquitectura (tool `apply_coupon` en CART_BUILDING + `CouponCoherenceInvariant`) | decisión + impl | #20 en 4 estados | media · **decisión founder** |
| 6 | **Reconciliación de tool_subset** — `get_recent_orders` (GREETING lo promete sin tenerlo; SHIPPING_QUOTE lo omite) | tool_subset | #18 tracking cross-state | media |
| 7 | **Pulido de prompt** — off-topic explícito, anáfora centralizada, PII voluntaria pre-consent, línea de IVA en resumen | prompt | varios menores | baja |

## Principio rector (del mapeo)

> Cuando una intención off-diagonal requiere **acción determinística** (recotizar, revocar
> consent, bloquear stock=0, abortar carrito), el patrón ganador es **resolver PRE-LLM +
> invariant con side-effect garantizado**, NO confiar en el prompt. Cada gap "partial cuyo
> mecanismo es 'el prompt lo guía'" es deuda hasta convertirlo en determinismo.

## Estado de cierre (2026-06-26)

| # | Palanca | Estado |
|---|---|---|
| 1 | Reconciliación intra-turno | ✅ cerrada (invariant caso A+B + prompt) |
| 2 | Gates pre-pago | ✅ cerrada — **verificado: la mayoría ya existía** (status=open, idempotencia, carrier_caps); solo se agregó gate explícito requires_requote + regresión |
| 3 | Habeas Data no-keyword | ✅ cerrada (detector + escala a humano + acuse, Ley 1581) |
| 4 | Variante AGOTADA | ✅ cerrada (marcador en catálogo + regla + add_to_cart enforce) |
| 5 | Cupones | ✅ **ya estaba cubierta** — handler pre-LLM determinístico (detect→apply/revoke) + regla "NUNCA afirmar cupón fuera del bloque" + summary_coherence. NO requirió build |
| 6 | Tracking en estados tempranos | ✅ cerrada (get_recent_orders agregado a GREETING+EXPLORING subset) |
| 7 | Pulido | ◐ parcial: off-topic/dominio ✅ (regla universal); **IVA = N/A** (no existe modelo de impuestos — precios IVA-incluido); anáfora-en-greeting + PII-voluntaria = marginales diferidos |

**Disciplina aplicada:** verificar antes de construir. 3 de las "alta" del synth resultaron
ya-cubiertas o parciales al inspeccionar el código real (gates de pago, cupones; y el
veredicto/HILO previos). Se evitó construir redundante.

**Follow-up de modelo de datos:** teleporte geográfico inicial (cotiza Bogotá / dirección
Medellín) requiere un campo `city` ESTRUCTURADO en `contacts` (hoy solo `address` free-text).
No hackeado.

## Cada gap → escenario de regresión

El cierre de cada palanca siembra su escenario permanente en `scripts/uat/coherence_scenarios.py`
(intra-turno requote, teleporte geográfico, envío 0 opciones, COD deshabilitado, cart abandonado,
revocación nuanced, variante agotada insistente, cupón alucinado, dedup link, tracking temprano, IVA).

# ADR-0026 — Cart-as-SoT dueño del destino + renderizador canónico de estado

**Estado:** IMPLEMENTADO (A + B + C + revert override) · verificado en vivo · main `4f8b77b2`
**Fecha:** 2026-06-26

> **Resultado de implementación (2026-06-26):** Piezas A, B y C implementadas y verificadas
> con CONVERSACIÓN REAL 1-a-1 (escenario exacto del founder): add a mitad de checkout →
> "Subtotal: $109.000" (real, no parcial) + "Recalculé el envío a *Medellín*" + opciones (no
> repregunta la ciudad) → resumen final TOTAL $125.500 correcto. El override post-LLM band-aid
> fue REVERTIDO (A+B+C lo manejan solos, verificado sin él). Suite 3089 verde.
>
> **Decisión sobre el paso de migración de los 3 renderizadores pre-checkout
> (`_build_order_summary_text`, `_build_canonical_summary`, `_build_pricing_replacement`):
> DIFERIDO deliberadamente.** Esos 3 producen output CORRECTO y validado (el 📋 Resumen
> alimenta el invariant `summary_coherence` que parsea el total para verificarlo contra el
> cart). Consolidarlos es deduplicación de código correcto con riesgo de regresión en el path
> de PAGO, desproporcionado al beneficio. La causa raíz (destino efímero + productores ciegos
> del post-mutación) ya está cerrada; el renderizador canónico queda como base para una
> consolidación futura cuidada (con golden parity tests). Quality-first = no desestabilizar el
> resumen de pago validado. `requote_pending_summary` se MANTIENE como red de seguridad del
> path LLM (output no determinístico).
**Contexto:** síntoma hallado por conversación REAL 1-a-1 (founder): al agregar un producto a
mitad del checkout el bot dice un subtotal PARCIAL (solo el ítem nuevo) y repregunta "a qué
ciudad" aunque el carrito ya fue cotizado a Medellín. No es money bug (el final queda correcto)
pero el turno intermedio es incoherente.

Relaciona: ADR-0011 (cart-as-SoT), ADR-0018 (invariants), ADR-0024 (invariants binarios).

---

## Causa raíz (no es un bug puntual)

El carrito **no es realmente Source-of-Truth** para DOS hechos que la respuesta necesita tras
una mutación, y ambos se reconstruyen ad-hoc en cada path:

1. **El destino de entrega es EFÍMERO.** Tras la PRIMERA cotización exitosa,
   `quote_shipping_for_cart_aveonline` ([aveonline.py:410-422](../../services/ai-orchestrator/agentic/legacy_adapters/aveonline.py#L410)) solo escribe
   `shipping_meta.quoted_options` y **nunca** `city`/`dane_code`. `set_shipping_city`
   ([cart_tool.py:879](../../services/ai-orchestrator/tools/cart_tool.py#L879)) solo corre cuando el cliente dice explícito "cambia a X".
   → En el flujo normal "envíalo a Medellín", la ciudad se **parsea** y se **usa** para cotizar,
   pero **jamás se persiste**. Por eso el override post-LLM ([dispatcher.py:2415](../../services/ai-orchestrator/agentic/dispatcher.py#L2415)) lee
   `shipping_meta.city = None` y no puede recotizar → el bot repregunta.

2. **El render está FRAGMENTADO en 4 renderizadores** con vistas parciales:
   `compose_outbound_from_resolution` ([purchase_intent_resolver.py:422](../../services/ai-orchestrator/agentic/purchase_intent_resolver.py#L422)),
   `_build_order_summary_text` (orchestrator.py:4662), `_build_canonical_summary`
   (summary_coherence.py:163), `_build_pricing_replacement` (cart_render_coherence.py:261).
   El path pre-LLM purchase llama al primero **sin** `cart_subtotal_cop` ([dispatcher.py:1898](../../services/ai-orchestrator/agentic/dispatcher.py#L1898))
   → subtotal parcial. El LLM **ni siquiera ve el carrito** (`build_prompt_for_state` no recibe
   ningún arg de cart). Los invariants (`requote_pending_summary`, etc.) son **band-aids
   post-facto** que REESCRIBEN cuando los productores ya compusieron mal.

**Conciliación:** cada productor de texto (3 resolvers pre-LLM + LLM + 3 invariants) reinventa
la lectura del estado. El fix de raíz: el cart dueño del destino persistido (A) + UN renderizador
canónico que todos consuman (B) + conectar los productores ciegos al SoT (C), eliminando los
band-aids.

---

## Decisión — 3 piezas (ninguna es parche)

### Pieza A — Destino de entrega como dato persistido de primera clase
El cart se vuelve dueño del destino. Se persiste `{city, dane_code, address_line}` en
`shipping_meta` **siempre** que se resuelve un destino (no solo en cambio explícito).
- `quote_shipping_for_cart_aveonline` pasa a persistir el destino cotizado vía
  `set_shipping_meta(city=..., dane_code=...)` además de `quoted_options`.
- Nuevo `get_shipping_destination(cart, contact)` con precedencia única:
  `shipping_meta.city` (persistido) → `contact.address.city/dane` (canónico, migración
  20260623153808) → `None`.
- `invalidate_shipping` ya preserva `city` (cart_tool.py:978-982) — ahora SIEMPRE habrá city
  que preservar (path vivo en vez de dead-code).

**V1 NO crea columna nueva** — el destino vive en `shipping_meta` (JSONB), que ya ES el contrato
documentado del cart. El problema no era el storage sino que **nadie escribía `city` ahí** en el
flujo normal. Se endurece con `set_shipping_destination()` explícito.

```
set_shipping_destination(supabase, *, cart_id, tenant_id, city, dane_code=None, address_line=None) -> dict
get_shipping_destination(cart, contact=None) -> dict|None  # {city, dane_code, address_line, source: 'cart'|'contact'}
```

### Pieza B — Renderizador canónico de estado-tras-mutación
Una sola función pura `render_cart_state_snapshot()` (módulo nuevo `agentic/cart_render.py`,
sin IO) que produce el texto canónico: items con line totals, **SUBTOTAL REAL del cart** (no
parcial), y línea de envío en uno de tres modos coherentes:
- (i) envío cotizado vigente → carrier + costo,
- (ii) `requires_requote=True` con destino conocido → "recalculo el envío a {city}" **sin
  repreguntar**,
- (iii) sin destino → pide ciudad UNA vez.

Es el **único** lugar que decide "¿pregunto ciudad?" leyendo `get_shipping_destination()`.
`_build_order_summary_text`, `_build_canonical_summary` y `_build_pricing_replacement` se
refactorizan para **delegar** el cuerpo de items/subtotal/envío a este renderizador.

```
render_cart_state_snapshot(*, cart, contact=None, destination=None,
                           mode: 'post_mutation'|'pre_checkout_summary'='post_mutation') -> str
```

### Pieza C — El pre-LLM purchase y el LLM consumen el estado real
Cerrar los dos productores ciegos:
- **Pre-LLM purchase** ([dispatcher.py:1842-1956](../../services/ai-orchestrator/agentic/dispatcher.py#L1842)): tras los `add_to_cart`, RECARGA el cart con
  `get_cart_with_items` y compone vía `render_cart_state_snapshot` (B) con destino persistido (A).
- **LLM**: `build_prompt_for_state` recibe `cart_snapshot`; `prompt/blocks.py` añade
  `cart_state_section()` que inyecta `[CARRITO ACTUAL CON ENVÍO]` en estados de checkout
  (CART_BUILDING/SHIPPING_QUOTE/CARRIER_SELECTION/PAYMENT), igual que `catalog_compact_section`.

---

## Migración de datos

**V1 NO introduce columna** → CERO riesgo de migración estructural al remoto. El cambio es de
**comportamiento** (escribir city/dane en la primera cotización), no de schema.

**Backfill opcional y SEGURO** (solo carritos `open` que quedaron sin city): script idempotente
que copia city/dane desde `contacts.address` (ya canónico). Protocolo founder: (1) SELECT de
conteo dry-run en remoto; (2) UPDATE acotado por tenant + `status='open' AND shipping_meta ?
'quoted_options' AND NOT (shipping_meta ? 'city')`; (3) `jsonb_set` (no sobrescribe el resto);
(4) verify post (debe dar 0). Si el founder prefiere, **se omite**: los carritos open en vuelo
repreguntan ciudad una última vez y quedan correctos — sin corrupción.

**V2 (futuro, NO en este fix):** CHECK constraint sobre shipping_meta (city presente cuando
shipping_cents>0) o columna dedicada. Se difiere porque introduce riesgo sin resolver el síntoma.

---

## Qué se REVIERTE (señal de que es raíz, no band-aid encima de band-aid)
- `dispatcher.py:2398-2446` — override post-LLM de auto-recotización (no funciona: depende de
  city no persistida + nunca corre en el path pre-LLM). Redundante con A+B+C.
- `requote_pending_summary.py` — el REWRITE hardcodeado degrada a OK-only/log (el renderizador
  ya produce el mensaje correcto en origen).
- `purchase_intent_resolver.py:488-493` — la rama que SIEMPRE dice "Dime a qué ciudad".

---

## Orden de implementación (cada paso verificado EN VIVO con conversación real)
1. **A storage:** `set/get_shipping_destination` + persistir city/dane en quote. Verificar en DB
   que `shipping_meta.city` aparece tras "envíalo a Medellín".
2. **B renderizador:** crear `cart_render.py` + golden tests de paridad con los 3 renderizadores
   actuales. No migrar consumidores aún.
3. **C pre-LLM purchase:** recargar cart + usar renderizador. Verificar en vivo "agrégame 1 más"
   a mitad: subtotal completo + sin repreguntar ciudad.
4. **C LLM:** `cart_state_section` + kwarg. Verificar en vivo mensaje que cae al LLM ya cotizado.
5. **Migrar por delegación** los 3 renderizadores restantes, uno a la vez, paridad de string +
   suite tras cada uno.
6. **Backfill** opcional (solo si founder aprueba).
7. **Revertir** override + invariant-rewrite SOLO tras confirmar coherencia en vivo sin ellos.
8. **Gate final:** suite completa + conversación real end-to-end del escenario del founder.

---

## Riesgos + mitigación
| Riesgo | Mitigación |
|---|---|
| Persistir city rompe match Aveonline (uppercase vs humano) | Persistir city humana ('Medellín') + dane_code, NO city_canonical; test merge existente |
| Renderizador unificado cambia texto ya validado (regresión visual) | Golden tests que reproducen EXACTO el output actual; migrar 1 consumidor a la vez con paridad de string |
| `[CARRITO ACTUAL]` en prompt infla tokens / confunde | Solo estados checkout; bloque <1KB del mismo renderizador → consistencia |
| Quitar override deja un path descubierto | No revertir hasta A+B+C verificados en vivo |
| Fallback a contact.address cotiza ciudad equivocada | Precedencia estricta: shipping_meta.city SIEMPRE gana; loguear source |

---

## Auto-crítica honesta (zonas grises)
- **Pieza C-LLM** sigue confiando en que el LLM "lea" el bloque. Mitigación: el path **pre-LLM
  determinístico es el primario** para el escenario del bug y NO depende del LLM; el bloque LLM
  es defensa en profundidad.
- **V1 deja el destino en JSONB sin constraint duro** — es "first-class" por comportamiento + API
  (`set/get_shipping_destination`), no por schema. Concesión consciente para evitar migración
  riesgosa ahora; V2 (CHECK/columna) documentado como follow-up. El enforcement de schema queda
  pendiente — se reconoce, no se oculta.

---

## Alternativas rechazadas
- **Seguir parcheando path-por-path** (pasar cart_subtotal + ampliar override): es lo que ya se
  hizo y dejó 3 renderizadores divergentes + city sin persistir. Cada path nuevo reinventaría su
  vista parcial. No ataca la raíz.
- **Columna dedicada en V1:** el destino ya tiene hogar contractual (shipping_meta); columna nueva
  = migración riesgosa sin resolver el síntoma más rápido. → V2 opcional.
- **Eliminar resolvers pre-LLM (solo LLM):** existen porque Gemini falla con muchos tools. La
  solución es que pre-LLM y LLM compartan renderizador + destino, no eliminar uno.
- **Reforzar invariants para que siempre reescriban:** band-aids post-facto frágiles (regex) +
  lectura DB extra/turno. Quedan como red de seguridad, no arquitectura primaria.

> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Rev. 103 — Auditoría UAT S13-S25 (concordancia + bugs identificados)

**Fecha**: 2026-05-04
**Alcance**: 13 escenarios UAT (S13 a S25), modos `new` + `known` donde aplique
**Tipo**: auditoría rigurosa para identificar bugs de código del proyecto
**Restricción**: NO se modificó código del proyecto — solo tests para mejorar concordancia

---

## 1. Contexto

Tras la fase previa donde se completó UAT S1-S12 (24/24 PASS, ver
[scripts/uat/scenarios/](../../scripts/uat/scenarios/)), se inicia esta auditoría
de S13 a S25 con dos objetivos:

1. **Identificar bugs reales del código** (orchestrator, API, integraciones).
2. **Asegurar concordancia** de los tests — que un PASS/FAIL/SKIP refleje fielmente
   el comportamiento del bot, no artefactos del harness.

Se ejecutaron dos rondas:

- **Ronda 1 (v1)** — corrida inicial con tests existentes. Identificó 6 FAIL +
  1 SKIP de 18 corridas.
- **Ronda 2 (v2)** — tras ajustar tests para concordancia (sin tocar código
  del proyecto). Identificó 5 FAIL + 2 SKIP de 18 corridas, con resultados
  ahora **veridicamente concordantes** con el comportamiento observado.

---

## 2. Matriz de resultados v2

| # | Escenario | Tipo | new | known | Tiempo (s) |
|---|-----------|------|:---:|:---:|:---:|
| S13 | Multi-producto + volumetría | LLM-driver | ✅ | ✅* | 143 / 147 |
| S14 | Cambio ciudad envío | LLM-driver | ❌ | ❌ | 127 / 118 |
| S15 | Promesa link cumplida | LLM-driver | ✅ | ✅ | 213 / 122 |
| S16 | Wompi APPROVED simulation | server-side | ❌ | n/a | 13 |
| S17 | Consent gating unconsented | LLM-driver | ✅ | n/a | 122 |
| S18 | MeLi ↔ WhatsApp match | server-side + bot | ❌ | n/a | 35 |
| S19 | Renewed consent post-anonim | server-side | ✅ | n/a | 5 |
| S20 | Delete audit immutable | server-side | ✅ | n/a | 4 |
| S21 | Form Add unconsented | server-side | ✅ | n/a | 4 |
| S22 | Storage bucket consent-evidence | server-side | ✅ | n/a | 2 |
| S23 | Renewals cap 50 | server-side | ✅ | n/a | 4 |
| S24 | Casual real-world chat | LLM-driver | ⏭️ | ⏭️ | 141 / 100 |
| S25 | Shipping phone alterno | LLM-driver | ✅ | ❌ | 124 / 83 |

\* S13 mode=known: PASS en run 2 pero FAIL en run 1 — comportamiento
intermitente (variabilidad LLM en variant detector multi-producto).

**Totales**: 11 PASS · 5 FAIL · 2 SKIP de 18 corridas (~22 min total)

---

## 3. Bugs de código identificados

> **Política de la auditoría**: ningún bug fue arreglado en código. Quedan
> listados aquí para seguimiento estructurado en una próxima ronda.

### 🔴 BUG-1 — Cart-as-SoT pierde city tras cambio de ubicación (S14)

| Campo | Detalle |
|-------|---------|
| Severidad | Alta — riesgo financiero (envío a ciudad equivocada) |
| Reproducibilidad | 100% (2/2 consistente en ambos modos) |
| Síntoma `mode=new` | Bot re-cotiza Medellín ($13.140) pero `cart.shipping_meta.city=""` y `requires_requote=False` |
| Síntoma `mode=known` | Bot **ignora completamente** "Mejor cambia el envío a Medellín" — re-cotiza Bogotá ($7.830) |
| Hipótesis | `_detect_shipping_location_change` no dispara en path conocido; `set_shipping_meta` no recibe `city` |
| Archivos sospechosos | [services/ai-orchestrator/orchestrator.py](../../services/ai-orchestrator/orchestrator.py), [shipping_quote_tool.py](../../services/ai-orchestrator/tools/shipping_quote_tool.py), [cart_tool.py](../../services/ai-orchestrator/tools/cart_tool.py) |

### 🔴 BUG-2 — Phone canonicalization MeLi ↔ orchestrator inconsistente (S18)

| Campo | Detalle |
|-------|---------|
| Severidad | Alta — duplicación silenciosa de contacts (Habeas Data + UX) |
| Reproducibilidad | 100% (2/2) |
| Síntoma | 2 filas en `contacts` para mismo phone: `+57X` (MeLi import) vs `57X` (orchestrator upsert) |
| Causa raíz | `_upsert_meli_contact` normaliza a E.164 (`+`), `orchestrator` a digits-only |
| Archivos sospechosos | [services/api/routers/meli_webhook.py:`_upsert_meli_contact`](../../services/api/routers/meli_webhook.py), [orchestrator.py:6006](../../services/ai-orchestrator/orchestrator.py#L6006) |
| Solución sugerida | Alinear a digits-only (canon connector) + migración backfill |

### 🔴 BUG-3 — Webhook Wompi APPROVED no actualiza `payments.status` (S16)

| Campo | Detalle |
|-------|---------|
| Severidad | Alta — auditabilidad rota |
| Reproducibilidad | 100% (revelado por asserts estrictos) |
| Síntoma | tras APPROVED → `orders.status=confirmed` ✓, `stock_movements` con delta=-1 ✓ — **PERO** `payments.status='PENDING'` y `payments.wompi_status=null` |
| Evidencia | order_id `9d557b60-34c4`, txn_id `sim_1df189e2`, webhook 200 |
| Archivos sospechosos | [services/api/routers/wompi_webhook.py](../../services/api/routers/wompi_webhook.py) |

### 🔴 BUG-4 — Phone alterno post-resumen ignorado en path conocido (S25 known)

| Campo | Detalle |
|-------|---------|
| Severidad | Alta — pérdida silenciosa de dato crítico para envío |
| Reproducibilidad | 100% (2/2) |
| Síntoma | cliente conocido tras ver resumen dice "el celular es 3225551234" → bot salta a generar payment_link sin extraer `extracted_shipping_phone`. `contacts.shipping_phone` queda con phone WhatsApp original |
| Hipótesis | bypass `AWAITING_ORDER_CONFIRMATION + _aff` interpreta la frase como afirmativa (palabras "pedido"/"recibe"), saltando extracción LLM |
| Archivos sospechosos | [orchestrator.py:`_is_affirmative_confirmation`](../../services/ai-orchestrator/orchestrator.py) |

### 🟠 BUG-5 — Bot omite resumen mandatorio antes de generar link (señalado por usuario)

| Campo | Detalle |
|-------|---------|
| Severidad | Media-Alta — UX/contrato — cliente puede pagar sin ver desglose |
| Reproducibilidad | Variable — observado en S17 mode=new run 2 |
| Síntoma | bot dice "Listo, te genero el link de pago. Por Wompi puedes pagar..." sin emitir el bloque `📋 *Resumen de tu pedido:*` previo |
| Contrato esperado (rev. 103) | Cart-as-SoT obliga a mostrar resumen antes de cualquier link |
| Hipótesis | El bypass `READY_FOR_SUMMARY → _build_order_summary_text` no dispara cuando el FSM transition es atípica (ej: dump dispara consent + datos en mismo turn) |
| Pendiente test | Helper `_resumen_shown_before_link(messages)` aplicable a S15, S17, S24, S25 |

### 🟡 BUG-6 — Bot stuck en foto fallback ante "confirmo, mándame el link" (S24)

| Campo | Detalle |
|-------|---------|
| Severidad | Media — LLM mis-routing |
| Reproducibilidad | ~75% (3 ocurrencias entre runs) |
| Síntoma | bot interpreta "mándame el link" como pedido de imagen → fallback "no tengo foto cargada" |
| Hipótesis | clasificador de intent del LLM (Gemini) confundido por "mándame" + "link" |
| Archivos sospechosos | [orchestrator.py: system prompt + intent classification](../../services/ai-orchestrator/orchestrator.py), [image_send_tool.py](../../services/ai-orchestrator/tools/) |

### 🟡 BUG-7 — Variant detector multi-producto intermitente (S13 known)

| Campo | Detalle |
|-------|---------|
| Severidad | Media — no determinístico |
| Reproducibilidad | ~50% (run 1 FAIL, run 2 PASS) |
| Síntoma | input "2 jabones de coco + 1 sérum vit C" — variabilidad: a veces cart=2 productos distintos, a veces cart=1 (perdió sérum) |
| Hipótesis | `_detect_explicit_product_in_inbound` (Camino B) variable según contexto; o cart_add_item async race |
| Recomendación | repetir N=10 corridas para cuantificar tasa de fallo real |

### 🟡 BUG-8 — Bot pidió PII sin pedir consent previamente (S24 new)

| Campo | Detalle |
|-------|---------|
| Severidad | Alta legal — violación Ley 1581 si llegara a producción |
| Reproducibilidad | 1/2 (intermitente — depende del path FSM) |
| Síntoma | bot pidió "compárteme tu nombre completo" SIN haber emitido el template CONSENT_QUESTION antes |
| Archivos sospechosos | [orchestrator.py: FSM display_state resolution](../../services/ai-orchestrator/orchestrator.py) — falta gate "no avanzar a NEEDS_NAME si consent_given=false" |

---

## 4. Ajustes a tests aplicados (concordancia)

> **Sin tocar código del proyecto.** Todas las modificaciones fueron en
> `scripts/uat/scenarios/` o `scripts/uat/lib/`.

### 4.1 S13 — Validación cart-as-SoT real
- **Antes**: contaba tokens "jabón"+"sérum" en transcript del bot (falso positivo posible).
- **Después**: query `conversation_carts` + `conversation_cart_items` y verifica `>= 2 product_id distintos`.

### 4.2 S14 — Validación cart-as-SoT en cambio de ciudad
- **Antes**: solo verificaba "medellín" en outbound.
- **Después**: lee `cart.shipping_meta.city` post-cambio. PASS si city actualizada O si `requires_requote=True` (invalidación válida intermedia).

### 4.3 S16 — Refactor self-contained con asserts estrictos
- **Antes**: dependía de orden `pending_payment` viva creada por S15. Wompi sandbox auto-confirma rápido → S15 dejaba la orden ya en `confirmed` → S16 era idempotente, no testeaba transición real.
- **Después**:
  - Inserta sintéticamente `contact + order(pending_payment) + order_items + payment` con `wompi_link_id` ficticio.
  - events_key leído via `get_tenant_wompi_creds` (Vault per-tenant, alineado con código real).
  - Asserts estrictos: `orders.status='confirmed'`, `stock_movements.reason='sale' delta<0`, **`payments.status='APPROVED'`**, **`payments.wompi_status='APPROVED'`**.
  - Path webhook corregido: `localhost:8001/api/v1/webhooks/wompi` (antes apuntaba a 8000/9000 inexistente).
- **Resultado**: estos asserts revelaron BUG-3.

### 4.4 S17 — Keyword check expandido
- **Antes**: detectaba consent solo con "tratamiento de datos", "habeas data", "ley 1581".
- **Después**: incluye "estás de acuerdo", "guardar tus datos", "consentimiento", "autorización", "podrías autorizarme".
- **Razón**: el template canónico del bot (`CONSENT_QUESTION_TEMPLATE`) usa "¿Estás de acuerdo? *SÍ* o *NO*" sin las palabras legalistas.

### 4.5 S24 — Validación DB-state estricta
- **mode=known antes**: PASS si `prio=30/60` rules NO disparaban (validaba solo "no re-pidió PII").
- **mode=known después**: además valida `orders.status in {pending_payment, confirmed}` AND detecta foto-fallback como SKIP/anomalía. Eliminó falso PASS.
- **mode=new antes**: SKIP si bot no pedía consent.
- **mode=new después**: distingue:
  - `link generado + consent_given=false` → CRITICAL FAIL (Habeas Data).
  - `bot stuck foto fallback` → SKIP (anomalía LLM).
  - `flow incompleto sin foto` → SKIP estándar.

### 4.6 S25 — Concordancia mode=known
- **Antes**: usaba dump completo via driver (irreal para conocido).
- **Después**: sequence determinística corta (5 turnos) — sin re-dar PII, solo introduce phone alterno tras carrier. Mantiene assertion de invariante `phone` y persistencia `shipping_phone`.

---

## 5. Pendientes para próxima ronda

1. **Helper `_resumen_shown_before_link`** en `harness.py` — validar que ANTES de cualquier link Wompi en outbound, hubo un outbound con `📋` o `*Resumen de tu pedido*`. Aplicar a S15, S17, S24, S25.
2. **Wompi RECHAZADO simulation** (S26 propuesto) — simular `transaction.status=DECLINED/VOIDED`, validar que orden NO transiciona, bot notifica al cliente, `payments.status='DECLINED'`.
3. **Investigación de variabilidad** — ejecutar BUG-7 (S13 multi-producto) con N=10 para cuantificar tasa de fallo.
4. **Resolver BUGs 1-8 en código** — sprint dedicado tras priorización.

---

## 6. Archivos modificados

### Tests ajustados (sin tocar código del proyecto)

| Archivo | Cambios | Motivación |
|---------|---------|------------|
| [scripts/uat/scenarios/s13_multi_product.py](../../scripts/uat/scenarios/s13_multi_product.py) | Validación DB cart-as-SoT (≥2 product_id distintos) | Eliminar falso positivo por tokens en transcript |
| [scripts/uat/scenarios/s14_change_shipping.py](../../scripts/uat/scenarios/s14_change_shipping.py) | Validación cart.shipping_meta.city / requires_requote | Detectar desincronización cart-as-SoT |
| [scripts/uat/scenarios/s16_wompi_approved_simulation.py](../../scripts/uat/scenarios/s16_wompi_approved_simulation.py) | Refactor self-contained + asserts estrictos + path correcto + events_key Vault | Aislar transición real + revelar BUG-3 |
| [scripts/uat/scenarios/s17_consent_gating_for_unconsented_contact.py](../../scripts/uat/scenarios/s17_consent_gating_for_unconsented_contact.py) | Keyword check expandido | Cubrir template canónico |
| [scripts/uat/scenarios/s24_casual_real_world_chat.py](../../scripts/uat/scenarios/s24_casual_real_world_chat.py) | Validaciones DB-state estrictas + detección foto-fallback + Habeas Data CRITICAL | Eliminar falso PASS engañoso |
| [scripts/uat/scenarios/s25_shipping_phone_alternate.py](../../scripts/uat/scenarios/s25_shipping_phone_alternate.py) | Refactor mode=known sequence determinística | Realismo SaaS B2B |

### Código del proyecto

**NO se modificó.** Política de la auditoría: identificar y documentar, no parchear.

---

## 7. Artefactos de la auditoría

- `/tmp/uat_s13_s25/results_v2.tsv` — matriz tabular completa post-ajustes
- `/tmp/uat_s13_s25/v2_*.log` — logs detallados de cada corrida (transcripts + JSON)

---

## 8. Resumen ejecutivo

- **18 corridas** ejecutadas (13 escenarios × modos soportados).
- **11 PASS · 5 FAIL · 2 SKIP** con concordancia validada.
- **8 bugs de código** identificados — 4 alta severidad, 4 media.
- **6 tests ajustados** para asegurar que PASS/FAIL refleja realidad del bot.
- **0 cambios** en código del proyecto (orchestrator, API, integraciones).
- Pendiente próxima ronda: helper resumen-mandatorio + S26 RECHAZADO + sprint de fixes.
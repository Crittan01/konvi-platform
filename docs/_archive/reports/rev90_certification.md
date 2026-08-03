> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Rev. 90 — Certificación post-fix S14 + listado truncado

Fecha: 2026-04-30
Branch: develop

## Cambios entregados

### P0 — S14: bypass del SKIP-shipping cuando hay cambio explícito de ubicación

**Síntoma anterior** (rev. 89): tras la pregunta de consent ("¿Estás de
acuerdo?"), el branch SKIP-shipping del orchestrator dejaba de procesar
shipping aunque el cliente respondiera con un cambio de ciudad ("mejor
envíalo a Medellín"). Resultado: bot quedaba mudo o repetía consent.

**Fix** (orchestrator.py:4314-4348): se chequea
`_detect_shipping_location_change(content, history)` ANTES del SKIP. Si
el detector retorna ciudad, se bypassa el SKIP y se reescribe el query
hacia `cotizar envío a {ciudad}`, forzando re-cotización al nuevo destino.

**Verificación E2E**: S14 ahora PASS. Bot re-cotiza a Medellín.

### P1 — Listado truncado por categoría (3 + N más)

**Síntoma anterior**: cuando el cliente pregunta "¿qué tienen?" sobre
un catálogo con varias categorías, el bot listaba TODOS los productos,
generando paredes de texto y la sensación falsa de "esos son TODOS"
cuando el catálogo del tenant tenía más.

**Fix** (orchestrator.py:3613): regla `LISTADO TRUNCADO` agregada a la
sección FORMATO WhatsApp del system prompt. Especifica:
- Por categoría: máximo 3 ítems + cuarto ítem en cursiva con conteo
  restante (`* _y N-3 más..._`).
- Si la consulta es específica a UNA categoría, hasta 5 ítems.

Patrón canónico documentado con ejemplo dentro del prompt.

## Resumen E2E (16 escenarios)

| # | Escenario | Estado |
|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS |
| 2 | Consulta catálogo | ✅ PASS |
| 3 | KB cita de fuentes | ✅ PASS |
| 4 | Out-of-domain | ✅ PASS |
| 5 | Foto producto | ✅ PASS |
| 6 | Datos desordenados (turn-by-turn) | ❌ FAIL |
| 7 | Formato canónico WhatsApp | ✅ PASS |
| 8 | Revocación adaptativa | ✅ PASS |
| 9 | Happy path completo | ❌ FAIL |
| 10 | Cancelación mid-flow | ✅ PASS |
| 11 | Escalación a humano | ✅ PASS |
| 12 | Address conjunto residencial | ❌ FAIL |
| 13 | Multi-producto + volumetría | ✅ PASS |
| 14 | Cambio ciudad de envío | ✅ PASS ← rev. 90 fix |
| 15 | Promesa de link cumplida | ⏭️ SKIP |
| 16 | Wompi APPROVED simulation | ⏭️ SKIP |

**Resultado**: 11 PASS · 3 FAIL · 2 SKIP

S15/S16 SKIP es estructural — dependen de que S6/S9/S12 lleguen al punto
de confirmación, lo que requiere completar la captura de datos LLM-only.

## Análisis honesto de los 3 FAIL residuales

S6, S9 y S12 fallan en el mismo segmento: post-consent, captura de datos
del cliente. La FSM se queda en `NEEDS_EMAIL` / `NEEDS_NAME` y la
respuesta del LLM cuando recibe el dump de datos sale vacía o no avanza.
**No son regresiones** — están presentes desde rev. 88 y son resistentes
al hard-lock determinístico actual.

Hipótesis (no validadas, requieren investigación dirigida):
1. La cascada LLM (`flash → flash-lite`) puede estar devolviendo
   respuesta vacía en este sub-flow específico, y el safety net no se
   está activando porque hay un short-circuit en otro detector.
2. El parser determinístico de campos del dump ("Soy Cristian, correo
   x@y.com, CC 123, dirección...") no está extrayendo y persistiendo
   los campos antes de re-prompting.
3. Específicamente para S12 (conjunto), el detector de building_type
   no está pidiendo torre/apto cuando detecta "conjunto" en address.

**Decisión**: estos no se atacan en rev. 90. Se documentan como rev. 91
backlog explícito.

## Triggers de regresión (tests unitarios)

```text
tests/test_rev90_s14_location_change_bypasses_skip.py    7 tests
tests/test_rev90_listado_truncado_prompt.py              5 tests
```

Suite total: 823 tests OK. Validate.sh: 13/13 OK.

## Pendientes para rev. 91

1. **S6/S9 captura LLM-only** — diseñar un dump-parser determinístico
   que extraiga (name, email, document, address) en una sola pasada
   cuando el inbound contiene varios campos separados por comas.
2. **S12 building_type** — wire del detector existente
   (`_detect_building_type_from_text`) en el handler post-consent,
   con re-prompting determinístico ("¿En qué torre y apto?") cuando
   address contiene "conjunto" pero falta torre/apto.
3. **Top 3 por ventas** — opcional. Requiere SQL de agregación de
   `order_items` por `product_id` y ranking. Solo aporta si el catálogo
   tiene ≥7 ítems por categoría.
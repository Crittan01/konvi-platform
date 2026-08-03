> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Rev. 82.b — Hotfix completo del image-handler hijack + run E2E

**Fecha**: 2026-04-30
**Detonante**: log conv 8bf9b673 (2026-04-30 16:32–16:45) mostró que el
hotfix rev. 82 (parcial) NO resolvió el bug — el bot seguía respondiendo
con photo prompt a saludos como "Hola como estan?".

## Diagnóstico completo (2 bugs distintos)

| Bug | Síntoma | Causa raíz | Verificación |
|---|---|---|---|
| **#1 substring matching** | "Hola como estan?" matcheaba `"como es"` como prefijo | `is_image_request_query` usaba `p in normalized` | `is_image_request_query("Hola como estan?")` → True (pre-fix) |
| **#2 followup loop** | Tras disambig, CUALQUIER input mantenía intent de imagen | `is_followup_to_image_disambiguation` solo chequeaba el último outbound | Logs del orchestrator turn 11:45:13: NO llamó a Gemini, salida pre-LLM |

Hipótesis alternativa "recovery de conversación previa" descartada con
logs (`POST contacts → 201 Created`, sin historial).

## Fix aplicado

### Bug #1 (rev. 82) — ya cerrado
- Removida `"como es"` de `_IMAGE_REQUEST_PHRASES`.
- Word-boundary matching para frases restantes
  (`_phrase_matches_with_boundary`).
- 18 tests rev. 82.

### Bug #2 (rev. 82.b — ESTE)
- **Greeting-only gate**: `_query_is_only_greeting()` bloquea el
  followup detector cuando el query del cliente consta solo de
  saludo/cortesía (frozenset de 26 tokens).
- **Disambig rounds counter**: `_count_disambiguation_rounds()` cuenta
  rondas consecutivas; tras 2 sin que el cliente identifique producto,
  abandona el intent y delega al LLM.
- **Followup detector original** preservado para casos legítimos.

3 gates aplicados en orden en `handle_image_request_if_applicable`:

```
if not is_image_request_query(query_text):
    if _query_is_only_greeting(query_text):
        return ImageSendResult(handled=False)         # gate 1
    if _count_disambiguation_rounds(history) >= 2:
        return ImageSendResult(handled=False)         # gate 2
    if not is_followup_to_image_disambiguation(history):
        return ImageSendResult(handled=False)         # gate 3 (original)
```

Tests: 31/31 OK (13 nuevos sobre 18 de rev. 82). Suite total **723 OK**.

## Run E2E rev. 79 completo (16 escenarios) — resultado

**Resumen**: 8 PASS · 6 FAIL · 2 SKIP

### Escenarios PASS (8)

| # | Escenario | Validación clave |
|---|---|---|
| 1 | Primer contacto + saludo | "Hola buenas tardes" → bot saludo normal — **bug del usuario CERRADO** |
| 2 | Consulta catálogo | Bot listó productos sin derraille |
| 5 | Foto producto | Bot fallback explicativo tras 2 turnos (ahora correcto) |
| 7 | Formato canónico WhatsApp | Sin `**` ni `• ` |
| 8 | Revocación adaptativa | Contacto eliminado tras "elimina mis datos" |
| 11 | Escalación a humano | Bot reconoció petición de asesor |
| 13 | Multi-producto + volumetría | Cotizó multi-producto con peso real |
| 14 | Cambio ciudad de envío | Bot re-cotizó a Medellín tras "cambia envío" |

### Escenarios FAIL (6) — DESGLOSE

#### Bugs de producto (no del fix)

**S4 — Alucinación crítica** 🔴
- Cliente: *"¿Cómo está el clima en Bogotá?"*
- Bot: *"aquí en bogotá está soleado y fresco, ¡un día perfecto para
  cuidarnos con lo mejor de la naturaleza!"*
- El bot **inventó datos meteorológicos** (no los conoce). Debe
  rechazar preguntas off-topic, no improvisar.
- **Severity P1**.

**S3 — KB sin cita** 🟡
- Bot respondió contenido de KB pero **omitió** la línea
  `_Fuente: <título>` que rev. 78 F3 instruye al LLM agregar.
- Posible regresión por cambios de prompt o LLM ignorando la
  instrucción.

#### Patrón crítico: respuesta vacía del bot

**5 escenarios (S6, S9, S10, S12, S15)** terminan con `bot: ""` en
turnos críticos del flow:

```
S6  cliente da datos personales  → bot ""
S9  cliente da email              → bot ""
S10 cliente cancela               → bot ""
S15 cliente confirma orden        → bot ""
```

El **ghost-message guard rev. 78 F2** está bloqueando outbounds
vacíos (correcto), pero el LLM/cascada produce string vacío en
turnos cargados. Cliente queda mudo. **Severity P0**.

Hipótesis a investigar (rev. 83):
1. Cascada degraded mal-parseada cuando 503 sostenido.
2. LLM trunca output antes de cerrar JSON.
3. Token compaction no implementado → contexto demasiado largo
   en turnos avanzados → output corrupto.

### Escenarios SKIP (2)

- **S15** (link delivery): no llegó a confirmación porque bot=""
  cortó el flow.
- **S16** (Wompi APPROVED sim): depende de S15 con orden creada.

## Conclusión

| Item | Estado |
|---|---|
| Bug del usuario ("Hola como estan?" derrailaba) | ✅ **Cerrado y verificado** (S1 PASS empírico) |
| Hotfix rev. 82.b | ✅ Aplicado, testeado, recargado en VM |
| Suite | ✅ 723 OK · validate 13/13 OK |
| 6 FAILs nuevos detectados en E2E completo | ⏳ **Out of scope rev. 82.b** — requieren rev. 83 |

## Pendientes para rev. 83 (priorizados)

| # | Item | Severity |
|---|---|---|
| 1 | Investigar `bot=""` en turnos avanzados (S6, S9, S10, S15) | **P0** |
| 2 | Fix alucinación S4 (out-of-domain) — endurecer system prompt anti-improvisación | **P1** |
| 3 | Fix S3 KB sin cita — verificar instrucción _Fuente: en kb_tool sigue vigente | **P1** |
| 4 | Token compaction del history (rev. 83) podría aliviar P0 si la causa es contexto largo | **P0** dependent |

## Archivos tocados

**Modificados**
- [services/ai-orchestrator/tools/image_send_tool.py](services/ai-orchestrator/tools/image_send_tool.py): 2 nuevas funciones (`_query_is_only_greeting`, `_count_disambiguation_rounds`) + 3 gates en `handle_image_request_if_applicable`.

**Tests**
- [tests/test_rev82_image_matcher_hotfix.py](tests/test_rev82_image_matcher_hotfix.py): extendido a 31 tests (greeting detector, rounds counter, regresión async del bug del log).
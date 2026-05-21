# Orchestrator Refactor — Target Architecture

**Estado:** propuesta arquitectónica activa, en ejecución.
**Branch:** `phase-1-orchestrator-refactor`.
**Punto de partida:** commit `78f6ac6` (orchestrator.py = 10,262 LOC, función `build_and_run_orchestration` = 3,589 LOC).
**Objetivo final:** orchestrator.py ≤ 1,500 LOC en 8 semanas mediante strangler-fig.

---

## 1. Resumen ejecutivo

El `services/ai-orchestrator/orchestrator.py` actual es funcional pero **insostenible al ritmo de crecimiento**:

- 124 funciones top-level en un archivo.
- 13 bypasses pre/post-LLM con guards multiplicativos anti-interferencia.
- 17 detectores con listas tokenizadas frágiles.
- 12 funciones parseando `history` para reconstruir estado (dual SoT latente con cart-as-SoT).
- 10 sitios invocando `_build_order_summary_text` sin invariante "datos frescos".
- 28 lecturas dispersas del cart, 37 puntos de salida outbound.

Esto fue producido por evolución incremental válida — cada parche cazó un bug real. Pero la **superficie de bugs futuros crece superlinealmente** con cada bypass que se añade.

El refactor NO cambia el comportamiento externo del bot (mismo FSM, mismas tools, mismos invariantes). Cambia la **organización interna** del orchestrator para que:

1. Cada bug afecte **una sola capa**, no se propague.
2. Cada feature nueva (multi-agente, storefront, channel registry) sea **una stage o un handler nuevo**, no más bypasses en el monolito.
3. Onboarding técnico futuro pase de **3-4 semanas** a **1-2 semanas**.

---

## 2. Arquitectura objetivo (pipeline de stages)

`build_and_run_orchestration` se convierte en un pipeline secuencial de stages. Cada stage tiene contrato explícito y tests propios. El estado del turno fluye en una estructura inmutable `TurnContext`.

### 2.1 Diagrama por capas

```text
INBOUND MESSAGE (worker.py dequeue)
   ↓
[ORCHESTRATOR PIPELINE]
   │
   ├─ Stage 1: LoadContextStage
   │     • Carga tenant, contact, catalog, kb, history, cart.
   │     • Produce TurnContext inmutable.
   │
   ├─ Stage 2: SafetyGatesStage
   │     • Meta 24h window check.
   │     • Domain filter (off-topic Meta Policy).
   │     • Content safety (toxic/prohibido).
   │     • Cancel/escalation explicit detection.
   │     → Si gate falla → outbound determinístico + END.
   │
   ├─ Stage 3: InboundIntentStage
   │     • Detectores consolidados (intent/*.py):
   │         - BuyingIntentClassifier
   │         - CartActionClassifier (add/modify/remove/qty)
   │         - PIIUpdateClassifier (correction, alternate phone)
   │         - VariantConfirmationClassifier
   │         - EscalationClassifier
   │     • Salida: IntentResult con tipo + confianza + matches.
   │
   ├─ Stage 4: ToolDispatchStage (pre-LLM tools determinísticos)
   │     • shipping_quote_tool, image_send_tool, order_status_tool, etc.
   │     • Si un tool resuelve → outbound determinístico + END.
   │
   ├─ Stage 5: FSMResolverStage
   │     • Resuelve display_state (ya existe en fsm/resolver.py).
   │     • Output: display_state + transition metadata.
   │
   ├─ Stage 6: StateHandlerStage (los 13 bypasses unificados)
   │     • Dispatch table: state → [Handler, Handler, ...].
   │     • Cada Handler:
   │         handle(turn_ctx) -> Optional[HandlerResult]
   │     • Si algún handler retorna result → outbound + END.
   │
   ├─ Stage 7: LLMStage
   │     • Solo se llama si STAGES 2-6 no resolvieron.
   │     • Prompt builder modular (prompt/*.py).
   │     • Cascade Gemini con router de modelos.
   │
   ├─ Stage 8: OutputValidatorStage
   │     • Anti-hallu invariants unificados:
   │         - payment_link_invariant
   │         - cart_add_invariant
   │         - summary_before_link_invariant
   │     • Reescribe response_text si viola invariante.
   │
   ├─ Stage 9: PIIPersistStage
   │     • USYNC: extracted_email/name/doc/address/shipping_phone → DB.
   │     • Re-load contact_record fresh.
   │
   └─ Stage 10: DispatchOutboundStage
         • Envía outbound vía whatsapp_sender.
         • Marca message processed.
         • Emite cart_events (summary_rendered, payment_link_created).
```

### 2.2 `TurnContext` — estructura inmutable

```python
@dataclass(frozen=True)
class TurnContext:
    # Identidad
    tenant_id: str
    conversation_id: str
    message_id: str
    contact_id: Optional[str]

    # Inbound
    inbound_text: str
    inbound_content_type: str  # text | image | audio | document

    # Estado cargado (Stage 1)
    contact_record: dict
    cart: Optional[dict]           # con .items
    catalog: list[dict]
    kb_docs: list[dict]
    history: list[dict]            # ≤25 msgs
    history_for_fsm: list[dict]    # incluye inbound actual
    ai_agent: dict
    tenant_config: dict            # tenant_name, store_type, schedule, etc.

    # FSM (Stage 5)
    display_state: str
    buying_intent: bool
    shipping_quoted: bool
    carrier_selected: bool
    order_confirm_pending: bool

    # Intent (Stage 3)
    intent: Optional['IntentResult']

    # Side-channels
    supabase: Client               # único acceso DB
    logger: logging.Logger
```

**Contrato**: `TurnContext` es inmutable. Stages que necesitan mutar producen un NUEVO `TurnContext` enriquecido (`turn_ctx = turn_ctx.with_intent(...)`). Esto elimina el problema del `contact_record` stale que causó Bug A.

### 2.3 `HandlerResult` — output de handlers

```python
@dataclass(frozen=True)
class HandlerResult:
    outbound_text: str
    handler_name: str                  # para audit log
    emit_events: list[CartEvent] = field(default_factory=list)
    mark_processed: bool = True
    skip_remaining_stages: bool = True
```

### 2.4 Estructura de directorios objetivo

```text
services/ai-orchestrator/
├── orchestrator.py                    # ≤1500 LOC: pipeline runner
├── turn_context.py                    # TurnContext dataclass + builders
├── stages/                            # NUEVO
│   ├── __init__.py
│   ├── base.py                        # Stage Protocol + StageResult
│   ├── load_context.py
│   ├── safety_gates.py
│   ├── inbound_intent.py
│   ├── tool_dispatch.py
│   ├── fsm_resolver.py                # delgado, delega a fsm/resolver.py
│   ├── state_handler.py
│   ├── llm.py
│   ├── output_validator.py
│   ├── pii_persist.py
│   └── dispatch_outbound.py
├── fsm/                               # YA EXISTE — extender
│   ├── states.py                      # ✓
│   ├── resolver.py                    # ✓
│   ├── address.py                     # ✓
│   ├── state_renderers.py             # → absorbido por handlers/
│   └── handlers/                      # NUEVO (Sem 1)
│       ├── __init__.py
│       ├── base.py                    # StateHandler Protocol
│       ├── dispatcher.py              # priority dispatch table
│       ├── needs_consent.py
│       ├── needs_email.py
│       ├── needs_name.py
│       ├── needs_document.py
│       ├── needs_direction.py
│       ├── needs_shipping_city.py
│       ├── awaiting_carrier_selection.py
│       ├── ready_for_summary.py
│       ├── awaiting_order_confirmation.py
│       ├── post_payment_link.py
│       └── catalog_mode.py            # mayoritariamente "pass to LLM"
├── intent/                            # NUEVO (Sem 2)
│   ├── __init__.py
│   ├── base.py                        # IntentClassifier Protocol
│   ├── buying_intent.py
│   ├── cart_action.py
│   ├── pii_update.py
│   ├── variant_confirmation.py
│   ├── escalation.py
│   └── lexicons/                      # tokens consolidados
│       ├── verbs_es_co.py             # vender, vendeme, peudes vender, etc.
│       └── markers.py
├── outbound/                          # NUEVO (Sem 3)
│   ├── __init__.py
│   ├── invariants.py                  # anti-hallu unificado
│   ├── format_wa.py                   # WhatsApp formatting
│   └── send.py                        # delgado, wraps whatsapp_sender
├── prompt/                            # YA EXISTE — extender (Sem 4-6)
│   ├── builder.py                     # ✓
│   └── blocks/                        # NUEVO
│       ├── identity.py
│       ├── customer_context.py
│       ├── catalog.py
│       ├── kb_rag.py
│       ├── fsm_instructions.py
│       └── safety_rules.py
├── cart/                              # YA EXISTE — extender (Sem 7)
│   ├── events.py                      # ✓
│   └── turn_view.py                   # NUEVO: load_turn_cart_view() único
├── safety/                            # YA EXISTE
├── tools/                             # YA EXISTE
├── llm/                               # NUEVO (Sem 4-6)
│   ├── invoke.py                      # cascade router
│   ├── parsed_response.py             # Pydantic schema
│   └── degraded.py                    # review_queue handoff
└── lib/                               # helpers compartidos
    ├── phone.py                       # canonicalizer único
    └── text.py                        # normalize_text, etc.
```

---

## 3. Migration plan strangler-fig (8 semanas)

### Principios operativos

1. **Monolito vive durante todo el refactor.** Cada semana extrae UNA capa. La capa extraída se invoca DESDE `build_and_run_orchestration`. El código viejo se reemplaza, NO se duplica.
2. **Tests verdes al cierre de cada semana.** Sin excepción. Si rompo regresión, revierto y replantee.
3. **Feature freeze sobre `phase-0-pre-prod`** durante el refactor. Solo P0 bugs críticos. Features nuevas esperan al cierre Sem 8.
4. **Smoke UAT real al cierre de cada semana.** Conversación end-to-end con usuario nuevo + conocido. Si rompo el bot, revierto.
5. **ADRs por extracción mayor.** Cada nueva capa = 1 ADR documentando contrato.

### Semana 1 — State Handler Layer (los 13 bypasses unificados)

**Entrega**: `fsm/handlers/` con 12 handlers + dispatcher con priority table.

**Refactor concreto**:
- Cada bypass actual identificable en `build_and_run_orchestration` se convierte en un `StateHandler`.
- Handler signature: `def handle(turn_ctx: TurnContext) -> Optional[HandlerResult]`.
- Dispatcher: `dispatch(turn_ctx) -> Optional[HandlerResult]` itera handlers en orden y retorna el primero que no-None.
- Orchestrator: reemplaza los 13 sitios con UNA llamada `result = handler_dispatcher.dispatch(turn_ctx)`.

**Métricas done**:
- 12 archivos handlers (~100-200 LOC c/u).
- 1 dispatcher (~100 LOC).
- Orchestrator `build_and_run_orchestration` reduce ~1500 LOC.
- Tests: suite verde + 50+ tests nuevos por handler.
- Smoke UAT: cliente nuevo + cliente conocido = 100% PASS.

### Semana 2 — Intent Classification Layer

**Entrega**: `intent/` con classifiers consolidados.

**Refactor concreto**:
- 17 detectores `_detect_*` y `_has_*` se consolidan en 5 classifiers.
- Cada classifier expone: `classify(turn_ctx) -> IntentResult`.
- Lexicons (tokens, markers) se extraen a `intent/lexicons/`.
- Orchestrator invoca classifiers una vez por turn, resultado se inyecta en TurnContext.

**Métricas done**:
- 5 classifiers + 2-3 archivos de lexicons.
- 17 detectores legacy borrados.
- Tests: ~80 tests nuevos cubriendo cada classifier.
- Smoke UAT: igual flujo, mismas respuestas.

### Semana 3 — Output Validator Layer

**Entrega**: `outbound/invariants.py` con anti-hallu unificado.

**Refactor concreto**:
- Anti-hallu payment + cart-add + summary_before_link en UN módulo.
- Cada invariante con contrato `validate(turn_ctx, candidate) -> ValidationResult`.
- ValidationResult con `outcome: PASS | REWRITE | BLOCK` + `replacement_text`.
- Stage 8 del pipeline aplica TODAS las invariantes secuencialmente.

**Métricas done**:
- 5-7 invariantes formalizadas.
- Tests: golden suite de patrones LLM-lie con respuesta esperada del validador.

### Semanas 4-6 — Prompt Builder Modular

**Entrega**: `prompt/blocks/` componibles.

**Refactor concreto**:
- `_build_system_prompt` (778 LOC) → 7 bloques composables.
- Cada bloque: `render(turn_ctx, tenant_config) -> str`.
- Builder principal compone bloques en orden + cache de bloques estáticos.

**Métricas done**:
- 7 archivos block (~100 LOC c/u).
- `_build_system_prompt` legacy borrado.
- Tests: snapshot tests por bloque + integration test del prompt completo.

### Semana 7 — Cart Operations Layer + LLM Stage

**Entrega**: `cart/turn_view.py` + `llm/` módulo formal.

**Refactor concreto**:
- 28 lecturas dispersas de `get_cart_with_items` reducidas a 1 carga por turn vía `load_turn_cart_view(turn_ctx)`.
- LLM invocation extraída a `llm/invoke.py` con cascade router + degraded path explícito.

**Métricas done**:
- 1 helper único de cart-load.
- LLM cascade + degraded en módulo aislado.

### Semana 8 — Pipeline Runner + Cierre

**Entrega**: orchestrator.py final ≤1500 LOC como pipeline de stages.

**Refactor concreto**:
- `build_and_run_orchestration` se vuelve:
  ```python
  async def build_and_run_orchestration(supabase, message_id, ...):
      turn_ctx = await LoadContextStage().run(...)
      for stage in PIPELINE_STAGES:
          result = await stage.run(turn_ctx)
          if result.short_circuit:
              return
          turn_ctx = result.turn_ctx
  ```
- ~300 LOC de runner + helpers.
- Resto del archivo: imports + módulo-level constants legacy a deprecar.

**Métricas done**:
- orchestrator.py ≤1500 LOC.
- Pipeline runner ≤300 LOC.
- Suite verde 100%.
- UAT S1-S26 dual-mode 100% PASS.
- Documentación final: este doc + ADR-0017 cerrado.

---

## 4. Test strategy — zero regresión

### 4.1 Capas de defensa

1. **Suite unit existente (2,184 tests)** — protege comportamiento actual. Verde antes y después de cada extracción.
2. **Smoke UAT real semanal** — conversación end-to-end con stack local. Cliente nuevo + cliente conocido.
3. **Behavioral golden tests** — capturas de conversaciones de referencia (e.g. la 00:23 buena, la 10:41 que rompió). Tests verifican que el bot responde igual o mejor a inputs idénticos.
4. **Contract tests por stage** — cada stage tiene tests que verifican contrato (input → output) sin depender del resto del pipeline.

### 4.2 Validación por extracción

Cada semana cierra con:

```bash
# Suite completa
python3.11 -m pytest tests/ --tb=line -q

# UAT scenarios afectados
bash scripts/uat/run_smoke.sh

# Métricas
bash scripts/validate.sh --ci
```

**Sin verde no se mergea a `phase-0-pre-prod`. Sin smoke UAT verde no se cierra la semana.**

### 4.3 Rollback strategy

- Cada extracción mayor = 1 commit atómico.
- Branch `phase-1-orchestrator-refactor` separada de `phase-0-pre-prod`.
- Si rompo regresión irrecuperable: `git reset --hard <commit-anterior>` en branch refactor; el monolito en `phase-0-pre-prod` sigue intacto.
- **Git ES el backup.** No se hace copia filesystem. La historia git completa preserva el estado de cualquier commit anterior.

---

## 5. Lo que NO cambia (invariantes preservados)

Para evitar scope creep, lista explícita de **NO-targets** del refactor:

- ❌ Cart-as-SoT (ADR-0011): se mantiene tal cual.
- ❌ FSM states canónicos (`fsm/states.py`): mismos estados, mismas transiciones.
- ❌ Wompi payment lifecycle: no se toca.
- ❌ Envia client + tier-2 detection: no se toca.
- ❌ Habeas Data audit log: no se toca.
- ❌ Tenant isolation (RLS + service_role guards): no se toca.
- ❌ Comportamiento externo del bot: cliente debe percibir IDÉNTICO bot (o mejor).
- ❌ Tests existentes (2,184): todos deben seguir verdes sin modificación de assertions.

**Si una extracción requiere tocar uno de los anteriores, se pausa, se documenta como ADR aparte, y se decide explícitamente.**

---

## 6. Comparación cuantitativa antes/después

| Métrica | Hoy (78f6ac6) | Target Sem 8 | Reducción |
|---|---|---|---|
| `orchestrator.py` LOC | 10,262 | ≤1,500 | -85% |
| `build_and_run_orchestration` LOC | 3,589 | ≤300 | -92% |
| Funciones top-level en orchestrator | 124 | ~20 | -84% |
| Bypasses pre/post-LLM dispersos | 13 | 0 (centralizado en handlers) | -100% |
| Detectores tokenizados frágiles | 17 | 5 classifiers | -70% |
| Listas hardcoded de tokens | 23 | ~5 lexicons centralizados | -78% |
| `_build_order_summary_text` call sites | 10 | 1 (vía handler único) | -90% |
| `get_cart_with_items` call sites | 28 | 1 (vía `load_turn_cart_view`) | -96% |
| Imports tardíos dentro de funciones | 24 | 0 | -100% |

**Cobertura de tests**: 2,184 → 2,400+ (más tests nuevos por handler/classifier/invariant).

---

## 7. Riesgos y mitigaciones

| # | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | Regresión silente en bypass extraído | Media | Alto | Suite 2,184 tests verde + smoke UAT por semana |
| R2 | Refactor toma >8 semanas | Media | Medio | Feature freeze + métricas semanales; reportar slip a Sem 3 si pasa |
| R3 | Encontrar dependencias ocultas (acoplamiento implícito) | Alta | Bajo | Imports tardíos hacen el acoplamiento visible al refactor. Tests destapan dependencias |
| R4 | Cambio comportamiento sutil del LLM por orden de stages distinto | Baja | Alto | Behavioral golden tests capturan respuestas de referencia |
| R5 | Discusión sobre "exactamente cuál bypass va dónde" | Alta | Bajo | Decisiones documentadas en commits + ADR; no re-litigar |
| R6 | Resistencia a feature freeze | Media | Medio | Acuerdo explícito con founder: P0 bugs solo |
| R7 | Bug producción real durante refactor | Media | Alto | `phase-0-pre-prod` sigue siendo branch productiva intocada; fixes ahí |

---

## 8. Definición de "done" — Sem 8 (criterios de cierre)

Sin TODOS estos criterios, no se cierra el refactor:

- [ ] orchestrator.py ≤ 1,500 LOC.
- [ ] `build_and_run_orchestration` ≤ 300 LOC.
- [ ] 10 stages implementadas con contratos explícitos.
- [ ] 12 state handlers consolidados (0 bypasses dispersos en orchestrator core).
- [ ] 5 intent classifiers consolidados (0 `_detect_*` dispersos).
- [ ] 1 `load_turn_cart_view` (0 `get_cart_with_items` directos en orchestrator).
- [ ] 1 `_build_order_summary_text` call (vía handler único READY_FOR_SUMMARY).
- [ ] 0 imports tardíos dentro de funciones del orchestrator.
- [ ] Suite tests verde (≥2,400 tests).
- [ ] UAT S1-S26 dual-mode 100% PASS.
- [ ] Smoke UAT real con stack local: cliente nuevo + conocido = flujo perfecto.
- [ ] ADR-0017 (este refactor) cerrado.
- [ ] `docs/architecture/orchestrator-refactor-target.md` (este doc) marcado COMPLETED.
- [ ] PR `phase-1-orchestrator-refactor` → `phase-0-pre-prod` aprobada.

---

## 9. Operatividad y branching

- **Branch de trabajo**: `phase-1-orchestrator-refactor` (creada desde `phase-0-pre-prod` en commit `78f6ac6`).
- **Branch productiva**: `phase-0-pre-prod` sigue siendo la fuente de producción durante el refactor.
- **Merge a `phase-0-pre-prod`**: solo al cierre Sem 8 con todos los criterios done.
- **Hotfixes de producción durante refactor**: se aplican a `phase-0-pre-prod` directamente y se rebasea `phase-1-orchestrator-refactor` semanalmente para incorporarlos.

**Git ES el backup**: cada commit está preservado. `git reflog`, `git diff <commit>..<commit>`, `git reset --hard <commit>` son las herramientas. No se hace copia filesystem.

---

## 10. Próximos pasos inmediatos

1. Crear ADR `docs/adr/0017-orchestrator-strangler-fig-refactor.md` (este refactor formalizado).
2. Iniciar Sem 1: extracción de State Handler Layer.
   - Crear `fsm/handlers/base.py` con Protocol + types.
   - Crear `fsm/handlers/dispatcher.py`.
   - Migrar bypass por bypass desde `build_and_run_orchestration`.
   - Tests por cada handler migrado.
3. Cierre Sem 1: smoke UAT + métricas.

Documento vivo. Actualizar al cierre de cada semana con métricas reales.

---

## Apéndice A — Progreso Sem 1 (en curso)

### Commits del refactor

| Commit | Fecha | Entrega | LOC orchestrator | Tests |
|---|---|---|---|---|
| `8efcf19` | 2026-05-21 | Doc + ADR-0017 | 10,262 | 2,184 |
| `554cd35` | 2026-05-21 | Sem 1.1: base + dispatcher + 2 handlers | 10,229 | 2,201 (+17) |
| `b1097a2` | 2026-05-21 | Sem 1.2: READY_FOR_SUMMARY + correction | 10,215 | 2,209 (+8) |
| (pendiente Sem 1.3+) | — | NEEDS_CONSENT + handlers restantes | — | — |

### Handlers migrados a `fsm/handlers/` (4 de ~12 objetivo Sem 1)

- ✅ `needs_shipping_city.py` — bypass commit 18a3a5d (cart vacío→variante, armado→ciudad).
- ✅ `awaiting_carrier_selection.py` — bypass commit 18a3a5d (recordatorio Económica/Rápida).
- ✅ `ready_for_summary.py` — bypass legacy `[BYPASS] READY_FOR_SUMMARY → resumen determinístico`.
- ✅ `ready_for_summary_correction.py` — bypass legacy `GAP-1 corrección de datos`.

### Bypasses restantes a migrar (Sem 1.3+)

- ⏳ `NEEDS_CONSENT` bypass (línea 8693 legacy).
- ⏳ `shipping_phone update` bypass (línea 8943+) — complejo, posiblemente Sem 3.
- ⏳ Anti-hallu cart-add bypass (línea ~9930) — posiblemente Sem 3 (OutputValidator Layer).
- ⏳ Anti-hallu payment_link bypass (línea ~9890) — Sem 3.

### Estado del refactor (snapshot)

- **Branch**: `phase-1-orchestrator-refactor` (separada de `phase-0-pre-prod`).
- **orchestrator.py LOC**: 10,262 → **10,215** (-47, -0.5%).
- **Tests verde**: 2,184 → **2,209** (+25).
- **Bypasses migrados**: 4 de los 13 dispersos legacy.
- **Funciones top-level orchestrator**: 124 (sin cambio aún; reducción esperada al borrar helpers que solo usa el monolito en Sem 7+).
- **Zero regresión verificable**: handlers tienen guards 100% equivalentes a bypasses legacy. Comportamiento externo del bot idéntico.

### Decisiones de diseño confirmadas durante Sem 1

1. **`TurnInput` inmutable como dataclass(frozen=True)**: handlers no pueden mutar input. Si necesitan state derivado, lo computan localmente. Esto elimina el problema de `contact_record` stale entre handlers.
2. **Auto-registro al importar handler**: cada handler hace `register(MyHandler())` al final del módulo. El orchestrator solo necesita `import fsm.handlers.X` para activarlo. Trade-off: requiere imports explícitos en tests, pero hace el wiring declarativo y observable vía `get_handlers_for_state(state)`.
3. **Priority-based ordering dentro del mismo state**: sub-handlers especializados (correction = 50) corren ANTES del handler default (summary = 100). Permite extender comportamiento sin modificar el default.
4. **Late imports DENTRO de handlers**: cada handler importa de `orchestrator` los helpers que necesita en su función `handle()`. Esto evita ciclo de imports al inicializar fsm/handlers (orchestrator todavía importa fsm.handlers para registro). En Sem 7-8 los helpers se moverán a sus propios módulos y los late imports desaparecerán.
5. **Degradación graceful en dispatcher**: si un handler lanza excepción, dispatcher loggea WARNING y prueba siguiente. NUNCA un handler roto colapsa el turn.

### Lecciones operativas

- **`asyncio.get_event_loop()` está deprecated en Python 3.11**: usar `asyncio.new_event_loop().run_until_complete()` en helpers de test async.
- **Registry global + tests aislados con clear_registry**: requiere snapshot/restore en setUp/tearDown para no contaminar otros tests del proyecto. Patrón implementado en `tests/test_handler_dispatcher.py`.
- **Tests de handlers reproducen bugs runtime del founder UAT**: ej. `test_cart_vacio_con_productos_presentados_y_mencion_filtra` reproduce conv bae0f6a2 con "1 Coco y 1 Lavanda" y verifica filtrado de productos mencionados. Es behavioral golden test.

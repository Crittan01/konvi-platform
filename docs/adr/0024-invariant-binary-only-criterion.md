# ADR-0024 — Criterio invariant binario/determinístico para `apply_invariants`

**Status**: Accepted (2026-06-23)
**Deciders**: Founder + AI Architect
**Context**: Root-cause analysis workflow `wujbdgrhk` 2026-06-23 — causa raíz crónica improvisación bot Inbox
**Sellado en**: Q2 sesión 2026-06-23 (founder OK quality-first)

---

## Contexto

El sistema `apply_invariants` (`services/ai-orchestrator/agentic/dispatcher.py:2100`) ejecuta una pipeline de validaciones post-LLM (o pre-tool) que pueden REWRITE outbound, BLOCK tool execution, o LOG warnings. Actualmente (rev. 110) hay 13 invariants:

- `PIISaveTruthfulnessInvariant` (binaria: tool_call_log mostró save_contact_field con success?)
- `PaymentCoherenceInvariant` (binaria: payment_link existe? amount match?)
- `CanonicalCategoriesInvariant` (binaria: categoria ∈ enum?)
- `FakeEscalationInvariant` (binaria: escalation_event registrado?)
- Otros 9 binarios similares.

**Patrón común**: todas verifican propiedades **decidibles sin parser NLP semántico**: existencia de registro DB, igualdad numérica, pertenencia a enum, presencia de field obligatorio.

En la sesión root-cause 2026-06-23 surgió la pregunta: ¿deberíamos agregar `BusinessOpsTruthfulnessInvariant` y `ContactAddressTruthfulnessInvariant` para detectar cuando el bot inventa horarios/direcciones?

## Decisión

**Adoptar el criterio "invariant solo si verificación binaria/determinística"**:

> Una invariant puede entrar a `apply_invariants` solamente si su lógica de validación se reduce a una proposición decidible mediante:
> - **Pertenencia a conjunto** (tool_id ∈ catalog_results recientes, categoria ∈ enum)
> - **Existencia de registro** (consent_audit_log row existe? cart_event success?)
> - **Comparación numérica** (cart.total == payment.amount?)
> - **Lookup directo en DB / tool log** (tool_call_log último turn tiene `name='X'`?)
> - **Pattern regex deterministic** sobre token discreto (UUID format, ISO date format) — NO sobre prosa semántica.

**Quedan PROHIBIDAS por construcción** las invariants que requieran:
- Parser NLP semántico en español/inglés ("¿el bot dijo el horario correcto?")
- Inferencia de equivalencia conceptual ("'lunes-viernes' es equivalente a 'L-V' o 'L a V'?")
- Detección de hechos cualitativos ("¿el bot prometió algo razonable?")

## Justificación

### 1. Mantenibilidad — O(1) vs O(N²)

Una invariant binaria cuesta **O(1) maintenance**: si la fuente de verdad (DB schema) cambia, la invariant se actualiza UNA vez. Una invariant semántica cuesta **O(N²)**: por cada campo nuevo (horario, dirección, política devolución, tiempos envío...) y por cada tenant con vocabulario distinto, requiere extender el parser. Crecimiento exponencial.

### 2. False positives degradan UX

Parser NLP en español tiene tasa false-positive >5% incluso en estado del arte 2026 (verificado en literatura citada en workflow `wujbdgrhk` LLM behavior analysis). Una invariant que bloquea outbound legítimos por mal parsing causa silencios bot percibidos por cliente como falla. Peor UX que la improvisación que pretendía curar.

### 3. Causa raíz vive arriba

Como documenta el root-cause analysis de la sesión: el bot improvisa porque el **dato falta en el prompt** (causa raíz P1), no porque su output sea malicioso. La cura legítima es **prevent** (inyectar dato al prompt = upstream), no **cure** (parsear output = downstream).

**Excepción técnica**: Gemini Flash improvisa incluso con dato presente en algunos casos (P4 transversal, ej. horarios — sesgo training data). La cura de P4 NO es invariant semántica — es **prompt reordering + XML tags + posible cambio modelo** (Fase 3 del roadmap).

### 4. Bandage vs cure documented

NeMo Guardrails docs oficial: *"rails are not factual correctness verification — they are control flow guards."* Frameworks LLM productivos NO recomiendan invariants semánticas como cura raíz.

## Consecuencias

### Positivas

- Pipeline `apply_invariants` permanece manageable a largo plazo (crecimiento linear con features nuevas, no exponencial).
- Decisiones futuras de tooling tienen criterio claro: "¿es decidible binario?" → SÍ entra. NO → resolver upstream.
- Maintenance debt baja: no acumular parsers NLP frágiles que fallan silenciosamente.

### Negativas (trade-offs aceptados)

- El bot puede improvisar sobre datos presentes en prompt (P4 transversal). Cura raíz no es invariant — es prompt design + model selection.
- Algunos bugs UX visibles tardarán más en cerrar (Fase 3 Slim + XML tags + posiblemente Claude tier_1 EXPLORING).
- Founder acepta este trade-off: calidad sostenida > velocidad fix por whack-a-mole.

### Triggers para revisitar

- Si un proveedor de invariants framework publica parser NLP español con FP <0.5% verificado independent → re-evaluar Tier 2 ("invariants con confidence threshold").
- Si volumen tenants >50 con vocabularios divergentes hace prompt-design upstream impractical → considerar invariants binarias específicas por tenant config.

## Implementación

### Invariants APROBADAS bajo este criterio (existentes rev. 110)

13 invariants actuales binarias — mantener.

### Invariant NUEVA Fase 2 finiquito 2026-06-23

`ToolIdReferentialIntegrityInvariant` (decidible binaria):
- Lógica: ¿el `product_id` UUID pasado a `add_to_cart` / `update_cart_item` pertenece al conjunto de UUIDs retornados por `list_catalog` en los últimos N turns del mismo `conversation_id`?
- Decidible: sí o no. SET pertenencia.
- Cierra BUG-CART-1 (LLM inventaba UUIDs).
- Pre-tool invariant (novedad arquitectónica vs los 13 post-LLM existentes).

### Invariants RECHAZADAS bajo este criterio

- `BusinessOpsTruthfulnessInvariant` (rechazada — requiere parser horarios/direcciones)
- `ContactAddressTruthfulnessInvariant` (rechazada — requiere parser direcciones)
- Cualquier `XxxTruthfulnessInvariant` que valide prosa semántica.

## Referencias

- Workflow root-cause `wujbdgrhk` synthesis sections 3-4 (matriz arquitectónica + decision tree)
- Adversarial review `adversarial-invariants-first` (refutación invariants-as-primary-cure)
- Memoria `feedback_quality_first_over_effort.md` (quality > effort principle)
- NeMo Guardrails docs (`docs.nvidia.com/nemo/guardrails`)
- ADR-0023 Model B (predecessor sealing pattern Q1-Q10)

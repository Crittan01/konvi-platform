# Gemini (Google AI) — LLM del bot (documento canónico)

> Estado: VIGENTE · **Revalidación contra doc oficial vigente (Track 6): 2026-08-22** (fetch live ai.google.dev — URLs citadas por fila en la matriz de investigación).
> Stack: `google-genai` SDK · primary `gemini-3.1-flash-lite` · fallback `gemini-3.5-flash` · path `generate_content` + tool loop manual (`services/ai-orchestrator/agentic/agent.py`, `llm_invoke.py`).

## Veredicto de la revalidación 2026-08-22

- **Nada de lo que usamos está deprecado**, pero el modelo prod tiene EOL anunciado: `gemini-3.1-flash-lite` **shutdown 2027-05-07** ([deprecations](https://ai.google.dev/gemini-api/docs/deprecations)) → migración a `gemini-3.5-flash-lite` calendarizada Q4-2026 (ya parametrizada por env `GEMINI_MODEL`; el reemplazo es ~20% más caro en input, 67% en output — presupuestar).
- **El ahorro por context caching NO está garantizado para flash-lite**: la tabla oficial de implicit caching omite todos los modelos Lite, y el mínimo de tokens de explicit caching no está publicado en la guía vigente. La auditoría del bot asumía el ahorro → la decisión correcta es **medir primero** (fase 0 implementada, abajo).
- Nuestra arquitectura (`generateContent` + tool loop manual + thought signatures manuales) es el path estable recomendado para producción; **Interactions API es beta con breaking changes y sin explicit caching/Batch** — no migrar.

## Adoptado en esta revalidación (2026-08-22)

| Cambio | Detalle |
|---|---|
| **Telemetría de uso desagregada (fase 0 caching)** | `agent._extract_usage` + acumulación por turno + columnas `prompt_tokens`/`cached_tokens`/`thoughts_tokens` en `agentic_shadow_log` (migración `20260822130100`, insert degrade-safe). Con 1-2 semanas de tráfico: ¿flash-lite hace implicit caching? ¿hit rate por estado FSM? |
| **SDK bump 2.11.0 → 2.19.0** | `requirements.txt` — prerrequisito de VALIDATED y de la telemetría completa |
| **`tool_config` VALIDATED tras flag** | `AGENTIC_TOOL_VALIDATED_ENABLED=true` (default false) — constrained decoding de function calls: elimina argumentos malformados POR CONSTRUCCIÓN (hoy `MALFORMED_FUNCTION_CALL` se trata con retry: síntoma, no causa). Canary en STG local; default solo tras medir latencia/calidad |
| **Correcciones documentales en código** | `llm_invoke.py` (2.5-flash NO tiene EOL anunciado; 3.1-flash-lite sí: 2027-05-07) · `llm_router.py` (precios reales 3.x: lite $0.25/$1.50, 3.5-flash $1.50/$9.00, cached input $0.025) · `kb_tool.py` (embeddings: solo `gemini-embedding-2` vigente) |

## Decisión explícita: prefijo del prompt NO reordenado (aún)

La estabilización del prefijo (bloques estáticos primero, dinámicos al final) multiplicaría los hits de caching — pero reordenar el system prompt puede cambiar el comportamiento del bot, y el beneficio depende de que flash-lite haga implicit caching (no confirmado por la doc). **Se difiere a tener la telemetría de la fase 0** (cached_tokens sostenido > 0) y al harness comportamental B-3 para medir el impacto conversacional del reorden. No es prudente tocar el prompt de dinero sin esas dos redes.

## Diseñado para el futuro (puntos de extensión, con gates)

| Ítem | Gate de adopción |
|---|---|
| **Explicit caching** (`CachedContent` por combinación modelo×estado FSM×subset tools; storage ~$0.01/h) | La telemetría muestra implicit hit rate bajo Y `cachedContents.create` acepta ~10k tokens en flash-lite (verificación empírica de 5 min — el mínimo no está publicado) |
| **Priority inference** (`service_tier="priority"`, downgrade graceful facturado Standard) | 503 "high demand" sostenidos tras la cascada actual; env flag `GEMINI_SERVICE_TIER` ya diseñado |
| **Flex/Batch inference (50% off)** | Solo trabajo diferible (crons, re-index KB, regresiones offline) — NUNCA el turno síncrono del chat (latencia de minutos) |
| **Grounding con Google Search** | OFF por defecto (deriva de producto + costo variable; choca con "LLM nunca fuente de verdad"). Solo tool opt-in por estado con tope diario si negocio lo pide |
| **Migración a 3.5-flash-lite** | Antes de 2027-05-07; canary de calidad + presupuesto nuevo (sube input/output) |
| **Interactions API** | Re-evaluar en GA (simplificaría el tool loop; hoy perderíamos explicit caching y Batch) |

## Confirmado alineado (sin cambio)

- Subset de tools por estado FSM (la doc oficial recomienda 10-20 tools activos máx — ya implementado rev. 109).
- Thought signatures round-trip manual en generateContent (correcto y necesario; en Interactions las maneja el SDK).
- Cascada con backoff + deadline 100s conforme a la guía oficial de errores (429/503).
- Streaming NO aplica: WhatsApp no renderiza incremental (el outbound es un mensaje completo).

## Referencias oficiales (fetcheadas 2026-08-22)

- [caching](https://ai.google.dev/gemini-api/docs/caching) · [api/caching](https://ai.google.dev/api/caching) · [tokens](https://ai.google.dev/gemini-api/docs/tokens) · [pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [function-calling](https://ai.google.dev/gemini-api/docs/function-calling) (modos auto/any/none/validated) · [structured-output](https://ai.google.dev/gemini-api/docs/structured-output)
- [deprecations](https://ai.google.dev/gemini-api/docs/deprecations) (EOL 3.1-flash-lite 2027-05-07) · [model page 3.1-flash-lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)
- [priority-inference](https://ai.google.dev/gemini-api/docs/priority-inference) · [flex-inference](https://ai.google.dev/gemini-api/docs/flex-inference) · [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) · [interactions](https://ai.google.dev/gemini-api/docs/interactions) (beta) · [google-search grounding](https://ai.google.dev/gemini-api/docs/google-search)

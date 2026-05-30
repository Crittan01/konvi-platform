# ADR-0017 — Multi-Agent System per Tenant (Templates + AI-Assisted Generation)

**Estado**: Aprobado · **Sesión**: 2026-05-29 · **Autores**: Founder + AI Architect

## Contexto

Hoy cada tenant tiene **un único bot** (`Sara Camila` por defecto en KAIU). La
estructura actual (post-auditoría 2026-05-29):

- `tenants.*` = IDENTIDAD del negocio (qué/por qué, filosofía, tono).
- `ai_agents.*` = COMPORTAMIENTO del bot (cómo actúa: nombre, prompt maestro,
  guardrails, rol funcional).

A futuro un tenant querrá tener **varios agentes especializados** (Ventas,
Soporte, Marketing, Reclamos) con diferentes:

- Personalidad (nombre + tono).
- Prompt maestro (cómo razonar).
- Subset de tools (qué puede hacer; ej. Soporte NO puede `add_to_cart`).
- Subset de FSM states (qué etapas atiende).

Además debería ser fácil para el operador:

- **Elegir un rol** y obtener un *template* pre-armado.
- **Auto-generar** el prompt maestro con IA, basándose en la configuración
  ya capturada del negocio (filosofía + catálogo).

## Decisión

Aceptamos construir un sistema multi-agente per tenant con:

1. **Tabla `ai_agents`** (extendida): soporta N agentes por tenant. Un único
   `is_default=true` por tenant. Campos `tools_allowed` y `fsm_states_allowed`
   permiten subsets per agente.

2. **Templates per rol** (código global, `services/ai-orchestrator/lib/
   agent_templates.py`): 5 templates base (sales, support, marketing, claims,
   custom). Cada uno expone `name_default`, `skeleton` (role_description
   inicial), `tools_allowed`, `fsm_states_allowed`. Los templates son
   GLOBAL (no per tenant) porque son patrones probados.

3. **AI suggest endpoint** (`POST /api/v1/ai-agents/suggest`): genera un
   `role_description` personalizado leyendo la config del tenant (filosofía
   + catálogo + horarios) + rol seleccionado + template skeleton. Devuelve
   un draft editable. Usa Gemini Flash (mismo cascade ya existente).

4. **UI** (`/dashboard/ai-agents`):
   - Lista de agentes del tenant (tabla con default + role + actions).
   - Drawer "Crear agente": selector de rol → carga template → opcional
     botón "✨ Sugerir con IA" → editable → guardar.
   - Edición de agente existente: drawer con campos.

5. **Router pre-LLM** (`agentic/agent_router.py`): clasifica el inbound por
   heurística (sin Gemini, cero costo runtime) y elige el agente apropiado.
   Si el tenant tiene 1 agente, fallback al default (backward-compat).

6. **Enforcement de `tools_allowed`**: el agentic dispatcher pasa
   `allowed_tools` ya filtrado por el agente activo. Las tools fuera del
   subset NO se exponen al LLM (no se les puede invocar por accidente).

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│ UI Tenant Console                                            │
│ ─────────────────────                                        │
│ /dashboard/ai-agents:                                        │
│   • Tabla agentes [Default · Role · Actions]                 │
│   • [+ Crear agente]                                         │
│     → Drawer: Selector rol → load template skeleton          │
│       → [✨ Sugerir con IA] → fetch POST /api/v1/ai-agents/  │
│          suggest → role_description draft                    │
│       → Editar + Guardar (UPSERT ai_agents row)              │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ Backend                                                       │
│ ──────────────                                                │
│ services/ai-orchestrator/lib/agent_templates.py              │
│   AGENT_TEMPLATES dict {sales|support|marketing|claims|custom}│
│     • name_default                                            │
│     • skeleton (role_description seed)                        │
│     • tools_allowed (list of tool names)                      │
│     • fsm_states_allowed (list of state names)                │
│                                                               │
│ services/api/routers/ai_agents.py                            │
│   POST /api/v1/ai-agents/suggest                             │
│     → Lee tenant_id + role from body                          │
│     → Carga tenants.* + catalog summary                       │
│     → Carga template del rol                                  │
│     → Meta-prompt a Gemini (cascade existente)                │
│     → Return { suggested_role_description }                   │
│                                                               │
│ services/ai-orchestrator/agentic/agent_router.py             │
│   classify_intent_to_agent(inbound, tenant_id) → agent dict   │
│     • Heurística (regex/keyword) clasifica intent             │
│     • Returns agente matching el rol, o default               │
│     • Backward-compat: 1 agente → siempre default             │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ Database (single schema, no nuevas tablas)                   │
│ ──────────────────────────────────────────                   │
│ ai_agents (existente, ya extendido):                         │
│   • id, tenant_id, name, role, role_description              │
│   • strict_guardrails, is_default                            │
│   • tools_allowed JSONB, fsm_states_allowed JSONB            │
│   • persona_block (futuro)                                   │
│                                                               │
│ UNIQUE INDEX (tenant_id) WHERE is_default = TRUE             │
│   → garantiza exactamente 1 default per tenant               │
└─────────────────────────────────────────────────────────────┘
```

## Templates (semilla)

```python
AGENT_TEMPLATES = {
  "sales": {
    "name_default": "Asesor de Ventas",
    "skeleton": "Eres {agent_name}, asesor de ventas de {tenant_name} ...",
    "tools_allowed": ["list_catalog", "add_to_cart",
                      "generate_payment_link", "get_recent_orders",
                      "kb_query", "send_product_image"],
  },
  "support": {
    "name_default": "Asesor de Soporte",
    "skeleton": "Eres {agent_name}, especialista en soporte ...",
    "tools_allowed": ["get_recent_orders", "kb_query",
                      "escalate_to_human"],
  },
  "marketing": {
    "name_default": "Marketing Bot",
    "skeleton": "Eres {agent_name}, especialista en outbound ...",
    "tools_allowed": ["kb_query", "list_catalog"],
  },
  "claims": {
    "name_default": "Especialista Reclamos",
    "skeleton": "Eres {agent_name}, especialista en reclamos ...",
    "tools_allowed": ["get_recent_orders", "kb_query",
                      "escalate_to_human"],
  },
  "custom": {
    "name_default": "Asistente",
    "skeleton": "",
    "tools_allowed": None,  # None = todas
  },
}
```

## AI generativa — Meta-prompt

```python
meta = f"""
Genera un role_description (prompt maestro) para un agente WhatsApp
de {role} llamado {agent_name} para este negocio:

Negocio: {tenant.name}
Pitch: {tenant.business_pitch}
Misión: {tenant.mision}
Visión: {tenant.vision}
Valores: {tenant.valores}
Tono: {tenant.tono_comunicacion}
Catálogo: {catalog_summary}

Template base a personalizar:
{template['skeleton']}

Reglas:
- 200-400 palabras
- Español Colombia
- NO inventes características del producto que no estén en el catálogo
- Adapta el rol al tipo de negocio
- NO repitas la filosofía del negocio literal (el bot ya la tiene
  inyectada automáticamente)
"""
```

## Router pre-LLM — Heurística

```python
def classify_intent_to_agent(inbound: str, agents: list[dict]) -> dict:
    if len(agents) <= 1:
        return agents[0]  # backward-compat

    inbound_lower = inbound.lower()

    # Claims keywords (más específicos primero).
    if any(w in inbound_lower for w in [
        "reclamo", "devolver", "retracto", "garantía",
        "defectuoso", "no funciona",
    ]):
        return _find_role(agents, "claims") or _default(agents)

    # Support keywords.
    if any(w in inbound_lower for w in [
        "dónde está mi pedido", "tracking", "no me llegó",
        "rastreo", "cuándo llega",
    ]):
        return _find_role(agents, "support") or _default(agents)

    # Marketing keywords.
    if any(w in inbound_lower for w in [
        "promo", "descuento", "oferta", "cupón disponible",
    ]):
        return _find_role(agents, "marketing") or _default(agents)

    # Default: ventas.
    return _find_role(agents, "sales") or _default(agents)
```

## Implicaciones / Trade-offs

**Pros**:

- Multi-vertical agnóstico real (cosmética + tech + comida + cualquier).
- Tenant decide su organización del bot (1 agente o muchos).
- IA generativa baja la barrera para configurar agentes.
- Tools filtering per rol previene mis-uso (Soporte no puede generar
  payment_link por accidente).

**Cons / Riesgos**:

- Complejidad operacional: tenant debe entender el concepto de "varios
  agentes". Riesgo de mal-configurar (varios agentes default, etc.).
  → Mitigation: UNIQUE INDEX en DB + UI con confirmación clara.
- Cost LLM: cada "Sugerir con IA" cuesta ~$0.0002 (Gemini Flash). A
  escala 100 tenants × 10 sugerencias = $0.20/mes. Aceptable.
- Router heurístico no es 100% preciso. Riesgo: cliente con intent
  ambiguo va al agente equivocado.
  → Mitigation: el default (Ventas) cubre todo lo que no clasifica
  específicamente. Casos edge se reportan en métricas + tunning.

## Implementación

| Fase | Componente | Esfuerzo |
|---|---|---|
| C1 | `lib/agent_templates.py` (5 templates) | 0.5d |
| C2 | `POST /api/v1/ai-agents/suggest` + meta-prompt | 1d |
| C3 | UI lista agentes + drawer crear + IA button | 2d |
| C4 | `agent_router.py` heurístico + dispatcher hook | 1d |
| C5 | `tools_allowed` enforcement (allowed_tools filter) | 0.5d |
| D | Tests + UAT certificación | 1d |
| **Total** | | **6 días-dev** |

## Verificación (criterios de éxito)

Cierre de Fase C+D:

1. KAIU tenant puede:
   - Ver "Sara Camila" (Ventas) como agente default.
   - Crear "Andrés Soporte" (rol Support) con prompt auto-generado.
   - Cliente envía "¿dónde está mi pedido?" → router elige Andrés.
   - Cliente envía "quiero comprar jabón" → router elige Sara.

2. Tenant Tech ficticio puede:
   - Crear "Carolina Ventas" con prompt auto-generado en lenguaje técnico
     (Gemini lee pitch="soluciones de software B2B" + valores y adapta).
   - El bot NUNCA dice "cosmética artesanal natural" (porque el campo
     hardcoded ya no existe).

3. Tools enforcement:
   - Agente Support tiene `tools_allowed=['get_recent_orders', 'kb_query',
     'escalate_to_human']`.
   - Cliente intenta hacer pedido en conversación con Support → bot NO
     puede invocar `add_to_cart` (tool no expuesto al LLM) → escala o
     transfiere a Sara Ventas.

4. UI:
   - Solo 1 agente puede ser default por tenant (UNIQUE constraint).
   - Crear agente sin elegir rol → tipo "custom" + tools_allowed=None.
   - Botón "Sugerir con IA" funciona con < 5s latencia (Gemini Flash).

## Decisiones Cerradas

- **Templates en código vs DB**: en código (`lib/agent_templates.py`). Razón:
  son patrones globales probados, no varían per tenant. Si un tenant
  necesita custom, ya tiene la opción `custom` con blank canvas.

- **AI generativa cost**: Gemini Flash, no Pro. ~$0.0002 por sugerencia.
  Aceptable a escala.

- **Router heurístico vs LLM**: heurístico (regex). Razón: 0 latencia +
  0 costo + casos cubiertos con keywords claros. Si en métricas vemos
  miss-classification > 10%, escalamos a clasificación con LLM Flash Lite.

- **Backward-compat**: si tenant tiene 1 agente (situación actual), todo
  funciona como hoy. Multi-agente es opt-in (operador crea agentes
  adicionales cuando los necesite).

## Estado

Implementado en sesión 2026-05-29 (commits `a6ab86a..[Cierre Fase D]`).

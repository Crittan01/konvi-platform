"""Paquete `prompt/` — composición del system prompt del Orchestrator (rev. 104, F1-4).

Empezamos extrayendo el monolito `_build_system_prompt` (~778 LOC) del
orchestrator a `builder.py` con lazy imports de las dependencias internas.

Iteraciones siguientes descomponen `builder.py` en bloques funcionales:
  • blocks/identity.py — saludos, role_desc, customer-known/new.
  • blocks/customer.py — `customer_context_block`, known_customer_block.
  • blocks/catalog.py — selección de catálogo según FSM display_state.
  • blocks/fsm_directives.py — `state_instruction` por display_state.
  • blocks/format_rules.py — reglas WhatsApp + patrones canónicos.
  • blocks/extraction.py — schema JSON + reglas extracción.

`builder.py` orquesta los bloques. Mantiene back-compat con `orchestrator._build_system_prompt`
mientras la migración progresa.
"""

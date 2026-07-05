/**
 * Guardrails por rol — tools_allowed / fsm_states_allowed que la CRUD de
 * agentes persiste al crear/editar (F5 — cierra el gap "guardrails prometidos
 * en UI que la CRUD nunca persistía").
 *
 * ESPEJO EXACTO de services/api/lib/agent_templates.py → AGENT_TEMPLATES.
 * Mantener en sync 1:1 (mismo criterio que VALID_ROLES en page.tsx es espejo de
 * is_valid_role()). Se replica en TS — en vez de fetchear el endpoint público
 * /api/v1/ai-agents/templates — porque el server action solo toca Supabase: una
 * llamada de red en el write path añadiría un modo de fallo (si el fetch cae,
 * insertaríamos tools_allowed=NULL = TODAS las tools, que es justo el bug que
 * este cambio cierra). Un mapa estático no tiene ese modo de fallo.
 *
 * Semántica (idéntica al dispatcher, agentic/dispatcher.py:3451-3499):
 *   • tools_allowed = null  → el agente puede invocar TODAS las tools (default).
 *   • tools_allowed = [...] → intersección con el toolset del estado FSM.
 *   • fsm_states_allowed = null → el agente atiende en TODOS los estados.
 *   • fsm_states_allowed = [...] → fuera de esos estados, out_of_state (sirve
 *     con el toolset del estado, no aplica su restricción — decisión low-touch).
 *
 * SEGURIDAD: un agente Soporte creado por UI ya NO recibe generate_payment_link
 * ni add_to_cart; el LLM nunca ve esas tools.
 */

export interface RoleGuardrails {
  tools_allowed: string[] | null
  fsm_states_allowed: string[] | null
}

export const AGENT_GUARDRAILS: Record<string, RoleGuardrails> = {
  sales: {
    tools_allowed: [
      'list_catalog',
      'add_to_cart',
      'update_cart_item_quantity',
      'remove_cart_item',
      'get_cart',
      'save_contact_field',
      'save_address',
      'record_consent',
      'get_contact_info',
      'quote_shipping',
      'select_carrier',
      'generate_payment_link',
      'get_recent_orders',
      'kb_query',
      'send_product_image',
      'create_claim',
      'get_claim_status',
      'escalate_to_human',
    ],
    fsm_states_allowed: null,
  },
  support: {
    tools_allowed: [
      'get_recent_orders',
      'get_contact_info',
      'kb_query',
      'get_claim_status',
      'escalate_to_human',
    ],
    fsm_states_allowed: ['POST_PAYMENT', 'HUMAN_HANDOFF'],
  },
  marketing: {
    tools_allowed: [
      'kb_query',
      'list_catalog',
      'record_consent',
    ],
    fsm_states_allowed: null,
  },
  claims: {
    tools_allowed: [
      'get_recent_orders',
      'get_contact_info',
      'kb_query',
      'create_claim',
      'get_claim_status',
      'escalate_to_human',
    ],
    fsm_states_allowed: ['POST_PAYMENT', 'HUMAN_HANDOFF'],
  },
  custom: {
    tools_allowed: null, // libre — el operador define el comportamiento a mano
    fsm_states_allowed: null,
  },
}

/**
 * Devuelve los guardrails del rol. Fallback a `custom` (libre) para roles
 * desconocidos — nunca lanza. El server action ya valida el rol contra
 * VALID_ROLES antes de llamar aquí, así que el fallback es defensa en
 * profundidad, no ruta normal.
 */
export function guardrailsForRole(role: string): RoleGuardrails {
  return AGENT_GUARDRAILS[role] ?? AGENT_GUARDRAILS.custom
}

"""Templates de agente per rol — multi-vertical agnóstico (rev. 109 ADR-0017).

5 templates base que el operador puede usar como punto de partida al crear
un agente nuevo. Cada template expone:

  • name_default — sugerencia de nombre para el agente.
  • skeleton — role_description seed que el operador puede editar o que
    la AI generativa toma como base para personalizar.
  • tools_allowed — subset de tools que ese rol PUEDE invocar. None = todas.
  • fsm_states_allowed — subset de estados FSM (None = todos).

Los templates son GLOBAL (en código, no per tenant) porque son patrones
probados. Si un tenant necesita algo distinto, usa el template `custom`
con blank canvas.

Multi-vertical agnóstico: ningún template asume vertical específica
(cosmética, tech, comida). El operador adapta el skeleton o usa la
AI generativa que lee la config del tenant.
"""
from __future__ import annotations

from typing import Optional, TypedDict


class AgentTemplate(TypedDict, total=False):
    name_default: str
    skeleton: str
    tools_allowed: Optional[list[str]]
    fsm_states_allowed: Optional[list[str]]


# ─── Skeletons (multi-vertical agnósticos) ──────────────────────────────────


_SALES_SKELETON = """Eres {agent_name}, asesor/a de ventas de {tenant_name}.
Atiendes por WhatsApp y tu objetivo es acompañar al cliente desde la
consulta hasta el cierre del pedido, con calidez y honestidad.

CÓMO ACTÚAS:
• Cuando el cliente pregunta por un producto, indaga su necesidad antes
  de recomendar. Pregunta qué busca, para quién, qué presupuesto.
• NUNCA presiones la compra. Si el cliente no está listo, ofrece
  información útil y deja la puerta abierta.
• Si el cliente quiere comprar, guía el flujo: catálogo → variante →
  cantidad → datos de envío → resumen → link de pago.
• Sé honesto sobre precios, disponibilidad y plazos. NUNCA inventes.

CUÁNDO ESCALAR A HUMANO:
• Reclamos sobre pedidos ya entregados.
• Dudas legales complejas (Habeas Data, retracto).
• Cliente hostil o caso fuera de catálogo.
"""

_SUPPORT_SKELETON = """Eres {agent_name}, especialista en soporte de
{tenant_name}. Atiendes consultas POST-COMPRA por WhatsApp: tracking,
estado de pedidos, garantías básicas.

CÓMO ACTÚAS:
• Cuando el cliente reporta un problema, primero VALIDA el estado real
  en el sistema (get_recent_orders, kb_query). NO supongas.
• Sé empático: el cliente que reporta un problema ya está frustrado.
• Si hay defecto, garantía o requiere refund, ESCALA a especialista.
  NO prometas resoluciones que no puedes garantizar.

NUNCA:
• Generes nuevos links de pago (no es tu rol).
• Modifiques pedidos en curso.
• Crees expectativas de "todo se arregla" sin validar políticas.
"""

_MARKETING_SKELETON = """Eres {agent_name}, especialista en outbound /
marketing de {tenant_name}. Envías recordatorios, promociones y contenido
de valor a clientes con consentimiento Habeas Data.

CÓMO ACTÚAS:
• NUNCA inicies conversaciones con clientes que no dieron consent
  (Ley 1581 + Meta Business Policy).
• Si el cliente responde a una campaña, escucha primero y propón
  según su contexto. NO empujes.
• Si pide unsubscribe / "STOP" / "no más mensajes", respeta y registra
  consent revocado.

PROHIBIDO:
• Crear urgencia falsa ("últimas unidades", "promo termina hoy" si no
  es cierto).
• Inventar descuentos.
• Spammear si ya respondieron negativo.
"""

_CLAIMS_SKELETON = """Eres {agent_name}, especialista en reclamos y
devoluciones de {tenant_name}. Atiendes garantías (Ley 1480 Art. 11),
retracto (Art. 47), devoluciones y reembolsos.

CÓMO ACTÚAS:
• Para retracto Art. 47: valida primero la elegibilidad (5 días hábiles
  + producto no excluido del parágrafo: cosmética abierta, software
  descargable, perecederos, etc.).
• Para garantía Art. 11: indaga el defecto, pide foto si aplica,
  registra ticket.
• Para reembolso: cita Ley 1480 Art. 49 (30 días calendario máximo).
• SIEMPRE empático — el cliente con reclamo ya tiene frustración.
• SIEMPRE escala al operador humano para validación final.

NO inventes:
• Plazos legales (sigue siempre Ley 1480).
• Resoluciones (especialista decide).
• Categorías de exclusión (lee del producto, no asumas).
"""

_CUSTOM_SKELETON = ""  # blank canvas — operador escribe desde cero


# ─── Templates exportados ───────────────────────────────────────────────────


AGENT_TEMPLATES: dict[str, AgentTemplate] = {
    "sales": {
        "name_default": "Asesor/a de Ventas",
        "skeleton": _SALES_SKELETON,
        "tools_allowed": [
            "list_catalog",
            "add_to_cart",
            "update_cart_item_quantity",
            "remove_cart_item",
            "get_cart",
            "save_contact_field",
            "save_address",
            "record_consent",
            "get_contact_info",
            "quote_shipping",
            "select_carrier",
            "generate_payment_link",
            "get_recent_orders",
            "kb_query",
            "send_product_image",
            "escalate_to_human",
        ],
        "fsm_states_allowed": None,  # todos los estados
    },
    "support": {
        "name_default": "Asesor/a de Soporte",
        "skeleton": _SUPPORT_SKELETON,
        "tools_allowed": [
            "get_recent_orders",
            "get_contact_info",
            "kb_query",
            "escalate_to_human",
        ],
        "fsm_states_allowed": ["POST_PAYMENT", "HUMAN_HANDOFF"],
    },
    "marketing": {
        "name_default": "Marketing Bot",
        "skeleton": _MARKETING_SKELETON,
        "tools_allowed": [
            "kb_query",
            "list_catalog",
            "record_consent",
        ],
        "fsm_states_allowed": None,
    },
    "claims": {
        "name_default": "Especialista en Reclamos",
        "skeleton": _CLAIMS_SKELETON,
        "tools_allowed": [
            "get_recent_orders",
            "get_contact_info",
            "kb_query",
            "escalate_to_human",
        ],
        "fsm_states_allowed": ["POST_PAYMENT", "HUMAN_HANDOFF"],
    },
    "custom": {
        "name_default": "Asistente",
        "skeleton": _CUSTOM_SKELETON,
        "tools_allowed": None,  # libre
        "fsm_states_allowed": None,
    },
}


_VALID_ROLES = frozenset(AGENT_TEMPLATES.keys())


def get_template(role: str) -> AgentTemplate:
    """Retorna el template del rol pedido. Fallback a 'custom' si no existe."""
    return AGENT_TEMPLATES.get(role, AGENT_TEMPLATES["custom"])


def render_skeleton(role: str, *, agent_name: str, tenant_name: str) -> str:
    """Renderiza el skeleton del rol con agent_name + tenant_name aplicados."""
    template = get_template(role)
    skeleton = template.get("skeleton", "") or ""
    if not skeleton:
        return ""
    return skeleton.format(
        agent_name=agent_name or "Asistente",
        tenant_name=tenant_name or "el negocio",
    )


def list_roles() -> list[str]:
    """Lista los roles disponibles. Útil para validación en endpoints."""
    return sorted(_VALID_ROLES)


def is_valid_role(role: str) -> bool:
    return role in _VALID_ROLES

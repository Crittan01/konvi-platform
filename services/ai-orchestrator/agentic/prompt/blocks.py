"""Bloques reutilizables compartidos entre per-state prompts (rev. 109).

Cada función retorna un string listo para concatenar. Los bloques son
PURE — no leen DB ni hacen IO. Reciben los datos pre-cargados desde
dispatcher.

Convenciones:
  • Bloques cortos (<2KB cada uno).
  • Sin reglas de negocio duplicadas — las reglas viven en las states/.
  • Heading consistente: `═══ TÍTULO ═══` (mismo que monolito legacy).
"""
from __future__ import annotations

from typing import Optional

# Reutilizamos los renderers del monolito (catalog, carriers, payment_methods,
# contact, server_greeting, business_ops) — son funciones puras testeadas en
# producción. Fase 0 finiquito 2026-06-23: business_ops_block migrado a per-state
# (audit-finiquito root cause analysis wujbdgrhk — V3 per-state es path primario,
# antes business_ops solo vivía en V2 monolito).
from agentic.system_prompt import (
    _render_catalog_block,
    _render_carriers_block,
    _render_payment_methods_block,
    _render_contact_block,
    _render_business_ops_block,
    _co_time_of_day_greeting,
)


def identity_block(
    *,
    agent_name: str,
    tenant_name: str,
    pitch: str,
    tone: str,
) -> str:
    """Identidad del agente + tenant — apertura del prompt."""
    return (
        f"Eres {agent_name}, {pitch}.\n\n"
        f"Conversas con clientes vía WhatsApp en {tone}. Atiendes en "
        f"nombre de *{tenant_name}*. Tu objetivo es ayudarles a comprar "
        f"productos del tenant, resolver dudas, y procesar el flujo de "
        f"pedido completo hasta el link de pago.\n"
    )


def time_greeting_block(server_greeting: Optional[str] = None) -> tuple[str, str]:
    """Bloque del saludo time-aware. Retorna (bloque, server_greeting)."""
    if server_greeting is None:
        server_greeting, _ = _co_time_of_day_greeting()
    block = (
        f"CONTEXTO HORARIO: ahora es **{server_greeting}** hora Colombia. "
        f"Cuando SALUDES al cliente, usa exactamente \"{server_greeting}\" "
        f"(no \"Hola\" genérico, no \"Hey\", no \"Saludos\"). Si el cliente "
        f"ya fue saludado en turnos anteriores, NO vuelvas a saludar — "
        f"responde directo a su mensaje.\n"
    )
    return block, server_greeting


def safety_block() -> str:
    """Reglas universales NO violables — anti-hallu + Habeas Data + style."""
    return """═══════════════════════════════════════════════════════════════════
REGLAS UNIVERSALES — NO VIOLAR
═══════════════════════════════════════════════════════════════════

1. **Verdad transaccional**: NUNCA afirmes que algo está "agregado",
   "guardado", "cotizado" o "registrado" sin haber invocado el tool
   correspondiente Y recibido `success=True`. Si UN tool de N falla,
   reporta solo lo que sí pasó.

2. **Catálogo es fuente de verdad**: NUNCA inventes productos, precios,
   variantes ni categorías. Los productos REALES están en "CATÁLOGO
   ACTUAL" con UUIDs reales. Si una variante aparece como *AGOTADO*, NO la
   ofrezcas ni la agregues — ofrece las presentaciones disponibles.

3. **Habeas Data Ley 1581**: NO invoques `save_contact_field` sin
   `consent_given=True`. Si el contacto no tiene consent, primero pide
   autorización y registra con `record_consent`.

4. **Cero promesas vacías**: NUNCA digas "un momento", "déjame revisar",
   "permíteme cotizar" SIN invocar el tool en el MISMO turno. Si vas a
   cotizar/consultar, llama el tool y retorna resultados de una.

5. **Escalation = última instancia**: agota tools antes de escalar.
   • catálogo/precio → `list_catalog`
   • pedido/tracking → `get_recent_orders`
   • producto info / políticas → `kb_query`
   • foto → `send_product_image`
   Escala solo si: cliente pide especialista, reclamo de entregado,
   refund sin política, o kb_query sin resultados. Di "*un especialista*"
   o "*mi equipo*" (NUNCA "asesor"/"agente"/"persona").
"""


def style_block(tone: str) -> str:
    """Estilo WhatsApp — formato + emojis whitelist."""
    return f"""═══════════════════════════════════════════════════════════════════
ESTILO
═══════════════════════════════════════════════════════════════════

• Tono: {tone}.
• Máx 4 líneas por respuesta (WhatsApp móvil; mensajes largos cansan).
• Formato: `*negrita*` para productos/precios/carriers/status.
  Bullets con `*` al inicio. Precios: "$24.000" (punto miles, COP).
• CERO emojis decorativos (😊 ✨ 🌿). Únicas excepciones:
  📋 (resumen), 🚚 (envío), ✅ (pago), 💵 (contraentrega).
"""


def catalog_section(catalog: list[dict] | None) -> str:
    """Sección CATÁLOGO ACTUAL — todos los productos con UUIDs reales."""
    catalog_block = _render_catalog_block(catalog or [])
    return f"""═══════════════════════════════════════════════════════════════════
CATÁLOGO ACTUAL
═══════════════════════════════════════════════════════════════════

Productos disponibles del tenant. Cada variante incluye su `variation_id`
real para usar en `add_to_cart`. NO inventes productos ni precios.

{catalog_block}
"""


def catalog_compact_section(catalog: list[dict] | None) -> str:
    """Catálogo COMPACTO (título + variantes + precio, SIN descripciones ni notas
    de seguridad) para estados de checkout (SHIPPING_QUOTE/CARRIER_SELECTION/
    PAYMENT). A11 2026-06-26: el cliente puede agregar productos a mitad del
    checkout; el bot debe conocer las variantes REALES para no inventar
    disponibilidad ("solo 30ml" cuando existe la 15ml). Liviano para no inflar."""
    block = _render_catalog_block(catalog or [], compact=True)
    return f"""═══════════════════════════════════════════════════════════════════
CATÁLOGO (referencia compacta — variantes y precios reales)
═══════════════════════════════════════════════════════════════════

Si el cliente pregunta por otro producto o quiere agregar uno a mitad del
checkout, usa SOLO estas variantes/precios reales. NUNCA inventes presentaciones.

{block}
"""


def customer_section(contact_record: dict | None, *, tenant_name: str) -> str:
    """Bloque CONTEXTO_CLIENTE inyectado pre-LLM."""
    return _render_contact_block(contact_record or {}, tenant_name=tenant_name) + "\n"


def carriers_section(carriers: list[dict] | None) -> str:
    return f"""═══════════════════════════════════════════════════════════════════
CARRIERS — CAPACIDADES (canonical Aveonline)
═══════════════════════════════════════════════════════════════════

{_render_carriers_block(carriers)}
"""


def payment_methods_section(payment_methods: dict | None) -> str:
    return f"""═══════════════════════════════════════════════════════════════════
MÉTODOS DE PAGO (configuración per-tenant)
═══════════════════════════════════════════════════════════════════

{_render_payment_methods_block(payment_methods)}
"""


def coupons_section(active_coupons: list[dict] | None) -> str:
    """Sección CUPONES — fuente de verdad DB (founder 2026-05-28).

    Bug A.0.1 revelado en UAT: el agente de marketing afirmaba "no hay
    promos" SIN consultar DB. Inyectamos cupones activos al system prompt
    (patrón cart-as-SoT) + regla anti-hallu. Reutiliza el renderer del
    monolito legacy para mantener single-source-of-truth de la regla.
    """
    from agentic.system_prompt import _render_coupons_block
    return f"""═══════════════════════════════════════════════════════════════════
CUPONES / PROMOCIONES (fuente de verdad — DB)
═══════════════════════════════════════════════════════════════════

{_render_coupons_block(active_coupons)}
"""


def business_ops_section(
    *,
    tenant_name: str,
    shipping_origin: Optional[dict] = None,
    store_locations: Optional[list[dict]] = None,
    store_type: Optional[str] = None,
    support_schedule: Optional[dict] = None,
    social_links: Optional[dict] = None,
    after_hours_message: Optional[str] = None,
) -> str:
    """Sección OPERACIONES DEL NEGOCIO (Fase 0/3 finiquito 2026-06-23 — V3 per-state).

    Cierra causa raíz P1 root-cause analysis wujbdgrhk: bot improvisaba
    horarios/despacho/sedes/redes porque V3 per-state path (build_prompt_for_state)
    NO recibía los kwargs business_ops — A2 commit 2026-06-22 los puso solo en
    V2 monolito (dispatcher.py:645) pero V3 sobreescribe ese prompt en línea 1969.

    Fase 3 finiquito 2026-06-23 — ataque P4 (LLM improvisa con dato presente,
    ej. horario "9-6 L-V" vs DB "Lun-Sáb 08:00-18:00"):

    1. XML tags `<business_ops>...</business_ops>` para clear attention closure.
       Anthropic prompting guide + Google Gemini 3 ("strictly grounded") + OpenAI
       structured prompts recomiendan XML para datos críticos que el modelo NO
       debe parafrasear/improvisar — el delimitador anchor reduce sesgo training-data
       (e.g. "9-6 horario común Colombia" attractor).
    2. Instrucción explícita ANTI-IMPROVISATION dentro del wrapper: "USA EXACTAMENTE
       estos valores literales — NUNCA aproximes, NUNCA inventes alternativas".

    Reutiliza `_render_business_ops_block` de V2 (single source of truth — NO
    duplica lógica de formateo). Si todos los datos están vacíos, retorna
    string vacío (no inyecta header sin contenido).

    Para qué estados aplica: ver agentic/prompt/builder.py _BUSINESS_OPS_STATES
    (decisión Q3: GREETING + EXPLORING + CART_BUILDING + POST_PAYMENT).
    """
    rendered = _render_business_ops_block(
        tenant_name=tenant_name,
        shipping_origin=shipping_origin,
        store_locations=store_locations,
        store_type=store_type,
        support_schedule=support_schedule,
        social_links=social_links,
        after_hours_message=after_hours_message,
    )
    if not rendered.strip():
        return ""

    # Fase 3 — XML wrapper + anti-improvisation hard rule.
    # Posición: builder.py inserta este bloque ANTES del mini-prompt del
    # estado (post identity + customer) para que sea anchor temprano del
    # contexto factual del negocio antes de la lógica de estado.
    return (
        "\n<business_ops priority=\"factual_truth\">\n"
        "REGLA CRÍTICA — USA EXACTAMENTE los valores literales de este bloque.\n"
        "NUNCA aproximes, parafrasees ni inventes alternativas (ej. si dice\n"
        "'Lun a Sáb de 08:00 a 18:00', NO digas '9-6 L-V'). Si el cliente\n"
        "pregunta horario/despacho/sedes/redes, cita textualmente abajo:\n"
        f"{rendered.lstrip()}\n"
        "</business_ops>\n"
    )

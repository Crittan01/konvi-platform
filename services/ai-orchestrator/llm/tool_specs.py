"""Declaraciones de tools (FunctionDeclaration) para Gemini Function Calling.

Cada tool se declara como dict OpenAPI 3.0 Schema subset, según la
documentación oficial:
https://ai.google.dev/gemini-api/docs/function-calling

Diseño:
  - Estos dicts son DATA, no ejecutables. Ejecución vive en el coordinator.
  - Cada tool documenta su propósito, parámetros y cuándo el LLM debe llamarlo
    (en ``description``).
  - Los nombres deben coincidir 1-a-1 con :data:`core.fsm.ALLOWED_TOOLS_BY_STATE`.

Convenciones de naming:
  - snake_case
  - verbo_objeto (``add_item_to_cart``, ``set_customer_email``)

NOTA: Usamos snake_case en parámetros (``product_id``, no ``productId``)
porque es el patrón Python del repo y el SDK ``google-genai`` lo acepta.
"""
from __future__ import annotations

# ── CATALOG / KB ─────────────────────────────────────────────────────────────


SEARCH_CATALOG: dict = {
    "name": "search_catalog",
    "description": (
        "Busca productos del catálogo del tenant cuando el cliente pregunta "
        "por disponibilidad, precio, categoría o presentación. Devuelve "
        "productos coincidentes con sus variantes y precios. NO inventes "
        "productos — si no aparece en el resultado, no existe."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Frase del cliente o término de búsqueda. Ej: 'aceite "
                    "de lavanda', 'jabón artesanal'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de productos a devolver. Default 10.",
            },
        },
        "required": ["query"],
    },
}


GET_PRODUCT_IMAGE: dict = {
    "name": "get_product_image",
    "description": (
        "Devuelve la URL de imagen del producto cuando el cliente pide ver "
        "una foto ('mándame foto', 'cómo se ve'). Si no hay imagen cargada "
        "en DB, devuelve null — NO inventes URLs ni reuses imágenes de "
        "otro producto."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string"},
            "variation_id": {
                "type": "string",
                "description": (
                    "Opcional. Si la variante específica fue identificada, "
                    "se prefiere su imagen sobre la del producto."
                ),
            },
        },
        "required": ["product_id"],
    },
}


ANSWER_KB: dict = {
    "name": "answer_kb",
    "description": (
        "Responde preguntas sobre políticas, envíos, devoluciones, formas "
        "de pago consultando la knowledge base del tenant via búsqueda "
        "semántica. Usar solo cuando la pregunta NO es sobre disponibilidad "
        "o precio de un producto específico."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "category_hint": {
                "type": "string",
                "enum": ["faq", "negocio", "politicas", "productos", "envios", "pagos"],
                "description": "Categoría sugerida (no obligatoria).",
            },
        },
        "required": ["question"],
    },
}


# ── CART ─────────────────────────────────────────────────────────────────────


ADD_ITEM_TO_CART: dict = {
    "name": "add_item_to_cart",
    "description": (
        "Agrega un item al carrito conversacional del cliente. Usar cuando "
        "el cliente expresa intención de compra concreta ('quiero', 'dame', "
        "'agrégame'). Si el cliente menciona la misma variante dos veces, "
        "el sistema suma cantidades automáticamente — NO crees duplicados. "
        "Si menciona dos variantes del mismo producto (ej. 1 de 10ml + 1 de "
        "30ml), llama esta función DOS veces, una por variation_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string"},
            "variation_id": {
                "type": "string",
                "description": (
                    "OBLIGATORIO. Si el cliente no especificó variante (ej. "
                    "'quiero el aceite' sin decir el volumen), NO llames "
                    "esta función — pide aclaración primero."
                ),
            },
            "quantity": {
                "type": "integer",
                "description": "Default 1 si el cliente no especifica.",
            },
        },
        "required": ["product_id", "variation_id"],
    },
}


REMOVE_ITEM_FROM_CART: dict = {
    "name": "remove_item_from_cart",
    "description": (
        "Elimina por completo un item del carrito. Usar cuando el cliente "
        "dice 'quita el X', 'ya no quiero el Y'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "variation_id": {"type": "string"},
        },
        "required": ["variation_id"],
    },
}


# ── SHIPPING ─────────────────────────────────────────────────────────────────


QUOTE_SHIPPING: dict = {
    "name": "quote_shipping",
    "description": (
        "Cotiza envío del carrito a la ciudad indicada por el cliente. "
        "Usa Envia.com con código DANE. NO inventes tarifas — si Envia "
        "no responde, escala a humano."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "city_text": {
                "type": "string",
                "description": (
                    "Texto crudo de la ciudad como lo dijo el cliente. Ej: "
                    "'Bogotá', 'Medellín', 'Cali'. El sistema resuelve el "
                    "código DANE."
                ),
            },
        },
        "required": ["city_text"],
    },
}


SELECT_CARRIER: dict = {
    "name": "select_carrier",
    "description": (
        "Confirma la elección del transportista del cliente entre las "
        "opciones cotizadas (Económica / Rápida)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "carrier_choice": {
                "type": "string",
                "enum": ["economica", "rapida"],
            },
        },
        "required": ["carrier_choice"],
    },
}


# ── CUSTOMER DATA ────────────────────────────────────────────────────────────


RECORD_CONSENT: dict = {
    "name": "record_consent",
    "description": (
        "Registra la autorización (Ley 1581 Colombia) del cliente para el "
        "tratamiento de sus datos personales. Solo llamar cuando el cliente "
        "responde afirmativamente a la pregunta de consentimiento."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "given": {"type": "boolean"},
        },
        "required": ["given"],
    },
}


SET_CUSTOMER_EMAIL: dict = {
    "name": "set_customer_email",
    "description": (
        "Persiste el email del cliente. Validar formato antes de llamar. "
        "Solo permitido si consent_given=True."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "email": {"type": "string"},
        },
        "required": ["email"],
    },
}


SET_CUSTOMER_NAME: dict = {
    "name": "set_customer_name",
    "description": (
        "Persiste el nombre completo del cliente como lo escribió "
        "(NO truncar a primer nombre). Solo permitido si consent_given=True."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
        },
        "required": ["full_name"],
    },
}


SET_CUSTOMER_DOCUMENT: dict = {
    "name": "set_customer_document",
    "description": (
        "Persiste tipo + número de documento del cliente. Tipos válidos "
        "Colombia: CC, CE, NIT, PP, TI, OTHER. Wompi requiere ambos juntos. "
        "El número se guarda solo dígitos (sin puntos ni espacios)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": ["CC", "CE", "NIT", "PP", "TI", "OTHER"],
            },
            "document_number": {"type": "string"},
        },
        "required": ["document_type", "document_number"],
    },
}


SET_CUSTOMER_ADDRESS: dict = {
    "name": "set_customer_address",
    "description": (
        "Persiste la dirección estructurada del cliente. building_type es "
        "OBLIGATORIO para saber si pedir apartamento/torre. Si el cliente "
        "no lo especifica, NO llames esta función — pide aclaración."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "street": {"type": "string"},
            "city": {"type": "string"},
            "building_type": {
                "type": "string",
                "enum": ["casa", "edificio", "conjunto"],
            },
            "apartment": {
                "type": "string",
                "description": "Obligatorio si building_type = edificio o conjunto.",
            },
            "tower": {
                "type": "string",
                "description": "Obligatorio si building_type = conjunto.",
            },
            "complex_name": {"type": "string"},
            "neighborhood": {"type": "string"},
            "reference": {"type": "string"},
        },
        "required": ["street", "city", "building_type"],
    },
}


# ── SUMMARY / CONFIRMATION ───────────────────────────────────────────────────


RENDER_SUMMARY: dict = {
    "name": "render_summary",
    "description": (
        "Genera el resumen estructurado del pedido (productos, subtotal, "
        "envío, total, datos de envío) y se lo presenta al cliente para "
        "confirmar. Llamar cuando todos los datos están completos."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


CONFIRM_ORDER: dict = {
    "name": "confirm_order",
    "description": (
        "Confirma la creación del pedido y dispara la generación del link "
        "de pago Wompi. Solo llamar cuando el cliente afirma explícitamente "
        "tras ver el resumen."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


CANCEL_ORDER: dict = {
    "name": "cancel_order",
    "description": (
        "Cancela el carrito en estado checkout/awaiting_confirmation. "
        "Llamar cuando el cliente dice 'cancelar', 'no quiero seguir'."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


# ── ESCALATION ───────────────────────────────────────────────────────────────


ESCALATE_TO_HUMAN: dict = {
    "name": "escalate_to_human",
    "description": (
        "Transfiere la conversación a un agente humano. Llamar cuando: "
        "(a) el cliente lo pide explícitamente, (b) hay reclamo/queja/"
        "devolución, (c) ≥2 intercambios sin resolver. NUNCA prometas "
        "'te paso con asesor' sin llamar esta función — si no la llamas, "
        "el bot sigue activo y el cliente queda en limbo."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Etiqueta corta interna: 'complaint', 'unresolved', 'customer_request', etc.",
            },
        },
        "required": ["reason"],
    },
}


# ── Registry ─────────────────────────────────────────────────────────────────
#
# Mapping nombre → spec, usado por ``llm/client.py`` para resolver
# ``allowed_function_names`` en cada turno.

ALL_TOOLS: dict[str, dict] = {
    SEARCH_CATALOG["name"]: SEARCH_CATALOG,
    GET_PRODUCT_IMAGE["name"]: GET_PRODUCT_IMAGE,
    ANSWER_KB["name"]: ANSWER_KB,
    ADD_ITEM_TO_CART["name"]: ADD_ITEM_TO_CART,
    REMOVE_ITEM_FROM_CART["name"]: REMOVE_ITEM_FROM_CART,
    QUOTE_SHIPPING["name"]: QUOTE_SHIPPING,
    SELECT_CARRIER["name"]: SELECT_CARRIER,
    RECORD_CONSENT["name"]: RECORD_CONSENT,
    SET_CUSTOMER_EMAIL["name"]: SET_CUSTOMER_EMAIL,
    SET_CUSTOMER_NAME["name"]: SET_CUSTOMER_NAME,
    SET_CUSTOMER_DOCUMENT["name"]: SET_CUSTOMER_DOCUMENT,
    SET_CUSTOMER_ADDRESS["name"]: SET_CUSTOMER_ADDRESS,
    RENDER_SUMMARY["name"]: RENDER_SUMMARY,
    CONFIRM_ORDER["name"]: CONFIRM_ORDER,
    CANCEL_ORDER["name"]: CANCEL_ORDER,
    ESCALATE_TO_HUMAN["name"]: ESCALATE_TO_HUMAN,
}


def get_tool_specs(tool_names: frozenset[str] | set[str]) -> list[dict]:
    """Devuelve los dicts ``FunctionDeclaration`` para los nombres dados.

    Los nombres desconocidos se ignoran en silencio (defensivo contra typos
    en :data:`core.fsm.ALLOWED_TOOLS_BY_STATE`).
    """
    return [ALL_TOOLS[name] for name in tool_names if name in ALL_TOOLS]

import os
import logging
from google import genai
from google.genai import types

from tools.catalog_tool import CatalogTool

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

def generate_ai_response(supabase_client, tenant_id: str, tenant_name: str, conversation_history: list, new_message: str) -> str:
    """
    Motor central de la IA con Tool Calling Integrado.
    """
    if not GEMINI_API_KEY:
        logger.error("No se puede invocar AI: GEMINI_API_KEY faltante en entorno.")
        return "El asistente AI está en mantenimiento por configuraciones de API."

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 1. Cargando Herramientas Dinamicas
    cat_tool = CatalogTool(tenant_id, supabase_client)
    agent_tools = cat_tool.get_tool_functions()
    
    # 2. El System Prompt Maestro
    system_instruction = f"""
    Eres el asistente oficial experto de atención al cliente para la empresa '{tenant_name}'.
    REGLAS ESTRICTAS DE GUARDRAILS (NO OMITIR NUNCA):
    1. Nunca inventes precios, promociones, ni inventario (Cero Alucinación).
    2. Usa SIEMPRE tu herramienta de sistema para buscar precios y stock antes de afirmar algo sobre productos. Si la herramienta devuelve vacío, informa que no manejas eso.
    3. Eres amable, conciso, y profesional. Ideal para WhatsApp (limita emojis y parrafos largos).
    4. NO eres la fuente única de verdad transaccional. Si algo requiere intervención, dilo.
    """

    # 3. Formatear la historia
    formatted_history = []
    for msg in conversation_history:
        role = "user" if msg.get("direction") == "inbound" else "model"
        formatted_history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content", ""))])
        )
        
    chat = client.chats.create(
        model='gemini-2.5-flash',
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=agent_tools,
            temperature=0.2, # Baja temperatura para que el tool caller sea hiper logico
        ),
        history=formatted_history
    )

    try:
        # 4. Invocacion con bucle de herrramientas auto-gestionado por el SDK Chat
        # Al enviar send_message a un objeto chat con tools, Google automatiza el roundtrip!
        response = chat.send_message(new_message)
        return response.text
    except Exception as e:
        logger.error(f"Caída del engine Gemini o de sus Tools: {e}")
        return "Tuvimos un hipo en nuestro sistema buscando tu información. ¿Podrías repetirme eso?"

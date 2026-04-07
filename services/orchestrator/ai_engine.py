import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

def generate_ai_response(tenant_name: str, conversation_history: list, new_message: str) -> str:
    """
    Toma el nombre del tenant, el historial previo, y el mensaje nuevo.
    Genera una respuesta usando Gemini asegurándose de obedecer los Guardrails de B2B Comercio.
    """
    if not GEMINI_API_KEY:
        logger.error("No se puede invocar AI: GEMINI_API_KEY faltante en entorno.")
        return "El asistente AI está en mantenimiento por configuraciones de API."

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 1. El System Prompt Maestro de B2B
    system_instruction = f"""
    Eres el asistente oficial de atención al cliente para la empresa '{tenant_name}'.
    REGLAS ESTRICTAS DE GUARDRAILS (NO OMITIR NUNCA):
    1. Nunca inventes precios, promociones, ni inventario (Cero Alucinación).
    2. Si el usuario pregunta por un artículo específico y no lo ves en tu contexto exacto (Catálogo BBDD), di que revisarás el sistema y pídele un momento.
    3. Eres amable, conciso, y profesional. No uses emojis excesivos ni parezcas un robot inseguro.
    4. NO eres la fuente de verdad. Si algo parece una queja grave, avisa que un operador humano intervendrá pronto.
    5. Nunca ofrezcas productos de la competencia ni te salgas del contexto de '{tenant_name}'.
    6. Tus respuestas deben ser breves (ideales para la pantalla de WhatsApp).
    """

    # 2. Formatear la historia para la API de Gemini
    # conversation_history espera una lista de diccionarios con 'role' ('user' o 'model') y 'parts'
    formatted_history = []
    for msg in conversation_history:
        # Asumiendo msg = {"direction": "inbound" / "outbound", "content": "..."}
        role = "user" if msg.get("direction") == "inbound" else "model"
        formatted_history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content", ""))])
        )

    # 3. Invocar la generación
    try:
        # Elegimos gemini-2.5-flash ya que es extremadamente rapido para pipelines de WhatsApp
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=formatted_history + [types.Content(role="user", parts=[types.Part.from_text(text=new_message)])],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3, # Baja temperatura para respuestas más determínisticas en commerce
            ),
        )
        return response.text
    except Exception as e:
        logger.error(f"Caída del engine Gemini: {e}")
        return "Tuvimos un hipo en nuestro sistema. ¿Podrías repetirme eso o aguardar un humano?"

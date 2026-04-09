import logging
import os
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types as genai_types
from supabase import Client
from tools.catalog_tool import get_tenant_catalog
from guardrails import validate_orchestrator_output
from whatsapp_sender import send_whatsapp_message

logger = logging.getLogger("orchestrator.core")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "10"))

# Cliente global del nuevo SDK
_genai_client: Optional[genai.Client] = None

def _get_genai_client() -> genai.Client:
    """Singleton lazy del cliente Gemini (nuevo SDK google-genai)."""
    global _genai_client
    if _genai_client is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no configurada")
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client


# ─── Schema de Output Estructurado ────────────────────────────────────────────

class OrchestratorOutput(BaseModel):
    """
    Output tipado de Gemini. El LLM NUNCA es fuente de verdad de stock/precios —
    solo puede referenciar datos inyectados en el contexto (catálogo del tenant).
    """
    should_respond: bool = Field(
        description="True si el mensaje requiere respuesta automática, False si debe escalar a humano"
    )
    response_text: Optional[str] = Field(
        default=None,
        description="Texto de la respuesta a enviar por WhatsApp. None si should_respond=False"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confianza del modelo en la respuesta (0.0 a 1.0)"
    )
    requires_human: bool = Field(
        default=False,
        description="True si el bot detecta que necesita intervención humana"
    )
    intent_detected: str = Field(
        default="unknown",
        description="Intención detectada: product_inquiry, order_status, complaint, greeting, off_topic, other"
    )


# ─── Context Builder ──────────────────────────────────────────────────────────

async def _get_conversation_history(supabase: Client, conversation_id: str) -> list:
    """Retorna los últimos N mensajes de la conversación (contexto del chat)."""
    result = (
        supabase.table("messages")
        .select("direction, content, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(CONVERSATION_HISTORY_LIMIT)
        .execute()
    )
    # Invertir para orden cronológico
    return list(reversed(result.data or []))


def _build_system_prompt(catalog: list, tenant_name: str) -> str:
    """Construye el system prompt con el catálogo real del tenant."""
    catalog_text = "\n".join([
        f"- {p['title']}: ${p['price']} (stock: {p['stock']})"
        for p in catalog
    ])
    if not catalog_text:
        catalog_text = "(No hay productos disponibles en este momento)"

    return f"""Eres un asistente de ventas de {tenant_name} en WhatsApp.
Tu trabajo es responder consultas de clientes sobre productos disponibles.

REGLAS:
- Solo menciona productos y precios del catálogo real que te proporciono abajo.
- Nunca inventes stock, precios o características que no están en el catálogo.
- Si no puedes ayudar, indica que pasarás la consulta a un agente humano.
- Responde siempre en español, de forma cordial y concisa (máx 3 oraciones).
- Si el cliente pregunta algo fuera del catálogo o soporte de pedidos complejos, escala (requires_human=true).

CATÁLOGO ACTUAL:
{catalog_text}

Responde SIEMPRE en JSON con este esquema exacto:
{{
  "should_respond": true/false,
  "response_text": "texto o null",
  "confidence": 0.0-1.0,
  "requires_human": true/false,
  "intent_detected": "product_inquiry|order_status|complaint|greeting|off_topic|other"
}}"""


def _build_user_context(history: list[dict], new_message: str) -> str:
    """Formatea el historial de conversación como contexto para Gemini."""
    lines = []
    for msg in history[:-1]:  # Excluir el mensaje actual (último)
        role = "Cliente" if msg["direction"] == "inbound" else "Asistente"
        lines.append(f"{role}: {msg['content']}")

    lines.append(f"Cliente: {new_message}")
    return "\n".join(lines)


# ─── Core Orchestration ───────────────────────────────────────────────────────

async def build_and_run_orchestration(
    supabase: Client,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """
    Ciclo completo de orquestación para un mensaje entrante:
      1. Construir contexto (catálogo + historial de conversación)
      2. Llamar a Gemini con output estructurado Pydantic
      3. Validar con guardrails
      4. Enviar respuesta por WhatsApp (si es válida)
      5. Persistir mensaje outbound + marcar inbound como processed
    """

    # Ignorar mensajes que no sean texto (audio, imagen, etc.) por ahora
    if content_type != "text":
        logger.info(f"Mensaje {message_id} de tipo '{content_type}' ignorado (solo se procesa texto)")
        _mark_processed(supabase, message_id)
        return

    logger.info(f"[ORCH] Procesando mensaje {message_id} | conv={conversation_id}")

    try:
        # ── 1. Resolver datos del tenant ──────────────────────────────────────
        tenant_res = supabase.table("tenants").select("name").eq("id", tenant_id).execute()
        tenant_name = tenant_res.data[0]["name"] if tenant_res.data else "Tienda"

        # ── 2. Obtener catálogo y historial ───────────────────────────────────
        catalog = await get_tenant_catalog(supabase, tenant_id)
        history = await _get_conversation_history(supabase, conversation_id)

        # ── 3. Construir prompts ───────────────────────────────────────────────
        system_prompt = _build_system_prompt(catalog, tenant_name)
        user_context = _build_user_context(history, content)

        # ── 4. Llamar a Gemini (nuevo SDK google-genai) ───────────────────────
        # Ref: https://googleapis.github.io/python-genai/
        client = _get_genai_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_context,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        raw_json = response.text
        logger.debug(f"[GEMINI] Raw response: {raw_json}")

        # ── 5. Parsear output estructurado ────────────────────────────────────
        import json
        parsed = OrchestratorOutput(**json.loads(raw_json))
        logger.info(
            f"[GEMINI] intent={parsed.intent_detected} | "
            f"confidence={parsed.confidence:.2f} | "
            f"should_respond={parsed.should_respond} | "
            f"requires_human={parsed.requires_human}"
        )

        # ── 6. Guardrails ─────────────────────────────────────────────────────
        is_safe = validate_orchestrator_output(parsed)
        if not is_safe:
            logger.warning(f"[GUARDRAIL] Mensaje {message_id} rechazado por guardrails")
            _mark_processed(supabase, message_id)
            return

        # ── 7. Enviar respuesta si corresponde ────────────────────────────────
        if parsed.should_respond and parsed.response_text:
            # Obtener el teléfono del cliente desde la conversación
            conv_res = supabase.table("conversations").select("customer_phone").eq("id", conversation_id).execute()
            customer_phone = conv_res.data[0]["customer_phone"]

            success = await send_whatsapp_message(
                tenant_id=tenant_id,
                supabase=supabase,
                to_phone=customer_phone,
                text=parsed.response_text,
            )

            if success:
                # Persistir mensaje outbound en el historial
                supabase.table("messages").insert({
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "direction": "outbound",
                    "content_type": "text",
                    "content": parsed.response_text,
                    "processed": True,
                }).execute()
                logger.info(f"[OUTBOUND] Respuesta enviada a {customer_phone}")

        # ── 8. Escalar a humano si es necesario ───────────────────────────────
        if parsed.requires_human:
            supabase.table("conversations").update({
                "status": "human_takeover"
            }).eq("id", conversation_id).execute()
            logger.info(f"[ESCALATION] Conversación {conversation_id} marcada para agente humano")

        # ── 9. Marcar mensaje como procesado ──────────────────────────────────
        _mark_processed(supabase, message_id)

    except Exception as e:
        logger.error(f"[ORCH] Error orquestando mensaje {message_id}: {e}", exc_info=True)
        # No marcar como processed — el worker reintentará en el próximo ciclo


def _mark_processed(supabase: Client, message_id: str) -> None:
    """Marca el mensaje como procesado con timestamp UTC."""
    supabase.table("messages").update({
        "processed": True,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", message_id).execute()

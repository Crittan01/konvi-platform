import logging
import os
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types as genai_types
from supabase import Client
from tools.catalog_tool import get_tenant_catalog
from tools.kb_tool import get_tenant_kb_rag, format_kb_for_prompt
from guardrails import validate_orchestrator_output
from whatsapp_sender import send_whatsapp_message
from conversation_contract import (
    CONVERSATION_STATUS_BOT_ACTIVE,
    CONVERSATION_STATUS_CLOSED,
    CONVERSATION_STATUS_HUMAN_TAKEOVER,
    PROCESSING_STATUS_FAILED,
    PROCESSING_STATUS_PROCESSED,
    PROCESSING_STATUS_SKIPPED,
    SKIP_REASON_CLOSED,
    SKIP_REASON_GUARDRAIL,
    SKIP_REASON_HUMAN_TAKEOVER,
    SKIP_REASON_NON_TEXT,
)

logger = logging.getLogger("orchestrator.core")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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


def _get_conversation_status(supabase: Client, conversation_id: str) -> str:
    """Lee el estado actual de la conversación para decidir si el bot puede responder."""
    conv_res = (
        supabase.table("conversations")
        .select("status")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not conv_res.data:
        return CONVERSATION_STATUS_CLOSED
    status = conv_res.data.get("status")
    if status in {
        CONVERSATION_STATUS_BOT_ACTIVE,
        CONVERSATION_STATUS_HUMAN_TAKEOVER,
        CONVERSATION_STATUS_CLOSED,
    }:
        return status
    return CONVERSATION_STATUS_CLOSED


def _set_conversation_status(supabase: Client, conversation_id: str, status: str) -> None:
    """Actualiza el estado de conversación en contrato canónico."""
    supabase.table("conversations").update({"status": status}).eq("id", conversation_id).execute()


def _mark_message_processing(
    supabase: Client,
    message_id: str,
    processing_status: str,
    skip_reason: Optional[str] = None,
    last_error: Optional[str] = None,
) -> None:
    """Registra el outcome explícito del procesamiento del inbound message."""
    supabase.table("messages").update(
        {
            "processing_status": processing_status,
            "processed": processing_status != "pending",
            "processed_at": datetime.now(timezone.utc).isoformat()
            if processing_status != "pending"
            else None,
            "skip_reason": skip_reason,
            "last_error": last_error,
        }
    ).eq("id", message_id).execute()


async def _get_tenant_ai_agent(supabase: Client, tenant_id: str) -> dict:
    """Extrae las reglas del Agente IA parametrizado por el tenant."""
    res = supabase.table("ai_agents").select("*").eq("tenant_id", tenant_id).execute()
    if res.data:
        return res.data[0]
    # Default agent si no ha configurado uno
    return {
        "name": "Bot Asistente",
        "role_description": "Eres un asistente de ventas cordial básico.",
        "strict_guardrails": True
    }

def _build_system_prompt(catalog: list, tenant_name: str, kb_text: str, ai_agent: dict) -> str:
    """Construye el system prompt con RAG dinámico, catálogo, y Anti-Spam estricto."""
    catalog_text = "\n".join([
        f"- {p['title']}: ${p['price']} (stock: {p['stock']})"
        for p in catalog
    ])
    if not catalog_text:
        catalog_text = "(No hay productos disponibles en este momento)"

    kb_section = ""
    if kb_text:
        kb_section = f"\n\nINFORMACIÓN EXTRAÍDA DE LA BASE DE CONOCIMIENTOS (ÚSALA PARA RESPONDER):\n{kb_text}"

    # Reglas dinámicas inyectadas desde UI del Tenant
    strict_rules = ""
    if ai_agent.get("strict_guardrails"):
        strict_rules = """
- ESTRICTO: NO INVENTES INFORMACIÓN, PRECIOS, NI POLÍTICAS que no estén explícitas arriba.
- Si desconoces la respuesta o la KB no es clara, ESCALA a un agente humano inmediatamente (requires_human=true).
- NUNCA des consejos médicos, legales o financieros.
"""

    return f"""Eres {ai_agent.get('name', 'el asistente')} de {tenant_name} atendiendo por WhatsApp.
Misión/Personalidad: {ai_agent.get('role_description', 'Ayudar al cliente')}.

REGLAS OBLIGATORIAS (META ANTI-SPAM COMPLIANCE):
- Mantén las respuestas extremadamente cortas y directas (máximo 2 a 3 oraciones cortas). WhatsApp odia los textos gigantes.
- No seas repetitivo. Evita saludar en cada mensaje si ya están en conversación.
- NUNCA envíes promociones crudas no solicitadas o texto masivo (Evita el bloqueo de la línea WABA).
{strict_rules}
CATÁLOGO ACTUAL ({tenant_name}):
{catalog_text}{kb_section}

Responde SIEMPRE en JSON puro con este esquema exacto:
{{
  "should_respond": true/false,
  "response_text": "texto escrito o null",
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
      5. Persistir outbound + registrar processing_status del inbound
    """

    logger.info(f"[ORCH] Procesando mensaje {message_id} | conv={conversation_id}")

    try:
        # 0) Revisar estado real de la conversación antes de responder
        conversation_status = _get_conversation_status(supabase, conversation_id)
        if conversation_status == CONVERSATION_STATUS_HUMAN_TAKEOVER:
            logger.info("[ORCH] Mensaje %s omitido: conversación en human_takeover", message_id)
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_HUMAN_TAKEOVER,
            )
            return

        if conversation_status == CONVERSATION_STATUS_CLOSED:
            logger.info("[ORCH] Mensaje %s omitido: conversación cerrada", message_id)
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_CLOSED,
            )
            return

        # Producto definido: no-text => escalar a humano, sin respuesta automática.
        if content_type != "text":
            logger.info(
                "[ORCH] Mensaje %s no-text (%s): escalado a human_takeover",
                message_id,
                content_type,
            )
            _set_conversation_status(
                supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_NON_TEXT,
            )
            return

        # ── 1. Resolver datos del tenant ──────────────────────────────────────
        tenant_res = supabase.table("tenants").select("name").eq("id", tenant_id).execute()
        tenant_name = tenant_res.data[0]["name"] if tenant_res.data else "Tienda"

        # ── 1.5 Auto-crear contacto si no existe (desde WhatsApp) ─────────────
        # Solo insertamos si no existe — nunca sobreescribimos datos manuales.
        # consent_given se deja en FALSE (default): el tenant debe obtenerlo
        # por canal propio (link de términos, mensaje explícito, etc.).
        try:
            conv_res = supabase.table("conversations") \
                .select("customer_phone") \
                .eq("id", conversation_id) \
                .execute()
            customer_phone_raw = conv_res.data[0]["customer_phone"] if conv_res.data else None
            if customer_phone_raw:
                supabase.table("contacts").upsert(
                    {
                        "tenant_id": tenant_id,
                        "phone": customer_phone_raw,
                        # name/notes remain NULL — tenant fills them manually
                        "consent_given": False,
                    },
                    on_conflict="tenant_id,phone",
                    ignore_duplicates=True,
                ).execute()
                logger.debug(f"[CONTACT] Upsert contacto {customer_phone_raw} en tenant {tenant_id}")
        except Exception as ce:
            logger.warning(f"[CONTACT] No se pudo upsert contacto: {ce}")

        # ── 2. Obtener catálogo, RAG KB, historial y Config. AI ───────────────
        catalog, kb_docs, history, ai_agent = await __import__('asyncio').gather(
            get_tenant_catalog(supabase, tenant_id),
            get_tenant_kb_rag(supabase, tenant_id, content),
            _get_conversation_history(supabase, conversation_id),
            _get_tenant_ai_agent(supabase, tenant_id)
        )
        kb_text = format_kb_for_prompt(kb_docs)

        # ── 3. Construir prompts ───────────────────────────────────────────────
        system_prompt = _build_system_prompt(catalog, tenant_name, kb_text, ai_agent)
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
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_GUARDRAIL,
            )
            return

        # ── 7. Enviar respuesta si corresponde ────────────────────────────────
        if parsed.should_respond and parsed.response_text:
            # Obtener el teléfono del cliente desde la conversación
            conv_res = supabase.table("conversations").select("customer_phone").eq("id", conversation_id).execute()
            customer_phone = conv_res.data[0]["customer_phone"]

            meta_message_id = await send_whatsapp_message(
                tenant_id=tenant_id,
                supabase=supabase,
                to_phone=customer_phone,
                text=parsed.response_text,
            )

            if meta_message_id:
                # Persistir mensaje outbound en el historial
                supabase.table("messages").insert({
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "direction": "outbound",
                    "content_type": "text",
                    "content": parsed.response_text,
                    "meta_message_id": meta_message_id,
                    "processed": True,
                    "processing_status": PROCESSING_STATUS_PROCESSED,
                }).execute()
                logger.info(f"[OUTBOUND] Respuesta enviada a {customer_phone}")

        # ── 8. Escalar a humano si es necesario ───────────────────────────────
        if parsed.requires_human:
            _set_conversation_status(
                supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
            )
            logger.info(f"[ESCALATION] Conversación {conversation_id} marcada para agente humano")

        # ── 9. Marcar mensaje como procesado ──────────────────────────────────
        _mark_message_processing(
            supabase,
            message_id,
            processing_status=PROCESSING_STATUS_PROCESSED,
        )

    except Exception as e:
        logger.error(f"[ORCH] Error orquestando mensaje {message_id}: {e}", exc_info=True)
        _mark_message_processing(
            supabase,
            message_id,
            processing_status=PROCESSING_STATUS_FAILED,
            last_error=str(e)[:1000],
        )

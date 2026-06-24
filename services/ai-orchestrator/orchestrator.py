import logging
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types as genai_types
from supabase import Client
from tools.catalog_tool import get_tenant_catalog
from tools.payment_link_tool import handle_payment_link_if_applicable
from tools.kb_tool import get_tenant_kb_rag, format_kb_for_prompt
from guardrails import validate_orchestrator_output
from whatsapp_sender import send_whatsapp_message
from checkout_form import CheckoutFormConductor
from conversation_contract import (
    CONVERSATION_STATUS_BOT_ACTIVE,
    CONVERSATION_STATUS_CLOSED,
    CONVERSATION_STATUS_HUMAN_TAKEOVER,
    PROCESSING_STATUS_FAILED,
    PROCESSING_STATUS_PENDING,
    PROCESSING_STATUS_PROCESSED,
    PROCESSING_STATUS_SKIPPED,
    CONVERSATION_STATUS_OPTED_OUT,
    SKIP_REASON_CLOSED,
    SKIP_REASON_GUARDRAIL,
    SKIP_REASON_HUMAN_TAKEOVER,
    SKIP_REASON_NON_TEXT,
    SKIP_REASON_OPTED_OUT,
)

logger = logging.getLogger("orchestrator.core")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "25"))
CONVERSATION_WINDOW_HOURS = int(os.getenv("CONVERSATION_WINDOW_HOURS", "24"))

# ── Consentimiento Ley 1581 de 2012 ──────────────────────────────────────────
CONSENT_TEXT_VERSION = "v2026-04"
CONSENT_QUESTION_TEMPLATE = (
    # Rev. 89.b + 91 — UX cordial, action-first. Cumple Habeas Data
    # Colombia (consent previo + expreso + informado + revocable).
    # Rev. 91: cierre con "*SÍ* o *NO*" para hacer la respuesta
    # esperada inequívoca (caso S9 happy path: cliente decía "Sigamos"
    # en vez de "Sí" y el detector consent_yes no disparaba).
    "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te "
    "pediré algunos datos (nombre, dirección, etc.) para esta compra "
    "y futuros pedidos.\n\n"
    "Si en algún momento quieres que los borre, solo dímelo. \n\n"
    "¿Estás de acuerdo? *SÍ* o *NO*."
)
ORDER_CREATION_CONFIRMATION_TEMPLATE = (
    "Listo, te genero el link de pago.\n\n"
    "Por Wompi puedes pagar con tarjeta, PSE, Nequi, Daviplata, Bancolombia, "
    "y otras opciones más.\n\n"
    "¿Confirmas que armamos el pedido?"
)
_CONSENT_QUESTION_MARKERS = (
    # Rev. 89.b: nuevos markers del consent UX-cordial. Sin estos el
    # detector no reconocía la pregunta y "Sí" del cliente no avanzaba
    # al FSM → loop infinito (bug observado en log conv f27516bb).
    "estas de acuerdo",
    "esta de acuerdo",
    "estás de acuerdo",
    "está de acuerdo",
    "con tu autorizacion",
    "con tu autorización",
    "te pedire algunos datos",
    "te pediré algunos datos",
    # Markers legacy (versiones previas del consent prompt):
    "nos autorizas",
    "autorizas",
    "me autorizas",
    "eliminar mis datos",
    "elimina mis datos",
)
# Rev. 104 (F1-1 batch 4) — extraído a safety/consent_gates.py.
from safety.consent_gates import (
    detect_revocation_intent as _detect_revocation_intent,
    detect_data_export_intent as _detect_data_export_intent,
    detect_rectification_intent as _detect_rectification_intent,
    detect_minor_intent as _detect_minor_intent,
    REVOCATION_TOKENS as _REVOCATION_TOKENS,
    DATA_EXPORT_TOKENS as _DATA_EXPORT_TOKENS,
    RECTIFICATION_TOKENS as _RECTIFICATION_TOKENS,
    MINOR_EXPLICIT_PHRASES as _MINOR_EXPLICIT_PHRASES,
)

# Rev. 84 — Guardrails de cumplimiento Meta Business Policy.
#
# Cita oficial (https://business.whatsapp.com/policy):
#   "Healthcare: Telemedicine and health data prohibited in non-compliant
#    systems"
#   "Personal data: Cannot collect/share full payment card numbers, bank
#    accounts, ID documents"
#
# Estas detecciones corren PRE-LLM con respuestas determinísticas para
# garantizar cumplimiento sin depender de la disciplina del modelo.

# P0 — crisis de salud mental: escalación INMEDIATA con mensaje de
# seguridad. Lista conservadora; falsos positivos son mejor que falsos
# negativos en este caso.
# Rev. 104 (F1-1 batch 2) — extraídos a safety/content_safety.py.
# Aliases legacy para call-sites internos sin breaking changes.
from safety.content_safety import (
    detect_mental_health_crisis as _detect_mental_health_crisis,
    MENTAL_HEALTH_CRISIS_PHRASES as _MENTAL_HEALTH_CRISIS_PHRASES,
)
import re as _re_meta  # mantenido para otros usos en este módulo


# Rev. 92.b — Telemedicina / consultas médicas / diagnóstico.
# Meta Business Policy:
#   "Healthcare: Telemedicine and health data prohibited in non-compliant
#    systems".
# WhatsApp NO es HIPAA/GDPR-compliant para data clínica → bot NO puede
# diagnosticar, recomendar tratamiento de condición médica, ni dar
# advice de salud específica. Sí puede informar BENEFICIOS COSMÉTICOS
# del producto, sin claims terapéuticos.
#
# Detección PRE-LLM: si el cliente menciona enfermedad/condición médica
# o pide diagnóstico, respondemos templated redirigiendo a profesional
# médico. Conservador con falsos positivos — mejor mandar al médico
# que dar consejo médico ilegal.
# Rev. 104 (F1-1) — extraídos a safety/domain_filter.py (strangler fig).
# Aliases legacy mantenidos para call-sites internos del orchestrator y
# tests que aún importan los nombres viejos. Eliminar cuando se complete
# el strangle (post-Fase 1).
from safety.domain_filter import (
    detect_medical_query as _detect_medical_query,
    detect_drug_purchase_request as _detect_drug_purchase_request,
    MEDICAL_QUERY_PHRASES as _MEDICAL_QUERY_PHRASES,
    DRUG_PURCHASE_PHRASES as _DRUG_PURCHASE_PHRASES,
)


# Rev. 104 (F1-1 batch 2) — extraído a safety/content_safety.py.
from safety.content_safety import (
    detect_sensitive_payment_data as _detect_sensitive_payment_data,
)


# Rev. 86 — Detector de intent de UPDATE de datos personales.
# UX cliente conocido: tras ver el resumen, puede pedir cambiar dirección
# (envío a oficina), correo, etc. Sin este detector, el LLM podría no
# entrar al sub-flow correcto.
_DATA_UPDATE_PHRASES = (
    "cambia mi direccion", "cambia la direccion", "cambiar la direccion",
    "cambiar mi direccion", "actualizar direccion", "actualizar la direccion",
    "envialo a", "enviar a otra", "enviar a la oficina", "envia a la oficina",
    "diferente direccion", "otra direccion", "mismo de antes no",
    "cambia mi correo", "actualizar correo", "nuevo correo",
    "cambia mi celular", "cambia mi telefono", "actualizar telefono",
    "cambia mis datos", "actualizar mis datos", "actualizar datos",
    "modificar datos", "no es esa direccion", "esa direccion no",
    "envia a otro lado", "ahora vivo en", "ahora estoy en",
)


def _detect_data_update_intent(text: str) -> Optional[str]:
    """Rev. 86 — True (con campo afectado) si el cliente quiere actualizar
    un dato personal antes de confirmar el pedido.

    Returns:
        None — no detect intent
        "address" — quiere cambiar dirección
        "email" — quiere cambiar correo
        "phone" — quiere cambiar celular
        "general" — quiere cambiar algún dato sin especificar cuál

    Usado en `READY_FOR_SUMMARY` para entrar a sub-flow de UPDATE en vez
    de generar payment_link directo.
    """
    if not text:
        return None
    normalized = _normalize_text_simple(text)
    if not any(phrase in normalized for phrase in _DATA_UPDATE_PHRASES):
        return None
    if any(k in normalized for k in ("direccion", "envialo", "enviar a", "envia a", "vivo en", "estoy en", "oficina")):
        return "address"
    if "correo" in normalized:
        return "email"
    if any(k in normalized for k in ("celular", "telefono")):
        return "phone"
    return "general"


# Rev. 103 — Pre-LLM extractor de phone alternativo de envío.
# Estrategia: requiere keyword DISCRIMINANTE (alterno, recibe, otra persona,
# actualiza, etc.) ANTES de extraer 10 dígitos. Sin keyword → asume el
# cliente solo dio su WhatsApp normal y NO extrae (evita falsos positivos).
_SHIPPING_KEYWORDS = (
    "alternativo", "alterno", "de envio", "de envío", "de entrega",
    "de contacto", "otra persona", "lo recibe", "la recibe",
    "lo va a recibir", "la va a recibir", "lo recibira", "la recibira",
    "actualiza el celular", "actualizar el celular",
    "actualiza mi celular", "actualizar mi celular",
    "actualiza el numero", "actualiza el número",
    "adicional", "nuevo numero", "nuevo número",
    "diferente", "secundario",
    "su celular es", "su numero es", "su número es",
    # Sem 7 F2 cierre — verbos de cambio explícito sobre número (caso
    # runtime: "Deseo cambiar el número 322... por 3003919461"). Sin
    # estos verbos, el regex no disparaba PRE_BYPASS → LLM componía
    # outbound libre con resumen mal renderizado.
    "cambiar el numero", "cambiar el número",
    "cambia el numero", "cambia el número",
    "cambiar mi numero", "cambiar mi número",
    "cambia mi numero", "cambia mi número",
    "reemplazar el numero", "reemplazar el número",
    "reemplaza el numero", "reemplaza el número",
    "modificar el numero", "modificar el número",
    "modifica el numero", "modifica el número",
    "cambiar el celular", "cambia el celular",
    "reemplazar el celular", "reemplaza el celular",
    "modificar el celular", "modifica el celular",
)

_SHIPPING_PHONE_DIGITS_RE = re.compile(r"(?:\+?57\s*)?(\d{10})\b")


def _detect_shipping_phone_update(
    text: str, history: Optional[list[dict]] = None,
) -> Optional[str]:
    """Rev. 103 — Pre-LLM: extrae phone alternativo de envío.

    Patrones cubiertos:
      - Con keyword en mismo inbound (legacy):
        * "celular alternativo: 3001234567"
        * "actualiza mi celular: 3001234567"
        * "el pedido lo recibe mi mamá, su celular es 3001234567"
        * "número adicional 3009998877"
        * "cambiar el número 3001234567 por 3009998877"
      - Sem 7 F2 cierre 2026-05-20 — Bug P7 founder UAT (conv 7053666a):
        Sin keyword en inbound PERO outbound anterior pidió número alterno
        ("dime cuál es el número", "compárteme tu celular alterno").
        Cliente responde solo "3223840887" → debe interpretarse como
        update. Sin esto, el resumen post-update perdía el número y el
        cliente debía señalar la omisión explícitamente.

    Defensivo: si el cliente solo da su WhatsApp normal sin contexto
    (no keyword en inbound + no pregunta previa del bot), NO extrae.

    Retorna 10 dígitos sin prefijo (+57 implícito) o None.
    """
    if not text:
        return None
    digits_matches = _SHIPPING_PHONE_DIGITS_RE.findall(text)
    if not digits_matches:
        return None

    # Camino A: keyword discriminante en el inbound mismo.
    normalized = _normalize_text_simple(text).lower()
    has_keyword = any(kw in normalized for kw in _SHIPPING_KEYWORDS)

    # Camino B: outbound anterior pidió explícitamente el número alterno
    # (Sem 7 F2 cierre 2026-05-20 — Bug P7).
    contextual_request = False
    if not has_keyword and history:
        contextual_request = _last_outbound_requested_shipping_phone(history)

    if not (has_keyword or contextual_request):
        return None

    # Último match: caso "cambiar X por Y" → Y (el nuevo).
    digits = digits_matches[-1]
    if len(digits) != 10 or digits[0] == "0":
        return None
    return digits


# Detección semántica de outbounds que piden número alterno de envío.
# Sem 7 F2 cierre 2026-05-20 — Bug P7 founder UAT.
#
# Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv f6ec7213):
# El bot dijo "Cuál es el número de celular que quieres agregar para el
# envío?" y los markers substring rígidos no machearon (faltaba contigüidad
# por "de celular" intercalado). Cliente respondió "3223840887" → detector
# no disparó → resumen rendereado con contact_record stale (sin segundo
# número). Solución arquitectónica: reemplazar lista de substrings frágiles
# por una regex SEMÁNTICA que captura la intención independiente del
# fraseo exacto del LLM.
#
# Intención capturada: "outbound pide al cliente un número/teléfono/celular
# alterno o adicional para envío". Tres patrones complementarios para evitar
# tanto falsos negativos (markers rígidos previos) como falsos positivos
# ("Te envío tu link de pago a tu celular" — informativo, no petición).
_SHIPPING_PHONE_REQUEST_REGEX = re.compile(
    # P1 — interrogativo/imperativo + sustantivo + cualidad de petición.
    #      "Cuál es el número de celular que quieres agregar para el envío?"
    r"\b(?:cual|dime|dame|comparteme)\b.*?"
    r"\b(?:numero|telefono|celular)\b.*?"
    r"\b(?:agregar|adicional|alterno|alternativo|envio|entrega)\b"
    r"|"
    # P2 — verbo de petición + sustantivo.
    #      "Agrega tu celular", "Compárteme el número adicional"
    r"\b(?:agrega|agregar|comparteme|dame)\b.*?"
    r"\b(?:numero|telefono|celular)\b"
    r"|"
    # P3 — sustantivo + cualidad alterna (orden inverso o adyacente).
    #      "El celular adicional", "número alternativo"
    r"\b(?:numero|telefono|celular)\b\s+\w*\s*"
    r"\b(?:adicional|alterno|alternativo)\b"
    r"|"
    # P4 — sustantivo + "para" + envío/entrega.
    #      "celular para el envío", "número para la entrega"
    r"\b(?:numero|telefono|celular)\b\s+(?:para|de)\s+(?:el\s+|la\s+)?"
    r"\b(?:envio|entrega)\b",
    flags=re.IGNORECASE | re.DOTALL,
)


def _last_outbound_requested_shipping_phone(history: list[dict]) -> bool:
    """True si el último outbound (no context_snapshot) pidió al cliente
    un número alterno de envío. Permite que el cliente responda solo con
    dígitos ("3223840887") sin keyword y aún así extraerlo correctamente.

    Mira solo el outbound MÁS RECIENTE (1 turno atrás) — más allá podría
    estar fuera de contexto.

    Sem 7 F2 cierre 2026-05-21 — detección semántica vía regex (antes:
    lista de substrings frágiles que perdían matches con filler words).
    """
    if not history:
        return False
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        if not content.strip():
            continue
        normalized = _normalize_text_simple(content).lower()
        return bool(_SHIPPING_PHONE_REQUEST_REGEX.search(normalized))
    return False


# Rev. 83: detección de cancelación de pedido. UX: el cliente que cancela
# NO debe ser escalado a humano (sería molesto). Bot acusa recibo cordial,
# cierra el cart, deja la puerta abierta para volver.
# Solo escalar si el cliente lo PIDE explícitamente (ver _detect_human_handoff).
_CANCEL_INTENT_PHRASES = (
    "cancela mi pedido", "cancelar mi pedido", "cancela el pedido",
    "cancela la compra", "cancelar la compra",
    "ya no quiero", "ya no me interesa", "ya no lo quiero",
    "mejor cancela", "mejor no", "mejor déjalo", "mejor dejalo",
    "olvidalo", "olvídalo", "olvida la compra",
    "no me interesa la compra", "no quiero comprar",
    "déjalo así", "dejalo asi",
    "cancela todo", "cancelar todo",
    "no lo voy a comprar", "no voy a comprar",
)
_CONSENT_YES_TOKENS = {"si", "sí", "yes", "dale", "ok", "claro", "acepto", "autorizo", "afirmativo", "listo", "de acuerdo"}
_CONSENT_NO_TOKENS = {"no", "nope", "negativo", "no gracias", "prefiero no", "nunca", "jamas", "rechazo", "no autorizo"}
_CONSENT_YES_PHRASES = {"por supuesto", "de una", "hágale", "hagale", "claro que si"}
_CONSENT_NO_PHRASES = {"de ninguna manera", "ni loco", "nunca", "jamas", "no autorizo"}
_AFFIRMATIVE_CONFIRMATION_TOKENS = {
    "si", "sí", "ok", "dale", "listo", "claro", "confirmo", "confirmado",
    "procede", "procedamos", "hagamos", "crear", "pedido",
}
_NEGATIVE_CONFIRMATION_TOKENS = {"no", "nunca", "jamas", "cancela", "cancelar", "deten", "detener"}
_ORDER_CONFIRMATION_MARKERS = (
    "procedemos a crear",
    "crear el pedido",
    "deseas crear tu pedido ahora",
    "te genero el link de pago",
    "te genero el link",
    "enviarte el link de pago",
    "link de pago ahora",
    "generando tu pedido",
    "creamos el pedido",
    "armamos el pedido",
    "confirmas que armamos",
    # Marcador del resumen determinístico (Bug C). Permite que la confirmación
    # del cliente al resumen ("Si, confirmo") avance directo a payment link.
    "generar tu link de pago",
    "datos estan correctos para generar",
    # Sem 7 F2 cierre — variantes con determinante "el" (no solo "tu").
    # Caso runtime: bot dijo "Para confirmar tu pedido y generar el link
    # de pago, respóndeme con un Sí, confirmo" → marker "generar tu link"
    # NO matchea por el "tu" vs "el". Sin matcher, el bypass payment_link
    # directo NO dispara → LLM compone "te genero el link" → anti-hallu
    # bloquea → fallback "armamos pedido?" = 1 turno extra (smell B).
    "generar el link de pago",
    "para generar el link",
    "confirmo para generar",
    "respondeme con un si confirmo",
    "respondeme con un si, confirmo",
)
_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", flags=re.IGNORECASE)
# Versión search-friendly (sin ^$) para extraer email embebido en texto libre.
_EMAIL_SEARCH_REGEX = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", flags=re.IGNORECASE)


def _normalize_text_simple(text: str) -> str:
    """Normaliza para comparación: minúsculas, sin acentos."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


# Rev. 104 (F1-1 batch 4) — _detect_revocation_intent extraído a
# safety/consent_gates.py (importado arriba como alias legacy).


# Rev. 103 — Detector pre-LLM determinístico de petición explícita de
# atención humana. Razón: la salvaguarda anti-escalación-espuria
# (orchestrator.py guard en CATALOG_MODE/NEEDS_SHIPPING_CITY/AWAITING_CARRIER_SELECTION)
# pisaba `requires_human=True` cuando el LLM lo detectaba pero el cliente
# estaba en modo consulta. Ese guard es necesario contra falsos positivos
# del LLM, pero NO debe atrapar al cliente que pide explícitamente un
# asesor. Este detector marca un flag `force_human_request` que sobrevive
# a TODOS los guards y dispara `_set_conversation_status(human_takeover)`.
# Rev. 104 (F1-1 batch 3) — extraído a safety/escalation.py.
from safety.escalation import (
    detect_human_request_intent as _detect_human_request_intent,
    HUMAN_REQUEST_PATTERNS as _HUMAN_REQUEST_PATTERNS,
)


# Rev. 97 — Cliente self-service Habeas Data Art. 14 (acceso a sus datos).
# El titular puede pedir vía WhatsApp un resumen de los datos que el
# tenant guarda sobre él. Detector pre-LLM determinístico (no se delega
# al modelo para evitar respuestas erráticas a un derecho fundamental).
# Rev. 104 (F1-1 batch 4) — _DATA_EXPORT_TOKENS + _detect_data_export_intent
# extraídos a safety/consent_gates.py (importados arriba como aliases legacy).


# Rev. 101 (F6) — Detector pre-LLM rectificación Habeas Data Art. 16.
# El titular puede solicitar corrección de un dato concreto vía WhatsApp:
# email, dirección, nombre, documento. NO actualizamos auto — registramos
# audit "rectified" pendiente de revisión + notificamos al tenant para
# que valide y ejecute el cambio (puede requerir verificación de identidad).
# Rev. 104 (F1-1 batch 4) — _RECTIFICATION_TOKENS + _detect_rectification_intent
# extraídos a safety/consent_gates.py (importados arriba como aliases legacy).


# Rev. 102 — Detector pre-LLM de minoría de edad.
# Decreto 1377/2013 Art. 7 prohíbe el tratamiento de datos de menores
# sin autorización del representante legal. Si el cliente declara ser
# menor (texto explícito o número de edad < 18), el bot NO continúa el
# flujo comercial: pide formalmente datos del representante legal y
# escala a operador humano.
#
# Conservador: falsos positivos (e.g., "tengo 16 productos") son
# aceptables porque escalan a humano que decide. Falsos negativos NO
# son aceptables porque generan tratamiento ilegal de datos de menor.
# Rev. 104 (F1-1 batch 4) — _MINOR_EXPLICIT_PHRASES, _AGE_REGEX, _detect_minor_intent
# extraídos a safety/consent_gates.py (importados arriba como aliases legacy).


def _mask_value(value: Optional[str]) -> str:
    """Mask sensible value, mostrando solo primeros 2 + últimos 4 chars."""
    if not value:
        return "(no registrado)"
    s = str(value)
    if len(s) <= 6:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 6) + s[-4:]


def _build_customer_data_summary(
    supabase: Client, contact_id: str, tenant_id: str
) -> str:
    """Rev. 97 — Resumen de datos del titular para envío vía WhatsApp.

    Output text-only (PDF + Meta document upload diferido a follow-up).
    Incluye campos PII enmascarados parcialmente para que el cliente
    confirme qué datos tenemos sin exponer doc completo en chat.
    """
    try:
        c_res = supabase.table("contacts").select(
            "name, email, phone, document_type, document_number, address, "
            "consent_given, consent_given_at, consent_revoked_at"
        ).eq("id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
        if not c_res.data:
            return (
                "No tenemos registros tuyos en el sistema. "
                "Si crees que esto es un error, escríbenos al correo "
                "soporte para ayudarte."
            )
        c = c_res.data[0]

        # Conteo de orders.
        orders_count = 0
        try:
            o_res = supabase.table("orders").select(
                "id", count="exact",
            ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).execute()
            orders_count = int(getattr(o_res, "count", 0) or 0)
        except Exception:
            pass

        consent_status = "Activo" if c.get("consent_given") else "Revocado"

        lines = [
            "*Resumen de tus datos personales*",
            "",
            f"• Nombre: {c.get('name') or '(no registrado)'}",
            f"• Email: {c.get('email') or '(no registrado)'}",
            f"• Teléfono: {_mask_value(c.get('phone'))}",
            f"• Documento: {c.get('document_type') or '?'} {_mask_value(c.get('document_number'))}",
            f"• Dirección: {'(registrada)' if c.get('address') else '(no registrada)'}",
            "",
            f"• Consentimiento: {consent_status}",
            f"• Pedidos asociados: {orders_count}",
            "",
            "Si quieres el reporte completo en formato JSON, escríbele al "
            "tenant pidiéndolo formalmente (Habeas Data Art. 14 Ley 1581/2012). "
            "Si quieres eliminar tus datos, responde *elimina mis datos*.",
        ]
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[SAR] Error generando summary contact=%s: %s", contact_id, exc)
        return (
            "Tu solicitud quedó registrada. En 24-48h te enviaremos el "
            "reporte completo de los datos que guardamos sobre ti "
            "(Habeas Data Ley 1581/2012)."
        )


def _detect_cancel_intent(text: str) -> bool:
    """Rev. 83 — True si el cliente quiere cancelar su pedido / compra.

    NO escalamos a humano por esto (UX): el bot acusa recibo cordial,
    cierra el cart, deja la puerta abierta. Solo si el cliente PIDE
    explícitamente un asesor, ahí sí escalamos (otro detector).
    """
    if not text:
        return False
    normalized = _normalize_text_simple(text)
    return any(phrase in normalized for phrase in _CANCEL_INTENT_PHRASES)


def _tokenize_for_consent(normalized: str) -> set[str]:
    """Rev. 91 — Tokenizador robusto para consent detection.

    Strip puntuación de cada token antes de comparar contra los sets
    `_CONSENT_YES_TOKENS` / `_CONSENT_NO_TOKENS`. Sin esto, una respuesta
    natural como "Sí, continuemos por favor" no matchea porque el primer
    token queda como "sí," (con coma) y el set no lo reconoce.
    """
    return {re.sub(r"[,.!?;:]+", "", tok) for tok in normalized.split() if tok}


# Rev. 103 — Pre-LLM gate de confirmación de pedido. Defensivo contra
# Gemini marcando intent=order_acknowledgment cuando el cliente envía
# texto largo (dump PII, pregunta, etc.) que NO es confirmación real.
_ORDER_CONFIRM_PHRASES: tuple[str, ...] = (
    "si confirmo", "sí confirmo", "confirmo el pedido", "confirmo la compra",
    "confirmo", "confirma", "confirmado", "confirmar",
    "si esta bien", "sí está bien", "esta bien", "está bien",
    "si listo", "sí listo", "listo confirmo", "ok confirmo",
    "perfecto confirmo", "vale confirmo", "dale confirmo",
    "si por favor", "sí por favor", "afirmativo",
    "claro confirmo", "claro que sí confirmo", "claro que si confirmo",
)
_ORDER_CONFIRM_TOKENS: set[str] = {
    "si", "sí", "confirmo", "confirmar", "ok", "vale", "dale", "listo",
    "perfecto", "afirmativo", "claro",
}
# Pistas de PII / texto no-confirmatorio (si están, NO es confirmación pura).
_NON_CONFIRM_HINTS: tuple[str, ...] = (
    "@", "soy ", "mi nombre", "mi correo", "mi email", "mi cédula", "mi cedula",
    "mi documento", "mi direccion", "mi dirección", "calle", "carrera",
    "diagonal", "transversal", "barrio", "cc ", "ti ", "ce ",
)


def _detect_order_confirmation(text: str) -> bool:
    """Rev. 103 — Pre-LLM: True si el cliente confirma EXPLÍCITAMENTE.

    Cuando el cliente ya recibió `📋 Resumen + ¿Confirmas?`, el siguiente
    inbound debe ser una afirmación corta ("sí", "confirmo", "ok") sin
    PII. Si trae datos personales (email, dirección, "mi cédula", etc.)
    es probablemente un dump duplicado u otra cosa — NO confirmación.

    Bug ref: T9-T10 en log conv 573125835649_20260502 — el cliente
    "envió" el dump dos veces (replay UAT runner) y Gemini interpretó el
    segundo como order_acknowledgment, generando link de pago sin
    confirmación real.

    Defensas:
      • PII detectada → False (no es confirmación pura).
      • Texto > 80 chars → False (probablemente otro contenido).
      • Negaciones explícitas → False.
      • Phrase canónica ("sí confirmo", "confirmo", "ok") → True.
      • Token único ("si", "ok", "vale") en mensaje corto → True.
    """
    if not text:
        return False
    normalized = _normalize_text_simple(text).lower()
    # Defensa 1: PII presente → no es confirmación pura.
    if any(hint in normalized for hint in _NON_CONFIRM_HINTS):
        return False
    # Defensa 2: texto largo → probablemente no es solo confirmación.
    if len(normalized) > 80:
        return False
    # Defensa 3: negación explícita.
    if any(phrase in normalized for phrase in _CONSENT_NO_PHRASES):
        return False
    # Frases canónicas de confirmación.
    if any(phrase in normalized for phrase in _ORDER_CONFIRM_PHRASES):
        return True
    # Tokens cortos.
    tokens = _tokenize_for_consent(normalized)
    return bool(tokens & _ORDER_CONFIRM_TOKENS) and not bool(tokens & _CONSENT_NO_TOKENS)


def _detect_consent_yes(text: str) -> bool:
    normalized = _normalize_text_simple(text)
    if any(phrase in normalized for phrase in _CONSENT_NO_PHRASES):
        return False
    if any(phrase in normalized for phrase in _CONSENT_YES_PHRASES):
        return True
    tokens = _tokenize_for_consent(normalized)
    return bool(tokens & _CONSENT_YES_TOKENS) and not bool(tokens & _CONSENT_NO_TOKENS)


def _detect_consent_no(text: str) -> bool:
    normalized = _normalize_text_simple(text)
    if any(phrase in normalized for phrase in _CONSENT_NO_PHRASES):
        return True
    tokens = _tokenize_for_consent(normalized)
    return bool(tokens & _CONSENT_NO_TOKENS)


def _last_outbound_was_consent_question(history: list[dict]) -> bool:
    """Retorna True si el último mensaje del bot fue la pregunta de consentimiento."""
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() == "outbound":
            content_norm = _normalize_text_simple(str(msg.get("content") or ""))
            return any(marker in content_norm for marker in _CONSENT_QUESTION_MARKERS)
    return False


# Rev. 73 — markers de outbounds en estado de recolección de datos personales.
# Se usan para skipear shipping_quote_tool durante recolección activa (evita
# malinterpretar nombres de ciudades como cambio de destino).
_DATA_COLLECTION_QUESTION_MARKERS: tuple[str, ...] = (
    "cual es tu correo",
    "cual es tu email",
    "tu correo electronico",
    "tu nombre completo",
    "como te llamas",
    "tu numero de documento",
    "tu nit",
    "tu cedula",
    "tu direccion exacta",
    "direccion de entrega",
    "donde te enviamos",
)


def _last_outbound_was_data_collection_question(history: list[dict]) -> bool:
    """Retorna True si el último outbound fue una pregunta de recolección de
    datos personales (email/nombre/documento/dirección). Distinto de consent.

    Rev. 73 — reemplaza el bypass por `consent_given` histórico que causaba
    que el cliente conocido nunca pasara por shipping_quote_tool en sesiones
    nuevas (log 2026-04-29 conv 615a9902)."""
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() == "outbound":
            content_norm = _normalize_text_simple(str(msg.get("content") or ""))
            return any(marker in content_norm for marker in _DATA_COLLECTION_QUESTION_MARKERS)
    return False


def _hash_phone(phone: Optional[str]) -> Optional[str]:
    """Rev. 93 — Hash sha256 del phone para `consent_audit_log.phone_hash`.

    Permite lookup post-anonimización del contact sin exponer el phone.
    """
    if not phone:
        return None
    import hashlib as _hashlib
    normalized = re.sub(r"[\s+\-]", "", str(phone))
    return _hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _log_consent_event(
    supabase: Client,
    *,
    tenant_id: str,
    contact_id: Optional[str],
    phone: Optional[str],
    event: str,                    # 'granted' | 'revoked' | etc.
    source: str = "whatsapp",
    conversation_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    evidence: Optional[dict] = None,
) -> None:
    """Rev. 93 — INSERT en consent_audit_log (append-only, Art. 9).

    Falla silently con log warning — un fallo del audit log NO debe
    abortar la operación principal de consent. La tabla tiene triggers
    anti-tamper, así que no hay forma de "fix" un row mal escrito; el
    siguiente intento crea un row nuevo correcto.
    """
    try:
        row = {
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "phone_hash": _hash_phone(phone),
            "event": event,
            "source": source,
            "conversation_id": conversation_id,
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "evidence": evidence or {},
        }
        # tenant_filter:exempt:payload_includes_tenant_id
        supabase.table("consent_audit_log").insert(row).execute()
    except Exception as e:
        logger.warning(
            "[CONSENT_AUDIT] No se pudo registrar evento %s contact=%s: %s",
            event, contact_id, e,
        )


def _log_pii_access(
    supabase: Client,
    *,
    tenant_id: str,
    contact_id: str,
    accessed_by: str,              # 'user:<email>' | 'agent:orchestrator' | 'integration:wompi'
    purpose: str,                  # 'inbox_view' | 'wompi_checkout' | 'data_export' | etc.
    fields_accessed: list[str],
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Rev. 93 — INSERT en pii_access_log (append-only, Art. 9).

    Llamar cuando un actor explícitamente lee PII del contacto (NO en
    cada SELECT sistémico — solo en lecturas con propósito específico).
    """
    try:
        row = {
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "accessed_by": accessed_by,
            "actor_user_id": actor_user_id,
            "purpose": purpose,
            "fields_accessed": fields_accessed,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
        # tenant_filter:exempt:payload_includes_tenant_id
        supabase.table("pii_access_log").insert(row).execute()
    except Exception as e:
        logger.warning(
            "[PII_ACCESS] No se pudo registrar acceso contact=%s: %s",
            contact_id, e,
        )


def _record_consent(
    supabase: Client,
    contact_id: str,
    tenant_id: str,
    given: bool,
    conversation_id: str,
) -> None:
    """Registra consentimiento o revocación directamente en DB (sin HTTP round-trip).

    Rev. 93: además del UPDATE en `contacts`, escribe en `consent_audit_log`
    para audit trail inmutable (Art. 9). El log persiste aunque
    posteriormente se haga hard-delete del contact.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Capturar phone ANTES del UPDATE (para hash en audit log).
    phone_for_hash: Optional[str] = None
    try:
        existing = supabase.table("contacts").select("phone").eq(
            "id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
        if existing.data:
            phone_for_hash = existing.data[0].get("phone")
    except Exception:
        pass  # Best-effort; el audit log puede ir sin hash.

    try:
        if given:
            update = {
                "consent_given": True,
                "consent_given_at": now_iso,
                "consent_source": "whatsapp",
                "consent_channel": "whatsapp",
                "consent_text_version": CONSENT_TEXT_VERSION,
                "consent_notice_version": CONSENT_TEXT_VERSION,
                "consent_revoked_at": None,
                "consent_revoked_reason": None,
                "consent_evidence": {
                    "captured_via": "whatsapp",
                    "conversation_id": conversation_id,
                    "timestamp": now_iso,
                },
            }
            event_for_log = "granted"
            logger.info("[CONSENT] Registrado via chat | contact=%s tenant=%s", contact_id, tenant_id)
        else:
            # Ley 1581/2012 Colombia (Habeas Data) — Art. 9 audit + Art. 15
            # supresión total de PII en revocación. Anonimizamos los 6
            # campos PII de `contacts`. `phone` se conserva como canal de
            # comunicación (cliente puede bloquear el número si requiere
            # supresión total del canal — out of scope del orchestrator).
            update = {
                "consent_given": False,
                "consent_revoked_at": now_iso,
                "consent_revoked_reason": "Revocación solicitada por el titular vía WhatsApp",
                "name": None,
                "email": None,
                "document_type": None,    # Rev. 92.e — Art. 15 (gap fix)
                "document_number": None,  # Rev. 92.e — Art. 15 (gap fix)
                "address": None,
                "notes": None,
            }
            event_for_log = "revoked"
            logger.info("[CONSENT] Revocado + anonimizado | contact=%s tenant=%s", contact_id, tenant_id)
        supabase.table("contacts").update(update).eq("id", contact_id).eq("tenant_id", tenant_id).execute()

        # Rev. 93 — Append-only audit log (Art. 9).
        _log_consent_event(
            supabase,
            tenant_id=tenant_id,
            contact_id=contact_id,
            phone=phone_for_hash,
            event=event_for_log,
            source="whatsapp",
            conversation_id=conversation_id,
            evidence={
                "consent_text_version": CONSENT_TEXT_VERSION,
                "timestamp": now_iso,
            },
        )
    except Exception as e:
        logger.error("[CONSENT] Error registrando consentimiento contact=%s: %s", contact_id, e)


def _extract_first_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    tokens = [token for token in str(name).split() if token]
    if not tokens:
        return None
    return tokens[0].title()


def _get_conversation_customer_phone(supabase: Client, tenant_id: str, conversation_id: str) -> Optional[str]:
    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("tenant_id", tenant_id)
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    if not conv_res.data:
        return None
    return str(conv_res.data[0].get("customer_phone") or "").strip() or None


_CUSTOMER_CONTEXT_LAZY_TOKENS: frozenset[str] = frozenset({
    # Tokens léxicos que indican que el cliente está consultando por sus operaciones.
    # Si la query del cliente contiene cualquiera de estos, cargamos el contexto.
    "pedido", "pedidos", "orden", "ordenes", "compra", "compras",
    "tracking", "guia", "guía", "envio", "envío", "rastreo",
    "reclamo", "reclamos", "queja", "quejas",
    "garantia", "garantía", "devolucion", "devolución", "cambio",
    "estado", "status",
    # F7-lite cart recovery: el cliente vuelve a hablar de "el carrito" /
    # "lo del otro día" / "retomar" — disparamos contexto para inyectar
    # carrito previo cancelled y permitir que el bot ofrezca retomar.
    "carrito", "retomar", "retomo", "antes", "ayer",
    "anterior", "ultima", "última", "ultimo", "último",
    "pendiente", "pendientes", "pagar", "pago",
})


def _customer_context_should_load(query_text: Optional[str]) -> bool:
    """Decide si cargar el bloque de contexto cliente conocido.

    Modos (CUSTOMER_CONTEXT_MODE env var, default 'lazy'):
    - 'always': siempre carga (rev. 68 default — mayor costo en tokens).
    - 'lazy': carga solo si la query del cliente contiene tokens de consulta
      sobre sus operaciones (pedido/reclamo/envío/etc.).
    - 'disabled': nunca carga (kill switch).

    El kill switch global CUSTOMER_CONTEXT_ENABLED (default 'true') anula
    el modo si está en 'false'.
    """
    if os.getenv("CUSTOMER_CONTEXT_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return False
    mode = (os.getenv("CUSTOMER_CONTEXT_MODE", "lazy") or "lazy").strip().lower()
    if mode == "disabled":
        return False
    if mode == "always":
        return True
    # Default: lazy — solo si la query menciona operaciones del cliente.
    if not query_text:
        return False
    # _tokenize_text extrae solo alfanuméricos sin acentos — robusto contra
    # signos de puntuación ("¿pedido?" → ["pedido"]).
    tokens = set(_tokenize_text(query_text))
    return bool(tokens & _CUSTOMER_CONTEXT_LAZY_TOKENS)


def _cart_recovery_enabled() -> bool:
    """F7-lite kill switch independiente del global CUSTOMER_CONTEXT_ENABLED.

    Permite apagar solo el bloque de carrito previo sin tumbar el contexto
    de pedidos activos / reclamos abiertos.
    """
    raw = os.getenv("CART_RECOVERY_ENABLED", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _cart_recovery_lookback_days() -> int:
    raw = os.getenv("CART_RECOVERY_LOOKBACK_DAYS", "7")
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return 7
    return max(1, min(v, 60))


def _fetch_recoverable_cart_items(
    supabase: Client, tenant_id: str, contact_id: str,
) -> list[dict]:
    """Rev. 103 — devuelve items recuperables del último cancelled order
    del cliente (filtrados por stock + precio actual válido). Used both
    by cart-recovery system prompt block AND by deterministic retake
    handler that persists items into conversation_cart_items.

    Cada item retornado tiene shape compatible con cart_tool.add_item:
      {variation_id, product_id, quantity, unit_price_cents, title}.

    Vacío si no hay cancelled order reciente o ningún item es válido.
    """
    if not _cart_recovery_enabled() or not contact_id:
        return []
    lookback_days = _cart_recovery_lookback_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    try:
        cart_res = (
            supabase.table("orders")
            .select("id, status, created_at, "
                    "order_items(title, unit_price, quantity, variation_id, product_id)")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .eq("status", "cancelled")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = cart_res.data or []
    except Exception as exc:
        logger.warning("[CART-REC] Error cargando cart cancelado: %s", exc)
        return []
    if not rows:
        return []
    items = (rows[0] or {}).get("order_items") or []
    if not items:
        return []
    variation_ids = [it.get("variation_id") for it in items if it.get("variation_id")]
    if not variation_ids:
        return []
    try:
        v_res = (
            supabase.table("product_variations")
            .select("id, stock_quantity, price")
            .eq("tenant_id", tenant_id)
            .in_("id", variation_ids)
            .execute()
        )
        variants_by_id = {row["id"]: row for row in (v_res.data or []) if row.get("id")}
    except Exception as exc:
        logger.warning("[CART-REC] Error re-validando variantes: %s", exc)
        return []
    out: list[dict] = []
    for it in items:
        vid = it.get("variation_id")
        pid = it.get("product_id")
        qty = int(it.get("quantity") or 0) or 1
        if not vid or not pid:
            continue
        v = variants_by_id.get(vid)
        if not v:
            continue
        if int(v.get("stock_quantity") or 0) < qty:
            continue
        cur_price = float(v.get("price") or 0)
        if cur_price <= 0:
            continue
        out.append({
            "variation_id": vid,
            "product_id": pid,
            "quantity": qty,
            "unit_price_cents": int(round(cur_price * 100)),
            "title": (it.get("title") or "").strip() or "Producto",
        })
    return out


def _last_outbound_offered_cart_retake(history: list[dict]) -> bool:
    """True si el último outbound del bot ofreció retomar el cart previo.
    Markers que aparecen cuando el LLM ofrece retake en distintas variantes
    fraseológicas. La detección debe ser AMPLIA porque el LLM compone con
    variabilidad — sin matcher, `_persist_recovered_cart_items` no dispara
    y el cart queda vacío → bot enuncia items via history-parsing pero
    add_item posterior los pierde (caso UAT runtime 2026-05-19 conv a4db1801).
    """
    markers = (
        # Variantes "carrito ..."
        "carrito reciente",
        "carrito anterior",
        "tu carrito anterior",
        "carrito previo",
        "tu carrito previo",
        # Sem 7 F2 cierre — variantes "carrito que se canceló/abandonó"
        # que el LLM usa cuando descubre cart histórico cancelled.
        "carrito que se cancel",
        "carrito que se cancelo",
        "carrito que cancel",
        "carrito que abandon",
        "un carrito que",
        # Variantes "retomar/retomamos"
        "¿lo retomamos",
        "lo retomamos o",
        "te gustaria retomarlo",
        "te gustaria retomar",
        "retomarlo o prefieres",
        "retomar o prefieres",
        "retomarlo o quieres",
        "lo retomamos",
        # Variantes "X items en tu carrito"
        "tenias x items",
        "tenias 1 items",
        "tenias 2 items",
        "tenias 3 items",
        "ítems en tu carrito",
        "items en tu carrito",
        # Variantes "tenías un [producto]" (caso single-item)
        "tenias un ",
        "tenias una ",
    )
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").strip().lower() == "outbound":
            content_norm = _normalize_text(str(msg.get("content") or ""))
            return any(m in content_norm for m in markers)
    return False


def _detect_cart_retake_acceptance(content: str) -> bool:
    """Rev. 103 — el cliente acepta retomar el cart previo. Solo dispara
    cuando el último outbound del bot ofreció el retake (caller verifica)."""
    if not content:
        return False
    norm = _normalize_text(content)
    tokens = set(norm.split())
    accept_phrases = (
        "retomemos", "retomamos", "retomar",
        "el anterior", "el mismo", "lo mismo",
        "sigamos con la compra", "sigamos con el pedido",
        "ese mismo", "esos mismos",
    )
    if any(p in norm for p in accept_phrases):
        return True
    # Frases cortas afirmativas tras la oferta también cuentan.
    short_yes = {"si", "sí", "dale", "claro", "listo", "ok", "vale", "perfecto", "siga"}
    if len(tokens) <= 4 and tokens & short_yes:
        return True
    return False


def _persist_recovered_cart_items(
    supabase: Client,
    *,
    tenant_id: str,
    conversation_id: str,
    contact_id: str,
    items: list[dict],
) -> bool:
    """Rev. 103 — Copia items recuperables al cart_items de la conversación
    actual. Idempotente: si el cart ya tiene items, no duplica.

    Razón: sin esto el bot menciona "tienes X items previos" pero el cart
    real está vacío → shipping_quote_tool cae a inventory disambiguation
    aunque ya conozca los productos. Cart-as-SoT roto.
    """
    if not items:
        return False
    try:
        from tools.cart_tool import ensure_cart, add_item, get_cart_with_items
    except Exception as exc:
        logger.warning("[CART-REC] cart_tool no disponible: %s", exc)
        return False
    try:
        existing = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
    except Exception:
        existing = None
    if existing and (existing.get("items") or []):
        # Cart ya tiene items en el flow actual — no sobreescribir.
        return False
    try:
        cart = ensure_cart(
            supabase, conversation_id=conversation_id,
            tenant_id=tenant_id, contact_id=contact_id,
        )
        cart_id = cart["id"]
        for it in items:
            add_item(
                supabase, cart_id=cart_id, tenant_id=tenant_id,
                product_id=it["product_id"], variation_id=it["variation_id"],
                quantity=int(it["quantity"]),
                unit_price_cents=int(it["unit_price_cents"]),
            )
        logger.info(
            "[CART-REC] Persistidos %d items recuperados a cart=%s conv=%s",
            len(items), cart_id[:8], conversation_id[:8],
        )
        return True
    except Exception as exc:
        logger.warning("[CART-REC] Error persistiendo items recuperados: %s", exc)
        return False


def _load_cart_recovery_block(
    supabase: Client, tenant_id: str, contact_id: str,
) -> str:
    """F7-lite: si el cliente tiene una orden 'cancelled' reciente, inyecta
    el carrito previo al system prompt con re-validación de stock y precio
    actual por variante.

    Salida: bloque vacío si no aplica o ningún item es válido. Si hay carrito,
    formato:

      CARRITO PREVIO (cancelado por timeout, hace 2 días):
      - 2x Camiseta Negra M (precio anterior $30.000, AHORA $35.000) — precio cambió
      - 1x Pantalón Beige 30 ($85.000) — disponible
      - 1x Gorra Roja — SIN STOCK
      Total recalculado al precio actual: $155.000.
      INSTRUCCIÓN: si el cliente quiere retomar, ofrece el total recalculado y
      advierte cambios. Si algo está SIN STOCK, ofrece reemplazar.

    NO crea orden nueva — eso lo hace el flujo normal del LLM con
    payment_link_tool una vez el cliente confirma.
    """
    if not _cart_recovery_enabled():
        return ""
    lookback_days = _cart_recovery_lookback_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    try:
        cart_res = (
            supabase.table("orders")
            .select("id, status, total_amount, created_at, order_items(title, unit_price, quantity, variation_id, product_id)")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .eq("status", "cancelled")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = cart_res.data or []
    except Exception as exc:
        logger.warning("[CART-REC] Error cargando carrito previo contact=%s: %s", contact_id, exc)
        return ""
    if not rows:
        return ""
    cart = rows[0] or {}
    items = cart.get("order_items") or []
    if not items:
        return ""

    # Re-validar stock y precio actual para cada item por variation_id.
    variation_ids = [it.get("variation_id") for it in items if it.get("variation_id")]
    variants_by_id: dict[str, dict] = {}
    if variation_ids:
        try:
            v_res = (
                supabase.table("product_variations")
                .select("id, stock_quantity, price")
                .eq("tenant_id", tenant_id)
                .in_("id", variation_ids)
                .execute()
            )
            variants_by_id = {row["id"]: row for row in (v_res.data or []) if row.get("id")}
        except Exception as exc:
            logger.warning("[CART-REC] Error re-validando variantes: %s", exc)
            variants_by_id = {}

    created_at_raw = str(cart.get("created_at") or "")
    days_ago: Optional[int] = None
    try:
        if created_at_raw:
            iso = created_at_raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            days_ago = max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        days_ago = None
    when = f"hace {days_ago} día{'s' if days_ago != 1 else ''}" if days_ago is not None else "reciente"

    item_lines: list[str] = []
    new_total = 0.0
    any_available = False
    for it in items:
        title = (it.get("title") or "").strip() or "Producto"
        qty = int(it.get("quantity") or 0) or 1
        prev_price = float(it.get("unit_price") or 0)
        variation_id = it.get("variation_id")
        v = variants_by_id.get(variation_id) if variation_id else None
        if v is None:
            # Sin variación o variación borrada → no recuperable.
            item_lines.append(f"- {qty}x {title} — NO DISPONIBLE (variante removida)")
            continue
        cur_stock = int(v.get("stock_quantity") or 0)
        cur_price = float(v.get("price") or 0)
        if cur_stock < qty:
            item_lines.append(f"- {qty}x {title} — SIN STOCK (disponibles: {cur_stock})")
            continue
        any_available = True
        new_total += cur_price * qty
        if abs(cur_price - prev_price) > 0.01:
            item_lines.append(
                f"- {qty}x {title} (precio anterior {_format_pesos(prev_price)}, AHORA {_format_pesos(cur_price)}) — precio cambió"
            )
        else:
            item_lines.append(f"- {qty}x {title} ({_format_pesos(cur_price)}) — disponible")

    if not any_available:
        # Todo el carrito es irrecuperable: no aporta valor inyectarlo, evita
        # ruido en el prompt. El cliente recibirá flujo normal de catálogo.
        return ""

    lines = ["", f"CARRITO PREVIO (cancelado por timeout, {when}):"]
    lines.extend(item_lines)
    lines.append(f"Total recalculado al precio actual: {_format_pesos(new_total)}.")
    lines.append(
        "INSTRUCCIÓN: si el cliente quiere retomar, ofrece el total recalculado "
        "y advierte si algún precio cambió. Si algo está SIN STOCK, ofrece "
        "reemplazarlo o armar el pedido con lo disponible. NO menciones el "
        "carrito previo si el cliente no expresa intención de comprar."
    )
    return "\n".join(lines)


def _load_customer_context_block(
    supabase: Client, tenant_id: str, contact_id: Optional[str], first_name: Optional[str],
    *, query_text: Optional[str] = None, conversation_id: Optional[str] = None,
    contact_record: Optional[dict] = None, history: Optional[list[dict]] = None,
) -> str:
    """Construye un bloque "CONTEXTO DEL CLIENTE" para el system prompt
    espejo del panel del Inbox del Tenant Console — para que el LLM tenga
    la VERDAD en tiempo real y no aluciñe.

    Rev. 103 — refactor a real-time mirror del Inbox panel:
      • Contacto: nombre, teléfono, email, doc, dirección, shipping_phone,
        consent (con bandera Habeas Data como en Inbox).
      • Carrito ACTIVO de la conversación actual (cart-as-SoT, items reales).
      • Pedidos recientes (mismo limit + status que Inbox).
      • Reclamos abiertos.
      • Carrito cancelado reciente (cart-recovery, opcional).

    Removed lazy loading (rev. 69): siempre se carga cuando hay contact_id
    + conversación viva. Razón directiva rev. 103: el LLM debe ver la
    realidad turn-by-turn — alucinaciones de productos/precios pasaban
    cuando el contexto no se cargaba en convs largas.
    """
    if not contact_id:
        return ""
    try:
        # Pedidos activos (no cancelados ni delivered).
        active_status = ("pending_payment", "confirmed", "processing", "shipped")
        orders_res = (
            supabase.table("orders")
            .select("id, status, total_amount, created_at")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .in_("status", active_status)
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        active_orders = orders_res.data or []
    except Exception as exc:
        logger.warning("[CTX] Error cargando orders contact=%s: %s", contact_id, exc)
        active_orders = []

    try:
        # NOTA: tabla `claims` usa `customer_id` como FK al contacto (no `contact_id`).
        claims_res = (
            supabase.table("claims")
            .select("id, ticket_number, status, created_at")
            .eq("tenant_id", tenant_id)
            .eq("customer_id", contact_id)
            .eq("status", "open")
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        open_claims = claims_res.data or []
    except Exception as exc:
        logger.warning("[CTX] Error cargando claims contact=%s: %s", contact_id, exc)
        open_claims = []

    cart_block = _load_cart_recovery_block(supabase, tenant_id, contact_id)

    # Rev. 103 — Carrito activo de la conversación actual (cart-as-SoT).
    # Espejo del panel "Contexto del cliente" del Inbox.
    active_cart_summary: Optional[dict] = None
    if conversation_id:
        try:
            from tools.cart_tool import get_cart_with_items as _get_cart_ctx
            _cart = _get_cart_ctx(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
            )
            if _cart and (_cart.get("items") or []):
                active_cart_summary = _cart
        except Exception as _ac_exc:
            logger.warning("[CTX] Error cargando carrito activo: %s", _ac_exc)

    # Construir contacto resumido (mirror Inbox)
    contact_lines: list[str] = []
    if isinstance(contact_record, dict):
        _name = (contact_record.get("name") or "").strip()
        _phone = (contact_record.get("phone") or "").strip()
        _email = (contact_record.get("email") or "").strip()
        _doc_t = (contact_record.get("document_type") or "").strip().upper()
        _doc_n = (contact_record.get("document_number") or "").strip()
        _ship = (contact_record.get("shipping_phone") or "").strip()
        _consent = bool(contact_record.get("consent_given"))
        _addr = contact_record.get("address") or {}
        if _name:
            contact_lines.append(f"- Nombre: {_name}")
        if _phone:
            contact_lines.append(f"- Celular WhatsApp: {_phone}")
        if _ship and _ship != _phone and _ship.replace("+", "") != _phone.replace("+", ""):
            contact_lines.append(f"- Celular envío (alterno): {_ship}")
        if _email:
            contact_lines.append(f"- Email: {_email}")
        if _doc_t and _doc_n:
            contact_lines.append(f"- Documento: {_doc_t} {_doc_n}")
        if isinstance(_addr, dict) and _addr:
            _addr_parts = [
                _addr.get("street"), _addr.get("complex_name"),
            ]
            if _addr.get("tower"):
                _addr_parts.append(f"Torre {_addr['tower']}")
            if _addr.get("apartment"):
                _addr_parts.append(f"Apto {_addr['apartment']}")
            if _addr.get("city"):
                _addr_parts.append(_addr["city"])
            _addr_str = " — ".join(p for p in _addr_parts if p)
            if _addr_str:
                contact_lines.append(f"- Dirección: {_addr_str}")
        # Bandera Habeas Data (mirror Inbox badges)
        if _consent:
            contact_lines.append("- Habeas Data: ✓ activo")
        elif contact_record.get("consent_revoked_at"):
            contact_lines.append("- Habeas Data: ✗ revocado")
        else:
            contact_lines.append("- Habeas Data: ✗ pendiente (cliente sin consent)")

    # Si nada para mostrar, no inyectar bloque vacío
    has_anything = bool(
        contact_lines or active_cart_summary or active_orders
        or open_claims or cart_block
    )
    if not has_anything:
        return ""

    lines: list[str] = ["", "CONTEXTO DEL CLIENTE (real-time desde DB — esta es la VERDAD; NO inventes ni cambies):"]

    if contact_lines:
        lines.append("")
        lines.append("👤 *Contacto*:")
        lines.extend(contact_lines)

    # Carrito ACTIVO de la conversación actual (cart-as-SoT)
    if active_cart_summary:
        lines.append("")
        lines.append("🛒 *Carrito actual* (en construcción):")
        _items = active_cart_summary.get("items") or []
        _subtotal_cents = int(active_cart_summary.get("subtotal_cents") or 0)
        for it in _items:
            qty = int(it.get("quantity") or 1)
            p = it.get("product") or {}
            v = it.get("variation") or {}
            ptitle = (p.get("title") or p.get("name") or "Producto").strip()
            vlabel = (v.get("label") or v.get("presentation") or "").strip()
            unit = int(it.get("unit_price_cents") or 0)
            line_total = unit * qty
            label = f"- {qty}x {ptitle}"
            if vlabel and vlabel.lower() not in {"estandar", "estándar"}:
                label += f" ({vlabel})"
            label += f": {_format_cop(line_total)}"
            lines.append(label)
        lines.append(f"- Subtotal: {_format_cop(_subtotal_cents)}")
        # Shipping en vivo desde history (último quote del bot)
        # Sem 6 I.2.7 — incluir descuento de cupón si está aplicado.
        _discount_cents = int(active_cart_summary.get("discount_cents") or 0)
        _coupon_code = active_cart_summary.get("coupon_code")
        if history:
            _ship_cents = _extract_shipping_cost_from_history(history) or 0
            _carrier_nm = _extract_shipping_carrier_from_history(history) or ""
            if _ship_cents > 0:
                _ship_label = f"Envío"
                if _carrier_nm:
                    _ship_label += f" (Económica · {_carrier_nm})"
                lines.append(f"- {_ship_label}: {_format_cop(_ship_cents)}")
                if _discount_cents > 0 and _coupon_code:
                    lines.append(
                        f"- Descuento: -{_format_cop(_discount_cents)} ({_coupon_code})"
                    )
                lines.append(
                    f"- Total con envío: "
                    f"{_format_cop(_subtotal_cents + _ship_cents - _discount_cents)}"
                )
        elif _discount_cents > 0 and _coupon_code:
            # Sin shipping aún — pero ya hay cupón aplicado.
            lines.append(
                f"- Descuento: -{_format_cop(_discount_cents)} ({_coupon_code})"
            )
            lines.append(
                f"- Total: {_format_cop(_subtotal_cents - _discount_cents)}"
            )

    if active_orders:
        lines.append("")
        lines.append("📦 *Pedidos recientes*:")
        for o in active_orders:
            short = (o.get("id") or "")[:8].upper()
            status = o.get("status", "?")
            total = o.get("total_amount") or 0
            lines.append(f"- Pedido #{short} | estado: {status} | total: {_format_pesos(total)}")

    if open_claims:
        lines.append("")
        lines.append("⚠️ *Reclamos abiertos*:")
        for c in open_claims:
            tn = c.get("ticket_number", "?")
            lines.append(f"- Reclamo #{tn} (sin resolver)")

    if cart_block:
        # Carrito previo cancelado (recovery) — separado del activo
        lines.append(cart_block)

    lines.append("")
    lines.append(
        "INSTRUCCIÓN CRÍTICA: este contexto es REALIDAD desde DB. NO inventes "
        "productos, precios, cantidades, ni datos del cliente. Si el cliente "
        "pide cambiar/agregar/quitar algo, hazlo SOBRE este estado real. Si "
        "el cliente NO pregunta por pedidos/reclamos, NO los menciones."
    )

    return "\n".join(lines)


def _fetch_contact_for_phone(
    supabase: Client,
    tenant_id: str,
    customer_phone_raw: Optional[str],
) -> tuple[Optional[str], dict]:
    if not customer_phone_raw:
        return None, {}

    phone_norm = re.sub(r"[\s+]", "", customer_phone_raw)
    if not phone_norm:
        return None, {}

    phone_plus = f"+{phone_norm}"
    phone_space = f"+57 {phone_norm[2:]}" if phone_norm.startswith("57") else phone_plus
    query = (
        supabase.table("contacts")
        .select("id, consent_given, name, email, address, document_type, document_number, phone, shipping_phone")
        .eq("tenant_id", tenant_id)
    )
    if hasattr(query, "or_"):
        query = query.or_(f"phone.eq.{phone_norm},phone.eq.{phone_plus},phone.eq.{phone_space}")
    else:
        query = query.eq("phone", phone_norm)
    c_res = query.order("name", nullsfirst=False).limit(1).execute()
    if not c_res.data:
        return None, {}
    record = c_res.data[0] or {}
    return record.get("id"), record

# Cliente global del nuevo SDK
_genai_client: Optional[genai.Client] = None

VARIANT_KEYWORDS = {
    "color",
    "colores",
    "talla",
    "tallas",
    "modelo",
    "version",
    "referencia",
    "sku",
}
SIZE_TOKENS = {"xs", "s", "m", "l", "xl", "xxl", "xxxl"}
QUERY_STOPWORDS = {
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "por", "para", "con", "sin", "que", "cuanto", "cuesta", "cuestan",
    "tienes", "tiene", "hay", "en", "del", "al", "me", "puedes", "podrias",
    "quisiera", "quiero", "disponible", "disponibles", "precio", "stock",
    "favor", "hola", "buenas", "buenos", "dias", "dia", "tarde", "noches",
    # Etiquetas de consulta: no deben forzar mismatch cuando el SKU sí coincide.
    "sku", "referencia", "referencias", "ref", "codigo",
}
def _get_genai_client() -> genai.Client:
    """Singleton lazy del cliente Gemini (nuevo SDK google-genai)."""
    global _genai_client
    if _genai_client is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no configurada")
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client


# ── Multimodal audio (D6 feature flag, lectura dinámica para apagable en caliente) ──
def _multimodal_audio_enabled() -> bool:
    raw = os.getenv("MULTIMODAL_AUDIO_ENABLED", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


async def _transcribe_audio_or_none(
    *,
    tenant_id: str,
    supabase,
    media_id: Optional[str],
    media_mime: Optional[str],
) -> Optional[str]:
    """Descarga audio de Meta y pide a Gemini transcribirlo.

    Retorna el texto transcrito (no vacío) o None si:
      - feature flag apagado
      - mime no soportado
      - falla descarga
      - falla transcripción Gemini
    En cualquier fallo, el caller debe caer al gate de no-texto humanizado.
    """
    if not _multimodal_audio_enabled():
        return None
    from services.meta_media import (
        fetch_media_bytes,
        is_supported_audio_mime,
        MediaDownloadError,
    )
    if not media_id:
        return None
    if not is_supported_audio_mime(media_mime):
        logger.info("[MULTIMODAL] mime no soportado: %s — fallback a gate texto", media_mime)
        return None
    # Reusa el access_token de WhatsApp del tenant (mismo que envía mensajes).
    try:
        from whatsapp_sender import _get_tenant_wa_credentials  # noqa: WPS433
        _, access_token = _get_tenant_wa_credentials(tenant_id, supabase)
    except Exception as exc:
        logger.warning("[MULTIMODAL] no se pudo resolver access_token tenant=%s: %s", tenant_id, exc)
        return None
    if not access_token:
        return None
    try:
        audio_bytes, mime_resolved = await fetch_media_bytes(media_id, access_token)
    except MediaDownloadError as exc:
        logger.info("[MULTIMODAL] descarga falló tenant=%s media_id=%s: %s", tenant_id, media_id, exc)
        return None
    # Llamada Gemini multimodal: transcribir el audio en español.
    try:
        client = _get_genai_client()
        audio_part = genai_types.Part(
            inline_data=genai_types.Blob(mime_type=mime_resolved or media_mime, data=audio_bytes)
        )
        prompt = (
            "Transcribe el siguiente audio en español. "
            "Si está en otro idioma, transcribe en el idioma original. "
            "Responde SOLO con el texto transcrito, sin comentarios ni meta-información."
        )
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, audio_part],
        )
        text = (getattr(resp, "text", "") or "").strip()
        if not text:
            logger.info("[MULTIMODAL] Gemini retornó transcripción vacía tenant=%s", tenant_id)
            return None
        logger.info(
            "[MULTIMODAL] audio procesado tenant=%s mime=%s bytes=%s transcripcion_chars=%s",
            tenant_id, mime_resolved or media_mime, len(audio_bytes), len(text),
        )
        return text
    except Exception as exc:
        logger.warning("[MULTIMODAL] Gemini transcripción falló tenant=%s: %s", tenant_id, exc, exc_info=True)
        return None


# ─── Schema de Output Estructurado ────────────────────────────────────────────

class OrchestratorOutput(BaseModel):
    """
    Output tipado de Gemini. El LLM NUNCA es fuente de verdad de stock/precios —
    solo puede referenciar datos inyectados en el contexto (catálogo del tenant).
    """
    should_respond: bool = Field(
        description="True si debes enviar el texto contenido de response_text al usuario. IMPORTANTE: En el Paso 4 (venta), DEBE ser True para enviar el resumen antes de escalar."
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
    extracted_name: Optional[str] = Field(
        default=None,
        description="El nombre del cliente si fue detectado en el historial (ej: 'Juan Pérez')"
    )
    extracted_direction: Optional[dict] = Field(
        default=None,
        description=(
            "Dirección estructurada con claves canónicas. Rev. 68 + Sem 7 F2 cierre: "
            "street, number, city, neighborhood, "
            "building_type (casa|edificio|conjunto|oficina), "
            "conjunto_type (torres|casas, solo si building_type=conjunto), "
            "tower (solo conjunto/torres), "
            "floor (piso, opcional para edificio/oficina), "
            "apartment (apartamento/casa#/oficina# según building_type), "
            "complex_name (nombre del edificio/conjunto residencial), "
            "company_name (nombre de la empresa, solo building_type=oficina), "
            "reference (punto de referencia genérico — NO uses para piso ni empresa). "
            "'additional_info' queda solo para residuos legacy."
        ),
    )
    extracted_email: Optional[str] = Field(
        default=None,
        description="Email del cliente si fue mencionado en la conversación."
    )
    # Rev. 68 — documento de identidad (Wompi customer_data.legal_id_type CO).
    extracted_document_type: Optional[str] = Field(
        default=None,
        description="Tipo de documento si fue mencionado: CC, CE, NIT, PP, TI, OTHER (mayúsculas)."
    )
    extracted_document_number: Optional[str] = Field(
        default=None,
        description="Número de documento sin puntos ni espacios. Para NIT puede incluir '-DV' al final."
    )
    # Rev. 103 — phone alternativo para envío (separado del WhatsApp).
    extracted_shipping_phone: Optional[str] = Field(
        default=None,
        description=(
            "Celular ALTERNATIVO para envío SOLO cuando el cliente menciona "
            "explícitamente que el pedido lo recibe OTRA persona o pide ACTUALIZAR "
            "el celular del envío. Solo dígitos (10 dígitos Colombia, sin +57). "
            "Ej: '3001234567'. Vacío si el cliente solo da su WhatsApp normal."
        )
    )
    total_in_cents: Optional[int] = Field(
        default=None,
        description="Total del pedido en centavos COP. Obligatorio cuando intent=order_acknowledgment."
    )
    shipping_cost_cents: Optional[int] = Field(
        default=None,
        description="Costo de envío del pedido en centavos COP, si aplica."
    )


# ─── Context Builder ──────────────────────────────────────────────────────────

async def _get_conversation_history(supabase: Client, tenant_id: str, conversation_id: str) -> list:
    """Retorna los últimos N mensajes de la conversación (contexto del chat)."""
    result = (
        supabase.table("messages")
        .select("direction, content, created_at")
        .eq("tenant_id", tenant_id)
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(CONVERSATION_HISTORY_LIMIT)
        .execute()
    )
    # Invertir para orden cronológico
    return list(reversed(result.data or []))


def _get_conversation_status(supabase: Client, tenant_id: str, conversation_id: str) -> str:
    """Lee el estado actual de la conversación para decidir si el bot puede responder."""
    conv_res = (
        supabase.table("conversations")
        .select("status")
        .eq("tenant_id", tenant_id)
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


_COMPLAINT_INTENTS: frozenset[str] = frozenset({
    "complaint", "reclamo", "devolucion", "garantia", "queja",
})


def _find_recent_claimable_order(
    supabase: Client, tenant_id: str, contact_id: str
) -> Optional[str]:
    """
    Retorna el order_id más reciente del contacto en estado post-venta
    (confirmed, processing, shipped, delivered) para asociarlo al claim.
    Retorna None si no hay orden elegible.
    """
    try:
        res = (
            supabase.table("orders")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .in_("status", ["confirmed", "processing", "shipped", "delivered"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        logger.warning("[CLAIMS] Error buscando orden para claim contact=%s: %s", contact_id, e)
        return None


def _create_claim(
    supabase: Client,
    *,
    tenant_id: str,
    order_id: str,
    contact_id: Optional[str],
    reason: str = "other",
) -> Optional[int]:
    """
    Inserta un claim en DB y retorna el ticket_number asignado por el trigger.
    Retorna None si falla el INSERT.
    """
    try:
        payload: dict = {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "status": "open",
            "reason": reason,
        }
        if contact_id:
            payload["customer_id"] = contact_id

        # tenant_filter:exempt:payload_includes_tenant_id
        res = supabase.table("claims").insert(payload).execute()
        inserted = (res.data or [{}])[0]
        ticket_number = inserted.get("ticket_number")
        logger.info(
            "[CLAIMS] Ticket #%s creado: order=%s tenant=%s",
            ticket_number, order_id, tenant_id,
        )
        return ticket_number
    except Exception as e:
        logger.warning("[CLAIMS] Error creando claim order=%s: %s", order_id, e)
        return None


def _is_conversation_window_expired(supabase: Client, tenant_id: str, conversation_id: str) -> bool:
    """
    Retorna True si la ventana de mensajería de 24h (CONVERSATION_WINDOW_HOURS) expiró.
    Fuera de esta ventana, WhatsApp solo permite mensajes de plantilla aprobados.
    Si no hay last_interaction_at, retorna False (no penalizar conversaciones nuevas).

    A6.2.7: tenant_id obligatorio — la conversación se lee filtrada por tenant
    para no leer last_interaction_at de otro tenant (aislamiento cross-tenant).
    """
    try:
        res = (
            supabase.table("conversations")
            .select("last_interaction_at")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        last_ts = (res.data or {}).get("last_interaction_at")
        if not last_ts:
            return False
        from datetime import datetime, timezone
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - last_dt
        return delta.total_seconds() > CONVERSATION_WINDOW_HOURS * 3600
    except Exception as e:
        logger.warning("[ORCH] Error verificando ventana conversación %s: %s", conversation_id, e)
        return False


_CANCEL_TOKENS: frozenset[str] = frozenset({
    "cancelar", "cancelar pedido", "cancelar compra", "reiniciar",
    "empezar de nuevo", "no quiero", "no quiero el pedido", "olvida el pedido",
})


def _cancel_pending_payment_order(supabase: Client, conversation_id: str, tenant_id: str) -> bool:
    """
    Cancela el pedido en pending_payment de esta conversación (si existe).
    Retorna True si se canceló algún pedido.
    El stock no estaba decrementado (solo se decrementa en APPROVED), no hay rollback de stock.
    """
    try:
        res = (
            supabase.table("orders")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("status", "pending_payment")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return False
        order_id = rows[0]["id"]
        supabase.table("orders").update({
            "status": "cancelled",
            "updated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }).eq("id", order_id).eq("tenant_id", tenant_id).execute()
        logger.info("[ORCH] Pedido cancelado por cliente: order=%s conv=%s", order_id, conversation_id)
        return True
    except Exception as e:
        logger.warning("[ORCH] Error cancelando pedido conv=%s: %s", conversation_id, e)
        return False


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


async def _send_outbound_text(
    supabase: Client,
    conversation_id: str,
    tenant_id: str,
    text: str,
) -> bool:
    text = _format_whatsapp_response_text(text)
    if not text or not text.strip():
        logger.warning(
            "[OUTBOUND] ghost_message_blocked conv=%s — texto vacío tras formato, no se envía",
            conversation_id,
        )
        return False

    # Rev. 104 (F1-5) — Invocación formal al OutputValidator. Reemplaza los
    # 2 bloques inline previos (BUG-5 resumen-before-link telemetry +
    # BUG-8 no-pii-pre-consent rewrite) con un único entrypoint estructurado
    # que devuelve un veredicto (`ok` / `rewrite` / `block`).
    try:
        from outbound.validator import OutputValidator, ValidationContext

        # Una sola query a `messages` para construir history compartido.
        # Sem 7 F2 cierre 2026-05-19 — Bug 3a founder UAT (conv 11c2dbde):
        # ANTES: `desc=False.limit(20)` tomaba los 20 más VIEJOS de la conv.
        # En conversaciones largas (45+ msgs) el resumen pre-link queda
        # fuera de la ventana → invariant `summary-before-link` dispara
        # falso positivo → Opción B ejecuta con contact incompleto →
        # texto acumulado caótico al cliente.
        # FIX: traer los 20 más RECIENTES (`desc=True`) y reordenar en
        # memoria como ascendente — los invariants esperan oldest-first
        # (`_is_first_outbound`, `last_outbound_was_summary` con lookback).
        recent = (
            supabase.table("messages")
            .select("direction, content")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        try:
            recent.data = list(reversed(recent.data or []))
        except Exception:
            pass  # data inmutable o nula — preservar tal cual
        # Lookup contact.consent_given. Rev. 104 (F1 fix): la tabla
        # `conversations` NO tiene columna `contact_id` — el lookup correcto
        # es vía `customer_phone` → `contacts.phone`. La query previa
        # (`conversations.contact_id`) devolvía HTTP 400 silenciado por el
        # try/except, dejando el invariant time-aware desactivado de facto.
        _conv_row = (
            supabase.table("conversations")
            .select("customer_phone")
            .eq("tenant_id", tenant_id)
            .eq("id", conversation_id)
            .limit(1)
            .execute()
        )
        _customer_phone = (
            (_conv_row.data or [{}])[0].get("customer_phone") or ""
        )
        _consent_given = False
        if _customer_phone:
            _phone_digits = _customer_phone.lstrip("+")
            _ctc = (
                supabase.table("contacts")
                .select("consent_given")
                .eq("tenant_id", tenant_id)
                .or_(f"phone.eq.{_phone_digits},phone.eq.+{_phone_digits}")
                .limit(1)
                .execute()
            )
            _consent_given = bool(
                (_ctc.data or [{}])[0].get("consent_given")
            )

        # SMELL-1: pasar saludo time-aware computado por hora local Colombia.
        # El validator solo aplica el rewrite si este valor está presente
        # y si el outbound es el primer mensaje (history sin outbounds previos).
        try:
            _server_greet, _ = _co_time_of_day_greeting()
        except Exception:
            _server_greet = None
        result = OutputValidator().validate(ValidationContext(
            candidate_text=text,
            history=recent.data or [],
            contact_consent_given=_consent_given,
            consent_question_template=CONSENT_QUESTION_TEMPLATE,
            server_time_greeting=_server_greet,
        ))
        for v in result.violations:
            logger.warning("[INVARIANT_VIOLATION] conv=%s %s", conversation_id, v)
        if result.rewrote and result.text:
            logger.info(
                "[OUTPUT_VALIDATOR] rewrite aplicado conv=%s",
                conversation_id,
            )
            text = result.text
        elif result.blocked:
            # Sem 7 F2 cierre (S12 UAT diagnosis) — fix Opción B:
            # cuando el invariant `summary-before-link` bloquea, en vez de
            # quedarnos mudos (loop silencioso si el bypass reintenta el
            # mismo flow), construimos el resumen desde cart-as-SoT y lo
            # PREFIJAMOS al outbound. Re-validamos: si pasa, enviamos el
            # outbound combinado (resumen + link en mismo mensaje).
            # Cumple ADR-0011 §A.10 sin dejar al cliente sin respuesta.
            _is_summary_block = (
                "summary-before-link" in (result.block_reason or "")
            )
            if _is_summary_block:
                # Sem 7 F2 cierre 2026-05-19 — Bug 3b founder UAT (conv 11c2dbde):
                # ANTES: contact_record={"phone": ...} solo, y se concatenaba
                # `_summary_text + text`. Si `text` venía del bypass payment_link
                # con "Perfecto! Tu pedido #X listo + link", quedaba duplicado:
                # 2 resúmenes + pregunta confirmación obsoleta + mensaje pedido.
                # FIX:
                #   1. Cargar contact COMPLETO (name, email, doc, address) por
                #      phone para que el resumen tenga todos los datos.
                #   2. Si `text` ya contiene "Pedido #XXXX" + Wompi link
                #      (formato canónico del bypass), REEMPLAZAR el outbound
                #      por uno determinístico limpio. NO concatenar.
                #   3. Si `text` es solo un link suelto del LLM (sin formato
                #      canónico), PREFIJAR resumen como antes.
                try:
                    from tools.cart_tool import (  # type: ignore
                        get_cart_with_items as _get_cart_with_items,
                    )
                    _cart_db = _get_cart_with_items(
                        supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                    )

                    # Cargar contact completo (no solo phone).
                    _contact_record = {"phone": _customer_phone}
                    if _customer_phone:
                        _phone_digits = _customer_phone.lstrip("+")
                        _full_contact = (
                            supabase.table("contacts")
                            .select(
                                "id, name, email, phone, shipping_phone, "
                                "document_type, document_number, address, "
                                "consent_given"
                            )
                            .eq("tenant_id", tenant_id)
                            .or_(
                                f"phone.eq.{_phone_digits},"
                                f"phone.eq.+{_phone_digits}"
                            )
                            .limit(1)
                            .execute()
                        )
                        _rows = _full_contact.data or []
                        if _rows:
                            _contact_record = _rows[0]

                    _summary_text = _build_order_summary_text(
                        contact_record=_contact_record,
                        verified_ctx=None,
                        history=recent.data or [],
                        cart_from_db=_cart_db,
                        supabase=supabase,
                        tenant_id=tenant_id,
                    )
                except Exception as _sum_exc:
                    logger.warning(
                        "[OUTPUT_VALIDATOR] fix Opción B: error armando "
                        "resumen conv=%s: %s",
                        conversation_id, _sum_exc,
                    )
                    _summary_text = None

                if _summary_text:
                    # Detectar si `text` viene del bypass payment_link
                    # (contiene "Pedido *#" formato canónico + Wompi link).
                    # Si sí → REPLACE limpio. Si no → PREFIX legacy.
                    import re as _re
                    _order_match = _re.search(
                        r"Pedido\s+\*?#([A-F0-9]{4,12})\*?", text or "",
                        flags=_re.IGNORECASE,
                    )
                    _link_match = _re.search(
                        r"https?://checkout\.wompi\.co/l/[A-Za-z0-9_-]+",
                        text or "",
                    )
                    _bypass_emit = bool(_order_match and _link_match)
                    if _bypass_emit:
                        # REPLACE: armar outbound determinístico limpio.
                        _short_id = _order_match.group(1)
                        _link_url = _link_match.group(0)
                        _first_name = ""
                        try:
                            _full_name = str(
                                _contact_record.get("name") or ""
                            ).strip()
                            _first_name = _full_name.split()[0] if _full_name else ""
                        except Exception:
                            pass
                        _greeting = (
                            f"Perfecto *{_first_name}*! "
                            if _first_name else "Perfecto! "
                        )
                        _combined = (
                            f"{_summary_text}\n\n"
                            f"{_greeting}Tu pedido *#{_short_id}* está listo.\n\n"
                            f"*Paga aquí:*\n{_link_url}\n\n"
                            f"> El link es válido por 30 minutos. Una vez "
                            f"confirmado el pago recibirás la confirmación por "
                            f"este chat."
                        )
                        logger.info(
                            "[OUTPUT_VALIDATOR] fix Opción B REPLACE aplicado "
                            "conv=%s order=#%s — bypass emit detectado",
                            conversation_id, _short_id,
                        )
                    else:
                        # PREFIX legacy: el texto del LLM no tiene formato
                        # canónico; prefijar resumen al final del LLM.
                        _combined = _summary_text + "\n\n" + text
                        logger.info(
                            "[OUTPUT_VALIDATOR] fix Opción B PREFIX aplicado "
                            "conv=%s — resumen prefijado al texto LLM",
                            conversation_id,
                        )

                    _revalidated = OutputValidator().validate(
                        ValidationContext(
                            candidate_text=_combined,
                            history=recent.data or [],
                            contact_consent_given=_consent_given,
                            consent_question_template=CONSENT_QUESTION_TEMPLATE,
                            server_time_greeting=None,
                        )
                    )
                    if not _revalidated.blocked:
                        text = (
                            _revalidated.text
                            if (_revalidated.rewrote and _revalidated.text)
                            else _combined
                        )
                    else:
                        logger.error(
                            "[OUTPUT_VALIDATOR] outbound BLOQUEADO conv=%s "
                            "reason=%s (fix Opción B re-validó pero sigue "
                            "bloqueado: %s)",
                            conversation_id, result.block_reason,
                            _revalidated.block_reason,
                        )
                        return False
                else:
                    logger.error(
                        "[OUTPUT_VALIDATOR] outbound BLOQUEADO conv=%s "
                        "reason=%s (fix Opción B: cart-as-SoT no provee "
                        "resumen — verified_ctx None)",
                        conversation_id, result.block_reason,
                    )
                    return False
            else:
                logger.error(
                    "[OUTPUT_VALIDATOR] outbound BLOQUEADO conv=%s reason=%s",
                    conversation_id, result.block_reason,
                )
                return False  # NO enviar
    except Exception as _inv_exc:
        logger.debug("[OUTPUT_VALIDATOR] falló (no-bloqueante): %s", _inv_exc)

    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("tenant_id", tenant_id)
        .eq("id", conversation_id)
        .execute()
    )
    customer_phone = conv_res.data[0]["customer_phone"] if conv_res.data else None
    if not customer_phone:
        logger.error("[OUTBOUND] No customer_phone for conversation_id=%s", conversation_id)
        return False

    # Rev. 103 — defensa final: si el outbound es resumen del pedido y
    # contiene "Celular: null/None", reemplazar con customer_phone real.
    # Cubre el caso donde el LLM compone el resumen viendo phone:null en
    # el contexto JSON (no pasa por el override determinístico).
    text = _fix_null_phone_in_summary(text, customer_phone)

    meta_message_id = await send_whatsapp_message(
        tenant_id=tenant_id,
        supabase=supabase,
        to_phone=customer_phone,
        text=text,
    )

    if meta_message_id:
        # Envío directo exitoso
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "text",
            "content": text,
            "meta_message_id": meta_message_id,
            "processed": True,
            "processing_status": PROCESSING_STATUS_PROCESSED,
        }).execute()
        logger.info("[OUTBOUND] Respuesta enviada directamente a %s", customer_phone)
        # Rev. 104 (F1-6) — hook único: si el texto enviado es resumen
        # determinístico (marker `📋`), emitir `summary_rendered` en
        # cart_events para auditoría. Best-effort.
        if "📋" in text:
            _emit_summary_rendered_event(
                supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                summary_text=text,
            )
        return True

    # Fallo en envío directo — insertar en DB y encolar para retry del worker
    logger.warning(
        "[OUTBOUND] send_whatsapp_message falló para conv=%s. Encolando para reintento.",
        conversation_id,
    )
    try:
        from uuid import uuid4
        from datetime import datetime, timezone as _tz
        msg_res = supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "text",
            "content": text,
            "processed": False,
            "processing_status": PROCESSING_STATUS_PENDING,
        }).execute()
        if msg_res.data:
            new_msg_id = msg_res.data[0]["id"]
            supabase.rpc(
                "enqueue_whatsapp_outbound_message",
                {"p_message": {
                    "event_type": "whatsapp.outbound.send",
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "message_id": new_msg_id,
                    "customer_phone": customer_phone,
                    "text": text,
                    "client_message_id": str(uuid4()),
                    "queued_at": datetime.now(_tz.utc).isoformat(),
                }, "p_delay": 5},
            ).execute()
            logger.info("[OUTBOUND] Mensaje encolado para reintento: msg_id=%s", new_msg_id)
    except Exception as enqueue_exc:
        logger.error("[OUTBOUND] No se pudo encolar para reintento: %s", enqueue_exc)
    return False


async def _get_tenant_ai_agent(supabase: Client, tenant_id: str) -> dict:
    """Extrae las reglas del Agente IA parametrizado por el tenant."""
    res = supabase.table("ai_agents").select("*").eq("tenant_id", tenant_id).execute()
    if res.data:
        return res.data[0]
    # Default agent si no ha configurado uno — alineado con DB default de
    # ai_agents.name ('Vendedor Oficial', migración 20260412000000) para que
    # el readiness check detecte coherentemente "no personalizado" en cualquier path.
    return {
        "name": "Vendedor Oficial",
        "role_description": "Eres un asistente de ventas cordial básico.",
        "strict_guardrails": True,
    }


from text_utils import normalize_text as _normalize_text, tokenize_text as _tokenize_text  # noqa: E402


_NON_TEXT_WARNING_MARKER = "solo puedo atender mensajes de texto"


def _had_non_text_warning(history: list[dict]) -> bool:
    """Retorna True si ya se envió una advertencia de no-texto en esta conversación."""
    for msg in history or []:
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        if _NON_TEXT_WARNING_MARKER in str(msg.get("content") or "").lower():
            return True
    return False


def _is_variant_query(query_text: str) -> bool:
    normalized = _normalize_text(query_text)
    tokens = set(_tokenize_text(query_text))
    if tokens & VARIANT_KEYWORDS:
        return True
    if tokens & SIZE_TOKENS:
        return True
    # SKU suele venir con patrón alfanumérico-guiones.
    if "sku" in normalized:
        return True
    # Follow-ups cortos típicos de contexto ("y en azul?", "en talla m?").
    if (normalized.startswith("y ") or normalized.startswith("en ")) and len(tokens) <= 5:
        return True
    return False


def _extract_query_specific_tokens(query_text: str) -> set[str]:
    tokens = set()
    for token in _tokenize_text(query_text):
        if token in QUERY_STOPWORDS:
            continue
        if len(token) == 1 and token not in SIZE_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _product_title_tokens(title: str) -> set[str]:
    return {
        token
        for token in _tokenize_text(title)
        if token not in QUERY_STOPWORDS and len(token) > 1
    }


def _find_context_product_from_history(catalog: list, history: list[dict]) -> Optional[dict]:
    # R-13: Buscar snapshot persistido primero (guardado cuando el cliente confirmó carrier).
    # El snapshot tiene content_type='context_snapshot' y payload con product_id real de DB.
    for msg in reversed(history or []):
        if msg.get("content_type") == "context_snapshot":
            payload = msg.get("payload") or {}
            snapped_id = str(payload.get("product_id") or "")
            if snapped_id:
                for p in catalog:
                    if str(p.get("id") or "") == snapped_id:
                        return p
            break  # Solo el snapshot más reciente; si no encontró en catálogo, cae a texto

    if not history:
        return None

    best_score = 0
    best_product = None
    for product in catalog:
        title = str(product.get("title", ""))
        title_tokens = _product_title_tokens(title)
        if not title_tokens:
            continue

        normalized_title = _normalize_text(title)
        product_score = 0
        for msg in reversed(history):
            content = str(msg.get("content", ""))
            if not content:
                continue
            normalized_content = _normalize_text(content)
            content_tokens = set(_tokenize_text(content))
            overlap = len(title_tokens & content_tokens)
            if overlap > product_score:
                product_score = overlap
            if normalized_title and normalized_title in normalized_content:
                product_score = max(product_score, len(title_tokens) + 1)
                break

        if product_score > best_score:
            best_score = product_score
            best_product = product

    if best_score <= 0:
        return None
    return best_product


_CORRECTION_FIELD_TOKENS: dict[str, frozenset[str]] = {
    "email": frozenset({"email", "correo", "mail", "correo electronico"}),
    "name":  frozenset({"nombre", "nombres", "apellido", "apellidos"}),
    "document": frozenset({
        "documento", "cedula", "cédula", "nit", "pasaporte", "ti", "cc", "ce",
    }),
    "address": frozenset({
        "direccion", "domicilio", "calle", "barrio", "apartamento",
        "apto", "torre", "conjunto", "edificio",
    }),
}
_CORRECTION_SIGNAL_TOKENS: frozenset[str] = frozenset({
    "mal", "malo", "mala", "incorrecto", "incorrecta", "equivocado",
    "equivocada", "cambiar", "cambio", "cambia", "error", "corregir",
    "corrige", "diferente", "otro", "otra", "no es", "no era",
})


def _detect_correction_intent(text: str) -> Optional[str]:
    """
    Detecta si el cliente quiere corregir un dato en el resumen (READY_FOR_SUMMARY).
    Retorna: 'email', 'name', 'address', o None si no hay intento de corrección.
    """
    normalized = _normalize_text(text)
    tokens = set(normalized.split())
    has_signal = bool(tokens & _CORRECTION_SIGNAL_TOKENS)
    if not has_signal:
        return None
    for field, field_tokens in _CORRECTION_FIELD_TOKENS.items():
        if tokens & field_tokens:
            return field
    return None


def _clear_contact_field(
    supabase: Client,
    contact_id: str,
    tenant_id: str,
    field: str,
) -> None:
    """Limpia un campo del contacto en DB para que el FSM lo vuelva a recolectar.

    Rev. 68 — 'document' limpia document_type Y document_number a la vez
    (van como par en Wompi, no tiene sentido limpiar uno solo).
    """
    if field == "document":
        null_value: dict = {"document_type": None, "document_number": None}
    else:
        null_value = {field: None}
    supabase.table("contacts").update(null_value).eq("id", contact_id).eq(
        "tenant_id", tenant_id
    ).execute()
    logger.info("[CORR] Campo '%s' limpiado para recolección | contact=%s", field, contact_id)


_CORRECTION_PROMPT: dict[str, str] = {
    "email":    "Entendido 👍 ¿Cuál es tu correo electrónico correcto?",
    "name":     "Entendido 👍 ¿Cuál es tu nombre completo correcto?",
    "document": "Entendido 👍 ¿Cuál es tu tipo (CC/CE/NIT/PP/TI) y número de documento correctos?",
    "address":  "Entendido 👍 Dame tu dirección correcta, por favor.",
}


# ── Cart-as-SoT — variant confirmation detector (rev. 103) ────────────────
# Razón arquitectónica: el carrito (`conversation_cart_items`) DEBE ser la
# fuente de verdad del pedido. Antes de rev. 103, el cart se inferia tarde
# (en READY_FOR_SUMMARY, vía `populate-on-demand`) leyendo del history. En
# conversaciones largas el history truncado a 25 mensajes perdía la mención
# del producto/variante elegido → el LLM componía resumen con producto
# alucinado del catálogo (caso real conv 32e0397e: cliente pidió Coco 60g,
# orden quedó con "Aceite Esencial de Árbol de Té $32.000").
#
# Solución: detector pre-LLM determinístico que persiste al cart EN EL
# MOMENTO en que el cliente confirma la variante, no al final del flujo.
# Después, todo el resto del sistema (cotización, resumen, payment_link,
# Inbox del Tenant Console) lee del cart real — alucinación imposible.

_PRESENTATION_MARKERS = (
    "lo tenemos en", "tenemos las siguientes", "presentaciones",
    "presentacion", "tamanos disponibles", "tamaños disponibles",
    "estos tamanos", "estos tamaños", "viene en", "disponible en",
    "estas presentaciones", "te puedo ofrecer",
)

_VARIANT_QTY_RE = re.compile(
    r"^\s*(?:quiero\s+|dame\s+|el\s+|la\s+|los\s+|las\s+|me\s+das\s+|"
    r"agreg(?:a|ame)\s+|añad(?:e|eme)\s+|sumame\s+|llevo\s+)?"
    r"(\d{1,3})\s*(?:unidades?|uds?\.?|cantidad)?",
    re.IGNORECASE,
)


def _last_outbound_presented_variants_all(
    catalog: list, history: list[dict],
) -> list[dict]:
    """Rev. 104 (Bug-C runtime) — devuelve TODOS los productos cuyas
    variantes fueron presentadas en el último outbound del bot.

    Mejora sobre la versión singular: cuando el bot lista variantes de
    múltiples productos en un solo outbound (ej. "Coco: 60g/100g/150g.
    Sérum: 15ml/30ml"), debemos considerar AMBOS como candidatos para
    resolver el variant que el cliente elija a continuación. El caller
    itera hasta encontrar un match.

    Match plural-tolerante: usa los tokens discriminativos del título
    (no substring exacto). "Jabones Artesanales de Coco" matchea el
    producto "Jabón Artesanal de Coco" porque comparten {coco, jabon,
    artesanal} (los plurales se resuelven por prefijo de 4-5 chars).

    Retorna `[]` si:
      • No hay outbound previo
      • El outbound no muestra signos de listado de variantes (sin marker
        ni bullets numéricos suficientes)
      • Ningún producto del catálogo matchea por discriminativos
    """
    if not catalog or not history:
        return []
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        if not content:
            return []
        content_norm = _normalize_text(content)
        has_marker = any(m in content_norm for m in _PRESENTATION_MARKERS)
        bullet_attrs = re.findall(
            r"[\*•\-]\s*(\d+)\s*(?:g|gr|gramos|ml|cc|mililitros|kg|oz)\b",
            content_norm,
            re.IGNORECASE,
        )
        if not (has_marker or len(bullet_attrs) >= 2):
            return []
        content_tokens = set(re.findall(r"[a-z0-9ñ]+", content_norm))
        results: list[dict] = []
        _stop = {"de", "con", "y", "o", "la", "el", "los", "las",
                 "un", "una", "para", "por"}
        for prod in catalog:
            title = str(prod.get("title") or "").strip()
            if not title:
                continue
            title_norm = _normalize_text(title)
            title_tokens = (
                set(re.findall(r"[a-z0-9ñ]+", title_norm)) - _stop
            )
            if not title_tokens:
                continue
            # Match laxo plural-tolerante: cada token discriminativo del
            # título debe aparecer en el contenido EXACTO o como prefijo
            # ≥4 chars de algún token del contenido.
            def _match_token(tw: str) -> bool:
                if tw in content_tokens:
                    return True
                if len(tw) < 4:
                    return False
                # Prefijo: el token del contenido empieza con el del título
                # (cubre "jabones" matchea "jabon").
                return any(
                    ct.startswith(tw[:4]) and len(ct) >= 4
                    for ct in content_tokens
                )

            if all(_match_token(tw) for tw in title_tokens):
                results.append(prod)
        return results
    return []


def _last_outbound_presented_variants(
    catalog: list, history: list[dict],
) -> Optional[dict]:
    """Wrapper singular para back-compat: retorna el primer producto
    cuyas variantes fueron presentadas, o None.

    Para flujos multi-producto usar `_last_outbound_presented_variants_all`.
    """
    products = _last_outbound_presented_variants_all(catalog, history)
    return products[0] if products else None


_QTY_STOPWORDS: frozenset[str] = frozenset({
    "de", "con", "y", "o", "la", "el", "los", "las", "un", "una",
    "para", "por", "que", "del", "al",
})

_QTY_UNIT_TOKENS: frozenset[str] = frozenset({
    "g", "gr", "gramos", "ml", "cc", "kg", "oz", "mililitros",
})


def _extract_qty_for_product(
    content_norm: str,
    product: dict,
    *,
    generic_terms: Optional[set[str]] = None,
) -> int:
    """Devuelve la cantidad declarada para `product` en el inbound, o 1.

    Atribución *product-local*: solo cuenta dígitos que estén dentro de
    una ventana de ±3 tokens respecto a una palabra discriminativa del
    título del producto (o su variante plural). Evita el caso típico de
    cross-attribution en inbounds multi-producto: "quiero 2 jabones de
    coco y 1 sérum" — el "2" es de coco, el "1" es de sérum, NUNCA al
    revés.

    Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv febcec09):
    inbound "1 Jabón Coco y 2 Lavanda" producía qty=2 para Coco porque:
      a) La ventana ±3 tokens desde "coco" alcanzaba al "2" de Lavanda.
      b) "jabon" + "artesanal" se trataban como discriminativos de cada
         producto aunque son palabras GENÉRICAS entre jabones.
    Fix doble:
      1. SEGMENTAR el inbound por separators ("y", ",", "+", ";") y
         evaluar la ventana SOLO dentro del segmento del producto.
      2. Aceptar `generic_terms` opcional del catálogo y RESTARLO de
         las palabras discriminativas (igual lógica que
         `_detect_explicit_products_in_inbound`).

    Reglas:
      • Segmentar por " y "/", "/"; "/"+ ".
      • Tokens del título − stop-words − generic_terms = `discriminative`.
      • Match laxo: token del inbound coincide con discriminative si son
        iguales OR comparten prefijo de ≥4 chars (cubre plurales).
      • Para cada segmento que contenga discriminativo del producto,
        busca dígitos 1-2 cifras dentro de ESE segmento. Excluye dígitos
        cuyo siguiente token es unidad (g/ml/etc.).
      • Devuelve el MÁXIMO encontrado entre segmentos. Default 1.
    """
    if not content_norm or not product:
        return 1
    title_norm = _normalize_text(str(product.get("title") or ""))
    title_words = (
        set(re.findall(r"[a-z0-9ñ]+", title_norm)) - _QTY_STOPWORDS
    )
    # Restar palabras genéricas del catálogo (e.g. "jabon"/"artesanal"
    # compartidas por todos los jabones). Sin esto, el caller que llame
    # con producto Coco para inbound "2 lavanda" obtendría qty=2 porque
    # "jabon"/"artesanal" matchearían en el segmento "2 jabon artesanal
    # de lavanda" como discriminativos espurios de Coco.
    if generic_terms:
        title_words = title_words - generic_terms
    if not title_words:
        return 1

    def _is_discriminative(tok: str) -> bool:
        if tok in title_words:
            return True
        # Match por prefijo (cubre plurales): el token comparte ≥4 chars
        # iniciales con alguna palabra del título de longitud ≥4.
        for tw in title_words:
            if len(tw) >= 4 and len(tok) >= 4 and tok.startswith(tw[:4]):
                return True
            if len(tw) >= 4 and len(tok) >= 4 and tw.startswith(tok[:4]):
                return True
        return False

    def _scan_qty_in_tokens(tokens_list: list[str], require_discriminative: bool) -> int:
        """Escanea una lista de tokens y retorna el MAX qty (≥2) detectado.
        Si `require_discriminative=True` el segmento DEBE contener un
        discriminativo del producto; cualquier dígito ≥2 no-unidad del
        segmento cuenta (la segmentación ya garantizó localización al
        producto)."""
        local_qty = 1
        if require_discriminative and not any(_is_discriminative(t) for t in tokens_list):
            return local_qty
        # Escanear todo el segmento (no ventana ±3) — segmentación previa
        # ya garantiza que este segmento corresponde a UN solo producto.
        # Ventana ±3 era anti-cross-attribution; ahora la segmentación
        # cumple esa función con mejor precisión.
        for j, w in enumerate(tokens_list):
            if not re.fullmatch(r"\d{1,2}", w):
                continue
            if j + 1 < len(tokens_list) and tokens_list[j + 1] in _QTY_UNIT_TOKENS:
                continue
            try:
                v = int(w)
                if 2 <= v <= 99:
                    local_qty = max(local_qty, v)
            except ValueError:
                continue
        return local_qty

    # Sem 7 F2 cierre 2026-05-21 — segmentar primero por separators.
    # Caso runtime: "1 jabon coco y 2 lavanda" → ["1 jabon coco", "2 lavanda"].
    # Cada segmento se evalúa de forma aislada → qty no se contagia entre
    # productos. Tipos de separators reconocidos: " y ", ", ", " + ", "; ".
    segments_raw: list[str] = []
    # Aplicar split secuencial: si el inbound tiene varios separators,
    # iterativamente cada split divide segmentos resultantes.
    _segments_tmp: list[str] = [content_norm]
    for sep in [" y ", ", ", " + ", "; "]:
        _next: list[str] = []
        for seg in _segments_tmp:
            if sep in seg:
                _next.extend(s.strip() for s in seg.split(sep) if s.strip())
            else:
                _next.append(seg)
        _segments_tmp = _next
    segments_raw = _segments_tmp or [content_norm]

    qty = 1
    # Si hay discriminativo en cualquier segmento, aplicar atribución
    # product-local POR SEGMENTO (cada segmento evalúa qty solo si tiene
    # discriminativo del producto). Si NINGÚN segmento tiene
    # discriminativo:
    #   • Caller pasó `generic_terms` (identificando productos en
    #     contexto multi-producto) → qty=1 default. NO usar Camino A
    #     porque significaría inventar qty para un producto NO mencionado.
    #   • Caller NO pasó `generic_terms` (contexto producto único, ej.
    #     bot recién presentó variantes) → Camino A: cualquier dígito
    #     no-unidad del inbound puede ser qty.
    all_tokens = re.findall(r"[a-z0-9ñ]+", content_norm)
    if not all_tokens:
        return 1
    has_any_discriminative = any(_is_discriminative(t) for t in all_tokens)
    if has_any_discriminative:
        for seg in segments_raw:
            seg_tokens = re.findall(r"[a-z0-9ñ]+", seg)
            if not seg_tokens:
                continue
            seg_qty = _scan_qty_in_tokens(seg_tokens, require_discriminative=True)
            qty = max(qty, seg_qty)
    elif generic_terms is None:
        # Camino A: contexto producto fijado por presentación previa,
        # cliente solo da "2 unidades de 60g" sin nombre.
        qty = _scan_qty_in_tokens(all_tokens, require_discriminative=False)
    # else: generic_terms provisto + no discriminativo → qty=1 default
    # (defensa contra cross-attribution en contexto multi-producto).
    return qty


def _resolve_variant_from_inbound(
    inbound_text: str, product: dict,
    *,
    require_discriminative_per_segment: bool = False,
) -> list[tuple[dict, int]]:
    """Match el inbound del cliente a una o más variantes del producto.

    Sem 7 F2 cierre: cambio de contrato — retorna `list[tuple[variant, qty]]`
    (puede ser vacía, 1 elemento, o N) en lugar de tupla única.

    Caso runtime motivador (UAT 2026-05-19): cliente dice "1 de 100ml y 1
    de 250ml" para Aceite de Almendras. El contrato anterior (1 inbound →
    1 variant) tomaba solo "100ml" y descartaba "250ml". El cliente perdía
    el segundo item.

    Estrategia (por cada match encontrado, agregar a la lista):
      1. Match por value de attributes (ej. "60g" matches attribute valor "60g").
      2. Match por sustring numérico + unidad (ej. "60 gramos" matches "60g").
      3. Match por label completo de la variant.

    Si el inbound contiene separator (" y ", " + "), procesa segmentos
    independientes para asignar qty correcta a cada variante.

    Default: si producto tiene 1 sola variante y no resolvió arriba, asume
    esa variante (rev. 104 F1-8 BUG-7).

    Sem 7 F2 cierre 2026-05-19 — Bug 2 founder UAT:
    `require_discriminative_per_segment` (default False, opt-in): cuando True
    Y hay multi-segments, exige que cada segmento contenga al menos una
    palabra discriminativa del título del producto. Usado por el caller
    tier-2 cuando hay múltiples productos potenciales en juego (caso
    "1 de Coco 100g y 1 de Lavanda 150g" — el segmento "1 de Lavanda 150g"
    NO debe matchearse contra Jabón Coco solo porque "150g" esté en sus
    variantes). El caller que conoce el contexto "un solo producto" (ej.
    `_detect_variant_confirmation` cuando el bot acaba de presentar UN
    producto) deja este flag en False para mantener back-compat.

    Sem 7 F2 cierre 2026-05-21 — la disambiguación CROSS-PRODUCT (caso
    "3 sérums presentados, cliente dice 'Sérum Vitamina C 30ml'") NO vive
    aquí — está en `_detect_variant_confirmation` que aplica la lógica
    post-resolución basada en si la variante matched es ambigua (label
    compartido entre productos del set).
    """
    if not inbound_text or not product:
        return []
    norm = _normalize_text(inbound_text)
    variants = product.get("variants") or []
    if not variants:
        return []

    # Detectar separadores que indican multi-variant intent.
    # "1 de 100ml y 1 de 250ml" → segments=["1 de 100ml", "1 de 250ml"]
    segments: list[str] = []
    if any(sep in norm for sep in (" y ", " + ", ", ", "tambien", "ademas")):
        # Split por separators conocidos.
        for sep in [" y ", " + ", "; "]:
            if sep in norm:
                segments = [s.strip() for s in norm.split(sep) if s.strip()]
                break
        if not segments:
            segments = [norm]
    else:
        segments = [norm]

    # Sem 7 F2 cierre 2026-05-19 — Bug 2 founder UAT:
    # OPT-IN (require_discriminative_per_segment=True): cuando hay multi-segments
    # Y el caller indica que hay múltiples productos potenciales en juego,
    # calculamos las palabras DISCRIMINATIVAS del título y exigimos que cada
    # segmento contenga al menos una. Sin esto: inbound "1 de Coco 100g y 1
    # de Lavanda 150g" matcheaba la variante 150g a Jabón Coco falsamente.
    # Cuando el caller sabe "este detector es para UN producto" (post-pregunta
    # de variantes), deja el flag en False y se preserva la semántica original.
    discriminative_words: set[str] = set()
    if require_discriminative_per_segment and len(segments) > 1:
        title_norm = _normalize_text(str(product.get("title") or ""))
        title_words = set(re.findall(r"[a-z0-9ñ]+", title_norm))
        _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}
        title_words -= _stop
        # Palabras del título ≥4 chars (heurística: descarta stop-words y
        # conectores como "de"/"con"; preserva sustantivos del título tipo
        # "coco", "lavanda", "jabon", "artesanal", "almendras"). Adjetivos
        # genéricos compartidos por todo el catálogo (ej. "artesanal") son
        # filtrados naturalmente por el caller que aplica category-lock.
        discriminative_words = {w for w in title_words if len(w) >= 4}

    # Si solo 1 segment, procesarlo igual que antes (1 variante o default).
    # Si N segments, procesar cada uno por separado y juntar matches únicos.
    results: list[tuple[dict, int]] = []
    seen_variation_ids: set[str] = set()

    for segment in segments:
        # Sem 7 F2 cierre — Bug 2 (OPT-IN): en multi-segment con
        # require_discriminative_per_segment, exigir match discriminative
        # para evitar atribución cruzada de variantes.
        if discriminative_words:
            seg_tokens = set(re.findall(r"[a-z0-9ñ]+", segment))
            if not (seg_tokens & discriminative_words):
                # Este segmento NO menciona el producto actual — skip.
                continue

        # Por segmento, intentar resolver una variante.
        segment_qty = _extract_qty_for_product(segment, product) if len(segments) == 1 else _extract_qty_from_segment(segment)
        segment_variant = _match_single_variant_in_text(segment, variants)
        if segment_variant:
            variation_id = str(segment_variant.get("id") or "")
            if variation_id and variation_id not in seen_variation_ids:
                results.append((segment_variant, segment_qty))
                seen_variation_ids.add(variation_id)

    # Default: si no resolvió ninguna variante Y producto tiene 1 sola, asumir.
    # Solo cuando había 1 segment (no multi-variant input ambiguo).
    if not results and len(segments) == 1 and len(variants) == 1:
        qty = _extract_qty_for_product(norm, product)
        results.append((variants[0], qty))

    return results


def _extract_qty_from_segment(segment: str) -> int:
    """Sem 7 F2 cierre — extract qty from a multi-variant segment.

    Para "1 de 100ml" → qty=1. Para "2 de 250ml" → qty=2.
    Si no hay qty explícita, default 1.
    """
    if not segment:
        return 1
    # Primer dígito SIN unidad seguida (60g, 30ml son atributos, no qty).
    m = re.search(r"\b(\d+)\s*(?!\s*(?:g|gr|gramos|ml|mililitros|cc|kg|oz)\b)\d*", segment, re.IGNORECASE)
    if not m:
        # Patrón más simple: cualquier número que NO esté seguido de unidad.
        nums = re.findall(r"\b(\d+)\b", segment)
        if not nums:
            return 1
        # Tomar el primer número que NO esté seguido inmediatamente por unidad.
        for num in nums:
            # Check si está seguido de unidad en el segment.
            num_unit_pattern = rf"\b{num}\s*(g|gr|gramos|ml|mililitros|cc|kg|oz)\b"
            if not re.search(num_unit_pattern, segment, re.IGNORECASE):
                try:
                    return max(1, min(100, int(num)))
                except ValueError:
                    continue
        return 1
    try:
        return max(1, min(100, int(m.group(1))))
    except (ValueError, IndexError):
        return 1


def _match_single_variant_in_text(text: str, variants: list) -> Optional[dict]:
    """Helper de `_resolve_variant_from_inbound`: matchea UNA variante
    contra un trozo de texto (segment) usando las 3 estrategias estándar.

    Returns: variant dict o None.
    """
    if not text or not variants:
        return None
    norm = _normalize_text(text)

    # 1. Match por attribute value (más confiable).
    for v in variants:
        attrs = v.get("attributes") or {}
        if not isinstance(attrs, dict):
            continue
        for av in attrs.values():
            av_n = _normalize_text(str(av or "")).strip()
            if av_n and av_n in norm and len(av_n) >= 2:
                return v

    # 2. Match por número + unidad.
    num_unit = re.search(
        r"(\d{1,4})\s*(g|gr|gramos|ml|mililitros|cc|kg|oz)\b",
        norm, re.IGNORECASE,
    )
    if num_unit:
        target_num = num_unit.group(1)
        for v in variants:
            attrs = v.get("attributes") or {}
            if not isinstance(attrs, dict):
                continue
            for av in attrs.values():
                av_n = _normalize_text(str(av or ""))
                if target_num and target_num in av_n:
                    return v

    # 3. Match por label de la variant.
    for v in variants:
        label_n = _normalize_text(str(v.get("label") or "")).strip()
        if label_n and label_n in norm and len(label_n) >= 3:
            return v

    return None


def _detect_explicit_products_in_inbound(
    content: str, catalog: list,
) -> tuple[list[dict], list[dict]]:
    """Rev. 104 — detector multi-producto con propuestas (F1-8 / Bug-A runtime).

    Devuelve `(matches, proposals)`:
      • `matches` — productos con producto+variante+precio resolubles desde
        el inbound actual. Listos para `cart_tool.add_item`.
      • `proposals` — productos mencionados con cantidad explícita (>=2)
        cuya variante NO es resoluble aún (multi-variant ambiguo). Se
        emiten como `cart_event(item_proposed)` para preservar la cantidad
        declarada hasta que el cliente elija variante en un turno posterior.

    Esto reemplaza el parche regex-en-historial por un patrón
    cart-as-SoT estructural (Plan A.3): item_proposed con
    `requires_confirmation=true` → ascende a item_added solo con
    confirmación explícita (variante elegida).

    Caso runtime (conv 9d357efc, 2026-05-04):
      T1: "quiero 2 jabones de coco y 1 sérum vit C"
        → matches=[] (ambos multi-variant ambiguos)
        → proposals=[{coco, qty=2}]  (sérum qty=1 default → no proposal)
      T3: "60 gramos por favor"  (caller mira proposals al resolver variante)
        → ascende coco proposal qty=2 → cart_add_item(qty=2) ✓
    """
    if not content or not catalog:
        return [], []
    norm = _normalize_text(content)
    if "?" in content:
        # Rev. 104 — antes: rechazo total si "?". Caso runtime motivador
        # (2026-05-05 manual UAT): cliente "Puedo adicionar jabón de
        # lavanda? De 100g" tenía intent CLARO de add_item pero el
        # detector descartaba por la pregunta cortés. Hoy diferenciamos:
        #   • pregunta de catálogo/disponibilidad ("tienen X?",
        #     "venden X?") → descartar (no es add_item).
        #   • pregunta-cortés con verbo de add ("puedo agregar?",
        #     "¿adicionar X?", "incluyes X?") → procesar normalmente.
        _add_intent_markers = (
            "agreg", "adicion", "anad", "anadir", "incluy", "incorpor",
            "sumar", "tambien",
        )
        _has_add_intent = any(m in norm for m in _add_intent_markers)
        if not _has_add_intent:
            return [], []
    norm_tokens = set(re.findall(r"[a-z0-9ñ]+", norm))
    if not norm_tokens:
        return [], []

    generic_terms = _generic_catalog_terms(catalog)
    _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}

    matches: list[dict] = []
    proposals: list[dict] = []
    for prod in catalog:
        title = str(prod.get("title") or "").strip()
        if not title:
            continue
        title_norm = _normalize_text(title)
        title_words = set(re.findall(r"[a-z0-9ñ]+", title_norm)) - _stop
        discriminative = title_words - generic_terms
        if not discriminative:
            continue
        if not (discriminative & norm_tokens):
            continue
        # Sem 7 F2 cierre — `_resolve_variant_from_inbound` ahora retorna
        # `list[tuple]`. Para callers que esperan single, tomar el primero.
        # Si no hay match de variant, qty se extrae del content (preserva
        # comportamiento previo para Camino B / proposals).
        _variant_matches = _resolve_variant_from_inbound(content, prod)
        if _variant_matches:
            variant, qty = _variant_matches[0]
        else:
            variant = None
            # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv febcec09):
            # pasar generic_terms para que "jabon"/"artesanal" no se traten
            # como discriminativos del producto al extraer qty.
            qty = _extract_qty_for_product(
                _normalize_text(content), prod, generic_terms=generic_terms,
            )
        if not variant:
            # Sin variante resoluble. Si el cliente declaró una qty
            # explícita >=2, registrar PROPUESTA para no perder la cantidad
            # cuando elija variante después.
            if qty >= 2:
                proposals.append({
                    "product_id": str(prod.get("id") or ""),
                    "title": str(prod.get("title") or "Producto"),
                    "quantity": qty,
                })
            continue
        unit_price = float(variant.get("price") or 0)
        if unit_price <= 0:
            continue
        matches.append({
            "product_id": str(prod.get("id") or ""),
            "variation_id": str(variant.get("id") or ""),
            "quantity": qty,
            "unit_price_cents": int(round(unit_price * 100)),
            "title": str(prod.get("title") or "Producto"),
            "variant_label": str(variant.get("label") or ""),
            "match_score": len(discriminative & norm_tokens),
        })
    matches.sort(key=lambda m: -m.get("match_score", 0))
    return matches, proposals


# Rev. 104 — Tier-2 intent detection (ADR-0011 §6.4.4)
# Verbos canónicos de add_item. El detector tier-2 también acepta
# preguntas-corteses ("¿puedo adicionar?") y verbos de deseo ("deseo X").
_ADD_ITEM_VERB_MARKERS = (
    "agreg", "adicion", "anad", "anadir", "incluy",
    "incorpor", "sumar", "tambien",
    # Verbos de deseo/petición (cliente expresa intent de obtener algo).
    "deseo", "deseamos", "quisiera", "quisieramos",
    "me gustaria", "me gustaría",
    "ponme", "ponle", "echame", "échame",
    # Petición cortés con verbo de obtención.
    "puedo agregar", "puedo adicionar", "puedo añadir", "puedo anadir",
    "puedo incluir", "puedo sumar", "puedo pedir",
    "podria agregar", "podría agregar", "podria adicionar", "podría adicionar",
    "podria pedir", "podría pedir",
    # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv bae0f6a2):
    # cliente dijo "Me peudes vender 1 Jabon de Coco y 1 de Lavanda".
    # Faltaban verbos de venta/compra en español CO + petición con
    # "vender" + typo común "peudes". Sin esto, tier-2 retornaba
    # `no_intent` → flow caía al LLM → alucinación de gramaje.
    "vender", "vende", "vendeme", "véndeme", "vendes", "venderme",
    "comprar", "compro", "compra", "comprarte", "comprarles",
    "me lo llevo", "me los llevo", "llevame", "llévame", "me llevo",
    "dame", "deme", "déme", "regalame", "regálame",
    "puedes vender", "puedes venderme", "peudes vender", "peudes venderme",
    "puede venderme", "podrias vender", "podrías vender",
    "podrias venderme", "podrías venderme",
    "me vendes", "me vendrias", "me vendrías",
    "quiero comprar", "quiero llevar", "quiero pedir",
    "quisiera comprar", "quisiera llevar", "quisiera pedir",
    "necesito", "necesitamos",
)


def _detect_add_item_intent_with_resolution(
    content: str,
    catalog: list,
) -> dict:
    """Detector tier-2 de intent de add_item con clasificación de
    resolución (ADR-0011 §6.4.4).

    Plan A.0.1 / A.0.3 — separa "qué quiere el cliente" (intent) de
    "tengo lo necesario para ejecutar" (resolution). El orchestrator usa
    `resolution` para decidir el path:

      • resolved          — producto + variante identificados → add_item.
      • product_ambiguous — verbo + discriminativa que matchea ≥2 productos
                            (ej. "lavanda" → Aceite + Jabón Lavanda).
      • variant_ambiguous — 1 producto único pero sin variante explícita
                            (ej. "jabón de coco" → 60g/100g/150g?).
      • no_product        — verbo de add pero sin producto identificable.
      • no_intent         — el inbound no expresa intent de add_item.

    Reusa heurísticas existentes:
      • `_normalize_text`, `_generic_catalog_terms` (palabras compartidas
        por ≥40% del catálogo, no discriminativas).
      • `_resolve_variant_from_inbound` (extrae variante + qty del texto).

    Retorna dict con keys consistentes:
      {
        "resolution": str,
        "matches": list[dict],     # presente si resolution=resolved
        "candidates": list[dict],  # presente si product/variant_ambiguous
        "qty": int,
      }
    """
    if not content or not catalog:
        return {"resolution": "no_intent", "matches": [], "candidates": [], "qty": 0}

    norm = _normalize_text(content)
    has_add_verb = any(m in norm for m in _ADD_ITEM_VERB_MARKERS)
    if not has_add_verb:
        return {"resolution": "no_intent", "matches": [], "candidates": [], "qty": 0}

    norm_tokens = set(re.findall(r"[a-z0-9ñ]+", norm))
    generic_terms = _generic_catalog_terms(catalog)
    _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}

    # Buscar productos cuya palabra discriminativa esté en el inbound.
    product_hits: list[dict] = []
    for prod in catalog:
        title = str(prod.get("title") or "").strip()
        if not title:
            continue
        title_norm = _normalize_text(title)
        title_words = set(re.findall(r"[a-z0-9ñ]+", title_norm)) - _stop
        discriminative = title_words - generic_terms
        if not discriminative:
            continue
        if not (discriminative & norm_tokens):
            continue
        product_hits.append({
            "product": prod,
            "discriminative_match": len(discriminative & norm_tokens),
        })

    # Extraer qty (default 1).
    nums_in_text = [int(n) for n in re.findall(r"\b(\d+)\b", norm)]
    detected_qty = max(1, nums_in_text[0]) if nums_in_text else 1
    if detected_qty > 50:
        detected_qty = 1  # sanity

    if not product_hits:
        return {
            "resolution": "no_product",
            "matches": [], "candidates": [], "qty": detected_qty,
        }

    # Filtrar por TOP score: el producto más específico al inbound. Si el
    # cliente dice "jabon de lavanda", "lavanda" es más discriminativa
    # que "jabon" (palabra que matchea varios productos). El producto que
    # comparte más palabras discriminativas con el inbound es el más
    # probable. Productos con score < top quedan filtrados.
    product_hits.sort(key=lambda h: -h["discriminative_match"])
    top_score = product_hits[0]["discriminative_match"]
    product_hits = [h for h in product_hits if h["discriminative_match"] == top_score]

    # Rev. 104 — filtro por variant compatibility (caso runtime UAT
    # 2026-05-05: cliente "1 adicional de Coco de 60g" → Aceite Coco
    # viene en ml, NO en gramos; solo Jabón Coco tiene 60g). Si hay >1
    # productos en el top score Y el cliente especificó variante explícita
    # (60g, 250ml, etc.), filtrar solo los que tienen esa variante.
    has_explicit_variant = bool(re.search(
        r"\d{1,4}\s*(g|gr|gramos|ml|mililitros|cc|kg|oz)\b",
        norm, re.IGNORECASE,
    ))
    if len(product_hits) > 1 and has_explicit_variant:
        compatible: list[dict] = []
        for h in product_hits:
            # Sem 7 F2 cierre — Bug 2: opt-in discriminative-per-segment para
            # evitar atribución cruzada de variantes entre productos distintos
            # en un mismo inbound (caso "1 de Coco 100g y 1 de Lavanda 150g").
            _matches_h = _resolve_variant_from_inbound(
                content, h["product"],
                require_discriminative_per_segment=True,
            )
            if _matches_h:
                # Sem 7 F2 cierre — Bug 2: tomar todas las variantes que
                # matcheen (no solo la primera). Necesario cuando el cliente
                # declara 2+ variantes de un mismo producto en un inbound.
                # Para multi-product (1 variante por producto), tomamos
                # solo la primera, que es la que el segmento del producto
                # ya filtró con discriminative_words.
                v, q = _matches_h[0]
                compatible.append({**h, "_resolved_variant": v, "_resolved_qty": q})
        if compatible:
            product_hits = compatible

    # Sem 7 F2 cierre 2026-05-19 — Bug 2 founder UAT:
    # Caso "N productos × 1 variante c/u" en un solo inbound (ej. "1 de Coco
    # 100g y 1 de Lavanda 150g"). Si después del filtro de compatibility
    # tenemos >1 productos Y cada uno tiene su variante explícita resolvida,
    # NO es ambiguo — el cliente declaró todos. Resolver como resolved_multi.
    if (
        len(product_hits) > 1
        and has_explicit_variant
        and all(
            isinstance(h.get("_resolved_variant"), dict) for h in product_hits
        )
    ):
        matches = []
        for h in product_hits:
            prod = h["product"]
            v = h["_resolved_variant"]
            q = h.get("_resolved_qty") or 1
            unit_price = float(v.get("price") or 0)
            matches.append({
                "product_id": str(prod.get("id") or ""),
                "variation_id": str(v.get("id") or ""),
                "title": str(prod.get("title") or "Producto"),
                "variant_label": str(v.get("label") or ""),
                "quantity": q if q >= 1 else 1,
                "unit_price_cents": int(round(unit_price * 100)),
            })
        return {
            "resolution": "resolved_multi",
            "matches": matches,
            "candidates": [],
            "qty": sum(m["quantity"] for m in matches),
        }

    # Si solo 1 producto en el top, intentar resolver variante.
    if len(product_hits) == 1:
        prod = product_hits[0]["product"]
        _matches_p = _resolve_variant_from_inbound(content, prod)
        if _matches_p:
            variant, qty = _matches_p[0]
        else:
            variant, qty = None, 1
        if variant:
            unit_price = float(variant.get("price") or 0)
            return {
                "resolution": "resolved",
                "matches": [{
                    "product_id": str(prod.get("id") or ""),
                    "variation_id": str(variant.get("id") or ""),
                    "title": str(prod.get("title") or "Producto"),
                    "variant_label": str(variant.get("label") or ""),
                    "quantity": qty if qty >= 1 else detected_qty,
                    "unit_price_cents": int(round(unit_price * 100)),
                }],
                "candidates": [],
                "qty": qty if qty >= 1 else detected_qty,
            }
        # Producto único pero sin variante resoluble → variant_ambiguous.
        variants = prod.get("variants") or []
        return {
            "resolution": "variant_ambiguous",
            "matches": [],
            "candidates": [{
                "product_id": str(prod.get("id") or ""),
                "title": str(prod.get("title") or "Producto"),
                "variants": [
                    {
                        "variation_id": str(v.get("id") or ""),
                        "label": str(
                            (v.get("attributes") or {}).get("size")
                            or v.get("label") or ""
                        ),
                        "price": float(v.get("price") or 0),
                    }
                    for v in variants
                ],
            }],
            "qty": detected_qty,
        }

    # Múltiples productos match con mismo score → product_ambiguous.
    # (El sort + filter top_score arriba ya dejó solo los empates).
    return {
        "resolution": "product_ambiguous",
        "matches": [],
        "candidates": [{
            "product_id": str(h["product"].get("id") or ""),
            "title": str(h["product"].get("title") or "Producto"),
            "variants": [
                {
                    "variation_id": str(v.get("id") or ""),
                    "label": str(
                        (v.get("attributes") or {}).get("size")
                        or v.get("label") or ""
                    ),
                    "price": float(v.get("price") or 0),
                }
                for v in (h["product"].get("variants") or [])
            ],
        } for h in product_hits],
        "qty": detected_qty,
    }


# Rev. 104 — qty-change intent detector (ADR-0011 §6.4.3)
# Verbos canónicos que el cliente usa para CAMBIAR la cantidad de un item
# ya en el cart. Diferenciado de add_item: estos NO suman al qty existente,
# REEMPLAZAN el qty (update_item_quantity).
_QTY_UPDATE_VERB_PHRASES = (
    "que sean", "que sea",
    "ahora son", "ahora es",
    "en vez de", "en lugar de",
    "cambia a", "cambiar a", "cambialo a", "cámbialo a",
    "cambiame a", "cámbiame a",
    "actualizar", "actualizalo", "actualízalo", "actualizame",
    "actualízame", "actualizar a",
    "modificar", "modificalo", "modifícalo",
    "subir a", "subelo a", "súbelo a",
    "bajar a", "bajalo a", "bájalo a",
    "ponme", "pon",
    "que en vez", "vez de",
)


def _detect_qty_change_intent(
    content: str,
    cart_items_with_titles: list[dict],
) -> Optional[dict]:
    """Detector pre-LLM de intent de **cambio de cantidad** sobre item ya en cart.

    Plan A.0.1 (cart-as-SoT) — diferenciado de add_item:
      • add_item: cliente quiere AGREGAR un producto nuevo o más unidades
        sumando al qty existente.
      • qty_change: cliente quiere REEMPLAZAR el qty actual de un item ya
        en el cart. "Que sean 2 de lavanda" cuando hay 1×Lavanda → qty=2,
        no qty=3 (1+2).

    Resolución del producto: contra el **cart real**, no contra el catálogo
    abstracto. Si cart tiene 1×Lavanda y cliente dice "que sean 2 de
    lavanda", el match es unívoco aún sin variante explícita en el inbound.

    cart_items_with_titles: lista de dicts con {variation_id, product_id,
        title, quantity, unit_price_cents}.

    Retorna:
      None si no hay intent de qty_change detectado.
      {"ambiguous": True, "candidates": [...], "new_qty": N} si hay >=2
        items del cart que matchean igual.
      {variation_id, product_id, title, current_qty, new_qty,
       unit_price_cents} si match unívoco.
    """
    if not content or not cart_items_with_titles:
        return None
    norm = _normalize_text(content)
    if not any(v in norm for v in _QTY_UPDATE_VERB_PHRASES):
        return None

    # Extraer números enteros del inbound. En frases tipo "en vez de 1 sean 2"
    # tomamos el ÚLTIMO número como qty objetivo (más reciente en la frase).
    nums_found = [int(n) for n in re.findall(r"\b(\d+)\b", norm)]
    if not nums_found:
        return None
    new_qty = nums_found[-1]
    if new_qty < 1 or new_qty > 50:  # sanity cap
        return None

    # Resolver producto: matchear palabras del inbound contra títulos del cart.
    _stop = {
        "de", "con", "y", "o", "la", "el", "los", "las", "un", "una",
        "que", "sea", "sean", "ahora", "es", "vez", "en", "lugar", "son",
        "cambia", "cambiar", "actualizar", "modificar", "ponme", "pon",
        "subir", "bajar", "subelo", "bajalo", "actualizalo", "modificalo",
        "favor", "por", "quiero", "deseo", "quisiera",
    }
    inbound_tokens = set(re.findall(r"[a-z0-9ñ]+", norm)) - _stop

    matches: list[tuple[dict, int]] = []
    for item in cart_items_with_titles:
        title = item.get("title") or ""
        title_norm = _normalize_text(title)
        title_tokens = set(re.findall(r"[a-z0-9ñ]+", title_norm)) - _stop
        intersection = title_tokens & inbound_tokens
        if intersection:
            matches.append((item, len(intersection)))
    matches.sort(key=lambda m: -m[1])

    if not matches:
        # Sin producto explícito en el inbound. Heurística: si el cart tiene
        # exactamente 1 item, asumir que el cliente se refiere a ese.
        if len(cart_items_with_titles) == 1:
            it = cart_items_with_titles[0]
            return {
                "variation_id": str(it.get("variation_id") or ""),
                "product_id": str(it.get("product_id") or ""),
                "title": str(it.get("title") or "Producto"),
                "current_qty": int(it.get("quantity") or 1),
                "new_qty": new_qty,
                "unit_price_cents": int(it.get("unit_price_cents") or 0),
            }
        return None

    # Si hay tie (varios items con la misma cantidad de palabras matcheadas),
    # devolver ambiguous para que el bot pida clarificación.
    if len(matches) >= 2 and matches[0][1] == matches[1][1]:
        return {
            "ambiguous": True,
            "candidates": [str(m[0].get("title") or "Producto") for m in matches[:3]],
            "new_qty": new_qty,
        }

    it = matches[0][0]
    return {
        "variation_id": str(it.get("variation_id") or ""),
        "product_id": str(it.get("product_id") or ""),
        "title": str(it.get("title") or "Producto"),
        "current_qty": int(it.get("quantity") or 1),
        "new_qty": new_qty,
        "unit_price_cents": int(it.get("unit_price_cents") or 0),
    }


def _detect_explicit_product_in_inbound(
    content: str, catalog: list,
) -> Optional[dict]:
    """Rev. 103 — Cliente especifica producto + variante en un solo mensaje
    sin esperar a que el bot presente opciones. Caso real (mode=known):
    "Quiero un jabón de coco de 60g". El detector existente
    `_last_outbound_presented_variants` falla aquí porque el último
    outbound del bot fue solo un saludo, NO una presentación.

    Estrategia: matchear en el inbound:
      1. Una palabra discriminativa del título (no genérica). Para
         "Jabón Artesanal de Coco" → {coco}. Si el inbound contiene
         "coco", candidate match.
      2. Un atributo de variante (60g, 100ml, etc) que matchee una de
         las variantes del producto candidate.

    Devuelve dict listo para `cart_tool.add_item` o None.
    """
    if not content or not catalog:
        return None
    if "?" in content:
        return None  # pregunta no es intent de compra
    norm = _normalize_text(content)
    norm_tokens = set(re.findall(r"[a-z0-9ñ]+", norm))
    if not norm_tokens:
        return None

    # Términos genéricos del catálogo (palabras compartidas por ≥40%
    # de productos). Reusa helper existente.
    generic_terms = _generic_catalog_terms(catalog)
    _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}

    best_match: Optional[dict] = None
    for prod in catalog:
        title = str(prod.get("title") or "").strip()
        if not title:
            continue
        title_norm = _normalize_text(title)
        title_words = set(re.findall(r"[a-z0-9ñ]+", title_norm)) - _stop
        # Palabras discriminativas (no genéricas)
        discriminative = title_words - generic_terms
        if not discriminative:
            continue  # Producto sin discriminantes — saltar
        # Necesita ALGUNA discriminativa en el inbound
        if not (discriminative & norm_tokens):
            continue
        # Match — ahora resolver variante (Sem 7 F2: lista[tuple], single)
        _vmatch = _resolve_variant_from_inbound(content, prod)
        if _vmatch:
            variant, qty = _vmatch[0]
        else:
            variant, qty = None, 1
        if not variant:
            continue
        unit_price = float(variant.get("price") or 0)
        if unit_price <= 0:
            continue
        # Si encontramos múltiples productos match, preferir el de
        # MÁS palabras discriminativas matcheadas (más específico).
        match_score = len(discriminative & norm_tokens)
        if best_match is None or match_score > best_match["_score"]:
            best_match = {
                "product_id": str(prod.get("id") or ""),
                "variation_id": str(variant.get("id") or ""),
                "quantity": qty,
                "unit_price_cents": int(round(unit_price * 100)),
                "title": str(prod.get("title") or "Producto"),
                "variant_label": str(variant.get("label") or ""),
                "_score": match_score,
            }

    if best_match:
        best_match.pop("_score", None)
    return best_match


def _detect_variant_confirmation(
    content: str, history: list[dict], catalog: list,
) -> list[dict]:
    """Rev. 103 — Detector pre-LLM determinístico cart-as-SoT.

    Sem 7 F2 cierre: contrato cambiado a `list[dict]` (puede ser vacía, 1
    elemento, o N) para soportar multi-variant input ("1 de 100ml y 1 de
    250ml"). El caller itera la lista llamando `add_item` por cada item.

    Dos caminos:
      A. Bot acaba de presentar variantes → cliente elige una o más
         ("60g" o "1 de 100ml y 1 de 250ml"). Match por variant attribute.
      B. Cliente especifica producto+variante en un mensaje
         ("quiero jabón de coco 60g") sin esperar presentación.
         Match por discriminative word del título + variant attribute.

    Devuelve lista de dicts listos para `cart_tool.add_item`.
    """
    if not content or not catalog:
        return []
    if "?" in content:
        return []
    norm = _normalize_text(content)
    tokens = norm.split()
    if not tokens or len(tokens) > 14:
        return []  # Mensajes muy largos descartados (probablemente
                   # consulta o address dump, no intent de compra)

    results: list[dict] = []
    seen_variation_ids: set[str] = set()

    # Camino A: ¿bot presentó variantes de uno o más productos en T-1?
    # Para cada producto presentado, evaluar TODAS las variantes que
    # matcheen el inbound (multi-variant support).
    products = _last_outbound_presented_variants_all(catalog, history)
    # Sem 7 F2 cierre 2026-05-19 — Bug 2.2 founder UAT:
    # Si T-1 listó múltiples productos (ej. Coco + Lavanda), aplicar
    # discriminative-per-segment para evitar atribución cruzada de
    # variantes entre productos distintos en un mismo inbound. Caso
    # runtime: "1 de Coco 100g y 1 de Lavanda 150g" matcheaba la
    # variante 150g de Coco (porque Coco tiene 150g) y la 100g de
    # Lavanda (porque Lavanda tiene 100g) → 4 items en cart en vez de 2.
    multi_product_context = len(products) > 1

    # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv f6ec7213):
    # disambiguación CROSS-PRODUCT a nivel de VARIANTE (post-resolución).
    # Caso: bot listó 3 sérums; cliente dijo "Sérum Vitamina C 30ml".
    # Cada sérum tenía variante 30ml → matcheaban los 3 → cart con 3 items.
    #
    # Arquitectura limpia:
    #   1. Computar `ambiguous_variant_labels`: labels (e.g. "30ml") que
    #      aparecen en ≥2 productos del set presentado. Si solo 1 producto
    #      tiene "60g", "60g" NO es ambigua y matchea sin requerir mención
    #      del nombre del producto (caso Coco/Sérum: 60g solo en Coco).
    #   2. Computar `product_discriminative_words` por producto: palabras
    #      del título exclusivas de ese producto vs los otros del set.
    #   3. Para cada match (producto, variante): si la variante es ambigua
    #      (compartida), exigir que el inbound contenga ≥1 palabra
    #      discriminativa del producto matched. Si la variante NO es
    #      ambigua, aceptar sin requerir mención (la variante misma
    #      identifica al producto unívocamente).
    ambiguous_variant_labels: set[str] = set()
    product_discriminative: dict[str, set[str]] = {}
    if multi_product_context:
        _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}
        # Conteo de labels de variante a través de productos.
        _variant_label_counts: dict[str, int] = {}
        for _prod in products:
            for _v in _prod.get("variants") or []:
                _label = _normalize_text(str(_v.get("label") or "")).strip()
                if _label:
                    _variant_label_counts[_label] = _variant_label_counts.get(_label, 0) + 1
        ambiguous_variant_labels = {
            lbl for lbl, c in _variant_label_counts.items() if c >= 2
        }
        # Conteo de palabras de título a través de productos (para
        # identificar palabras compartidas que NO sirven como discriminadores).
        _title_word_counts: dict[str, int] = {}
        for _prod in products:
            _tn = _normalize_text(str(_prod.get("title") or ""))
            _tw = {w for w in re.findall(r"[a-z0-9ñ]+", _tn) if len(w) >= 4} - _stop
            for w in _tw:
                _title_word_counts[w] = _title_word_counts.get(w, 0) + 1
        _shared_title_words = {w for w, c in _title_word_counts.items() if c >= 2}
        # Per-producto: palabras exclusivas del título.
        for _prod in products:
            _tn = _normalize_text(str(_prod.get("title") or ""))
            _tw = {w for w in re.findall(r"[a-z0-9ñ]+", _tn) if len(w) >= 4} - _stop
            product_discriminative[str(_prod.get("id") or "")] = _tw - _shared_title_words

    _content_tokens = set(re.findall(r"[a-z0-9ñ]+", _normalize_text(content)))

    for product in products:
        variant_matches = _resolve_variant_from_inbound(
            content, product,
            require_discriminative_per_segment=multi_product_context,
        )
        for variant, qty in variant_matches:
            unit_price = float(variant.get("price") or 0)
            if unit_price <= 0:
                continue
            variation_id = str(variant.get("id") or "")
            if not variation_id or variation_id in seen_variation_ids:
                continue
            # Sem 7 F2 cierre 2026-05-21 — gate cross-product post-resolución.
            # Si la variante matched tiene label compartido con otros productos
            # presentados, exigir que el inbound mencione palabra exclusiva
            # del título de ESTE producto. Si la variante es única (solo este
            # producto la tiene), aceptar sin requerir mención.
            if multi_product_context:
                _label_norm = _normalize_text(str(variant.get("label") or "")).strip()
                if _label_norm in ambiguous_variant_labels:
                    _disc = product_discriminative.get(str(product.get("id") or ""), set())
                    if not (_content_tokens & _disc):
                        # Variante ambigua + inbound no menciona producto.
                        # Rechazar para evitar atribución cruzada.
                        continue
            results.append({
                "product_id": str(product.get("id") or ""),
                "variation_id": variation_id,
                "quantity": qty,
                "unit_price_cents": int(round(unit_price * 100)),
                "title": str(product.get("title") or "Producto"),
                "variant_label": str(variant.get("label") or ""),
            })
            seen_variation_ids.add(variation_id)

    if results:
        return results

    # Camino B: producto+variante explícitos en el inbound (single).
    # Si el detector explícito retorna un dict, envolverlo en lista.
    single = _detect_explicit_product_in_inbound(content, catalog)
    if single:
        return [single]
    return []


def _save_product_snapshot(
    supabase: Client,
    *,
    conversation_id: str,
    tenant_id: str,
    catalog: list,
    history_for_prompt: list[dict],
) -> None:
    """
    R-13: Persiste snapshot del producto seleccionado en messages.payload
    cuando el carrier acaba de ser confirmado.
    Previene que _build_verified_order_context falle en conversaciones largas
    donde el usuario habló de otros productos o la detección por texto es ambigua.
    """
    ctx = _build_verified_order_context(catalog, history_for_prompt)
    if not ctx or not ctx.get("product_id"):
        logger.warning("[R-13] No se pudo construir contexto para snapshot")
        return
    try:
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "context_snapshot",
            "content": "",
            "payload": {
                "product_id": ctx["product_id"],
                "variation_id": ctx["variation_id"],
                "quantity": ctx["quantity"],
                "unit_price_cents": ctx["unit_price_cents"],
            },
            "processed": True,
            "processing_status": "processed",
        }).execute()
        logger.info(
            "[R-13] Snapshot guardado: product=%s variation=%s conv=%s",
            ctx["product_id"], ctx["variation_id"], conversation_id,
        )
    except Exception as e:
        logger.warning("[R-13] Error guardando snapshot: %s", e)


def _query_mentions_any_product(catalog: list, query_tokens: set[str]) -> bool:
    if not query_tokens:
        return False
    for product in catalog:
        if _product_title_tokens(str(product.get("title", ""))) & query_tokens:
            return True
    return False


def _variant_tokens(product_title: str, variant: dict) -> set[str]:
    attrs = variant.get("attributes")
    attrs_text = ""
    if isinstance(attrs, dict):
        attrs_text = " ".join([f"{k} {v}" for k, v in attrs.items()])
    searchable = " ".join(
        [
            str(product_title),
            str(variant.get("label", "")),
            str(variant.get("sku") or ""),
            attrs_text,
        ]
    )
    return set(_tokenize_text(searchable))


def _build_variant_match_section(catalog: list, query_text: str, history: list[dict]) -> str:
    if not _is_variant_query(query_text):
        return ""

    required_tokens = _extract_query_specific_tokens(query_text)
    context_product = _find_context_product_from_history(catalog, history)
    mentions_product_now = _query_mentions_any_product(catalog, required_tokens)

    if not required_tokens:
        return """

ANÁLISIS DE VARIANTE (QUERY ACTUAL):
- Consulta de variante detectada, pero faltan datos específicos.
- Pide precisión de variante (por ejemplo color/talla/SKU) antes de confirmar precio o stock.
"""

    exact_matches: list[dict] = []
    products_to_scan = catalog
    if context_product and not mentions_product_now:
        products_to_scan = [context_product]

    for product in products_to_scan:
        title = product.get("title", "")
        for variant in product.get("variants") or []:
            searchable_tokens = _variant_tokens(str(title), variant)
            if required_tokens.issubset(searchable_tokens):
                exact_matches.append(
                    {
                        "title": title,
                        "label": variant.get("label", "variante"),
                        "price": variant.get("price", 0),
                        "stock": variant.get("stock", 0),
                    }
                )

    if exact_matches:
        lines = ["", "ANÁLISIS DE VARIANTE (QUERY ACTUAL):", "- Coincidencias exactas detectadas:"]
        if context_product and not mentions_product_now:
            lines.append(
                f"- Producto en contexto detectado por historial: {context_product.get('title', 'N/A')}"
            )
        for match in exact_matches[:3]:
            lines.append(
                f"  - {match['title']} | {match['label']} | "
                f"precio: {match['price']} | stock: {match['stock']}"
            )
        if len(exact_matches) > 3:
            lines.append(f"  - ... y {len(exact_matches) - 3} coincidencia(s) adicional(es)")
        lines.append("- Si hay más de una coincidencia exacta, pide confirmación breve antes de cerrar la respuesta.")
        return "\n".join(lines)

    no_match_lines = [
        "",
        "ANÁLISIS DE VARIANTE (QUERY ACTUAL):",
    ]
    if context_product and not mentions_product_now:
        no_match_lines.append(
            f"- Producto en contexto detectado por historial: {context_product.get('title', 'N/A')}"
        )
    no_match_lines.extend(
        [
            "- No se encontraron coincidencias exactas para la variante solicitada en el catálogo disponible.",
            "- No inventes disponibilidad/precio. Solicita precisión o escala al equipo experto (requires_human=true).",
        ]
    )
    return "\n".join(no_match_lines)


_BUYING_INTENT_STRONG_TOKENS = {
    "comprar", "compra", "lo compro", "lo quiero comprar", "agregar al pedido", "hacer pedido",
    "proceder", "procede", "confirmo", "confirmar pedido", "me lo llevo", "pagar", "pago",
    # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv bae0f6a2):
    # frases coloquiales CO de "véndeme/vendeme" + typo "peudes" que NO
    # estaban listadas. Sin estos, "Me peudes vender 1 Coco y 1 Lavanda"
    # caía a buying_intent=False → CATALOG_MODE → LLM libre → alucinación.
    "vendeme", "véndeme", "me vendes", "venderme",
    "puedes vender", "peudes vender", "puede venderme", "puedes venderme",
    "podrias vender", "podrías vender", "podrias venderme", "podrías venderme",
    "quiero comprar", "quiero llevar", "quiero pedir",
    "quisiera comprar", "quisiera llevar", "quisiera pedir",
    "necesito comprar", "necesito llevar",
    "dame", "regalame", "regálame",
}
_BUYING_INTENT_CONTEXT_MARKERS = {
    "cotice el envio", "cotizar envio", "envio de", "economica", "rapida", "direccion de entrega",
    "nombre completo", "resumen de tu pedido", "confirmas que los datos", "link de pago",
}
_INQUIRY_ONLY_MARKERS = {
    "averiguar", "consultar", "saber", "informacion", "información", "precio", "stock", "tienes",
}
_ADDRESS_HINT_TOKENS = {
    "calle", "carrera", "cra", "kr", "avenida", "av", "transversal", "diagonal",
    "barrio", "torre", "apartamento", "apto", "conjunto", "edificio", "casa",
}


def _has_buying_intent(query_text: str, history: list[dict]) -> bool:
    normalized = _normalize_text(query_text)
    if not normalized:
        return False

    if any(token in normalized for token in _BUYING_INTENT_STRONG_TOKENS):
        return True

    # "me gustaría averiguar/consultar..." no es intención de compra todavía.
    if "me gustaria" in normalized and any(marker in normalized for marker in _INQUIRY_ONLY_MARKERS):
        return False

    # Follow-up afirmativo muy corto solo vale como buying intent si venimos
    # de contexto transaccional reciente.
    tokens = set(_tokenize_text(query_text))
    is_short_affirmative = len(tokens) <= 3 and bool(tokens & {"si", "sí", "ok", "dale", "claro", "listo"})

    recent = history[-6:] if history else []
    has_recent_transactional_context = False
    for msg in recent:
        content = _normalize_text(str(msg.get("content") or ""))
        if any(marker in content for marker in _BUYING_INTENT_CONTEXT_MARKERS):
            has_recent_transactional_context = True
            break

    if is_short_affirmative and has_recent_transactional_context:
        return True

    return has_recent_transactional_context


def _has_shipping_been_quoted(history: list[dict]) -> bool:
    shipping_markers = ("economica", "rapida", "envio de", "opciones de envio", "cotizacion de envio")
    for msg in history or []:
        if str(msg.get("direction") or "").strip().lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        if any(marker in content_norm for marker in shipping_markers):
            return True
    return False


def _has_shipping_been_quoted_in_conversation(
    supabase: Client, conversation_id: str
) -> bool:
    """Versión DB que verifica TODA la conversación (no limitada por
    CONVERSATION_HISTORY_LIMIT). Usar cuando el history en memoria pueda
    estar truncado y haya shipping marker antes de los últimos N mensajes.
    """
    if not conversation_id:
        return False
    try:
        # ILIKE sobre outbound. PostgREST acepta `or=` con varios markers.
        for marker in ("economica", "Económica", "Económica", "Envío de"):
            r = (
                supabase.table("messages")
                .select("id", count="exact")
                .eq("tenant_id", conversation_id[:conversation_id.find("_")] if "_" in conversation_id else tenant_id)
                .eq("conversation_id", conversation_id)
                .eq("direction", "outbound")
                .ilike("content", f"%{marker}%")
                .limit(1)
                .execute()
            )
            if int(getattr(r, "count", 0) or 0) > 0:
                return True
    except Exception as exc:
        logger.warning("[FSM] error verificando shipping quoted DB conv=%s: %s", conversation_id, exc)
    return False


def _cart_changed_since_last_quote(history: list[dict]) -> bool:
    """Rev. 73 — detecta si el cliente agregó un producto al carrito DESPUÉS del
    último outbound de cotización de envío. Si es así, la cotización vigente
    está stale (no refleja el peso/dimensiones actual) → forzar re-cotización.

    Trigger: outbound del bot con frase de confirmación de adición ("agregué",
    "listo agregué", "añadí", "lo agregué") después del último outbound de
    cotización (con precio $X.XXX + palabra envío/Económica/Rápida).

    Patrón típico (log 2026-04-29 conv 615a9902):
        outbound: "El envío a Bogotá: $17.730 con Coordinadora"   # cotizar
        outbound: "¡Listo! Agregué el Sérum a tu carrito."        # cart cambió
        → cart_changed_since_last_quote = True → re-cotizar.
    """
    if not history:
        return False
    _quote_markers = ("economica", "rapida", "envio a", "envio de", "costo de envio")
    _add_markers = ("agregue", "listo agregue", "anadi", "agregado", "lo agregue")

    # Encontrar índice del último outbound de cotización
    last_quote_idx = None
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        # Heurística simple: contiene marker de cotización + un precio
        has_quote_marker = any(m in content_norm for m in _quote_markers)
        has_price = bool(re.search(r"\$\s*[\d.,]+", str(msg.get("content") or "")))
        if has_quote_marker and has_price:
            last_quote_idx = i
            break
    if last_quote_idx is None:
        return False

    # Buscar outbound de adición posterior
    for msg in history[last_quote_idx + 1:]:
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        if any(m in content_norm for m in _add_markers):
            return True
    return False


def _has_carrier_been_selected(history: list[dict]) -> bool:
    """
    Detecta si el cliente seleccionó explícitamente un carrier.
    Busca el outbound de cotización más reciente (con "Económica"/"Rápida") y
    verifica que ALGÚN inbound posterior sea una selección válida:
    corta (≤8 tokens), con token de carrier, sin signo de pregunta.
    Evita falsos positivos en preguntas como '¿la económica incluye seguro?'
    """
    carrier_tokens = (
        "economica", "rapida", "deprisa", "servientrega", "coordinadora", "tcc",
        "dhl", "fedex", "interrapidisimo", "mensajeros", "urbanos",
    )
    # Marker específico de shipping_quote_tool ("¿Con cuál continuamos?" o
    # "¿Continuamos con la opción Económica?" o "¿Continuamos?"). El "?"
    # diferencia del consent template ("continuamos registrando tus datos"
    # — sin signo de pregunta) y evita el falso positivo.
    _quote_outbound_markers = ("continuamos con", "cual continuamos", "continuamos?")

    hist = list(history or [])
    # Encontrar el índice del outbound de cotización más reciente
    quote_idx = None
    quote_content_norm = ""
    for i, msg in enumerate(hist):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        if any(m in content_norm for m in _quote_outbound_markers):
            quote_idx = i
            quote_content_norm = content_norm  # Guardar para detectar opción única

    if quote_idx is None:
        return False

    # Detectar si la cotización mostró UNA sola opción.
    # "¿Continuamos con la opción Económica?" = opción única → afirmativo corto = selección válida.
    # "¿Con cuál continuamos? Económica o Rápida" = múltiple → afirmativo "sigamos"/"continuemos"
    # se interpreta como Económica (default cheaper).
    is_single_option = (
        "continuamos con la opcion" in quote_content_norm
        and "con cual continuamos" not in quote_content_norm
    )
    _affirmative_short = {"si", "sí", "ok", "dale", "listo", "claro", "si claro", "de una"}
    # Rev. 103 — "sigamos"/"continuemos" tras multi-opción = aceptar default
    # cheaper (Económica). Caso real: cliente que solo quiere terminar la
    # compra rápido sin elegir explícitamente. Sin esto el LLM toma control
    # del turno (display=AWAITING_CARRIER_SELECTION) y se salta NEEDS_CONSENT.
    _continue_intent = {
        "sigamos", "continuemos", "continuar", "continua", "continúa",
        "procedamos", "compra", "comprar", "avancemos", "sigue",
    }

    # Verificar inbounds DESPUÉS del outbound de cotización
    for msg in hist[quote_idx + 1:]:
        if str(msg.get("direction") or "").lower() != "inbound":
            continue
        raw = str(msg.get("content") or "")
        content_n = _normalize_text(raw)
        tokens = content_n.split()
        has_carrier = any(token in content_n for token in carrier_tokens)
        is_question = "?" in raw
        is_short = len(tokens) <= 8

        if is_question:
            continue  # Pregunta nunca es selección
        if has_carrier and is_short:
            return True  # Mencionó el carrier explícitamente
        if is_single_option and is_short:
            # "Sí, dale" / "ok claro" / "listo" — quitar comas/signos y verificar
            # token por token contra el set afirmativo.
            cleaned = re.sub(r"[,\.!\?;:]+", " ", content_n).strip()
            cleaned_tokens = [t for t in cleaned.split() if t]
            if cleaned_tokens and all(t in _affirmative_short for t in cleaned_tokens):
                return True
            if any(t in _affirmative_short for t in cleaned_tokens) and len(cleaned_tokens) <= 3:
                return True
        # Rev. 103 — multi-opción: "sigamos con la compra" / "continuemos" /
        # "procedamos" → aceptar como Económica (cheaper default).
        if is_short and any(t in _continue_intent for t in tokens):
            return True
    return False


def _has_carrier_been_selected_in_conversation(
    supabase: Client, conversation_id: str
) -> bool:
    """Rev. 103 — DB fallback para `_has_carrier_been_selected` (igual
    patrón que `_has_shipping_been_quoted_in_conversation`).

    Razón: el `history` en memoria está limitado a CONVERSATION_HISTORY_LIMIT=25.
    En conversaciones largas (caso real conv 3448118a con 41 mensajes) el
    inbound "Económica" + el outbound de cotización quedan FUERA del window
    → `carrier_selected=False` → state degrada a AWAITING_CARRIER_SELECTION
    → cadena de fallos: LLM compone resumen freestyle (con alucinaciones de
    productos no pedidos) + payment_link_tool no dispara (guard de
    display_state) → "Te genero el link" sin link real al cliente.

    Estrategia: query directo a `messages` de TODA la conversación. Busca
    el outbound de cotización con markers + cualquier inbound posterior con
    token de carrier (economica/rapida/etc). Sin límite de history.
    """
    if not conversation_id:
        return False
    carrier_tokens = (
        "economica", "rapida", "deprisa", "servientrega", "coordinadora",
        "tcc", "dhl", "fedex", "interrapidisimo", "mensajeros", "urbanos",
    )
    try:
        # 1. Encontrar el outbound de cotización más reciente (con marker
        #    "continuamos" + signo de pregunta) — patrón shipping_quote_tool.
        quote_res = (
            supabase.table("messages")
            .select("id, content, created_at")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("direction", "outbound")
            .ilike("content", "%continuamos%")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        quote_rows = quote_res.data or []
        quote_at: Optional[str] = None
        for row in quote_rows:
            content_norm = _normalize_text(str(row.get("content") or ""))
            if any(m in content_norm for m in (
                "continuamos con", "cual continuamos", "continuamos?"
            )):
                quote_at = row.get("created_at")
                break
        if not quote_at:
            return False

        # 2. Buscar inbounds POSTERIORES al quote, escaneando por carrier
        #    token. Limitamos a 30 mensajes posteriores (suficiente para
        #    cualquier flujo de PII collection razonable).
        in_res = (
            supabase.table("messages")
            .select("content")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("direction", "inbound")
            .gt("created_at", quote_at)
            .order("created_at", desc=False)
            .limit(30)
            .execute()
        )
        for row in (in_res.data or []):
            raw = str(row.get("content") or "")
            content_n = _normalize_text(raw)
            tokens = content_n.split()
            if "?" in raw:
                continue  # pregunta NO es selección
            if len(tokens) > 8:
                continue  # mensaje largo NO es selección de carrier
            if any(token in content_n for token in carrier_tokens):
                return True
            # Continue intent ("sigamos", "continuemos") como Económica default
            if any(t in {
                "sigamos", "continuemos", "continuar", "continua", "continúa",
                "procedamos", "compra", "comprar", "avancemos", "sigue",
            } for t in tokens):
                return True
    except Exception as exc:
        logger.warning(
            "[FSM] error verificando carrier_selected DB conv=%s: %s",
            conversation_id, exc,
        )
    return False


def _last_outbound_was_order_confirmation_question(history: list[dict]) -> bool:
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").strip().lower() == "outbound":
            content_norm = _normalize_text(str(msg.get("content") or ""))
            return any(marker in content_norm for marker in _ORDER_CONFIRMATION_MARKERS)
    return False


def _emit_summary_rendered_event(
    supabase,
    *,
    conversation_id: str,
    tenant_id: str,
    summary_text: str,
    correlation_id: Optional[str] = None,
) -> None:
    """Rev. 104 (F1-6) — emite `cart_events.summary_rendered` best-effort.

    Resuelve cart_id buscando el cart abierto de la conversación. Si no
    hay cart o falla la emisión, swallow + log debug. El cliente ya recibió
    el resumen cuando este helper se invoca; la auditoría no debe bloquear.

    Por convención se invoca DESPUÉS de `_send_outbound_text` con el texto
    del resumen para que la trazabilidad refleje el orden real visto por
    el cliente.
    """
    try:
        from tools.cart_tool import get_cart_with_items
        from cart.events import emit as _emit
        cart = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
        if not cart or not cart.get("id"):
            return
        items_count = len(cart.get("items") or [])
        _emit(
            supabase,
            cart_id=cart["id"], tenant_id=tenant_id,
            event_type="summary_rendered",
            payload={
                "total_cents": int(cart.get("total_cents") or 0),
                "subtotal_cents": int(cart.get("subtotal_cents") or 0),
                "shipping_cents": int(cart.get("shipping_cents") or 0),
                "items_count": items_count,
                "summary_chars": len(summary_text or ""),
            },
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[CART_EVENT] summary_rendered emit falló: %s", exc)


# Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv e0d7c539):
# Detector determinístico de "LLM intentó confirmar cart-add sin que
# `cart_tool.add_item` haya corrido". El detector busca CONFIRMACIÓN
# verbal + VARIANTE explícita (peso/volumen entre paréntesis) + PRECIO
# en un mismo segmento. Los 3 elementos juntos = LLM afirmando estado
# de carrito concreto que no existe en DB. Sin los 3, podría ser solo
# acuse-de-recibo neutral ("Claro, te muestro...") que no requiere
# rewrite.
#
# Caso runtime: "Listo, 1x Jabón Artesanal de Coco (60g) por $18.000 COP"
#   → confirmación "Listo" ✓
#   → variante "(60g)" ✓
#   → precio "$18.000" ✓
#   → REWRITE: pedir presentación al cliente.
#
# Falso positivo defensa: el caller solo invoca este detector cuando
# `_cart_add_executed_this_turn=False`. Si add_item corrió legítimamente,
# la confirmación es real y no se reescribe.
_CART_ADD_CONFIRMATION_VERBS = (
    r"listo|agregue|agregu[eé]|a[nñ]ad[ií]|te\s+vendo|"
    r"agreg[oó]\s+a\s+tu\s+carrito|sum[eé]|agregad[oa]s?"
)
_CART_ADD_CONFIRMATION_REGEX = re.compile(
    rf"\b(?:{_CART_ADD_CONFIRMATION_VERBS})\b"
    r"[\s\S]{0,250}?"                                  # filler tolerante
    r"\(\s*\d+\s*(?:g|gr|gramos|ml|mililitros|cc|kg|oz)\s*\)"   # variante
    r"[\s\S]{0,80}?"
    r"\$\s*\d",                                        # precio
    flags=re.IGNORECASE,
)


def _looks_like_cart_add_confirmation(text: str) -> bool:
    """True si el texto del LLM afirma haber agregado item(s) al carrito
    con variante + precio explícitos. Caller debe gatear con
    `_cart_add_executed_this_turn` para evitar falsos positivos sobre
    confirmaciones legítimas post add_item."""
    if not text:
        return False
    norm = _normalize_text(text)
    return bool(_CART_ADD_CONFIRMATION_REGEX.search(norm))


def _last_outbound_was_summary(history: list[dict]) -> bool:
    """Rev. 103+ — True si el último outbound del bot ya fue un resumen.

    Detecta cualquiera de: emoji 📋, label `*Resumen*`, ó la línea
    `*TOTAL:` (presente solo en el resumen determinístico). Evita
    re-emitir resumen si el cliente ya lo vio (idempotencia).
    """
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").strip().lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        if "📋" in content:
            return True
        normalized = _normalize_text(content)
        if "*resumen" in normalized or "resumen de tu pedido" in normalized:
            return True
        return False  # primer outbound más reciente no era resumen
    return False


def _detect_shipping_location_change(text: str, history: list[dict]) -> Optional[str]:
    """Rev. 87 — Detecta intent de cambiar ubicación de envío post-cotización.

    "Ubicación" es deliberadamente amplio: cubre cambios de ciudad,
    departamento, o incluso una dirección específica dentro de la misma
    ciudad ("envíalo a la oficina en Bogotá") siempre que mencione una
    ciudad reconocible.

    Trigger:
        • Texto del cliente contiene frase de cambio de envío.
        • History reciente tiene al menos un outbound del bot con
          cotización previa (precios, transportadora).
        • Se menciona explícitamente una ciudad colombiana.

    Returns: nombre de ciudad detectada (Title Case) o None.

    Casos cubiertos:
        "cambia el envío a Medellín"            → "Medellín"
        "envíalo a la oficina en Cali"          → "Cali"
        "mejor a Bucaramanga"                    → "Bucaramanga"
        "ya no a Bogotá, mándalo a Pereira"      → "Pereira"
        "cambia la ubicación a Manizales"        → "Manizales"
    """
    if not text or not history:
        return None
    normalized = _normalize_text_simple(text).lower()

    # Frase de cambio (incluye ubicación / dirección, no solo "ciudad")
    change_phrases = (
        "cambia el envio", "cambiar el envio", "cambia envio",
        "cambia la ubicacion", "cambiar ubicacion", "cambia la direccion",
        "cambiar la direccion", "ya no a", "mejor a ", "mejor envia",
        "envia a ", "enviar a ", "envialo a ", "envialo en",
        "mandalo a", "mandar a ", "enviar mejor a",
        "cambia la ciudad", "cambiar ciudad",
    )
    if not any(phrase in normalized for phrase in change_phrases):
        return None

    # History debe tener cotización previa (precios o transportadora)
    has_prior_quote = False
    for msg in history[-10:]:
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text_simple(str(msg.get("content") or "")).lower()
        if any(k in content_norm for k in ("$", "transportadora", "envio:", "envio a ",
                                            "economica", "rapida", "servientrega",
                                            "deprisa", "coordinadora")):
            has_prior_quote = True
            break
    if not has_prior_quote:
        return None

    # Extraer ciudad mencionada. Si el cliente dice "ya no a Bogotá, mándalo
    # a Pereira", queremos Pereira (la última mencionada, no la primera).
    cities = (
        "bogota", "medellin", "cali", "barranquilla", "cartagena",
        "bucaramanga", "pereira", "manizales", "ibague", "santa marta",
        "cucuta", "monteria", "villavicencio", "pasto", "neiva", "armenia",
        "tunja", "popayan", "valledupar", "sincelejo", "riohacha",
    )
    last_match: Optional[str] = None
    last_pos = -1
    for city in cities:
        pos = normalized.rfind(city)
        if pos > last_pos:
            last_pos = pos
            last_match = city
    return last_match.title() if last_match else None


def _truncate_at_first_question(text: str) -> str:
    """Rev. 87 — Trunca el texto al primer signo de pregunta de cierre,
    pero conservando el bloque informativo previo.

    Política UX: el bot debe hacer 1 pregunta por turno para no abrumar.
    Si el LLM produjo "Listo, X. ¿A qué ciudad? ¿Qué presentación?"
    devolvemos solo "Listo, X. ¿A qué ciudad?" — la segunda pregunta
    se descarta porque será regenerada en el próximo turno cuando el
    cliente responda.

    Implementación: encuentra la primera "?" después de un signo "¿"
    o el primer "?" si no hay "¿" abridor. Trunca después.
    """
    if not text:
        return text
    # Buscar la primera pregunta completa (¿...? o ...?).
    closing_q = text.find("?")
    if closing_q < 0:
        return text
    # Conservar todo hasta e incluyendo la primera "?".
    truncated = text[: closing_q + 1].rstrip()
    # Si por algún motivo el corte deja la frase sin un signo de apertura
    # adecuado, devolver el original (mejor algo largo que algo roto).
    if not truncated:
        return text
    return truncated


def _detect_document_type_from_text(text: str) -> Optional[str]:
    """Sem 7 F2 cierre 2026-05-20 — P4 founder UAT (conv 7053666a):
    Detector determinístico de tipo de documento colombiano.

    Caso runtime motivador: cliente dijo "Cedula de Ciudadania" → LLM no
    extrajo `CC` → bot re-preguntó como si nada hubiera entendido.

    Reconoce variantes coloquiales típicas en español CO:
      • Cédula / Cedula / Cédula de Ciudadanía → CC
      • Cédula de Extranjería / Extranjeria → CE
      • NIT (también "RUT" mal usado) → NIT
      • Pasaporte / Passport → PP
      • Tarjeta de Identidad / TI → TI

    Returns: "CC" | "CE" | "NIT" | "PP" | "TI" | None.
    Defensa en profundidad: si LLM no extrajo, este detector cubre.
    """
    if not text:
        return None
    norm = _normalize_text_simple(text)
    # Orden importante: más específicos primero (extranjería antes que cédula).
    if "extranjeria" in norm or "cedula extranjera" in norm:
        return "CE"
    if "tarjeta de identidad" in norm or re.search(r"\bti\b", norm):
        return "TI"
    if "pasaporte" in norm or "passport" in norm:
        return "PP"
    if re.search(r"\bnit\b", norm) or re.search(r"\brut\b", norm):
        # Algunos clientes dicen "RUT" por error (es Chile/España). Asumimos NIT en CO.
        return "NIT"
    # "Cedula" cubre CC + "Cédula de Ciudadanía". Va al final por especificidad.
    if "cedula" in norm or re.search(r"\bcc\b", norm):
        return "CC"
    return None


def _detect_building_type_from_text(text: str) -> Optional[str]:
    """Rev. 86 — Si el LLM olvida setear building_type pero el cliente
    menciona explícitamente 'conjunto'/'torre'/'edificio'/'casa'/'oficina'
    en el texto, lo inferimos para que el FSM exija los campos correctos.

    Sem 7 F2 cierre 2026-05-19 — agrega 'oficina' como tipo descubrible.
    'oficina' tiene precedencia sobre 'edificio' cuando ambos están presentes
    ("oficina en el edificio Acme" → oficina).

    Returns: "conjunto" | "edificio" | "casa" | "oficina" | None
    """
    if not text:
        return None
    normalized = _normalize_text_simple(text)
    # Oficina primero — más específico (precedencia sobre edificio).
    if any(kw in normalized for kw in (
        "oficina", "mi trabajo", "en el trabajo", "lugar de trabajo",
        "donde trabajo", "horario laboral", "en horario de oficina",
        "la empresa", "en la empresa",
    )):
        return "oficina"
    if any(kw in normalized for kw in ("conjunto", "unidad residencial", "torres del", "torre ")):
        return "conjunto"
    if any(kw in normalized for kw in ("edificio", "apartamento", "apto ", "apto.", " apto", "piso ", "torre")):
        # "torre" sola es ambigua, pero si NO hay 'conjunto' en el texto,
        # asumimos edificio.
        return "edificio"
    if "casa" in normalized:
        return "casa"
    return None


def _detect_conjunto_type_from_text(text: str) -> Optional[str]:
    """Sem 7 F2 cierre 2026-05-19 — Detecta si un conjunto residencial
    es de torres o de casas. Solo se invoca cuando ya sabemos
    building_type='conjunto' pero falta el sub-tipo.

    Returns: "torres" | "casas" | None.
    """
    if not text:
        return None
    normalized = _normalize_text_simple(text)
    # Señales fuertes "casas":
    if any(kw in normalized for kw in (
        "conjunto de casas", "conjunto cerrado de casas",
        "casas del conjunto", "es de casas", "son casas",
        "casa #", "casa numero", "casa no", "mi casa es la",
    )):
        return "casas"
    # Señales fuertes "torres":
    if any(kw in normalized for kw in (
        "conjunto de torres", "torres del conjunto",
        "torre ", "bloque ", "torres y", "es de torres",
    )):
        return "torres"
    return None


# Rev. 104 (F1-2) — extraídos a fsm/address.py.
from fsm.address import (
    normalize_building_type as _normalize_building_type,
    normalize_conjunto_type as _normalize_conjunto_type,
    missing_address_fields as _missing_address_fields,
    has_real_address_data as _has_real_address_data,
)


def _merge_address_data(existing: Optional[dict], incoming: Optional[dict]) -> dict:
    merged: dict = {}
    if isinstance(existing, dict):
        merged.update(existing)
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            if value is None:
                continue
            if isinstance(value, str):
                cleaned = value.strip()
                if not cleaned:
                    continue
                merged[key] = cleaned
            else:
                merged[key] = value
    normalized_type = _normalize_building_type(merged.get("building_type"))
    if normalized_type:
        merged["building_type"] = normalized_type
    # Sem 7 F2 cierre — normalizar sub-tipo conjunto si viene presente.
    normalized_conjunto = _normalize_conjunto_type(merged.get("conjunto_type"))
    if normalized_conjunto:
        merged["conjunto_type"] = normalized_conjunto
    return merged


def _build_address_request_prompt(contact_record: dict, first_name: Optional[str]) -> str:
    """Rev. 92.d — Prompt de address diferenciado por tipo de vivienda.

    Sem 7 F2 cierre 2026-05-19 (Opción 1 SIMPLIFY):
      • `building_type` con 4 escenarios: casa, edificio, conjunto, oficina.
      • Para conjunto sin sub-tipo → pide clarificación torres/casas.
      • Para oficina → pide número de oficina (apartment) y menciona
        floor + nombre empresa como opcionales.

    Reglas:
      • Solo lista los OBLIGATORIOS faltantes (nunca pide lo ya dado).
      • Marca explícitamente cada faltante como obligatorio.
      • Sugiere OPCIONALES contextuales según tipo conocido (o
        condicionales si tipo aún se desconoce).
    """
    name_prefix = f", {first_name}" if first_name else ""
    address = contact_record.get("address") if isinstance(contact_record, dict) else None
    missing = _missing_address_fields(address)
    building_type = _normalize_building_type(
        (address or {}).get("building_type") if isinstance(address, dict) else None
    )

    # Address completa — defensivo.
    if not missing:
        return f"Listo{name_prefix}, ya tengo tu dirección de entrega."

    # Construir el bloque de obligatorios faltantes.
    lines = [f"Gracias{name_prefix}. Para completar la dirección de entrega me falta:"]
    for field in missing:
        lines.append(f"* *{field}* (obligatorio)")

    # Opcionales contextuales — depende del tipo conocido.
    optional_msg = ""
    if building_type == "casa":
        optional_msg = (
            "_Opcional_: punto de referencia "
            "(ej. portería, esquina cercana)."
        )
    elif building_type == "edificio":
        optional_msg = (
            "_Opcional_: piso, nombre del edificio, punto de referencia."
        )
    elif building_type == "oficina":
        optional_msg = (
            "_Opcional_: piso, nombre de la empresa, punto de referencia."
        )
    elif building_type == "conjunto":
        # Si es conjunto de casas, mencionar manzana/bloque como opcional
        # (reusa el campo `tower` semánticamente).
        from fsm.address import normalize_conjunto_type as _norm_ct
        _ct = _norm_ct((address or {}).get("conjunto_type"))
        if _ct == "casas":
            optional_msg = (
                "_Opcional_: manzana/bloque, nombre del conjunto, "
                "punto de referencia."
            )
        else:
            optional_msg = (
                "_Opcional_: nombre del conjunto, punto de referencia."
            )
    else:
        # Tipo aún se desconoce — sugerir condicionales sin pedir
        # lo que ya tenemos.
        optional_msg = (
            "_Opcional_ (según el tipo): nombre del edificio/conjunto/empresa, "
            "piso, o punto de referencia."
        )

    lines.append("")
    lines.append(optional_msg)
    return "\n".join(lines)


# Rev. 104 (F1-2) — extraído a fsm/. Wrappers preservan firma legacy del
# call-site (que pasa `history` y `carrier_selected_db` separados); el
# resolver puro toma `carrier_selected` ya combinado.
from fsm import resolver as _fsm_resolver
from fsm import _has_real_address_data as _fsm_has_real_address_data  # noqa: F401


def _determine_transactional_state(contact: dict) -> str:
    """Wrapper legacy → fsm.resolver.determine_transactional_state."""
    return _fsm_resolver.determine_transactional_state(contact)


def _resolve_display_state(
    *,
    contact_record: dict,
    history: Optional[list[dict]],
    buying_intent: bool,
    shipping_quoted: bool,
    carrier_selected_db: Optional[bool] = None,
) -> str:
    """Wrapper legacy: combina history + DB fallback antes de delegar al resolver puro.

    Mantiene la firma original (history + carrier_selected_db separados) para
    que los call-sites del orchestrator no requieran cambios. Internamente
    computa `carrier_selected` y `order_confirm_pending` y delega.
    """
    carrier_selected = (
        _has_carrier_been_selected(history or [])
        or bool(carrier_selected_db)
    )
    order_confirm_pending = _last_outbound_was_order_confirmation_question(
        history or []
    )
    return _fsm_resolver.resolve_display_state(
        contact_record=contact_record,
        buying_intent=buying_intent,
        shipping_quoted=shipping_quoted,
        carrier_selected=carrier_selected,
        order_confirm_pending=order_confirm_pending,
    )


def _fix_null_phone_in_summary(text: str, customer_phone: Optional[str]) -> str:
    """Rev. 103 — defensa final: reemplaza 'Celular: null' / 'None' por
    el phone real del WhatsApp del cliente cuando aparece en un resumen
    de pedido.

    Este post-process se ejecuta en el outbound antes de enviar a Meta.
    Cubre el caso donde el LLM compone el resumen y copia 'null' que vio
    en el contexto JSON (`contact_record.phone: null`), saltándose el
    override determinístico de `_build_order_summary_text`.

    Idempotente: si el outbound ya tiene un phone válido en la línea
    Celular, no toca.
    """
    if not text or "Resumen de tu pedido" not in text:
        return text
    if not customer_phone:
        return text
    formatted = _format_phone_for_summary(customer_phone)
    if not formatted:
        return text
    # Reemplazar "* Celular: null|None|undefined" (case insensitive) +
    # variantes con espacios extra. NO toca si ya hay un phone real.
    return re.sub(
        r"(\*\s*Celular:\s*)(?:null|none|undefined)\b",
        rf"\1{formatted}",
        text,
        flags=re.IGNORECASE,
    )


def _format_phone_for_summary(phone: Optional[str]) -> str:
    """Formatea el celular para mostrar en el resumen.

    El celular se captura automáticamente del WhatsApp (no se pide por chat),
    pero se muestra para que el cliente confirme que es el correcto antes
    de generar el link de pago. Envía y Wompi requieren este dato.
    """
    if not phone:
        return ""
    # Defensivo: rechazar cadenas como "null" / "none" / "undefined" que
    # pueden colarse desde JSON parseado o coerción str(None) en algún path.
    phone_str = str(phone).strip().lower()
    if phone_str in ("null", "none", "undefined", ""):
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    if digits.startswith("57") and len(digits) == 12:
        return f"+57 {digits[2:5]} {digits[5:8]} {digits[8:]}"
    if len(digits) == 10:
        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return f"+{digits}" if not str(phone).startswith("+") else str(phone)


def _format_address_for_summary(address: Optional[dict]) -> str:
    """Renderiza la dirección persistida en una sola línea legible para el resumen.

    Sem 7 F2 cierre 2026-05-19 (Opción 1 SIMPLIFY) — render condicional según
    `building_type`:
      • casa → solo street + barrio + city.
      • edificio → + "Piso X" (si floor) + "Apto Y".
      • conjunto torres → + complex + "Torre X" + "Apto Y".
      • conjunto casas → + complex + "Casa #Y" (sin torre).
      • oficina → + "Piso X" (si floor) + "Oficina Y" + "(Empresa: Z)" si company_name.
    """
    if not isinstance(address, dict):
        return ""
    parts: list[str] = []
    street = str(address.get("street") or "").strip()
    if street:
        parts.append(street)
    btype = _normalize_building_type(address.get("building_type"))
    ctype = _normalize_conjunto_type(address.get("conjunto_type"))
    floor = str(address.get("floor") or "").strip()
    company = str(address.get("company_name") or "").strip()

    sub_parts: list[str] = []
    if btype == "conjunto":
        tower = str(address.get("tower") or "").strip()
        apt = str(address.get("apartment") or "").strip()
        complex_name = str(address.get("complex_name") or "").strip()
        if complex_name:
            sub_parts.append(complex_name)
        if ctype == "casas":
            # Sem 7 F2 cierre 2026-05-20 (D4) — manzana opcional en
            # conjunto de casas. Reusa `tower` semánticamente como
            # "Manzana / Bloque". Sin migración de schema.
            if tower:
                _tlow = tower.lower()
                if _tlow.startswith("manzana") or _tlow.startswith("bloque"):
                    sub_parts.append(tower)
                else:
                    sub_parts.append(f"Manzana {tower}")
            if apt:
                sub_parts.append(f"Casa #{apt}")
        else:
            if tower:
                sub_parts.append(f"Torre {tower}" if not tower.lower().startswith("torre") else tower)
            if apt:
                sub_parts.append(f"Apto {apt}")
    elif btype == "edificio":
        apt = str(address.get("apartment") or "").strip()
        complex_name = str(address.get("complex_name") or "").strip()
        if complex_name:
            sub_parts.append(complex_name)
        if floor:
            sub_parts.append(f"Piso {floor}")
        if apt:
            sub_parts.append(f"Apto {apt}")
    elif btype == "oficina":
        apt = str(address.get("apartment") or "").strip()
        if floor:
            sub_parts.append(f"Piso {floor}")
        if apt:
            sub_parts.append(f"Oficina {apt}")
    if sub_parts:
        parts.append(", ".join(sub_parts))
    neighborhood = str(address.get("neighborhood") or "").strip()
    if neighborhood:
        parts.append(neighborhood)
    city = str(address.get("city") or "").strip()
    if city:
        parts.append(city)

    base = " — ".join(parts)
    if btype == "oficina" and company:
        return f"{base} _(Empresa: {company})_"
    return base


def _verified_ctx_from_cart(cart: dict) -> Optional[dict]:
    """Rev. 80: convierte el cart en DB (output de cart_tool.get_cart_with_items)
    al schema de verified_ctx que espera _build_order_summary_text.

    Rev. 103 — `requires_requote=True` (set por add_item/remove_item) NO
    invalida el cart como fuente de verdad de ITEMS. Solo significa que
    `cart.shipping_cents` está stale — el caller debe extraer el shipping
    actual desde history. Antes (rev. 80) retornaba None y el caller
    caía a inferencia desde history truncado → alucinación de productos.
    Razón: cart-as-SoT debe mantenerse independiente del estado
    shipping; los items son verdad incluso si el envío necesita re-quote.

    Devuelve None solo si cart vacío.
    """
    if not cart:
        return None
    items = cart.get("items") or []
    if not items:
        return None
    subtotal = int(cart.get("subtotal_cents") or 0)
    # Rev. 103 — si requires_requote, ignorar shipping del cart (se
    # extrae de history en caller). Items y subtotal SIEMPRE válidos.
    if cart.get("requires_requote"):
        shipping = 0
    else:
        shipping = int(cart.get("shipping_cents") or 0)
    total = int(cart.get("total_cents") or (subtotal + shipping))
    out_items = []
    for it in items:
        v = it.get("variation") or {}
        p = it.get("product") or {}
        title = p.get("title") or p.get("name") or "Producto"
        variant_label = v.get("label") or v.get("presentation") or ""
        out_items.append({
            "variation_id": it.get("variation_id"),
            "product_id": it.get("product_id"),
            "title": title,
            "variant_label": variant_label,
            "quantity": int(it.get("quantity") or 1),
            "unit_price_cents": int(it.get("unit_price_cents") or 0),
        })
    # Sem 6 I.2.7 — propagar cupón aplicado para que el resumen lo muestre.
    coupon_code = cart.get("coupon_code")
    discount_cents = int(cart.get("discount_cents") or 0)
    return {
        "items": out_items,
        "subtotal_cents": subtotal,
        "shipping_cost_cents": shipping,
        "total_cents": total,
        "coupon_code": coupon_code,
        "discount_cents": discount_cents,
        "_source": "cart_db",
    }


def _build_order_summary_text(
    *,
    contact_record: dict,
    verified_ctx: Optional[dict],
    catalog: Optional[list] = None,
    history: Optional[list[dict]] = None,
    cart_from_db: Optional[dict] = None,
    supabase: Any = None,
    tenant_id: Optional[str] = None,
) -> Optional[str]:
    """Resumen estructurado determinístico antes de la confirmación final.

    Rev. 80 — Prioridad de fuentes:
      1. cart_from_db (DB SoT) si tiene items y NO requiere recotización.
      2. verified_ctx provisto por el caller.
      3. Fallback: history-parsing (DEPRECATED rev. 80, queda como red de
         seguridad cuando el cart-en-DB no está disponible).

    Si no hay contexto verificable retorna None y dejamos que el LLM
    componga el mensaje (degradación segura).
    """
    if not verified_ctx and cart_from_db:
        verified_ctx = _verified_ctx_from_cart(cart_from_db)
        # Rev. 103 — si cart tiene items pero shipping=0 (requires_requote),
        # extraer shipping del history para no mostrar "Envío: $0".
        if verified_ctx and not verified_ctx.get("shipping_cost_cents"):
            _ship_hist = _extract_shipping_cost_from_history(history or []) or 0
            if _ship_hist > 0:
                verified_ctx["shipping_cost_cents"] = _ship_hist
                verified_ctx["total_cents"] = (
                    int(verified_ctx.get("subtotal_cents") or 0) + _ship_hist
                )
    if not verified_ctx:
        # Rev. 103 — fallback eliminado. Si no hay cart real, retornar None
        # para que el LLM componga (con LIE_PHRASES guard) en vez de
        # inventar productos del catálogo. El populate-on-demand fue
        # source of hallucinations (caso real conv 32e0397e: cliente pidió
        # Coco 60g → orden con "Aceite Esencial de Árbol de Té").
        return None
    if not verified_ctx.get("total_cents"):
        return None

    items = verified_ctx.get("items")
    lines: list[str] = ["📋 *Resumen de tu pedido:*", ""]
    if isinstance(items, list) and items:
        lines.append("*Productos:*")
        for it in items:
            qty = int(it.get("quantity") or 1)
            title = str(it.get("title") or "Producto").strip()
            variant = str(it.get("variant_label") or "").strip()
            line_total = int(it.get("unit_price_cents") or 0) * qty
            label = f"• {qty}x {title}"
            if variant and variant.lower() not in {"estandar", "estándar"}:
                label += f" ({variant})"
            label += f": {_format_cop(line_total)}"
            lines.append(label)
    else:
        title = str(verified_ctx.get("product_name") or "Producto")
        variant = str(verified_ctx.get("variant_label") or "").strip()
        qty = int(verified_ctx.get("quantity") or 1)
        line_total = int(verified_ctx.get("unit_price_cents") or 0) * qty
        label = f"• {qty}x {title}"
        if variant and variant.lower() not in {"estandar", "estándar"}:
            label += f" ({variant})"
        label += f": {_format_cop(line_total)}"
        lines.append("*Productos:*")
        lines.append(label)

    subtotal = int(verified_ctx.get("subtotal_cents") or 0)
    shipping = int(verified_ctx.get("shipping_cost_cents") or 0)
    total = int(verified_ctx.get("total_cents") or 0)
    # Sem 6 I.2.7 (ADR-0015) — descuento de cupón.
    discount = int(verified_ctx.get("discount_cents") or 0)
    coupon_code = verified_ctx.get("coupon_code")
    lines.append("")
    lines.append(f"Subtotal: {_format_cop(subtotal)}")
    # Rev. 103 — incluir carrier en línea de envío para que el cliente
    # vea qué transportadora cotizó (Económica = default cuando dice
    # "sigamos" sin elegir explícitamente).
    #
    # Sem 7 F2 cierre 2026-05-20 — Bug P9 founder UAT (conv 7053666a):
    # En conversaciones largas (≥25 msgs), el outbound de cotización queda
    # FUERA del window de history → extractor retorna None → resumen
    # muestra "Envío: $X" sin carrier (regresión visual).
    # Fix: usar `cart_from_db.shipping_meta.carrier` como FUENTE PRIMARIA
    # (cart-as-SoT, ADR-0011) y caer a history solo si DB no tiene.
    carrier_name: Optional[str] = None
    if isinstance(cart_from_db, dict):
        _meta = cart_from_db.get("shipping_meta") or {}
        if isinstance(_meta, dict):
            _carrier_db = str(_meta.get("carrier") or "").strip()
            _service_db = str(_meta.get("service_level") or "").strip()
            if _carrier_db:
                # Componer "Coordinadora Ground" o "FedEx Express®" con
                # service_level si está disponible.
                carrier_name = (
                    f"{_carrier_db} {_service_db}".strip()
                    if _service_db else _carrier_db
                )
    if not carrier_name:
        carrier_name = _extract_shipping_carrier_from_history(history or [])
    if carrier_name and shipping > 0:
        lines.append(f"Envío (Económica - {carrier_name}): {_format_cop(shipping)}")
    else:
        lines.append(f"Envío: {_format_cop(shipping)}")
    if discount > 0 and coupon_code:
        lines.append(f"Descuento: -{_format_cop(discount)} ({coupon_code})")
    lines.append(f"*TOTAL: {_format_cop(total)}*")

    contact = contact_record if isinstance(contact_record, dict) else {}
    name = str(contact.get("name") or "").strip()
    email = str(contact.get("email") or "").strip()
    phone = _format_phone_for_summary(contact.get("phone"))
    # Rev. 103 — phone alternativo de envío. Solo se muestra si difiere
    # del WhatsApp (caso "compro para otra persona").
    shipping_phone_raw = contact.get("shipping_phone")
    shipping_phone = _format_phone_for_summary(shipping_phone_raw)
    has_alternate_phone = bool(shipping_phone) and shipping_phone != phone
    doc_t = str(contact.get("document_type") or "").strip().upper()
    doc_n = str(contact.get("document_number") or "").strip()
    address_line = _format_address_for_summary(contact.get("address"))

    if any([name, email, phone, doc_t and doc_n, address_line]):
        lines.append("")
        lines.append("*Datos de envío:*")
        if name:
            lines.append(f"• Nombre: {name}")
        if email:
            lines.append(f"• Correo: {email}")
        if phone:
            if has_alternate_phone:
                # Cliente dio shipping alternativo — diferenciar ambos.
                lines.append(f"• Celular (WhatsApp): {phone}")
                lines.append(f"• Celular (envío): *{shipping_phone}*")
            else:
                lines.append(f"• Celular: {phone}")
        if doc_t and doc_n:
            lines.append(f"• Documento: {doc_t} {doc_n}")
        if address_line:
            lines.append(f"• Dirección: {address_line}")

    # ── Rev. 108 holístico — texto adaptado a payment_method del cart ────
    # Si cart_from_db.payment_method == 'cod':
    #   • Mensaje "Pagas $X al recibir" en lugar de "link de pago"
    #   • Warning condicional si carrier.charges_return_fee=true (dossier
    #     §7.2: ENVIA y COORDINADORA cobran costo devolución).
    is_cod_order = False
    carrier_charges_return = False
    if isinstance(cart_from_db, dict):
        is_cod_order = (
            (cart_from_db.get("payment_method") or "credit").lower() == "cod"
        )
        if is_cod_order and carrier_name and supabase is not None and tenant_id:
            try:
                from lib.carrier_capabilities import (
                    get_effective_carrier_capability,
                )
                # carrier_name puede tener service_level concatenado;
                # extraer primer token (ej. "SERVIENTREGA Mensajería" → "SERVIENTREGA")
                _carrier_pure = (carrier_name.split() or [""])[0]
                _cap = get_effective_carrier_capability(
                    supabase,
                    tenant_id=tenant_id,
                    carrier_name=_carrier_pure,
                )
                carrier_charges_return = _cap.charges_return_fee
            except Exception:
                # Fallback: no warning — log silent.
                carrier_charges_return = False

    lines.append("")
    if is_cod_order:
        lines.append(f"💵 Pagarás *{_format_cop(total)}* en efectivo al recibir tu pedido.")
        if carrier_charges_return:
            lines.append("")
            _carrier_short = (carrier_name or "el courier").split()[0] if carrier_name else "el courier"
            lines.append(
                f"⚠️ *Aviso de devolución*: si rechazas el pedido al recibir, "
                f"{_carrier_short} cobra costo de devolución (a tu cargo, "
                f"~$5.000 estimado)."
            )
        lines.append("")
        lines.append("¿Confirmas tu pedido?")
    else:
        lines.append("¿Confirmas que los datos están correctos para generar tu link de pago?")
    return "\n".join(lines)


def _build_next_data_request_prompt(contact_record: dict) -> str:
    state = _determine_transactional_state(contact_record)
    first_name = _extract_first_name(contact_record.get("name") if isinstance(contact_record, dict) else None)
    name_prefix = f", {first_name}" if first_name else ""
    if state == "NEEDS_CONSENT":
        # Rev. 89.b + 91 — UX cordial cumpliendo Habeas Data Colombia
        # (Ley 1581/2012). Cierre con "*SÍ* o *NO*" para que
        # la respuesta esperada sea inequívoca (S9 fix).
        return (
            "¡Perfecto! Voy a continuar con tu pedido. Con tu "
            "autorización te pediré algunos datos (nombre, dirección, "
            "etc.) para esta compra y futuros pedidos.\n\n"
            "Si en algún momento quieres que los borre, solo dímelo. \n\n"
            "¿Estás de acuerdo? *SÍ* o *NO*."
        )
    if state == "NEEDS_EMAIL":
        return f"¡Perfecto{name_prefix}! ¿Cuál es tu correo electrónico?"
    if state == "NEEDS_NAME":
        return "Gracias. Para continuar, compárteme tu nombre completo."
    if state == "NEEDS_DOCUMENT":
        # Sem 7 F2 cierre 2026-05-19 — Bug 1 founder UAT: prompt contextual.
        # Si el cliente ya dio el tipo en un turno previo (persistido como
        # partial), pedir SOLO el número. Evita que el bot re-pregunte
        # ambos como si nada hubiera avanzado.
        _doc_type_actual = str(
            (contact_record or {}).get("document_type") or ""
        ).strip().upper()
        _doc_num_actual = str(
            (contact_record or {}).get("document_number") or ""
        ).strip()
        if _doc_type_actual and not _doc_num_actual:
            return (
                f"Gracias{name_prefix}. Tengo registrado tu tipo de documento "
                f"como *{_doc_type_actual}*. Ahora compárteme el número, por favor."
            )
        if _doc_num_actual and not _doc_type_actual:
            return (
                f"Gracias{name_prefix}. Tengo el número de documento. "
                "¿Qué tipo es: Cédula (CC), Cédula de extranjería (CE), "
                "NIT, Pasaporte (PP) o Tarjeta de identidad (TI)?"
            )
        # Caso inicial: ambos vacíos. Pedir ambos en una sola pregunta
        # pero aceptar respuesta parcial (el LLM/extractor persiste lo
        # que venga y este prompt re-itera con contexto en el próximo turno).
        return (
            "Para procesar tu pago, necesito tu documento de identidad. "
            "¿Qué tipo es: Cédula (CC), Cédula de extranjería (CE), NIT, Pasaporte (PP) o Tarjeta de identidad (TI)? "
            "Después indícame el número, por favor."
        )
    if state == "NEEDS_DIRECTION":
        return _build_address_request_prompt(contact_record, first_name)
    if state == "READY_FOR_SUMMARY":
        return "Perfecto. Ya tengo tus datos, ¿confirmas que procedamos con el resumen final del pedido?"
    return "Listo. ¿Me confirmas los datos para continuar con tu pedido?"


# Rev. 91 — Conductor único del checkout form. Reemplaza la lógica
# fragmentada de SAFETY_NET + FSM POST hard-lock por un punto de
# decisión explícito (patrón Rasa Forms / Bot Framework Dialogs).
# La instancia se construye una sola vez por proceso porque las
# dependencias inyectadas son funciones puras del módulo.
_CHECKOUT_FORM_CONDUCTOR = CheckoutFormConductor(
    determine_state=_determine_transactional_state,
    build_prompt=_build_next_data_request_prompt,
    build_address_prompt=_build_address_request_prompt,
    extract_first_name=_extract_first_name,
    merge_address=_merge_address_data,
    detect_building_type=_detect_building_type_from_text,
    missing_address_fields=_missing_address_fields,
)


def _is_affirmative_confirmation(text: str) -> bool:
    """True si el inbound es confirmación afirmativa pura.

    Rev. 104 (F0-5 / BUG-4): el detector NO debe interpretar como afirmativo
    un mensaje que contiene un token telefónico (10 dígitos consecutivos o
    frase "celular es"/"número alterno"). Caso: cliente conocido tras resumen
    dice "el pedido lo recibe mi mamá, su celular es 3225551234". Sin guard,
    se interpretaba como afirmativo → bypass payment_link → phone alterno
    nunca extraído. Con guard, cae al LLM que extrae `extracted_shipping_phone`.
    """
    raw = str(text or "")
    # Guard 1: token telefónico explícito (10 dígitos consecutivos).
    if re.search(r"\b\+?5?7?\s?\d{10}\b", raw):
        return False
    # Guard 2: frases que mencionan celular/número alterno (intent update PII).
    raw_norm = _normalize_text(raw)
    _phone_intent_phrases = (
        "celular es", "celular alterno", "celular alternativo",
        "celular para envio", "celular para envío",
        "numero alterno", "número alterno",
        "numero alternativo", "número alternativo",
        "lo recibe", "el pedido lo recibe",
        "cambiar el celular", "actualizar el celular",
        "actualiza mi celular", "actualizar mi celular",
    )
    if any(p in raw_norm for p in _phone_intent_phrases):
        return False

    normalized = _normalize_text_simple(text)
    if not normalized:
        return False
    tokens = [tok for tok in re.split(r"\s+", normalized) if tok]
    if not tokens:
        return False
    token_set = set(tokens)
    if token_set & _NEGATIVE_CONFIRMATION_TOKENS:
        return False
    if token_set & _AFFIRMATIVE_CONFIRMATION_TOKENS:
        return True
    return any(phrase in normalized for phrase in ("si confirmo", "si, confirmo", "crear pedido", "procedamos"))


def _extract_shipping_cost_from_history(history: list[dict]) -> Optional[int]:
    """
    Extrae el costo de envío en centavos del último outbound de cotización en el historial.
    Busca patrones como '$12.000 COP', '$12,000', '12000'.
    Retorna None si no encuentra o no puede parsear.
    """
    _price_pattern = re.compile(r"\$\s*([\d.,]+)\s*(?:COP)?", re.IGNORECASE)
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        content_norm = _normalize_text(content)
        if "economica" not in content_norm and "rapida" not in content_norm:
            continue
        # Encontrado: extraer primer precio de la línea "Económica"
        for line in content.splitlines():
            if "Económica" in line or "Economica" in line or "economica" in _normalize_text(line):
                matches = _price_pattern.findall(line)
                for raw in matches:
                    cleaned = raw.replace(".", "").replace(",", "")
                    try:
                        value = int(cleaned)
                        if value >= 1000:  # mínimo $10 COP en centavos
                            return value * 100  # convertir pesos → centavos
                    except ValueError:
                        continue
    return None


def _extract_shipping_cost_from_db(
    supabase: Client, conversation_id: str,
) -> Optional[int]:
    """Rev. 103 — DB fallback de `_extract_shipping_cost_from_history`.

    Razón: el `history` en memoria está limitado a CONVERSATION_HISTORY_LIMIT=25.
    En convs largas (caso real conv c765ea4d con 45 msgs), la cotización
    quedó en msg #8 → fuera del window → resumen mostraba "Envío: $0 COP"
    aunque el panel del Inbox correctamente mostraba $7.310.

    Estrategia: query directo a `messages` de toda la conversación,
    buscando el outbound más reciente con marker "Económica". Sin límite.
    """
    if not conversation_id:
        return None
    _price_pattern = re.compile(r"\$\s*([\d.,]+)\s*(?:COP)?", re.IGNORECASE)
    try:
        res = (
            supabase.table("messages")
            .select("content")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("direction", "outbound")
            .ilike("content", "%conómica%")
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        for row in (res.data or []):
            content = str(row.get("content") or "")
            for line in content.splitlines():
                if "Económica" in line or "Economica" in line:
                    matches = _price_pattern.findall(line)
                    for raw in matches:
                        cleaned = raw.replace(".", "").replace(",", "")
                        try:
                            value = int(cleaned)
                            if value >= 1000:
                                return value * 100
                        except ValueError:
                            continue
    except Exception as exc:
        logger.warning(
            "[SHIP_HIST_DB] error extrayendo shipping conv=%s: %s",
            conversation_id, exc,
        )
    return None


def _extract_shipping_carrier_from_history(history: list[dict]) -> Optional[str]:
    """Rev. 103 — extrae el carrier de la opción Económica del último
    outbound de cotización. Caso real: el cliente que dice "sigamos" tras
    una cotización multi-opción defaultea a Económica; el resumen y el
    DB necesitan saber QUÉ carrier es para que la transportadora
    reciba la guía correcta.

    Formatos soportados (continúa buscando hacia atrás si el primer
    outbound con "Económica" no matchea — ej. carrier ack post-quote):
      • Cotización: "* *Económica*: Coordinadora Ground | $7.310 | ..."
      • Carrier ack: "voy con la opción *Económica* (Coordinadora Ground) por ..."
    Retorna ej. "Coordinadora Ground" o None.
    """
    _patterns = (
        # Cotización con `|` separators
        re.compile(r"(?:Económica|Economica)\*?:?\s*([^|]+?)\s*\|"),
        # Ack con paréntesis
        re.compile(r"(?:Económica|Economica)\*?\s*\(([^)]+)\)"),
    )
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        if "Económica" not in content and "Economica" not in content:
            continue
        for line in content.splitlines():
            if "Económica" not in line and "Economica" not in line:
                continue
            for pat in _patterns:
                m = pat.search(line)
                if m:
                    name = m.group(1).strip().strip("*").strip()
                    if name and 2 <= len(name) <= 60:
                        return name
        # No match en este outbound — sigue buscando hacia atrás (NO return None aquí).
    return None


async def _persist_cart_shipping_if_needed(
    *,
    supabase: Client,
    conversation_id: str,
    tenant_id: str,
    history: list[dict],
) -> None:
    """Rev. 103/104 — Cart-as-SoT: persiste shipping al cart cuando carrier
    está seleccionado pero `cart.shipping_cents` aún es 0 o el cart está
    en `requires_requote=True`.

    Política de fuentes (en orden de preferencia, ADR-0011 §6.5):
      1. Si `requires_requote=True` (cliente modificó cart post-cotización),
         intentar **recotización lazy** contra Envia con peso/dims actuales.
         Eso garantiza que el shipping refleja el cart real, no la
         cotización vieja del history (que estaría stale tras add_item).
      2. Si recotización falla o `requires_requote=False`, fallback al
         shipping del history (o DB) — comportamiento legacy.

    Sin paso (1) los re-usos del shipping del history producían que el
    link Wompi nuevo (post-modificación cart) cobrara el shipping viejo
    aunque el peso/dims hubieran cambiado → pérdida silenciosa de margen.

    Idempotente: si el cart ya tiene shipping correcto y NO requires_requote,
    no toca. Best-effort: si todo falla, log warning y no bloquea.
    """
    try:
        from tools.cart_tool import get_cart_with_items, set_shipping_meta
    except Exception as exc:  # pragma: no cover
        logger.warning("[CART_SYNC] import falló: %s", exc)
        return
    try:
        cart = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning("[CART_SYNC] get_cart falló conv=%s: %s", conversation_id[:8], exc)
        return
    if not cart or not (cart.get("items") or []):
        return
    current_shipping = int(cart.get("shipping_cents") or 0)
    requires_requote = bool(cart.get("requires_requote"))
    if current_shipping > 0 and not requires_requote:
        return  # ya sincronizado

    # Preservar city del cart (Plan A.0.1: cart-as-SoT).
    # El shipping_quote_tool persiste city al cart en cuanto la resuelve
    # (vía _persist_destination_city_to_cart), así que `_city` debe estar
    # poblada en este punto si hubo cotización previa exitosa.
    _meta = cart.get("shipping_meta") or {}
    _city = (_meta.get("city") or "").strip()

    # Paso 1 (ADR-0011 §6.5) — recotización lazy si requires_requote.
    if requires_requote:
        try:
            from tools.shipping_quote_tool import requote_shipping_for_cart
            requote = await requote_shipping_for_cart(
                supabase, tenant_id=tenant_id, conversation_id=conversation_id,
            )
            if requote and int(requote.get("shipping_cents", 0)) > 0:
                set_shipping_meta(
                    supabase,
                    cart_id=cart["id"],
                    tenant_id=tenant_id,
                    carrier=requote["carrier_name"],
                    service_level=requote["service_level"],
                    shipping_cents=int(requote["shipping_cents"]),
                    city=requote.get("city") or _city or None,
                    rate_id=requote.get("rate_id"),
                )
                logger.info(
                    "[CART_SYNC] cart=%s shipping=%s carrier=%s service=%s "
                    "RECOTIZADO (requires_requote=True)",
                    cart["id"][:8], requote["shipping_cents"],
                    requote["carrier_name"], requote["service_level"],
                )
                return
            logger.warning(
                "[CART_SYNC] recotización lazy retornó None — fallback a history conv=%s",
                conversation_id[:8],
            )
        except Exception as exc:
            logger.warning(
                "[CART_SYNC] recotización lazy excepción: %s — fallback a history",
                exc,
            )

    # Paso 2 — fallback al shipping del history (comportamiento legacy).
    ship_cents = _extract_shipping_cost_from_history(history) or 0
    if ship_cents <= 0:
        ship_cents = _extract_shipping_cost_from_db(supabase, conversation_id) or 0
    if ship_cents <= 0:
        return  # no hay cotización conocida — nada que persistir
    carrier_name = _extract_shipping_carrier_from_history(history) or "Coordinadora"

    try:
        set_shipping_meta(
            supabase,
            cart_id=cart["id"],
            tenant_id=tenant_id,
            carrier=carrier_name,
            service_level="Económica",
            shipping_cents=ship_cents,
            city=_city or None,
        )
        logger.info(
            "[CART_SYNC] cart=%s shipping=%s carrier=%s city=%s persistido (history fallback)",
            cart["id"][:8], ship_cents, carrier_name, _city or "?",
        )
    except Exception as exc:
        logger.warning("[CART_SYNC] set_shipping_meta falló: %s", exc)


def _generic_catalog_terms(catalog: list) -> set[str]:
    """Rev. 103 — términos compartidos por ≥40% del catálogo, no
    discriminativos. Caso real: catálogo de cosmética con 5 jabones todos
    tienen "jabon" + "artesanal" en el título. El matcher por overlap >=2
    atrapaba toda la categoría cuando el cliente solo nombraba 1 producto.
    """
    if not catalog:
        return set()
    _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}
    counts: dict[str, int] = {}
    n = 0
    for prod in catalog:
        title = str(prod.get("title") or "").strip()
        if not title:
            continue
        n += 1
        words = set(re.findall(r"[a-z0-9ñ]+", _normalize_text(title))) - _stop
        for w in words:
            counts[w] = counts.get(w, 0) + 1
    if n < 3:
        # Catálogo pequeño: nada se considera genérico.
        return set()
    threshold = max(2, int(n * 0.4))
    return {w for w, c in counts.items() if c >= threshold}


def _category_head_words(catalog: list) -> set[str]:
    """Sem 7 F2 cierre — primer token significativo (>=3 chars, no stop) de
    cada título. Esto identifica el SUSTANTIVO DE CATEGORÍA (ej. "jabon" en
    "Jabón Artesanal de Coco", "aceite" en "Aceite de Coco Virgen"). Útil
    para preferir el sustantivo de categoría sobre adjetivos comunes
    ("artesanal") al detectar el contexto declarado por el cliente.
    """
    _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}
    heads: set[str] = set()
    for prod in catalog:
        title = str(prod.get("title") or "").strip()
        if not title:
            continue
        tokens = re.findall(r"[a-z0-9ñ]+", _normalize_text(title))
        for t in tokens:
            if len(t) >= 3 and t not in _stop:
                heads.add(t)
                break  # primera palabra significativa solamente
    return heads


def _extract_category_token_from_recent_context(
    history: list[dict],
    catalog: list,
    max_lookback: int = 5,
) -> Optional[str]:
    """Sem 7 F2 cierre 2026-05-19 — Extrae el token de categoría declarado
    en el contexto conversacional reciente (Bug 2 founder UAT manual).

    Caso runtime motivador (conv b36ecb31):
      T5 cliente: "Que jabones artesanales venden?"   ← declara "jabones"
      T6 bot:    lista 4 jabones específicos          ← framing jabón
      T7 cliente: "Me peudes vender 1 Jabon de Cogo..." ← declara "jabón"
      T8 bot:    "Confírmame la presentación de cada jabón"
      T9 cliente: "Ok, deseo 1 de Coco 100g y 1 de Lavanda 150g"
        ← NO declara "jabón" pero el contexto sigue siendo jabón.

    Estrategia:
      1. `category_head_words` (primer token significativo de cada título)
         identifica los SUSTANTIVOS de categoría (ej. "jabon", "aceite").
         Se prefiere sobre `generic_terms` para evitar matchear adjetivos
         comunes como "artesanal" que aparecen pluri-categóricamente.
      2. Fallback: `generic_terms` si head_words no matchea.
      3. Iterar últimos `max_lookback` mensajes desde el más reciente.

    Returns: token de categoría o None si no se identifica framing.
    """
    if not history or not catalog:
        return None
    head_words = _category_head_words(catalog)
    generic_terms = _generic_catalog_terms(catalog) if head_words else set()
    if not head_words and not generic_terms:
        return None
    # Iterar de más reciente a más viejo.
    for msg in reversed(history[-max_lookback:]):
        content = str(msg.get("content") or "")
        if not content:
            continue
        norm = _normalize_text(content)
        tokens = re.findall(r"[a-zñ]+", norm)  # lista preserva orden
        # PASS 1: priorizar head_words (sustantivos de categoría).
        for token in tokens:
            if token in head_words:
                return token
            if token.endswith("es") and token[:-2] in head_words:
                return token[:-2]
            if token.endswith("s") and token[:-1] in head_words:
                return token[:-1]
        # PASS 2: fallback a generic_terms si head_words no matchea.
        for token in tokens:
            if token in generic_terms:
                return token
            if token.endswith("es") and token[:-2] in generic_terms:
                return token[:-2]
            if token.endswith("s") and token[:-1] in generic_terms:
                return token[:-1]
    return None


def _filter_catalog_by_category_token(
    catalog: list, category_token: Optional[str],
) -> list:
    """Sem 7 F2 cierre 2026-05-19 — Filtra el catalog dejando solo productos
    cuyo título contiene `category_token`. Pure, sin side effects.

    Si `category_token` es None o vacío → retorna catalog completo (no-op).
    Si el filtro deja 0 productos → retorna catalog completo (back-compat).
    """
    if not category_token or not catalog:
        return catalog
    token_norm = _normalize_text(category_token).strip()
    if not token_norm:
        return catalog
    filtered = []
    for prod in catalog:
        title_norm = _normalize_text(str(prod.get("title") or ""))
        # Match por palabra completa (token está en tokens del título).
        title_tokens = set(re.findall(r"[a-zñ]+", title_norm))
        if token_norm in title_tokens:
            filtered.append(prod)
    return filtered if filtered else catalog


def _build_verified_multi_product_context(
    catalog: list,
    history: list[dict],
) -> Optional[dict]:
    """Variante multi-producto: detecta 2+ productos con cantidad explícita en
    history (ej "2 aceites de coco y 1 sérum") y suma subtotales de cada uno
    a su variante específica. Devuelve None si no hay multi-producto.
    """
    if not catalog or not history:
        return None
    full_text = ""
    for msg in history[:25]:
        if str(msg.get("direction") or "").lower() == "inbound":
            full_text += " " + str(msg.get("content") or "")
    norm = _normalize_text(full_text)
    norm_tokens_set = set(re.findall(r"[a-z0-9ñ]+", norm))
    _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}

    # Rev. 103 — palabras genéricas compartidas por toda una categoría
    # (ej. "jabon"/"artesanal" están en todos los jabones del catálogo).
    # Si el cliente solo dijo "1 jabón artesanal de coco", el matcher por
    # overlap >=2 también atrapaba Lavanda/Avena/Menta — bug grave en
    # populate-on-demand del cart.
    _generic_terms = _generic_catalog_terms(catalog)

    items_summary: list[dict] = []
    seen_titles: set[str] = set()
    has_explicit_qty = False
    for prod in catalog:
        title = str(prod.get("title") or "").strip()
        if not title:
            continue
        norm_title = _normalize_text(title)
        if norm_title in seen_titles:
            continue
        title_words = set(re.findall(r"[a-z0-9ñ]+", norm_title)) - _stop
        # Discriminantes = palabras del título que NO son genéricas
        # de la categoría. Para "Jabón Artesanal de Coco" → {coco};
        # para "Aceite de Coco Virgen" → {aceite, coco, virgen}.
        # Requerimos que TODAS las discriminativas estén en el texto
        # del cliente — un solo "coco" en el inbound NO debe matchear
        # tanto Jabón-Coco como Aceite-Coco.
        discriminative = title_words - _generic_terms
        if norm_title in norm:
            pass
        elif discriminative and discriminative.issubset(norm_tokens_set):
            pass
        else:
            continue
        seen_titles.add(norm_title)
        # Cantidad cerca del título
        sig_tokens = [t for t in title_words if len(t) > 3]
        qty = 1
        explicit = False
        if sig_tokens:
            pat = r"(\d+)\s+(?:[a-zñáéíóú]+s?\s+){0,3}(" + "|".join(re.escape(t) for t in sig_tokens) + ")"
            m = re.search(pat, norm)
            if m:
                try:
                    qty = int(m.group(1))
                    explicit = True
                except ValueError:
                    pass
        # Variante específica
        variants = prod.get("variants") or []
        chosen_var = None
        for v in variants:
            attrs = v.get("attributes") or {}
            if not isinstance(attrs, dict):
                continue
            for av in attrs.values():
                av_n = _normalize_text(str(av or "")).strip()
                if av_n and av_n in norm:
                    chosen_var = v
                    break
            if chosen_var:
                break
        if not chosen_var and variants:
            chosen_var = min(
                (v for v in variants if (v.get("stock") or 0) > 0 and v.get("price")),
                key=lambda v: float(v.get("price") or 0),
                default=None,
            )
        if not chosen_var:
            continue
        unit_price = float(chosen_var.get("price") or 0)
        if unit_price <= 0:
            continue
        items_summary.append({
            "product_id": prod.get("id"),
            "variation_id": chosen_var.get("id"),
            "title": title,
            "variant_label": chosen_var.get("label"),
            "quantity": qty,
            "unit_price_cents": int(round(unit_price * 100)),
        })
        if explicit:
            has_explicit_qty = True

    if len(items_summary) < 2 or not has_explicit_qty:
        return None

    subtotal_cents = sum(it["unit_price_cents"] * it["quantity"] for it in items_summary)
    shipping_cents = _extract_shipping_cost_from_history(history) or 0
    return {
        "items": items_summary,
        # Para retro-compat con payment_link_tool single-product
        "product_id": items_summary[0]["product_id"],
        "variation_id": items_summary[0]["variation_id"],
        "product_name": " + ".join(
            f"{it['quantity']}x {it['title']}" for it in items_summary[:3]
        ),
        "variant_label": None,
        "unit_price_cents": items_summary[0]["unit_price_cents"],
        "quantity": sum(it["quantity"] for it in items_summary),
        "subtotal_cents": subtotal_cents,
        "shipping_cost_cents": shipping_cents,
        "total_cents": subtotal_cents + shipping_cents,
    }


def _build_verified_order_context(
    catalog: list,
    history: list[dict],
) -> Optional[dict]:
    """
    Construye un contexto de pedido verificado desde datos reales (catálogo DB + historial).
    NO delega cálculos al LLM.
    Retorna dict con totales listos para inyectar en el prompt de READY_FOR_SUMMARY,
    o None si no hay suficientes datos.
    """
    product = _find_context_product_from_history(catalog, history)
    if not product:
        return None

    # Precio + IDs: preferir variante detectada en historial, fallback a la más barata con stock
    unit_price: float = 0.0
    variant_label: Optional[str] = None
    variation_id: Optional[str] = None
    variants = product.get("variants") or []
    if variants:
        # Precio base: variante más barata con stock
        prices = [
            float(v.get("price") or 0)
            for v in variants
            if (v.get("stock") or 0) > 0 and v.get("price")
        ]
        if prices:
            unit_price = min(prices)
        else:
            unit_price = float(product.get("price_min") or product.get("price") or 0)
        # Detectar variante específica mencionada en el historial.
        # Normaliza label quitando puntuación para que "Color: Rojo" matchee "color rojo".
        def _clean_label(raw: str) -> str:
            normalized = _normalize_text(raw)
            return " ".join(re.sub(r"[^a-z0-9 ]", " ", normalized).split())

        for msg in reversed(history or []):
            if str(msg.get("direction") or "").lower() != "inbound":
                continue
            c = _normalize_text(str(msg.get("content") or ""))
            c_tokens = set(c.replace(",", " ").replace(".", " ").split())
            for v in variants:
                lbl_clean = _clean_label(str(v.get("label") or ""))
                # 1) Match completo del label (ej "presentacion 100g" en "...presentacion 100g...")
                if lbl_clean and lbl_clean in c:
                    unit_price = float(v.get("price") or unit_price)
                    variant_label = str(v.get("label"))
                    variation_id = v.get("id")
                    break
                # 2) Match por VALOR del attribute (ej "100g" cuando el cliente dice
                #    "quiero el de 100g" sin nombrar el atributo "Presentación").
                attrs = v.get("attributes") or {}
                if isinstance(attrs, dict):
                    matched = False
                    for av in attrs.values():
                        av_norm = _normalize_text(str(av or "")).strip()
                        if not av_norm:
                            continue
                        # token-level match para evitar substring trampa (ej "10g" en "100g")
                        if av_norm in c_tokens or av_norm in c.split():
                            unit_price = float(v.get("price") or unit_price)
                            variant_label = str(v.get("label"))
                            variation_id = v.get("id")
                            matched = True
                            break
                    if matched:
                        break
            if variant_label:
                break
        # Si no se detectó variante específica, usar la más barata disponible con su ID
        if not variation_id:
            best = min(
                (v for v in variants if (v.get("stock") or 0) > 0 and v.get("price")),
                key=lambda v: float(v.get("price") or 0),
                default=None,
            )
            if best:
                variation_id = best.get("id")
    else:
        unit_price = float(product.get("price") or 0)

    if unit_price <= 0:
        return None

    # Cantidad: extraer del historial reciente
    quantity = 1
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").lower() != "inbound":
            continue
        q = _extract_quantity_from_text(str(msg.get("content") or ""))
        if q > 1:
            quantity = q
            break

    subtotal_cents = int(round(unit_price * quantity * 100))
    shipping_cost_cents = _extract_shipping_cost_from_history(history) or 0
    total_cents = subtotal_cents + shipping_cost_cents

    title = re.sub(r"^\[.*?\]\s*", "", str(product.get("title", "Producto"))).strip()
    return {
        "product_id": product.get("id"),      # UUID del producto en DB
        "variation_id": variation_id,          # UUID de la variante en DB (None si sin variantes)
        "product_name": title,
        "variant_label": variant_label,
        "unit_price_cents": int(round(unit_price * 100)),
        "quantity": quantity,
        "subtotal_cents": subtotal_cents,
        "shipping_cost_cents": shipping_cost_cents,
        "total_cents": total_cents,
    }


def _extract_quantity_from_text(text: str) -> int:
    """Extrae cantidad desde texto libre. Retorna 1 si no detecta."""
    normalized = _normalize_text(text)
    patterns = [
        r"\bx\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*x\b",
        r"\b(\d{1,3})\s*(?:unidad|unidades|ud|uds|u)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, normalized)
        if m:
            try:
                q = int(m.group(1))
                if q > 0:
                    return min(q, 200)
            except ValueError:
                pass
    return 1


from text_utils import format_cents_cop as _format_cop, format_pesos as _format_pesos  # noqa: E402


_TONO_INSTRUCCIONES: dict[str, str] = {
    "formal": (
        "TONO: Formal y respetuoso. Trate de usted al cliente; tutee solo si el cliente lo hace primero.\n"
        "Saluda así: \"Buenas tardes, ¿en qué puedo ayudarle?\". Confirma así: \"Perfecto, le confirmo enseguida.\".\n"
        "Cierra así: \"Quedo atento.\". Evita coloquialismos, jergas y emojis.\n"
        "Ejemplo natural: \"Le confirmo que el producto está disponible. ¿Para qué ciudad sería el envío?\""
    ),
    "profesional": (
        "TONO: Profesional y preciso. Tono cordial pero claro, sin coloquialismos.\n"
        "Saluda así: \"Hola, ¿en qué puedo ayudarte?\". Confirma así: \"Perfecto, lo reviso.\".\n"
        "Usa frases breves. Evita muletillas y exclamaciones excesivas.\n"
        "Ejemplo natural: \"Tenemos disponibilidad. Confírmame ciudad y te paso la cotización.\""
    ),
    "amigable": (
        "TONO: Amigable y cercano. Tutea al cliente desde el inicio.\n"
        "Saluda así: \"¡Hola! ¿En qué te puedo ayudar?\". Confirma así: \"Listo, eso lo manejamos.\".\n"
        "Usa contracciones naturales (\"está\", \"vamos\", \"aquí\"). Sin emojis.\n"
        "Ejemplo natural: \"¡Sí! Lo tenemos disponible. Cuéntame para qué ciudad y te cotizo el envío.\""
    ),
    "cercano": (
        "TONO: Muy cercano, casi como un amigo. Tutea siempre y conversa con calidez.\n"
        "Saluda así: \"¡Hola! ¿Cómo estás? ¿En qué te ayudo?\". Confirma así: \"Listo, ya te ayudo con eso.\".\n"
        "Permite expresiones colombianas naturales (\"vale\", \"con gusto\", \"de una\"). Sin emojis.\n"
        "Ejemplo natural: \"¡Claro que sí! Eso lo tenemos. ¿Para dónde te lo enviaríamos?\""
    ),
    "juvenil": (
        "TONO: Joven, dinámico y energético. Tutea siempre, usa frases cortas. Sin emojis.\n"
        "Saluda así: \"¡Hey! ¿Qué necesitas?\". Confirma así: \"¡Listo! Eso lo tengo.\".\n"
        "Evita textitos infantilizados o sobreuso de signos.\n"
        "Ejemplo natural: \"¡Sí lo tenemos! ¿Para qué ciudad sería?\""
    ),
}


# Guía de estilo humano que aplica a TODOS los tonos. Inyectado al system prompt.
# Razón: evitar que el LLM caiga en fórmulas robóticas o repetitivas, asegurar
# variación natural entre mensajes, y mantener registro adaptado al cliente.
_HUMAN_STYLE_GUIDE = """
GUÍA DE ESTILO HUMANO (aplica siempre, encima del tono):
- Nunca uses fórmulas robóticas: "Procesando su solicitud", "Estamos procesando", "Lamentamos los inconvenientes ocasionados", "Su solicitud ha sido recibida".
- ESTILO PUNTUACIÓN WhatsApp (casual colombiano): NO uses los signos de apertura `¡` ni `¿`. Solo usa los de CIERRE `!` y `?`. Ejemplos correctos: "Hola!" (NO "¡Hola!"), "Cómo estás?" (NO "¿Cómo estás?"), "Te ayudo?" (NO "¿Te ayudo?"). Es el registro real de WhatsApp en Colombia. Aplica a TODOS los outbounds — saludos, preguntas, exclamaciones, listas con preguntas finales.
- NO RE-SALUDES dentro de la misma conversación. "Hola!" SOLO en el primer mensaje saliente cuando el cliente saluda ("hola", "buenas"). Si el primer mensaje del cliente es una PREGUNTA DIRECTA (sin saludo, ej: "Qué productos tienes?", "Cuál es la política de devoluciones?"), abre con un conector cordial ("Claro", "Por supuesto", "Te cuento", "Con gusto", "Listo") + va al grano — NO uses "Hola!" si el cliente no saludó. Si ya hubo intercambio previo, abre con conector ("Claro", "Listo", "Perfecto", "Entendido", "Genial") o entra directo al contenido — nunca con "Hola!".
- No repitas la misma estructura sintáctica en mensajes consecutivos: varía inicios, transiciones y cierres.
- Adáptate al registro del cliente: si escribe corto e informal, responde corto e informal; si escribe formal, mantén formalidad.
- Confirma comprensión rotando expresiones: "Listo", "Perfecto", "Entendido", "Ya veo", "Claro" — no repitas la misma dos veces seguidas.
- Para respuestas conversacionales cortas, usa prosa natural con `\\n\\n` entre ideas. Evita listas con bullets a menos que el cliente pida opciones explícitas.
- Si el cliente usa emojis, puedes responder con emojis con moderación; si no los usa, modera el uso.
- Sé empático cuando hay fricción (sin stock, pago fallido, demora): reconoce, ofrece alternativa, no pidas disculpa formularia.
- Frases prohibidas: "Procesando su solicitud", "Estamos procesando", "Lamentamos los inconvenientes ocasionados", "Su solicitud ha sido recibida y será atendida".
"""


# Salvaguarda determinística cuando Gemini retorna requires_human=True para
# saludos/off_topic con response_text vacío. 5 variaciones por tono, rotativas
# por (conversation_id + day_of_year). Si first_name está disponible, prefijar.
_SAFETY_GREETING_BANK: dict[str, list[str]] = {
    "formal": [
        "Buenas, soy {agent} de {tenant}. ¿En qué puedo ayudarle?",
        "Hola, soy {agent} de {tenant}. Cuénteme cómo puedo asistirle.",
        "Buen día, soy {agent} de {tenant}. ¿Qué necesita hoy?",
        "Hola, le saluda {agent} de {tenant}. ¿En qué le ayudo?",
        "Bienvenido a {tenant}, soy {agent}. Estoy a sus órdenes.",
    ],
    "profesional": [
        "Hola, soy {agent} de {tenant}. ¿En qué puedo ayudarte?",
        "Hola, soy {agent} de {tenant}. Cuéntame qué necesitas.",
        "Hola, soy {agent} de {tenant}. ¿Sobre qué te ayudo?",
        "Hola, te saluda {agent} de {tenant}. ¿Qué necesitas hoy?",
        "Hola, {agent} de {tenant} por aquí. ¿En qué te apoyo?",
    ],
    "amigable": [
        "¡Hola! Soy {agent} de {tenant}  ¿En qué te ayudo?",
        "¡Hola! Soy {agent} de {tenant}. Cuéntame, ¿qué necesitas?",
        "¡Hola! Acá {agent} de {tenant}. ¿En qué te puedo ayudar?",
        "¡Hola! Soy {agent} de {tenant}. ¿Qué se te ofrece hoy?",
        "¡Hey, hola! Soy {agent} de {tenant}. ¿Cómo te ayudo?",
    ],
    "cercano": [
        "¡Hola! ¿Cómo estás? Soy {agent} de {tenant}. Cuéntame.",
        "¡Hola! Soy {agent} de {tenant}. ¿En qué te ayudo?",
        "¡Hey! Acá {agent} de {tenant}. Dime, ¿qué necesitas?",
        "¡Hola! Soy {agent} de {tenant}. ¿En qué te echo una mano?",
        "¡Qué tal! Soy {agent} de {tenant}. Cuéntame qué buscas.",
    ],
    "juvenil": [
        "¡Hey! Soy {agent} de {tenant}. ¿Qué necesitas?",
        "¡Holaaa! Soy {agent} de {tenant}. Cuéntame.",
        "¡Hey! Acá {agent} de {tenant}. ¿En qué te ayudo?",
        "¡Hola! Soy {agent} de {tenant}. ¿Qué buscas?",
        "¡Qué más! Soy {agent} de {tenant}. Dime, ¿qué necesitas?",
    ],
}


def _co_time_of_day_greeting() -> tuple[str, str]:
    """Retorna (saludo_apropiado, etiqueta) según la hora actual en Colombia
    (UTC-5, sin DST). Usado por el bot para saludar naturalmente:
      - 05:00 a 11:59 → "Buenos días" (mañana)
      - 12:00 a 18:59 → "Buenas tardes" (tarde)
      - 19:00 a 04:59 → "Buenas noches" (noche)
    """
    co_tz = timezone(timedelta(hours=-5))
    hour = datetime.now(co_tz).hour
    if 5 <= hour < 12:
        return ("Buenos días", "mañana")
    if 12 <= hour < 19:
        return ("Buenas tardes", "tarde")
    return ("Buenas noches", "noche")


def _safety_greeting_response(
    *,
    agent_name: str,
    tenant_name: str,
    first_name: Optional[str],
    tono: str,
    conversation_id: str,
) -> str:
    """Retorna saludo seguro variado cuando Gemini falla en intent=greeting/off_topic.

    - Rotación: hash(conversation_id + day_of_year) % 5 → mismo conv recibe la misma
      variante en el mismo día, pero rota entre días.
    - Si first_name (con consent) presente: prefijar "¡Hola, {first_name}! ".
    - Tono inválido o ausente → fallback a "amigable".
    """
    import hashlib
    from datetime import datetime, timezone, timedelta

    bank = _SAFETY_GREETING_BANK.get(tono) or _SAFETY_GREETING_BANK["amigable"]
    co_tz = timezone(timedelta(hours=-5))
    day_of_year = datetime.now(co_tz).timetuple().tm_yday
    seed_input = f"{conversation_id}|{day_of_year}".encode("utf-8")
    idx = int(hashlib.md5(seed_input).hexdigest(), 16) % len(bank)
    template = bank[idx]
    base = template.format(agent=agent_name or "tu asistente", tenant=tenant_name or "la tienda")
    if first_name:
        # Personalización: anteponer saludo con nombre solo si la variante
        # empieza con "¡Hola" / "Hola" / "Buenas" / "Buen día" / "Hey" / "Qué tal".
        # En otros casos (ej. "Bienvenido a..."), inyectar nombre dentro.
        if base.lower().startswith(("¡hola", "hola", "buenas", "buen día", "¡hey", "hey", "¡qué", "qué tal")):
            # Mantener el saludo y agregar nombre tras la primera coma o reemplazar "Hola"
            base = base.replace("¡Hola!", f"¡Hola, {first_name}!", 1)
            base = base.replace("¡Hey!", f"¡Hey, {first_name}!", 1)
            base = base.replace("¡Holaaa!", f"¡Holaaa, {first_name}!", 1)
            base = base.replace("¡Qué más!", f"¡Qué más, {first_name}!", 1)
            if first_name not in base:
                # Para "Hola, ..." / "Buenas, ..." / "Buen día, ..."
                if "," in base:
                    head, tail = base.split(",", 1)
                    base = f"{head}, {first_name},{tail}"
    return base


def _pick_variant(variants: list[str], *, seed: str) -> str:
    """Selecciona una variante de forma estable basada en seed (hash determinístico)."""
    import hashlib
    if not variants:
        return ""
    idx = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % len(variants)
    return variants[idx]


# Bug 30 — frases que indican que el bot anuncia handover a humano. Si el
# response_text del LLM contiene una de estas pero requires_human=False,
# el cliente queda en limbo (texto promete asesor pero status=bot_active).
# La salvaguarda fuerza requires_human=True para que la escalación real ocurra.
_HANDOVER_PHRASES: tuple[str, ...] = (
    "te paso con",
    "te paso a",
    "te conecto con",
    "te transfiero",
    "te derivo",
    "te canalizo",
    "paso a un asesor",
    "paso al asesor",
    "te comunicare con",
    "te comunico con",
    "lo paso con",
    "lo conecto con",
    "te atendera un",
    "te atendera una",
    "te ayudara un asesor",
    "te ayudara una asesora",
    "te ayudara nuestro",
    "te ayudara nuestra",
    "te ayudara de inmediato",
    "te contactara un",
    "te contactara una",
    "un asesor te ayudara",
    "una asesora te ayudara",
    "un asesor te atendera",
    "una asesora te atendera",
    "un especialista te",
    "una especialista te",
    "un consultor te",
    "una consultora te",
    "un agente te",
    "una agente te",
    "asesor humano",
)


def _response_promises_handover(text: str) -> bool:
    """True si el response_text anuncia traspaso a humano (asesor/agente/especialista).

    Usa _normalize_text (sin acentos, lowercase) para robustez. Bug 30 — si el
    LLM emite este texto pero requires_human=False, el cliente queda en limbo:
    el mensaje promete asesor pero el status sigue bot_active.
    """
    if not text:
        return False
    try:
        from tools.shipping_quote_tool import _normalize_text  # noqa: WPS433
    except Exception:
        return False
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _HANDOVER_PHRASES)


# Variantes humanas para mensajes determinísticos templated.
# Razón: evitar que el cliente reciba siempre la misma string robótica.
# Selección por seed = conversation_id + day_of_year (consistente en el día).
_CANCEL_SUCCESS_VARIANTS = [
    "Listo, cancelé tu pedido. \n\nCuando quieras volver a cotizar, aquí estoy.",
    "Hecho, ya cancelé el pedido.\n\nSi cambias de idea o quieres ver otra cosa, me avisas.",
    "Perfecto, lo cancelo. 👍\n\nPuedes volver a consultar el catálogo cuando gustes.",
]
_CANCEL_NONE_VARIANTS = [
    "No tienes un pedido activo para cancelar en este momento. ¿En qué más te ayudo?",
    "No veo ningún pedido pendiente para cancelar. ¿Hay algo más en lo que te apoye?",
    "Por aquí no aparece pedido activo. ¿Qué necesitas?",
]
_REACTIVATION_VARIANTS = [
    "¡Hola de nuevo!  Hace un rato que no hablábamos. ¿En qué te puedo ayudar hoy?",
    "¡Hola! Ha pasado un tiempo desde tu última consulta. Cuéntame, ¿qué necesitas?",
    "¡Hey! Por aquí estoy de nuevo. ¿En qué te ayudo?",
]
# Correcciones de datos: 2 variantes por campo (rotación por seed).
_CORRECTION_PROMPT_VARIANTS: dict[str, list[str]] = {
    "email": [
        "Entendido 👍 ¿Cuál es tu correo electrónico correcto?",
        "Listo, lo corregimos. ¿Me compartes el correo correcto?",
    ],
    "name": [
        "Entendido 👍 ¿Cuál es tu nombre completo correcto?",
        "Sin problema. ¿Me confirmas tu nombre completo?",
    ],
    "document": [
        "Entendido 👍 Compárteme tu tipo (CC/CE/NIT/PP/TI) y número de documento correctos.",
        "Listo, lo ajustamos. ¿Me das el tipo y número de documento correcto?",
    ],
    "address": [
        "Entendido 👍 Dame tu dirección correcta, por favor.",
        "Listo, lo ajustamos. ¿Me compartes la dirección correcta?",
    ],
}


def _today_seed(conversation_id: str) -> str:
    from datetime import datetime, timezone, timedelta
    co_tz = timezone(timedelta(hours=-5))
    return f"{conversation_id}|{datetime.now(co_tz).timetuple().tm_yday}"


def _is_outside_support_hours(support_schedule: dict) -> bool:
    """
    Retorna True si la hora actual (Colombia UTC-5) está fuera del horario de soporte configurado.
    Si support_schedule está vacío o mal formado, retorna False (no bloquear).
    """
    from datetime import datetime, timezone, timedelta
    if not support_schedule:
        return False
    try:
        days: list[int] = support_schedule.get("days") or []
        open_time: str  = support_schedule.get("open") or ""
        close_time: str = support_schedule.get("close") or ""
        if not days or not open_time or not close_time:
            return False
        co_tz = timezone(timedelta(hours=-5))
        now = datetime.now(co_tz)
        # isoweekday: Monday=1 ... Sunday=7
        if now.isoweekday() not in days:
            return True
        open_h, open_m = map(int, open_time.split(":"))
        close_h, close_m = map(int, close_time.split(":"))
        current_minutes = now.hour * 60 + now.minute
        open_minutes    = open_h * 60 + open_m
        close_minutes   = close_h * 60 + close_m
        return not (open_minutes <= current_minutes < close_minutes)
    except Exception:
        return False


# ISO weekday 1=Lu .. 7=Do (alineado con DaysSelector y _is_outside_support_hours).
_DAY_LABELS_ES_ISO = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}


def _format_support_schedule_text(schedule: Optional[dict]) -> str:
    """Deriva 'Lun a Vie de 09:00 a 18:00' desde support_schedule jsonb.
    Reemplaza el legacy `tenants.business_hours` (texto libre, sin estructura).

    Convención de días: ISO weekday 1=Lu..7=Do (alineada con DaysSelector UI
    y con `_is_outside_support_hours`). NO mezclar con 0-6 (Python weekday())."""
    if not schedule or not isinstance(schedule, dict):
        return ""
    raw_days = schedule.get("days") or []
    open_t   = (schedule.get("open") or "").strip()
    close_t  = (schedule.get("close") or "").strip()
    if not raw_days or not open_t or not close_t:
        return ""
    days = sorted({int(d) for d in raw_days if isinstance(d, (int, float)) and 1 <= int(d) <= 7})
    if not days:
        return ""
    # Si es bloque continuo (ej. Lu-Vi = [1,2,3,4,5]) → notación rango.
    is_contiguous = all(days[i] - days[i - 1] == 1 for i in range(1, len(days)))
    if is_contiguous and len(days) >= 2:
        labels = f"{_DAY_LABELS_ES_ISO[days[0]]} a {_DAY_LABELS_ES_ISO[days[-1]]}"
    else:
        labels = ", ".join(_DAY_LABELS_ES_ISO[d] for d in days)
    return f"{labels} de {open_t} a {close_t}"


def _build_store_info_section(
    tenant_name: str,
    store_type: str,
    shipping_origin: dict,
    social_links: dict,
    store_locations: list,
    support_schedule: Optional[dict] = None,
    mision: str = "",
    vision: str = "",
    valores: str = "",
    nit: str = "",
    email_contacto: str = "",
    telefono_contacto: str = "",
) -> str:
    """
    Construye la sección de información comercial del tenant para el system prompt.
    Adaptativa por tipo de tienda: fisica | virtual | fisica_virtual.
    Permite al bot responder sin escalar: ubicación, sedes, redes, horario.

    Rev. 71 — La columna legacy `business_hours` (texto libre) se eliminó del prompt.
    El horario textual ahora se deriva de `support_schedule` (jsonb) — fuente única.
    """
    has_fisica  = store_type in ("fisica", "fisica_virtual")
    has_virtual = store_type in ("virtual", "fisica_virtual")

    lines: list[str] = [f"\nSOBRE LA TIENDA — INFORMACIÓN COMERCIAL DE {tenant_name.upper()}:"]

    # Modo de operación explícito (rev. 71 — antes el bot lo inferia del shape)
    if has_fisica and has_virtual:
        lines.append("- Modo de operación: atención presencial en sedes y venta online.")
    elif has_virtual:
        lines.append("- Modo de operación: solo tienda virtual (sin sedes físicas al público).")
    elif has_fisica:
        lines.append("- Modo de operación: atención presencial en sedes (consulta horario).")

    if has_fisica:
        # Sedes públicas (atención al cliente). Diferentes conceptualmente del
        # origen de despacho (`shipping_origin`) — ver bloque dedicado abajo.
        sedes = [s for s in (store_locations or []) if s.get("city") or s.get("street")]
        if sedes:
            lines.append("- Sedes públicas de atención al cliente:")
            # Rev. 71 — sede con `is_primary=True` se rotula explícita y se ordena primero.
            primary = [s for s in sedes if s.get("is_primary")]
            others  = [s for s in sedes if not s.get("is_primary")]
            ordered = (primary + others) if primary else sedes
            for sede in ordered:
                sede_name = sede.get("name") or "Sede"
                if sede.get("is_primary"):
                    sede_name = f"{sede_name} (principal)"
                city      = sede.get("city", "")
                state     = sede.get("state", "")
                street    = sede.get("street", "")
                phone     = sede.get("phone", "")
                email     = sede.get("email", "")
                loc       = city
                if state and state != city:
                    loc += f", {state}"
                sede_line = f"  · {sede_name}: {street}{', ' + loc if loc else ''}" if street else f"  · {sede_name}: {loc}"
                if phone:
                    sede_line += f" | Tel: {phone}"
                if email:
                    sede_line += f" | Email: {email}"
                lines.append(sede_line)

    # Rev. 71 — Origen de despacho (`shipping_origin`): es la BODEGA operacional
    # desde donde sale Envia. NO es necesariamente pública — solo se entrega al
    # LLM la ciudad/estado para que pueda responder "despachamos desde Bogotá"
    # sin revelar la dirección exacta de la bodega (dato operacional sensible).
    ship_city  = (shipping_origin or {}).get("city", "")
    ship_state = (shipping_origin or {}).get("state", "")
    if ship_city:
        ship_loc = ship_city
        if ship_state and ship_state != ship_city:
            ship_loc += f", {ship_state}"
        lines.append(f"- Origen de despacho (bodega): {ship_loc}")

    active_social = {k: v for k, v in (social_links or {}).items() if v}
    if active_social:
        social_parts = ", ".join(f"{k.capitalize()}: {v}" for k, v in active_social.items())
        lines.append(f"- Redes y canales digitales: {social_parts}")

    horario_texto = _format_support_schedule_text(support_schedule)
    if horario_texto:
        lines.append(f"- Horario de atención: {horario_texto}")

    if mision:
        lines.append(f"- Misión: {mision}")
    if vision:
        lines.append(f"- Visión: {vision}")
    if valores:
        lines.append(f"- Valores: {valores}")

    # Rev. 71 — Identidad legal/contacto del negocio. Solo se entrega al LLM con
    # instrucción explícita de usarse SI EL CLIENTE PREGUNTA. Evita que el bot
    # ofrezca proactivamente NIT/email/teléfono (sería invasivo) pero permite
    # responder con verdad cuando lo piden ("¿cuál es su NIT?", "¿correo?").
    identidad_lines: list[str] = []
    if nit:
        identidad_lines.append(f"  - NIT: {nit}")
    if email_contacto:
        identidad_lines.append(f"  - Email de contacto del negocio: {email_contacto}")
    if telefono_contacto:
        identidad_lines.append(f"  - Teléfono del negocio: {telefono_contacto}")
    if identidad_lines:
        lines.append("- Identidad legal y canales corporativos (úsalos SOLO si el cliente lo pregunta):")
        lines.extend(identidad_lines)

    if len(lines) == 1:
        return ""  # Sin info configurada → no inyectar sección vacía

    lines.append(
        "INSTRUCCIÓN — DISTINGUE estos conceptos al responder (rev. 71):"
    )
    lines.append(
        "  · Si el cliente pregunta '¿dónde están?' / '¿puedo recoger?' / '¿tienen tienda física?' "
        "→ usa SEDES PÚBLICAS DE ATENCIÓN. La sede (principal) es la primera referencia."
    )
    lines.append(
        "  · Si el cliente pregunta '¿desde dónde despachan?' / '¿de qué ciudad sale el envío?' "
        "→ usa ORIGEN DE DESPACHO (solo ciudad/estado, NUNCA la dirección exacta — es bodega operacional)."
    )
    lines.append(
        "  · Si el cliente pregunta '¿cuándo entregan?' / '¿en cuántos días?' "
        "→ NO inventes; consulta KB categoría envíos o pide confirmar la cotización del carrier."
    )
    lines.append(
        "Para preguntas de horario, redes, misión o valores: responde con la info de arriba. NO escales por estas preguntas."
    )
    return "\n".join(lines)


# Estado de disponibilidad de la tabla bot_source_log (rev. 71).
# Best-effort lazy detection: si la migración no está aplicada, evita gastar
# round-trips a Supabase y solo reintenta cada N segundos.
_BOT_LOG_AVAILABLE: Optional[bool] = None  # None = no chequeado aún
_BOT_LOG_LAST_CHECK: float = 0.0
_BOT_LOG_RECHECK_SECONDS: float = 900.0  # 15 min — cooldown tras "tabla no existe"


def _bot_log_available(supabase) -> bool:
    """Detecta si la tabla `bot_source_log` existe. Cachea el resultado:
    - True estable (tabla existe): siempre True hasta restart.
    - False con cooldown: re-verifica cada 15 min (cubre el caso de aplicar
      migración con servicio caliente).
    """
    global _BOT_LOG_AVAILABLE, _BOT_LOG_LAST_CHECK
    import time as _t
    now = _t.monotonic()
    if _BOT_LOG_AVAILABLE is True:
        return True
    if _BOT_LOG_AVAILABLE is False and (now - _BOT_LOG_LAST_CHECK) < _BOT_LOG_RECHECK_SECONDS:
        return False
    try:
        supabase.table("bot_source_log").select("id").limit(1).execute()
        _BOT_LOG_AVAILABLE = True
        logger.info("[BOT_LOG] Tabla bot_source_log disponible — logging activado.")
    except Exception as exc:
        text = str(exc).lower()
        if "does not exist" in text or "relation" in text or "404" in text:
            if _BOT_LOG_AVAILABLE is not False:
                logger.warning(
                    "[BOT_LOG] Tabla bot_source_log no existe; logging inhibido. "
                    "Aplicar migración 20260501000001_bot_source_log.sql."
                )
            _BOT_LOG_AVAILABLE = False
        else:
            # Error transitorio (red, RLS, etc.) — no marcamos como permanentemente falso.
            logger.debug("[BOT_LOG] Probe fallido (transitorio): %s", exc)
            _BOT_LOG_AVAILABLE = False
    _BOT_LOG_LAST_CHECK = now
    return _BOT_LOG_AVAILABLE is True


def _log_bot_sources(
    *,
    supabase,
    tenant_id: str,
    conversation_id: str,
    message_id: Optional[str],
    fsm_state: str,
    system_prompt: str,
    kb_docs: list,
    catalog_count: int,
    customer_context_block: str,
    is_outside_hours: bool,
    identity_present: bool,
    intent_detected: Optional[str],
    requires_human: bool,
) -> None:
    """Inserta un registro append-only en bot_source_log con metadata de fuentes.
    Sin PII — solo flags estructurales y agregados.
    Rev. 71 — fundamento para auditabilidad operativa del bot.

    Si la tabla no existe (migración no aplicada), inhibe el insert con cooldown
    de 15 min para evitar round-trips inútiles."""
    if not _bot_log_available(supabase):
        return

    kb_categories_used: list[str] = []
    kb_missing_categories: list[str] = []
    kb_real_count = 0
    for d in (kb_docs or []):
        cat = d.get("category")
        if d.get("_synthetic_missing"):
            if cat and cat not in kb_missing_categories:
                kb_missing_categories.append(cat)
        else:
            kb_real_count += 1
            if cat and cat not in kb_categories_used:
                kb_categories_used.append(cat)

    payload = {
        "tenant_id":                    tenant_id,
        "conversation_id":              conversation_id,
        "message_id":                   message_id,
        "fsm_state":                    fsm_state,
        "injected_catalog":             "Producto en contexto" in system_prompt or catalog_count > 0,
        "injected_kb":                  "INFORMACIÓN EXTRAÍDA DE LA BASE" in system_prompt,
        "injected_store_info":          "SOBRE LA TIENDA" in system_prompt,
        "injected_business_identity":   identity_present and "Identidad legal" in system_prompt,
        "injected_customer_context":    bool((customer_context_block or "").strip()),
        "injected_cart_recovery":       "CARRITO PREVIO" in system_prompt,
        "injected_after_hours":         is_outside_hours and "FUERA DE HORARIO HUMANO" in system_prompt,
        "kb_categories_used":           kb_categories_used,
        "kb_missing_categories":        kb_missing_categories,
        "kb_docs_count":                kb_real_count,
        "catalog_products_count":       int(catalog_count),
        "prompt_chars":                 len(system_prompt or ""),
        "intent_detected":              intent_detected,
        "requires_human":               bool(requires_human),
    }
    try:
        supabase.table("bot_source_log").insert(payload).execute()
    except Exception as exc:
        # Si el insert falla con "relation does not exist", invalidamos cache
        # — la migración pudo haber sido revertida. Cooldown re-evalúa en 15 min.
        global _BOT_LOG_AVAILABLE, _BOT_LOG_LAST_CHECK
        import time as _t
        text = str(exc).lower()
        if "does not exist" in text or "404" in text:
            _BOT_LOG_AVAILABLE = False
            _BOT_LOG_LAST_CHECK = _t.monotonic()
            logger.warning("[BOT_LOG] Insert falló por tabla ausente; inhibo por 15 min.")
        else:
            logger.debug("[BOT_LOG] Insert falló (transitorio): %s", exc)


def _build_system_prompt(
    catalog: list,
    tenant_name: str,
    kb_text: str,
    ai_agent: dict,
    contact_record: dict,
    query_text: str = "",
    history: Optional[list[dict]] = None,
    buying_intent: bool = False,
    shipping_quoted: bool = False,
    tenant_shipping_origin: Optional[dict] = None,
    tenant_store_type: str = "fisica",
    tenant_social_links: Optional[dict] = None,
    tenant_store_locations: Optional[list] = None,
    tenant_support_schedule: Optional[dict] = None,
    tenant_mision: str = "",
    tenant_vision: str = "",
    tenant_valores: str = "",
    tenant_tono: str = "amigable",
    tenant_escalation_role: str = "especialista",
    tenant_nit: str = "",
    tenant_email_contacto: str = "",
    tenant_telefono_contacto: str = "",
    tenant_after_hours_message: str = "",
    tenant_is_outside_hours: bool = False,
    customer_context_block: str = "",
    # Sem 7 F2 cierre 2026-05-20 — P1+P2 multitenant.
    tenant_business_pitch: str = "",
    tenant_product_groups: Optional[list] = None,
    tenant_show_prices: bool = True,
) -> str:
    """Thin wrapper — delega a `prompt.builder.build_system_prompt` (rev. 104, F1-4).

    El cuerpo de la composición (~778 LOC) vive ahora en
    `services/ai-orchestrator/prompt/builder.py`. Esta función mantiene
    la firma + nombre legacy para compat con tests que hacen
    `patch.object(orchestrator, "_build_system_prompt")` y para call-sites
    que aún no migran al import directo.
    """
    from prompt.builder import build_system_prompt
    return build_system_prompt(
        catalog=catalog,
        tenant_name=tenant_name,
        kb_text=kb_text,
        ai_agent=ai_agent,
        contact_record=contact_record,
        query_text=query_text,
        history=history,
        buying_intent=buying_intent,
        shipping_quoted=shipping_quoted,
        tenant_shipping_origin=tenant_shipping_origin,
        tenant_store_type=tenant_store_type,
        tenant_social_links=tenant_social_links,
        tenant_store_locations=tenant_store_locations,
        tenant_support_schedule=tenant_support_schedule,
        tenant_mision=tenant_mision,
        tenant_vision=tenant_vision,
        tenant_valores=tenant_valores,
        tenant_tono=tenant_tono,
        tenant_escalation_role=tenant_escalation_role,
        tenant_nit=tenant_nit,
        tenant_email_contacto=tenant_email_contacto,
        tenant_telefono_contacto=tenant_telefono_contacto,
        tenant_after_hours_message=tenant_after_hours_message,
        tenant_is_outside_hours=tenant_is_outside_hours,
        customer_context_block=customer_context_block,
        tenant_business_pitch=tenant_business_pitch,
        tenant_product_groups=tenant_product_groups or [],
        tenant_show_prices=tenant_show_prices,
    )


def _build_user_context(history: list[dict], new_message: str) -> str:
    """Formatea el historial de conversación como contexto para Gemini."""
    history_for_prompt = _history_without_current_inbound(history, new_message)
    lines = []
    for msg in history_for_prompt:
        role = "Cliente" if msg["direction"] == "inbound" else "Asistente"
        lines.append(f"{role}: {msg['content']}")

    lines.append(f"Cliente: {new_message}")
    return "\n".join(lines)


def _history_without_current_inbound(history: list[dict], new_message: str) -> list[dict]:
    if not history:
        return []
    last = history[-1] or {}
    last_direction = str(last.get("direction") or "").strip().lower()
    last_content_norm = _normalize_text(str(last.get("content") or ""))
    new_content_norm = _normalize_text(new_message)
    if last_direction == "inbound" and last_content_norm and last_content_norm == new_content_norm:
        return history[:-1]
    return history


_NAME_DISCARD_TOKENS = {
    "si", "sí", "no", "ok", "oki", "okey", "vale", "dale", "listo", "claro",
    "gracias", "hola", "buenas", "buenos", "bien", "perfecto", "genial",
    "confirmo", "acepto", "entendido", "de", "una", "la", "el",
}


def _try_extract_name_from_message(content: str, display_state: str) -> Optional[str]:
    """
    Fallback conservador: cuando display_state==NEEDS_NAME y el LLM no extrae
    el nombre, intenta detectarlo desde el mensaje del cliente.
    Solo activa con mensajes cortos (2-5 tokens), sin stopwords críticas,
    sin caracteres especiales de frase.
    """
    if display_state != "NEEDS_NAME":
        return None
    normalized = content.strip()
    if any(c in normalized for c in ["@", "http", "www", "?", "!", "#"]):
        return None
    tokens = [t for t in normalized.split() if t]
    if not (2 <= len(tokens) <= 5):
        return None
    lower_tokens = {t.lower() for t in tokens}
    if lower_tokens & _NAME_DISCARD_TOKENS:
        return None
    return " ".join(t.title() for t in tokens)


def _humanize_name_in_text(text: str, contact_name: Optional[str], extracted_name: Optional[str]) -> str:
    if not text:
        return text

    patterns: list[tuple[re.Pattern[str], str]] = []
    for full_name in (contact_name, extracted_name):
        if not full_name:
            continue
        normalized_name = " ".join(str(full_name).split())
        if not normalized_name:
            continue
        tokens = [token for token in normalized_name.split(" ") if token]
        if len(tokens) <= 1:
            continue
        first_name = tokens[0].title()
        patterns.append((
            re.compile(
                r"\b" + r"\s+".join(re.escape(token) for token in tokens) + r"\b",
                flags=re.IGNORECASE,
            ),
            first_name,
        ))

    # Post-procesador defensivo: si el texto contiene un saludo con un nombre
    # de 3+ palabras capitalizadas seguido de signo de exclamación o coma,
    # acortarlo al primer nombre. Cubre casos donde el LLM emitió el nombre
    # completo y `contact_name`/`extracted_name` no están disponibles
    # (el LLM no los extrajo, o se persisten más tarde).
    # Rev. 103 — sin re.IGNORECASE: el flag rompía la semántica "Title Case"
    # del bloque del nombre (`[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+`) y atrapaba frases
    # como "Listo, registré tu solicitud." reduciéndolas a "Listo, Registré.".
    # Greeting words se aceptan ambas capitalizaciones explícitamente.
    _greeting_re = re.compile(
        r"(¡?(?:[Gg]racias|[Hh]ola|[Pp]erfecto|[Ll]isto|[Cc]laro|[Ee]ntendido|[Bb]ienvenid[oa])[,\s]+)"
        r"((?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+){2,4}[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)"
        r"([!,\.])",
    )
    def _shorten_full_name(m: re.Match[str]) -> str:
        full = m.group(2)
        first = full.split()[0].capitalize()
        return f"{m.group(1)}{first}{m.group(3)}"
    text = _greeting_re.sub(_shorten_full_name, text)

    if not patterns:
        return text

    protected_lines: dict[int, str] = {}
    original_lines = text.splitlines()
    for idx, line in enumerate(original_lines):
        if "nombre:" in _normalize_text_simple(line):
            protected_lines[idx] = line

    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)

    if protected_lines:
        updated_lines = text.splitlines()
        for idx, original_line in protected_lines.items():
            if idx < len(updated_lines):
                updated_lines[idx] = original_line
        text = "\n".join(updated_lines)

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    return text


def _format_whatsapp_response_text(text: str) -> str:
    """Normaliza el texto del LLM al formato visual canónico WhatsApp (rev. 77).

    Decisión de canon de bullet (corregida tras consulta FAQ oficial):
      WhatsApp dice textualmente:
        "Listas con viñetas: Escribe un asterisco o guion seguido de espacio"
        — https://faq.whatsapp.com/539178204879377
      Por lo tanto el formato NATIVO es `* item` (asterisco + espacio). El cliente
      WhatsApp lo renderiza como viñeta con indent automático y espaciado correcto.
      El caracter `•` Unicode también se ve como bullet pero es solo texto plano
      sin tratamiento especial del cliente.
      Esta función normaliza `•`, `-`, `·`, `+` al inicio de línea hacia `* `
      para usar el formato nativo de WhatsApp en todos los mensajes salientes.

    Reglas aplicadas:
      1. CRLF → LF + trim.
      2. Markdown `**bold**` → `*bold*` (WhatsApp usa un solo asterisco para negrita).
      3. Bullets `• `, `- `, `· `, `+ ` al inicio de línea → `* ` (formato nativo).
      4. Después de `:` con bullet pegado → newline antes del bullet.
      5. Bullet seguido inmediatamente de pregunta `¿` → línea en blanco entre.
      6. Frase con `.!?` seguida de `¿` → línea en blanco entre.
      7. 3+ saltos consecutivos colapsados a 2 (máximo respiro visual).
      8. Citas `> texto` se preservan intactas.

    No invento separadores: si el LLM ya devuelve estructura limpia, queda igual.
    """
    if not text:
        return text
    formatted = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    # 2. Markdown bold doble → simple (WhatsApp usa `*texto*`).
    formatted = re.sub(r"\*\*([^\n*]+?)\*\*", r"*\1*", formatted)

    # 2.b — Rev. 88: bullet malformado al inicio de línea.
    # El LLM a veces produce `*Texto:` (asterisco pegado a palabra, sin
    # espacio, sin cerrar) intentando dar formato bold pero quedando como
    # bullet roto. Detección: línea inicia con `*` + carácter de palabra Y
    # NO tiene `*` de cierre en la misma línea.
    # Convertimos a bullet canónico `* Texto:` agregando el espacio.
    # Preservamos `*texto*` (bold válido cerrado) intacto.
    formatted = re.sub(
        r"(?m)^\*(?=\w)([^*\n]+?)$",
        r"* \1",
        formatted,
    )

    # 3. Bullets variantes al inicio de línea → `* ` (formato nativo WhatsApp).
    # Detecta `• `, `- `, `· `, `+ ` con espacio al inicio (con o sin sangría).
    # NO incluimos `* ` en el patrón porque ya está en formato canónico.
    # NO confunde con `*texto*` (bold inline) porque exige `\s+` después del marker.
    formatted = re.sub(
        r"(?m)^(\s*)[•\-\·\+]\s+(?=\S)",
        r"\1* ",
        formatted,
    )

    # 4. Asegurar newline antes de bullet pegado a `:` (cuando LLM olvida \n).
    formatted = re.sub(r": +\* +(?=\S)", ":\n* ", formatted)

    # 5. Bullet seguido de pregunta sin separación → párrafo aparte.
    formatted = re.sub(r"(\*\s[^\n]+)\s+(¿)", r"\1\n\n\2", formatted)

    # 6. Punto/exclamación/interrogación seguida de pregunta → párrafo aparte.
    formatted = re.sub(r"([.!?])\s+(¿)", r"\1\n\n\2", formatted)

    # 7. Colapsar 3+ saltos consecutivos a 2 (un párrafo de respiro, no más).
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)

    # 8. Rev. 92 — Truncar listados de catálogo a 2 + "Entre otros" por categoría.
    #    Ver `_truncate_category_listings` para reglas + cita marketing.
    formatted = _truncate_category_listings(formatted)

    # 9. Rev. 92 — Realzar citas KB. Convierte `_Fuente: X_` (etiqueta
    #    colgada en cursiva) en blockquote `> Fuente: X` + agrega CTA
    #    invitacional. Mejora UX cuando no hay URL pública del doc.
    formatted = _enhance_kb_citation(formatted)

    # 10. Rev. 103 — Negrita en términos KB regulatoria (plazos, condiciones,
    #     términos legales). Aplica solo si hay cita Fuente:.
    formatted = _bold_kb_terms(formatted)

    # 11. Rev. 104 — Estilo WhatsApp casual colombiano: NO opening puntuación.
    # Removemos `¡` y `¿` — los closing `!` y `?` se preservan. En español
    # estos signos SOLO aparecen como aperturas, nunca dentro de palabras,
    # así que el strip global es seguro. Es la red de seguridad determinística:
    # aunque el LLM ignore la regla del prompt, el outbound siempre sale natural.
    formatted = formatted.replace("¡", "").replace("¿", "")

    return formatted


# ── Rev. 92 — Realzado de cita KB ────────────────────────────────────────────

_KB_CITE_RE = re.compile(r"_Fuente:\s*([^\n_]+?)_")
_KB_CITE_CTA = (
    "Si quieres que te amplíe algún punto o que te envíe el documento "
    "completo, házmelo saber."
)


def _enrich_image_caption(
    caption: str,
    *,
    contact_record: Optional[dict],
    history: Optional[list[dict]],
) -> str:
    """Rev. 103 — añade conector cordial al inicio del caption de imagen.

    El image_send_tool produce un caption "frío" que arranca con el título
    del producto en negrita. Para humanizar el envío de imagen,
    prefijamos con un conector cordial ("Claro, mira:" / "Listo, mira:")
    + opcionalmente el nombre del cliente si es conocido + es primer
    outbound de la conversación (no satura con nombre repetido).

    Variantes rotativas (basadas en hash de conversation timestamp) para
    no sonar robotizado en runs consecutivos.

    Sigue el patrón de `_inject_known_customer_name` (post-process
    determinístico que asegura UX consistente cuando el LLM no decide).
    """
    if not caption or not isinstance(caption, str):
        return caption
    is_known = (
        isinstance(contact_record, dict)
        and contact_record.get("consent_given")
        and (contact_record.get("name") or "").strip()
    )
    has_prior_outbound = any(
        str(m.get("direction") or "").lower() == "outbound"
        for m in (history or [])
    )
    if is_known and not has_prior_outbound:
        first_name = contact_record["name"].strip().split()[0]
        connector = f"Claro, mira *{first_name}*:"
    else:
        connector = "Claro, mira:"
    return f"{connector}\n\n{caption}"


def _inject_known_customer_name(
    text: str,
    *,
    contact_record: Optional[dict],
    history: Optional[list[dict]],
) -> str:
    """Rev. 103 — post-process determinístico: si el contact es conocido
    (consent_given=True + name) Y este es el PRIMER outbound de la
    conversación, inyecta el primer nombre al saludo del bot.

    El LLM a veces sigue la instrucción de personalización del prompt
    (S1 saludo) y a veces no (S2 pregunta directa). Este post-process
    garantiza consistencia — sigue el patrón establecido por
    `_truncate_category_listings`, `_enhance_kb_citation`,
    `_safety_greeting_response`.

    Idempotente: no toca si el nombre ya aparece en el texto.
    """
    if not text or not isinstance(text, str):
        return text
    if not isinstance(contact_record, dict):
        return text
    if not contact_record.get("consent_given"):
        return text
    raw_name = (contact_record.get("name") or "").strip()
    if not raw_name:
        return text
    first_name = raw_name.split()[0]
    if first_name.lower() in text.lower():
        return text  # ya presente — idempotente

    # Verificar que sea el primer outbound. `history` debe contener solo
    # mensajes previos (no el outbound que estamos por enviar).
    has_prior_outbound = any(
        str(m.get("direction") or "").lower() == "outbound"
        for m in (history or [])
    )
    if has_prior_outbound:
        return text

    # Rev. 104 — Integrar el nombre DENTRO del saludo existente (Hola o
    # time-specific). Evita prefijar "Hola, X." cuando el LLM ya emitió
    # un saludo time-aware ("Buenas tardes!"), lo cual causaba duplicación
    # de saludos al pasar por el invariant time-aware downstream.
    #
    # Patrones (orden = preferencia):
    #   1. Saludos time-specific con `!`: "Buenos días!" → "Buenos días, X!"
    #   2. Saludos time-specific sin `!`: "Buenos días " → "Buenos días, X "
    #   3. "Hola" en sus formas comunes (¡Hola!, Hola!, Hola, Hola ).
    # El primer patrón que matchea inyecta el nombre y termina.
    patterns = [
        # Time-specific con `!` (con o sin `¡` opening — el format pipeline
        # strip `¡` después, pero podríamos verlo aquí pre-strip).
        (re.compile(r"^¡?(Buenos?\s+d[íi]as?)!", re.IGNORECASE),
            rf"\1, {first_name}!"),
        (re.compile(r"^¡?(Buenas?\s+tardes?)!", re.IGNORECASE),
            rf"\1, {first_name}!"),
        (re.compile(r"^¡?(Buenas?\s+noches?)!", re.IGNORECASE),
            rf"\1, {first_name}!"),
        # Time-specific sin `!` (acompañado de espacio o coma).
        (re.compile(r"^¡?(Buenos?\s+d[íi]as?)(?=[\s,])", re.IGNORECASE),
            rf"\1, {first_name}"),
        (re.compile(r"^¡?(Buenas?\s+tardes?)(?=[\s,])", re.IGNORECASE),
            rf"\1, {first_name}"),
        (re.compile(r"^¡?(Buenas?\s+noches?)(?=[\s,])", re.IGNORECASE),
            rf"\1, {first_name}"),
        # Hola variantes.
        (re.compile(r"^¡Hola!"), f"¡Hola, {first_name}!"),
        (re.compile(r"^¡Hola\s"), f"¡Hola, {first_name} "),
        (re.compile(r"^Hola!"), f"Hola, {first_name}!"),
        (re.compile(r"^Hola\b"), f"Hola, {first_name}"),
    ]
    for pat, repl in patterns:
        if pat.match(text):
            return pat.sub(repl, text, count=1)

    # No empieza con saludo conocido — prefijar saludo personalizado mínimo.
    return f"Hola, {first_name}. {text}"


# Términos típicos de KB regulatoria que mejoran la lectura WhatsApp
# si quedan en *negrita*. Aplica solo si el outbound tiene cita Fuente:.
_BOLD_KB_PATTERNS: list[str] = [
    # Plazos específicos primero (más largos = más específicos).
    # IMPORTANTE: NO incluir un patrón genérico "\d+\s*días" porque
    # solaparía con "X días calendario / hábiles" causando doble-bold.
    r"\d+\s*d[ií]as\s+calendario",
    r"\d+\s*d[ií]as\s+h[áa]biles",
    r"\d+\s*horas?\s+(?:h[áa]biles|calendario)",
    # Términos contractuales/legales recurrentes.
    r"sin\s+usar",
    r"empaque\s+original",
    r"perfectas?\s+condiciones?",
    r"producto\s+defectuoso",
    r"ofertas?\s+especiales?",
    r"contacto\s+con\s+la\s+piel",
    r"n[úu]mero\s+de\s+pedido",
]


def _bold_kb_terms(text: str) -> str:
    """Rev. 103 — post-process determinístico: envuelve en *negrita* los
    términos recurrentes de KB regulatoria (devoluciones, garantías) que
    mejoran la legibilidad del cliente en pantalla WhatsApp.

    Solo aplica si la respuesta tiene cita `Fuente:` (señal de KB).
    Idempotente: si ya está en negrita, no duplica.

    Sigue el patrón de `_truncate_category_listings`,
    `_enhance_kb_citation` e `_inject_known_customer_name`.
    """
    if not text or "Fuente:" not in text:
        return text
    if not isinstance(text, str):
        return text
    out = text
    for pattern in _BOLD_KB_PATTERNS:
        # Lookbehind/lookahead negativo para `*`: evita re-envolver
        # si el LLM ya puso el término en negrita.
        regex = re.compile(rf"(?<!\*)({pattern})(?!\*)", re.IGNORECASE)
        # `count=1` por patrón — destacar 1ra aparición; evita saturar.
        out = regex.sub(r"*\1*", out, count=1)
    return out


def _enhance_kb_citation(text: str) -> str:
    """Rev. 92 — Si la respuesta tiene `_Fuente: TITLE_` (cita KB en
    cursiva del LLM rev. 78), transforma el bloque final a:

        <cuerpo de la respuesta>

        <CTA invitacional>

        > Fuente: TITLE

    Garantiza separadores `\\n\\n` (párrafo) antes del CTA y antes del
    blockquote — el LLM tiende a pegar el cite directo al cuerpo sin
    blank line.

    Razones del cambio:
      • Cita en cursiva sin URL = etiqueta colgada (cliente no puede
        consultar el documento).
      • Blockquote (`>`) separa visualmente y se identifica como
        referencia.
      • CTA invita al cliente a profundizar dentro del mismo chat.

    Idempotente: si ya hay `> Fuente:` o el CTA, no duplica.
    """
    if not text or "_Fuente:" not in text:
        return text
    if "> Fuente:" in text:
        return text
    match = _KB_CITE_RE.search(text)
    if not match:
        return text
    title = match.group(1).strip()
    if not title:
        return text
    cta_present = "házmelo saber" in text or "hazmelo saber" in text

    # Construir el bloque final con separadores explícitos.
    blocks: list[str] = []
    if not cta_present:
        blocks.append(_KB_CITE_CTA)
    blocks.append(f"> Fuente: {title}")
    final_block = "\n\n".join(blocks)

    # Trim whitespace alrededor del cite original para evitar
    # acumulación de saltos (\n\n\n) tras la sustitución.
    before = text[:match.start()].rstrip()
    after = text[match.end():].lstrip()

    result = before + "\n\n" + final_block
    if after:
        result += "\n\n" + after
    return result


def _ensure_kb_citation_present(text: str, kb_docs: list[dict]) -> str:
    """Rev. 103 — Garantiza cita KB cuando el LLM la omitió.

    El system prompt instruye al LLM a cerrar con `_Fuente: <título>_`
    cuando usa la KB, pero en runs reales el modelo a veces lo olvida
    (variabilidad ~5-15% según largo del contexto). Este post-process
    determinístico cubre ese gap:

      • Si el outbound tiene ≥ 30 chars verbatim de un kb_doc real →
        anexa `_Fuente: <título>_` al final.
      • Idempotente: si ya hay `_Fuente:` o `> Fuente:`, no toca.

    Detección verbatim (no paraphrase): asegura que solo agrega cita
    cuando el LLM realmente copió contenido de la KB. Evita falsos
    positivos en respuestas que mencionan tópicos cubiertos por la KB
    pero no la usan (ej. "tenemos política de devoluciones" sin citar
    el plazo concreto).

    El upgrade visual a `> Fuente: X` lo hace `_enhance_kb_citation`
    durante el formato WhatsApp.
    """
    if not text or not kb_docs:
        return text
    if "_Fuente:" in text or "> Fuente:" in text:
        return text

    text_norm = re.sub(r"\s+", " ", text).strip()
    if len(text_norm) < 30:
        return text

    best_overlap = 0
    best_title = ""
    for doc in kb_docs:
        if doc.get("_synthetic_missing"):
            continue
        title = (doc.get("title") or "").strip()
        content = (doc.get("content") or "").strip()
        if not title or len(content) < 30:
            continue
        content_norm = re.sub(r"\s+", " ", content)
        # Slide window 30 chars step 5 — busca overlap verbatim.
        for i in range(0, max(0, len(text_norm) - 30) + 1, 5):
            chunk = text_norm[i:i + 30]
            if chunk in content_norm:
                if len(chunk) > best_overlap:
                    best_overlap = len(chunk)
                    best_title = title
                break

    if not best_title:
        return text
    logger.info(
        "[KB_CITE] LLM omitió cita — anexando _Fuente: %s (overlap=%d)",
        best_title, best_overlap,
    )
    return text.rstrip() + f"\n\n_Fuente: {best_title}_"


# ── Rev. 92 — Listado truncado determinístico ────────────────────────────────

_CATEGORY_HEADER_RE = re.compile(r"^\*[^*\n]+:\*\s*$")
_BULLET_LINE_RE = re.compile(r"^\* (?!_Entre otros)\S")
_TRUNCATED_MARKER = "* _Entre otros..._"
_MARKETING_CITE = (
    "> _Tenemos muchas más referencias para ti — pregúntame por la "
    "que te interese._ "
)


def _truncate_category_listings(text: str) -> str:
    """Rev. 92 — Si el outbound es un listado de catálogo, trunca cada
    categoría a MÁXIMO 2 ítems concretos + un 3er bullet `* _Entre otros..._`
    cuando hay ≥3 ítems en la categoría. Si al menos UNA categoría fue
    truncada, agrega cita marketing al final.

    Reglas aplicadas:
      • Categoría = línea `*Header:*` seguida de bullets `* item`.
      • Si la categoría tiene ≥3 bullets → corta a 2 + `* _Entre otros..._`.
      • Si la categoría tiene ≤2 bullets → no toca.
      • Si al menos 1 categoría fue truncada → append cita marketing.

    Skip por seguridad — NUNCA trunca:
      • Resúmenes de pedido (`📋` o `*TOTAL:` o `*Resumen`).
      • Cotizaciones de envío (texto contiene "Económica" o "transportadora").
      • Cualquier texto que no tenga al menos 1 cabecera de categoría.

    El LLM no honra confiablemente la regla del prompt; este post-process
    determinístico garantiza la UX.
    """
    if not text or not isinstance(text, str):
        return text

    # Skip-conditions: nunca tocamos summaries / cotizaciones / carts.
    skip_markers = (
        "📋", "*TOTAL:", "*Resumen", "Económica", "Rápida",
        "transportadora", "*Datos de envío", "¿Confirmas",
        "*Productos:*",  # Cart summary o order ack — items deben verse todos.
    )
    if any(marker in text for marker in skip_markers):
        return text
    # Skip si CUALQUIER bullet tiene prefijo cart-quantity (ej. "* 2x ...").
    if re.search(r"(?m)^\* \d+x ", text):
        return text

    lines = text.split("\n")
    out: list[str] = []
    i = 0
    truncated_any = False
    has_any_category = False

    while i < len(lines):
        line = lines[i]
        if _CATEGORY_HEADER_RE.match(line):
            has_any_category = True
            out.append(line)
            i += 1
            # Recolectar bullets que siguen (saltando líneas en blanco intermedias).
            bullets: list[str] = []
            while i < len(lines):
                ln = lines[i]
                if _BULLET_LINE_RE.match(ln):
                    bullets.append(ln)
                    i += 1
                    continue
                break
            if len(bullets) >= 3:
                out.extend(bullets[:2])
                out.append(_TRUNCATED_MARKER)
                truncated_any = True
            else:
                out.extend(bullets)
        else:
            out.append(line)
            i += 1

    # Si no detectamos categorías, devolver intacto.
    if not has_any_category:
        return text

    result = "\n".join(out)
    if truncated_any and "Tenemos muchas más referencias" not in result:
        # Append con doble salto antes para separar visualmente.
        result = result.rstrip() + "\n\n" + _MARKETING_CITE
    return result


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
        conversation_status = _get_conversation_status(supabase, tenant_id, conversation_id)
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

        # Fix founder 2026-05-28 — opt-out EN CUALQUIER SITUACIÓN.
        # Cliente revocó consent (Habeas Data Ley 1581 ART. 9): el bot NO
        # debe responder ni siquiera a un mensaje no-STOP. Operador puede
        # reactivar manual desde Inbox UI si el cliente da re-consent explícito.
        if conversation_status == CONVERSATION_STATUS_OPTED_OUT:
            logger.info(
                "[ORCH] Mensaje %s omitido: conversación en opted_out "
                "(consent revocado, Habeas Data)", message_id,
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_OPTED_OUT,
            )
            return

        # ── 0.5 Resolución temprana: tenant + contacto + historial ────────────────
        # Necesario antes de los gates para personalizar respuestas y verificar estado.
        # Rev. 71 — Saca columnas legacy (business_hours/cutoff_message/dispatch_lead_time)
        # del SELECT. El horario textual se deriva de support_schedule;
        # cutoff_message y dispatch_lead_time eran orphan (sin UI) y se moverán a KB envios.
        # Sem 7 F2 cierre 2026-05-20 — P1+P2 multitenant: agregar
        # business_pitch + product_groups + show_prices_in_catalog al
        # SELECT para que el bot use lenguaje del tenant en vez de
        # hardcoded "KAIU/cosmética".
        tenant_res = supabase.table("tenants").select(
            "name, nit, email_contacto, telefono_contacto, "
            "shipping_origin, store_type, social_links, store_locations, "
            "mision, vision, valores, tono_comunicacion, "
            "support_schedule, after_hours_message, escalation_role, "
            "business_pitch, product_groups, show_prices_in_catalog"
        ).eq("id", tenant_id).execute()
        tenant_row              = tenant_res.data[0] if tenant_res.data else {}
        tenant_name             = tenant_row.get("name") or "Tienda"
        tenant_nit              = tenant_row.get("nit") or ""
        tenant_email_contacto   = tenant_row.get("email_contacto") or ""
        tenant_telefono_contacto= tenant_row.get("telefono_contacto") or ""
        tenant_shipping_origin  = tenant_row.get("shipping_origin") or {}
        tenant_store_type       = tenant_row.get("store_type") or "fisica"
        tenant_social_links     = tenant_row.get("social_links") or {}
        tenant_store_locations  = tenant_row.get("store_locations") or []
        tenant_mision           = tenant_row.get("mision") or ""
        tenant_vision           = tenant_row.get("vision") or ""
        tenant_valores          = tenant_row.get("valores") or ""
        tenant_tono             = tenant_row.get("tono_comunicacion") or "amigable"
        tenant_support_schedule = tenant_row.get("support_schedule") or {}
        tenant_after_hours_msg  = tenant_row.get("after_hours_message") or ""
        # Rev. 68 — escalation_role configurable por tenant (default 'asesor').
        # Se usa en mensajes de escalación al humano para alinear el término al
        # lenguaje de la marca (asesor / especialista / consultor / agente).
        # Rev. 103 — fallback "especialista" (no "asesor"): el bot ya se
        # posiciona como asesor/asesora virtual; usar "asesor" para el rol
        # humano crea ambigüedad ("¿con cuál asesor?, ¿no eres tú asesora?").
        # "Especialista" diferencia al humano del bot, suena profesional y
        # cabe en cualquier vertical. Tenant puede sobrescribir por
        # `escalation_role` en `tenants` si prefiere otro término.
        tenant_escalation_role  = tenant_row.get("escalation_role") or "especialista"
        # Sem 7 F2 cierre 2026-05-20 — P1+P2 multitenant config.
        tenant_business_pitch   = (tenant_row.get("business_pitch") or "").strip()
        tenant_product_groups   = tenant_row.get("product_groups") or []
        if not isinstance(tenant_product_groups, list):
            tenant_product_groups = []
        tenant_show_prices      = bool(tenant_row.get("show_prices_in_catalog", True))

        customer_phone_raw: Optional[str] = None
        contact_id: Optional[str] = None
        contact_record: dict = {}
        try:
            customer_phone_raw = _get_conversation_customer_phone(supabase, tenant_id, conversation_id)
            if customer_phone_raw:
                # Rev. 103 — shipping_phone defaultea al WhatsApp para que la
                # transportadora siempre tenga un número (caso real: cliente
                # no menciona alternativo → Envía usa WhatsApp). Si después
                # da otro celular ("el pedido lo recibe mi mamá"), el
                # detector de intent lo sobrescribe en update_data.
                supabase.table("contacts").upsert(
                    {
                        "tenant_id": tenant_id,
                        "phone": customer_phone_raw,
                        "shipping_phone": customer_phone_raw,
                        "consent_given": False,
                    },
                    on_conflict="tenant_id,phone",
                    ignore_duplicates=True,
                ).execute()
                logger.debug("[CONTACT] Upsert contacto %s en tenant %s", customer_phone_raw, tenant_id)
        except Exception as ce:
            logger.warning("[CONTACT] No se pudo upsert contacto: %s", ce)
        try:
            contact_id, contact_record = _fetch_contact_for_phone(
                supabase=supabase, tenant_id=tenant_id, customer_phone_raw=customer_phone_raw,
            )
        except Exception as ce:
            logger.warning("[CONTACT] No se pudo fetch contact para FSM: %s", ce)

        # ── Rev. 105 Sem 4 H.4.1 — STOP keyword detector (Habeas Data + Meta) ──
        # Short-circuit: si el mensaje completo trimmed coincide con un
        # patrón canónico de opt-out (STOP, BAJA, CANCELAR, etc.), revocamos
        # consent (soft, NO anonimiza PII), notificamos al cliente y NO
        # invocamos LLM. Idempotente: STOP repetido refresca timestamp +
        # emite nuevo audit log event sin romper.
        if content_type == "text" and contact_id and customer_phone_raw:
            try:
                from lib.whatsapp_optout import (  # noqa: PLC0415
                    OPTOUT_CONFIRMATION_TEXT,
                    is_optout_keyword,
                    mark_conversation_opted_out,
                    soft_revoke_consent,
                )
                if is_optout_keyword(content):
                    logger.info(
                        "[OPTOUT] Detectado STOP keyword msg=%s conv=%s contact=%s",
                        message_id, conversation_id, contact_id,
                    )
                    revoked = soft_revoke_consent(
                        supabase,
                        tenant_id=tenant_id,
                        contact_id=contact_id,
                        conversation_id=conversation_id,
                        phone=customer_phone_raw,
                    )
                    if revoked:
                        # Audit log evento (Art. 9 Habeas Data trail).
                        _log_consent_event(
                            supabase,
                            tenant_id=tenant_id,
                            contact_id=contact_id,
                            phone=customer_phone_raw,
                            event="revoked",  # canónico (constraint existente)
                            source="whatsapp",
                            conversation_id=conversation_id,
                            evidence={
                                # Granularidad H.4.1 en evidence (constraint
                                # solo conoce 'revoked'; trigger detalla origen).
                                "trigger": "stop_keyword",
                                "keyword_matched": content.strip().lower(),
                                "rev": "105_h41",
                            },
                        )
                        # Marca conversación como opted_out (visibilidad UI
                        # Inbox) — Op-A.2 founder 2026-05-06: status es
                        # transitorio. El connector-whatsapp lo resetea
                        # automáticamente a 'bot_active' al siguiente inbound
                        # del cliente (lógica existente preserva Q3 "no
                        # bloquea futuro"). Operador ve el badge "Opt-out"
                        # en Inbox entre el STOP y la próxima respuesta del
                        # cliente — audit visual transversal.
                        #
                        # IMPORTANTE: contacts.consent_revoked_at es la fuente
                        # de verdad PERMANENTE del opt-out (nunca auto-reset).
                        # Cuando se implemente outbound HSM marketing (H.4.2),
                        # ese flow chequeará consent_revoked_at — bloqueará
                        # envío proactivo aunque la conversación esté bot_active.
                        mark_conversation_opted_out(
                            supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                        )
                        # Envía confirmación de baja al cliente vía WhatsApp.
                        meta_msg_id_optout: Optional[str] = None
                        try:
                            meta_msg_id_optout = await send_whatsapp_message(
                                tenant_id=tenant_id,
                                supabase=supabase,
                                to_phone=customer_phone_raw,
                                text=OPTOUT_CONFIRMATION_TEXT,
                            )
                        except Exception as send_err:
                            logger.error(
                                "[OPTOUT] Falló envío confirmación: %s", send_err,
                            )

                        # Persistir el outbound en messages para que aparezca
                        # en el Inbox del Tenant Console (rev. 105 H.4.1 fix #5).
                        # Si el envío falló (meta_msg_id_optout=None), igual
                        # registramos para trazabilidad — el cliente puede
                        # reportar al operador que no recibió la confirmación.
                        try:
                            supabase.table("messages").insert({
                                "conversation_id": conversation_id,
                                "tenant_id": tenant_id,
                                "direction": "outbound",
                                "content_type": "text",
                                "content": OPTOUT_CONFIRMATION_TEXT,
                                "meta_message_id": meta_msg_id_optout,
                                "processed": True,
                                "processing_status": PROCESSING_STATUS_PROCESSED,
                            }).execute()
                        except Exception as persist_err:
                            logger.error(
                                "[OPTOUT] Falló persist messages outbound: %s",
                                persist_err,
                            )
                        # Marca el mensaje inbound como procesado.
                        _mark_message_processing(
                            supabase,
                            message_id,
                            processing_status=PROCESSING_STATUS_PROCESSED,
                        )
                        return  # Short-circuit: NO continuar con LLM.
                    else:
                        logger.warning(
                            "[OPTOUT] Revocación falló — caemos a flow normal "
                            "msg=%s contact=%s",
                            message_id, contact_id,
                        )
            except Exception as optout_err:
                # Cualquier error en el detector NO debe romper el flow
                # normal del bot — caemos a procesamiento LLM standard.
                logger.error(
                    "[OPTOUT] Error inesperado en detector (cae a LLM): %s",
                    optout_err,
                )

        # ── Rev. 105 Sem 6 I.2.2 — Coupon detector pre-LLM (ADR-0015) ──────
        # Detector híbrido (Decisión 1): regex pre-LLM extrae intent
        # apply/remove + código → llamada directa al helper Python (no LLM
        # decide). Mode A (Decisión 2): respuesta corta + return; intents
        # residuales del cliente ("y quiero 2 jabones") se procesan en
        # próximo turno.
        # FSM Guard (Decisión 3): si cart está en 'checkout' (post-link
        # Wompi), reject con mensaje cita+negrita explicando regla.
        # UX (Decisión 4): respuestas concisas formato WhatsApp.
        if content_type == "text" and customer_phone_raw:
            try:
                from lib.coupon_detector import (  # noqa: PLC0415
                    detect_coupon_intent,
                    INTENT_APPLY,
                    INTENT_REMOVE,
                )
                from lib import coupons as _coupon_helpers  # noqa: PLC0415

                _coupon_intent = detect_coupon_intent(content)
                if _coupon_intent:
                    # Lookup cart en cualquier status open|checkout para
                    # distinguir cupón pre-link vs post-link.
                    _cart_lookup = (
                        supabase.table("conversation_carts")
                        .select(
                            "id, status, subtotal_cents, shipping_cents, "
                            "total_cents, coupon_id, coupon_code, discount_cents"
                        )
                        .eq("tenant_id", tenant_id)
                        .eq("conversation_id", conversation_id)
                        .in_("status", ["open", "checkout"])
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    _cart_rows = _cart_lookup.data or []
                    _coupon_response: Optional[str] = None
                    _coupon_event_type: Optional[str] = None
                    _coupon_event_payload: dict = {}
                    _coupon_cart_id: Optional[str] = None

                    if not _cart_rows:
                        # Sin cart vivo — aplicar cupón no tiene sentido aún.
                        if _coupon_intent.intent == INTENT_APPLY:
                            _coupon_response = (
                                "🛒 Aún no tienes un pedido en curso. "
                                "Cuando agregues productos podemos aplicar tu cupón."
                            )
                        else:
                            _coupon_response = "No tienes ningún cupón aplicado."
                    else:
                        _cart = _cart_rows[0]
                        _coupon_cart_id = _cart["id"]

                        if _cart["status"] == "checkout":
                            # Decisión 3: cupón post-payment-link → reject.
                            # Cita+negrita per sugerencia founder.
                            _coupon_response = (
                                "> *El cupón debe aplicarse antes de generar el link de pago.*\n"
                                "Si quieres usarlo, dime y cancelamos el link actual para rehacer el pedido."
                            )
                        elif _coupon_intent.intent == INTENT_REMOVE:
                            _prev_code = _cart.get("coupon_code")
                            _prev_id = _cart.get("coupon_id")
                            _revoked = _coupon_helpers.revoke_coupon(
                                supabase,
                                tenant_id=tenant_id,
                                cart_id=_coupon_cart_id,
                                reason="user_removed",
                            )
                            if _revoked:
                                _coupon_response = "✅ Cupón removido."
                                _coupon_event_type = "coupon_revoked"
                                _coupon_event_payload = {
                                    "coupon_id": _prev_id,
                                    "code": _prev_code,
                                    "reason": "user_removed",
                                }
                            else:
                                _coupon_response = "No tenías ningún cupón aplicado."
                        elif _coupon_intent.intent == INTENT_APPLY:
                            if not _coupon_intent.code:
                                _coupon_response = (
                                    "No detecté el código del cupón. "
                                    "¿Me lo confirmas?"
                                )
                            else:
                                _result = _coupon_helpers.apply_coupon(
                                    supabase,
                                    tenant_id=tenant_id,
                                    cart_id=_coupon_cart_id,
                                    code=_coupon_intent.code,
                                )
                                if _result.ok:
                                    _descuento_str = (
                                        f"${_result.discount_cents / 100:,.0f}"
                                        .replace(",", ".")
                                    )
                                    _coupon_response = (
                                        f"✅ Cupón *{_result.coupon_code}* aplicado: "
                                        f"descuento -{_descuento_str}\n"
                                        f"¿En qué más te puedo ayudar?"
                                    )
                                    _coupon_event_type = "coupon_applied"
                                    _coupon_event_payload = {
                                        "coupon_id": _result.coupon_id,
                                        "code": _result.coupon_code,
                                        "discount_cents": _result.discount_cents,
                                    }
                                else:
                                    # ValidationResult.user_message ya en ES.
                                    _coupon_response = _result.user_message

                    if _coupon_response:
                        # Emit cart_event si hubo cambio real (apply/revoke OK).
                        if _coupon_event_type and _coupon_cart_id:
                            try:
                                supabase.table("cart_events").insert({
                                    "cart_id": _coupon_cart_id,
                                    "tenant_id": tenant_id,
                                    "event_type": _coupon_event_type,
                                    "event_payload": _coupon_event_payload,
                                    "triggered_by": "bot",
                                    "correlation_id": message_id,
                                }).execute()
                            except Exception as _evt_err:
                                logger.debug(
                                    "[COUPON][EVENT] emit %s falló: %s",
                                    _coupon_event_type, _evt_err,
                                )

                        logger.info(
                            "[COUPON][DISPATCH] tenant=%s conv=%s intent=%s "
                            "code=%s cart=%s event=%s",
                            tenant_id, conversation_id,
                            _coupon_intent.intent, _coupon_intent.code,
                            _coupon_cart_id, _coupon_event_type,
                        )

                        # Send WhatsApp + persist outbound + mark + return.
                        _meta_msg_id_coupon: Optional[str] = None
                        try:
                            _meta_msg_id_coupon = await send_whatsapp_message(
                                tenant_id=tenant_id,
                                supabase=supabase,
                                to_phone=customer_phone_raw,
                                text=_coupon_response,
                            )
                        except Exception as _send_err:
                            logger.error(
                                "[COUPON] Falló envío respuesta: %s", _send_err,
                            )

                        try:
                            supabase.table("messages").insert({
                                "conversation_id": conversation_id,
                                "tenant_id": tenant_id,
                                "direction": "outbound",
                                "content_type": "text",
                                "content": _coupon_response,
                                "meta_message_id": _meta_msg_id_coupon,
                                "processed": True,
                                "processing_status": PROCESSING_STATUS_PROCESSED,
                            }).execute()
                        except Exception as _persist_err:
                            logger.error(
                                "[COUPON] Falló persist messages: %s",
                                _persist_err,
                            )

                        _mark_message_processing(
                            supabase, message_id,
                            processing_status=PROCESSING_STATUS_PROCESSED,
                        )
                        return  # Short-circuit: NO continuar con LLM.
            except Exception as _coupon_err:
                # Cualquier error en detector NO debe romper flow normal —
                # caemos a procesamiento LLM standard.
                logger.error(
                    "[COUPON] Error inesperado en detector (cae a LLM): %s",
                    _coupon_err,
                )

        history: list[dict] = await _get_conversation_history(supabase, tenant_id, conversation_id)

        # Primer nombre: solo si hay consentimiento explícito en DB
        first_name = (
            _extract_first_name(contact_record.get("name"))
            if contact_record.get("consent_given") else None
        )

        # Gate 1: no-texto.
        # Multimodal: si es audio y feature está activo, transcribimos con Gemini
        # y dejamos que el flow normal procese el texto. Si falla, continuamos
        # al gate humanizado de advertencia (comportamiento legacy).
        if content_type == "audio":
            media_row = (
                supabase.table("messages")
                .select("media_id, media_mime")
                .eq("id", message_id)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            mrow = (media_row.data or [{}])[0]
            transcription = await _transcribe_audio_or_none(
                tenant_id=tenant_id,
                supabase=supabase,
                media_id=mrow.get("media_id"),
                media_mime=mrow.get("media_mime"),
            )
            if transcription:
                # Persistir la transcripción en el mismo registro para trazabilidad
                # (content vacío "[Audio recibido]" → content="[Audio] {transcripcion}")
                try:
                    (
                        supabase.table("messages")
                        .update({"content": f"[Audio] {transcription}"})
                        .eq("id", message_id)
                        .eq("tenant_id", tenant_id)
                        .execute()
                    )
                except Exception:
                    pass
                # Continuar el flow normal con la transcripción como content y type=text
                content = transcription
                content_type = "text"

        if content_type != "text":
            if _had_non_text_warning(history):
                logger.info(
                    "[ORCH] Mensaje %s no-text (%s): cliente insiste → human_takeover",
                    message_id, content_type,
                )
                _set_conversation_status(
                    supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
                )
                _mark_message_processing(
                    supabase, message_id,
                    processing_status=PROCESSING_STATUS_SKIPPED,
                    skip_reason=SKIP_REASON_NON_TEXT,
                )
            else:
                logger.info(
                    "[ORCH] Mensaje %s no-text (%s): primera advertencia enviada",
                    message_id, content_type,
                )
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=(
                        "Por ahora solo puedo atender mensajes de texto. \n\n"
                        f"Si necesitas que un {tenant_escalation_role} revise lo que enviaste, "
                        f"dímelo y te conecto con él."
                    ),
                )
                _mark_message_processing(
                    supabase, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
            return

        # Gate: solicitud explícita de humano (rev. 68 — admite múltiples términos
        # para que el cliente pueda usar "asesor", "especialista", "consultor" o
        # "agente" sin importar cómo el tenant configuró el rol de escalación).
        _norm = _normalize_text_simple(content).strip()
        _ESCALATION_TRIGGERS = {
            "asesor", "un asesor", "quiero asesor", "necesito asesor", "hablar con asesor",
            "especialista", "un especialista", "quiero especialista", "necesito especialista", "hablar con especialista",
            "consultor", "un consultor", "quiero consultor", "necesito consultor", "hablar con consultor",
            "agente", "un agente", "quiero agente", "necesito agente", "hablar con agente",
            "humano", "un humano", "persona real",
        }
        if _norm in _ESCALATION_TRIGGERS:
            # Gate fuera de horario — enviar mensaje antes de escalar si está configurado
            if tenant_after_hours_msg and _is_outside_support_hours(tenant_support_schedule):
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    text=tenant_after_hours_msg,
                )
                logger.info("[ORCH] Fuera de horario — mensaje after_hours enviado | conv=%s", conversation_id)
            else:
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    text=f"Entendido, te conecto con un {tenant_escalation_role}. ¡Un momento! ",
                )
            _set_conversation_status(supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            return

        # F3B Gate: comando "cancelar" — cancela pedido pending_payment y resetea FSM implícito
        if _normalize_text_simple(content).strip() in _CANCEL_TOKENS:
            cancelled = _cancel_pending_payment_order(supabase, conversation_id, tenant_id)
            _seed = _today_seed(conversation_id)
            if cancelled:
                reply = _pick_variant(_CANCEL_SUCCESS_VARIANTS, seed=_seed)
            else:
                reply = _pick_variant(_CANCEL_NONE_VARIANTS, seed=_seed)
            await _send_outbound_text(
                supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                text=reply,
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info("[ORCH] Comando cancelar | conv=%s cancelled=%s", conversation_id, cancelled)
            return

        # F3A: Ventana de conversación 24h
        # Si expiró, forzar CATALOG_MODE en FSM Y enviar mensaje de reactivación al cliente.
        # No silenciar — el cliente merece saber que puede empezar de nuevo.
        _window_expired = _is_conversation_window_expired(supabase, tenant_id, conversation_id)
        if _window_expired:
            logger.info(
                "[ORCH] Ventana de conversación expirada (>%sh) | conv=%s — reiniciando con mensaje de reactivación",
                CONVERSATION_WINDOW_HOURS, conversation_id,
            )
            _reactivation_msg = _pick_variant(
                _REACTIVATION_VARIANTS, seed=_today_seed(conversation_id)
            )
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=_reactivation_msg,
            )

        # ── 2.5 Respuesta de consentimiento (ANTES de cualquier tool determinístico) ──
        # Si el último mensaje del bot fue la pregunta de consentimiento, el
        # cliente está respondiendo Sí/No — manejarlo aquí. Si dejamos pasar,
        # shipping_quote_tool puede interceptar "Sí autorizo" como confirmación
        # de carrier / cotización por el contexto previo.
        recent_history_for_consent = history[-4:] if history else []
        if contact_id and _last_outbound_was_consent_question(recent_history_for_consent):
            if _detect_consent_yes(content):
                _record_consent(supabase, contact_id, tenant_id, given=True, conversation_id=conversation_id)
                # Bug 27 (Ley 1581) recovery: el cliente posiblemente mencionó
                # datos personales antes del consent — ahora que autorizó,
                # extraerlos del history y persistirlos sin tener que pedirlos
                # de nuevo. Email vía regex (determinístico). Nombre/dirección
                # quedan para el próximo turn del LLM (regla en system prompt).
                _pii_recovered: dict = {}
                _full_inbound = " ".join(
                    str(m.get("content") or "") for m in (history or [])
                    if str(m.get("direction") or "").lower() == "inbound"
                )
                _email_m = _EMAIL_SEARCH_REGEX.search(_full_inbound) if _full_inbound else None
                if _email_m:
                    _pii_recovered["email"] = _email_m.group(0).lower()
                if _pii_recovered:
                    try:
                        supabase.table("contacts").update(_pii_recovered).eq("id", contact_id).eq("tenant_id", tenant_id).execute()  # A6.2.7: PII cross-tenant
                        logger.info("[CONSENT][PII] Recuperado del history: %s", list(_pii_recovered.keys()))
                    except Exception as exc:
                        logger.warning("[CONSENT][PII] Error persistiendo recovery: %s", exc)

                refreshed_contact_id, refreshed_contact_record = _fetch_contact_for_phone(
                    supabase=supabase,
                    tenant_id=tenant_id,
                    customer_phone_raw=customer_phone_raw,
                )
                if refreshed_contact_id:
                    contact_id = refreshed_contact_id
                if refreshed_contact_record:
                    contact_record = refreshed_contact_record
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=_build_next_data_request_prompt(contact_record),
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CONSENT] Aceptado | conversation=%s contact=%s", conversation_id, contact_id)
                return
            elif _detect_consent_no(content):
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=(
                        "Entendido, no guardo tus datos. \n\n"
                        "Sin embargo, para cerrar la compra y enviarte el pedido, "
                        "Wompi y la transportadora necesitan al menos tu nombre, "
                        "correo, documento y dirección. Si cambias de idea avísame "
                        f"y los registramos de forma segura, o te conecto con un {tenant_escalation_role} "
                        "que te ayude por otra vía."
                    ),
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CONSENT] Rechazado | conversation=%s", conversation_id)
                return

        # ── 2.7 ToolDispatcher — image_send | shipping_quote | order_status ─
        # Rev. 104 (F1-3): los tres tools determinísticos pre-LLM se evalúan
        # via `tools/inbound_dispatcher.py`. El primer handler con
        # `handled=True` gana; el post-procesamiento se selecciona por
        # `result.meta["tool"]`.
        #
        # Gates pre-flight pasados por `ctx.metadata`:
        #   • `skip_shipping_quote`: True si último outbound fue pregunta de
        #     consent o data-collection y NO hay cambio explícito de ciudad
        #     (recolección activa de PII — el inbound es la respuesta, no
        #     una nueva intención de cotizar).
        #   • `shipping_query_override`: query reescrito a "cotizar envío a
        #     <new_city>" cuando el cliente pidió cambiar destino post-quote.
        #
        # Side-effect cart-as-SoT (F0-3 / BUG-1) se ejecuta ANTES del
        # dispatch porque es independiente del handler shipping_quote.
        _last_oc_consent = _last_outbound_was_consent_question(history or [])
        _last_oc_data_request = _last_outbound_was_data_collection_question(history or [])
        _explicit_location_change = _detect_shipping_location_change(
            content, history or []
        )
        _skip_shipping = bool(
            (_last_oc_consent or _last_oc_data_request)
            and not _explicit_location_change
        )
        if _skip_shipping:
            logger.info(
                "[SHIPPING_QUOTE][SKIP] last_oc_consent=%s last_oc_data=%s — recolección activa",
                _last_oc_consent, _last_oc_data_request,
            )
        _new_city = _explicit_location_change
        _shipping_query_override: str | None = (
            f"cotizar envío a {_new_city}" if _new_city else None
        )
        if _new_city:
            logger.info(
                "[SHIPPING_LOCATION_CHANGE] cliente cambió a %s — re-quote forzado",
                _new_city,
            )
            try:
                from tools.cart_tool import get_cart_with_items, set_shipping_city
                _cart_for_city = get_cart_with_items(
                    supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                )
                if _cart_for_city and _cart_for_city.get("id"):
                    set_shipping_city(
                        supabase,
                        cart_id=_cart_for_city["id"],
                        new_city=_new_city,
                        tenant_id=tenant_id,
                    )
            except Exception as _city_exc:
                logger.warning(
                    "[SHIPPING_LOCATION_CHANGE] set_shipping_city falló: %s",
                    _city_exc,
                )

        from tools.inbound_dispatcher import build_inbound_dispatcher
        from tools.dispatcher import ToolContext as _ToolContext
        _dispatcher = build_inbound_dispatcher()
        # `display_state` se resuelve más abajo con FSM — no relevante aquí.
        _ds_for_dispatch = locals().get("display_state") or ""
        _dispatch_ctx = _ToolContext(
            supabase=supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            contact_record=contact_record or {},
            content=content,
            history=history or [],
            catalog=[],
            display_state=_ds_for_dispatch,
            metadata={
                "skip_shipping_quote": _skip_shipping,
                "shipping_query_override": _shipping_query_override,
            },
        )
        _dispatch_result, _dispatch_name = await _dispatcher.dispatch(_dispatch_ctx)

        if _dispatch_result.handled:
            _tool_id = _dispatch_result.meta.get("tool", _dispatch_name or "")
            if _tool_id == "image_send":
                _img_link = _dispatch_result.meta.get("image_link")
                _img_caption = _dispatch_result.meta.get("image_caption")
                if _img_link:
                    # Rev. 103 — enriquecer caption con conector cordial +
                    # nombre del cliente si conocido (humaniza el envío).
                    _enriched_caption = _enrich_image_caption(
                        _img_caption or "",
                        contact_record=contact_record,
                        history=history,
                    )
                    # Rev. 104 — aplicar el mismo format pipeline que outbound
                    # text (bullets canónicos, bold, strip `¡`/`¿`, etc.). Sin
                    # esto los image captions iban bypass y mantenían signos
                    # opening que rompían el estilo casual colombiano.
                    _enriched_caption = _format_whatsapp_response_text(
                        _enriched_caption
                    )
                    _meta_id = await send_whatsapp_message(
                        tenant_id=tenant_id,
                        supabase=supabase,
                        to_phone=customer_phone_raw or "",
                        image_link=_img_link,
                        image_caption=_enriched_caption,
                    )
                    try:
                        supabase.table("messages").insert({
                            "conversation_id": conversation_id,
                            "tenant_id": tenant_id,
                            "direction": "outbound",
                            "content_type": "image",
                            "content": _enriched_caption or "",
                            "media_url": _img_link,
                            "meta_message_id": _meta_id,
                            "processed": True,
                            "processing_status": "processed",
                        }).execute()
                    except Exception as exc:
                        logger.warning("[IMAGE_SEND] persist outbound falló: %s", exc)
                    logger.info(
                        "[IMAGE_SEND] foto enviada conv=%s link=%s",
                        conversation_id, _img_link,
                    )
                elif _dispatch_result.response_text:
                    await _send_outbound_text(
                        supabase=supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=_dispatch_result.response_text,
                    )
            elif _tool_id == "shipping_quote":
                if _dispatch_result.response_text:
                    # Si es la primera respuesta del bot, prefijar saludo
                    # natural — el cliente abrió con "Hola" + pedido combinado
                    # y el tool determinístico no incluye saludo.
                    _resp_text = _dispatch_result.response_text
                    _outbound_count = sum(
                        1 for m in (history or [])
                        if str(m.get("direction") or "").lower() == "outbound"
                        and str(m.get("content_type") or "text") != "context_snapshot"
                    )
                    if _outbound_count == 0:
                        _first_name_greet = _extract_first_name(
                            contact_record.get("name") if isinstance(contact_record, dict) else None
                        )
                        _td_greet, _ = _co_time_of_day_greeting()
                        _greet = (
                            f"{_td_greet}, {_first_name_greet}. "
                            if _first_name_greet else f"{_td_greet}. "
                        )
                        _resp_text = f"{_greet}\n\n{_resp_text}"
                    await _send_outbound_text(
                        supabase=supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=_resp_text,
                    )
            else:  # order_status u otros futuros con send_text simple
                if _dispatch_result.response_text:
                    await _send_outbound_text(
                        supabase=supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=_dispatch_result.response_text,
                    )
            if _dispatch_result.requires_human:
                _set_conversation_status(
                    supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER,
                )
            _mark_message_processing(
                supabase, message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        # ── 2. Obtener catálogo, RAG KB y Config. AI (paralelo; historial ya cargado) ──
        # NOTA: ya no hay gates determinísticos pre-Gemini para saludos/agradecimientos.
        # Todo mensaje pasa al agente configurado (con su nombre, tono, catálogo y KB)
        # para mantener consistencia de marca desde el primer mensaje.
        catalog, kb_docs, ai_agent = await __import__('asyncio').gather(
            get_tenant_catalog(supabase, tenant_id),
            get_tenant_kb_rag(supabase, tenant_id, content),
            _get_tenant_ai_agent(supabase, tenant_id)
        )
        kb_text = format_kb_for_prompt(kb_docs)
        logger.info(
            "[CTX] tenant=%s | catalog=%d productos | kb_docs=%d | agent='%s'",
            tenant_id, len(catalog), len(kb_docs), ai_agent.get("name", "?"),
        )

        # ── 2.4 Crisis de salud mental (rev. 84 P0 · Meta compliance) ─────────
        # Prioridad MÁXIMA — antes de cualquier otra lógica. Mensaje de
        # seguridad + escalación inmediata. NO procesa por LLM (riesgo de
        # respuesta inapropiada). El humano evaluará el caso.
        if _detect_mental_health_crisis(content):
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "Lamento mucho que estés pasando por esto. \n\n"
                    "Tu bienestar es lo más importante. Por favor contacta "
                    "una línea de apoyo profesional ahora mismo:\n\n"
                    "• Colombia — Línea de la vida 106 (Bogotá) o 123 "
                    "(emergencias nacionales)\n"
                    "• Acude a urgencias o a un servicio de salud mental "
                    "en tu localidad.\n\n"
                    "Te conecto también con un asesor humano de inmediato."
                ),
            )
            try:
                supabase.table("conversations").update({
                    "status": "human_takeover",
                    "human_takeover_reason": "mental_health_crisis",
                }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()  # A6.2.7
            except Exception as _crisis_err:
                logger.error("[CRISIS] no pude marcar takeover: %s", _crisis_err)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.warning(
                "[CRISIS] Mental health crisis detectada conv=%s — escalación inmediata",
                conversation_id,
            )
            return

        # ── 2.45 Datos sensibles (rev. 84 · Meta compliance PCI) ───────────────
        # Cliente envió tarjeta de crédito o CVV en el chat. NO procesar
        # por LLM (queda en logs/history). Advertir y guiar al widget Wompi.
        _is_sensitive, _sensitive_reason = _detect_sensitive_payment_data(content)
        if _is_sensitive:
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "Por tu seguridad, **no envíes** datos de tarjeta o "
                    "CVV por este chat — no son canales seguros.\n\n"
                    "Cuando generemos tu link de pago, Wompi te pedirá esos "
                    "datos en su widget cifrado. Yo nunca los necesito acá."
                ),
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.warning(
                "[PCI] Datos sensibles detectados conv=%s reason=%s — bot advirtió y descartó",
                conversation_id, _sensitive_reason,
            )
            return

        # ── 2.46 Consulta médica / diagnóstica (rev. 92.b · Meta Healthcare) ──
        # Meta Business Policy prohíbe telemedicina/diagnóstico vía WhatsApp
        # en sistemas no compliant. Aplica a TODO tenant sin importar vertical
        # (cosmética, tech, comida, etc.) — el bot nunca diagnostica ni
        # recomienda tratamiento médico.
        # Cobertura legal: Ley 23 de 1981 Colombia (ejercicio ilegal de
        # medicina sin licencia).
        if _detect_medical_query(content):
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "Soy un asesor virtual y no doy diagnósticos ni "
                    "recomendaciones médicas — para eso consulta a tu "
                    "profesional de salud. \n\n"
                    "Si tienes una pregunta sobre los productos "
                    "(características, ingredientes o beneficios generales), "
                    "con gusto te ayudo."
                ),
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.warning(
                "[META_HEALTHCARE] Consulta médica detectada conv=%s — bot redirigió a profesional",
                conversation_id,
            )
            return

        # ── 2.47 Solicitud de medicamentos (rev. 92.b · Meta Commerce) ────────
        # Meta Commerce Policy prohíbe venta de Rx y OTC en WhatsApp en
        # CUALQUIER tenant (Rx + OTC + suplementos). Bot redirige a
        # droguería/farmacia con wording vertical-agnóstico.
        if _detect_drug_purchase_request(content):
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "No comercializamos medicamentos. Para eso lo mejor "
                    "es tu droguería o farmacia de confianza. \n\n"
                    "Si te interesa algo de nuestro catálogo, dime y te "
                    "ayudo a encontrarlo."
                ),
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.warning(
                "[META_COMMERCE] Solicitud medicamento detectada conv=%s — bot rechazó cordialmente",
                conversation_id,
            )
            return

        # ── 2.45 Detección determinística de minoría de edad (rev. 102) ────────
        # Prioridad máxima absoluta: Decreto 1377/2013 Art. 7 prohíbe tratamiento
        # de datos de menores sin autorización del representante legal. Si el
        # cliente declara ser menor, NO continuamos NINGÚN flujo comercial —
        # respondemos cordialmente pidiendo el representante + escalamos a humano.
        if _detect_minor_intent(content):
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "Por nuestra política de protección de datos no podemos "
                    "continuar con la compra directamente contigo (Habeas Data "
                    "Ley 1581/2012, Decreto 1377 Art. 7). Necesitamos que tu "
                    "padre, madre o tutor legal nos escriba a este chat para "
                    "autorizar la operación. Mientras tanto, un asesor del "
                    "equipo te contactará si lo necesitas."
                ),
            )
            # Audit: queda registro de que el cliente declaró minoría de edad y
            # que NO se procesó la solicitud comercial.
            try:
                phone_for_audit = None
                if contact_id:
                    p_res = supabase.table("contacts").select("phone").eq(
                        "id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
                    if p_res.data:
                        phone_for_audit = p_res.data[0].get("phone")
                # Reuse del helper de consent audit (event=rectified pendiente
                # review parece el más cercano semánticamente; alternativa:
                # extender el CHECK del enum si se requiere event específico).
                _log_consent_event(
                    supabase,
                    tenant_id=tenant_id,
                    contact_id=contact_id or "00000000-0000-0000-0000-000000000000",
                    phone=phone_for_audit,
                    event="rectified",
                    source="whatsapp",
                    conversation_id=conversation_id,
                    evidence={
                        "reason": "minor_age_declared",
                        "law": "Decreto 1377/2013 Art. 7",
                        "action": "escalated_to_human_pending_legal_representative",
                        "raw_message_excerpt": content[:200],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:
                logger.warning("[MINOR] audit log falló: %s", exc)
            # Escala a humano: marca conversación como takeover para que un
            # operador adulto retome (validación de identidad del representante
            # requiere criterio humano).
            try:
                supabase.table("conversations").update({
                    "status": CONVERSATION_STATUS_HUMAN_TAKEOVER,
                }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
            except Exception as exc:
                logger.warning("[MINOR] escalation status update falló: %s", exc)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.warning(
                "[MINOR] Detectada minoría de edad conv=%s — flujo comercial bloqueado, escalado a humano",
                conversation_id,
            )
            return

        # ── 2.5 Detección determinística de revocación (ANTES del LLM) ─────────
        # Prioridad máxima: el titular siempre puede revocar el consentimiento.
        # Rev. 103 — bifurcamos según si REALMENTE hay datos personales que
        # eliminar. Si el cliente nunca dio consent ni PII, el bot da
        # tranquilidad sin afirmar falsamente "tus datos fueron eliminados".
        if _detect_revocation_intent(content):
            phone_for_notify: Optional[str] = None
            had_data_to_revoke = False
            if contact_id and isinstance(contact_record, dict):
                # Capturar phone ANTES del UPDATE para hashearlo en notificación.
                phone_for_notify = contact_record.get("phone")
                # Determinar si hay datos reales que eliminar:
                #   - consent_given=True (consentimiento activo), o
                #   - cualquier PII registrada (name/email/doc/address).
                had_consent = contact_record.get("consent_given") is True
                had_pii = any(
                    contact_record.get(k)
                    for k in ("name", "email", "document_number", "address")
                )
                had_data_to_revoke = had_consent or had_pii

            if had_data_to_revoke and contact_id:
                # Path A — revocación legal real (Art. 9 + 15).
                _record_consent(
                    supabase, contact_id, tenant_id,
                    given=False, conversation_id=conversation_id,
                )
                outbound_text = (
                    "Tus datos personales han sido eliminados de nuestros registros. "
                    "Si en un futuro deseas volver a registrarte, puedes hacerlo cuando quieras. "
                    "Seguiré ayudándote con tu consulta sin guardar información personal."
                )
            else:
                # Path B — tranquilidad: no hay datos que eliminar.
                outbound_text = (
                    "No tengo datos personales tuyos registrados, así que no hay nada que eliminar. "
                    "Puedes seguir conversando con tranquilidad — solo guardo el chat de WhatsApp "
                    "necesario para responderte. Si más adelante autorizas el tratamiento de datos "
                    "para una compra, te lo pediré explícitamente."
                )

            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=outbound_text,
            )

            if had_data_to_revoke and contact_id:
                # Rev. 94 — Notificar al tenant SOLO si hubo revocación real.
                # No alertar al tenant cuando el cliente nunca dio datos.
                try:
                    from notifications import notify_consent_revoked
                    ok = await notify_consent_revoked(
                        supabase,
                        tenant_id=tenant_id,
                        contact_phone_hash=_hash_phone(phone_for_notify) or "",
                        occurred_at=datetime.now(timezone.utc).isoformat(),
                        source="whatsapp",
                    )
                    if not ok:
                        logger.error(
                            "[CONSENT] notify_consent_revoked returned False tenant=%s — todos los recipients fallaron",
                            tenant_id,
                        )
                except Exception as exc:
                    logger.error("[CONSENT] notify_consent_revoked excepción: %s", exc)

            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info(
                "[CONSENT] Revocación procesada | conversation=%s | had_data=%s",
                conversation_id, had_data_to_revoke,
            )
            return

        # ── 2.6 Detección Habeas Data Art. 14 (cliente pide SUS datos) ──────────
        # Rev. 97 — El titular puede ejercer derecho de acceso vía WhatsApp.
        # El bot responde con resumen de datos + audit log + notifica al tenant.
        if _detect_data_export_intent(content) and contact_id:
            summary_text = _build_customer_data_summary(supabase, contact_id, tenant_id)
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=summary_text,
            )
            # Audit append-only (Art. 9).
            try:
                phone_for_audit = None
                p_res = supabase.table("contacts").select("phone").eq(
                    "id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
                if p_res.data:
                    phone_for_audit = p_res.data[0].get("phone")
                _log_consent_event(
                    supabase,
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    phone=phone_for_audit,
                    event="export_request",
                    source="whatsapp",
                    conversation_id=conversation_id,
                    evidence={
                        "via": "self_service",
                        "channel": "whatsapp",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:
                logger.warning("[SAR] audit log falló: %s", exc)
            # Notificar al tenant (Art. 9 — registro de SAR).
            # Rev. 100 — distinguir excepción de False semantics.
            try:
                from notifications import notify_sar_received
                ok = await notify_sar_received(
                    supabase,
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    sar_type="export",
                    reason="Cliente solicitó datos vía WhatsApp",
                )
                if not ok:
                    logger.error(
                        "[SAR] notify_sar_received returned False tenant=%s — todos los recipients fallaron",
                        tenant_id,
                    )
            except Exception as exc:
                logger.error("[SAR] notify_sar_received excepción: %s", exc)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info("[SAR] Export self-service procesado | conversation=%s", conversation_id)
            return

        # ── 2.7 Rectificación Habeas Data Art. 16 (rev. 101 / F6) ───────────────
        # Cliente pide corrección formal vía WhatsApp. NO actualizamos auto:
        # registramos rectified en consent_audit_log (pendiente revisión) +
        # notificamos al tenant. El titular puede entonces ser contactado por
        # el operador para verificar identidad y recoger los datos correctos.
        # Diferencia con sub-flow UPDATE (rev. 89): aquel cambia datos
        # operacionales puntuales en flujo de compra. Este es ejercicio
        # formal del derecho Art. 16 — exige paper trail.
        if _detect_rectification_intent(content) and contact_id:
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "Recibida tu solicitud de rectificación de datos personales "
                    "(Art. 16 Ley 1581/2012 Habeas Data). Un operador la "
                    "revisará y se contactará contigo para validar tu "
                    "identidad y recoger los datos correctos.\n\n"
                    "Mientras tanto, sigue tu compra normal si lo deseas."
                ),
            )
            try:
                phone_for_audit = None
                p_res = supabase.table("contacts").select("phone").eq(
                    "id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
                if p_res.data:
                    phone_for_audit = p_res.data[0].get("phone")
                _log_consent_event(
                    supabase,
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    phone=phone_for_audit,
                    event="rectified",
                    source="whatsapp",
                    conversation_id=conversation_id,
                    evidence={
                        "via": "self_service",
                        "channel": "whatsapp",
                        "status": "pending_review",
                        "raw_message": content[:500],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:
                logger.warning("[SAR] rectify audit log falló: %s", exc)
            try:
                from notifications import notify_sar_received
                ok = await notify_sar_received(
                    supabase,
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    sar_type="rectify",
                    reason="Cliente solicitó rectificación vía WhatsApp",
                )
                if not ok:
                    logger.error(
                        "[SAR] notify_sar_received(rectify) returned False tenant=%s",
                        tenant_id,
                    )
            except Exception as exc:
                logger.error("[SAR] notify_sar_received(rectify) excepción: %s", exc)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info("[SAR] Rectify self-service registrado | conversation=%s", conversation_id)
            return

        # ── 2.55 Sub-flow UPDATE de datos (rev. 89) ───────────────────────────
        # Cliente conocido, en pre-confirmación, pide cambiar UN dato puntual
        # (dirección/correo/celular). Sub-flow determinístico que pregunta
        # SOLO ese campo. Evita volver al FSM completo y al LLM se le quita
        # esa decisión.
        _update_intent = _detect_data_update_intent(content)
        if _update_intent and (contact_record or {}).get("consent_given"):
            _prompts = {
                "address": (
                    "Listo. Por favor envíame la nueva dirección completa "
                    "(calle, número, barrio, ciudad). Si es edificio o "
                    "conjunto, incluye torre/apartamento."
                ),
                "email": "Listo. ¿Cuál es el correo electrónico nuevo?",
                "phone": (
                    "Listo. ¿Cuál es el celular nuevo? "
                    "Recuerda incluir el indicativo del país (ej: +57 ...)."
                ),
                "general": (
                    "Listo. ¿Qué dato quieres actualizar — dirección, correo, "
                    "celular o documento? Indícamelo y lo cambio."
                ),
            }
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=_prompts.get(_update_intent, _prompts["general"]),
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info(
                "[UPDATE] sub-flow activado conv=%s field=%s",
                conversation_id, _update_intent,
            )
            return

        # ── 2.6 Detección determinística de cancelación (rev. 83) ──────────────
        # UX: cliente desiste de la compra → bot acusa recibo cordial, cierra
        # el cart, deja la puerta abierta. NO escalamos a humano (sería
        # molesto si solo cambió de opinión). Si el cliente quiere asesor,
        # tiene su propio detector explícito.
        if _detect_cancel_intent(content):
            # Cerrar cart en DB si existe (cart-as-SoT rev. 80).
            try:
                from tools.cart_tool import get_cart_with_items
                _existing_cart = get_cart_with_items(
                    supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                )
                if _existing_cart and _existing_cart.get("id"):
                    supabase.table("conversation_carts").update(
                        {"status": "cancelled"}
                    ).eq("id", _existing_cart["id"]).eq("tenant_id", tenant_id).execute()  # A6.2.7
                    logger.info(
                        "[CANCEL] cart=%s marcado cancelled tras intent del cliente",
                        _existing_cart["id"][:8],
                    )
            except Exception as _cart_err:
                logger.warning("[CANCEL] no pude cerrar cart: %s", _cart_err)
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "Entendido, cancelo tu pedido. \n\n"
                    "No hay problema, cuando quieras retomar la compra aquí "
                    "estaré para ayudarte. ¡Que tengas un excelente día!"
                ),
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info("[CANCEL] Cancelación procesada (sin escalación) | conversation=%s", conversation_id)
            return

        # ── 3. Construir prompts ───────────────────────────────────────────────
        history_for_prompt = _history_without_current_inbound(history or [], content)

        # Rev. 103 — Cart-recovery: si el bot ofreció retomar el cart
        # cancelado en el outbound previo y el cliente aceptó ahora, copiar
        # los items al conversation_cart_items (cart-as-SoT). Sin esto el
        # bot menciona items pero shipping_quote_tool no los ve y pide
        # disambiguación de productos al cotizar.
        if (
            contact_id
            and _last_outbound_offered_cart_retake(history_for_prompt)
            and _detect_cart_retake_acceptance(content)
        ):
            _recovered_items = _fetch_recoverable_cart_items(
                supabase, tenant_id, contact_id,
            )
            if _recovered_items:
                _persist_recovered_cart_items(
                    supabase,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    contact_id=contact_id,
                    items=_recovered_items,
                )

        # ADR-0011 §6.4.4 — Tier-2 add_item intent detection (Plan A.0.3).
        # ANTES del flujo qty_change y add_item normales, intentar
        # resolver intent de add_item con clasificación granular:
        #   • resolved          → continúa al flow add_item normal abajo.
        #   • product_ambiguous → outbound determinístico con candidatos.
        #   • variant_ambiguous → outbound determinístico con presentaciones.
        #   • no_intent / no_product → continúa flow normal (qty_change /
        #     bypass / LLM).
        #
        # Caso runtime motivador (manual UAT 2026-05-05 conv 59bab7cc):
        #   "Puedo adicionar otro jabon? Deseo 1 de lavanda" → cliente
        #   quería Jabón Lavanda pero no especificó variante. Bot ANTES:
        #   emitía resumen viejo o alucinaba "no tenemos Lavanda". AHORA:
        #   tier 2 detecta variant_ambiguous para Jabón Lavanda y emite
        #   "*Jabón Artesanal de Lavanda* lo tenemos en: 60g, 100g, 150g.
        #   ¿Cuál presentación?" — determinístico, sin alucinación LLM.
        try:
            # Sem 7 F2 cierre 2026-05-19 — Bug 2 founder UAT:
            # Pre-filtrar catalog por categoría declarada en contexto reciente
            # (capas A+B). Si el cliente/bot encuadraron "jabones" en turnos
            # previos, el detector tier-2 solo evalúa jabones, evitando que
            # "coco" matchee Aceite Coco + Jabón Coco como ambiguo.
            _category_token = _extract_category_token_from_recent_context(
                history or [], catalog or [],
            )
            _eff_catalog = _filter_catalog_by_category_token(
                catalog or [], _category_token,
            )
            if _category_token and len(_eff_catalog) != len(catalog or []):
                logger.info(
                    "[TIER2] category-lock '%s' aplicado: catalog %d → %d productos (conv=%s)",
                    _category_token, len(catalog or []), len(_eff_catalog),
                    conversation_id[:8],
                )
            _tier2 = _detect_add_item_intent_with_resolution(content, _eff_catalog)
            _resolution = _tier2.get("resolution")
            if _resolution == "product_ambiguous":
                _cands = _tier2.get("candidates") or []
                _lines = [
                    f"Tenemos varios productos relacionados:"
                ]
                for c in _cands[:5]:
                    _lines.append(f"* *{c['title']}*")
                _lines.append("")
                _lines.append("¿Cuál te gustaría llevar?")
                _ambig_text = "\n".join(_lines)
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=_ambig_text,
                )
                _mark_message_processing(
                    supabase, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                logger.info(
                    "[TIER2] product_ambiguous (%d candidatos) — outbound "
                    "determinístico conv=%s",
                    len(_cands), conversation_id[:8],
                )
                return
            if _resolution == "resolved_multi":
                # Sem 7 F2 cierre 2026-05-19 — Bug 2 founder UAT (refinado).
                # Cliente declaró N productos con variantes explícitas en un
                # solo inbound (ej. "1 de Coco 100g y 1 de Lavanda 150g").
                # Tier-2 ya resolvió todos los matches deterministically.
                #
                # Bug 2.1 (UAT 2026-05-19 conv ee6cc665): "dejar que el flow
                # normal arme el resumen" producía DOBLE add_item porque
                # `_detect_variant_confirmation` posterior re-procesaba el
                # mismo inbound. Resultado: qty duplicado en cart.
                #
                # Fix: persistir + emitir resumen determinístico + RETURN
                # explícito (mismo patrón que product_ambiguous y
                # variant_ambiguous).
                _matches_multi = _tier2.get("matches") or []
                if _matches_multi:
                    try:
                        from tools.cart_tool import (
                            add_item as _add_item_multi,
                            ensure_cart as _ensure_cart_multi,
                            get_cart_with_items as _get_cart_multi,
                        )
                        _cart_multi = _ensure_cart_multi(
                            supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                            contact_id=contact_id,
                        )
                        for _m in _matches_multi:
                            _add_item_multi(
                                supabase,
                                cart_id=_cart_multi["id"],
                                tenant_id=tenant_id,
                                product_id=_m["product_id"],
                                variation_id=_m["variation_id"],
                                quantity=int(_m["quantity"]),
                                unit_price_cents=int(_m["unit_price_cents"]),
                            )
                            logger.info(
                                "[TIER2][RESOLVED_MULTI] add_item %s × %d (cart=%s conv=%s)",
                                _m["title"], _m["quantity"],
                                _cart_multi["id"][:8], conversation_id[:8],
                            )

                        # Resumen determinístico del cart actualizado
                        # (lee cart-as-SoT, NO history-parsing).
                        _cart_after = _get_cart_multi(
                            supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                        )
                        _items_after = (_cart_after or {}).get("items") or []
                        _lines = ["Listo, agregué a tu carrito:"]
                        for _m in _matches_multi:
                            _price_fmt = (
                                f"${int(_m['unit_price_cents'] / 100):,}".replace(",", ".")
                            )
                            _label = _m.get("variant_label") or ""
                            _label_str = f" ({_label})" if _label else ""
                            _lines.append(
                                f"* {_m['quantity']}x *{_m['title']}{_label_str}*: "
                                f"*{_price_fmt}*"
                            )
                        if _items_after and len(_items_after) > len(_matches_multi):
                            # Hay items previos en el cart — mostrar resumen total.
                            _subtotal_cents = sum(
                                int(it.get("subtotal_cents") or 0) for it in _items_after
                            )
                            _subtotal_fmt = (
                                f"${int(_subtotal_cents / 100):,}".replace(",", ".")
                            )
                            _lines.append("")
                            _lines.append(f"Subtotal: *{_subtotal_fmt}*")
                        _lines.append("")
                        _lines.append(
                            "¿Quieres agregar algo más, cotizar envío o avanzar al pedido?"
                        )
                        _resumen_text = "\n".join(_lines)
                        await _send_outbound_text(
                            supabase=supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                            text=_resumen_text,
                        )
                        _mark_message_processing(
                            supabase, message_id,
                            processing_status=PROCESSING_STATUS_PROCESSED,
                        )
                        logger.info(
                            "[TIER2] resolved_multi N=%d items añadidos + resumen "
                            "emitido — conv=%s",
                            len(_matches_multi), conversation_id[:8],
                        )
                        return
                    except Exception as _rm_exc:
                        logger.warning(
                            "[TIER2][RESOLVED_MULTI] persist+emit falló: %s",
                            _rm_exc,
                        )
                        # Si falla, NO retornamos — dejamos que el flow
                        # tradicional intente recuperar (degrade gracefully).
            if _resolution == "variant_ambiguous":
                _cands = _tier2.get("candidates") or []
                if _cands:
                    _c0 = _cands[0]
                    _vars = _c0.get("variants") or []
                    _opt_lines: list[str] = []
                    for v in _vars:
                        label = v.get("label") or ""
                        price = float(v.get("price") or 0)
                        if label and price > 0:
                            _opt_lines.append(
                                f"* {label} por *${int(price):,}*".replace(",", ".")
                            )
                    if _opt_lines:
                        _ask_text = (
                            f"*{_c0['title']}* lo tenemos en:\n"
                            + "\n".join(_opt_lines)
                            + "\n\n¿Cuál presentación y cuántas unidades te gustaría llevar?"
                        )
                        await _send_outbound_text(
                            supabase=supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                            text=_ask_text,
                        )
                        _mark_message_processing(
                            supabase, message_id,
                            processing_status=PROCESSING_STATUS_PROCESSED,
                        )
                        logger.info(
                            "[TIER2] variant_ambiguous (%s) — outbound "
                            "determinístico conv=%s",
                            _c0["title"], conversation_id[:8],
                        )
                        return
            # resolved / no_intent / no_product → continúa flow normal.
        except Exception as _t2_exc:
            logger.warning(
                "[TIER2] detector falló (no bloquea): %s", _t2_exc,
            )

        # ADR-0011 §6.4.3 — qty-change intent (Plan A.0.1, cart-as-SoT).
        # Antes del flujo de add_item normal, detectar si el cliente quiere
        # CAMBIAR la cantidad de un item ya en el cart ("que sean 2 de
        # lavanda", "en vez de 1 sean 2", "actualizar...sean N"). Sin este
        # hook, esos patterns caían a:
        #   • detector multi-product → emitía propuestas duplicadas o nada,
        #   • bypass READY_FOR_SUMMARY → emitía resumen sin cambiar qty,
        # y el cliente se frustraba repitiendo la intención.
        try:
            from tools.cart_tool import (
                get_cart_with_items as _get_cart_qty,
                update_item_quantity as _update_qty_tool,
            )
            _cart_for_qty = _get_cart_qty(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
            )
            _cart_items_qty = (_cart_for_qty or {}).get("items") or []
            if _cart_items_qty:
                _qty_items_with_titles = [{
                    "variation_id": it.get("variation_id"),
                    "product_id": it.get("product_id"),
                    "title": (it.get("product") or {}).get("title")
                             or (it.get("product") or {}).get("name")
                             or "Producto",
                    "quantity": int(it.get("quantity") or 1),
                    "unit_price_cents": int(it.get("unit_price_cents") or 0),
                } for it in _cart_items_qty]
                _qty_change = _detect_qty_change_intent(
                    content, _qty_items_with_titles,
                )
                if _qty_change and not _qty_change.get("ambiguous"):
                    _new_qty = int(_qty_change["new_qty"])
                    _current_qty = int(_qty_change.get("current_qty") or 1)
                    if _new_qty != _current_qty:
                        # Ejecuta el cambio.
                        _qty_payload = _update_qty_tool(
                            supabase,
                            cart_id=_cart_for_qty["id"],
                            tenant_id=tenant_id,
                            product_id=_qty_change["product_id"],
                            variation_id=_qty_change["variation_id"],
                            new_quantity=_new_qty,
                            unit_price_cents=int(_qty_change["unit_price_cents"]),
                        )
                        logger.info(
                            "[CART][QTY_CHANGE] %s: %d → %d (cart=%s conv=%s)",
                            _qty_change["title"], _current_qty, _new_qty,
                            _cart_for_qty["id"][:8], conversation_id[:8],
                        )

                        # Recotización lazy + resumen unificado (mismo path
                        # que el add_item invalidante). update_item_quantity
                        # ya marcó requires_requote=True.
                        try:
                            await _persist_cart_shipping_if_needed(
                                supabase=supabase,
                                conversation_id=conversation_id,
                                tenant_id=tenant_id,
                                history=history_for_prompt,
                            )
                        except Exception as _qe:
                            logger.warning(
                                "[CART][QTY_CHANGE] sync shipping falló: %s", _qe,
                            )

                        # Si update_item_quantity invalidó orden, emitir
                        # resumen unificado con prefijo. Sino, solo resumen.
                        _qty_inv = (_qty_payload or {}).get("order_invalidated") if isinstance(_qty_payload, dict) else None
                        try:
                            _cart_post_qty = _get_cart_qty(
                                supabase, conversation_id=conversation_id,
                                tenant_id=tenant_id,
                            )
                            _vctx_qty = (
                                _verified_ctx_from_cart(_cart_post_qty)
                                if _cart_post_qty else None
                            )
                            if _vctx_qty and int(_vctx_qty.get("total_cents") or 0) > 0:
                                _summary_qty = _build_order_summary_text(
                                    contact_record=contact_record,
                                    verified_ctx=_vctx_qty,
                                    catalog=catalog,
                                    history=history,
                                    cart_from_db=_cart_post_qty,
                                    supabase=supabase,
                                    tenant_id=tenant_id,
                                )
                                if _summary_qty:
                                    if _qty_inv:
                                        _short_q = str(_qty_inv.get("order_id") or "")[:8].upper()
                                        _prefix = (
                                            f"Listo, actualicé tu carrito. "
                                            f"El link de pago anterior "
                                            f"(*#{_short_q}*) ya no es válido.\n\n"
                                        )
                                    else:
                                        _prefix = "Listo, actualicé tu carrito.\n\n"
                                    _unified_qty = _prefix + _summary_qty
                                    await _send_outbound_text(
                                        supabase=supabase,
                                        conversation_id=conversation_id,
                                        tenant_id=tenant_id,
                                        text=_unified_qty,
                                    )
                                    _emit_summary_rendered_event(
                                        supabase,
                                        conversation_id=conversation_id,
                                        tenant_id=tenant_id,
                                        summary_text=_unified_qty,
                                    )
                                    _mark_message_processing(
                                        supabase, message_id,
                                        processing_status=PROCESSING_STATUS_PROCESSED,
                                    )
                                    return
                        except Exception as _qsexc:
                            logger.warning(
                                "[CART][QTY_CHANGE] resumen unificado falló: %s",
                                _qsexc,
                            )
                elif _qty_change and _qty_change.get("ambiguous"):
                    # Ambiguo: pedir clarificación.
                    _cands = _qty_change.get("candidates") or []
                    _cand_lines = "\n".join(f"* {c}" for c in _cands)
                    _ambig_text = (
                        f"Tienes varios productos en el carrito. ¿De cuál "
                        f"quieres que sean *{_qty_change['new_qty']}*?\n\n"
                        f"{_cand_lines}"
                    )
                    await _send_outbound_text(
                        supabase=supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=_ambig_text,
                    )
                    _mark_message_processing(
                        supabase, message_id,
                        processing_status=PROCESSING_STATUS_PROCESSED,
                    )
                    logger.info(
                        "[CART][QTY_CHANGE] ambiguous (%d candidates) — pidiendo clarificación conv=%s",
                        len(_cands), conversation_id[:8],
                    )
                    return
        except Exception as _qty_exc:
            logger.warning(
                "[CART][QTY_CHANGE] detector falló (no bloquea): %s", _qty_exc,
            )

        # Rev. 103 — Cart-as-SoT: detectar confirmación de variante
        # determinísticamente y persistir AL CART en el momento exacto en
        # que el cliente eligió. Antes el cart se inferia tarde (en
        # READY_FOR_SUMMARY) leyendo del history truncado → producto
        # alucinado. Ahora el cart es la fuente de verdad turn-by-turn.
        # El Inbox del Tenant Console (F-Inbox-1) leerá del cart real.
        # Sem 7 F2 cierre 2026-05-21 — flag turn-by-turn para invariante
        # anti-alucinación cart-add (orchestrator.py:~9820). Se setea a
        # True si CUALQUIER `cart_tool.add_item` corre exitosamente durante
        # este turn. Si LLM dice "Listo, 1x ... (60g) por $X" pero este
        # flag es False, REWRITE para pedir variante en lugar de mentir.
        _cart_add_executed_this_turn = False
        try:
            # Rev. 104 — Detector de variantes con propuestas (Plan A.3).
            #   Camino A: bot presentó opciones → cliente elige una variante.
            #   Camino B: cliente da producto+variante en un solo mensaje.
            #   Camino C (nuevo): cliente declara qty con variante ambigua →
            #     emitimos `cart_event(item_proposed)` para preservar la qty
            #     hasta que se resuelva la variante. Cuando Camino A
            #     resuelve la variante, elevamos la qty desde la propuesta.
            # Sem 7 F2 cierre — `_detect_variant_confirmation` ahora retorna
            # `list[dict]` (puede ser vacía, 1 elemento, o N) para soportar
            # multi-variant input ("1 de 100ml y 1 de 250ml" → 2 items).
            _variant_confirmed = _detect_variant_confirmation(
                content, history_for_prompt, catalog or [],
            )
            _multi_explicit: list[dict] = []
            _proposals: list[dict] = []
            if not _variant_confirmed:
                # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv febcec09):
                # Catalog FULL produce false positives multi-categoría.
                # Caso runtime: cliente dijo "1 Jabón Coco y 2 Lavanda" tras
                # ver listado de jabones → detector hizo 5 propuestas
                # (incluyó Aceite de Coco Virgen + Avena/Menta por overlap
                # de "jabon" + "artesanal"). Fix: filtrar catalog por
                # categoría reciente (mismo helper que tier-2 ya usa) ANTES
                # del detector explícito.
                _category_token_pre = _extract_category_token_from_recent_context(
                    history_for_prompt or [], catalog or [],
                )
                _eff_catalog_pre = _filter_catalog_by_category_token(
                    catalog or [], _category_token_pre,
                )
                _multi_explicit, _proposals = _detect_explicit_products_in_inbound(
                    content, _eff_catalog_pre,
                )

            from tools.cart_tool import ensure_cart, add_item
            from cart.events import (
                emit_item_proposal,
                find_unresolved_proposal,
                emit_proposal_resolved,
            )

            # Cart se asegura sólo si hay algo que persistir (item o propuesta).
            _cart_handle: Optional[dict] = None
            def _get_cart() -> dict:
                nonlocal _cart_handle
                if _cart_handle is None:
                    _cart_handle = ensure_cart(
                        supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        contact_id=contact_id,
                    )
                return _cart_handle

            # Camino C: emitir propuestas para productos sin variante resuelta
            # cuando el cliente declaró qty>=2.
            for _prop in _proposals:
                _cart_for_prop = _get_cart()
                emit_item_proposal(
                    supabase,
                    cart_id=_cart_for_prop["id"],
                    tenant_id=tenant_id,
                    product_id=_prop["product_id"],
                    title=_prop["title"],
                    quantity=_prop["quantity"],
                )
                logger.info(
                    "[CART][PROPOSAL] %dx %s (variante pendiente) → cart=%s conv=%s",
                    _prop["quantity"], _prop["title"],
                    _cart_for_prop["id"][:8], conversation_id[:8],
                )

            # Items a persistir + reconciliación con propuestas pendientes.
            # Sem 7 F2 cierre: `_variant_confirmed` ahora es lista (no
            # single dict), soporta multi-variant input directamente.
            _items_to_add = (
                _variant_confirmed if _variant_confirmed
                else _multi_explicit
            )
            # Sem 7 F2 cierre — fix arquitectónico Bug A multi-variant.
            # Antes: el `return` dentro del for loop (post emisión resumen
            # unificado) terminaba prematuramente sin procesar items restantes.
            # Resultado: "1 de 100ml y 1 de 250ml" solo agregaba el 100ml.
            # Fix: el for SOLO persiste items + acumula `_invalidation_info`.
            # Después del loop, UNA emisión de resumen unificado con cart final.
            _invalidation_info: Optional[dict] = None
            if _items_to_add:
                _cart = _get_cart()
                for _item in _items_to_add:
                    # Si el inbound NO declaró qty explícita (default 1) y
                    # existe una propuesta unresolved para este producto,
                    # adoptar su qty (preserva intención del cliente declarada
                    # turnos atrás).
                    _proposal = None
                    if int(_item.get("quantity") or 1) <= 1:
                        _proposal = find_unresolved_proposal(
                            supabase,
                            cart_id=_cart["id"],
                            product_id=_item["product_id"],
                        )
                        if _proposal and int(_proposal.get("quantity") or 1) >= 2:
                            _item["quantity"] = int(_proposal["quantity"])
                            logger.info(
                                "[CART][PROPOSAL_RESOLVED] qty=%d desde propuesta "
                                "para %s (cart=%s)",
                                _item["quantity"], _item["title"],
                                _cart["id"][:8],
                            )
                    _add_payload = add_item(
                        supabase,
                        cart_id=_cart["id"],
                        tenant_id=tenant_id,
                        product_id=_item["product_id"],
                        variation_id=_item["variation_id"],
                        quantity=_item["quantity"],
                        unit_price_cents=_item["unit_price_cents"],
                    )
                    # Sem 7 F2 cierre 2026-05-21 — flag para anti-hallu cart-add.
                    _cart_add_executed_this_turn = True
                    logger.info(
                        "[CART][VARIANT_CONFIRMED] %dx %s (%s) → cart=%s conv=%s",
                        _item["quantity"], _item["title"],
                        _item.get("variant_label") or "default",
                        _cart["id"][:8], conversation_id[:8],
                    )
                    # ADR-0011 §6.4.1 — recotización lazy INMEDIATA tras
                    # add_item invalidante. Sin esto, el resumen que el LLM
                    # construye después en este mismo turn lee shipping del
                    # cart (=0 por invalidate_shipping) y cae a heurística
                    # de history-parsing → muestra shipping stale.
                    # Caso runtime motivador 2026-05-05 (manual UAT):
                    # cart Coco+Sérum recotizado a $11.570; tras agregar
                    # Lavanda 100g (peso/dims +106%), el resumen final
                    # mantuvo $11.570 stale en lugar de recotizar.
                    # El guard genérico de _persist_cart_shipping_if_needed
                    # (que depende de buying_intent + carrier_selected) no
                    # se cumple post add_item porque el FSM degrada a
                    # CATALOG_MODE / buying_intent=False mientras el LLM
                    # procesa la nueva variante.
                    if isinstance(_add_payload, dict) and bool(
                        _add_payload.get("order_invalidated")
                        or _add_payload.get("requires_requote", True)
                    ):
                        try:
                            await _persist_cart_shipping_if_needed(
                                supabase=supabase,
                                conversation_id=conversation_id,
                                tenant_id=tenant_id,
                                history=history_for_prompt,
                            )
                        except Exception as _sync_exc:
                            logger.warning(
                                "[CART_SYNC] post add_item lazy requote falló: %s",
                                _sync_exc,
                            )

                    # Sem 7 F2 cierre — solo acumular info de invalidación.
                    # NO emitir outbound aquí (eso bloquearía items restantes
                    # del multi-variant input). Se emitirá DESPUÉS del loop
                    # con el cart final que tiene TODOS los items.
                    if isinstance(_add_payload, dict) and _add_payload.get("order_invalidated"):
                        _invalidation_info = _add_payload["order_invalidated"]
                    # Cierre de la propuesta (si la consumimos arriba).
                    if _proposal and _proposal.get("event_id"):
                        emit_proposal_resolved(
                            supabase,
                            cart_id=_cart["id"],
                            tenant_id=tenant_id,
                            proposed_event_id=_proposal["event_id"],
                            variation_id=_item["variation_id"],
                            final_quantity=int(_item["quantity"]),
                        )
                if len(_items_to_add) > 1:
                    logger.info(
                        "[CART][MULTI_PRODUCT] %d items distintos detectados conv=%s",
                        len(_items_to_add), conversation_id[:8],
                    )

            # Sem 7 F2 cierre — Plan A.0.1 / ADR-0011 §6.4.2: emitir resumen
            # unificado UNA VEZ después del loop con el cart final que ya
            # tiene TODOS los items procesados. Antes esto vivía dentro del
            # for y hacía `return` prematuro al primer item invalidante,
            # bloqueando items restantes del multi-variant input.
            if _invalidation_info:
                _short_id = str(_invalidation_info.get("order_id") or "")[:8].upper()
                _unified_emitted = False
                try:
                    from tools.cart_tool import get_cart_with_items as _get_cart_post
                    _cart_post = _get_cart_post(
                        supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                    )
                    _vctx_post = (
                        _verified_ctx_from_cart(_cart_post)
                        if _cart_post else None
                    )
                    if _vctx_post and int(_vctx_post.get("total_cents") or 0) > 0:
                        _summary_post = _build_order_summary_text(
                            contact_record=contact_record,
                            verified_ctx=_vctx_post,
                            catalog=catalog,
                            history=history,
                            cart_from_db=_cart_post,
                            supabase=supabase,
                            tenant_id=tenant_id,
                        )
                        if _summary_post:
                            _prefix = (
                                f"Listo, actualicé tu carrito. "
                                f"El link de pago anterior "
                                f"(*#{_short_id}*) ya no es válido.\n\n"
                            )
                            _unified_text = _prefix + _summary_post
                            await _send_outbound_text(
                                supabase=supabase,
                                conversation_id=conversation_id,
                                tenant_id=tenant_id,
                                text=_unified_text,
                            )
                            _emit_summary_rendered_event(
                                supabase,
                                conversation_id=conversation_id,
                                tenant_id=tenant_id,
                                summary_text=_unified_text,
                            )
                            _mark_message_processing(
                                supabase, message_id,
                                processing_status=PROCESSING_STATUS_PROCESSED,
                            )
                            logger.info(
                                "[CART_INVALIDATE] resumen unificado emitido "
                                "conv=%s order=%s shipping=%s items=%d",
                                conversation_id, _short_id,
                                _vctx_post.get("shipping_cost_cents"),
                                len(_items_to_add or []),
                            )
                            _unified_emitted = True
                except Exception as _unified_exc:
                    logger.warning(
                        "[CART_INVALIDATE] resumen unificado falló: %s "
                        "— fallback a notice + LLM resumen",
                        _unified_exc,
                    )

                if _unified_emitted:
                    return

                # Fallback (no se pudo construir resumen unificado):
                # emitir notice básico y dejar que el flujo normal del LLM
                # construya su respuesta.
                _notice = (
                    f"Actualicé tu carrito. El link de pago anterior "
                    f"(*#{_short_id}*) ya no es válido. Cuando confirmes "
                    f"el resumen, *recotizo el envío* con los productos "
                    f"actualizados y te genero un link nuevo."
                )
                try:
                    await _send_outbound_text(
                        supabase=supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=_notice,
                    )
                    logger.info(
                        "[CART_INVALIDATE] fallback notice conv=%s order=%s",
                        conversation_id, _short_id,
                    )
                except Exception as _notice_exc:
                    logger.warning(
                        "[CART_INVALIDATE] notice fallback falló: %s",
                        _notice_exc,
                    )
        except Exception as _vc_exc:
            logger.warning(
                "[CART] Variant confirmation persistence falló conv=%s: %s",
                conversation_id, _vc_exc,
            )

        # F3A: si la ventana de 24h expiró, buying_intent del historial no aplica
        buying_intent = False if _window_expired else _has_buying_intent(content, history_for_prompt)
        shipping_quoted = _has_shipping_been_quoted(history_for_prompt)
        # En conversaciones largas el history en memoria está truncado a
        # CONVERSATION_HISTORY_LIMIT. Si shipping_quoted=False allí, verificar en
        # DB la conversación completa antes de degradar el FSM a NEEDS_SHIPPING_CITY.
        if not shipping_quoted:
            shipping_quoted = _has_shipping_been_quoted_in_conversation(supabase, conversation_id)
        # Rev. 73 — si el cliente agregó productos DESPUÉS de la cotización,
        # invalidar la cotización vigente (peso/dimensiones cambiaron). Forzar
        # nueva pasada por shipping_quote_tool.
        if shipping_quoted and _cart_changed_since_last_quote(history_for_prompt):
            logger.info(
                "[FSM] Carrito cambió post-cotización en conv=%s → invalidando shipping_quoted",
                conversation_id,
            )
            shipping_quoted = False
        # Si ya cotizamos envío, el intent de compra persiste — _has_buying_intent
        # solo mira últimos 6 mensajes y se "pierde" en conversaciones largas
        # tras la captura de consent/email/name/document/address.
        if not buying_intent and not _window_expired and shipping_quoted:
            buying_intent = True
        # FSM evalúa con el mensaje actual incluido — para detectar
        # selección de carrier o consent en el inbound corriente que aún
        # no está persistido. history_for_prompt mantiene la versión sin
        # el actual para no duplicarlo en el contexto del LLM.
        history_for_fsm = list(history_for_prompt) + [
            {"direction": "inbound", "content": content}
        ]
        # Rev. 103 — DB fallback para carrier_selected (cubre casos donde
        # el history truncado a 25 mensajes pierde la señal del inbound de
        # selección, que en convs largas queda fuera del window).
        _carrier_selected_db = _has_carrier_been_selected_in_conversation(
            supabase, conversation_id,
        )

        # Rev. 103 — Cart-as-SoT: persistir shipping al cart en cuanto el
        # carrier es detectado como seleccionado. Sin esto, el cart queda
        # con shipping_cents=0 y total=subtotal — el panel Inbox y el
        # resumen necesitan workarounds (extract_shipping_cost_from_history)
        # para mostrar el shipping correcto. Con esto el cart es la única
        # fuente de verdad coherente: subtotal + shipping = total.
        if (
            buying_intent
            and (_has_carrier_been_selected(history_for_fsm) or _carrier_selected_db)
        ):
            await _persist_cart_shipping_if_needed(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                history=history_for_fsm,
            )

        # Sem 7 F2 cierre — Sólo una noción de "shipping resuelto" / "carrier
        # elegido", computada desde TODAS las fuentes de verdad coherentemente:
        #   1. History reciente (`shipping_quoted` de _has_shipping_quoted_in_conversation).
        #   2. DB carrier_selected_db (carrier persistido en cart).
        #   3. DB orders.pending_payment — si existe orden creada con
        #      shipping_cost > 0, AMBAS condiciones (shipping_quoted +
        #      carrier_selected) son TRUE por definición: la orden no se
        #      pudo crear sin esos pasos.
        # Caso runtime descubierto: cliente conocido retoma orden pendiente
        # ("Tengo carrito pendiente?"). History nuevo no muestra cotización
        # pero la orden DB ya la tiene → FSM caía en NEEDS_SHIPPING_CITY,
        # bypass payment_link no disparaba, LLM alucinaba "te genero el link".
        # Rev. 107 fix: la columna canónica de orders es `shipping_cost`
        # (DECIMAL), no `shipping_amount`. Bug silente del legacy que
        # devolvía HTTP 400 sin afectar UX pero impedía esta verificación.
        if contact_id and not (shipping_quoted and _carrier_selected_db):
            try:
                _po_check = (
                    supabase.table("orders")
                    .select("id, shipping_cost, status")
                    .eq("tenant_id", tenant_id)
                    .eq("contact_id", contact_id)
                    .eq("conversation_id", conversation_id)
                    .eq("status", "pending_payment")
                    .gt("shipping_cost", 0)
                    .limit(1)
                    .execute()
                )
                if _po_check.data:
                    if not shipping_quoted:
                        shipping_quoted = True
                    if not _carrier_selected_db:
                        _carrier_selected_db = True
            except Exception as _po_exc:
                logger.debug(
                    "[FSM] order DB lookup como fuente de verdad shipping/carrier "
                    "falló conv=%s: %s",
                    conversation_id, _po_exc,
                )

        display_state = _resolve_display_state(
            contact_record=contact_record,
            history=history_for_fsm,
            buying_intent=buying_intent,
            shipping_quoted=shipping_quoted,
            carrier_selected_db=_carrier_selected_db,
        )

        # R-13: Snapshot de producto al confirmar carrier
        # Se actualiza si ya existe uno (cliente puede cambiar de producto antes de confirmar).
        # Rev. 103 — usa también el DB fallback de carrier_selected para
        # que el snapshot dispare en convs largas con history truncado.
        if (
            buying_intent
            and (_has_carrier_been_selected(history_for_prompt) or _carrier_selected_db)
        ):
            _save_product_snapshot(
                supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                catalog=catalog,
                history_for_prompt=history_for_prompt,
            )

        # R-15: Refetch contacto antes de mostrar el resumen — garantiza datos frescos de DB
        # (nombre, email, dirección pueden haber sido escritos en el mensaje previo)
        if display_state == "READY_FOR_SUMMARY" and contact_id:
            try:
                _, fresh_contact = _fetch_contact_for_phone(
                    supabase=supabase,
                    tenant_id=tenant_id,
                    customer_phone_raw=customer_phone_raw,
                )
                if fresh_contact:
                    contact_record = fresh_contact
            except Exception as _r15_err:
                logger.warning("[ORCH] R-15: error refetch contacto para READY_FOR_SUMMARY: %s", _r15_err)

        if display_state == "NEEDS_CONSENT":
            # Rev. 103 — si el carrier acaba de defaultearse a Económica
            # porque el cliente dijo "sigamos"/"continuemos" tras una
            # cotización multi-opción (sin elegir explícitamente), prepender
            # un ack de carrier para que el cliente vea qué se eligió. Sin
            # esto, el bot saltaba a consent silenciosamente — feedback UAT
            # s9: "el chat no confirmó cuál tipo de envío y supuso económico".
            consent_text = CONSENT_QUESTION_TEMPLATE
            _content_norm = _normalize_text(content or "")
            _continue_intent = {
                "sigamos", "continuemos", "continuar", "continua", "continúa",
                "procedamos", "compra", "comprar", "avancemos", "sigue",
            }
            _user_picked_carrier_explicitly = any(
                t in _content_norm for t in (
                    "economica", "rapida", "deprisa", "servientrega",
                    "coordinadora", "tcc", "dhl", "fedex", "interrapidisimo",
                    "mensajeros", "urbanos",
                )
            )
            if (
                not _user_picked_carrier_explicitly
                and any(t in _content_norm.split() for t in _continue_intent)
            ):
                _carrier_name = _extract_shipping_carrier_from_history(
                    history_for_prompt or []
                )
                _shipping_cents = _extract_shipping_cost_from_history(
                    history_for_prompt or []
                ) or 0
                if _carrier_name and _shipping_cents > 0:
                    _carrier_ack = (
                        f"Listo, voy con la opción *Económica* "
                        f"({_carrier_name}) por *{_format_cop(_shipping_cents)}*.\n\n"
                    )
                    consent_text = _carrier_ack + consent_text
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=consent_text,
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        if display_state == "READY_FOR_SUMMARY" and _is_affirmative_confirmation(content):
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=ORDER_CREATION_CONFIRMATION_TEMPLATE,
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        # Bypass LLM: cuando display_state es AWAITING_ORDER_CONFIRMATION y el
        # cliente confirma explícito ("Sí, confirmo", "dale"), generar el link
        # de pago de forma determinística sin pasar por el LLM. El LLM en
        # contextos largos a veces emite intent=other y requires_human=True,
        # forzando escalación falsa cuando todo está listo para cerrar.
        history_for_bypass = _history_without_current_inbound(history or [], content)
        _aff = _is_affirmative_confirmation(content)
        _last_oc = _last_outbound_was_order_confirmation_question(history_for_bypass)
        logger.info(
            "[BYPASS] display_state=%s aff=%s last_oc=%s",
            display_state, _aff, _last_oc,
        )
        if (
            display_state == "AWAITING_ORDER_CONFIRMATION"
            and _aff
            and _last_oc
        ):
            # Rev. 104 — Cart-as-SoT primero (Plan A.0.1: cart es SoT
            # transaccional). Antes el bypass usaba `_build_verified_*_context`
            # que leen del history del LLM → en multi-producto sin mención
            # explícita en T-1, el ctx terminaba con SOLO 1 item, y la orden
            # se creaba con monto erróneo (caso runtime conv c8e07eff:
            # cart real 2×Coco+1×Sérum=$132.570 pero orden creada con 1×Coco=$29.570).
            verified_ctx_bypass = None
            _requote_info: Optional[dict] = None
            try:
                from tools.cart_tool import get_cart_with_items as _get_cart_bp, set_shipping_meta as _set_meta_bp
                _cart_bp = _get_cart_bp(
                    supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                )
                if _cart_bp and (_cart_bp.get("items") or []):
                    # ADR-0011 §6.5 — recotización lazy. Si el cart tiene
                    # `requires_requote=true` (típicamente por add_item /
                    # remove_item con orden previa invalidada), intentar
                    # recotizar contra Envia con peso/dims actualizados ANTES
                    # de generar el resumen+link. Mantiene el invariante:
                    # "el link Wompi nunca refleja shipping stale".
                    if _cart_bp.get("requires_requote"):
                        try:
                            from tools.shipping_quote_tool import requote_shipping_for_cart as _requote_lazy
                            _requote_info = await _requote_lazy(
                                supabase,
                                tenant_id=tenant_id,
                                conversation_id=conversation_id,
                            )
                            if _requote_info and _requote_info.get("shipping_cents", 0) > 0:
                                _set_meta_bp(
                                    supabase,
                                    cart_id=_cart_bp["id"],
                                    tenant_id=tenant_id,
                                    carrier=_requote_info["carrier_name"],
                                    service_level=_requote_info["service_level"],
                                    shipping_cents=int(_requote_info["shipping_cents"]),
                                )
                                # Re-leer cart con shipping recotizado persistido.
                                _cart_bp = _get_cart_bp(
                                    supabase,
                                    conversation_id=conversation_id,
                                    tenant_id=tenant_id,
                                )
                                logger.info(
                                    "[BYPASS] recotización lazy aplicada conv=%s "
                                    "shipping=%s carrier=%s",
                                    conversation_id, _requote_info["shipping_cents"],
                                    _requote_info["carrier_name"],
                                )
                        except Exception as _rq_exc:
                            logger.warning(
                                "[BYPASS] recotización lazy falló conv=%s: %s "
                                "— fallback a history-parsing (puede ser stale)",
                                conversation_id, _rq_exc,
                            )

                    verified_ctx_bypass = _verified_ctx_from_cart(_cart_bp)
                    # Si recotización falló y cart sigue requires_requote → fallback history.
                    if verified_ctx_bypass and not verified_ctx_bypass.get("shipping_cost_cents"):
                        _ship_hist = _extract_shipping_cost_from_history(
                            history_for_bypass
                        ) or 0
                        if _ship_hist > 0:
                            verified_ctx_bypass["shipping_cost_cents"] = _ship_hist
                            verified_ctx_bypass["total_cents"] = (
                                int(verified_ctx_bypass.get("subtotal_cents") or 0)
                                + _ship_hist
                            )
            except Exception as _bp_cart_exc:
                logger.warning(
                    "[BYPASS] cart-as-SoT lookup falló: %s", _bp_cart_exc,
                )
            # Fallback defensivo (sólo si cart vacío) — usa history-parsing.
            if not verified_ctx_bypass:
                logger.warning(
                    "[BYPASS] cart vacío → fallback history-parsing (puede alucinar) conv=%s",
                    conversation_id,
                )
                verified_ctx_bypass = (
                    _build_verified_multi_product_context(catalog, history_for_bypass)
                    or _build_verified_order_context(catalog, history_for_bypass)
                )
            if verified_ctx_bypass and verified_ctx_bypass.get("total_cents", 0) > 0:
                pl_result = await handle_payment_link_if_applicable(
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    conversation_id=conversation_id,
                    contact_name=contact_record.get("name") if contact_record else None,
                    total_in_cents=verified_ctx_bypass["total_cents"],
                    shipping_cost_cents=verified_ctx_bypass.get("shipping_cost_cents"),
                    notes=None,
                    supabase=supabase,
                    verified_ctx=verified_ctx_bypass,
                )
                if pl_result and pl_result.response_text:
                    # Rev. 104 (F1-5 mandatory) — GATE: si el último outbound
                    # NO fue un resumen, EMITIR resumen primero y POSPONER el
                    # link. El cliente confirmará el resumen y en el siguiente
                    # turn se dispara el link real. Sin este gate el
                    # OutputValidator BLOQUEA el send (defensa en profundidad).
                    if not _last_outbound_was_summary(history or []):
                        _summary_text = _build_order_summary_text(
                            contact_record=contact_record,
                            verified_ctx=verified_ctx_bypass,
                            catalog=catalog,
                            history=history,
                            cart_from_db=None,
                            supabase=supabase,
                            tenant_id=tenant_id,
                        )
                        if _summary_text:
                            await _send_outbound_text(
                                supabase=supabase,
                                conversation_id=conversation_id,
                                tenant_id=tenant_id,
                                text=_summary_text,
                            )
                            _mark_message_processing(
                                supabase, message_id,
                                processing_status=PROCESSING_STATUS_PROCESSED,
                            )
                            logger.info(
                                "[ORCH][BYPASS] resumen mandatorio emitido antes del link conv=%s",
                                conversation_id,
                            )
                            return
                    await _send_outbound_text(
                        supabase=supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=pl_result.response_text,
                    )
                    _mark_message_processing(
                        supabase,
                        message_id,
                        processing_status=PROCESSING_STATUS_PROCESSED,
                    )
                    logger.info(
                        "[ORCH][BYPASS] AWAITING_ORDER_CONFIRMATION + afirmativo → payment_link directo conv=%s",
                        conversation_id,
                    )
                    return

        # Rev. 103+ — Bypass LLM: cuando display_state es READY_FOR_SUMMARY y
        # el último outbound NO fue un resumen, emitir resumen determinístico
        # cart-as-SoT antes de cualquier pregunta de confirmación. Garantiza
        # contrato: cliente DEBE ver pedido + envío + total + datos de envío
        # antes de aceptar. Aplica especialmente al cliente conocido que
        # salta de carrier → READY_FOR_SUMMARY directo (sin pasar por
        # NEEDS_CONSENT/NEEDS_EMAIL etc), donde el LLM tiende a emitir
        # "Te genero el link" sin mostrar desglose. Idempotente: si el último
        # outbound ya tiene `📋` o `*Resumen`, no re-emite.
        #
        # Guards adicionales para no interceptar updates de PII:
        #   • inbound NO afirmativo (else dispara AWAITING_ORDER_CONFIRMATION).
        #   • inbound NO contiene phone alternativo (else perdemos extracción
        #     LLM de extracted_shipping_phone — caso S12 known T6 "3223840887"
        #     respondiendo a "¿Cuál es tu número alterno?").
        #   • inbound NO contiene email/document (PII update midflow).
        #
        # Sem 7 F2 cierre — Caso shipping_phone update post-resumen.
        # Cliente dice "Deseo cambiar el número X por Y" tras el resumen.
        # Fix arquitectónico completo:
        #   1. Persistir shipping_phone en DB
        #   2. Re-cargar contact_record fresh
        #   3. Emitir resumen determinístico DIRECTAMENTE con ambos
        #      celulares (NO delegar al bypass general — ese solo dispara
        #      para READY_FOR_SUMMARY, no AWAITING_ORDER_CONFIRMATION).
        #   4. Return early — LLM NO compone.
        # Garantiza: contrato resumen siempre por builder determinístico.
        # Sem 7 F2 cierre 2026-05-20 — pasar history para detectar contexto
        # cuando el outbound anterior pidió el número alterno (Bug P7).
        _shipping_phone_pre_persist = _detect_shipping_phone_update(content or "", history or [])
        _shipping_phone_just_persisted = False
        if (
            _shipping_phone_pre_persist
            and contact_id
            and display_state in {"READY_FOR_SUMMARY", "AWAITING_ORDER_CONFIRMATION"}
        ):
            _ship_digits = re.sub(r"\D", "", str(_shipping_phone_pre_persist))
            if len(_ship_digits) >= 10 and _ship_digits[-10] != "0":
                _new_ship = f"+57{_ship_digits[-10:]}"
                try:
                    supabase.table("contacts").update(
                        {"shipping_phone": _new_ship}
                    ).eq("id", contact_id).eq("tenant_id", tenant_id).execute()
                    # Re-cargar contact_record fresh.
                    _fresh_res = (
                        supabase.table("contacts")
                        .select(
                            "id, consent_given, name, email, address, "
                            "document_type, document_number, phone, shipping_phone"
                        )
                        .eq("tenant_id", tenant_id)
                        .eq("id", contact_id)
                        .single()
                        .execute()
                    )
                    if _fresh_res.data:
                        contact_record = _fresh_res.data
                        _shipping_phone_just_persisted = True
                        logger.info(
                            "[PRE_BYPASS] shipping_phone=%s persisted conv=%s",
                            _new_ship, conversation_id[:8],
                        )
                        # Emitir resumen determinístico inmediato (no delegar).
                        try:
                            from tools.cart_tool import get_cart_with_items as _gcwi_sp
                            _cart_sp = _gcwi_sp(
                                supabase, conversation_id=conversation_id,
                                tenant_id=tenant_id,
                            )
                        except Exception:
                            _cart_sp = None
                        if _cart_sp and (_cart_sp.get("items") or []):
                            _vctx_sp = _verified_ctx_from_cart(_cart_sp)
                            if _vctx_sp and not _vctx_sp.get("shipping_cost_cents"):
                                _ship_h = (
                                    _extract_shipping_cost_from_history(history or [])
                                    or _extract_shipping_cost_from_db(supabase, conversation_id)
                                    or 0
                                )
                                if _ship_h > 0:
                                    _vctx_sp["shipping_cost_cents"] = _ship_h
                                    _vctx_sp["total_cents"] = (
                                        int(_vctx_sp.get("subtotal_cents") or 0) + _ship_h
                                    )
                            if _vctx_sp and int(_vctx_sp.get("total_cents") or 0) > 0:
                                _resumen_sp = _build_order_summary_text(
                                    contact_record=contact_record,
                                    verified_ctx=_vctx_sp,
                                    catalog=catalog,
                                    history=history,
                                    cart_from_db=_cart_sp,
                                    supabase=supabase,
                                    tenant_id=tenant_id,
                                )
                                if _resumen_sp:
                                    # Preámbulo cordial + resumen actualizado.
                                    _outbound_sp = (
                                        f"Listo, *{_new_ship}* quedó como "
                                        f"celular para el envío.\n\n{_resumen_sp}"
                                    )
                                    await _send_outbound_text(
                                        supabase=supabase,
                                        conversation_id=conversation_id,
                                        tenant_id=tenant_id,
                                        text=_outbound_sp,
                                    )
                                    _mark_message_processing(
                                        supabase, message_id,
                                        processing_status=PROCESSING_STATUS_PROCESSED,
                                    )
                                    logger.info(
                                        "[PRE_BYPASS] shipping_phone update → "
                                        "resumen determinístico emitido conv=%s",
                                        conversation_id[:8],
                                    )
                                    return
                except Exception as _sp_exc:
                    logger.warning(
                        "[PRE_BYPASS] shipping_phone persist/emit falló conv=%s: "
                        "%s — sigue flow normal post-LLM",
                        conversation_id, _sp_exc,
                    )

        _is_pii_update = bool(
            (_detect_shipping_phone_update(content or "", history or []) and not _shipping_phone_just_persisted)
            or _detect_data_update_intent(content or "")
        )
        # Heurística adicional: si el inbound es 10+ dígitos consecutivos
        # respondiendo a una pregunta del bot sobre número, es phone update.
        # Sem 7 F2 cierre: si ya persistimos shipping_phone arriba, ya NO
        # bloquea bypass (el resumen actualizado es lo correcto a emitir).
        _looks_like_phone = bool(
            re.search(r"\b\+?5?7?\s?\d{10}\b", content or "")
        ) and not _shipping_phone_just_persisted
        # Rev. 104 — guard add_item intent (Plan A.0.1, ADR-0011 §6.4.1):
        # si el cliente pide agregar producto explícitamente, NO interceptar
        # con resumen. Dejar que el flujo normal procese variant detector +
        # add_item; el resumen actualizado vendrá DESPUÉS.
        # Caso runtime: "Puedo adicionar jabón de lavanda? De 100g" tras
        # un link generado: el bypass emitía resumen del cart anterior sin
        # agregar Lavanda → cliente no veía cambio.
        _has_add_item_intent = False
        if content and catalog:
            _norm_content = _normalize_text(content)
            _add_markers = (
                "agreg", "adicion", "anad", "anadir", "incluy",
                "incorpor", "sumar", "tambien",
            )
            if any(m in _norm_content for m in _add_markers):
                _matches_pre, _proposals_pre = _detect_explicit_products_in_inbound(
                    content, catalog,
                )
                if _matches_pre or _proposals_pre:
                    _has_add_item_intent = True
        if (
            display_state == "READY_FOR_SUMMARY"
            and not _last_outbound_was_summary(history or [])
            and not _is_affirmative_confirmation(content or "")
            and not _is_pii_update
            and not _looks_like_phone
            and not _has_add_item_intent
        ):
            try:
                from tools.cart_tool import get_cart_with_items
                _cart_resumen = get_cart_with_items(
                    supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                )
            except Exception as _ce:
                logger.warning("[BYPASS_RESUMEN] cart fetch falló: %s", _ce)
                _cart_resumen = None
            if _cart_resumen and (_cart_resumen.get("items") or []):
                _vctx = _verified_ctx_from_cart(_cart_resumen)
                if _vctx and not _vctx.get("shipping_cost_cents"):
                    _ship = (
                        _extract_shipping_cost_from_history(history or []) or
                        _extract_shipping_cost_from_db(supabase, conversation_id) or
                        0
                    )
                    if _ship > 0:
                        _vctx["shipping_cost_cents"] = _ship
                        _vctx["total_cents"] = (
                            int(_vctx.get("subtotal_cents") or 0) + _ship
                        )
                if _vctx and int(_vctx.get("total_cents") or 0) > 0:
                    _resumen_text = _build_order_summary_text(
                        contact_record=contact_record,
                        verified_ctx=_vctx,
                        catalog=catalog,
                        history=history,
                        cart_from_db=_cart_resumen,
                        supabase=supabase,
                        tenant_id=tenant_id,
                    )
                    if _resumen_text:
                        await _send_outbound_text(
                            supabase=supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                            text=_resumen_text,
                        )
                        _mark_message_processing(
                            supabase, message_id,
                            processing_status=PROCESSING_STATUS_PROCESSED,
                        )
                        logger.info(
                            "[BYPASS] READY_FOR_SUMMARY → resumen determinístico conv=%s",
                            conversation_id[:8],
                        )
                        return

        # ── Sem 7 F2 cierre 2026-05-21 — State renderers determinísticos ───
        # Bug founder UAT (conv 72e3f77e): el FSM resuelve correctamente
        # `display_state=NEEDS_SHIPPING_CITY` pero el LLM, dentro de ese
        # estado, redactaba libremente y a veces pedía consent/email/etc.
        # aunque cliente conocido ya tenía esos datos en DB. Solución:
        # override determinístico pre-LLM para estados transaccionales.
        # Patrón idéntico al bypass `READY_FOR_SUMMARY → resumen` arriba.
        #
        # CATALOG_MODE y NEEDS_X PII se delegan al LLM/conductor existente
        # (esos paths funcionan; el bug runtime estaba en NEEDS_SHIPPING_CITY).
        #
        # Guards: solo bypass cuando el inbound NO es una respuesta a otro
        # flow paralelo (shipping_phone update, qty_change, etc.) — esos
        # detectores ya corrieron arriba y emitieron sus propios outbounds.
        if (
            display_state in {"NEEDS_SHIPPING_CITY", "AWAITING_CARRIER_SELECTION"}
            and not _is_pii_update
            and not _looks_like_phone
            and not _has_add_item_intent
        ):
            from fsm import state_renderers as _state_renderers
            _override_text: Optional[str] = None
            if display_state == "NEEDS_SHIPPING_CITY":
                try:
                    from tools.cart_tool import get_cart_with_items as _gcwi_sr
                    _cart_sr = _gcwi_sr(
                        supabase, conversation_id=conversation_id,
                        tenant_id=tenant_id,
                    )
                except Exception:
                    _cart_sr = None
                _cart_items_sr = (_cart_sr or {}).get("items") or []
                _last_products = _last_outbound_presented_variants_all(
                    catalog or [], history or [],
                )
                _override_text = _state_renderers.render_needs_shipping_city(
                    cart_items=_cart_items_sr,
                    last_outbound_products=_last_products,
                    inbound_text=content,
                )
            elif display_state == "AWAITING_CARRIER_SELECTION":
                _override_text = _state_renderers.render_awaiting_carrier_selection(
                    last_outbound_was_quote=
                        _state_renderers.last_outbound_was_shipping_quote(
                            history or [],
                        ),
                )
            if _override_text:
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=_override_text,
                )
                _mark_message_processing(
                    supabase, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                logger.info(
                    "[STATE_RENDER] %s → outbound determinístico conv=%s",
                    display_state, conversation_id[:8],
                )
                return

        # GAP-1: Corrección de datos en el resumen — el cliente indica que un campo está mal
        if display_state == "READY_FOR_SUMMARY" and contact_id:
            correction_field = _detect_correction_intent(content)
            if correction_field:
                _clear_contact_field(supabase, contact_id, tenant_id, correction_field)
                _variants = _CORRECTION_PROMPT_VARIANTS.get(correction_field) or [
                    "Sin problema. ¿Qué dato quieres corregir?",
                    "Listo, ¿qué dato actualizo?",
                ]
                reply = _pick_variant(_variants, seed=_today_seed(conversation_id))
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=reply,
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CORR] Corrección solicitada campo='%s' | conv=%s", correction_field, conversation_id)
                return

        # Rev. 68 — contexto cliente conocido: pedidos activos + reclamos abiertos.
        _customer_first_name = (
            _extract_first_name(contact_record.get("name"))
            if contact_record and contact_record.get("consent_given") else None
        )
        customer_context_block = _load_customer_context_block(
            supabase, tenant_id, contact_id, _customer_first_name,
            query_text=content,
            conversation_id=conversation_id,        # rev. 103 — cart en vivo
            contact_record=contact_record,          # rev. 103 — datos contacto
            history=history_for_prompt,             # rev. 103 — shipping/carrier
        )

        system_prompt = _build_system_prompt(
            catalog=catalog,
            tenant_name=tenant_name,
            kb_text=kb_text,
            ai_agent=ai_agent,
            contact_record=contact_record,
            query_text=content,
            # FSM/carrier-detection lee history_for_fsm (incluye el inbound
            # actual) para que la instrucción al LLM refleje el estado tras
            # procesar el current. El catálogo/KB siguen leyendo history_for_prompt
            # para no contaminar contexto del LLM con duplicado.
            history=history_for_fsm,
            buying_intent=buying_intent,
            shipping_quoted=shipping_quoted,
            tenant_shipping_origin=tenant_shipping_origin,
            tenant_store_type=tenant_store_type,
            tenant_social_links=tenant_social_links,
            tenant_store_locations=tenant_store_locations,
            tenant_support_schedule=tenant_support_schedule,
            tenant_mision=tenant_mision,
            tenant_vision=tenant_vision,
            tenant_valores=tenant_valores,
            tenant_tono=tenant_tono,
            tenant_escalation_role=tenant_escalation_role,
            tenant_nit=tenant_nit,
            tenant_email_contacto=tenant_email_contacto,
            tenant_telefono_contacto=tenant_telefono_contacto,
            tenant_after_hours_message=tenant_after_hours_msg,
            tenant_is_outside_hours=_is_outside_support_hours(tenant_support_schedule),
            customer_context_block=customer_context_block,
            # Sem 7 F2 cierre 2026-05-20 — P1+P2 multitenant config.
            tenant_business_pitch=tenant_business_pitch,
            tenant_product_groups=tenant_product_groups,
            tenant_show_prices=tenant_show_prices,
        )
        user_context = _build_user_context(history, content)

        # ── 4. Llamar a Gemini con cascada + model router (rev. 81) ────────
        # Ref: https://googleapis.github.io/python-genai/
        # Rev. 81: cascada flash → flash-lite → degraded ante 503/429.
        # Rev. 81 model-routing: clasifica intent (simple|transactional) y
        # elige el modelo primario. Saludos/FAQ/info usan lite (cheap),
        # cart/pago/resumen usan flash (precision). Reduce costos ~50-60%.
        from llm_invoke import generate_with_cascade, degraded_response_text
        from llm_router import classify_intent, model_pair_for
        client = _get_genai_client()

        _intent_class = classify_intent(content, display_state, history_for_prompt)
        _primary_model, _fallback_model = model_pair_for(_intent_class)
        logger.info(
            "[ROUTER] intent=%s primary=%s fallback=%s",
            _intent_class, _primary_model, _fallback_model,
        )

        def _invoke_gemini(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=user_context,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

        cascade = generate_with_cascade(
            _invoke_gemini,
            primary_model=_primary_model,
            fallback_model=_fallback_model,
        )
        if cascade.degraded:
            # Todos los intentos fallaron con transitorios — degradar a
            # respuesta canned con requires_human=true para escalar.
            raw_json = degraded_response_text()
            logger.error(
                "[GEMINI] degradado tras %d intentos | last_err=%s",
                cascade.attempts, (cascade.last_error or "")[:160],
            )
            # Rev. 104 (F1-10) — encolar en review_queue + cambiar status a
            # human_takeover con contexto del fallo. El operador ve la cola
            # en Inbox/Revisión LLM y atiende manualmente. Sin esto, el
            # cliente quedaba con respuesta degradada y operador sin contexto.
            try:
                from llm.degraded import on_cascade_degraded
                on_cascade_degraded(
                    supabase,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    last_message_id=message_id,
                    fsm_state=display_state,
                    error=(cascade.last_error or "")[:1500],
                    prompt_snapshot=(system_prompt or "")[:6000],
                )
            except Exception as _hk_exc:
                logger.warning(
                    "[F1-10] hook on_cascade_degraded falló: %s", _hk_exc,
                )
        else:
            response = cascade.response
            raw_json = response.text
            logger.info(
                f"[GEMINI] model={cascade.model_used} attempts={cascade.attempts} | "
                f"Raw: {raw_json}"
            )

        # ── 5. Parsear output estructurado ────────────────────────────────────
        import json
        parsed = OrchestratorOutput(**json.loads(raw_json))
        logger.info(
            f"[GEMINI] intent={parsed.intent_detected} | "
            f"confidence={parsed.confidence:.2f} | "
            f"should_respond={parsed.should_respond} | "
            f"requires_human={parsed.requires_human}"
        )

        # Rev. 71 — Append-only log de fuentes consumidas (auditabilidad operativa).
        # Best-effort: si falla, no bloquea la respuesta al cliente.
        try:
            _bot_log_state = _resolve_display_state(
                contact_record=contact_record,
                history=history_for_fsm,
                buying_intent=buying_intent,
                shipping_quoted=shipping_quoted,
            )
            _log_bot_sources(
                supabase=supabase,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                fsm_state=_bot_log_state,
                system_prompt=system_prompt,
                kb_docs=kb_docs,
                catalog_count=len(catalog or []),
                customer_context_block=customer_context_block,
                is_outside_hours=_is_outside_support_hours(tenant_support_schedule),
                identity_present=bool(tenant_nit or tenant_email_contacto or tenant_telefono_contacto),
                intent_detected=parsed.intent_detected,
                requires_human=parsed.requires_human,
            )
        except Exception as _log_exc:
            logger.warning("[BOT_LOG] Falló persistencia bot_source_log: %s", _log_exc)

        # Rev. 103 — Petición EXPLÍCITA de atención humana (pre-LLM
        # determinístico). Marca un flag que sobrevive a TODOS los guards
        # anti-escalación-espuria + reescribe el response_text con un
        # mensaje de tranquilidad correcto sea horario o no. SIEMPRE
        # escala (status=human_takeover) — el cliente que pide humano
        # no debe quedar atrapado en bucle automático.
        force_human_request = _detect_human_request_intent(content)
        if force_human_request:
            parsed.requires_human = True
            parsed.should_respond = True
            _outside_hours = _is_outside_support_hours(tenant_support_schedule)
            # Rev. 103 — formato WhatsApp con jerarquía visual:
            #   • *Negritas* en acción/rol/horario (info accionable).
            #   • `> _cursiva_` en la nota secundaria (ofrecer adelantar tema)
            #     — separa visualmente del CTA principal.
            # Honesto al estado real: tras escalar, `status=human_takeover`
            # y el orchestrator ignora futuros inbounds (los persiste pero
            # no procesa). Decir "si necesitas ayuda con algo más, dímelo"
            # sería una falsa puerta. Lo que SÍ es cierto: lo que el cliente
            # escriba queda registrado y el {especialista} lo lee al tomar
            # la conversación.
            if _outside_hours:
                _hours_text = _format_support_schedule_text(tenant_support_schedule) or "horario hábil"
                parsed.response_text = (
                    f"*Listo*, registré tu solicitud.\n\n"
                    f"Un *{tenant_escalation_role}* te contactará apenas "
                    f"inicie nuestro horario:\n"
                    f"*{_hours_text}*.\n\n"
                    f"> _Si quieres adelantar el tema, escríbelo aquí — "
                    f"el {tenant_escalation_role} lo leerá cuando llegue._"
                )
            else:
                parsed.response_text = (
                    f"*Listo*, te conecto con un *{tenant_escalation_role}*.\n\n"
                    f"En unos minutos alguien te atiende por aquí.\n\n"
                    f"> _Si quieres adelantar el tema, escríbelo aquí — "
                    f"el {tenant_escalation_role} lo verá apenas tome la conversación._"
                )
            logger.info(
                "[HUMAN_REQ] Petición explícita de %s — escalando "
                "conv=%s outside_hours=%s",
                tenant_escalation_role, conversation_id, _outside_hours,
            )

        # Salvaguarda: si LLM pide takeover para saludo/off_topic, no escalar.
        # Confiamos en la respuesta de Gemini (response_text); si vino vacía, generamos
        # un saludo seguro variado por tono + conversation_id (5 variaciones rotativas).
        # Rev. 103 — `force_human_request` la sobrescribe (cliente pidió humano explícito).
        if (
            parsed.requires_human
            and parsed.intent_detected in {"greeting", "off_topic"}
            and not force_human_request
        ):
            parsed.requires_human = False
            parsed.should_respond = True
            if not parsed.response_text:
                agent_name = ai_agent.get("name", "el asistente")
                first_name_safe = None
                if contact_record and contact_record.get("consent_given"):
                    raw_name = (contact_record.get("name") or "").strip()
                    first_name_safe = raw_name.split()[0] if raw_name else None
                parsed.response_text = _safety_greeting_response(
                    agent_name=agent_name,
                    tenant_name=tenant_name,
                    first_name=first_name_safe,
                    tono=str(tenant_tono or "amigable"),
                    conversation_id=conversation_id,
                )
            logger.info(
                "[ORCH] requires_human ignorado para intent=%s en %s — respuesta automática",
                parsed.intent_detected, display_state,
            )

        # Salvaguarda de escalación espuria en modo consulta.
        # Rev. 103 — bypass cuando `force_human_request=True` (cliente pidió
        # humano explícito). El guard sigue protegiendo contra falsos
        # positivos del LLM en modo consulta normal.
        if (
            parsed.requires_human
            and display_state in {"CATALOG_MODE", "NEEDS_SHIPPING_CITY", "AWAITING_CARRIER_SELECTION"}
            and not force_human_request
        ):
            if parsed.intent_detected in {"product_inquiry", "other", "unknown", "greeting"}:
                parsed.requires_human = False
                parsed.should_respond = True
                if not (parsed.response_text or "").strip():
                    parsed.response_text = "Te ayudo con eso. ¿Me confirmas producto y ciudad para avanzar?"

        # order_acknowledgment no debe aparecer temprano sin datos transaccionales.
        if parsed.intent_detected == "order_acknowledgment" and parsed.requires_human:
            has_data = bool(parsed.extracted_name) or bool(parsed.extracted_email) or _has_real_address_data(parsed.extracted_direction)
            if display_state not in {"AWAITING_ORDER_CONFIRMATION", "READY_FOR_SUMMARY"} and not has_data:
                parsed.intent_detected = "product_inquiry"
                parsed.requires_human = False
                parsed.should_respond = True

        payment_link_result = None
        # El LLM emite intent=order_acknowledgment cuando el cliente confirma cierre
        # transaccional. requires_human depende del estilo del LLM y NO debe
        # condicionar la generación del link — si hay total claro, generamos.
        # PERO solo si el FSM de datos del cliente ya está listo: display_state
        # debe ser AWAITING_ORDER_CONFIRMATION o READY_FOR_SUMMARY. Si todavía
        # está en NEEDS_CONSENT/EMAIL/NAME/DOCUMENT/DIRECTION, NO crear orden —
        # el flujo de recolección de datos debe completarse primero.
        # Si el LLM emitió order_ack pero no incluyó total (caso multi-producto
        # donde el LLM no calcula bien), intentar fallback al verified_ctx
        # (calculado determinísticamente desde history + catálogo).
        if (
            parsed.intent_detected == "order_acknowledgment"
            and not parsed.total_in_cents
            and display_state in {"AWAITING_ORDER_CONFIRMATION", "READY_FOR_SUMMARY"}
        ):
            # Probar primero multi-producto, luego single
            verified_ctx_fallback = (
                _build_verified_multi_product_context(catalog, history_for_prompt)
                or _build_verified_order_context(catalog, history_for_prompt)
            )
            if verified_ctx_fallback and verified_ctx_fallback.get("total_cents", 0) > 0:
                parsed.total_in_cents = verified_ctx_fallback["total_cents"]
                parsed.shipping_cost_cents = verified_ctx_fallback.get("shipping_cost_cents")
                logger.info(
                    "[PAYMENT_LINK] LLM emitió total=null — fallback a verified_ctx=%s",
                    parsed.total_in_cents,
                )

        if (
            parsed.intent_detected == "order_acknowledgment"
            and parsed.total_in_cents
            and display_state in {"AWAITING_ORDER_CONFIRMATION", "READY_FOR_SUMMARY"}
        ):
            order_confirmation_prompted = _last_outbound_was_order_confirmation_question(history_for_prompt)
            if not order_confirmation_prompted:
                parsed.requires_human = False
                parsed.should_respond = True
                parsed.response_text = ORDER_CREATION_CONFIRMATION_TEMPLATE
            else:
                # Rev. 103 — Cart-as-SoT: leer del cart real primero. El cart
                # ya fue poblado turn-by-turn por `_detect_variant_confirmation`.
                # Solo fallback a inferencia desde history si cart genuinamente
                # vacío (caso edge — debería ser raro post-rev. 103).
                verified_ctx = None
                try:
                    from tools.cart_tool import get_cart_with_items as _get_cart_pl
                    _cart_for_payment = _get_cart_pl(
                        supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    )
                    if _cart_for_payment and (_cart_for_payment.get("items") or []):
                        verified_ctx = _verified_ctx_from_cart(_cart_for_payment)
                        # Cart no almacena shipping_cost autoritariamente —
                        # leer del último outbound de cotización.
                        if verified_ctx:
                            _ship_from_hist = _extract_shipping_cost_from_history(
                                history_for_prompt
                            ) or 0
                            if _ship_from_hist > 0 and not verified_ctx.get("shipping_cost_cents"):
                                verified_ctx["shipping_cost_cents"] = _ship_from_hist
                                verified_ctx["total_cents"] = (
                                    int(verified_ctx.get("subtotal_cents") or 0)
                                    + _ship_from_hist
                                )
                except Exception as _pl_cart_exc:
                    logger.warning(
                        "[PAYMENT_LINK] cart-as-SoT falló: %s", _pl_cart_exc,
                    )
                # Fallback defensivo (raro post-rev. 103 con variant detector activo)
                if not verified_ctx:
                    logger.warning(
                        "[PAYMENT_LINK] cart vacío al confirmar — fallback "
                        "a _build_verified_order_context (puede alucinar) conv=%s",
                        conversation_id,
                    )
                    verified_ctx = _build_verified_order_context(catalog, history_for_prompt)
                if verified_ctx and verified_ctx["total_cents"] > 0:
                    expected = verified_ctx["total_cents"]
                    tolerance = max(50000, int(expected * 0.05))  # 5% o $500 COP
                    if abs(parsed.total_in_cents - expected) > tolerance:
                        logger.warning(
                            "[PAYMENT_LINK] total_in_cents=%s difiere del contexto verificado=%s → usando verificado",
                            parsed.total_in_cents, expected,
                        )
                        parsed.total_in_cents = expected
                        parsed.shipping_cost_cents = verified_ctx["shipping_cost_cents"] or parsed.shipping_cost_cents

                # Rev. 103 — Pre-LLM gate: validar que el inbound del
                # cliente sea confirmación EXPLÍCITA antes de generar
                # link de pago. Defensa contra Gemini marcando
                # order_acknowledgment ante un dump duplicado o texto
                # largo que NO es confirmación real (bug detectado en
                # log conv 573125835649_20260502).
                if not _detect_order_confirmation(content):
                    logger.warning(
                        "[PAYMENT_LINK_GATE] LLM marcó order_acknowledgment "
                        "pero inbound NO es confirmación explícita: %r — "
                        "preservando pregunta de confirmación",
                        content[:100],
                    )
                    parsed.intent_detected = "product_inquiry"
                    parsed.requires_human = False
                    parsed.should_respond = True
                    parsed.response_text = (
                        "Para confirmar tu pedido y generar el link de pago, "
                        "respóndeme con un *Sí, confirmo* (o dime qué dato "
                        "quieres actualizar primero)."
                    )
                    payment_link_result = None
                else:
                    payment_link_result = await handle_payment_link_if_applicable(
                        tenant_id=tenant_id,
                        contact_id=contact_id,
                        conversation_id=conversation_id,
                        contact_name=contact_record.get("name") if contact_record else None,
                        total_in_cents=parsed.total_in_cents,
                        shipping_cost_cents=parsed.shipping_cost_cents,
                        notes=None,
                        supabase=supabase,
                        verified_ctx=verified_ctx,  # IDs reales para stock correcto
                    )
                if payment_link_result:
                    # Rev. 104 (F1-5 mandatory) — GATE: si el último outbound
                    # NO fue un resumen, REEMPLAZAR el response_text del
                    # payment_link por el resumen determinístico. El siguiente
                    # turn del cliente "Sí confirmo" disparará el link.
                    if (
                        not _last_outbound_was_summary(history or [])
                        and verified_ctx
                    ):
                        _summary_text = _build_order_summary_text(
                            contact_record=contact_record,
                            verified_ctx=verified_ctx,
                            catalog=catalog,
                            history=history,
                            cart_from_db=None,
                            supabase=supabase,
                            tenant_id=tenant_id,
                        )
                        if _summary_text:
                            parsed.requires_human = False
                            parsed.should_respond = True
                            parsed.response_text = _summary_text
                            logger.info(
                                "[ORCH] resumen mandatorio antepuesto al link conv=%s",
                                conversation_id,
                            )
                            # NO sobreescribir parsed.response_text con el link.
                        else:
                            # Fallback: emitir el link aunque no haya resumen
                            # (mejor que dejar al cliente sin respuesta).
                            parsed.requires_human = False
                            parsed.should_respond = True
                            parsed.response_text = payment_link_result.response_text
                    else:
                        parsed.requires_human = False
                        parsed.should_respond = True
                        parsed.response_text = payment_link_result.response_text

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

        # ── 6.99 Safety net (rev. 87, simplificado en rev. 91) ───────────────
        # Si el LLM responde vacío en estados NO transaccionales (CATALOG_MODE,
        # NEEDS_SHIPPING_CITY, AWAITING_CARRIER_SELECTION, etc.) inyectamos
        # fallback genérico para evitar bot mudo. Los estados transaccionales
        # (NEEDS_X) los maneja CheckoutFormConductor más abajo.
        if parsed.should_respond and (not parsed.response_text or not parsed.response_text.strip()):
            if display_state not in {"NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME",
                                      "NEEDS_DOCUMENT", "NEEDS_DIRECTION"}:
                parsed.response_text = (
                    "Disculpa, déjame procesar eso un momento. ¿Puedes "
                    "repetirme tu última solicitud o indicarme cómo continuar?"
                )
                logger.warning(
                    "[SAFETY_NET] response_text vacío sin state transaccional — fallback genérico",
                )

        # ── 6.999 Post-process rev. 87: 1 pregunta por turno ──────────────────
        # Si el LLM produjo 2+ "?" en la respuesta, truncar al primer signo
        # de cierre conservando el primer bloque coherente. Evita
        # interrogatorios "¿X? ¿Y?" que sobrecargan al cliente.
        if parsed.response_text and parsed.response_text.count("?") >= 2:
            _truncated = _truncate_at_first_question(parsed.response_text)
            if _truncated != parsed.response_text:
                logger.info(
                    "[1Q_TURN] respuesta tenía %d preguntas, trunqué al primero",
                    parsed.response_text.count("?"),
                )
                parsed.response_text = _truncated

        # ── 6.999a Post-process rev. 103: cita KB obligatoria ────────────────
        # Si el LLM omitió `_Fuente: X_` pero usó contenido verbatim ≥ 30 chars
        # de un kb_doc real, anexamos la cita determinísticamente. El formato
        # WhatsApp aplica el upgrade visual a `> Fuente:` después.
        if parsed.response_text and kb_docs:
            parsed.response_text = _ensure_kb_citation_present(
                parsed.response_text, kb_docs,
            )

        # ── 6.999b Post-process rev. 103: personalización cliente conocido ────
        # Si contact_record tiene consent + name Y es el primer outbound de
        # la conversación, garantizar que el saludo incluya el primer nombre.
        # El LLM a veces ignora la instrucción del prompt; este post-process
        # determinístico asegura consistencia (igual patrón que
        # _truncate_category_listings / _enhance_kb_citation).
        if parsed.response_text:
            _personalized = _inject_known_customer_name(
                parsed.response_text,
                contact_record=contact_record,
                history=history,
            )
            if _personalized != parsed.response_text:
                logger.info(
                    "[KNOWN_CUSTOMER] inyectado primer_nombre en outbound conv=%s",
                    conversation_id,
                )
                parsed.response_text = _personalized

        # ── 7. Enviar respuesta si corresponde ────────────────────────────────
        if parsed.should_respond and parsed.response_text:
            # Bug 16 — Gate "compras previas?": si el cliente expresa reclamo
            # y NO tiene NINGUNA orden con este número, en vez de escalar
            # respondemos preguntando si usó otro número. Así evitamos escalar
            # a humano por ruido y reducimos falsos positivos en SLA.
            # Debe ejecutarse ANTES del envío para sobreescribir el response_text
            # del LLM (que típicamente dice "te paso con un asesor").
            if (
                parsed.intent_detected in _COMPLAINT_INTENTS
                and parsed.requires_human
                and contact_id
            ):
                try:
                    _orders_count_res = (
                        supabase.table("orders")
                        .select("id", count="exact")
                        .eq("tenant_id", tenant_id)
                        .eq("contact_id", contact_id)
                        .execute()
                    )
                    _orders_count = int(getattr(_orders_count_res, "count", 0) or 0)
                except Exception:
                    _orders_count = -1
                if _orders_count == 0:
                    parsed.response_text = (
                        "No veo compras registradas con este número de WhatsApp. "
                        "¿Realizaste tu pedido con otro número o tienes el código de orden? "
                        "Así te ayudo a resolver lo antes posible."
                    )
                    parsed.requires_human = False
                    logger.info(
                        "[GATE-COMPRAS] complaint sin órdenes contact=%s — postpone escalación",
                        contact_id,
                    )

            # Rev. 91 — CheckoutFormConductor: punto único de decisión post-LLM
            # para los estados de captura (NEEDS_X). Reemplaza el SAFETY_NET
            # parcial + el FSM POST hard-lock fragmentado. El conductor:
            #   • Enriquece parsed.extracted_* con regex (caso S6: dump combinado).
            #   • Override building_type si el detector textual disagree con LLM
            #     (caso S12: cliente menciona "conjunto", LLM extrajo "casa").
            #   • Decide si forzar prompt determinístico cuando LLM no avanza
            #     o respondió vacío (casos S6/S9).
            # Patrón Rasa Forms — interfaz fluida (LLM redacta), lógica de
            # captura rígida (Python decide).
            if display_state in {"NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME", "NEEDS_DOCUMENT", "NEEDS_DIRECTION"}:
                form_result = _CHECKOUT_FORM_CONDUCTOR.run(
                    inbound=content or "",
                    parsed=parsed,
                    contact_record=contact_record,
                    display_state=display_state,
                )
                _sim_contact = form_result.sim_contact
                _new_state = form_result.new_state
                # Orden FSM canónico para detectar avance vs estancamiento
                # en la rama elif de "avance intermedio".
                _state_order = {
                    "NEEDS_CONSENT": 0, "NEEDS_EMAIL": 1, "NEEDS_NAME": 2,
                    "NEEDS_DOCUMENT": 3, "NEEDS_DIRECTION": 4,
                    "READY_FOR_SUMMARY": 5,
                }

                if form_result.response_text:
                    parsed.response_text = form_result.response_text
                    parsed.requires_human = False
                    parsed.should_respond = True
                    parsed.intent_detected = "data_request"
                    logger.info(
                        "[FSM][POST] conductor override display=%s new=%s",
                        display_state, _new_state,
                    )

                # READY_FOR_SUMMARY recién alcanzado: inyectar resumen
                # determinístico en vez de delegar al LLM. Esto garantiza que
                # el cliente vea siempre el desglose antes de confirmar.
                # Rev. 80: priorizar cart-en-DB como fuente de verdad para el
                # resumen — evita que el resolver de history pierda items.
                # Rev. 103+: incluir AWAITING_CARRIER_SELECTION como prior state
                # (cliente conocido con PII completa salta directo de carrier
                # → resumen sin pasar por NEEDS_*). Sin esto, el LLM componía
                # "¿Confirmas?" sin mostrar el resumen primero, contradiciendo
                # el contrato: cliente DEBE ver pedido + envío + total antes
                # de aceptar para evitar sorpresas en el cobro.
                if (
                    _new_state == "READY_FOR_SUMMARY"
                    and display_state in {
                        "NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME",
                        "NEEDS_DOCUMENT", "NEEDS_DIRECTION",
                        "AWAITING_CARRIER_SELECTION",
                    }
                ):
                    # Rev. 103 — Cart-as-SoT: el cart se persiste turn-by-turn
                    # vía `_detect_variant_confirmation` cuando el cliente
                    # elige variante. Aquí solo LEEMOS, no inferimos. El
                    # populate-on-demand previo (rev. 80) se eliminó porque
                    # llamaba a `_build_verified_*` con history truncado y
                    # producía alucinaciones (caso real conv 32e0397e:
                    # cliente pidió Coco 60g → orden con "Aceite Esencial
                    # de Árbol de Té"). Si por excepción el cart queda
                    # vacío al llegar aquí, mejor degradar a CTA explícito
                    # que inventar.
                    _cart_for_summary = None
                    try:
                        from tools.cart_tool import get_cart_with_items
                        _cart_for_summary = get_cart_with_items(
                            supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                        )
                    except Exception as _cart_err:
                        logger.warning(
                            "[CART] get_cart_with_items falló: %s", _cart_err,
                        )
                    if not _cart_for_summary or not (_cart_for_summary.get("items") or []):
                        # Cart vacío en READY_FOR_SUMMARY → algo se perdió
                        # (probablemente el cliente saltó el paso de variantes
                        # o el detector no captó). Pedir confirmación explícita
                        # en vez de inventar producto.
                        logger.warning(
                            "[CART] READY_FOR_SUMMARY con cart vacío conv=%s — "
                            "pidiendo confirmación de producto",
                            conversation_id,
                        )
                        parsed.response_text = (
                            "Antes de generar el resumen, ayúdame a confirmar el "
                            "producto que quieres llevar.\n\n¿Cuál te interesa?"
                        )
                        parsed.requires_human = False
                        parsed.should_respond = True
                        parsed.intent_detected = "product_inquiry"
                        # Skip el bloque de _build_order_summary_text — no
                        # tenemos cart real.
                        _cart_for_summary = None
                    # Rev. 103 — fallback de phone: si _sim_contact no
                    # tiene phone válido (None/"null"/vacío), usar el
                    # customer_phone_raw del WhatsApp para que el resumen
                    # muestre celular real (no "Celular: null").
                    if isinstance(_sim_contact, dict):
                        _sim_phone = _sim_contact.get("phone")
                        _sim_phone_str = str(_sim_phone or "").strip().lower()
                        if _sim_phone_str in ("", "null", "none", "undefined"):
                            if customer_phone_raw:
                                _sim_contact["phone"] = customer_phone_raw
                    # Rev. 103 — Solo construir resumen determinístico si
                    # tenemos cart real con items. Si cart vacío, ya
                    # seteamos el response_text de "confirma producto" arriba
                    # — NO llamar a `_build_order_summary_text` que caería
                    # al fallback de inferencia desde history (alucinación).
                    if _cart_for_summary and (_cart_for_summary.get("items") or []):
                        # DB fallback de shipping para convs largas. En
                        # history truncado a 25 msgs, la cotización (msg
                        # #8) queda fuera → resumen mostraba "$0 COP" aunque
                        # el panel sí lo veía. Inyectamos el shipping de
                        # DB directamente al cart_from_db para que
                        # `_verified_ctx_from_cart` lo pase al resumen.
                        if not (_cart_for_summary.get("shipping_cents") or 0):
                            _ship_db = _extract_shipping_cost_from_db(
                                supabase, conversation_id,
                            ) or 0
                            if _ship_db > 0:
                                _cart_for_summary["shipping_cents"] = _ship_db
                                # Reset requires_requote — el shipping recién
                                # leído de DB ES la cotización vigente.
                                _cart_for_summary["requires_requote"] = False
                                # Recalcular total — el cart_db tenía
                                # total = subtotal (sin envío) porque el
                                # shipping no estaba persistido al cart.
                                _sub_cents = int(_cart_for_summary.get("subtotal_cents") or 0)
                                _cart_for_summary["total_cents"] = _sub_cents + _ship_db
                                logger.info(
                                    "[CART_SUMMARY] shipping inyectado desde DB "
                                    "(history truncado): %s cents → total=%s conv=%s",
                                    _ship_db, _sub_cents + _ship_db, conversation_id[:8],
                                )
                        _summary = _build_order_summary_text(
                            contact_record=_sim_contact,
                            verified_ctx=None,
                            catalog=catalog,
                            history=history_for_prompt,
                            cart_from_db=_cart_for_summary,
                            supabase=supabase,
                            tenant_id=tenant_id,
                        )
                        if _summary:
                            parsed.response_text = _summary
                            parsed.requires_human = False
                            parsed.should_respond = True
                            parsed.intent_detected = "product_inquiry"
                            logger.info(
                                "[FSM][POST] override READY_FOR_SUMMARY con resumen determinístico (cart=%s items=%d)",
                                _cart_for_summary.get("id", "?")[:8],
                                len(_cart_for_summary.get("items") or []),
                            )
                # Avance intermedio NEEDS_X → NEEDS_Y: solicitar el siguiente dato.
                elif (
                    _new_state in _state_order
                    and _state_order.get(_new_state, 0) - _state_order.get(display_state, 0) >= 1
                    and _new_state != "READY_FOR_SUMMARY"
                ):
                    parsed.response_text = _build_next_data_request_prompt(_sim_contact)
                    logger.info(
                        "[FSM][POST] override LLM: %s → %s (datos extraídos)",
                        display_state, _new_state,
                    )

            # Fallback: si el LLM no extrajo el nombre pero el cliente lo acaba de dar, detectarlo
            name_for_humanize = parsed.extracted_name or _try_extract_name_from_message(content, display_state)
            parsed.response_text = _humanize_name_in_text(
                parsed.response_text,
                contact_record.get("name") if contact_record else None,
                name_for_humanize,
            )

            # Rev. 73 — Anti-alucinación transaccional. Detectar respuestas del
            # LLM que afirman estado transaccional sin que un tool determinístico
            # haya corrido. Si payment_link_result no fue producido pero el texto
            # promete pedido/entrega/carrier específico, reemplazar por CTA.
            _LIE_PHRASES = (
                "ya seleccione el envio",
                "ya seleccione tu envio",
                "tu pedido sera entregado",
                "tu pedido fue creado",
                "ya genere tu pedido",
                "confirmare tu compra",
                "tu compra ha sido confirmada",
                "tu pedido va en camino",
                "tu pedido esta confirmado",
                "ya procese tu pedido",
                # Rev. 103 — promesas de link de pago sin que el tool haya
                # corrido. Caso real conv 3448118a: bot dijo "Te genero el
                # link de pago" pero `payment_link_tool` no disparó (state
                # estaba degradado a AWAITING_CARRIER_SELECTION). Cliente
                # quedó sin link prometido. Estas frases ahora se reemplazan
                # por CTA si no hay payment_link_result.
                "te genero el link de pago",
                "te genero el link",
                "te genero tu link de pago",
                "te genero tu link",
                "voy a generarte el link",
                "te envio el link de pago",
                "tu pedido esta listo",
                "pedido esta listo",
                # Rev. 103+: variantes en presente continuo sin entrega.
                # Caso S9[known]: LLM dijo "Te estoy generando el link de
                # pago para que finalices tu compra. Te lo envío en un
                # momento." y nunca disparó payment_link_tool. Mensaje
                # promesa-sin-entrega que confunde al cliente.
                "te estoy generando el link",
                "estoy generando el link",
                "te lo envio en un momento",
                "te lo envio en unos momentos",
                "te lo envio en breve",
                "te lo envio enseguida",
            )
            _resp_norm = _normalize_text(parsed.response_text or "")
            if not payment_link_result and any(p in _resp_norm for p in _LIE_PHRASES):
                logger.warning(
                    "[ANTI_HALLU] LLM intentó confirmar pedido sin payment_link en conv=%s. "
                    "Texto original: %r",
                    conversation_id, (parsed.response_text or "")[:200],
                )
                # Rev. 103+: si tenemos cart con items + carrier seleccionado,
                # emitir el RESUMEN determinístico en lugar del CTA genérico.
                # Cumple contrato: cliente DEBE ver desglose antes de confirmar.
                _replacement_text: str | None = None
                if not _last_outbound_was_summary(history or []):
                    try:
                        from tools.cart_tool import get_cart_with_items
                        _cart_lh = get_cart_with_items(
                            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                        )
                    except Exception:
                        _cart_lh = None
                    if _cart_lh and (_cart_lh.get("items") or []):
                        _vctx_lh = _verified_ctx_from_cart(_cart_lh)
                        if _vctx_lh and not _vctx_lh.get("shipping_cost_cents"):
                            _ship_lh = (
                                _extract_shipping_cost_from_history(history or []) or
                                _extract_shipping_cost_from_db(supabase, conversation_id) or
                                0
                            )
                            if _ship_lh > 0:
                                _vctx_lh["shipping_cost_cents"] = _ship_lh
                                _vctx_lh["total_cents"] = (
                                    int(_vctx_lh.get("subtotal_cents") or 0) + _ship_lh
                                )
                        if _vctx_lh and int(_vctx_lh.get("total_cents") or 0) > 0:
                            _replacement_text = _build_order_summary_text(
                                contact_record=contact_record,
                                verified_ctx=_vctx_lh,
                                catalog=catalog,
                                history=history,
                                cart_from_db=_cart_lh,
                                supabase=supabase,
                                tenant_id=tenant_id,
                            )
                if _replacement_text:
                    parsed.response_text = _replacement_text
                    logger.info(
                        "[ANTI_HALLU] reemplazo LIE→resumen determinístico conv=%s",
                        conversation_id[:8],
                    )
                else:
                    parsed.response_text = (
                        "Antes de confirmarte el pedido necesito tu visto bueno. "
                        "¿Confirmas para generar tu link de pago?"
                    )

            # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv e0d7c539):
            # Anti-alucinación CART-ADD. Cliente pidió "1 Coco y 1 Lavanda"
            # SIN gramaje; detector determinístico retornó [] (correcto,
            # ambiguo entre 60g/100g/150g) → NO se ejecutó add_item; LLM
            # compuso "Listo, 1x Coco (60g) por $18.000 y 1x Lavanda (60g)
            # por $18.000" — alucinó el gramaje + alucinó la confirmación
            # de carrito. Mismo patrón que el guard payment_link arriba.
            #
            # Detector determinístico: el texto contiene confirmación
            # ("listo", "agregué", "te vendo", "añadí", "sumé") + variante
            # con unidad de peso/volumen en paréntesis ("(60g)", "(100g)",
            # "(15ml)", etc.) + precio ($X). Tres elementos juntos = LLM
            # afirmando estado de carrito concreto.
            #
            # Gate: `_cart_add_executed_this_turn=False` (no corrió
            # add_item en este turn). Cuando sí corrió, la confirmación
            # es legítima — no se reescribe.
            if (
                not _cart_add_executed_this_turn
                and _looks_like_cart_add_confirmation(parsed.response_text or "")
            ):
                logger.warning(
                    "[ANTI_HALLU][CART_ADD] LLM confirmó cart-add sin que add_item "
                    "haya corrido conv=%s. Texto original: %r",
                    conversation_id, (parsed.response_text or "")[:300],
                )
                parsed.response_text = (
                    "Para procesar el pedido necesito saber la presentación "
                    "exacta de cada producto. ¿Cuál presentación y cuántas "
                    "unidades te gustaría llevar?"
                )

            # Bug 30 — sincronizar texto y status. Si el response_text promete
            # handover ("te paso con un asesor") pero requires_human=False, el
            # cliente queda en limbo: el mensaje anuncia escalación que nunca
            # ocurre. Forzamos requires_human=True para que el bloque de
            # escalación más abajo realmente cambie status a human_takeover.
            # No aplicamos cuando ya generamos payment_link (flujo transaccional
            # válido) ni cuando el texto fue reescrito por gates determinísticos.
            if (
                not parsed.requires_human
                and not payment_link_result
                and _response_promises_handover(parsed.response_text)
            ):
                parsed.requires_human = True
                logger.info(
                    "[ESCALATION_SYNC] response_text promete handover — "
                    "forzando requires_human=True (conv=%s)",
                    conversation_id,
                )

            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=parsed.response_text,
            )

        # ── 8. Escalar a humano si es necesario ───────────────────────────────
        if parsed.requires_human:
            _set_conversation_status(
                supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
            )
            logger.info(f"[ESCALATION] Conversación {conversation_id} marcada para agente humano")

            # F5: Crear ticket automático en claims si es reclamo y hay contacto con orden
            if parsed.intent_detected in _COMPLAINT_INTENTS and contact_id:
                order_id_for_claim = _find_recent_claimable_order(supabase, tenant_id, contact_id)
                if order_id_for_claim:
                    ticket_number = _create_claim(
                        supabase,
                        tenant_id=tenant_id,
                        order_id=order_id_for_claim,
                        contact_id=contact_id,
                    )
                    if ticket_number and parsed.response_text:
                        _ticket_variants = [
                            f"\n\n📋 Quedó registrado tu caso con el número *#{ticket_number}*.",
                            f"\n\n📋 Tu reclamo ya está abierto con el ticket *#{ticket_number}*. Un {tenant_escalation_role} lo revisa.",
                            f"\n\n📋 Listo, tu caso queda con número *#{ticket_number}* para seguimiento.",
                        ]
                        _ticket_suffix = _pick_variant(_ticket_variants, seed=str(ticket_number))
                        parsed.response_text = parsed.response_text.rstrip() + _ticket_suffix

        # ── 8.5 Actualizar datos del contacto ─────────────────────────────────
        # Bug 27 (Ley 1581 Colombia): NO persistir datos personales (name, email,
        # address, document) si el cliente no ha dado consentimiento explícito.
        # Solo persistir cuando contact.consent_given == True. El cliente puede
        # mencionar datos en su pitch pero el bot los retiene en el contexto
        # de la conversación sin escribirlos en DB hasta que autorice.
        _consent_ok = bool(contact_record and contact_record.get("consent_given"))
        # Sem 7 F2 cierre 2026-05-20 — P4 founder UAT: defensa en profundidad.
        # Si el LLM no extrajo el tipo de documento (caso "Cedula de Ciudadania"
        # que el LLM no mapeó a CC), regex pre-LLM cubre las variantes
        # coloquiales típicas en español CO.
        if not parsed.extracted_document_type:
            _doc_type_detected = _detect_document_type_from_text(content or "")
            if _doc_type_detected:
                parsed.extracted_document_type = _doc_type_detected
                logger.info(
                    "[DOC] tipo detectado por regex pre-LLM: %s (LLM no extrajo)",
                    _doc_type_detected,
                )
        _has_doc_extract = bool(parsed.extracted_document_type or parsed.extracted_document_number)
        # Rev. 103 — pre-LLM dual cobertura: regex defensivo si LLM no extrajo.
        _shipping_phone_extracted = (
            getattr(parsed, "extracted_shipping_phone", None)
            or _detect_shipping_phone_update(content or "", history or [])
        )
        if contact_id and _consent_ok and (
            parsed.extracted_name
            or parsed.extracted_direction
            or parsed.extracted_email
            or _has_doc_extract
            or _shipping_phone_extracted
        ):
            update_data = {}
            # Rev. 103 — shipping_phone alternativo (separado de contacts.phone).
            # NO toca el phone WhatsApp; solo añade shipping_phone con fallback +57.
            if _shipping_phone_extracted:
                _ship_digits = re.sub(r"\D", "", str(_shipping_phone_extracted))
                if len(_ship_digits) >= 10 and _ship_digits[-10] != "0":
                    update_data["shipping_phone"] = f"+57{_ship_digits[-10:]}"
            if parsed.extracted_email and _EMAIL_REGEX.match(str(parsed.extracted_email).strip()):
                update_data["email"] = str(parsed.extracted_email).strip().lower()
            if parsed.extracted_name and str(parsed.extracted_name).strip():
                update_data["name"] = " ".join(str(parsed.extracted_name).split())
            # Rev. 68 — documento.
            # Sem 7 F2 cierre 2026-05-19 — Bug 1 founder UAT (conv 11c2dbde):
            # ANTES exigía tipo+número JUNTOS para persistir. Cliente dio
            # solo "CC" → no persistía → FSM seguía en NEEDS_DOCUMENT → bot
            # re-preguntaba ambos como si nada hubiera avanzado.
            # AHORA admite persistencia parcial: tipo solo o número solo
            # son válidos progresivos. El FSM sigue en NEEDS_DOCUMENT hasta
            # que ambos estén; el prompt es contextual (pide solo lo que falta).
            if _has_doc_extract:
                _doc_type = (str(parsed.extracted_document_type or "").strip().upper() or None)
                _doc_num_raw = str(parsed.extracted_document_number or "").strip()
                _doc_num = re.sub(r"[\s.]", "", _doc_num_raw) or None
                _valid_types = {"CC", "CE", "NIT", "PP", "TI", "OTHER"}
                if _doc_type and _doc_type in _valid_types:
                    update_data["document_type"] = _doc_type
                if _doc_num:
                    update_data["document_number"] = _doc_num
            # Rev. 91 — Reconciliación cross-cutting de building_type.
            # El detector textual tiene precedencia sobre la clasificación
            # del LLM (que tiende a errar conjunto vs casa). Caso S12: el
            # cliente dice "conjunto Las Flores" y el LLM extrae
            # building_type="casa" — sin esta reconciliación, el address
            # se persiste mal y FSM nunca exige torre/apto.
            # Esto vive aquí (capa de persistencia) en vez del conductor
            # porque el conductor solo activa en NEEDS_X — y S12 ocurre
            # cuando el dump llega aún en AWAITING_CARRIER_SELECTION.
            if isinstance(parsed.extracted_direction, dict) and any(
                parsed.extracted_direction.get(k) for k in
                ("street", "city", "neighborhood", "building_type", "tower", "apartment")
            ):
                _detected_bt = _detect_building_type_from_text(content or "")
                if _detected_bt and parsed.extracted_direction.get("building_type") != _detected_bt:
                    logger.info(
                        "[ADDRESS_RECONCILE] building_type LLM=%s text=%s — usando text",
                        parsed.extracted_direction.get("building_type"), _detected_bt,
                    )
                    parsed.extracted_direction["building_type"] = _detected_bt
            merged_address = _merge_address_data(
                contact_record.get("address") if isinstance(contact_record, dict) else None,
                parsed.extracted_direction,
            )
            if merged_address:
                # Enriquecer con Estado y Código DANE para que la UI los muestre bien
                dane_city = merged_address.get("city", "")
                if dane_city:
                    try:
                        from tools.shipping_quote_tool import _resolve_destination_from_query
                        dest, _ = _resolve_destination_from_query(dane_city)
                        if dest:
                            merged_address["city"] = dest["city"]
                            merged_address["state"] = dest["state"]
                            merged_address["country"] = "CO"
                            merged_address["dane_code"] = dest["dane_code"]
                    except Exception as e:
                        logger.warning(f"[CONTACT USYNC] Error en DANE lookup: {e}")
                
                # Normalización DIAN para almacenamiento unificado
                try:
                    from dian_normalization import normalize_dian_address
                    if merged_address.get("street"):
                        merged_address["street"] = normalize_dian_address(merged_address["street"])
                    if merged_address.get("number"):
                        merged_address["number"] = normalize_dian_address(merged_address["number"])
                except Exception as e:
                    logger.warning(f"[CONTACT USYNC] Error en DIAN normalizer: {e}")

                update_data["address"] = merged_address
            if update_data:
                try:
                    supabase.table("contacts").update(update_data).eq("id", contact_id).eq("tenant_id", tenant_id).execute()  # A6.2.7: PII cross-tenant
                    logger.info(f"[CONTACT USYNC] Actualizado {contact_id} con {update_data}")
                except Exception as ex:
                    logger.warning(f"[CONTACT USYNC] Error actualizando contacto: {ex}")

        # ── 9. Marcar mensaje como procesado ──────────────────────────────────
        _mark_message_processing(
            supabase,
            message_id,
            processing_status=PROCESSING_STATUS_PROCESSED,
        )

    except Exception as e:
        error_str = str(e)
        error_lower = error_str.lower()

        # Errores transitorios: 503, 429, timeout, connection — dejar en pending para retry del worker
        is_transient = (
            "503" in error_str
            or "unavailable" in error_lower
            or "timeout" in error_lower
            or "timed out" in error_lower
            or "connection" in error_lower
            or "503 service unavailable" in error_lower
            or "429" in error_str                     # Gemini rate limit → reintentar
            or "rate limit" in error_lower            # Rate limit genérico
            or "quota" in error_lower                 # Quota de API agotada
            or "resource_exhausted" in error_lower   # gRPC rate limit de Gemini
        )

        if is_transient:
            logger.warning(
                "[ORCH] Error transitorio en mensaje %s (se reintentará): %s",
                message_id,
                error_str[:200],
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PENDING,
                last_error=f"[transitorio] {error_str[:500]}",
            )
        else:
            logger.error(
                "[ORCH] Error orquestando mensaje %s: %s",
                message_id,
                error_str,
                exc_info=True,
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_FAILED,
                last_error=error_str[:1000],
            )

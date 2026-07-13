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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
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


# BLOQUE K (decisión founder J-4 #1): `_log_pii_access` del orchestrator ELIMINADO
# — tenía 0 callsites en runtime (el bot audita PII vía los chokepoints de tools, no
# per-turn; diseño documentado rev.93). El espejo VIVO vive en el API
# (services/api/dependencies/pii_audit.py) para las lecturas con propósito (SAR, etc.).


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


# BLOQUE K (decisión founder J-4 #1): `_customer_context_should_load` +
# `_CUSTOMER_CONTEXT_LAZY_TOKENS` ELIMINADOS. El gate tenía 0 callsites en runtime
# (los flags CUSTOMER_CONTEXT_ENABLED/MODE de render.yaml no gateaban nada — el bot
# carga el contexto del cliente por diseño vía `_load_customer_context_block`). Se
# quitaron los flags muertos + el gate + los tokens. La carga real es by-design (rev.93).


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


def _set_conversation_status(supabase: Client, tenant_id: str, conversation_id: str, status: str) -> None:
    """Actualiza el estado de conversación en contrato canónico.

    A6.2.7: tenant_id obligatorio — el UPDATE filtra por tenant para no mutar
    el status de una conversación de otro tenant aunque coincidiera el id.
    """
    supabase.table("conversations").update({"status": status}).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()


_COMPLAINT_INTENTS: frozenset[str] = frozenset({
    "complaint", "reclamo", "devolucion", "garantia", "queja",
})


_CANCEL_TOKENS: frozenset[str] = frozenset({
    "cancelar", "cancelar pedido", "cancelar compra", "reiniciar",
    "empezar de nuevo", "no quiero", "no quiero el pedido", "olvida el pedido",
})


def _mark_message_processing(
    supabase: Client,
    tenant_id: str,
    message_id: str,
    processing_status: str,
    skip_reason: Optional[str] = None,
    last_error: Optional[str] = None,
) -> None:
    """Registra el outcome explícito del procesamiento del inbound message.

    A6.2.7: tenant_id obligatorio — el UPDATE de messages filtra por tenant.
    """
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
    ).eq("id", message_id).eq("tenant_id", tenant_id).execute()


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


from text_utils import normalize_text as _normalize_text, tokenize_text as _tokenize_text  # noqa: E402


_NON_TEXT_WARNING_MARKER = "solo puedo atender mensajes de texto"


def _product_title_tokens(title: str) -> set[str]:
    return {
        token
        for token in _tokenize_text(title)
        if token not in QUERY_STOPWORDS and len(token) > 1
    }


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


# Rev. 104 (F1-2) — extraídos a fsm/address.py.
from fsm.address import (
    normalize_building_type as _normalize_building_type,
    normalize_conjunto_type as _normalize_conjunto_type,
    missing_address_fields as _missing_address_fields,
    has_real_address_data as _has_real_address_data,
)


# Rev. 104 (F1-2) — extraído a fsm/. Wrappers preservan firma legacy del
# call-site (que pasa `history` y `carrier_selected_db` separados); el
# resolver puro toma `carrier_selected` ya combinado.
from fsm import resolver as _fsm_resolver
from fsm import _has_real_address_data as _fsm_has_real_address_data  # noqa: F401


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


_NAME_DISCARD_TOKENS = {
    "si", "sí", "no", "ok", "oki", "okey", "vale", "dale", "listo", "claro",
    "gracias", "hola", "buenas", "buenos", "bien", "perfecto", "genial",
    "confirmo", "acepto", "entendido", "de", "una", "la", "el",
}


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


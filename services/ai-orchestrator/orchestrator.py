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
from llm_invoke import DEFAULT_PRIMARY_MODEL
from whatsapp_sender import send_whatsapp_message, _mask_phone
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
# M8 (2026-08-02) — el default del modelo vive UNA sola vez en llm_invoke
# (DEFAULT_PRIMARY_MODEL = el primario que prod declara en render.yaml).
# Antes este archivo defaultaba a gemini-3.5-flash y llm_invoke a
# gemini-3.1-flash-lite → defaults divergentes.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_PRIMARY_MODEL)
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
# H11 (founder live 2026-08-28 + harness t8_reclamo_coherente): en contexto de
# RECLAMO el framing de compra ("tu pedido / esta compra") descarrila la
# conversación y la enreda en loop. Variante con framing de reclamo — la acción
# legal es LA MISMA (tratamiento de datos, Ley 1581: previo + expreso +
# informado + revocable). Conserva los markers que reconoce el detector de
# consent (`consent_intent_resolver`): "autorización", "estás de acuerdo",
# "*SÍ* o *NO*". La elige `_send_outbound_text` vía `is_claim_context`.
CONSENT_QUESTION_TEMPLATE_CLAIM = (
    "Entendido, y lamento lo que pasó. Para registrar tu reclamo y darte "
    "seguimiento, con tu autorización usaré tus datos de contacto solo para "
    "gestionar tu caso.\n\n"
    "Si en algún momento quieres que los borre, solo dímelo.\n\n"
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
    """Retorna los últimos N mensajes de la conversación (contexto del chat).

    B-2 Fase 0 (2026-08-28): el SELECT incluye `content_type` — el TurnContext
    deriva de este history el recent-10 del image-request (que necesita saber
    si un mensaje fue media) sin una segunda lectura de `messages` por turno.
    Los consumidores leen por `.get()` — la columna extra es inerte para ellos.
    """
    result = (
        supabase.table("messages")
        .select("direction, content, content_type, created_at")
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
        _customer_name: Optional[str] = None
        if _customer_phone:
            _phone_digits = _customer_phone.lstrip("+")
            _ctc = (
                supabase.table("contacts")
                .select("consent_given, name")
                .eq("tenant_id", tenant_id)
                .or_(f"phone.eq.{_phone_digits},phone.eq.+{_phone_digits}")
                .limit(1)
                .execute()
            )
            _ctc_row = (_ctc.data or [{}])[0]
            _consent_given = bool(_ctc_row.get("consent_given"))
            # Founder 2026-08-23: primer nombre para el saludo personalizado
            # del prepend cold-open (cliente conocido).
            _full_name = (_ctc_row.get("name") or "").strip()
            if _full_name:
                _customer_name = _full_name.split(" ", 1)[0]

        # SMELL-1: pasar saludo time-aware computado por hora local Colombia.
        # El validator solo aplica el rewrite si este valor está presente
        # y si el outbound es el primer mensaje (history sin outbounds previos).
        try:
            _server_greet, _ = _co_time_of_day_greeting()
        except Exception:
            _server_greet = None
        # H11 (2026-08-28, founder live + harness t8_reclamo_coherente): si la
        # conversación activa es un RECLAMO, la pregunta de consent usa el
        # framing de reclamo — NUNCA el de compra (descarrilaba el reclamo y lo
        # enredaba en loop). Misma acción legal (Ley 1581); la elige el embudo
        # según el contexto reciente del history ya cargado arriba.
        _consent_template = CONSENT_QUESTION_TEMPLATE
        try:
            from agentic.claim_intent_resolver import is_claim_context
            if is_claim_context(recent.data or []):
                _consent_template = CONSENT_QUESTION_TEMPLATE_CLAIM
        except Exception:
            pass  # fail-safe: template de compra (el de siempre)
        result = OutputValidator().validate(ValidationContext(
            candidate_text=text,
            history=recent.data or [],
            contact_consent_given=_consent_given,
            consent_question_template=_consent_template,
            server_time_greeting=_server_greet,
            customer_name=_customer_name,
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
                            # M10 (2026-08-02): no prometer "por este chat" —
                            # fuera de la ventana 24h Meta mata el outbound
                            # (131047). El comprobante SIEMPRE va por correo
                            # (receipt_email.py; email obligatorio en checkout,
                            # FSM NEEDS_EMAIL) y por aquí si la ventana sigue abierta.
                            f"> El link es válido por 30 minutos. Una vez confirmado "
                            f"el pago recibirás la confirmación por aquí y por correo."
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
        logger.info("[OUTBOUND] Respuesta enviada directamente a %s", _mask_phone(customer_phone))
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


_VARIANT_QTY_RE = re.compile(
    r"^\s*(?:quiero\s+|dame\s+|el\s+|la\s+|los\s+|las\s+|me\s+das\s+|"
    r"agreg(?:a|ame)\s+|añad(?:e|eme)\s+|sumame\s+|llevo\s+)?"
    r"(\d{1,3})\s*(?:unidades?|uds?\.?|cantidad)?",
    re.IGNORECASE,
)




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














from text_utils import format_cents_cop as _format_cop, format_pesos as _format_pesos  # noqa: E402

# G12: cluster de formato extraído a lib/response_format.py — los nombres
# quedan en este namespace por el import (dispatcher y demás callers intactos).
from lib.response_format import (  # noqa: F401
    _PRESENTATION_MARKERS,
    _DAY_LABELS_ES_ISO,
    _KB_CITE_RE,
    _KB_CITE_CTA,
    _CATEGORY_HEADER_RE,
    _BULLET_LINE_RE,
    _TRUNCATED_MARKER,
    _MARKETING_CITE,
    _mask_value,
    _format_phone_for_summary,
    _format_address_for_summary,
    _build_customer_data_summary,
    _extract_shipping_cost_from_history,
    _extract_shipping_carrier_from_history,
    _format_support_schedule_text,
    _build_store_info_section,
    _format_whatsapp_response_text,
    _bold_kb_terms,
    _enhance_kb_citation,
    _truncate_category_listings,
    _last_outbound_presented_variants_all,
    _verified_ctx_from_cart,
    _build_order_summary_text,
)


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




# ── Rev. 92 — Realzado de cita KB ────────────────────────────────────────────



# Términos típicos de KB regulatoria que mejoran la lectura WhatsApp
# si quedan en *negrita*. Aplica solo si el outbound tiene cita Fuente:.






# ── Rev. 92 — Listado truncado determinístico ────────────────────────────────




"""Known-customer data confirmation tool — rev. 104 (UX known users).

Cuando un cliente conocido (consent_given=True + name + email + document
+ address completos) inicia una intención de compra en una conversación
nueva, el bot debe ANTES de pedir ciudad / continuar:

  1. Mostrar los datos guardados como bullets.
  2. Preguntar "¿estos datos están correctos para tu envío o necesitas
     actualizar alguno?"
  3. Esperar confirmación o solicitud de update.

Hoy el FSM eventualmente llega a `READY_FOR_SUMMARY` donde sí se hace
esto, pero TARDE (post-cotización). Para conversaciones casuales el
LLM no siempre triggea la confirmación temprana — el cliente termina
cotizando con datos asumidos sin haberlos revisado.

Este tool es una emisión DETERMINÍSTICA pre-LLM: se invoca a través del
`ToolDispatcher` con prioridad alta cuando aplican TODAS las condiciones:

  • Cliente tiene `consent_given=true`.
  • Tiene `name`, `email`, `document_number`, `address.street`.
  • Inbound actual contiene buying intent (verbo + producto / consulta de
    presentaciones), NO selección de variante o respuesta corta.
  • La conversación NO ha mostrado aún el bloque de confirmación
    (idempotencia: evitamos re-emitir si ya se hizo).

Si las condiciones se cumplen, retorna un `response_text` formateado
canónico que el orchestrator envía vía `_send_outbound_text` y termina
el turno (sin llamar al LLM).

Esto es estructural — no rewriting de la salida del LLM. Sigue el patrón
de los otros tools determinísticos (image_send, shipping_quote, order_status)
y se integra al `inbound_dispatcher`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_CONFIRMATION_MARKER = "📇 *Datos guardados de tu envío:*"


@dataclass
class KnownCustomerConfirmationResult:
    handled: bool
    response_text: Optional[str] = None


_BUYING_VERBS = (
    "quiero", "quisiera", "deseo", "comprar", "necesito",
    "busco", "buscar", "buscando",
    "llevar", "llevarme", "llevame",
    "envíame", "enviame", "mándame", "mandame",
    "pídeme", "pideme", "ordenar", "pedir", "pedido",
    "interesa", "interesado", "interesada",
    "me gustaria", "me gustaría",
)


def _has_buying_intent_in_inbound(text: str) -> bool:
    """Detecta intención de compra en un solo inbound. Conservador: solo
    True si hay un verbo de compra explícito."""
    if not text:
        return False
    norm = text.lower()
    for verb in _BUYING_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", norm):
            return True
    return False


def _conversation_is_past_initial_intent(history: list[dict]) -> bool:
    """True si la conversación ya pasó de intent inicial — el bot ya:
      • Mostró cotización con precio de envío.
      • Listó variantes con precios concretos (selección iniciada).
      • Preguntó por consent o PII (LLM ya tomó control del flow).

    En esos casos NO tiene sentido emitir el bloque de pre-confirmación
    porque sería redundante con preguntas posteriores del bot.
    """
    for msg in history or []:
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "").lower()
        # Cotización ya entregada (shipping_quote_tool determinístico).
        if ("económica" in content or "economica" in content) and "$" in content:
            return True
        # Bot ya pidió PII o consent.
        if any(s in content for s in (
            "tratamiento de datos", "habeas data", "autorizas",
            "tu correo electrónico", "tu correo electronico",
            "tu nombre completo", "tu cédula", "tu cedula", "tu nit",
            "necesito algunos datos", "para procesar tu pago",
        )):
            return True
    return False


def _has_already_shown_confirmation(history: list[dict]) -> bool:
    """Idempotencia: no re-emitimos el bloque si ya está en algún outbound
    previo de la conversación."""
    for msg in history or []:
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        if _CONFIRMATION_MARKER in content:
            return True
        if "datos guardados" in content.lower() and "envío" in content.lower():
            return True
    return False


def _format_phone_co(phone: str) -> str:
    """+57 312 583 5649 ← '573125835649'."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 12 and digits.startswith("57"):
        return f"+57 {digits[2:5]} {digits[5:8]} {digits[8:]}"
    if len(digits) == 10:
        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return phone


def _format_address(address: dict) -> str:
    if not isinstance(address, dict):
        return ""
    parts: list[str] = []
    street = (address.get("street") or "").strip()
    if street:
        parts.append(street)
    if address.get("complex_name"):
        parts.append(str(address["complex_name"]).strip())
    if address.get("tower"):
        parts.append(f"Torre {address['tower']}")
    if address.get("apartment"):
        parts.append(f"Apto {address['apartment']}")
    if address.get("neighborhood"):
        parts.append(str(address["neighborhood"]).strip())
    if address.get("city"):
        parts.append(str(address["city"]).strip())
    return " — ".join(p for p in parts if p)


def _is_complete_known_customer(contact_record: Optional[dict]) -> bool:
    """True si el contacto tiene todo lo necesario para saltar el FSM
    de captura: consent + name + email + document + address con calle."""
    if not isinstance(contact_record, dict):
        return False
    if not contact_record.get("consent_given"):
        return False
    if not (contact_record.get("name") or "").strip():
        return False
    if not (contact_record.get("email") or "").strip():
        return False
    if not (contact_record.get("document_number") or "").strip():
        return False
    address = contact_record.get("address")
    if not isinstance(address, dict):
        return False
    if not (address.get("street") or "").strip():
        return False
    return True


def build_confirmation_text(contact_record: dict) -> str:
    """Genera el bloque de confirmación canónico — bullets + pregunta CTA.

    Función pura (testeable sin DB): toma el `contact_record` y produce
    el texto. El orchestrator solo lo despacha vía `_send_outbound_text`.
    """
    name = (contact_record.get("name") or "").strip()
    first_name = name.split()[0].title() if name else ""
    email = (contact_record.get("email") or "").strip()
    doc_t = (contact_record.get("document_type") or "CC").strip().upper()
    doc_n = (contact_record.get("document_number") or "").strip()
    phone = (contact_record.get("phone") or "").strip()
    shipping_phone = (contact_record.get("shipping_phone") or "").strip()
    address = _format_address(contact_record.get("address") or {})

    greeting = f"Listo{', *' + first_name + '*' if first_name else ''}."
    lines = [
        f"{greeting} Antes de avanzar, confirmemos tus datos guardados — así no los pedimos otra vez.",
        "",
        _CONFIRMATION_MARKER,
        f"* Nombre: *{name}*" if name else "",
        f"* Correo: {email}" if email else "",
        f"* Documento: {doc_t} {doc_n}" if doc_n else "",
        f"* Celular WhatsApp: {_format_phone_co(phone)}" if phone else "",
    ]
    if shipping_phone and shipping_phone != phone:
        lines.append(f"* Celular envío (alterno): {_format_phone_co(shipping_phone)}")
    if address:
        lines.append(f"* Dirección: {address}")
    lines.extend([
        "",
        "¿Estos datos están correctos para tu envío o necesitas actualizar alguno?",
        "",
        "> _Si todo está bien, dime *sí* y continuamos con tu pedido._",
    ])
    return "\n".join(line for line in lines if line is not None)


def handle_known_customer_confirmation_if_applicable(
    *,
    contact_record: Optional[dict],
    history: list[dict],
    content: str,
) -> KnownCustomerConfirmationResult:
    """Punto de entrada del tool. Función pura (no DB) — toda la
    información viene en parámetros.

    Gates de aplicabilidad (todos deben pasar):
      1. Cliente conocido completo (consent + name + email + document +
         address con calle).
      2. Inbound contiene buying_intent (verbo + sustantivo).
      3. Idempotencia: NO se ha emitido el bloque antes en esta conv.
      4. Conversación NO ha pasado de intent inicial — sin cotización
         entregada, sin preguntas de consent/PII previas. Esto evita
         redundancia con la pre-confirmación de READY_FOR_SUMMARY o
         con preguntas LLM posteriores.
    """
    if not _is_complete_known_customer(contact_record):
        return KnownCustomerConfirmationResult(handled=False)
    if not _has_buying_intent_in_inbound(content):
        return KnownCustomerConfirmationResult(handled=False)
    if _has_already_shown_confirmation(history):
        return KnownCustomerConfirmationResult(handled=False)
    if _conversation_is_past_initial_intent(history):
        return KnownCustomerConfirmationResult(handled=False)
    text = build_confirmation_text(contact_record)
    return KnownCustomerConfirmationResult(handled=True, response_text=text)

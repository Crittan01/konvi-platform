"""FSMResolver — resolución determinística del estado conversacional.

Rev. 104 (F1-2) — extraído de orchestrator.py:
  • `_determine_transactional_state` → `determine_transactional_state`
  • `_resolve_display_state` → `resolve_display_state`

Diseño:
  • Funciones puras sobre `contact_record` + `history` + flags.
  • NO accede a DB ni LLM.
  • El caller pasa `carrier_selected_db` (DB fallback) cuando history truncado.

Reglas de transición (rev. 68 canon):
  consent → email → name → document → direction → ready_for_summary

Razón del orden:
  Wompi requiere `legal_id` + `legal_id_type` en customer_data → NEEDS_DOCUMENT
  va antes de NEEDS_DIRECTION para que checkout quede pre-poblado.

Ramas declarativas (resolve_display_state):
  • Sin buying_intent → CATALOG_MODE.
  • Buying_intent + sin shipping → NEEDS_SHIPPING_CITY.
  • Shipping cotizado + sin carrier → AWAITING_CARRIER_SELECTION.
  • Recolección PII (precede a confirmation siempre).
  • Pregunta confirmation pendiente → AWAITING_ORDER_CONFIRMATION.

Tests: `tests/test_fsm_resolver.py`.
"""
from __future__ import annotations

from typing import Optional

from . import states as S
from .address import has_real_address_data as _has_real_address_data  # alias para compat tests


def determine_transactional_state(contact: Optional[dict]) -> str:
    """Resuelve el estado de recolección PII según campos del contact.

    Orden FSM rev. 68: consent → email → name → document → direction → ready.

    NEEDS_DOCUMENT (rev. 68) se inserta entre NAME y DIRECTION para que el
    customer_data Wompi quede pre-poblado en checkout (legal_id +
    legal_id_type). Si la pasarela cambia la regla, ajustar aquí sin
    tocar el resto del FSM.
    """
    if not contact:
        return S.NEEDS_CONSENT
    if not contact.get("consent_given"):
        return S.NEEDS_CONSENT
    if not str(contact.get("email") or "").strip():
        return S.NEEDS_EMAIL
    if not str(contact.get("name") or "").strip():
        return S.NEEDS_NAME
    # Rev. 68: documento — ambos campos juntos.
    if (
        not str(contact.get("document_type") or "").strip()
        or not str(contact.get("document_number") or "").strip()
    ):
        return S.NEEDS_DOCUMENT
    if not _has_real_address_data(contact.get("address")):
        return S.NEEDS_DIRECTION
    return S.READY_FOR_SUMMARY


def resolve_display_state(
    *,
    contact_record: dict,
    buying_intent: bool,
    shipping_quoted: bool,
    carrier_selected: bool,
    order_confirm_pending: bool,
) -> str:
    """Resuelve el display_state que el caller debe usar para enrutar la conversación.

    Args:
      contact_record: contact dict (puede ser None/vacío).
      buying_intent: True si el cliente expresó intent de compra.
      shipping_quoted: True si shipping_quote_tool ya cotizó (history) O
        si hay orden DB pendiente con shipping_amount > 0 (caller debe
        agregar esa fuente de verdad — ver `_resolve_display_state` wrapper).
      carrier_selected: True si el cliente eligió carrier (history) O si
        hay orden DB pendiente con carrier persistido (idem).
      order_confirm_pending: True si último outbound fue pregunta confirmación.

    Reglas (rev. 73 — sin shortcuts por consent histórico):
      • Si NO hay buying_intent → CATALOG_MODE (modo asesoría/catálogo).
      • Si hay buying_intent pero NO shipping_quoted → NEEDS_SHIPPING_CITY.
      • Si shipping_quoted pero NO carrier_selected → AWAITING_CARRIER_SELECTION.
      • Si recolección PII pendiente (consent/email/name/document/direction) →
        retornar ese estado (NUNCA saltarlo aunque haya order_confirm_pending).
      • Si todo PII completo + order_confirm_pending → AWAITING_ORDER_CONFIRMATION.
      • Si todo PII completo y NO order_confirm_pending → READY_FOR_SUMMARY.
    """
    transaction_state = determine_transactional_state(contact_record)

    if not buying_intent:
        return S.CATALOG_MODE

    if not shipping_quoted:
        return S.NEEDS_SHIPPING_CITY

    if not carrier_selected:
        return S.AWAITING_CARRIER_SELECTION

    # Recolección PII NUNCA se salta por una pregunta de confirmación previa.
    # Wompi customer_data exige el documento; saltarlo deja el checkout sin
    # legal_id pre-poblado.
    if transaction_state in S.PII_COLLECTION_STATES:
        return transaction_state

    if order_confirm_pending:
        return S.AWAITING_ORDER_CONFIRMATION

    return transaction_state

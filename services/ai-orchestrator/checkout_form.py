"""Rev. 91 — Checkout Form Conductor (slot filling arquitectónico).

Reemplaza `[SAFETY_NET]` y `[FSM][POST] hard-lock` de orchestrator.py por
un conductor explícito que:

  1. Extrae slots determinísticamente del inbound (composition con LLM).
  2. Decide siguiente slot faltante via FSM existente
     (`_determine_transactional_state`).
  3. Devuelve prompt determinístico para ese slot.

Patrón Rasa Forms: el form está activo mientras haya slots requeridos
faltantes; cada turno extrae + valida + decide. La interfaz es fluida
(LLM redacta), la lógica de captura es rígida (Python decide).

El conductor NO persiste — la persistencia downstream (orchestrator.py
~5368-5417) ya valida y escribe a `contacts`. El conductor solo:
  • Enriquece `parsed.extracted_*` con regex hits que el LLM omitió.
  • Calcula `_sim_contact` y decide `_new_state` (igual que el código
    legacy que reemplaza).
  • Devuelve `FormResult.response_text` con el prompt determinístico
    cuando el form sigue activo.

Tests: tests/test_rev91_checkout_form_conductor.py
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import slot_extractors

logger = logging.getLogger("orchestrator.checkout_form")


_NEEDS_X_STATES = frozenset({
    "NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME",
    "NEEDS_DOCUMENT", "NEEDS_DIRECTION",
})


@dataclass
class FormResult:
    """Resultado del conductor para un turno.

    Attributes:
        active: True si el form está activo (capturando datos).
        complete: True si todos los slots requeridos están llenos
                  (form alcanzó READY_FOR_SUMMARY).
        response_text: Prompt determinístico a emitir, o None si el
                  conductor no debe override la respuesta del LLM.
        sim_contact: Estado simulado del contacto tras mergear extracciones.
        new_state: Estado FSM resultante (NEEDS_X / READY_FOR_SUMMARY).
        slots_enriched: Diccionario de slots que el conductor agregó
                  (regex extracciones que el LLM omitió). Útil para
                  logging / persistencia downstream.
    """
    active: bool
    complete: bool
    response_text: Optional[str]
    sim_contact: dict
    new_state: Optional[str]
    slots_enriched: dict


class CheckoutFormConductor:
    """Conductor único para el sub-flow de captura post-consent.

    Dependencias inyectadas (no acopladas a orchestrator imports
    porque éste importa primitivas que pueden cambiar de ubicación):
        - determine_state: callable(_sim_contact) -> str FSM state.
        - build_prompt: callable(_sim_contact) -> str prompt para el
          estado actual (canonical: _build_next_data_request_prompt).
        - build_address_prompt: callable(_sim_contact, first_name) -> str
          (canonical: _build_address_request_prompt).
        - extract_first_name: callable(name_str) -> Optional[str].
        - merge_address: callable(existing, incoming) -> dict.
        - detect_building_type: callable(text) -> Optional[str].
        - missing_address_fields: callable(address_dict) -> list[str].
    """

    def __init__(
        self,
        *,
        determine_state,
        build_prompt,
        build_address_prompt,
        extract_first_name,
        merge_address,
        detect_building_type,
        missing_address_fields,
    ):
        self._determine_state = determine_state
        self._build_prompt = build_prompt
        self._build_address_prompt = build_address_prompt
        self._extract_first_name = extract_first_name
        self._merge_address = merge_address
        self._detect_building_type = detect_building_type
        self._missing_address_fields = missing_address_fields

    # ── Punto de entrada ──────────────────────────────────────────────────

    def run(
        self,
        *,
        inbound: str,
        parsed: Any,           # OrchestratorOutput (mutado)
        contact_record: Optional[dict],
        display_state: str,
    ) -> FormResult:
        """Ejecuta un turno del form. Mutates `parsed.extracted_*`
        con extracciones determinísticas que el LLM omitió.

        Si display_state NO está en {NEEDS_X}, retorna `active=False`
        (el conductor no aplica fuera del sub-flow de captura).

        Si la respuesta del LLM ya es válida y avanza el FSM, devuelve
        `response_text=None` (no override). Si el LLM no avanzó o
        respondió vacío, devuelve `response_text=<prompt determinístico>`.
        """
        if display_state not in _NEEDS_X_STATES:
            return FormResult(
                active=False, complete=False,
                response_text=None,
                sim_contact=dict(contact_record or {}),
                new_state=None,
                slots_enriched={},
            )

        # 1. Extraer slots con regex y enriquecer parsed.extracted_*
        enriched = self._enrich_extractions(parsed, inbound)

        # 2. Construir _sim_contact con mergeo de extracciones LLM + regex
        sim_contact = self._build_sim_contact(parsed, contact_record, inbound)

        # 3. Calcular nuevo estado
        new_state = self._determine_state(sim_contact)

        # 4. Decidir si override la respuesta del LLM
        response_text = self._decide_response_text(
            inbound=inbound,
            parsed=parsed,
            sim_contact=sim_contact,
            display_state=display_state,
            new_state=new_state,
        )

        if enriched:
            logger.info(
                "[CHECKOUT_FORM] enriched=%s display_state=%s new_state=%s "
                "override=%s",
                list(enriched.keys()), display_state, new_state,
                bool(response_text),
            )

        return FormResult(
            active=True,
            complete=(new_state == "READY_FOR_SUMMARY"),
            response_text=response_text,
            sim_contact=sim_contact,
            new_state=new_state,
            slots_enriched=enriched,
        )

    # ── Pasos internos ────────────────────────────────────────────────────

    def _enrich_extractions(self, parsed: Any, inbound: str) -> dict:
        """Corre extractores regex y rellena parsed.extracted_* faltantes.

        IMPORTANTE: NUNCA sobrescribe valores que el LLM ya extrajo —
        regex es complemento, no reemplazo. Excepción: building_type,
        donde la detección textual tiene prioridad sobre la clasificación
        del LLM (el LLM tiende a errar conjunto vs casa).

        Retorna dict con los campos que el conductor agregó.
        """
        enriched: dict = {}
        regex_slots = slot_extractors.extract_all_slots(inbound)

        if regex_slots.get("email") and not getattr(parsed, "extracted_email", None):
            parsed.extracted_email = regex_slots["email"]
            enriched["email"] = regex_slots["email"]

        if regex_slots.get("name") and not getattr(parsed, "extracted_name", None):
            parsed.extracted_name = regex_slots["name"]
            enriched["name"] = regex_slots["name"]

        if (regex_slots.get("document_type") and regex_slots.get("document_number")
                and not (getattr(parsed, "extracted_document_type", None)
                         and getattr(parsed, "extracted_document_number", None))):
            parsed.extracted_document_type = regex_slots["document_type"]
            parsed.extracted_document_number = regex_slots["document_number"]
            enriched["document"] = (
                regex_slots["document_type"], regex_slots["document_number"]
            )
        else:
            # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv 099bb891):
            # Slot-filling secuencial. Si solo viene el tipo (sin número),
            # persistirlo. El prompt contextual del FSM pide solo el
            # número en el siguiente turno.
            if (regex_slots.get("document_type")
                    and not getattr(parsed, "extracted_document_type", None)):
                parsed.extracted_document_type = regex_slots["document_type"]
                enriched["document_type"] = regex_slots["document_type"]

        # Address: mergeamos con lo que el LLM ya extrajo (sin pisar valores).
        regex_addr = regex_slots.get("address") or {}
        if regex_addr:
            llm_addr = getattr(parsed, "extracted_direction", None) or {}
            if not isinstance(llm_addr, dict):
                llm_addr = {}
            address_changed = False
            for key, value in regex_addr.items():
                if value and not llm_addr.get(key):
                    llm_addr[key] = value
                    address_changed = True
            if address_changed:
                parsed.extracted_direction = llm_addr
                enriched["address"] = dict(regex_addr)

        # Building type: detector del texto tiene prioridad sobre LLM.
        # Caso S12: cliente dice "conjunto", LLM extrae como "casa".
        # Detector resuelve correctamente.
        detected_bt = self._detect_building_type(inbound or "")
        if detected_bt:
            llm_addr = getattr(parsed, "extracted_direction", None) or {}
            if not isinstance(llm_addr, dict):
                llm_addr = {}
            current_bt = (llm_addr.get("building_type") or "").strip().lower()
            if current_bt != detected_bt:
                # Override solo si difieren — log explícito.
                if current_bt:
                    logger.info(
                        "[CHECKOUT_FORM] building_type LLM=%s text=%s → usando text",
                        current_bt, detected_bt,
                    )
                llm_addr["building_type"] = detected_bt
                parsed.extracted_direction = llm_addr
                enriched["building_type"] = detected_bt

        return enriched

    def _build_sim_contact(
        self, parsed: Any, contact_record: Optional[dict], inbound: str,
    ) -> dict:
        """Replica la lógica de orchestrator.py:5074-5108 sobre el
        contact_record con las extracciones LLM ya enriquecidas."""
        sim: dict = dict(contact_record or {})

        email = getattr(parsed, "extracted_email", None)
        if email:
            sim["email"] = str(email).strip().lower()

        name = getattr(parsed, "extracted_name", None)
        if name:
            sim["name"] = " ".join(str(name).split())

        # Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv 099bb891):
        # Slot-filling secuencial para documento. ANTES: atómico (ambos o
        # ninguno). AHORA: parcial. Cliente puede dar tipo en un turno
        # ("Cédula de Ciudadanía") y número en otro ("1032414179"). El
        # FSM sigue en NEEDS_DOCUMENT hasta que ambos estén; el prompt
        # contextual del orchestrator pide solo lo que falta.
        doc_t = getattr(parsed, "extracted_document_type", None)
        doc_n = getattr(parsed, "extracted_document_number", None)
        if doc_t:
            doc_t_norm = str(doc_t).strip().upper()
            if doc_t_norm in {"CC", "CE", "NIT", "PP", "TI", "OTHER"}:
                sim["document_type"] = doc_t_norm
        if doc_n:
            doc_n_norm = re.sub(r"[\s.]", "", str(doc_n).strip())
            if doc_n_norm:
                sim["document_number"] = doc_n_norm

        # Auto-asignación de número cuando tipo ya está y cliente responde
        # solo dígitos. Conservador: requiere que sim ya tenga document_type
        # (persistido en turno previo) Y inbound sea EXCLUSIVAMENTE dígitos
        # válidos (6-12 chars). Evita interpretar dígitos en otro contexto
        # (ej. ciudad numérica, teléfonos) como documento. El guard
        # contextual lo provee el conductor — solo invoca enrich cuando
        # display_state ∈ NEEDS_X (incluye NEEDS_DOCUMENT).
        if sim.get("document_type") and not sim.get("document_number"):
            inbound_digits = re.sub(r"[\s.]", "", inbound or "")
            if inbound_digits.isdigit() and 6 <= len(inbound_digits) <= 12:
                sim["document_number"] = inbound_digits

        addr = getattr(parsed, "extracted_direction", None)
        if isinstance(addr, dict) and any(v for v in addr.values() if v):
            sim["address"] = self._merge_address(sim.get("address"), addr)

        # Rev. 103 — phone alternativo de envío (separado de contacts.phone).
        # NO sobrescribe sim["phone"] (que es el WhatsApp invariante);
        # persiste como sim["shipping_phone"] formato +E.164 Colombia.
        ship_phone = getattr(parsed, "extracted_shipping_phone", None)
        if ship_phone:
            digits = re.sub(r"\D", "", str(ship_phone))
            if len(digits) >= 10 and digits[-10] != "0":
                sim["shipping_phone"] = f"+57{digits[-10:]}"

        # Consent: si el inbound es claro "sí" tras una pregunta de consent,
        # el flujo orchestrator superior ya marca consent_given=True ANTES
        # de llegar al conductor. No tocamos consent aquí (separation of
        # concerns).

        return sim

    def _decide_response_text(
        self,
        *,
        inbound: str,
        parsed: Any,
        sim_contact: dict,
        display_state: str,
        new_state: str,
    ) -> Optional[str]:
        """Decide cuándo override la respuesta del LLM.

        Reglas (en orden):
          1. Si LLM respondió vacío y seguimos en NEEDS_X → forzar prompt
             del estado actual (heredado de SAFETY_NET).
          2. Si LLM respondió pero seguimos en el mismo NEEDS_X (no
             avanzó), forzar prompt determinístico (heredado de FSM POST).
          3. Si new_state == NEEDS_DIRECTION (o seguimos en él), construir
             prompt de address con campos faltantes.
          4. Si new_state == READY_FOR_SUMMARY tras avance real, NO
             override aquí — el orchestrator tiene su propio path para
             generar el resumen determinístico desde el cart-as-SoT.
        """
        response_text = getattr(parsed, "response_text", None) or ""
        is_empty = not response_text.strip()

        # Caso 4: avance a READY_FOR_SUMMARY → no override (delega al
        # builder de resumen del orchestrator).
        if new_state == "READY_FOR_SUMMARY" and display_state in _NEEDS_X_STATES:
            return None

        # Caso 1 + 2: vacío o mismo estado → forzar prompt determinístico.
        same_state = (new_state == display_state)
        if is_empty or same_state:
            # Caso 3: NEEDS_DIRECTION usa builder específico (campos
            # faltantes detallados).
            if new_state == "NEEDS_DIRECTION":
                first_name = self._extract_first_name(sim_contact.get("name"))
                return self._build_address_prompt(sim_contact, first_name)
            # Otros NEEDS_X: prompt genérico del estado.
            return self._build_prompt(sim_contact)

        # LLM avanzó FSM y respondió no-vacío → respetar respuesta LLM.
        return None

"""Address validation — reglas Wompi/Envía para FSM (rev. 104, F1-2 · simplificado Sem 7 F2 cierre 2026-05-19).

Decisión arquitectónica founder 2026-05-19 (Opción 1 SIMPLIFY):
`building_type` con 4 escenarios reales del usuario colombiano, sin
`delivery_context` ortogonal.

Reglas alineadas al formulario Contactos (Wompi/Envía):
  • street: obligatorio.
  • city: obligatorio.
  • building_type: obligatorio (casa | edificio | conjunto | oficina).
  • conjunto_type ∈ {torres, casas} — obligatorio si building_type='conjunto'.
  • apartment: obligatorio si building_type ∈ {edificio, conjunto, oficina}.
    En 'oficina' es el número de oficina; en 'conjunto casas' es el número
    de casa (alias semántico).
  • tower: obligatorio si building_type='conjunto' AND conjunto_type='torres'.
  • floor: SIEMPRE opcional (metadata útil para edificio y oficina,
    no obligatorio).
  • company_name: SIEMPRE opcional (informativo, oficina solo).

Sin estos campos obligatorios, el bot NO puede declarar la dirección
"lista para envío" y el FSM debe quedarse en NEEDS_DIRECTION.
"""
from __future__ import annotations

import unicodedata as _ud
from typing import Optional


def _normalize_text_simple(text: str) -> str:
    """Lowercase + sin acentos + strip (replica orchestrator legacy)."""
    if not text:
        return ""
    nfkd = _ud.normalize("NFKD", str(text).lower())
    return "".join(c for c in nfkd if not _ud.combining(c)).strip()


def normalize_building_type(value: Optional[str]) -> str:
    """Normaliza variantes coloquiales a uno de {casa, edificio, conjunto, oficina}.

    Vacío si el valor no encaja en ningún canon — caller debe pedir clarificación.
    """
    normalized = _normalize_text_simple(str(value or ""))
    if normalized in {"casa", "hogar", "residencia"}:
        return "casa"
    if normalized in {"edificio", "apartamento", "apto"}:
        return "edificio"
    if normalized in {"conjunto", "unidad", "unidad residencial"}:
        return "conjunto"
    if normalized in {"oficina", "trabajo", "empresa", "laboral", "negocio"}:
        return "oficina"
    return ""


def normalize_conjunto_type(value: Optional[str]) -> str:
    """Normaliza el sub-tipo de conjunto a uno de {torres, casas}.

    Vacío si no encaja — caller debe pedir clarificación cuando
    building_type='conjunto'.
    """
    normalized = _normalize_text_simple(str(value or ""))
    if normalized in {"torres", "torre", "bloques", "bloque", "edificios"}:
        return "torres"
    if normalized in {"casas", "casa"}:
        return "casas"
    return ""


def missing_address_fields(direction: Optional[dict]) -> list[str]:
    """Lista de campos faltantes para que `address` quede lista para envío.

    Devuelve descripciones legibles ("Calle y número", "Ciudad", etc.) para
    que el bot las pueda usar directamente al pedirlas al cliente.

    `conjunto_type` SÍ es obligatorio cuando building_type='conjunto' — sin él
    no se sabe si pedir torre/apto o solo casa#.

    Sem 7 F2 cierre 2026-05-20 — P6 founder UAT (acuerdo opción C):
    `neighborhood` SÍ es obligatorio en residencial (casa/edificio/conjunto)
    porque transportadoras CO lo usan para sub-zonificar tarifa+ETA. En
    OFICINA no aplica naturalmente — opcional. Sincronizado con
    `services/api/dependencies/contact_validators.py::address_required_fields`.
    """
    address = direction if isinstance(direction, dict) else {}
    street = str(address.get("street") or "").strip()
    city = str(address.get("city") or "").strip()
    neighborhood = str(address.get("neighborhood") or "").strip()
    building_type = normalize_building_type(address.get("building_type"))
    conjunto_type = normalize_conjunto_type(address.get("conjunto_type"))
    tower = str(address.get("tower") or "").strip()
    apartment = str(address.get("apartment") or "").strip()

    missing: list[str] = []
    if not street:
        missing.append("Calle y número")
    if not city:
        missing.append("Ciudad")
    # Barrio: obligatorio en residencial (casa/edificio/conjunto), opcional
    # en oficina y cuando aún no se sabe el building_type (se exige
    # condicionalmente más abajo según el tipo declarado).
    if not building_type:
        missing.append("Tipo de vivienda (casa, edificio, conjunto u oficina)")
        # Sin building_type, no podemos saber si neighborhood es obligatorio.
        # Lo pediremos en el siguiente turno cuando el cliente declare tipo.
    elif building_type == "edificio":
        if not neighborhood:
            missing.append("Barrio")
        if not apartment:
            missing.append("Apartamento")
    elif building_type == "oficina":
        # Sin barrio obligatorio (P6 opción C).
        if not apartment:
            missing.append("Número de oficina")
    elif building_type == "conjunto":
        if not neighborhood:
            missing.append("Barrio")
        if not conjunto_type:
            missing.append("Tipo de conjunto (torres o casas)")
        elif conjunto_type == "torres":
            if not tower:
                missing.append("Torre")
            if not apartment:
                missing.append("Apartamento")
        elif conjunto_type == "casas":
            if not apartment:
                missing.append("Número de casa")
    elif building_type == "casa":
        if not neighborhood:
            missing.append("Barrio")
    return missing


def has_real_address_data(direction: Optional[dict]) -> bool:
    """True si la dirección tiene TODOS los campos obligatorios (sin missing)."""
    return len(missing_address_fields(direction)) == 0

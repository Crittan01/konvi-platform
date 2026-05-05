"""Address validation — reglas Wompi/Envía para FSM (rev. 104, F1-2).

Extraído de orchestrator.py:
  • `_normalize_building_type` → `normalize_building_type`
  • `_missing_address_fields` → `missing_address_fields`
  • `_has_real_address_data` → `has_real_address_data`

Reglas alineadas al formulario Contactos (Wompi/Envía):
  • street: obligatorio.
  • city: obligatorio.
  • building_type: obligatorio (casa | edificio | conjunto).
  • apartment: obligatorio si building_type ∈ {edificio, conjunto}.
  • tower: obligatorio si building_type = conjunto.

Sin estos campos, el bot NO puede declarar la dirección "lista para envío"
y el FSM debe quedarse en NEEDS_DIRECTION.
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
    """Normaliza variantes coloquiales a uno de {casa, edificio, conjunto}.

    Vacío si el valor no encaja en ningún canon — caller debe pedir clarificación.
    """
    normalized = _normalize_text_simple(str(value or ""))
    if normalized in {"casa", "hogar", "residencia"}:
        return "casa"
    if normalized in {"edificio", "apartamento", "apto"}:
        return "edificio"
    if normalized in {"conjunto", "unidad", "unidad residencial"}:
        return "conjunto"
    return ""


def missing_address_fields(direction: Optional[dict]) -> list[str]:
    """Lista de campos faltantes para que `address` quede lista para envío.

    Devuelve descripciones legibles ("Calle y número", "Ciudad", etc.) para
    que el bot las pueda usar directamente al pedirlas al cliente.
    """
    address = direction if isinstance(direction, dict) else {}
    street = str(address.get("street") or "").strip()
    city = str(address.get("city") or "").strip()
    building_type = normalize_building_type(address.get("building_type"))
    tower = str(address.get("tower") or "").strip()
    apartment = str(address.get("apartment") or "").strip()

    missing: list[str] = []
    if not street:
        missing.append("Calle y número")
    if not city:
        missing.append("Ciudad")
    if not building_type:
        missing.append("Tipo de vivienda (casa, edificio o conjunto)")
    elif building_type == "edificio" and not apartment:
        missing.append("Apartamento")
    elif building_type == "conjunto":
        if not tower:
            missing.append("Torre")
        if not apartment:
            missing.append("Apartamento")
    return missing


def has_real_address_data(direction: Optional[dict]) -> bool:
    """True si la dirección tiene TODOS los campos obligatorios (sin missing)."""
    return len(missing_address_fields(direction)) == 0

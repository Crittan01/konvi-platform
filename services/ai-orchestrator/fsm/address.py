"""Address validation — reglas Wompi/Envía para FSM (rev. 104, F1-2 · ampliado Sem 7 F2 cierre 2026-05-19).

Extraído de orchestrator.py:
  • `_normalize_building_type` → `normalize_building_type`
  • `_missing_address_fields` → `missing_address_fields`
  • `_has_real_address_data` → `has_real_address_data`

Reglas alineadas al formulario Contactos (Wompi/Envía):
  • street: obligatorio.
  • city: obligatorio.
  • building_type: obligatorio (casa | edificio | conjunto).
  • conjunto_type ∈ {torres, casas} — obligatorio si building_type='conjunto'.
  • apartment: obligatorio si building_type ∈ {edificio, conjunto}.
  • tower: obligatorio si building_type='conjunto' AND conjunto_type='torres'.
  • delivery_context ∈ {residencia, oficina, otro} — opcional, default 'residencia'
    (metadata informativa, no obligatorio para envío).

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


def normalize_delivery_context(value: Optional[str]) -> str:
    """Normaliza el contexto de entrega a uno de {residencia, oficina, otro}.

    Vacío si no encaja — caller puede asumir 'residencia' como default.
    """
    normalized = _normalize_text_simple(str(value or ""))
    if normalized in {"residencia", "casa", "hogar", "vivienda"}:
        return "residencia"
    if normalized in {"oficina", "trabajo", "empresa", "laboral", "negocio"}:
        return "oficina"
    if normalized in {"otro", "otra"}:
        return "otro"
    return ""


def missing_address_fields(direction: Optional[dict]) -> list[str]:
    """Lista de campos faltantes para que `address` quede lista para envío.

    Devuelve descripciones legibles ("Calle y número", "Ciudad", etc.) para
    que el bot las pueda usar directamente al pedirlas al cliente.

    `delivery_context` NO es obligatorio (default 'residencia' si ausente).
    `conjunto_type` SÍ es obligatorio cuando building_type='conjunto' — sin él
    no se sabe si pedir torre/apto o solo casa#.
    """
    address = direction if isinstance(direction, dict) else {}
    street = str(address.get("street") or "").strip()
    city = str(address.get("city") or "").strip()
    building_type = normalize_building_type(address.get("building_type"))
    conjunto_type = normalize_conjunto_type(address.get("conjunto_type"))
    tower = str(address.get("tower") or "").strip()
    apartment = str(address.get("apartment") or "").strip()

    missing: list[str] = []
    if not street:
        missing.append("Calle y número")
    if not city:
        missing.append("Ciudad")
    if not building_type:
        missing.append("Tipo de vivienda (casa, edificio, conjunto u oficina)")
    elif building_type == "edificio" and not apartment:
        missing.append("Apartamento")
    elif building_type == "conjunto":
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
    return missing


def has_real_address_data(direction: Optional[dict]) -> bool:
    """True si la dirección tiene TODOS los campos obligatorios (sin missing)."""
    return len(missing_address_fields(direction)) == 0

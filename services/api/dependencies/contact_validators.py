"""Validators de datos de contacto — rev. 68.

Reglas alineadas con Wompi `customer_data.legal_id_type` (Colombia) y con la
estructura canónica de address documentada en migración 20260429000000.

No dependen de Supabase ni FastAPI — funciones puras para reutilizar en
backend (Pydantic validators, endpoints, orchestrator) y testing.
"""
from __future__ import annotations

from typing import Optional


# Tipos de documento aceptados por Wompi para Colombia.
# DNI no aplica (es Argentina/España); RG es Brasil. Para CO usamos solo:
DOCUMENT_TYPES_CO = frozenset({"CC", "CE", "NIT", "PP", "TI", "OTHER"})


# Reglas de longitud por tipo (Colombia, conservadoras).
# CC: 6-12 dígitos. CE: 4-7 dígitos.
# NIT: 9-11 (sin DV) o con DV "9.999.999.999-1".
# PP: alfanumérico 6-15.
# TI: 8-11 dígitos.
# OTHER: 3-30 caracteres alfanuméricos.
DOC_LEN_RULES = {
    "CC":    {"min": 6,  "max": 12, "digits_only": True},
    "CE":    {"min": 4,  "max": 8,  "digits_only": True},
    "NIT":   {"min": 9,  "max": 13, "digits_only": False},  # admite "-1" del DV
    "PP":    {"min": 6,  "max": 15, "digits_only": False},
    "TI":    {"min": 8,  "max": 11, "digits_only": True},
    "OTHER": {"min": 3,  "max": 30, "digits_only": False},
}


def normalize_document_number(raw: Optional[str]) -> Optional[str]:
    """Limpia separadores comunes (puntos, espacios). Mantiene el guión del DV en NIT."""
    if not raw:
        return None
    cleaned = raw.replace(".", "").replace(" ", "").strip()
    return cleaned or None


def _calculate_nit_dv(number_without_dv: str) -> int:
    """Calcula dígito verificador de un NIT colombiano (módulo-11 oficial DIAN).

    Pesos oficiales DIAN para 1-15 posiciones (de derecha a izquierda).
    Algoritmo:
      sum = sum(digit_i * weight_i) para cada dígito de derecha a izquierda
      mod = sum % 11
      DV = mod si mod < 2, sino 11 - mod

    Lanza ValueError si number_without_dv no es solo dígitos.
    """
    if not number_without_dv.isdigit():
        raise ValueError("NIT base debe ser solo dígitos para calcular DV")
    weights = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]
    digits_reversed = list(map(int, reversed(number_without_dv)))
    if len(digits_reversed) > len(weights):
        raise ValueError(f"NIT excede longitud máxima ({len(weights)} dígitos sin DV)")
    total = sum(d * w for d, w in zip(digits_reversed, weights))
    mod = total % 11
    return mod if mod < 2 else 11 - mod


def validate_document(doc_type: Optional[str], doc_number: Optional[str]) -> Optional[str]:
    """Valida tipo + número de documento. Retorna mensaje de error o None si OK.

    - Si ambos None → OK (campos opcionales hasta que el bot los pida).
    - Si uno es None y el otro no → error (deben ir juntos).
    - Tipo debe estar en DOCUMENT_TYPES_CO.
    - Número debe pasar reglas de longitud / formato según tipo.
    - Para NIT: si trae '-X' al final, validar que X sea el DV correcto (módulo-11).
      Si NO trae DV, aceptar (lenient — Wompi acepta NIT sin DV).
    """
    if doc_type is None and doc_number is None:
        return None
    if doc_type is None or doc_number is None:
        return "document_type y document_number deben ir juntos (ambos o ninguno)."

    if doc_type not in DOCUMENT_TYPES_CO:
        return f"document_type inválido. Valores aceptados: {sorted(DOCUMENT_TYPES_CO)}."

    cleaned = normalize_document_number(doc_number)
    if not cleaned:
        return "document_number no puede estar vacío."

    rules = DOC_LEN_RULES[doc_type]
    if rules["digits_only"] and not cleaned.isdigit():
        return f"document_number para {doc_type} debe ser solo dígitos."
    # NIT puede traer "-1" al final como dígito verificador opcional.
    length_check = cleaned.replace("-", "")
    if not (rules["min"] <= len(length_check) <= rules["max"]):
        return (
            f"document_number para {doc_type} debe tener entre "
            f"{rules['min']} y {rules['max']} caracteres ({len(length_check)} provisto)."
        )

    # Rev. 69 — validación DV NIT (módulo-11 oficial DIAN).
    if doc_type == "NIT" and "-" in cleaned:
        try:
            base, dv_str = cleaned.rsplit("-", 1)
            if not base.isdigit() or not dv_str.isdigit() or len(dv_str) != 1:
                return "NIT con DV inválido. Formato esperado: '123456789-0'."
            expected_dv = _calculate_nit_dv(base)
            if int(dv_str) != expected_dv:
                return (
                    f"DV del NIT incorrecto. Para {base} el DV correcto es {expected_dv} "
                    f"(provisto: {dv_str}). Verifica el número."
                )
        except ValueError as exc:
            return f"NIT inválido: {exc}"
    return None


# ── Address structured (rev. 68) ────────────────────────────────────────────

BUILDING_TYPES = frozenset({"casa", "edificio", "conjunto"})


def address_required_fields(building_type: Optional[str]) -> list[str]:
    """Campos requeridos según building_type.

    Casa: street, neighborhood, city, state, dane_code.
    Edificio: + apartment.
    Conjunto: + tower, apartment.
    """
    base = ["street", "neighborhood", "city", "state", "dane_code"]
    if building_type == "edificio":
        return base + ["apartment"]
    if building_type == "conjunto":
        return base + ["tower", "apartment"]
    return base  # casa o no especificado


def is_address_complete(address: Optional[dict]) -> tuple[bool, list[str]]:
    """Retorna (completa, faltantes). Si address es None o vacío → False, lista total."""
    if not address:
        return False, address_required_fields("casa")
    bt = (address.get("building_type") or "").strip().lower() or None
    if bt and bt not in BUILDING_TYPES:
        return False, [f"building_type inválido (debe ser uno de {sorted(BUILDING_TYPES)})"]
    required = address_required_fields(bt)
    missing = [f for f in required if not (address.get(f) or "").strip()]
    return (not missing), missing

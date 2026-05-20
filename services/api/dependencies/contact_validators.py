"""Validators de datos de contacto — rev. 68.

Reglas alineadas con Wompi `customer_data.legal_id_type` (Colombia) y con la
estructura canónica de address documentada en migración 20260429000000.

No dependen de Supabase ni FastAPI — funciones puras para reutilizar en
backend (Pydantic validators, endpoints, orchestrator) y testing.
"""
from __future__ import annotations

from typing import Optional


# Tipos de documento aceptados por Wompi para Colombia.
# DNI no aplica (es Argentina/España); RG es Brasil.
#
# Rev. 102 — TI (Tarjeta de Identidad) removido: corresponde a menores
# de edad. Decreto 1377/2013 Art. 7 prohíbe el tratamiento de datos de
# menores sin autorización del representante legal — flujo no soportado
# por el sistema (F8 backlog si se requiere).
DOCUMENT_TYPES_CO = frozenset({"CC", "CE", "NIT", "PP", "OTHER"})


# Reglas de longitud por tipo — rangos estrictos a realidad colombiana
# (rev. 102 — antes eran laxos):
#   CC  6-10 dígitos (cédula CO máx. 10)
#   CE  6-7 dígitos (Migración Colombia)
#   NIT 9-11 chars (9 dígitos + DV opcional con guion)
#   PP  6-15 alfanumérico (cubre extranjeros)
#   OTHER 3-30 alfanumérico
DOC_LEN_RULES = {
    "CC":    {"min": 6,  "max": 10, "digits_only": True},
    "CE":    {"min": 6,  "max": 7,  "digits_only": True},
    "NIT":   {"min": 9,  "max": 11, "digits_only": False},  # admite "-DV"
    "PP":    {"min": 6,  "max": 15, "digits_only": False},
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


# ── Address structured (rev. 68 · simplificado Sem 7 F2 cierre 2026-05-19) ──
#
# Decisión arquitectónica founder 2026-05-19 (Opción 1 SIMPLIFY): eliminar
# `delivery_context` ortogonal. Era confuso al usuario tener 2 ejes
# (building_type + delivery_context). Mejor un solo eje con 4 escenarios
# reales del usuario colombiano:
#
#   building_type ∈ {casa, edificio, conjunto, oficina}
#
#   - casa: street + city + barrio.
#   - edificio: + apartment (+ floor opcional).
#   - conjunto: + conjunto_type ∈ {torres, casas}:
#       - torres: tower + apartment.
#       - casas: apartment (alias semántico "casa #X").
#   - oficina: + apartment (= oficina #) + floor opcional + company_name opcional.
#
# Floor es opcional en TODO caso. Si el cliente lo da, mejora el render.

BUILDING_TYPES = frozenset({"casa", "edificio", "conjunto", "oficina"})
CONJUNTO_TYPES = frozenset({"torres", "casas"})


def address_required_fields(
    building_type: Optional[str],
    conjunto_type: Optional[str] = None,
) -> list[str]:
    """Campos requeridos según building_type + conjunto_type.

    Casa: street, neighborhood, city, state, dane_code.
    Edificio: + apartment.
    Conjunto torres (default si conjunto_type ausente): + tower, apartment.
    Conjunto casas: + apartment (alias "casa #X" — sin torre).
    Oficina: + apartment (= oficina #). NO exige neighborhood.

    Sem 7 F2 cierre 2026-05-20 — P6 founder UAT (acuerdo opción C):
    `neighborhood` es OBLIGATORIO en residencial (casa/edificio/conjunto)
    porque las transportadoras CO (Coordinadora, Servientrega) lo usan
    para sub-zonificar tarifa + ETA. En OFICINA (edificio empresarial
    en zona céntrica) el barrio no aplica naturalmente — opcional.

    `floor` y `company_name` son SIEMPRE opcionales — no entran en required.
    """
    base_residencial = ["street", "neighborhood", "city", "state", "dane_code"]
    base_oficina = ["street", "city", "state", "dane_code"]  # sin neighborhood
    if building_type == "oficina":
        return base_oficina + ["apartment"]
    if building_type == "edificio":
        return base_residencial + ["apartment"]
    if building_type == "conjunto":
        if conjunto_type == "casas":
            return base_residencial + ["apartment"]
        # Default + 'torres': comportamiento legacy (back-compat).
        return base_residencial + ["tower", "apartment"]
    return base_residencial  # casa o no especificado


def is_address_complete(address: Optional[dict]) -> tuple[bool, list[str]]:
    """Retorna (completa, faltantes). Si address es None o vacío → False, lista total.

    `floor` y `company_name` NO son obligatorios — son metadata informativa.
    """
    if not address:
        return False, address_required_fields("casa")
    bt = (address.get("building_type") or "").strip().lower() or None
    if bt and bt not in BUILDING_TYPES:
        return False, [f"building_type inválido (debe ser uno de {sorted(BUILDING_TYPES)})"]
    ct = (address.get("conjunto_type") or "").strip().lower() or None
    if ct and ct not in CONJUNTO_TYPES:
        return False, [f"conjunto_type inválido (debe ser uno de {sorted(CONJUNTO_TYPES)})"]
    required = address_required_fields(bt, ct)
    missing = [f for f in required if not (address.get(f) or "").strip()]
    return (not missing), missing

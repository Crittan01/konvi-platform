"""Consent gates — Habeas Data Ley 1581 (revocación, acceso, rectificación, menores).

Rev. 104 (F1-1 batch 4) — extraído de orchestrator.py.

Cobertura del titular sobre sus datos:
  • **Revocación** (Art. 9): "elimina mis datos", "revoco consentimiento" →
    bot anonimiza + audit log event='revoked'.
  • **Acceso** (Art. 14): "envía mis datos", "habeas data" → bot exporta
    datos al titular con audit log.
  • **Rectificación** (Art. 16): "corregir mis datos", "actualiza email" →
    bot registra solicitud + notifica al tenant para validar.
  • **Menor de edad** (Decreto 1377 Art. 7): "soy menor", "tengo 16 años" →
    bot escala a humano sin recolectar datos.

Orden de precedencia (cuando un mensaje activa múltiples):
  revocación > rectificación > export

(`revocación` siempre dominante por riesgo. `rectificación` precede a
`export` porque "habeas data" es genérico — la frase específica gana.)

Public API:
  • `detect_revocation_intent(text) -> bool`
  • `detect_data_export_intent(text) -> bool`
  • `detect_rectification_intent(text) -> bool`
  • `detect_minor_intent(text) -> bool`
  • Constantes: `REVOCATION_TOKENS`, `DATA_EXPORT_TOKENS`,
    `RECTIFICATION_TOKENS`, `MINOR_EXPLICIT_PHRASES`.

Tests: `tests/test_safety_consent_gates.py`.
"""
from __future__ import annotations

import re
import unicodedata as _ud


# ─── Revocación (Ley 1581 Art. 9) ────────────────────────────────────────────

REVOCATION_TOKENS: frozenset[str] = frozenset({
    # Variantes "X mis datos"
    "eliminar mis datos", "elimina mis datos",
    "borrar mis datos", "borra mis datos",
    # Variantes "X todos mis datos"
    "eliminar todos mis datos", "elimina todos mis datos",
    "borrar todos mis datos", "borra todos mis datos",
    # Variantes "X toda mi informacion"
    "eliminar mi informacion", "elimina mi informacion",
    "eliminar toda mi informacion", "elimina toda mi informacion",
    "borrar mi informacion", "borra mi informacion",
    "borrar toda mi informacion", "borra toda mi informacion",
    # Otros fraseos naturales
    "quiero ser eliminado", "no guardes mis datos",
    "no quieras guardar mis datos", "no quiero que guardes",
    "quiero borrar mis datos", "quiero eliminar mis datos",
    "olvida mis datos", "olvida toda mi info",
    # Habeas Data formal
    "revoco el consentimiento", "revoco mi consentimiento",
    "retiro el consentimiento",
})


# ─── Acceso / portabilidad (Art. 14, 19) ─────────────────────────────────────

DATA_EXPORT_TOKENS: frozenset[str] = frozenset({
    # "Mis datos" — pedido directo
    "envia mis datos", "enviame mis datos", "enviar mis datos",
    "manda mis datos", "mandame mis datos", "mandar mis datos",
    "quiero mis datos", "necesito mis datos",
    "dame mis datos", "comparte mis datos",
    # "Mi informacion"
    "envia mi informacion", "enviame mi informacion",
    "manda mi informacion", "mandame mi informacion",
    "quiero mi informacion", "dame mi informacion",
    "comparte mi informacion",
    # "Que tienen sobre mi" — consulta natural
    "que tienen sobre mi", "que datos tienen sobre mi",
    "que informacion tienen sobre mi", "que tienen de mi",
    "que datos guardan sobre mi", "que informacion guardan sobre mi",
    "que datos tienen mios", "que informacion tienen mia",
    # Habeas Data formal (Art. 14)
    "habeas data", "derecho de acceso", "ejercer habeas data",
    "solicito mis datos", "acceso a mis datos personales",
    # Portabilidad (Art. 19)
    "portabilidad de datos", "exportar mis datos",
})


# ─── Rectificación (Art. 16) ────────────────────────────────────────────────

RECTIFICATION_TOKENS: frozenset[str] = frozenset({
    # "Corregir / actualizar mi X"
    "corregir mis datos", "corrige mis datos",
    "actualizar mis datos", "actualiza mis datos",
    "modificar mis datos", "modifica mis datos",
    "rectificar mis datos", "rectifica mis datos",
    # Variantes con campos específicos
    "actualizar mi email", "actualiza mi email",
    "actualizar mi correo", "actualiza mi correo",
    "actualizar mi direccion", "actualiza mi direccion",
    "actualizar mi telefono", "actualiza mi telefono",
    "cambiar mis datos", "cambia mis datos",
    # Ley 1581 formal
    "ejercer rectificacion", "derecho de rectificacion",
    "solicito rectificacion", "rectificacion habeas data",
    # Errores en datos
    "tienen mal mis datos", "estan mal mis datos",
    "mis datos estan incorrectos", "mis datos no son correctos",
})


# ─── Menor de edad (Decreto 1377 Art. 7) ─────────────────────────────────────

MINOR_EXPLICIT_PHRASES: tuple[str, ...] = (
    "soy menor de edad", "soy menor", "soy menor de 18",
    "no tengo mayoria de edad", "no soy mayor de edad",
    "soy un nino", "soy una nina", "soy un menor",
    "estoy en colegio", "estoy en bachillerato",
    "mi mama me dijo", "mi papa me dijo",
    "tengo permiso de mis padres", "tengo permiso de mi mama",
    "tengo permiso de mi papa",
)

# Regex: captura "tengo N años" / "ya tengo N" / "N años de edad" / etc.
_AGE_REGEX = re.compile(
    r"\b(?:tengo|tengo casi|tengo apenas|cumpli|ya tengo)?\s*"
    r"(\d{1,2})\s*(?:años|anos|añitos|anitos|year|years)\b",
    re.IGNORECASE,
)


# ─── Helper interno ──────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase + sin acentos (replica `_normalize_text_simple` legacy)."""
    if not text:
        return ""
    nfkd = _ud.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not _ud.combining(c)).strip()


# ─── Public detectors ────────────────────────────────────────────────────────

def detect_revocation_intent(text: str) -> bool:
    """True si el mensaje es una solicitud de eliminación de datos (Art. 9)."""
    normalized = _normalize(text)
    return any(token in normalized for token in REVOCATION_TOKENS)


def detect_data_export_intent(text: str) -> bool:
    """True si el titular solicita ejercer derecho Art. 14 (acceso).

    Excluye si hay tokens de revocación o rectificación (más específicos).
    La frase "habeas data" sola es genérica y los detectores específicos ganan.
    """
    if not text:
        return False
    normalized = _normalize(text)
    if any(rev in normalized for rev in REVOCATION_TOKENS):
        return False
    if any(rec in normalized for rec in RECTIFICATION_TOKENS):
        return False
    return any(token in normalized for token in DATA_EXPORT_TOKENS)


def detect_rectification_intent(text: str) -> bool:
    """True si el titular solicita corrección de datos (Art. 16).

    Orden de precedencia: revocación > rectificación > export.
    Si hay token de rectificación, gana incluso si también hay token de export.
    """
    if not text:
        return False
    normalized = _normalize(text)
    if any(rev in normalized for rev in REVOCATION_TOKENS):
        return False
    if any(token in normalized for token in RECTIFICATION_TOKENS):
        return True
    return False


def detect_minor_intent(text: str) -> bool:
    """True si el cliente declara/sugiere ser menor de edad.

    Habeas Data Decreto 1377/2013 Art. 7. Conservador: prefiere falso
    positivo (escalar a humano) sobre falso negativo (tratar datos de
    menor sin autorización).
    """
    if not text:
        return False
    normalized = _normalize(text)
    if any(p in normalized for p in MINOR_EXPLICIT_PHRASES):
        return True
    for match in _AGE_REGEX.finditer(normalized):
        try:
            age = int(match.group(1))
        except (ValueError, IndexError):
            continue
        if 1 <= age < 18:
            return True
    return False
